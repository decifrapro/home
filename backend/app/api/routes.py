"""Endpoints HTTP do Decifra Pro."""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app import db
from app.api.deps import (
    clear_session,
    issue_session,
    password_matches,
    require_access,
    session_is_valid,
)
from app.api.serializers import event_to_dict, job_to_dict
from app.config import settings
from app.jobs.worker import PARSE, PROCESS, RETRY_ALL, RETRY_ONE, Task, purge_expired, runner
from app.models.schemas import EventType, JobStatus, ProcessingStatus
from app.services import storage
from app.services.exporters import export_json_text, export_markdown, export_txt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


# ── Saúde e configuração ────────────────────────────────────────────────────
@router.get("/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "aiEnabled": settings.ai_enabled}


@router.get("/config")
def config(decifra_sessao: str | None = Cookie(default=None)) -> dict:
    return {
        **settings.public_config(),
        "authenticated": not settings.access_gate_enabled or session_is_valid(decifra_sessao),
    }


class LoginPayload(BaseModel):
    password: str = Field(default="", max_length=200)


@router.post("/auth/login")
def login(payload: LoginPayload, response: Response) -> dict:
    if not settings.access_gate_enabled:
        return {"authenticated": True}
    if not password_matches(payload.password):
        raise HTTPException(status_code=401, detail="Senha incorreta.")
    issue_session(response)
    return {"authenticated": True}


@router.post("/auth/logout")
def logout(response: Response) -> dict:
    clear_session(response)
    return {"authenticated": False}


# ── Atendimentos ────────────────────────────────────────────────────────────
@router.post("/jobs", dependencies=[Depends(require_access)])
def create_job() -> dict:
    job_id = storage.new_job_id()
    storage.ensure_job_dirs(job_id)
    job = db.create_job(job_id)
    logger.info("job=%s criado", job_id)
    return job_to_dict(job)


@router.get("/jobs", dependencies=[Depends(require_access)])
def list_jobs(limit: int = Query(default=30, ge=1, le=100)) -> dict:
    return {"jobs": [job_to_dict(job) for job in db.list_jobs(limit)]}


class UploadInit(BaseModel):
    filename: str = Field(max_length=400)
    size: int = Field(ge=0)
    totalChunks: int = Field(ge=1, le=100_000)


@router.post("/jobs/{job_id}/upload/init", dependencies=[Depends(require_access)])
def upload_init(job_id: str, payload: UploadInit) -> dict:
    job = _job_or_404(job_id)
    max_bytes = settings.max_zip_mb * 1024 * 1024
    if payload.size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"O ZIP tem {payload.size / 1024 / 1024:.0f} MB e o limite é {settings.max_zip_mb} MB.",
        )
    storage.ensure_job_dirs(job_id)
    for stale in storage.upload_dir(job_id).glob("part-*"):
        stale.unlink(missing_ok=True)
    db.update_job(
        job_id,
        status=JobStatus.UPLOADING,
        original_filename=payload.filename.strip()[:400],
        zip_size=payload.size,
        error=None,
    )
    return {
        "jobId": job.id,
        "chunkSize": settings.upload_chunk_mb * 1024 * 1024,
        "totalChunks": payload.totalChunks,
    }


@router.put("/jobs/{job_id}/upload/chunk", dependencies=[Depends(require_access)])
async def upload_chunk(job_id: str, request: Request, index: int = Query(ge=0)) -> dict:
    _job_or_404(job_id)
    target = storage.upload_dir(job_id) / f"part-{index:06d}"
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    max_bytes = settings.max_zip_mb * 1024 * 1024
    with target.open("wb") as sink:
        async for chunk in request.stream():
            written += len(chunk)
            if written > max_bytes:
                sink.close()
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Parte de upload maior que o permitido.")
            sink.write(chunk)
    return {"index": index, "received": written}


class UploadComplete(BaseModel):
    totalChunks: int = Field(ge=1, le=100_000)
    size: int | None = None
    sha256: str | None = None


