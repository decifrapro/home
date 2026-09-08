"""Estimativa e contabilidade de custo das chamadas de IA.

A estimativa não precisa ser exata; precisa ser honesta o bastante para o
usuário decidir se quer gastar antes de o processamento começar.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from app.config import Settings
from app.models.schemas import CostBreakdown, CostEstimate, Event, EventType, LinkItem
from app.services.media import disponivel as ffmpeg_disponivel
from app.services.media import estimar_duracao, probe

logger = logging.getLogger(__name__)

# Aproximações usadas só para estimar. O custo real registrado por evento vem do
# consumo informado pelo provedor.
VISION_INPUT_TOKENS_PER_IMAGE = 1_200
VISION_OUTPUT_TOKENS_PER_IMAGE = 450


def vision_call_cost(settings: Settings, input_tokens: float, output_tokens: float) -> float:
    return round(
        input_tokens / 1_000_000 * settings.price_vision_input_per_mtok
        + output_tokens / 1_000_000 * settings.price_vision_output_per_mtok,
        6,
    )


def transcription_cost(settings: Settings, seconds: float) -> float:
    return round(seconds / 60 * settings.price_transcription_per_minute, 6)


def _image_estimate(settings: Settings, quantity: int) -> float:
    return round(
        quantity
        * vision_call_cost(settings, VISION_INPUT_TOKENS_PER_IMAGE, VISION_OUTPUT_TOKENS_PER_IMAGE),
        6,
    )


def pdf_pages_needing_vision(path: Path, settings: Settings) -> tuple[int, int]:
    """(total de páginas, páginas com pouco texto extraível).

    A leitura local com PyMuPDF é gratuita; só as páginas pobres em texto custam
    dinheiro, porque precisam ser vistas por um modelo de visão.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:  # pragma: no cover
        return (0, 0)
    try:
        with fitz.open(path) as document:
            total = min(document.page_count, settings.pdf_max_pages)
            poor = 0
            for number in range(total):
                text = document.load_page(number).get_text("text") or ""
                if len(text.strip()) < settings.pdf_min_chars_per_page:
                    poor += 1
            return (total, poor)
    except Exception as exc:  # PDF corrompido ou protegido
        logger.debug("não foi possível inspecionar o PDF: %s", exc)
        return (0, 0)


async def estimate_job(
    events: list[Event],
    links: list[LinkItem],
    settings: Settings,
    obter_caminho: Callable[[Event], Path | None] | None = None,
) -> CostEstimate:
    """Percorre as mídias pendentes e calcula quanto custaria processá-las.

    Quando `obter_caminho` é dado (servidor próprio, arquivos em disco), a conta
    usa a duração real do áudio e o número de páginas de PDF que precisam de
    visão. Sem ele (Vercel, arquivos no Supabase), a conta é feita pelo tamanho
    do arquivo — mais grosseira, e o texto na tela avisa isso.
    """
    estimate = CostEstimate(cap_usd=settings.max_job_cost_usd)
    breakdown = CostBreakdown()

    for event in events:
        if not event.attachment_path:
            continue
        path = obter_caminho(event) if obter_caminho else None
        if obter_caminho and (path is None or not path.exists()):
            continue
        if path is None:
            _estimar_sem_arquivo(event, estimate, breakdown, settings)
            continue

        if event.type == EventType.AUDIO:
            info = await probe(path)
            seconds = info.duration_seconds or estimar_duracao(
                path.stat().st_size, event.detected_mime
            )
            estimate.audio_seconds += seconds
            breakdown.audio_usd += transcription_cost(settings, seconds)
        elif event.type == EventType.IMAGE:
            estimate.images += 1
            breakdown.image_usd += _image_estimate(settings, 1)
        elif event.type == EventType.PDF:
            total, poor = pdf_pages_needing_vision(path, settings)
            estimate.pdf_pages += total
            breakdown.pdf_usd += _image_estimate(settings, poor)
        elif event.type == EventType.VIDEO:
            if not ffmpeg_disponivel():
                continue  # vídeo não é analisado nesta instalação: não custa nada
            info = await probe(path)
            seconds = info.duration_seconds or 0
            frames = min(settings.video_max_frames, max(3, int(seconds // 20) + 3))
            estimate.video_seconds += seconds
            estimate.video_frames += frames
            breakdown.video_usd += transcription_cost(settings, seconds) + _image_estimate(
                settings, frames
            )

    estimate.links = len([link for link in links if link.status.value == "pending"])
    estimate.breakdown = CostBreakdown(
        audio_usd=round(breakdown.audio_usd, 4),
        image_usd=round(breakdown.image_usd, 4),
        pdf_usd=round(breakdown.pdf_usd, 4),
        video_usd=round(breakdown.video_usd, 4),
        link_usd=0.0,
    )
    estimate.total_usd = estimate.breakdown.total_usd
    estimate.exceeds_cap = estimate.total_usd > settings.max_job_cost_usd

    if estimate.links:
        estimate.notes.append(
            "A leitura de links é feita no próprio servidor e não consome crédito de IA."
        )
    if any(event.type == EventType.PDF for event in events):
        estimate.notes.append(
            "PDFs entram por leitura de texto, que é gratuita. Se alguma página for "
            "escaneada, ela passa por visão e aparece no custo real no fim."
        )
    if not ffmpeg_disponivel():
        estimate.notes.append(
            "Esta instalação roda sem FFmpeg: vídeos não são analisados e áudios muito "
            "grandes ficam de fora, então eles não entram na conta."
        )
    if estimate.pdf_pages:
        estimate.notes.append(
            "Páginas de PDF com texto extraível são lidas localmente, sem custo; "
            "só as páginas escaneadas passam por visão."
        )
    if estimate.exceeds_cap:
        estimate.notes.append(
            f"A estimativa passa do teto configurado de US$ {settings.max_job_cost_usd:.2f}. "
            "O processamento vai parar ao atingir o teto e o atendimento ficará parcial."
        )
    return estimate


def _estimar_sem_arquivo(
    event: Event, estimate: CostEstimate, breakdown: CostBreakdown, settings: Settings
) -> None:
    """Conta aproximada quando o arquivo não está em disco: vale o tamanho dele."""
    tamanho = int((event.metadata or {}).get("file_size") or 0)
    if event.type == EventType.AUDIO:
        segundos = estimar_duracao(tamanho, event.detected_mime)
        estimate.audio_seconds += segundos
        breakdown.audio_usd += transcription_cost(settings, segundos)
    elif event.type == EventType.IMAGE:
        estimate.images += 1
        breakdown.image_usd += _image_estimate(settings, 1)
    elif event.type == EventType.PDF:
        # Sem abrir o arquivo não dá para saber quantas páginas precisam de visão.
        # A leitura de texto é gratuita, então a estimativa fica em zero e o aviso
        # na tela explica que página escaneada pode custar.
        estimate.pdf_pages += 0


def add_cost(total: CostBreakdown, category: str, amount: float) -> CostBreakdown:
    field = f"{category}_usd"
    if hasattr(total, field):
        setattr(total, field, round(getattr(total, field) + amount, 6))
    return total
