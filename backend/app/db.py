"""Persistência em SQLite.

O status de cada atendimento vive no banco, não na memória do processo: o
servidor pode reiniciar e continuar mostrando (e retomando) os jobs.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import settings
from app.models.schemas import (
    SCHEMA_VERSION,
    CatalogFile,
    CostBreakdown,
    CostEstimate,
    Coverage,
    Event,
    EventType,
    Inventory,
    Job,
    JobStatus,
    JobWarning,
    LinkItem,
    ProcessingStatus,
)

_lock = threading.RLock()
_connection: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    original_filename TEXT,
    zip_size INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    warnings TEXT NOT NULL DEFAULT '[]',
    inventory TEXT NOT NULL DEFAULT '{}',
    coverage TEXT NOT NULL DEFAULT '{}',
    estimate TEXT,
    cost TEXT NOT NULL DEFAULT '{}',
    confirmed INTEGER NOT NULL DEFAULT 0,
    conversation_start TEXT,
    conversation_end TEXT,
    event_count INTEGER NOT NULL DEFAULT 0,
    metadata TEXT NOT NULL DEFAULT '{}',
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    raw_timestamp TEXT NOT NULL,
    timestamp TEXT,
    sender TEXT,
    type TEXT NOT NULL,
    raw_text TEXT NOT NULL DEFAULT '',
    caption TEXT,
    attachment_name TEXT,
    attachment_path TEXT,
    detected_mime TEXT,
    processed_text TEXT,
    processing_status TEXT NOT NULL DEFAULT 'pending',
    processing_error TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_events_job ON events (job_id, idx);

CREATE TABLE IF NOT EXISTS links (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    title TEXT,
    description TEXT,
    content TEXT,
    error TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_links_job ON links (job_id);

CREATE TABLE IF NOT EXISTS files (
    job_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    name TEXT NOT NULL,
    original_path TEXT NOT NULL DEFAULT '',
    original_name TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL DEFAULT 0,
    detected_mime TEXT,
    extension_mime TEXT,
    mime_mismatch INTEGER NOT NULL DEFAULT 0,
    matched_event_id TEXT,
    PRIMARY KEY (job_id, relative_path),
    FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
);
"""


def connect() -> sqlite3.Connection:
    global _connection
    with _lock:
        if _connection is None:
            path = Path(settings.db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            _connection = sqlite3.connect(str(path), check_same_thread=False)
            _connection.row_factory = sqlite3.Row
            _connection.execute("PRAGMA journal_mode=WAL")
            _connection.execute("PRAGMA foreign_keys=ON")
            _connection.executescript(SCHEMA)
            _connection.commit()
        return _connection


def reset_connection() -> None:
    """Fecha a conexão (usado em testes ao trocar o diretório de dados)."""
    global _connection
    with _lock:
        if _connection is not None:
            _connection.close()
            _connection = None


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


# ── Jobs ────────────────────────────────────────────────────────────────────

def create_job(job_id: str, original_filename: str | None = None) -> Job:
    now = datetime.now()
    with _lock:
        conn = connect()
        conn.execute(
            "INSERT INTO jobs (id, status, created_at, updated_at, original_filename, schema_version)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, JobStatus.CREATED.value, now.isoformat(), now.isoformat(), original_filename,
             SCHEMA_VERSION),
        )
        conn.commit()
    return Job(id=job_id, status=JobStatus.CREATED, created_at=now, updated_at=now,
               original_filename=original_filename)


