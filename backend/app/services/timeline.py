"""Montagem da timeline: junta o que o TXT diz com o que existe no ZIP."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.models.schemas import (
    CatalogFile,
    Event,
    EventType,
    Inventory,
    JobWarning,
    LinkItem,
    ProcessingStatus,
)
from app.parsers.whatsapp import ParseResult
from app.services.matcher import AttachmentMatcher
from app.services.mime import type_for_mime


def _event_type(value: str) -> EventType:
    try:
        return EventType(value)
    except ValueError:
        return EventType.UNKNOWN


MEDIA_OMITTED_NOTE = "Mídia não incluída nesta exportação do WhatsApp."
UNRESOLVED_NOTE = "Arquivo citado na conversa não foi encontrado dentro do ZIP."


@dataclass
class TimelineResult:
    events: list[Event]
    links: list[LinkItem]
    files: list[CatalogFile]
    inventory: Inventory
    warnings: list[JobWarning] = field(default_factory=list)


def build_timeline(
    parse_result: ParseResult,
    files: list[CatalogFile],
    extract_root: Path,
    main_txt_path: str | None,
) -> TimelineResult:
    matcher = AttachmentMatcher([item for item in files if item.relative_path != main_txt_path])
    events: list[Event] = []
    links: list[LinkItem] = []
    inventory = Inventory()

    for parsed in parse_result.events:
        event = Event(
            id=parsed.id,
            index=parsed.index,
            raw_timestamp=parsed.raw_timestamp,
            timestamp=parsed.timestamp,
            sender=parsed.sender,
            type=_event_type(parsed.type),
            raw_text=parsed.raw_text,
            caption=parsed.caption,
            attachment_name=parsed.attachment_name,
            metadata=dict(parsed.metadata),
        )

        if parsed.attachment_name:
            inventory.attachments_referenced += 1
            outcome = matcher.match(parsed.attachment_name)
            if outcome.file is not None:
                matched = outcome.file
                matched.matched_event_id = event.id
                event.attachment_path = matched.relative_path
                event.detected_mime = matched.detected_mime
                event.type = type_for_mime(matched.detected_mime)
                event.metadata.update(
                    {
                        "match_strategy": outcome.strategy,
                        "file_size": matched.size,
                        "original_filename": matched.original_name,
                    }
                )
                if matched.mime_mismatch:
                    # O conteúdo real prevalece sobre a extensão do arquivo.
                    event.metadata["mime_mismatch"] = {
                        "extension": matched.extension_mime,
                        "detected": matched.detected_mime,
                    }
                event.processing_status = ProcessingStatus.PENDING
                inventory.attachments_matched += 1
            else:
                event.processing_status = ProcessingStatus.UNRESOLVED
                event.processing_error = UNRESOLVED_NOTE + (
                    " Havia mais de um arquivo com esse nome, então nada foi associado."
                    if outcome.ambiguous
                    else ""
                )
                inventory.attachments_unresolved += 1
        elif event.metadata.get("media_omitted"):
            event.processing_status = ProcessingStatus.UNSUPPORTED
            event.processing_error = MEDIA_OMITTED_NOTE
        elif event.type in (EventType.TEXT, EventType.SYSTEM, EventType.LINK):
            event.processing_status = ProcessingStatus.DONE
        else:
            event.processing_status = ProcessingStatus.UNRESOLVED
            event.processing_error = UNRESOLVED_NOTE

        for url in parsed.urls:
            links.append(LinkItem(id=str(uuid.uuid4()), event_id=event.id, url=url))

        events.append(event)
        _count(inventory, event)

    inventory.links = len(links)
    orphans = matcher.orphans(main_txt_path)
    inventory.orphan_files = len(orphans)
    inventory.orphan_names = [item.original_name or item.name for item in orphans][:200]

    warnings = [JobWarning(**item) for item in parse_result.warnings]
    if inventory.attachments_unresolved:
        warnings.append(
            JobWarning(
                code="unresolved_attachments",
                message=(
                    f"{inventory.attachments_unresolved} anexos citados na conversa não foram "
                    "encontrados no ZIP. Eles continuam visíveis na timeline, sem conteúdo."
                ),
            )
        )
    if inventory.orphan_files:
        warnings.append(
            JobWarning(
                code="orphan_files",
                message=(
                    f"{inventory.orphan_files} arquivos do ZIP não são citados no TXT. "
                    "Eles não foram inseridos na conversa."
                ),
                detail=", ".join(inventory.orphan_names[:20]),
            )
        )

    return TimelineResult(
        events=events, links=links, files=files, inventory=inventory, warnings=warnings
    )


def _count(inventory: Inventory, event: Event) -> None:
    if event.type == EventType.AUDIO:
        inventory.audio += 1
    elif event.type == EventType.IMAGE:
        inventory.image += 1
    elif event.type == EventType.PDF:
        inventory.pdf += 1
    elif event.type == EventType.VIDEO:
        inventory.video += 1
    elif event.type == EventType.DOCUMENT:
        inventory.document += 1
    elif event.type == EventType.SYSTEM:
        inventory.system += 1
    elif event.type == EventType.UNKNOWN:
        inventory.unknown += 1
    else:
        inventory.text += 1
