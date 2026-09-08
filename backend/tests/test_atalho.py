"""Testes do atalho do iPhone: enviar do WhatsApp em um toque."""

from __future__ import annotations

import pytest

from app import db
from app.models.schemas import JobStatus
from app.services.atalho import CABECALHO, chave_confere, gerar_chave
from tests.conftest import MEDIA

CHAT = """25/08/2026 10:45 - Sanchai: Boa tarde, Sr. Rui
25/08/2026 10:52 - Sanchai: audio.opus (arquivo anexado)
"""


@pytest.fixture
def com_segredo(monkeypatch):
    monkeypatch.setattr("app.config.settings.app_session_secret", "segredo-longo-de-teste")


def test_chave_e_estavel_e_muda_com_o_segredo(com_segredo, monkeypatch):
    from app.config import settings

    primeira = gerar_chave(settings)
    assert primeira == gerar_chave(settings)
    assert chave_confere(primeira, settings) is True
    assert chave_confere("chave-errada", settings) is False

    monkeypatch.setattr("app.config.settings.app_session_secret", "outro-segredo")
    assert chave_confere(primeira, settings) is False


def test_sem_segredo_o_atalho_avisa_em_vez_de_dar_chave_instavel(client, monkeypatch):
    monkeypatch.setattr("app.config.settings.app_session_secret", "")
    resposta = client.get("/api/atalho/chave").json()
    assert resposta["disponivel"] is False
    assert "APP_SESSION_SECRET" in resposta["motivo"]


def test_chave_so_aparece_para_quem_entrou(com_segredo, client):
    resposta = client.get("/api/atalho/chave").json()
    assert resposta["disponivel"] is True
    assert len(resposta["chave"]) == 40
    assert resposta["urlPreparar"].endswith("/api/atalho/preparar")
    assert resposta["cabecalho"] == CABECALHO


def test_atalho_recusa_chave_errada(com_segredo, client):
    resposta = client.post(
        "/api/atalho/preparar",
        json={"filename": "conversa.zip", "size": 10},
        headers={CABECALHO: "chave-de-mentira"},
    )
    assert resposta.status_code == 401
    assert "Gere a chave de novo" in resposta.json()["detail"]


async def test_fluxo_do_atalho_de_ponta_a_ponta(com_segredo, client, make_zip, monkeypatch):
    """Os três passos que o Atalho faz: preparar, mandar o arquivo, concluir."""
    from app.config import settings
    from tests.fakes import FakeProvider

    provedor = FakeProvider(transcript="boa tarde, seu Rui")
    monkeypatch.setattr("app.jobs.worker.build_provider", lambda _s: provedor)
    monkeypatch.setattr("app.config.settings.openai_api_key", "chave-fake")

    chave = gerar_chave(settings)
    cabecalhos = {CABECALHO: chave}
    conteudo = make_zip(CHAT, {"audio.opus": MEDIA / "audio.opus"}).read_bytes()

    preparar = client.post(
        "/api/atalho/preparar",
        json={"filename": "Conversa do WhatsApp com Rui.zip", "size": len(conteudo)},
        headers=cabecalhos,
    ).json()
    job_id = preparar["jobId"]
    assert preparar["uploadUrl"].endswith(f"/api/atalho/arquivo/{job_id}")

    envio = client.put(preparar["uploadUrl"], content=conteudo, headers=cabecalhos)
    assert envio.status_code == 200
    assert envio.json()["size"] == len(conteudo)

    concluir = client.post("/api/atalho/concluir", json={"jobId": job_id}, headers=cabecalhos).json()

    # A conversa já foi lida e o processamento começou sozinho: ninguém está na tela.
    assert "mensagens" in concluir["mensagem"]
    assert "1 áudios" in concluir["mensagem"]
    assert concluir["url"].endswith(f"/?atendimento={job_id}")

    job = db.get_job(job_id)
    assert job.confirmed is True
    assert job.status in {JobStatus.PROCESSING, JobStatus.PARTIAL, JobStatus.COMPLETED}
    assert job.metadata["origem"] == "atalho-ios"
    assert job.original_filename == "Conversa do WhatsApp com Rui.zip"


async def test_atalho_recusa_arquivo_acima_do_limite(com_segredo, client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr("app.config.settings.max_zip_mb", 1)
    resposta = client.post(
        "/api/atalho/preparar",
        json={"filename": "grande.zip", "size": 5 * 1024 * 1024},
        headers={CABECALHO: gerar_chave(settings)},
    )
    assert resposta.status_code == 413


async def test_zip_ruim_pelo_atalho_devolve_recado_amigavel(com_segredo, client, monkeypatch):
    from app.config import settings

    chave = {CABECALHO: gerar_chave(settings)}
    preparar = client.post("/api/atalho/preparar", json={"filename": "x.zip"}, headers=chave).json()
    client.put(preparar["uploadUrl"], content=b"isto nao e um zip", headers=chave)

    concluir = client.post(
        "/api/atalho/concluir", json={"jobId": preparar["jobId"]}, headers=chave
    ).json()

    assert "não é um ZIP válido" in concluir["mensagem"]
    assert db.get_job(preparar["jobId"]).status == JobStatus.FAILED
