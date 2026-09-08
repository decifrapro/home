"""Worker de segundo plano.

O processamento roda no servidor, independente da aba do navegador: o frontend
só consulta o status. Quem coordena tudo é este módulo — parse, estimativa de
custo, processadores, cobertura, custo real e limpeza por retenção.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.config import settings
from app.db import (
    get_events,
    get_job,
    get_links,
    merge_job_metadata,
    replace_events,
    replace_files,
    replace_links,
    update_event,
    update_job,
    update_link,
)
from app.models.schemas import (
    CostBreakdown,
    Event,
    EventType,
    Job,
    JobStatus,
    JobWarning,
    LinkItem,
    ProcessingStatus,
)
from app.parsers.whatsapp import parse_chat
from app.processors.base import Budget, BudgetExceeded, ProcessingContext, ProcessingOutcome
from app.processors.registry import CONCURRENCY_KEYS, link_processor, processor_for
from app.providers import build_provider
from app.services import storage
from app.services.cost import add_cost, estimate_job
from app.services.coverage import compute_coverage
from app.services.timeline import build_timeline
from app.services.zip_service import ZipRejected, choose_main_txt, extract_zip, read_text_file

logger = logging.getLogger(__name__)

PARSE = "parse"
PROCESS = "process"
RETRY_ALL = "retry_all"
RETRY_ONE = "retry_one"


@dataclass
class Task:
    job_id: str
    action: str
    event_id: str | None = None


class JobRunner:
    """Fila simples de trabalho, um job por vez, com paralelismo interno por tipo."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Task] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._retention_task: asyncio.Task | None = None
        self._cancelled: set[str] = set()
        self._current: str | None = None

    # ── ciclo de vida ───────────────────────────────────────────────────────
    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._consume(), name="decifra-worker")
        if self._retention_task is None:
            self._retention_task = asyncio.create_task(self._retention_loop(), name="decifra-retencao")
        await self.resume_pending()

    async def stop(self) -> None:
        for task in (self._task, self._retention_task):
            if task is not None:
                task.cancel()
        self._task = None
        self._retention_task = None

    def pending_tasks(self) -> list[Task]:
        """Jobs que ficaram pela metade quando o servidor caiu."""
        from app.db import jobs_in_status

        tasks = [
            Task(job.id, PARSE)
            for job in jobs_in_status([JobStatus.UPLOADED, JobStatus.PARSING])
        ]
        tasks += [Task(job.id, PROCESS) for job in jobs_in_status([JobStatus.PROCESSING])]
        return tasks

    async def resume_pending(self) -> None:
        """Depois de um reinício, retoma o que ficou pela metade."""
        for task in self.pending_tasks():
            logger.info("job=%s retomando %s após reinício", task.job_id, task.action)
            await self.submit(task)

    async def submit(self, task: Task) -> None:
        self._cancelled.discard(task.job_id)
        await self._queue.put(task)

    def cancel(self, job_id: str) -> None:
        self._cancelled.add(job_id)

    def is_cancelled(self, job_id: str) -> bool:
        return job_id in self._cancelled

    async def _consume(self) -> None:
        while True:
            task = await self._queue.get()
            self._current = task.job_id
            try:
                await self._run(task)
            except asyncio.CancelledError:  # pragma: no cover
                raise
            except Exception as exc:
                logger.exception("job=%s falha inesperada no worker", task.job_id)
                update_job(task.job_id, status=JobStatus.FAILED, error=_sanitize(str(exc)))
            finally:
                self._current = None
                self._queue.task_done()

    async def _retention_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(900)
                purge_expired()
            except asyncio.CancelledError:  # pragma: no cover
                raise
            except Exception:
                logger.exception("falha na limpeza por retenção")

    # ── execução ────────────────────────────────────────────────────────────
    async def _run(self, task: Task) -> None:
        job = get_job(task.job_id)
        if job is None:
            return
        if task.action == PARSE:
            await self.parse_job(job)
        elif task.action == PROCESS:
            await self.process_job(job)
        elif task.action == RETRY_ALL:
            await self.process_job(job, retry_failed=True)
        elif task.action == RETRY_ONE and task.event_id:
            await self.process_job(job, retry_failed=True, only_event=task.event_id)

    # ── fase 1: motor ───────────────────────────────────────────────────────
    async def parse_job(self, job: Job) -> None:
        """Descompacta, lê o TXT e monta a timeline. Nenhuma chamada de IA aqui."""
        job_id = job.id
        update_job(job_id, status=JobStatus.PARSING, error=None)
        extract_root = storage.extract_dir(job_id)
        zip_file = storage.zip_path(job_id)

        try:
            extraction = await asyncio.to_thread(extract_zip, zip_file, extract_root, settings)
        except ZipRejected as exc:
            logger.warning("job=%s zip recusado code=%s", job_id, exc.code)
            update_job(job_id, status=JobStatus.FAILED, error=exc.message)
            return
        except FileNotFoundError:
            update_job(job_id, status=JobStatus.FAILED, error="O arquivo enviado não foi encontrado.")
            return

        main_txt, choice_log = choose_main_txt(extraction.txt_candidates, extract_root)
        if main_txt is None:
            update_job(
                job_id,
                status=JobStatus.FAILED,
                error=(
                    "Não encontrei o arquivo de texto da conversa dentro do ZIP. "
                    "Exporte a conversa pelo WhatsApp em 'Exportar conversa' e envie o ZIP gerado."
                ),
            )
            return

        content = await asyncio.to_thread(read_text_file, extract_root / main_txt.relative_path)
        parse_result = parse_chat(content)
        timeline = build_timeline(parse_result, extraction.files, extract_root, main_txt.relative_path)

        replace_files(job_id, timeline.files)
        replace_events(job_id, timeline.events)
        replace_links(job_id, timeline.links)

        stamps = [event.timestamp for event in timeline.events if event.timestamp]
        coverage = compute_coverage(timeline.events, timeline.links)
        metadata = {
            "dateOrder": parse_result.date_order,
            "mainTxt": main_txt.original_name or main_txt.name,
            "txtCandidates": choice_log,
            "filesInZip": len(extraction.files),
            "uncompressedBytes": extraction.total_uncompressed,
            "aiEnabled": settings.ai_enabled,
        }

        merge_job_metadata(job_id, metadata)
        update_job(
            job_id,
            inventory=timeline.inventory,
            coverage=coverage,
            warnings=timeline.warnings,
            event_count=len(timeline.events),
            conversation_start=min(stamps) if stamps else None,
            conversation_end=max(stamps) if stamps else None,
        )

        logger.info(
            "job=%s parse concluído eventos=%d anexos=%d/%d órfãos=%d",
            job_id, len(timeline.events), timeline.inventory.attachments_matched,
            timeline.inventory.attachments_referenced, timeline.inventory.orphan_files,
        )

        if not settings.ai_enabled:
            warnings = list(timeline.warnings)
            if _has_pending_media(timeline.events, timeline.links):
                warnings.append(
                    JobWarning(
                        code="ai_disabled",
                        message=(
                            "Nenhum provedor de IA está configurado, então as mídias não foram "
                            "decifradas. A conversa está montada e o texto está completo."
                        ),
                    )
                )
                update_job(job_id, status=JobStatus.PARTIAL, warnings=warnings)
            else:
                update_job(job_id, status=JobStatus.COMPLETED, warnings=warnings)
            return

        estimate = await estimate_job(timeline.events, timeline.links, extract_root, settings)
        update_job(job_id, estimate=estimate)

        if settings.auto_confirm_processing:
            update_job(job_id, confirmed=True)
            refreshed = get_job(job_id)
            if refreshed:
                await self.process_job(refreshed)
        else:
            update_job(job_id, status=JobStatus.AWAITING_CONFIRMATION)

    # ── fase 2: inteligência ────────────────────────────────────────────────
    async def process_job(
        self, job: Job, *, retry_failed: bool = False, only_event: str | None = None
    ) -> None:
        """Processa as mídias pendentes com semáforo por tipo e teto de custo."""
        job_id = job.id
        events = get_events(job_id, with_links=False)
        links = get_links(job_id)

        if not settings.ai_enabled and _needs_ai(events, links, retry_failed, only_event):
            update_job(
                job_id,
                status=JobStatus.PARTIAL,
                error="Nenhum provedor de IA configurado (defina OPENAI_API_KEY).",
            )
            return

        update_job(job_id, status=JobStatus.PROCESSING, error=None)
        provider = build_provider(settings)
        budget = Budget(cap_usd=settings.max_job_cost_usd, spent_usd=job.cost.total_usd)
        context = ProcessingContext(
            job_id=job_id,
            extract_root=storage.extract_dir(job_id),
            work_root=storage.work_dir(job_id),
            settings=settings,
            provider=provider,
            budget=budget,
            conversation_hint=_conversation_hint(events),
        )

        semaphores = {
            category: asyncio.Semaphore(max(1, getattr(settings, attribute)))
            for category, attribute in CONCURRENCY_KEYS.items()
        }
        cost = job.cost.model_copy()
        budget_hit = False

        selected_events = [
            event
            for event in events
            if _should_process(event, retry_failed, only_event)
        ]
        selected_links = [
            link for link in links if _should_process_link(link, retry_failed, only_event)
        ]

        async def handle_event(event: Event) -> None:
            nonlocal budget_hit
            processor = processor_for(event.type)
            if processor is None:
                return
            if self.is_cancelled(job_id):
                return
            async with semaphores.get(processor.category, semaphores["image"]):
                if self.is_cancelled(job_id) or budget_hit:
                    return
                update_event(job_id, event.id, processing_status=ProcessingStatus.PROCESSING)
                try:
                    outcome = await processor.process(event, context)
                except BudgetExceeded as exc:
                    budget_hit = True
                    update_event(
                        job_id, event.id,
                        processing_status=ProcessingStatus.PENDING,
                        processing_error=f"Processamento pausado: {exc}",
                    )
                    return
                except Exception as exc:  # falha isolada nunca derruba o job
                    logger.exception("job=%s event=%s falha no processador", job_id, event.index)
                    update_event(
                        job_id, event.id,
                        processing_status=ProcessingStatus.FAILED,
                        processing_error=_sanitize(str(exc)),
                    )
                    return
                _apply_outcome(job_id, event, outcome, cost)
                logger.info(
                    "job=%s event=%d type=%s status=%s",
                    job_id, event.index, event.type.value, outcome.status.value,
                )

        async def handle_link(link: LinkItem) -> None:
            if self.is_cancelled(job_id) or budget_hit:
                return
            async with semaphores["link"]:
                update_link(job_id, link.id, status=ProcessingStatus.PROCESSING.value)
                try:
                    outcome = await link_processor().process(link, context)
                except Exception as exc:
                    logger.exception("job=%s link falha", job_id)
                    update_link(
                        job_id, link.id,
                        status=ProcessingStatus.FAILED.value,
                        error=_sanitize(str(exc)),
                    )
                    return
                update_link(
                    job_id, link.id,
                    status=outcome.status.value,
                    title=outcome.metadata.get("title"),
                    description=outcome.metadata.get("description"),
                    content=outcome.text,
                    error=outcome.error,
                    metadata=outcome.metadata,
                )

        try:
            await asyncio.gather(
                *(handle_event(event) for event in selected_events),
                *(handle_link(link) for link in selected_links),
            )
        finally:
            await provider.aclose()

        await asyncio.to_thread(storage.purge_work, job_id)

        final_events = get_events(job_id, with_links=False)
        final_links = get_links(job_id)
        coverage = compute_coverage(final_events, final_links)
        update_job(job_id, coverage=coverage, cost=cost)

        if self.is_cancelled(job_id):
            update_job(job_id, status=JobStatus.CANCELLED)
            self._cancelled.discard(job_id)
            return

        warnings = [w for w in (get_job(job_id) or job).warnings if w.code != "budget"]
        if budget_hit:
            warnings.append(
                JobWarning(
                    code="budget",
                    message=(
                        f"O teto de custo de US$ {settings.max_job_cost_usd:.2f} foi atingido. "
                        "O processamento parou e nada foi apagado — aumente o teto e reprocesse "
                        "as pendências quando quiser."
                    ),
                )
            )

        status = JobStatus.COMPLETED if coverage.complete else JobStatus.PARTIAL
        update_job(job_id, status=status, warnings=warnings)
        logger.info(
            "job=%s processamento encerrado status=%s cobertura=%.1f%% custo=%.4f",
            job_id, status.value, coverage.percent, cost.total_usd,
        )


