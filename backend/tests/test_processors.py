"""Testes dos processadores de mídia, com provedor de IA falso."""

from __future__ import annotations

import shutil
import subprocess

import httpx
import pytest

from app.config import settings
from app.models.schemas import Event, EventType, LinkItem, ProcessingStatus
from app.processors.audio import AudioProcessor, needs_conversion
from app.processors.base import Budget, BudgetExceeded, ProcessingContext
from app.processors.document import DocumentProcessor
from app.processors.image import ImageProcessor
from app.processors.link import BlockedURL, LinkProcessor, assert_public_url, extract_readable
from app.processors.pdf import PdfProcessor
from app.processors.video import VideoProcessor
from tests.conftest import MEDIA
from tests.fakes import FakeProvider

TEM_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
precisa_ffmpeg = pytest.mark.skipif(not TEM_FFMPEG, reason="FFmpeg não instalado neste ambiente")


def make_context(tmp_path, provider=None, cap=5.0, **overrides):
    extract_root = tmp_path / "extraido"
    extract_root.mkdir(exist_ok=True)
    config = settings.model_copy(update=overrides) if overrides else settings
    return ProcessingContext(
        job_id="teste",
        extract_root=extract_root,
        work_root=tmp_path / "trabalho",
        settings=config,
        provider=provider or FakeProvider(),
        budget=Budget(cap_usd=cap),
        conversation_hint="Sanchai, Rui",
    )


def make_event(tmp_path, source_name: str, event_type: EventType, mime: str) -> Event:
    destination = tmp_path / "extraido" / source_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(MEDIA / source_name, destination)
    return Event(
        id="evento-1",
        index=1,
        raw_timestamp="25/08/2026 10:52",
        sender="Sanchai",
        type=event_type,
        attachment_name=source_name,
        attachment_path=source_name,
        detected_mime=mime,
        processing_status=ProcessingStatus.PENDING,
    )


# ── Áudio ───────────────────────────────────────────────────────────────────
def test_opus_precisa_de_conversao(tmp_path):
    from pathlib import Path

    assert needs_conversion(Path("PTT-0001.opus"), "audio/ogg") is True
    assert needs_conversion(Path("audio.mp3"), "audio/mpeg") is False
    assert needs_conversion(Path("audio.mp3"), "audio/ogg") is True


@precisa_ffmpeg
async def test_transcricao_de_audio_curto(tmp_path):
    provider = FakeProvider(transcript="boa tarde seu Rui")
    context = make_context(tmp_path, provider)
    event = make_event(tmp_path, "audio.opus", EventType.AUDIO, "audio/ogg")

    outcome = await AudioProcessor().process(event, context)

    assert outcome.status == ProcessingStatus.DONE
    assert outcome.text == "boa tarde seu Rui"
    assert outcome.metadata["chunks"] == 1
    assert outcome.metadata["duration_seconds"] > 0
    assert len(provider.transcribe_calls) == 1


@precisa_ffmpeg
async def test_audio_grande_e_dividido_e_unido_na_ordem(tmp_path):
    longo = tmp_path / "extraido" / "longo.opus"
    longo.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=25", "-c:a", "libopus", "-b:a", "16k", str(longo)],
        check=True,
    )
    provider = FakeProvider(transcript="pedaço")
    context = make_context(tmp_path, provider, audio_chunk_seconds=10)
    event = Event(
        id="e", index=0, raw_timestamp="x", type=EventType.AUDIO,
        attachment_name="longo.opus", attachment_path="longo.opus", detected_mime="audio/ogg",
        processing_status=ProcessingStatus.PENDING,
    )

    outcome = await AudioProcessor().process(event, context)

    assert outcome.status == ProcessingStatus.DONE
    assert outcome.metadata["chunks"] >= 3
    linhas = outcome.text.splitlines()
    assert linhas == sorted(linhas), "os pedaços precisam sair na ordem original"
    assert "chunk-000" in linhas[0]


@precisa_ffmpeg
async def test_falha_do_provedor_nao_apaga_o_evento(tmp_path):
    provider = FakeProvider(permanent_failure=True)
    context = make_context(tmp_path, provider)
    event = make_event(tmp_path, "audio.opus", EventType.AUDIO, "audio/ogg")

    outcome = await AudioProcessor().process(event, context)

    assert outcome.status == ProcessingStatus.FAILED
    assert "Transcrição não concluída" in outcome.error


async def test_audio_sem_arquivo_fica_nao_associado(tmp_path):
    context = make_context(tmp_path)
    event = Event(id="e", index=0, raw_timestamp="x", type=EventType.AUDIO,
                  attachment_name="sumiu.opus", processing_status=ProcessingStatus.PENDING)
    outcome = await AudioProcessor().process(event, context)
    assert outcome.status == ProcessingStatus.UNRESOLVED