@router.post("/jobs/{job_id}/upload/complete", dependencies=[Depends(require_access)])
async def upload_complete(job_id: str, payload: UploadComplete) -> dict:
    _job_or_404(job_id)
    upload_dir = storage.upload_dir(job_id)
    parts = [upload_dir / f"part-{index:06d}" for index in range(payload.totalChunks)]
    missing = [index for index, part in enumerate(parts) if not part.exists()]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Faltam partes do upload: {missing[:10]}. Reenvie as partes que faltam.",
        )

    destination = storage.zip_path(job_id)
    digest = hashlib.sha256()
    total = 0
    with destination.open("wb") as sink:
        for part in parts:
            with part.open("rb") as source:
                while True:
                    block = source.read(1024 * 512)
                    if not block:
                        break
                    digest.update(block)
                    total += len(block)
                    sink.write(block)
    for part in parts:
        part.unlink(missing_ok=True)

    checksum = digest.hexdigest()
    if payload.size is not None and payload.size != total:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"O upload chegou incompleto ({total} de {payload.size} bytes). Tente de novo.",
        )
    if payload.sha256 and payload.sha256.lower() != checksum:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="A verificação do arquivo enviado falhou.")

    db.update_job(job_id, status=JobStatus.UPLOADED, zip_size=total)
    db.merge_job_metadata(job_id, {"sha256": checksum})
    await runner.submit(Task(job_id, PARSE))
    logger.info("job=%s upload concluído bytes=%d", job_id, total)
    return {"jobId": job_id, "size": total, "sha256": checksum, "status": JobStatus.UPLOADED.value}


class UploadDireto(BaseModel):
    filename: str = Field(max_length=400)
    size: int = Field(ge=0)


@router.post("/jobs/{job_id}/upload/link", dependencies=[Depends(require_access)])
def upload_link(job_id: str, payload: UploadDireto) -> dict:
    """Link para o navegador enviar o ZIP direto ao Supabase.

    Na Vercel a requisição que chega à função é limitada a poucos megabytes, então
    o arquivo não pode passar por ela: o celular envia direto para o armazenamento.
    """
    _job_or_404(job_id)
    if settings.storage_mode != "supabase":
        raise HTTPException(
            status_code=409,
            detail="Esta instalação recebe o arquivo em partes pela própria API.",
        )
    max_bytes = settings.max_zip_mb * 1024 * 1024
    if payload.size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"O ZIP tem {payload.size / 1024 / 1024:.0f} MB e o limite é {settings.max_zip_mb} MB.",
        )

    from app.repositorios.supabase import cliente

    caminho = f"{job_id}/conversa.zip"
    link = cliente().signed_upload_url(caminho)
    db.update_job(
        job_id,
        status=JobStatus.UPLOADING,
        original_filename=payload.filename.strip()[:400],
        zip_size=payload.size,
        error=None,
    )
    db.merge_job_metadata(job_id, {"zipPath": caminho})
    return {"jobId": job_id, "path": caminho, "uploadUrl": link["signedUrl"], "token": link["token"]}


@router.post("/jobs/{job_id}/upload/registrado", dependencies=[Depends(require_access)])
async def upload_registrado(job_id: str) -> dict:
    """Avisa que o envio direto terminou e já lê a conversa."""
    job = _job_or_404(job_id)
    if settings.storage_mode != "supabase":
        raise HTTPException(status_code=409, detail="Endpoint válido apenas no modo Supabase.")
    db.update_job(job_id, status=JobStatus.UPLOADED)
    atual = db.get_job(job_id) or job
    await runner.parse_job(atual)
    return job_to_dict(db.get_job(job_id) or atual)


