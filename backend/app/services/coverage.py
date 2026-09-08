"""Cobertura do atendimento: quanto do conteúdo foi realmente decifrado.

100% só aparece quando é 100% de verdade.
"""

from __future__ import annotations

from app.models.schemas import (
    CategoryCoverage,
    Coverage,
    Event,
    EventType,
    LinkItem,
    ProcessingStatus,
)

# Categorias que contam para a cobertura geral, na ordem em que são exibidas.
CATEGORIES = ("text", "audio", "image", "pdf", "video", "document", "link")

_TYPE_TO_CATEGORY = {
    EventType.TEXT: "text",
    EventType.SYSTEM: "text",
    EventType.AUDIO: "audio",
    EventType.IMAGE: "image",
    EventType.PDF: "pdf",
    EventType.VIDEO: "video",
    EventType.DOCUMENT: "document",
    EventType.UNKNOWN: "document",
    EventType.LINK: "link",
}


def _bump(bucket: CategoryCoverage, status: ProcessingStatus) -> None:
    bucket.total += 1
    if status == ProcessingStatus.DONE:
        bucket.done += 1
    elif status == ProcessingStatus.FAILED:
        bucket.failed += 1
    elif status == ProcessingStatus.UNSUPPORTED:
        bucket.unsupported += 1
    elif status == ProcessingStatus.UNRESOLVED:
        bucket.unresolved += 1
    else:
        bucket.pending += 1


def compute_coverage(events: list[Event], links: list[LinkItem] | None = None) -> Coverage:
    """Cobertura por categoria e geral.

    Links contam como subitens: um evento de texto com três URLs contribui com
    uma linha de texto e três itens de link.
    """
    coverage = Coverage()
    for name in CATEGORIES:
        coverage.categories[name] = CategoryCoverage()

    for event in events:
        category = _TYPE_TO_CATEGORY.get(event.type, "document")
        if event.type == EventType.LINK:
            # O corpo do evento de link é texto; as URLs entram pela lista de links.
            category = "text"
        _bump(coverage.categories[category], event.processing_status)

    all_links = links if links is not None else [link for event in events for link in event.links]
    for link in all_links:
        _bump(coverage.categories["link"], link.status)

    coverage.overall_total = sum(bucket.total for bucket in coverage.categories.values())
    coverage.overall_done = sum(bucket.done for bucket in coverage.categories.values())
    return coverage


def pending_work(events: list[Event], links: list[LinkItem]) -> bool:
    """Ainda há mídia esperando processamento de IA?"""
    waiting = {ProcessingStatus.PENDING, ProcessingStatus.PROCESSING}
    return any(event.processing_status in waiting for event in events) or any(
        link.status in waiting for link in links
    )


def failures(events: list[Event], links: list[LinkItem]) -> tuple[list[Event], list[LinkItem]]:
    return (
        [event for event in events if event.processing_status == ProcessingStatus.FAILED],
        [link for link in links if link.status == ProcessingStatus.FAILED],
    )
