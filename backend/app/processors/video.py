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
    extract_audio_track,
    extract_frames,
    probe,
)
from app.services.media import (
    disponivel as ffmpeg_disponivel,
)

logger = logging.getLogger(__name__)


class VideoProcessor(MediaProcessor):
    category = "video"
    handles = (EventType.VIDEO,)

    async def process(self, event: Event, context: ProcessingContext) -> ProcessingOutcome:
        path = await context.midia(event)
        if path is None:
            return ProcessingOutcome(
                status=ProcessingStatus.UNRESOLVED,
                error="Arquivo de vídeo não encontrado no ZIP.",
                category=self.category,
            )

        if not ffmpeg_disponivel():
            return ProcessingOutcome(
                status=ProcessingStatus.UNSUPPORTED,
                error=(
                    "Vídeo não é analisado nesta instalação, que roda sem FFmpeg. "
                    "O arquivo continua na conversa, na posição certa, apenas sem "
                    "transcrição e sem descrição."
                ),
                metadata={"reason": "sem_ffmpeg"},
                category=self.category,
            )

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
