"""O caminho da Vercel, do começo ao fim, com Supabase de mentira.

Cobre o fluxo real: pedir o link de envio, mandar o ZIP para o armazenamento,
ler a conversa direto de lá por faixas de bytes, processar em blocos curtos e
exportar — tudo sem disco e sem FFmpeg, como acontece na Vercel.
"""

from __future__ import annotations

import pytest

from app import db
from app.models.schemas import JobStatus, ProcessingStatus
from tests.conftest import MEDIA
from tests.fake_supabase import FakeSupabaseClient
from tests.fakes import FakeProvider

CHAT = """‎25/08/2026 10:40 - As mensagens e as chamadas são criptografadas de ponta a ponta.
25/08/2026 10:45 - Sanchai: Boa tarde, Sr. Rui
25/08/2026 10:52 - Sanchai: audio.opus (arquivo anexado)
25/08/2026 11:03 - Rui: imagem.jpg (arquivo anexado)
Olha essa condição
25/08/2026 11:10 - Sanchai: documento.pdf (arquivo anexado)
25/08/2026 12:00 - Rui: video.mp4 (arquivo anexado)
25/08/2026 12:05 - Rui: veja https://exemplo.com/proposta
"""

ARQUIVOS = {
    "audio.opus": MEDIA / "audio.opus",
    "imagem.jpg": MEDIA / "imagem.jpg",
    "documento.pdf": MEDIA / "documento.pdf",
    "video.mp4": MEDIA / "video.mp4",
    "orfao.jpg": MEDIA / "orfao.jpg",
}


@pytest.fixture
def nuvem(monkeypatch, make_zip):
    """Liga o modo Supabase, sem FFmpeg, com um provedor de IA de mentira."""
    cliente = FakeSupabaseClient()

    monkeypatch.setattr("app.config.settings.supabase_url", "https://projeto.supabase.co")
    monkeypatch.setattr("app.config.settings.supabase_service_key", "chave-de-servico")
    monkeypatch.setattr("app.config.settings.openai_api_key", "chave-fake")
    monkeypatch.setattr("app.repositorios.supabase._cliente", cliente, raising=False)
    monkeypatch.setattr("app.repositorios.supabase.cliente", lambda: cliente)
    # Na Vercel não existe FFmpeg.
    monkeypatch.setattr("app.services.media.disponivel", lambda: False)
    monkeypatch.setattr("app.processors.audio.ffmpeg_disponivel", lambda: False)
    monkeypatch.setattr("app.processors.video.ffmpeg_disponivel", lambda: False)
    monkeypatch.setattr("app.services.cost.ffmpeg_disponivel", lambda: False)

    provedor = FakeProvider(transcript="boa tarde, seu Rui")
    monkeypatch.setattr("app.jobs.worker.build_provider", lambda _s: provedor)

    async def link_falso(url, timeout, limite):
        return 200, url, "text/html", "<html><title>Proposta</title><body>Sala 705</body></html>"

    monkeypatch.setattr("app.processors.link._fetch", link_falso)

    assert db.backend == "supabase"
    return cliente, provedor, make_zip


def _subir(cliente, client, zip_path) -> str:
    """Faz o que o celular faz: pede o link, envia o arquivo e avisa o servidor."""
    job_id = client.post("/api/jobs").json()["id"]
    conteudo = zip_path.read_bytes()

    link = client.post(
        f"/api/jobs/{job_id}/upload/link",
        json={"filename": zip_path.name, "size": len(conteudo)},
    )
    assert link.status_code == 200, link.text
    caminho = link.json()["path"]
    assert "token" in link.json()["uploadUrl"]

    cliente.upload(caminho, conteudo)  # o navegador envia direto para o armazenamento
    return job_id