@router.post("/jobs/{job_id}/tick", dependencies=[Depends(require_access)])
async def tick(job_id: str) -> dict:
    """Processa um pedaço do atendimento e conta o que ainda falta."""
    job = _job_or_404(job_id)
    if job.status == JobStatus.AWAITING_CONFIRMATION and not job.confirmed:
        raise HTTPException(status_code=409, detail="Confirme o processamento antes de continuar.")
    return await runner.tick(job)


@router.get("/cron/tick")
async def cron_tick(request: Request) -> dict:
    """Chamado pelo agendamento: continua os atendimentos com o aplicativo fechado."""
    if settings.cron_secret:
        enviado = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if enviado != settings.cron_secret and not request.headers.get("x-vercel-cron"):
            raise HTTPException(status_code=401, detail="Chamada não autorizada.")

    db.release_stale_leases()
    purge_expired()
    atendidos = []
    for job in db.jobs_in_status([JobStatus.PROCESSING, JobStatus.UPLOADED, JobStatus.PARSING])[:3]:
        if job.status in {JobStatus.UPLOADED, JobStatus.PARSING}:
            await runner.parse_job(job)
            atendidos.append({"jobId": job.id, "acao": "leitura"})
        else:
            atendidos.append(await runner.tick(job))
    return {"atendidos": atendidos}


@router.get("/jobs/{job_id}", dependencies=[Depends(require_access)])
def get_job(job_id: str) -> dict:
    return job_to_dict(_job_or_404(job_id))


@router.get("/jobs/{job_id}/events", dependencies=[Depends(require_access)])
def get_events(
    job_id: str,
    type: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict:
    _job_or_404(job_id)
    events = db.get_events(job_id)

    if type and type != "all":
        try:
            wanted = EventType(type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Tipo de evento inválido.") from exc
        events = [event for event in events if event.type == wanted]
    if status and status != "all":
        try:
            wanted_status = ProcessingStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Status inválido.") from exc
        events = [event for event in events if event.processing_status == wanted_status]
    if search:
        needle = search.casefold()
        events = [event for event in events if _matches(event, needle)]

    total = len(events)
    page = events[offset : offset + limit]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "events": [event_to_dict(event) for event in page],
    }


@router.post("/jobs/{job_id}/confirm", dependencies=[Depends(require_access)])
async def confirm_processing(job_id: str) -> dict:
    job = _job_or_404(job_id)
    if job.status not in {JobStatus.AWAITING_CONFIRMATION, JobStatus.PARTIAL, JobStatus.COMPLETED}:
        raise HTTPException(
            status_code=409, detail="Este atendimento não está aguardando confirmação."
        )
    if not settings.ai_enabled:
        raise HTTPException(
            status_code=409,
            detail="Nenhum provedor de IA configurado no servidor (defina OPENAI_API_KEY).",
        )
    db.update_job(job_id, confirmed=True, status=JobStatus.PROCESSING)
    if settings.serverless:
        # Sem processo de fundo: quem toca o trabalho é o aplicativo (chamando
        # /tick) e o agendamento automático, que continua com a aba fechada.
        return {"jobId": job_id, "status": JobStatus.PROCESSING.value, "modo": "tick"}
    await runner.submit(Task(job_id, PROCESS))
    return {"jobId": job_id, "status": JobStatus.PROCESSING.value}


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(require_access)])
def cancel_job(job_id: str) -> dict:
    job = _job_or_404(job_id)
    if job.status.is_terminal:
        return job_to_dict(job)
    runner.cancel(job_id)
    db.update_job(job_id, status=JobStatus.CANCELLED)
    logger.info("job=%s cancelado pelo usuário", job_id)
    return job_to_dict(_job_or_404(job_id))


@router.post("/jobs/{job_id}/retry", dependencies=[Depends(require_access)])
async def retry_failures(job_id: str) -> dict:
    _job_or_404(job_id)
    if settings.serverless:
        _reenfileirar(job_id)
        return {"jobId": job_id, "status": JobStatus.PROCESSING.value, "modo": "tick"}
    await runner.submit(Task(job_id, RETRY_ALL))
    return {"jobId": job_id, "status": JobStatus.PROCESSING.value}