# ── Imagem ──────────────────────────────────────────────────────────────────
async def test_imagem_com_texto_legivel(tmp_path):
    provider = FakeProvider(visible_text="Sala 705 — R$ 4.200,00", description="print de proposta")
    context = make_context(tmp_path, provider)
    event = make_event(tmp_path, "imagem.jpg", EventType.IMAGE, "image/jpeg")
    event.caption = "Olha essa condição"

    outcome = await ImageProcessor().process(event, context)

    assert outcome.status == ProcessingStatus.DONE
    assert outcome.metadata["ocr_text"] == "Sala 705 — R$ 4.200,00"
    assert outcome.metadata["visual_description"] == "print de proposta"
    assert outcome.cost_usd > 0
    assert provider.vision_calls[0][1] == "image"


async def test_imagem_ilegivel_nao_inventa_conteudo(tmp_path):
    provider = FakeProvider(visible_text="", description="")
    context = make_context(tmp_path, provider)
    event = make_event(tmp_path, "imagem.jpg", EventType.IMAGE, "image/jpeg")

    outcome = await ImageProcessor().process(event, context)

    assert outcome.text == "[imagem sem conteúdo identificável]"
    assert outcome.metadata["ocr_text"] == ""


async def test_imagem_em_formato_nao_suportado(tmp_path):
    context = make_context(tmp_path)
    event = make_event(tmp_path, "imagem.jpg", EventType.IMAGE, "image/tiff")
    outcome = await ImageProcessor().process(event, context)
    assert outcome.status == ProcessingStatus.UNSUPPORTED


async def test_teto_de_custo_interrompe_antes_de_gastar(tmp_path):
    context = make_context(tmp_path, cap=0.0000001)
    event = make_event(tmp_path, "imagem.jpg", EventType.IMAGE, "image/jpeg")
    with pytest.raises(BudgetExceeded):
        await ImageProcessor().process(event, context)


# ── PDF ─────────────────────────────────────────────────────────────────────
async def test_pdf_com_texto_extraivel_nao_usa_visao(tmp_path):
    provider = FakeProvider()
    context = make_context(tmp_path, provider, pdf_min_chars_per_page=10)
    event = make_event(tmp_path, "documento.pdf", EventType.PDF, "application/pdf")

    outcome = await PdfProcessor().process(event, context)

    assert outcome.status == ProcessingStatus.DONE
    assert "Página 1:" in outcome.text
    assert "R$ 4.200,00" in outcome.text
    assert outcome.metadata["pages_count"] == 2
    assert provider.vision_calls == []


async def test_pdf_escaneado_usa_visao_por_pagina(tmp_path):
    import pymupdf

    escaneado = tmp_path / "extraido" / "escaneado.pdf"
    escaneado.parent.mkdir(parents=True, exist_ok=True)
    documento = pymupdf.open()
    documento.new_page()
    documento.save(escaneado)
    documento.close()

    provider = FakeProvider(visible_text="TEXTO DA PÁGINA ESCANEADA", description="folha escaneada")
    context = make_context(tmp_path, provider)
    event = Event(id="e", index=0, raw_timestamp="x", type=EventType.PDF,
                  attachment_name="escaneado.pdf", attachment_path="escaneado.pdf",
                  detected_mime="application/pdf", processing_status=ProcessingStatus.PENDING)

    outcome = await PdfProcessor().process(event, context)

    assert outcome.status == ProcessingStatus.DONE
    assert "TEXTO DA PÁGINA ESCANEADA" in outcome.text
    assert outcome.metadata["pages"][0]["source"] == "vision"
    assert provider.vision_calls[0][1] == "pdf_page"


# ── Vídeo ───────────────────────────────────────────────────────────────────
@precisa_ffmpeg
async def test_video_transcreve_audio_e_descreve_quadros(tmp_path):
    provider = FakeProvider(transcript="fala do vídeo", visible_text="", description="cena de teste")
    context = make_context(tmp_path, provider, video_max_frames=3)
    event = make_event(tmp_path, "video.mp4", EventType.VIDEO, "video/mp4")

    outcome = await VideoProcessor().process(event, context)

    assert outcome.status == ProcessingStatus.DONE
    assert "fala do vídeo" in outcome.text
    assert "Quadro 1" in outcome.text
    assert 0 < outcome.metadata["frames"] <= 3
    assert outcome.metadata["transcript"] == "fala do vídeo"


