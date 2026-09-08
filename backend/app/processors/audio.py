"""Transcrição de mensagens de voz.

O áudio é convertido só quando necessário, dividido quando for grande demais
para o provedor, e a transcrição volta como um texto contínuo — na posição
cronológica exata do áudio original.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.models.schemas import Event, EventType, ProcessingStatus
from app.processors.base import MediaProcessor, ProcessingContext, ProcessingOutcome
from app.providers.base import ProviderError
from app.services.cost import transcription_cost
from app.services.media import MediaToolError, convert_audio, probe, split_audio

logger = logging.getLogger(__name__)

# Extensões que a API de transcrição aceita diretamente.
DIRECT_EXTENSIONS = {".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".oga", ".ogg", ".wav", ".webm"}


def needs_conversion(path: Path, mime: str | None) -> bool:
    """Converte quando a extensão não é aceita pelo provedor ou não bate com o conteúdo.

    O `.opus` do WhatsApp é OGG por dentro, mas a extensão não é aceita — esse é
    o caso que mais aparece nas exportações reais.
    """
    suffix = path.suffix.lower()
    if suffix not in DIRECT_EXTENSIONS:
        return True
    if mime and mime.startswith("audio/"):
        family = {
            "audio/ogg": {".ogg", ".oga"},
            "audio/mpeg": {".mp3", ".mpga", ".mpeg"},
            "audio/wav": {".wav"},
            "audio/x-wav": {".wav"},
            "audio/mp4": {".m4a", ".mp4"},
            "audio/flac": {".flac"},
            "audio/webm": {".webm"},
        }.get(mime)
        if family and suffix not in family:
            return True
    return False


class AudioProcessor(MediaProcessor):
    category = "audio"
    handles = (EventType.AUDIO,)

    async def process(self, event: Event, context: ProcessingContext) -> ProcessingOutcome:
        path = context.media_path(event)
        if path is None:
            return ProcessingOutcome(
                status=ProcessingStatus.UNRESOLVED,
                error="Arquivo de áudio não encontrado no ZIP.",
                category=self.category,
            )

        settings = context.settings
        info = await probe(path)
        duration = info.duration_seconds or 0.0
        context.budget.check(transcription_cost(settings, duration))

        try:
            source = path
            if needs_conversion(path, event.detected_mime):
                source = await convert_audio(path, context.scratch(event, "audio.mp3"))

            size_mb = source.stat().st_size / (1024 * 1024)
            too_big = size_mb > settings.audio_chunk_max_mb
            too_long = duration > settings.audio_chunk_seconds

            if too_big or too_long:
                chunks = await split_audio(
                    source, context.scratch(event, "chunks"), settings.audio_chunk_seconds
                )
            else:
                chunks = [source]
        except MediaToolError as exc:
            return ProcessingOutcome(
                status=ProcessingStatus.FAILED,
                error=f"Falha ao preparar o áudio: {exc}",
                category=self.category,
            )

        parts: list[str] = []
        try:
            for chunk in chunks:
                result = await context.provider.transcribe(
                    chunk, language=None, hint=context.conversation_hint
                )
                parts.append(result.text.strip())
        except ProviderError as exc:
            return ProcessingOutcome(
                status=ProcessingStatus.FAILED,
                error=f"Transcrição não concluída: {exc}",
                category=self.category,
                metadata={"duration_seconds": round(duration, 2), "chunks": len(chunks)},
            )

        cost = transcription_cost(settings, duration or 0.0)
        context.budget.spend(cost)

        text = "\n".join(part for part in parts if part).strip()
        if not text:
            return ProcessingOutcome(
                status=ProcessingStatus.DONE,
                text="[áudio sem fala identificável]",
                metadata={
                    "duration_seconds": round(duration, 2),
                    "chunks": len(chunks),
                    "empty": True,
                    "cost": cost,
                },
                cost_usd=cost,
                category=self.category,
            )

        return ProcessingOutcome(
            status=ProcessingStatus.DONE,
            text=text,
            metadata={
                "duration_seconds": round(duration, 2),
                "chunks": len(chunks),
                "codec": info.audio_codec,
                "converted": chunks[0] != path,
                "cost": cost,
            },
            cost_usd=cost,
            category=self.category,
        )