@router.post("/jobs/{job_id}/events/{event_id}/retry", dependencies=[Depends(require_access)])
async def retry_event(job_id: str, event_id: str) -> dict:
    _job_or_404(job_id)
    if settings.serverless:
        _reenfileirar(job_id, apenas=event_id)
        return {"jobId": job_id, "eventId": event_id, "status": JobStatus.PROCESSING.value,
                "modo": "tick"}
    await runner.submit(Task(job_id, RETRY_ONE, event_id=event_id))
    return {"jobId": job_id, "eventId": event_id, "status": JobStatus.PROCESSING.value}


def _reenfileirar(job_id: str, apenas: str | None = None) -> None:
    """Devolve as falhas para a fila. O conteúdo já obtido não é apagado."""
    for evento in db.get_events(job_id, with_links=False):
        if apenas and evento.id != apenas:
            continue
        if evento.processing_status == ProcessingStatus.FAILED or (apenas and evento.type.is_media):
            db.update_event(job_id, evento.id, processing_status=ProcessingStatus.PENDING,
                            processing_error=None)
    for link in db.get_links(job_id):
        if apenas and link.event_id != apenas and link.id != apenas:
            continue
        if link.status == ProcessingStatus.FAILED:
            db.update_link(job_id, link.id, status=ProcessingStatus.PENDING.value, error=None)
    db.update_job(job_id, status=JobStatus.PROCESSING, error=None)


@router.delete("/jobs/{job_id}", dependencies=[Depends(require_access)])
def delete_job(job_id: str) -> dict:
    _job_or_404(job_id)
    runner.cancel(job_id)
    storage.purge_job(job_id)
    if settings.storage_mode == "supabase":
        from app.repositorios.supabase import cliente

        try:
            cliente().remove_prefix(job_id)
        except Exception as exc:  # o banco é apagado de qualquer forma
            logger.warning("job=%s não foi possível apagar os arquivos: %s", job_id, exc)
    db.delete_job(job_id)
    logger.info("job=%s apagado pelo usuário", job_id)
    return {"deleted": True, "jobId": job_id}


# ── Exportações ─────────────────────────────────────────────────────────────
@router.get("/jobs/{job_id}/export/txt", dependencies=[Depends(require_access)])
def export_as_txt(job_id: str) -> PlainTextResponse:
    job = _job_or_404(job_id)
    content = export_txt(job, db.get_events(job_id))
    return PlainTextResponse(content, headers=_download_headers(job_id, "txt"))


@router.get("/jobs/{job_id}/export/md", dependencies=[Depends(require_access)])
def export_as_markdown(job_id: str) -> PlainTextResponse:
    job = _job_or_404(job_id)
    content = export_markdown(job, db.get_events(job_id))
    return PlainTextResponse(
        content, media_type="text/markdown; charset=utf-8", headers=_download_headers(job_id, "md")
    )


@router.get("/jobs/{job_id}/export/json", dependencies=[Depends(require_access)])
def export_as_json(job_id: str) -> Response:
    job = _job_or_404(job_id)
    content = export_json_text(job, db.get_events(job_id))
    return Response(
        content,
        media_type="application/json; charset=utf-8",
        headers=_download_headers(job_id, "json"),
    )


def _download_headers(job_id: str, extension: str) -> dict:
    return {"Content-Disposition": f'attachment; filename="conversa-{job_id[:8]}.{extension}"'}


def _job_or_404(job_id: str):
    if not job_id.isalnum():
        raise HTTPException(status_code=404, detail="Atendimento não encontrado.")
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Atendimento não encontrado.")
    return job


def _matches(event, needle: str) -> bool:
    haystacks = [event.raw_text, event.caption or "", event.processed_text or "", event.sender or ""]
    haystacks += [link.url for link in event.links]
    return any(needle in (item or "").casefold() for item in haystacks)