_JOB_JSON_FIELDS = {"warnings", "inventory", "coverage", "estimate", "cost", "metadata"}
_JOB_DATE_FIELDS = {"conversation_start", "conversation_end"}


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    assignments: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        if key in _JOB_JSON_FIELDS:
            if hasattr(value, "model_dump"):
                value = value.model_dump(mode="json")
            elif isinstance(value, list):
                value = [v.model_dump(mode="json") if hasattr(v, "model_dump") else v for v in value]
            value = _dump(value) if value is not None else None
        elif key in _JOB_DATE_FIELDS:
            value = _iso(value)
        elif key == "status":
            value = JobStatus(value).value
        elif key == "confirmed":
            value = int(bool(value))
        assignments.append(f"{key} = ?")
        values.append(value)
    assignments.append("updated_at = ?")
    values.append(datetime.now().isoformat())
    values.append(job_id)
    with _lock:
        conn = connect()
        conn.execute(f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?", values)
        conn.commit()


def _row_to_job(row: sqlite3.Row) -> Job:
    estimate_raw = json.loads(row["estimate"]) if row["estimate"] else None
    return Job(
        id=row["id"],
        status=JobStatus(row["status"]),
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
        original_filename=row["original_filename"],
        zip_size=row["zip_size"],
        error=row["error"],
        warnings=[JobWarning(**item) for item in json.loads(row["warnings"] or "[]")],
        inventory=Inventory(**json.loads(row["inventory"] or "{}")),
        coverage=Coverage(**json.loads(row["coverage"] or "{}")),
        estimate=CostEstimate(**estimate_raw) if estimate_raw else None,
        cost=CostBreakdown(**json.loads(row["cost"] or "{}")),
        confirmed=bool(row["confirmed"]),
        conversation_start=_parse_dt(row["conversation_start"]),
        conversation_end=_parse_dt(row["conversation_end"]),
        event_count=row["event_count"],
        metadata=json.loads(row["metadata"] or "{}"),
        schema_version=row["schema_version"],
    )


def merge_job_metadata(job_id: str, patch: dict) -> None:
    """Atualiza chaves da metadata sem descartar o que já estava lá."""
    with _lock:
        conn = connect()
        row = conn.execute("SELECT metadata FROM jobs WHERE id = ?", (job_id,)).fetchone()
        current = json.loads(row["metadata"] or "{}") if row else {}
        current.update(patch)
        conn.execute(
            "UPDATE jobs SET metadata = ?, updated_at = ? WHERE id = ?",
            (_dump(current), datetime.now().isoformat(), job_id),
        )
        conn.commit()


def get_job(job_id: str) -> Job | None:
    with _lock:
        row = connect().execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_jobs(limit: int = 50) -> list[Job]:
    with _lock:
        rows = connect().execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_job(row) for row in rows]


def delete_job(job_id: str) -> None:
    with _lock:
        conn = connect()
        conn.execute("DELETE FROM events WHERE job_id = ?", (job_id,))
        conn.execute("DELETE FROM links WHERE job_id = ?", (job_id,))
        conn.execute("DELETE FROM files WHERE job_id = ?", (job_id,))
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()


def jobs_in_status(statuses: list[JobStatus]) -> list[Job]:
    placeholders = ",".join("?" for _ in statuses)
    with _lock:
        rows = connect().execute(
            f"SELECT * FROM jobs WHERE status IN ({placeholders})",
            [status.value for status in statuses],
        ).fetchall()
    return [_row_to_job(row) for row in rows]


def expired_jobs(retention_hours: int) -> list[Job]:
    cutoff = (datetime.now() - timedelta(hours=retention_hours)).isoformat()
    with _lock:
        rows = connect().execute("SELECT * FROM jobs WHERE created_at < ?", (cutoff,)).fetchall()
    return [_row_to_job(row) for row in rows]


# ── Eventos ─────────────────────────────────────────────────────────────────

def replace_events(job_id: str, events: list[Event]) -> None:
    with _lock:
        conn = connect()
        conn.execute("DELETE FROM events WHERE job_id = ?", (job_id,))
        conn.executemany(
            "INSERT INTO events (id, job_id, idx, raw_timestamp, timestamp, sender, type, raw_text,"
            " caption, attachment_name, attachment_path, detected_mime, processed_text,"
            " processing_status, processing_error, metadata)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    event.id, job_id, event.index, event.raw_timestamp, _iso(event.timestamp),
                    event.sender, event.type.value, event.raw_text, event.caption,
                    event.attachment_name, event.attachment_path, event.detected_mime,
                    event.processed_text, event.processing_status.value, event.processing_error,
                    _dump(event.metadata),
                )
                for event in events
            ],
        )
        conn.commit()


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        index=row["idx"],
        raw_timestamp=row["raw_timestamp"],
        timestamp=_parse_dt(row["timestamp"]),
        sender=row["sender"],
        type=EventType(row["type"]),
        raw_text=row["raw_text"],
        caption=row["caption"],
        attachment_name=row["attachment_name"],
        attachment_path=row["attachment_path"],
        detected_mime=row["detected_mime"],
        processed_text=row["processed_text"],
        processing_status=ProcessingStatus(row["processing_status"]),
        processing_error=row["processing_error"],
        metadata=json.loads(row["metadata"] or "{}"),
    )


def get_events(job_id: str, with_links: bool = True) -> list[Event]:
    with _lock:
        rows = connect().execute(
            "SELECT * FROM events WHERE job_id = ? ORDER BY idx ASC", (job_id,)
        ).fetchall()
    events = [_row_to_event(row) for row in rows]
    if with_links:
        by_event: dict[str, list[LinkItem]] = {}
        for link in get_links(job_id):
            by_event.setdefault(link.event_id, []).append(link)
        for event in events:
            event.links = by_event.get(event.id, [])
    return events