def _apply_outcome(job_id: str, event: Event, outcome: ProcessingOutcome, cost: CostBreakdown) -> None:
    metadata = dict(event.metadata or {})
    metadata.update(outcome.metadata or {})
    if outcome.cost_usd:
        add_cost(cost, outcome.category, outcome.cost_usd)
    update_event(
        job_id,
        event.id,
        processed_text=outcome.text,
        processing_status=outcome.status,
        processing_error=outcome.error,
        metadata=metadata,
    )


def _should_process(event: Event, retry_failed: bool, only_event: str | None) -> bool:
    if only_event is not None:
        return event.id == only_event and event.type.is_media
    if not event.type.is_media:
        return False
    if event.processing_status == ProcessingStatus.PENDING:
        return True
    return retry_failed and event.processing_status == ProcessingStatus.FAILED


def _should_process_link(link: LinkItem, retry_failed: bool, only_event: str | None) -> bool:
    if only_event is not None:
        return link.id == only_event or link.event_id == only_event
    if link.status == ProcessingStatus.PENDING:
        return True
    return retry_failed and link.status == ProcessingStatus.FAILED


def _needs_ai(
    events: list[Event], links: list[LinkItem], retry_failed: bool, only_event: str | None
) -> bool:
    return any(
        _should_process(event, retry_failed, only_event)
        and event.type in {EventType.AUDIO, EventType.IMAGE, EventType.VIDEO}
        for event in events
    )


