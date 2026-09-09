"""Análise de imagens: texto visível e descrição factual, separados.

A legenda escrita pela pessoa no WhatsApp é preservada à parte — ela é conteúdo
original, não interpretação de IA.
"""

from __future__ import annotations

from app.models.schemas import Event, EventType, ProcessingStatus
from app.processors.base import MediaProcessor, ProcessingContext, ProcessingOutcome
from app.providers.base import ProviderError
from app.services.cost import VISION_INPUT_TOKENS_PER_IMAGE, VISION_OUTPUT_TOKENS_PER_IMAGE, vision_call_cost

SUPPORTED_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}
NEEDS_CONVERSION = {"image/heic", "image/heif"}


class ImageProcessor(MediaProcessor):
    category = "image"
    handles = (EventType.IMAGE,)

    async def process(self, event: Event, context: ProcessingContext) -> ProcessingOutcome:
        path = await context.midia(event)
        if path is None:
            return ProcessingOutcome(
                status=ProcessingStatus.UNRESOLVED,
                error="Arquivo de imagem não encontrado no ZIP.",
                category=self.category,
            )

        mime = (event.detected_mime or "").lower()
        working = path
        if mime in NEEDS_CONVERSION:
            converted = _to_jpeg(path, context.scratch(event, "imagem.jpg"))
            if converted is None:
                return ProcessingOutcome(
                    status=ProcessingStatus.UNSUPPORTED,
                    error="Formato de imagem não suportado para análise (HEIC sem conversor disponível).",
                    category=self.category,
                )
            working = converted
        elif mime and mime not in SUPPORTED_MIMES:
            return ProcessingOutcome(
                status=ProcessingStatus.UNSUPPORTED,
                error=f"Formato de imagem não suportado para análise: {mime}.",
                category=self.category,
            )

        context.budget.check(
            vision_call_cost(
                context.settings, VISION_INPUT_TOKENS_PER_IMAGE, VISION_OUTPUT_TOKENS_PER_IMAGE
            )
        )

        try:
            result = await context.provider.describe_image(
                working, context=event.caption, purpose="image"
            )
        except ProviderError as exc:
            return ProcessingOutcome(
                status=ProcessingStatus.FAILED,
                error=f"Análise da imagem não concluída: {exc}",
                category=self.category,
            )

        context.budget.spend(result.cost_usd)

        pieces = []
        if result.visible_text:
            pieces.append(result.visible_text)
        if result.description:
            pieces.append(result.description)

        return ProcessingOutcome(
            status=ProcessingStatus.DONE,
            text="\n\n".join(pieces) or "[imagem sem conteúdo identificável]",
            metadata={
                "ocr_text": result.visible_text,
                "visual_description": result.description,
                "model": result.model,
                "tokens": {"input": result.input_tokens, "output": result.output_tokens},
                "cost": result.cost_usd,
            },
            cost_usd=result.cost_usd,
            category=self.category,
        )


def _to_jpeg(source, target):
    """Converte formatos que o provedor não aceita. None se não for possível."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        return None
    try:
        with Image.open(source) as image:
            image.convert("RGB").save(target, "JPEG", quality=88)
        return target
    except Exception:
        return None
