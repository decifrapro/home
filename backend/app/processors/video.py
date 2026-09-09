"""Vídeos: o áudio é transcrito e alguns quadros são descritos.

O MP4 inteiro nunca é enviado cegamente para um modelo. Componentes separados,
com teto de frames, para não gastar dinheiro em dezenas de quadros iguais.
"""

from __future__ import annotations

import logging

from app.models.schemas import Event, EventType, ProcessingStatus
from app.processors.base import BudgetExceeded, MediaProcessor, ProcessingContext, ProcessingOutcome
from app.providers.base import ProviderError
from app.services.cost import (
    VISION_INPUT_TOKENS_PER_IMAGE,
    VISION_OUTPUT_TOKENS_PER_IMAGE,
    transcription_cost,
    vision_call_cost,
)
from app.services.media import (
    MediaToolError,
    estimar_duracao_do_video,
    extract_audio_track,
    extract_frames,
    probe,
)
from app.services.media import (
    disponivel as ffmpeg_disponivel,
)

logger = logging.getLogger(__name__)


# Contêineres que a transcrição aceita direto, sem conversão. O MP4 do WhatsApp
# está nessa lista — é o que permite ouvir o vídeo mesmo sem FFmpeg.
CONTEINERES_ACEITOS = {".mp4", ".m4a", ".mpeg", ".mpga", ".webm"}


class VideoProcessor(MediaProcessor):
    category = "video"
    handles = (EventType.VIDEO,)

    async def _so_a_fala(
        self, event: Event, path, context: ProcessingContext
    ) -> ProcessingOutcome:
        """Sem FFmpeg: o que falaram no vídeo ainda pode ser recuperado.

        O arquivo vai inteiro para a transcrição, que aceita MP4 sem conversão.
        A parte visual continua fora — por isso o item não é dado como
        decifrado, e a cobertura continua dizendo a verdade.
        """
        settings = context.settings
        tamanho_mb = path.stat().st_size / (1024 * 1024)
        sufixo = path.suffix.lower()

        if sufixo not in CONTEINERES_ACEITOS or tamanho_mb > settings.audio_max_upload_mb:
            motivo = (
                f"Vídeo de {tamanho_mb:.0f} MB: acima do limite de "
                f"{settings.audio_max_upload_mb} MB desta instalação, que roda sem FFmpeg "
                "e não divide arquivos."
                if sufixo in CONTEINERES_ACEITOS
                else (
                    f"Vídeo em {sufixo or 'formato desconhecido'}: esta instalação roda sem "
                    "FFmpeg e só consegue ouvir os formatos que a transcrição aceita direto."
                )
            )
            return ProcessingOutcome(
                status=ProcessingStatus.UNSUPPORTED,
                error=f"{motivo} O arquivo continua na conversa, na posição certa.",
                metadata={"reason": "sem_ffmpeg", "size_mb": round(tamanho_mb, 1)},
                category=self.category,
            )

        duracao = estimar_duracao_do_video(path.stat().st_size)
        try:
            context.budget.check(transcription_cost(settings, duracao))
            resultado = await context.provider.transcribe(
                path, hint=context.conversation_hint, mime="audio/mp4"
            )
        except BudgetExceeded:
            raise
        except ProviderError as exc:
            return ProcessingOutcome(
                status=ProcessingStatus.UNSUPPORTED,
                error=(
                    f"Não consegui transcrever o áudio deste vídeo: {exc}. Esta instalação "
                    "roda sem FFmpeg, então também não há descrição visual."
                ),
                metadata={"reason": "sem_ffmpeg"},
                category=self.category,
            )

        gasto = transcription_cost(settings, duracao)
        context.budget.spend(gasto)
        fala = resultado.text.strip()
        return ProcessingOutcome(
            status=ProcessingStatus.UNSUPPORTED,
            text=fala,
            error=(
                "Transcrevi o que foi falado neste vídeo. A parte visual não é analisada "
                "nesta instalação, que roda sem FFmpeg — por isso o vídeo não conta como "
                "totalmente decifrado."
            ),
            metadata={
                "reason": "sem_ffmpeg",
                "transcript": fala,
                "duration_seconds": duracao,
                "size_mb": round(tamanho_mb, 1),
            },
            cost_usd=gasto,
            category=self.category,
        )

    async def process(self, event: Event, context: ProcessingContext) -> ProcessingOutcome:
        path = await context.midia(event)
        if path is None:
            return ProcessingOutcome(
                status=ProcessingStatus.UNRESOLVED,
                error="Arquivo de vídeo não encontrado no ZIP.",
                category=self.category,
            )

        if not ffmpeg_disponivel():
            return await self._so_a_fala(event, path, context)

        settings = context.settings
        info = await probe(path)
        duration = info.duration_seconds or 0.0

        transcript = ""
        descriptions: list[str] = []
        cost = 0.0
        problems: list[str] = []

        # 1) Áudio do vídeo, pelo mesmo caminho das mensagens de voz.
        if info.has_audio:
            try:
                context.budget.check(transcription_cost(settings, duration))
                audio_path = await extract_audio_track(path, context.scratch(event, "audio.mp3"))
                if audio_path is not None:
                    result = await context.provider.transcribe(
                        audio_path, hint=context.conversation_hint
                    )
                    transcript = result.text.strip()
                    spent = transcription_cost(settings, duration)
                    context.budget.spend(spent)
                    cost += spent
            except BudgetExceeded:
                raise
            except (MediaToolError, ProviderError) as exc:
                problems.append(f"áudio do vídeo: {exc}")

        # 2) Quadros representativos.
        frames = []
        try:
            frames = await extract_frames(
                path, context.scratch(event, "frames"), settings.video_max_frames
            )
        except MediaToolError as exc:
            problems.append(f"extração de quadros: {exc}")

        for position, frame in enumerate(frames):
            try:
                context.budget.check(
                    vision_call_cost(
                        settings, VISION_INPUT_TOKENS_PER_IMAGE, VISION_OUTPUT_TOKENS_PER_IMAGE
                    )
                )
            except BudgetExceeded:
                problems.append("teto de custo atingido antes de descrever todos os quadros")
                break
            try:
                result = await context.provider.describe_image(
                    frame, context=event.caption, purpose="video_frame"
                )
            except ProviderError as exc:
                problems.append(f"quadro {position + 1}: {exc}")
                continue
            context.budget.spend(result.cost_usd)
            cost += result.cost_usd
            piece = " ".join(part for part in (result.visible_text, result.description) if part)
            if piece:
                descriptions.append(f"Quadro {position + 1}: {piece}")

        metadata = {
            "duration_seconds": round(duration, 2),
            "frames": len(frames),
            "transcript": transcript,
            "visual_description": "\n".join(descriptions),
            "cost": round(cost, 6),
        }
        if problems:
            metadata["partial_failures"] = problems

        if not transcript and not descriptions:
            return ProcessingOutcome(
                status=ProcessingStatus.FAILED,
                metadata=metadata,
                error="Não foi possível extrair áudio nem quadros deste vídeo."
                + (f" ({'; '.join(problems)})" if problems else ""),
                cost_usd=cost,
                category=self.category,
            )

        body = "\n\n".join(
            piece
            for piece in (
                f"Transcrição do áudio:\n{transcript}" if transcript else "",
                "\n".join(descriptions),
            )
            if piece
        )
        return ProcessingOutcome(
            status=ProcessingStatus.DONE,
            text=body,
            metadata=metadata,
            cost_usd=cost,
            category=self.category,
        )