async def test_fluxo_completo_no_modo_vercel(nuvem, client):
    cliente, provedor, make_zip = nuvem
    zip_path = make_zip(CHAT, ARQUIVOS, name="Conversa do WhatsApp com Cliente.zip")
    job_id = _subir(cliente, client, zip_path)

    resposta = client.post(f"/api/jobs/{job_id}/upload/registrado")
    assert resposta.status_code == 200, resposta.text
    job = resposta.json()

    # A conversa foi lida direto do armazenamento, sem baixar o ZIP inteiro.
    assert cliente.leituras_por_faixa > 0
    assert job["inventory"]["audio"] == 1
    assert job["inventory"]["image"] == 1
    assert job["inventory"]["pdf"] == 1
    assert job["inventory"]["video"] == 1
    assert job["inventory"]["orphanFiles"] == 1
    assert job["status"] == JobStatus.AWAITING_CONFIRMATION.value
    assert job["estimate"]["total_usd"] >= 0

    # O usuário autoriza o gasto.
    assert client.post(f"/api/jobs/{job_id}/confirm").json()["modo"] == "tick"

    # O aplicativo vai empurrando o trabalho em blocos.
    for _ in range(10):
        resultado = client.post(f"/api/jobs/{job_id}/tick").json()
        if resultado["restantes"] == 0:
            break
    assert resultado["restantes"] == 0

    eventos = client.get(f"/api/jobs/{job_id}/events").json()["events"]
    audio = next(e for e in eventos if e["type"] == "audio")
    imagem = next(e for e in eventos if e["type"] == "image")
    pdf = next(e for e in eventos if e["type"] == "pdf")
    video = next(e for e in eventos if e["type"] == "video")

    assert audio["processingStatus"] == "done"
    assert audio["processedText"] == "boa tarde, seu Rui"
    assert provedor.transcribe_calls[0].suffix == ".ogg", "o .opus vai como .ogg, sem converter"
    assert imagem["processingStatus"] == "done"
    assert imagem["metadata"]["ocrText"]
    assert pdf["processingStatus"] == "done"
    assert "R$ 4.200,00" in pdf["processedText"]
    assert video["processingStatus"] == "unsupported"
    assert "sem FFmpeg" in video["processingError"]

    link = next(e for e in eventos if e["links"])["links"][0]
    assert link["status"] == "done"
    assert link["title"] == "Proposta"

    # Vídeo não analisado = cobertura honestamente abaixo de 100%.
    final = client.get(f"/api/jobs/{job_id}").json()
    assert final["status"] == JobStatus.PARTIAL.value
    assert final["coverage"]["percent"] < 100
    assert final["cost"]["totalUsd"] > 0

    # Exportações continuam funcionando no modo nuvem.
    txt = client.get(f"/api/jobs/{job_id}/export/txt").text
    assert "boa tarde, seu Rui" in txt
    assert "[MÍDIA NÃO PROCESSADA]" in txt  # o vídeo aparece, com o motivo escrito
    assert "sem FFmpeg" in txt
    dados = client.get(f"/api/jobs/{job_id}/export/json").json()
    assert len(dados["events"]) == 7
    assert dados["schemaVersion"] == 2


async def test_decifra_sozinho_sem_pedir_confirmacao(nuvem, client, monkeypatch):
    """Decifrar é o serviço: ninguém precisa clicar num botão para recebê-lo."""
    monkeypatch.setattr("app.config.settings.auto_confirm_processing", True)
    cliente, _provedor, make_zip = nuvem
    job_id = _subir(cliente, client, make_zip(CHAT, ARQUIVOS))

    job = client.post(f"/api/jobs/{job_id}/upload/registrado").json()
    assert job["status"] == JobStatus.PROCESSING.value  # já saiu decifrando

    for _ in range(10):
        resultado = client.post(f"/api/jobs/{job_id}/tick").json()
        if resultado["restantes"] == 0:
            break
    assert resultado["restantes"] == 0
    audio = next(e for e in client.get(f"/api/jobs/{job_id}/events").json()["events"]
                 if e["type"] == "audio")
    assert audio["processingStatus"] == "done"


async def test_item_preso_por_execucao_interrompida_volta_para_a_fila(nuvem, client):
    """A função da Vercel morre aos 60 s; o item reservado não pode ficar preso."""
    from datetime import UTC, datetime, timedelta

    cliente, _provedor, make_zip = nuvem
    job_id = _subir(cliente, client, make_zip(CHAT, ARQUIVOS))
    client.post(f"/api/jobs/{job_id}/upload/registrado")
    client.post(f"/api/jobs/{job_id}/confirm")

    audio = next(e for e in db.get_events(job_id) if e.type.value == "audio")
    vencido = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    cliente.update_returning(
        "decifra_events",
        {"job_id": f"eq.{job_id}", "id": f"eq.{audio.id}"},
        {"processing_status": "processing", "leased_until": vencido},
    )

    for _ in range(10):
        if client.post(f"/api/jobs/{job_id}/tick").json()["restantes"] == 0:
            break

    audio = next(e for e in db.get_events(job_id) if e.type.value == "audio")
    assert audio.processing_status == ProcessingStatus.DONE


