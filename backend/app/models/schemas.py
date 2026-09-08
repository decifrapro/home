"""Modelo interno de dados: eventos da timeline, jobs, links e inventário."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = 2
"""Versão do JSON exportado.

1 — Parte 1: timeline fiel, mídias em `pending`, sem conteúdo processado.
2 — Parte 2: acrescenta `processedText` preenchido, `links` como subitens
    processados, `coverage`, `cost` e metadados de mídia por evento.
"""


class EventType(StrEnum):
    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"
    PDF = "pdf"
    VIDEO = "video"
    LINK = "link"
    DOCUMENT = "document"
    SYSTEM = "system"
    UNKNOWN = "unknown"

    @property
    def is_media(self) -> bool:
        return self in {
            EventType.AUDIO,
            EventType.IMAGE,
            EventType.PDF,
            EventType.VIDEO,
            EventType.DOCUMENT,
            EventType.UNKNOWN,
        }


class ProcessingStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    UNRESOLVED = "unresolved"


class JobStatus(StrEnum):
    CREATED = "created"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    PARSING = "parsing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    PROCESSING = "processing"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            JobStatus.PARTIAL,
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }


class LinkItem(BaseModel):
    """URL encontrada dentro de uma mensagem. Subitem do evento."""

    id: str
    event_id: str
    url: str
    status: ProcessingStatus = ProcessingStatus.PENDING
    title: str | None = None
    description: str | None = None
    content: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Event(BaseModel):
    id: str
    index: int
    raw_timestamp: str
    timestamp: datetime | None = None
    sender: str | None = None
    type: EventType = EventType.TEXT
    raw_text: str = ""
    caption: str | None = None
    attachment_name: str | None = None
    attachment_path: str | None = None
    detected_mime: str | None = None
    processed_text: str | None = None
    processing_status: ProcessingStatus = ProcessingStatus.DONE
    processing_error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    links: list[LinkItem] = Field(default_factory=list)


class CatalogFile(BaseModel):
    """Arquivo físico encontrado dentro do ZIP."""

    relative_path: str
    name: str
    original_path: str = ""
    original_name: str = ""
    size: int
    detected_mime: str | None = None
    extension_mime: str | None = None
    mime_mismatch: bool = False
    matched_event_id: str | None = None


class Inventory(BaseModel):
    text: int = 0
    audio: int = 0
    image: int = 0
    pdf: int = 0
    video: int = 0
    document: int = 0
    system: int = 0
    unknown: int = 0
    links: int = 0
    attachments_referenced: int = 0
    attachments_matched: int = 0
    attachments_unresolved: int = 0
    orphan_files: int = 0
    orphan_names: list[str] = Field(default_factory=list)


class CategoryCoverage(BaseModel):
    total: int = 0
    done: int = 0
    failed: int = 0
    pending: int = 0
    unsupported: int = 0
    unresolved: int = 0

    @property
    def complete(self) -> bool:
        return self.total == self.done


class Coverage(BaseModel):
    categories: dict[str, CategoryCoverage] = Field(default_factory=dict)
    overall_total: int = 0
    overall_done: int = 0

    @property
    def percent(self) -> float:
        if self.overall_total == 0:
            return 100.0
        return round(self.overall_done * 100 / self.overall_total, 1)

    @property
    def complete(self) -> bool:
        return self.overall_done == self.overall_total


class CostBreakdown(BaseModel):
    audio_usd: float = 0.0
    image_usd: float = 0.0
    pdf_usd: float = 0.0
    video_usd: float = 0.0
    link_usd: float = 0.0

    @property
    def total_usd(self) -> float:
        return round(
            self.audio_usd + self.image_usd + self.pdf_usd + self.video_usd + self.link_usd, 4
        )


class CostEstimate(BaseModel):
    breakdown: CostBreakdown = Field(default_factory=CostBreakdown)
    audio_seconds: float = 0.0
    images: int = 0
    pdf_pages: int = 0
    video_seconds: float = 0.0
    video_frames: int = 0
    links: int = 0
    total_usd: float = 0.0
    exceeds_cap: bool = False
    cap_usd: float = 0.0
    notes: list[str] = Field(default_factory=list)


class JobWarning(BaseModel):
    code: str
    message: str
    detail: str | None = None


class Job(BaseModel):
    id: str
    status: JobStatus = JobStatus.CREATED
    created_at: datetime
    updated_at: datetime
    original_filename: str | None = None
    zip_size: int = 0
    error: str | None = None
    warnings: list[JobWarning] = Field(default_factory=list)
    inventory: Inventory = Field(default_factory=Inventory)
    coverage: Coverage = Field(default_factory=Coverage)
    estimate: CostEstimate | None = None
    cost: CostBreakdown = Field(default_factory=CostBreakdown)
    confirmed: bool = False
    conversation_start: datetime | None = None
    conversation_end: datetime | None = None
    event_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION
