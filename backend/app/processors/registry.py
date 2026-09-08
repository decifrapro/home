"""Mapa de tipo de mídia para processador."""

from __future__ import annotations

from app.models.schemas import EventType
from app.processors.audio import AudioProcessor
from app.processors.base import LinkProcessorBase, MediaProcessor
from app.processors.document import DocumentProcessor
from app.processors.image import ImageProcessor
from app.processors.link import LinkProcessor
from app.processors.pdf import PdfProcessor
from app.processors.video import VideoProcessor

_PROCESSORS: tuple[MediaProcessor, ...] = (
    AudioProcessor(),
    ImageProcessor(),
    PdfProcessor(),
    VideoProcessor(),
    DocumentProcessor(),
)

_BY_TYPE: dict[EventType, MediaProcessor] = {
    event_type: processor for processor in _PROCESSORS for event_type in processor.handles
}

_LINK_PROCESSOR = LinkProcessor()

# Categorias com semáforo próprio de concorrência.
CONCURRENCY_KEYS = {
    "audio": "audio_concurrency",
    "image": "image_concurrency",
    "pdf": "pdf_concurrency",
    "video": "video_concurrency",
    "link": "link_concurrency",
    "document": "pdf_concurrency",
}


def processor_for(event_type: EventType) -> MediaProcessor | None:
    return _BY_TYPE.get(event_type)


def link_processor() -> LinkProcessorBase:
    return _LINK_PROCESSOR