async def test_atendimento_nao_se_diz_pronto_com_item_reservado(nuvem, client):
    """Item reservado por outra execução ainda é trabalho: o bloco não encerra."""
    from datetime import UTC, datetime, timedelta

    cliente, _provedor, make_zip = nuvem
    job_id = _subir(cliente, client, make_zip(CHAT, ARQUIVOS))
    client.post(f"/api/jobs/{job_id}/upload/registrado")
    client.post(f"/api/jobs/{job_id}/confirm")

    # Alguém está com a imagem na mão, reserva ainda válida.
    imagem = next(e for e in db.get_events(job_id) if e.type.value == "image")
    futuro = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    cliente.update_returning(
        "decifra_events",
        {"job_id": f"eq.{job_id}", "id": f"eq.{imagem.id}"},
        {"processing_status": "processing", "leased_until": futuro},
    )

    resultado = client.post(f"/api/jobs/{job_id}/tick").json()
    assert resultado["restantes"] >= 1, "a imagem reservada não pode sumir da conta"
    assert db.get_job(job_id).status == JobStatus.PROCESSING


async def test_agendamento_continua_o_trabalho_com_o_app_fechado(nuvem, client):
    cliente, _provedor, make_zip = nuvem
    zip_path = make_zip(CHAT, ARQUIVOS)
    job_id = _subir(cliente, client, zip_path)
    client.post(f"/api/jobs/{job_id}/upload/registrado")
    client.post(f"/api/jobs/{job_id}/confirm")

    # Ninguém abre o aplicativo: só o agendamento roda.
    for _ in range(10):
        client.get("/api/cron/tick")
        if db.get_job(job_id).status != JobStatus.PROCESSING:
            break

    job = db.get_job(job_id)
    assert job.status in {JobStatus.PARTIAL, JobStatus.COMPLETED}
    assert all(
        evento.processing_status != ProcessingStatus.PENDING
        for evento in db.get_events(job_id)
        if evento.type.is_media
    )


async def test_apagar_atendimento_limpa_banco_e_arquivos(nuvem, client):
    cliente, _provedor, make_zip = nuvem
    zip_path = make_zip(CHAT, ARQUIVOS)
    job_id = _subir(cliente, client, zip_path)
    client.post(f"/api/jobs/{job_id}/upload/registrado")

    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    assert db.get_job(job_id) is None
    assert db.get_events(job_id) == []
    assert not [caminho for caminho in cliente.arquivos if caminho.startswith(job_id)]


async def test_cron_protegido_por_segredo(nuvem, client, monkeypatch):
    monkeypatch.setattr("app.config.settings.cron_secret", "segredo")
    assert client.get("/api/cron/tick").status_code == 401
    assert client.get("/api/cron/tick", headers={"Authorization": "Bearer segredo"}).status_code == 200
    assert client.get("/api/cron/tick", headers={"x-vercel-cron": "1"}).status_code == 200


async def test_item_que_nunca_cabe_no_tempo_vira_falha_declarada(nuvem, client, monkeypatch):
    """Tentar para sempre deixaria a tela girando sem fim. Melhor dizer que não deu."""
    import asyncio

    from app.jobs.worker import MAX_TENTATIVAS_POR_TEMPO
    from app.models.schemas import EventType
    from app.processors import registry

    cliente, _provedor, make_zip = nuvem
    job_id = _subir(cliente, client, make_zip(CHAT, ARQUIVOS))
    client.post(f"/api/jobs/{job_id}/upload/registrado")
    client.post(f"/api/jobs/{job_id}/confirm")

    # Um áudio que nunca termina dentro da janela da hospedagem.
    original = registry.processor_for

    class NuncaTermina:
        category = "audio"

        async def process(self, evento, contexto):
            await asyncio.sleep(3600)

    monkeypatch.setattr(
        "app.jobs.worker.processor_for",
        lambda tipo: NuncaTermina() if tipo is EventType.AUDIO else original(tipo),
    )
    monkeypatch.setattr("app.config.settings.tick_hard_limit_seconds", 11)

    for _ in range(MAX_TENTATIVAS_POR_TEMPO + 2):
        client.post(f"/api/jobs/{job_id}/tick")

    audio = next(e for e in db.get_events(job_id) if e.type is EventType.AUDIO)
    assert audio.processing_status == ProcessingStatus.FAILED
    assert "tentativas" in (audio.processing_error or "")
    assert db.get_job(job_id).status in {JobStatus.PARTIAL, JobStatus.COMPLETED}