# ── Documentos ──────────────────────────────────────────────────────────────
async def test_documento_de_texto_e_lido_localmente(tmp_path):
    caminho = tmp_path / "extraido" / "notas.txt"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("condições combinadas", encoding="utf-8")
    context = make_context(tmp_path)
    event = Event(id="e", index=0, raw_timestamp="x", type=EventType.DOCUMENT,
                  attachment_name="notas.txt", attachment_path="notas.txt",
                  detected_mime="text/plain", processing_status=ProcessingStatus.PENDING)

    outcome = await DocumentProcessor().process(event, context)

    assert outcome.status == ProcessingStatus.DONE
    assert outcome.text == "condições combinadas"


# ── Links ───────────────────────────────────────────────────────────────────
def test_ssrf_bloqueia_enderecos_internos():
    for url in (
        "http://127.0.0.1:8000/admin",
        "http://localhost/",
        "file:///etc/passwd",
        "ftp://exemplo.com/arquivo",
    ):
        with pytest.raises(BlockedURL):
            assert_public_url(url)


async def test_link_bloqueado_preserva_url(tmp_path):
    context = make_context(tmp_path)
    link = LinkItem(id="l1", event_id="e1", url="http://192.168.0.10/interno")
    outcome = await LinkProcessor().process(link, context)
    assert outcome.status == ProcessingStatus.FAILED
    assert outcome.metadata.get("blocked") is True
    assert link.url == "http://192.168.0.10/interno"


async def test_link_valido_extrai_titulo_e_conteudo(tmp_path, monkeypatch):
    html = """
    <html><head><title>Proposta comercial</title>
    <meta name="description" content="Sala 705 no Premium Office"></head>
    <body><script>ignore()</script><article>Valor total de R$ 4.200,00 em 12 parcelas.</article>
    </body></html>
    """

    async def fake_fetch(url, timeout, limit_bytes):
        return 200, url, "text/html", html

    monkeypatch.setattr("app.processors.link._fetch", fake_fetch)
    context = make_context(tmp_path)
    link = LinkItem(id="l1", event_id="e1", url="https://exemplo.com/proposta")

    outcome = await LinkProcessor().process(link, context)

    assert outcome.status == ProcessingStatus.DONE
    assert outcome.metadata["title"] == "Proposta comercial"
    assert outcome.metadata["description"] == "Sala 705 no Premium Office"
    assert "R$ 4.200,00" in outcome.text
    assert "ignore()" not in outcome.text


async def test_link_com_timeout_registra_falha(tmp_path, monkeypatch):
    async def fake_fetch(url, timeout, limit_bytes):
        raise httpx.TimeoutException("demorou demais")

    monkeypatch.setattr("app.processors.link._fetch", fake_fetch)
    context = make_context(tmp_path)
    outcome = await LinkProcessor().process(
        LinkItem(id="l1", event_id="e1", url="https://exemplo.com/lento"), context
    )
    assert outcome.status == ProcessingStatus.FAILED
    assert "tempo limite" in outcome.error


def test_extracao_de_conteudo_legivel_ignora_navegacao():
    html = "<html><body><nav>menu</nav><main>conteúdo útil</main><footer>rodapé</footer></body></html>"
    _title, _description, content = extract_readable(html)
    assert "conteúdo útil" in content
    assert "menu" not in content and "rodapé" not in content


# ── Provedor: retry ─────────────────────────────────────────────────────────
async def test_provedor_repete_em_erro_temporario(tmp_path, monkeypatch):
    from app.providers.openai_provider import OpenAIProvider

    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            return httpx.Response(429, json={"error": {"message": "rate limit"}})
        return httpx.Response(200, json={"text": "transcrição depois do retry"})

    config = settings.model_copy(update={"openai_api_key": "chave-de-teste"})
    provider = OpenAIProvider(config)
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://provedor.teste/v1"
    )
    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"\xff\xfb\x00")
    result = await provider.transcribe(audio)

    assert result.text == "transcrição depois do retry"
    assert chamadas["n"] == 2
    await provider.aclose()


async def test_provedor_nao_repete_em_erro_permanente(tmp_path):
    from app.providers.base import ProviderError
    from app.providers.openai_provider import OpenAIProvider

    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        return httpx.Response(400, json={"error": {"message": "arquivo inválido"}})

    provider = OpenAIProvider(settings.model_copy(update={"openai_api_key": "x"}))
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://provedor.teste/v1"
    )
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"\xff\xfb\x00")

    with pytest.raises(ProviderError) as excinfo:
        await provider.transcribe(audio)
    assert chamadas["n"] == 1
    assert excinfo.value.retryable is False
    await provider.aclose()


async def _no_sleep(_seconds):
    return None
