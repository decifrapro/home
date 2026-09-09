"""Guarda dos atendimentos no Supabase — usado quando o sistema roda na Vercel.

Mesmas funções do módulo SQLite, para o resto do programa não perceber a
diferença. Aqui não há disco nem processo que fique de pé: cada chamada é uma
conversa curta com o banco pela internet.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
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
from app.services.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)

_cliente: SupabaseClient | None = None


def cliente() -> SupabaseClient:
    global _cliente
    if _cliente is None:
        _cliente = SupabaseClient(settings)
    return _cliente


def _tabela(nome: str) -> str:
    return f"{settings.supabase_table_prefix}{nome}"


def connect() -> None:
    """Confere que dá para falar com o banco antes de começar."""
    cliente().select(_tabela("jobs"), colunas="id", limite=1)


def reset_connection() -> None:
    global _cliente
    _cliente = None


def _agora() -> str:
    return datetime.now(UTC).isoformat()


def _data(valor: Any) -> datetime | None:
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.replace(tzinfo=None)
    texto = str(valor).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(texto).replace(tzinfo=None)
    except ValueError:
        return None


def _json(valor: Any, padrao: Any) -> Any:
    if valor is None:
        return padrao
    if isinstance(valor, str):
        try:
            return json.loads(valor)
        except json.JSONDecodeError:
            return padrao
    return valor


def _limpar(valor: Any) -> Any:
    """Deixa o valor pronto para virar JSON no banco."""
    if hasattr(valor, "model_dump"):
        return valor.model_dump(mode="json")
    if isinstance(valor, list):
        return [_limpar(item) for item in valor]
    if isinstance(valor, datetime):
        return valor.isoformat()
    return valor


# ── Atendimentos ────────────────────────────────────────────────────────────

def create_job(job_id: str, original_filename: str | None = None) -> Job:
    agora = datetime.now()
    cliente().insert(
        _tabela("jobs"),
        {
            "id": job_id,
            "status": JobStatus.CREATED.value,
            "created_at": _agora(),
            "updated_at": _agora(),
            "original_filename": original_filename,
            "schema_version": SCHEMA_VERSION,
        },
    )
    return Job(
        id=job_id,
        status=JobStatus.CREATED,
        created_at=agora,
        updated_at=agora,
        original_filename=original_filename,
    )


def update_job(job_id: str, **campos: Any) -> None:
    if not campos:
        return
    valores: dict[str, Any] = {}
    for chave, valor in campos.items():
        if chave == "status":
            valores[chave] = JobStatus(valor).value
        elif chave == "confirmed":
            valores[chave] = bool(valor)
        else:
            valores[chave] = _limpar(valor)
    valores["updated_at"] = _agora()
    cliente().update(_tabela("jobs"), {"id": f"eq.{job_id}"}, valores)


def merge_job_metadata(job_id: str, patch: dict) -> None:
    atual = get_job(job_id)
    metadata = dict(atual.metadata) if atual else {}
    metadata.update(patch)
    cliente().update(_tabela("jobs"), {"id": f"eq.{job_id}"}, {"metadata": metadata, "updated_at": _agora()})


def _linha_para_job(linha: dict) -> Job:
    estimativa = _json(linha.get("estimate"), None)
    return Job(
        id=linha["id"],
        status=JobStatus(linha["status"]),
        created_at=_data(linha.get("created_at")) or datetime.now(),
        updated_at=_data(linha.get("updated_at")) or datetime.now(),
        original_filename=linha.get("original_filename"),
        zip_size=linha.get("zip_size") or 0,
        error=linha.get("error"),
        warnings=[JobWarning(**item) for item in _json(linha.get("warnings"), [])],
        inventory=Inventory(**_json(linha.get("inventory"), {})),
        coverage=Coverage(**_json(linha.get("coverage"), {})),
        estimate=CostEstimate(**estimativa) if estimativa else None,
        cost=CostBreakdown(**_json(linha.get("cost"), {})),
        confirmed=bool(linha.get("confirmed")),
        conversation_start=_data(linha.get("conversation_start")),
        conversation_end=_data(linha.get("conversation_end")),
        event_count=linha.get("event_count") or 0,
        metadata=_json(linha.get("metadata"), {}),
        schema_version=linha.get("schema_version") or SCHEMA_VERSION,
    )


def get_job(job_id: str) -> Job | None:
    linhas = cliente().select(_tabela("jobs"), filtros={"id": f"eq.{job_id}"}, limite=1)
    return _linha_para_job(linhas[0]) if linhas else None


def list_jobs(limit: int = 50) -> list[Job]:
    linhas = cliente().select(_tabela("jobs"), ordem="created_at.desc", limite=limit)
    return [_linha_para_job(linha) for linha in linhas]


def delete_job(job_id: str) -> None:
    for nome in ("events", "links", "files"):
        cliente().delete(_tabela(nome), {"job_id": f"eq.{job_id}"})
    cliente().delete(_tabela("jobs"), {"id": f"eq.{job_id}"})


def jobs_in_status(statuses: list[JobStatus]) -> list[Job]:
    lista = ",".join(status.value for status in statuses)
    linhas = cliente().select(_tabela("jobs"), filtros={"status": f"in.({lista})"})
    return [_linha_para_job(linha) for linha in linhas]


def expired_jobs(retention_hours: int) -> list[Job]:
    corte = (datetime.now(UTC) - timedelta(hours=retention_hours)).isoformat()
    linhas = cliente().select(_tabela("jobs"), filtros={"created_at": f"lt.{corte}"})
    return [_linha_para_job(linha) for linha in linhas]


# ── Eventos ─────────────────────────────────────────────────────────────────

def _evento_para_linha(job_id: str, evento: Event) -> dict:
    return {
        "id": evento.id,
        "job_id": job_id,
        "idx": evento.index,
        "raw_timestamp": evento.raw_timestamp,
        "timestamp": evento.timestamp.isoformat() if evento.timestamp else None,
        "sender": evento.sender,
        "type": evento.type.value,
        "raw_text": evento.raw_text,
        "caption": evento.caption,
        "attachment_name": evento.attachment_name,
        "attachment_path": evento.attachment_path,
        "detected_mime": evento.detected_mime,
        "processed_text": evento.processed_text,
        "processing_status": evento.processing_status.value,
        "processing_error": evento.processing_error,
        "metadata": evento.metadata,
    }


def _linha_para_evento(linha: dict) -> Event:
    return Event(
        id=linha["id"],
        index=linha["idx"],
        raw_timestamp=linha["raw_timestamp"],
        timestamp=_data(linha.get("timestamp")),
        sender=linha.get("sender"),
        type=EventType(linha["type"]),
        raw_text=linha.get("raw_text") or "",
        caption=linha.get("caption"),
        attachment_name=linha.get("attachment_name"),
        attachment_path=linha.get("attachment_path"),
        detected_mime=linha.get("detected_mime"),
        processed_text=linha.get("processed_text"),
        processing_status=ProcessingStatus(linha.get("processing_status") or "pending"),
        processing_error=linha.get("processing_error"),
        metadata=_json(linha.get("metadata"), {}),
    )


def replace_events(job_id: str, events: list[Event]) -> None:
    cliente().delete(_tabela("events"), {"job_id": f"eq.{job_id}"})
    linhas = [_evento_para_linha(job_id, evento) for evento in events]
    for bloco in range(0, len(linhas), 200):
        cliente().insert(_tabela("events"), linhas[bloco : bloco + 200])


def get_events(job_id: str, with_links: bool = True) -> list[Event]:
    linhas = cliente().select(_tabela("events"), filtros={"job_id": f"eq.{job_id}"}, ordem="idx.asc")
    eventos = [_linha_para_evento(linha) for linha in linhas]
    if with_links:
        por_evento: dict[str, list[LinkItem]] = {}
        for link in get_links(job_id):
            por_evento.setdefault(link.event_id, []).append(link)
        for evento in eventos:
            evento.links = por_evento.get(evento.id, [])
    return eventos


def get_event(job_id: str, event_id: str) -> Event | None:
    linhas = cliente().select(
        _tabela("events"), filtros={"job_id": f"eq.{job_id}", "id": f"eq.{event_id}"}, limite=1
    )
    if not linhas:
        return None
    evento = _linha_para_evento(linhas[0])
    evento.links = [link for link in get_links(job_id) if link.event_id == evento.id]
    return evento


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
    valores: dict[str, Any] = {"processing_error": processing_error}
    if processed_text is not None:
        valores["processed_text"] = processed_text
    if processing_status is not None:
        valores["processing_status"] = processing_status.value
        if processing_status != ProcessingStatus.PROCESSING:
            valores["leased_until"] = None
    if metadata is not None:
        valores["metadata"] = metadata
    if detected_mime is not None:
        valores["detected_mime"] = detected_mime
    cliente().update(_tabela("events"), {"job_id": f"eq.{job_id}", "id": f"eq.{event_id}"}, valores)


def count_events_by_status(job_id: str) -> dict[tuple[str, str], int]:
    contagem: dict[tuple[str, str], int] = {}
    for evento in get_events(job_id, with_links=False):
        chave = (evento.type.value, evento.processing_status.value)
        contagem[chave] = contagem.get(chave, 0) + 1
    return contagem


def lease_event(job_id: str, event_id: str, seconds: int = 300) -> bool:
    """Reserva o item. False quando outra execução pegou primeiro.

    A reserva é feita numa única atualização condicional: quem conseguir mudar
    a linha fica com o item, e o outro segue em frente.
    """
    limite = (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()
    agora = _agora()
    atualizados = cliente().update_returning(
        _tabela("events"),
        {
            "job_id": f"eq.{job_id}",
            "id": f"eq.{event_id}",
            "processing_status": "in.(pending,failed)",
            "or": f"(leased_until.is.null,leased_until.lt.{agora})",
        },
        {"processing_status": ProcessingStatus.PROCESSING.value, "leased_until": limite},
    )
    return bool(atualizados)


def reclaim_expired(job_id: str) -> int:
    """Devolve para a fila os itens cuja reserva venceu.

    Sem isto um item reservado por uma execução que morreu no meio ficaria
    marcado como "processando" para sempre e ninguém voltaria nele.
    """
    agora = _agora()
    devolvidos = cliente().update_returning(
        _tabela("events"),
        {
            "job_id": f"eq.{job_id}",
            "processing_status": f"eq.{ProcessingStatus.PROCESSING.value}",
            "leased_until": f"lt.{agora}",
        },
        {"processing_status": ProcessingStatus.PENDING.value, "leased_until": None},
    )
    devolvidos += cliente().update_returning(
        _tabela("links"),
        {
            "job_id": f"eq.{job_id}",
            "status": f"eq.{ProcessingStatus.PROCESSING.value}",
            "leased_until": f"lt.{agora}",
        },
        {"status": ProcessingStatus.PENDING.value, "leased_until": None},
    )
    return len(devolvidos) if isinstance(devolvidos, list) else int(devolvidos)


def lease_link(job_id: str, link_id: str, seconds: int = 300) -> bool:
    limite = (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()
    agora = _agora()
    atualizados = cliente().update_returning(
        _tabela("links"),
        {
            "job_id": f"eq.{job_id}",
            "id": f"eq.{link_id}",
            "status": "in.(pending,failed)",
            "or": f"(leased_until.is.null,leased_until.lt.{agora})",
        },
        {"status": ProcessingStatus.PROCESSING.value, "leased_until": limite},
    )
    return bool(atualizados)


def release_stale_leases(seconds: int = 900) -> None:
    agora = _agora()
    cliente().update(
        _tabela("events"),
        {"processing_status": "eq.processing", "leased_until": f"lt.{agora}"},
        {"processing_status": ProcessingStatus.PENDING.value, "leased_until": None},
    )
    cliente().update(
        _tabela("links"),
        {"status": "eq.processing", "leased_until": f"lt.{agora}"},
        {"status": ProcessingStatus.PENDING.value, "leased_until": None},
    )


# ── Links ───────────────────────────────────────────────────────────────────

def replace_links(job_id: str, links: list[LinkItem]) -> None:
    cliente().delete(_tabela("links"), {"job_id": f"eq.{job_id}"})
    linhas = [
        {
            "id": link.id,
            "job_id": job_id,
            "event_id": link.event_id,
            "url": link.url,
            "status": link.status.value,
            "title": link.title,
            "description": link.description,
            "content": link.content,
            "error": link.error,
            "metadata": link.metadata,
        }
        for link in links
    ]
    for bloco in range(0, len(linhas), 200):
        cliente().insert(_tabela("links"), linhas[bloco : bloco + 200])


def get_links(job_id: str) -> list[LinkItem]:
    linhas = cliente().select(_tabela("links"), filtros={"job_id": f"eq.{job_id}"})
    return [
        LinkItem(
            id=linha["id"],
            event_id=linha["event_id"],
            url=linha["url"],
            status=ProcessingStatus(linha.get("status") or "pending"),
            title=linha.get("title"),
            description=linha.get("description"),
            content=linha.get("content"),
            error=linha.get("error"),
            metadata=_json(linha.get("metadata"), {}),
        )
        for linha in linhas
    ]


def update_link(job_id: str, link_id: str, **campos: Any) -> None:
    valores: dict[str, Any] = {}
    for chave, valor in campos.items():
        if chave == "status":
            valores[chave] = ProcessingStatus(valor).value
            if valores[chave] != ProcessingStatus.PROCESSING.value:
                valores["leased_until"] = None
        else:
            valores[chave] = _limpar(valor)
    cliente().update(_tabela("links"), {"job_id": f"eq.{job_id}", "id": f"eq.{link_id}"}, valores)


# ── Arquivos do ZIP ─────────────────────────────────────────────────────────

def replace_files(job_id: str, files: list[CatalogFile]) -> None:
    cliente().delete(_tabela("files"), {"job_id": f"eq.{job_id}"})
    linhas = [
        {
            "job_id": job_id,
            "relative_path": item.relative_path,
            "name": item.name,
            "original_path": item.original_path,
            "original_name": item.original_name,
            "size": item.size,
            "detected_mime": item.detected_mime,
            "extension_mime": item.extension_mime,
            "mime_mismatch": item.mime_mismatch,
            "matched_event_id": item.matched_event_id,
        }
        for item in files
    ]
    for bloco in range(0, len(linhas), 200):
        cliente().insert(_tabela("files"), linhas[bloco : bloco + 200])


def get_files(job_id: str) -> list[CatalogFile]:
    linhas = cliente().select(_tabela("files"), filtros={"job_id": f"eq.{job_id}"})
    return [
        CatalogFile(
            relative_path=linha["relative_path"],
            name=linha["name"],
            original_path=linha.get("original_path") or "",
            original_name=linha.get("original_name") or "",
            size=linha.get("size") or 0,
            detected_mime=linha.get("detected_mime"),
            extension_mime=linha.get("extension_mime"),
            mime_mismatch=bool(linha.get("mime_mismatch")),
            matched_event_id=linha.get("matched_event_id"),
        )
        for linha in linhas
    ]
