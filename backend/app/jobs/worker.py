"""Worker de segundo plano.

O processamento roda no servidor, independente da aba do navegador: o frontend
só consulta o status. Quem coordena tudo é este módulo — parse, estimativa de
custo, processadores, cobertura, custo real e limpeza por retenção.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from app import db
from app.config import settings
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
from app.services.fonte_zip import FonteLocal, FonteSupabase, FonteZip, nome_temporario
from app.services.timeline import build_timeline
from app.services.zip_service import ZipRejected, choose_main_txt

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


# Quantas vezes um item pode estourar o tempo antes de ser dado como falho. Sem
# esse limite, um arquivo que não cabe na janela da hospedagem seria tentado
# eternamente e a tela ficaria "processando" para sempre.
MAX_TENTATIVAS_POR_TEMPO = 3


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
        tasks = [
            Task(job.id, PARSE)
            for job in db.jobs_in_status([JobStatus.UPLOADED, JobStatus.PARSING])
        ]
        tasks += [Task(job.id, PROCESS) for job in db.jobs_in_status([JobStatus.PROCESSING])]
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
                db.update_job(task.job_id, status=JobStatus.FAILED, error=_sanitize(str(exc)))
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
        job = db.get_job(task.job_id)
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

    # ── de onde vêm os arquivos ─────────────────────────────────────────────
    def fonte(self, job: Job) -> FonteZip:
        """ZIP no disco (servidor próprio) ou no Supabase (Vercel)."""
        if settings.storage_mode == "supabase":
            from app.repositorios.supabase import cliente

            caminho = str(job.metadata.get("zipPath") or f"{job.id}/conversa.zip")
            return FonteSupabase(cliente(), caminho, settings)
        return FonteLocal(storage.zip_path(job.id), storage.extract_dir(job.id), settings)

    def _buscador_de_midia(self, job_id: str, fonte: FonteZip):
        """Função que entrega o arquivo da mídia no disco temporário, sob demanda."""

        def obter(event: Event) -> Path | None:
            if not event.attachment_path:
                return None
            destino = nome_temporario(job_id, event.attachment_path, storage.work_dir(job_id))
            try:
                return fonte.obter(event.attachment_path, destino)
            except Exception as exc:
                logger.warning("job=%s não foi possível trazer a mídia: %s", job_id, exc)
                return None

        return obter

    # ── fase 1: motor ───────────────────────────────────────────────────────
    async def parse_job(self, job: Job) -> None:
        """Descompacta, lê o TXT e monta a timeline. Nenhuma chamada de IA aqui."""
        job_id = job.id
        db.update_job(job_id, status=JobStatus.PARSING, error=None)
        extract_root = storage.extract_dir(job_id)
        fonte = self.fonte(job)

        try:
            extraction = await asyncio.to_thread(fonte.catalogar)
        except ZipRejected as exc:
            logger.warning("job=%s zip recusado code=%s", job_id, exc.code)
            db.update_job(job_id, status=JobStatus.FAILED, error=exc.message)
            return
        except FileNotFoundError:
            db.update_job(job_id, status=JobStatus.FAILED, error="O arquivo enviado não foi encontrado.")
            return

        main_txt, choice_log = choose_main_txt(extraction.txt_candidates, fonte.ler_texto)
        if main_txt is None:
            db.update_job(
                job_id,
                status=JobStatus.FAILED,
                error=(
                    "Não encontrei o arquivo de texto da conversa dentro do ZIP. "
                    "Exporte a conversa pelo WhatsApp em 'Exportar conversa' e envie o ZIP gerado."
                ),
            )
            return

        content = await asyncio.to_thread(fonte.ler_texto, main_txt.relative_path)
        parse_result = parse_chat(content)
        timeline = build_timeline(parse_result, extraction.files, extract_root, main_txt.relative_path)

        db.replace_files(job_id, timeline.files)
        db.replace_events(job_id, timeline.events)
        db.replace_links(job_id, timeline.links)

        stamps = [event.timestamp for event in timeline.events if event.timestamp]
        coverage = compute_coverage(timeline.events, timeline.links)
        metadata = {
            "dateOrder": parse_result.date_order,
            "mainTxt": main_txt.original_name or main_txt.name,
            "txtCandidates": choice_log,
            "filesInZip": len(extraction.files),
            "uncompressedBytes": extraction.total_uncompressed,
            "aiEnabled": settings.ai_enabled,
            "ffmpeg": settings.storage_mode != "supabase",
        }

        db.merge_job_metadata(job_id, metadata)
        db.update_job(
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
                db.update_job(job_id, status=JobStatus.PARTIAL, warnings=warnings)
            else:
                db.update_job(job_id, status=JobStatus.COMPLETED, warnings=warnings)
            return

        obter_caminho = None if settings.serverless else (lambda evento: extract_root / evento.attachment_path)
        estimate = await estimate_job(timeline.events, timeline.links, settings, obter_caminho)
        db.update_job(job_id, estimate=estimate)

        if settings.auto_confirm_processing:
            # Decifrar é o serviço; não faz sentido pedir permissão para prestá-lo.
            # O teto de custo por atendimento continua sendo o freio.
            db.update_job(job_id, confirmed=True, status=JobStatus.PROCESSING)
            if settings.serverless:
                # Numa função de curta duração o trabalho avança em blocos: quem
                # continua daqui são as chamadas de tick (tela aberta) e o
                # agendamento automático. Fazer tudo aqui estouraria o tempo.
                return
            refreshed = db.get_job(job_id)
            if refreshed:
                await self.process_job(refreshed)
        else:
            db.update_job(job_id, status=JobStatus.AWAITING_CONFIRMATION)

    def montar_contexto(
        self, job: Job, events: list[Event], provider, fonte: FonteZip | None = None
    ) -> ProcessingContext:
        """Contexto que os processadores recebem, igual nos dois modos de execução."""
        return ProcessingContext(
            job_id=job.id,
            extract_root=storage.extract_dir(job.id),
            work_root=storage.work_dir(job.id),
            settings=settings,
            provider=provider,
            budget=Budget(cap_usd=settings.max_job_cost_usd, spent_usd=job.cost.total_usd),
            conversation_hint=_conversation_hint(events),
            obter_midia=self._buscador_de_midia(job.id, fonte) if fonte is not None else None,
        )

    # ── processamento em blocos curtos (Vercel) ─────────────────────────────
    async def tick(
        self, job: Job, *, budget_seconds: int | None = None, max_items: int | None = None
    ) -> dict:
        """Roda um bloco de trabalho e nunca engole a falha.

        Se algo quebrar aqui, o erro fica registrado no atendimento e aparece na
        tela. Sem isso a pessoa ficaria olhando "processando" para sempre sem
        saber o motivo — que é justamente o que este sistema não pode fazer.
        """
        try:
            resultado = await asyncio.wait_for(
                self._tick(job, budget_seconds=budget_seconds, max_items=max_items),
                timeout=settings.tick_hard_limit_seconds,
            )
        except TimeoutError:
            # Melhor responder "ainda falta tanto" do que ser morto pela
            # hospedagem sem resposta nenhuma: assim a próxima rodada continua.
            logger.warning("job=%s bloco encerrado no limite duro", job.id)
            return {
                "jobId": job.id,
                "status": JobStatus.PROCESSING.value,
                "processados": 0,
                "restantes": self._restantes(job.id),
            }
        except Exception as exc:  # noqa: BLE001 — a falha precisa chegar na tela
            logger.exception("job=%s falha no bloco de processamento", job.id)
            motivo = _sanitize(str(exc)) or exc.__class__.__name__
            db.update_job(
                job.id,
                status=JobStatus.PARTIAL,
                error=f"O processamento parou: {motivo}",
            )
            return {
                "jobId": job.id,
                "status": JobStatus.PARTIAL.value,
                "processados": 0,
                "restantes": self._restantes(job.id),
                "erro": motivo,
            }
        db.update_job(job.id, error=None)
        return resultado

    async def _tick(
        self, job: Job, *, budget_seconds: int | None = None, max_items: int | None = None
    ) -> dict:
        """Processa um punhado de itens e devolve o que ainda falta.

        É o formato que cabe numa função de curta duração: em vez de segurar o
        trabalho inteiro numa chamada só, cada chamada avança um pedaço. Cada
        item é reservado antes, então duas chamadas ao mesmo tempo — a do
        aplicativo aberto e a do agendamento automático — nunca processam o
        mesmo áudio duas vezes.
        """
        limite_tempo = budget_seconds or settings.tick_budget_seconds
        limite_itens = max_items or settings.tick_max_items
        comeco = time.monotonic()
        job_id = job.id

        if job.status in {JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED}:
            return {"jobId": job_id, "status": job.status.value, "processados": 0, "restantes": 0}

        # Uma execução anterior pode ter morrido no meio (a Vercel corta a função
        # aos 60 segundos). Sem devolver o item reservado, ele ficaria parado
        # para sempre e a tela nunca sairia de "processando".
        try:
            db.reclaim_expired(job_id)
        except Exception:
            logger.exception("job=%s falha ao devolver reservas vencidas", job_id)

        events = db.get_events(job_id, with_links=False)
        links = db.get_links(job_id)
        pendentes_eventos = [
            evento for evento in events
            if evento.type.is_media and evento.processing_status == ProcessingStatus.PENDING
        ]
        pendentes_links = [link for link in links if link.status == ProcessingStatus.PENDING]

        if not pendentes_eventos and not pendentes_links:
            return await self._encerrar(job, budget_hit=False)

        if not settings.ai_enabled:
            db.update_job(job_id, status=JobStatus.PARTIAL,
                       error="Nenhum provedor de IA configurado (defina OPENAI_API_KEY).")
            return {"jobId": job_id, "status": JobStatus.PARTIAL.value, "processados": 0,
                    "restantes": len(pendentes_eventos) + len(pendentes_links)}

        db.update_job(job_id, status=JobStatus.PROCESSING, error=None)
        provider = build_provider(settings)
        fonte = self.fonte(job) if settings.serverless else None
        context = self.montar_contexto(job, events, provider, fonte)
        cost = job.cost.model_copy()
        segundos_de_preparo = round(time.monotonic() - comeco, 1)

        # Os itens do bloco correm juntos, respeitando o limite por tipo. Fazer um
        # de cada vez multiplicava a espera pelo número de mídias — três áudios
        # viravam três esperas somadas em vez de uma só.
        semaforos = {
            categoria: asyncio.Semaphore(max(1, getattr(settings, atributo)))
            for categoria, atributo in CONCURRENCY_KEYS.items()
        }
        processados = 0
        budget_hit = False

        # Quanto um item pode demorar. Não é o orçamento do bloco (esse diz até
        # quando vale começar trabalho novo): é o que ainda cabe antes de a
        # resposta precisar sair. Amarrar os dois fazia um item um pouco mais
        # lento que o bloco nunca terminar em tentativa nenhuma.
        teto_do_item = max(10.0, settings.tick_hard_limit_seconds - 8)

        def tempo_restante() -> float:
            gasto = time.monotonic() - comeco
            return max(10.0, min(teto_do_item, settings.tick_hard_limit_seconds - 8 - gasto))

        async def tratar_evento(evento: Event) -> None:
            nonlocal processados, budget_hit
            processador = processor_for(evento.type)
            if processador is None:
                return
            if not db.lease_event(job_id, evento.id, seconds=limite_tempo * 2):
                return  # outra execução pegou este item
            async with semaforos.get(processador.category, semaforos["image"]):
                comecou_o_item = time.monotonic()
                if budget_hit:
                    db.update_event(job_id, evento.id, processing_status=ProcessingStatus.PENDING)
                    return
                try:
                    resultado = await asyncio.wait_for(
                        processador.process(evento, context), timeout=tempo_restante()
                    )
                except TimeoutError:
                    tentativas = int(evento.metadata.get("tentativasPorTempo", 0)) + 1
                    logger.warning(
                        "job=%s event=%s estourou o tempo (tentativa %d)",
                        job_id, evento.index, tentativas,
                    )
                    dados = {**evento.metadata, "tentativasPorTempo": tentativas}
                    if tentativas >= MAX_TENTATIVAS_POR_TEMPO:
                        # Tentar para sempre deixaria a tela girando sem fim e sem
                        # explicação. Melhor dizer que não deu, com o motivo.
                        db.update_event(
                            job_id, evento.id,
                            processing_status=ProcessingStatus.FAILED,
                            processing_error=(
                                f"Não deu tempo de decifrar em {tentativas} tentativas. "
                                "O arquivo continua na conversa, na posição certa."
                            ),
                            metadata=dados,
                        )
                    else:
                        db.update_event(
                            job_id, evento.id,
                            processing_status=ProcessingStatus.PENDING,
                            processing_error=(
                                f"Demorou demais (tentativa {tentativas} de "
                                f"{MAX_TENTATIVAS_POR_TEMPO}); será tentado de novo."
                            ),
                            metadata=dados,
                        )
                    return
                except BudgetExceeded as exc:
                    budget_hit = True
                    db.update_event(job_id, evento.id, processing_status=ProcessingStatus.PENDING,
                                 processing_error=f"Processamento pausado: {exc}")
                    return
                except Exception as exc:
                    logger.exception("job=%s event=%s falha no processador", job_id, evento.index)
                    db.update_event(job_id, evento.id, processing_status=ProcessingStatus.FAILED,
                                 processing_error=_sanitize(str(exc)))
                    processados += 1
                    return
                busca = context.tempo_de_busca.get(evento.id, 0.0)
                total = round(time.monotonic() - comecou_o_item, 1)
                _apply_outcome(
                    job_id, evento, resultado, cost,
                    tempos={"segundos": total, "segundosBuscandoArquivo": busca},
                )
                processados += 1
                logger.info(
                    "job=%s event=%d type=%s status=%s %ss (busca %ss)",
                    job_id, evento.index, evento.type.value, resultado.status.value, total, busca,
                )

        async def tratar_link(link: LinkItem) -> None:
            nonlocal processados
            if budget_hit:
                return
            if not db.lease_link(job_id, link.id, seconds=limite_tempo * 2):
                return
            async with semaforos["link"]:
                try:
                    resultado = await asyncio.wait_for(
                        link_processor().process(link, context), timeout=tempo_restante()
                    )
                except TimeoutError:
                    db.update_link(job_id, link.id, status=ProcessingStatus.PENDING.value,
                                error="Demorou mais que o tempo do bloco; será tentado de novo.")
                    return
                except Exception as exc:
                    logger.exception("job=%s link falha", job_id)
                    db.update_link(job_id, link.id, status=ProcessingStatus.FAILED.value,
                                error=_sanitize(str(exc)))
                    processados += 1
                    return
                db.update_link(job_id, link.id, status=resultado.status.value,
                            title=resultado.metadata.get("title"),
                            description=resultado.metadata.get("description"),
                            content=resultado.text, error=resultado.error,
                            metadata=resultado.metadata)
                processados += 1

        do_bloco = (pendentes_eventos + pendentes_links)[:limite_itens]
        tarefas = [
            tratar_evento(item) if isinstance(item, Event) else tratar_link(item)
            for item in do_bloco
        ]
        try:
            await asyncio.gather(*tarefas)
        finally:
            await provider.aclose()
            if fonte is not None:
                fonte.fechar()

        duracao = round(time.monotonic() - comeco, 1)
        db.update_job(
            job_id,
            cost=cost,
            metadata={
                **(job.metadata or {}),
                "ultimoBloco": {
                    "segundos": duracao,
                    "segundosDePreparo": segundos_de_preparo,
                    "itens": processados,
                },
            },
        )
        atual = db.get_job(job_id) or job
        restantes = self._restantes(job_id)
        if restantes == 0 or budget_hit:
            return await self._encerrar(atual, budget_hit=budget_hit)

        coverage = compute_coverage(db.get_events(job_id, with_links=False), db.get_links(job_id))
        db.update_job(job_id, coverage=coverage)
        return {
            "jobId": job_id,
            "status": JobStatus.PROCESSING.value,
            "processados": processados,
            "restantes": restantes,
            "cobertura": coverage.percent,
            "segundos": duracao,
            "segundosDePreparo": segundos_de_preparo,
        }

    def _restantes(self, job_id: str) -> int:
        """O que ainda falta — incluindo o que está reservado por outra execução.

        Contar só o que está "pendente" fazia o atendimento ser dado por
        encerrado enquanto um item ainda estava reservado, e esse item nunca
        mais era retomado: ficava para sempre sem decifrar num histórico que se
        dizia terminado.
        """
        esperando = {ProcessingStatus.PENDING, ProcessingStatus.PROCESSING}
        eventos = db.get_events(job_id, with_links=False)
        links = db.get_links(job_id)
        return sum(
            1 for evento in eventos
            if evento.type.is_media and evento.processing_status in esperando
        ) + sum(1 for link in links if link.status in esperando)

    async def _encerrar(self, job: Job, *, budget_hit: bool) -> dict:
        """Fecha o atendimento: cobertura final e status honesto."""
        job_id = job.id
        eventos = db.get_events(job_id, with_links=False)
        links = db.get_links(job_id)
        coverage = compute_coverage(eventos, links)
        avisos = [aviso for aviso in job.warnings if aviso.code != "budget"]
        if budget_hit:
            avisos.append(
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
        db.update_job(job_id, status=status, coverage=coverage, warnings=avisos)
        logger.info("job=%s encerrado status=%s cobertura=%.1f%%", job_id, status.value, coverage.percent)
        return {
            "jobId": job_id,
            "status": status.value,
            "processados": 0,
            "restantes": 0,
            "cobertura": coverage.percent,
        }

    # ── fase 2: inteligência ────────────────────────────────────────────────
    async def process_job(
        self, job: Job, *, retry_failed: bool = False, only_event: str | None = None
    ) -> None:
        """Processa as mídias pendentes com semáforo por tipo e teto de custo."""
        job_id = job.id
        events = db.get_events(job_id, with_links=False)
        links = db.get_links(job_id)

        if not settings.ai_enabled and _needs_ai(events, links, retry_failed, only_event):
            db.update_job(
                job_id,
                status=JobStatus.PARTIAL,
                error="Nenhum provedor de IA configurado (defina OPENAI_API_KEY).",
            )
            return

        db.update_job(job_id, status=JobStatus.PROCESSING, error=None)
        provider = build_provider(settings)
        fonte = self.fonte(job) if settings.serverless else None
        context = self.montar_contexto(job, events, provider, fonte)

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
                db.update_event(job_id, event.id, processing_status=ProcessingStatus.PROCESSING)
                try:
                    outcome = await processor.process(event, context)
                except BudgetExceeded as exc:
                    budget_hit = True
                    db.update_event(
                        job_id, event.id,
                        processing_status=ProcessingStatus.PENDING,
                        processing_error=f"Processamento pausado: {exc}",
                    )
                    return
                except Exception as exc:  # falha isolada nunca derruba o job
                    logger.exception("job=%s event=%s falha no processador", job_id, event.index)
                    db.update_event(
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
                db.update_link(job_id, link.id, status=ProcessingStatus.PROCESSING.value)
                try:
                    outcome = await link_processor().process(link, context)
                except Exception as exc:
                    logger.exception("job=%s link falha", job_id)
                    db.update_link(
                        job_id, link.id,
                        status=ProcessingStatus.FAILED.value,
                        error=_sanitize(str(exc)),
                    )
                    return
                db.update_link(
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

        final_events = db.get_events(job_id, with_links=False)
        final_links = db.get_links(job_id)
        coverage = compute_coverage(final_events, final_links)
        db.update_job(job_id, coverage=coverage, cost=cost)

        if self.is_cancelled(job_id):
            db.update_job(job_id, status=JobStatus.CANCELLED)
            self._cancelled.discard(job_id)
            return

        warnings = [w for w in (db.get_job(job_id) or job).warnings if w.code != "budget"]
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
        db.update_job(job_id, status=status, warnings=warnings)
        logger.info(
            "job=%s processamento encerrado status=%s cobertura=%.1f%% custo=%.4f",
            job_id, status.value, coverage.percent, cost.total_usd,
        )


def _apply_outcome(
    job_id: str,
    event: Event,
    outcome: ProcessingOutcome,
    cost: CostBreakdown,
    tempos: dict | None = None,
) -> None:
    metadata = dict(event.metadata or {})
    metadata.update(outcome.metadata or {})
    if tempos:
        metadata.update(tempos)
    if outcome.cost_usd:
        add_cost(cost, outcome.category, outcome.cost_usd)
    db.update_event(
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
    for job in db.expired_jobs(settings.job_retention_hours):
        logger.info("job=%s removido por retenção", job.id)
        storage.purge_job(job.id)
        db.delete_job(job.id)


runner = JobRunner()