def get_event(job_id: str, event_id: str) -> Event | None:
    with _lock:
        row = connect().execute(
            "SELECT * FROM events WHERE job_id = ? AND id = ?", (job_id, event_id)
        ).fetchone()
    if not row:
        return None
    event = _row_to_event(row)
    event.links = [link for link in get_links(job_id) if link.event_id == event.id]
    return event


def update_event(
    job_id: str,
    event_id: str,
    *,
    processed_text: str | None = None,
    processing_status: ProcessingStatus | None = None,
    processing_error: str | None = None,
    metadata: dict | None = None,
    detected_mime: str | None = None,
) -> None:
    assignments: list[str] = []
    values: list[Any] = []
    if processed_text is not None:
        assignments.append("processed_text = ?")
        values.append(processed_text)
    if processing_status is not None:
        assignments.append("processing_status = ?")
        values.append(processing_status.value)
    assignments.append("processing_error = ?")
    values.append(processing_error)
    if metadata is not None:
        assignments.append("metadata = ?")
        values.append(_dump(metadata))
    if detected_mime is not None:
        assignments.append("detected_mime = ?")
        values.append(detected_mime)
    values.extend([job_id, event_id])
    with _lock:
        conn = connect()
        conn.execute(
            f"UPDATE events SET {', '.join(assignments)} WHERE job_id = ? AND id = ?", values
        )
        conn.commit()


def count_events_by_status(job_id: str) -> dict[tuple[str, str], int]:
    with _lock:
        rows = connect().execute(
            "SELECT type, processing_status, COUNT(*) AS total FROM events WHERE job_id = ?"
            " GROUP BY type, processing_status",
            (job_id,),
        ).fetchall()
    return {(row["type"], row["processing_status"]): row["total"] for row in rows}


# ── Links ───────────────────────────────────────────────────────────────────

def replace_links(job_id: str, links: list[LinkItem]) -> None:
    with _lock:
        conn = connect()
        conn.execute("DELETE FROM links WHERE job_id = ?", (job_id,))
        conn.executemany(
            "INSERT INTO links (id, job_id, event_id, url, status, title, description, content,"
            " error, metadata) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    link.id, job_id, link.event_id, link.url, link.status.value, link.title,
                    link.description, link.content, link.error, _dump(link.metadata),
                )
                for link in links
            ],
        )
        conn.commit()


def get_links(job_id: str) -> list[LinkItem]:
    with _lock:
        rows = connect().execute("SELECT * FROM links WHERE job_id = ?", (job_id,)).fetchall()
    return [
        LinkItem(
            id=row["id"],
            event_id=row["event_id"],
            url=row["url"],
            status=ProcessingStatus(row["status"]),
            title=row["title"],
            description=row["description"],
            content=row["content"],
            error=row["error"],
            metadata=json.loads(row["metadata"] or "{}"),
        )
        for row in rows
    ]


def update_link(job_id: str, link_id: str, **fields: Any) -> None:
    assignments: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        if key == "status":
            value = ProcessingStatus(value).value
        elif key == "metadata":
            value = _dump(value)
        assignments.append(f"{key} = ?")
        values.append(value)
    values.extend([job_id, link_id])
    with _lock:
        conn = connect()
        conn.execute(
            f"UPDATE links SET {', '.join(assignments)} WHERE job_id = ? AND id = ?", values
        )
        conn.commit()


# ── Arquivos do ZIP ─────────────────────────────────────────────────────────

def replace_files(job_id: str, files: list[CatalogFile]) -> None:
    with _lock:
        conn = connect()
        conn.execute("DELETE FROM files WHERE job_id = ?", (job_id,))
        conn.executemany(
            "INSERT INTO files (job_id, relative_path, name, original_path, original_name, size,"
            " detected_mime, extension_mime, mime_mismatch, matched_event_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    job_id, item.relative_path, item.name, item.original_path, item.original_name,
                    item.size, item.detected_mime, item.extension_mime, int(item.mime_mismatch),
                    item.matched_event_id,
                )
                for item in files
            ],
        )
        conn.commit()


def get_files(job_id: str) -> list[CatalogFile]:
    with _lock:
        rows = connect().execute("SELECT * FROM files WHERE job_id = ?", (job_id,)).fetchall()
    return [
        CatalogFile(
            relative_path=row["relative_path"],
            name=row["name"],
            original_path=row["original_path"],
            original_name=row["original_name"],
            size=row["size"],
            detected_mime=row["detected_mime"],
            extension_mime=row["extension_mime"],
            mime_mismatch=bool(row["mime_mismatch"]),
            matched_event_id=row["matched_event_id"],
        )
        for row in rows
    ]