def _has_pending_media(events: list[Event], links: list[LinkItem]) -> bool:
    waiting = {ProcessingStatus.PENDING, ProcessingStatus.PROCESSING}
    return any(event.processing_status in waiting for event in events) or any(
        link.status in waiting for link in links
    )


def _conversation_hint(events: list[Event]) -> str:
    """Nomes que já aparecem na conversa ajudam o reconhecimento de fala.

    Só nomes de remetentes — nada de conteúdo de mensagem vai para o provedor
    como contexto.
    """
    senders: list[str] = []
    for event in events:
        if event.sender and event.sender not in senders:
            senders.append(event.sender)
    return ", ".join(senders[:20])


def _sanitize(message: str) -> str:
    """Mensagem de erro sem conteúdo sensível e sem chave de API."""
    cleaned = message.strip().replace("\n", " ")
    for marker in ("sk-", "Bearer "):
        if marker in cleaned:
            cleaned = cleaned.split(marker)[0] + "[credencial removida]"
    return cleaned[:400]


def purge_expired() -> None:
    """Apaga jobs além da retenção configurada: banco e arquivos."""
    from app.db import delete_job, expired_jobs

    for job in expired_jobs(settings.job_retention_hours):
        logger.info("job=%s removido por retenção", job.id)
        storage.purge_job(job.id)
        delete_job(job.id)


runner = JobRunner()
