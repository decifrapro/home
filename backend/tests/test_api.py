"""Testes da API: gate por senha, upload em partes, filtros e limites."""

from __future__ import annotations

import pytest

from app import db
from app.models.schemas import JobStatus


def test_health_e_config(client):
    saude = client.get("/api/health").json()
    assert saude["status"] == "ok"
    config = client.get("/api/config").json()
    assert config["appName"]
    assert config["uploadChunkBytes"] > 0
    assert config["authenticated"] is True  # sem senha configurada


def test_upload_recusa_zip_acima_do_limite(client):
    job_id = client.post("/api/jobs").json()["id"]
    resposta = client.post(
        f"/api/jobs/{job_id}/upload/init",
        json={"filename": "gigante.zip", "size": 10_000 * 1024 * 1024, "totalChunks": 2},
    )
    assert resposta.status_code == 413
    assert "limite" in resposta.json()["detail"]


def test_upload_incompleto_e_recusado(client):
    job_id = client.post("/api/jobs").json()["id"]
    client.post(
        f"/api/jobs/{job_id}/upload/init",
        json={"filename": "conversa.zip", "size": 10, "totalChunks": 3},
    )
    client.put(f"/api/jobs/{job_id}/upload/chunk?index=0", content=b"abc")
    resposta = client.post(
        f"/api/jobs/{job_id}/upload/complete", json={"totalChunks": 3, "size": 10}
    )
    assert resposta.status_code == 400
    assert "Faltam partes" in resposta.json()["detail"]


def test_reenvio_de_parte_substitui_a_anterior(client):
    job_id = client.post("/api/jobs").json()["id"]
    client.post(
        f"/api/jobs/{job_id}/upload/init",
        json={"filename": "conversa.zip", "size": 4, "totalChunks": 1},
    )
    client.put(f"/api/jobs/{job_id}/upload/chunk?index=0", content=b"xxxx")
    client.put(f"/api/jobs/{job_id}/upload/chunk?index=0", content=b"ok!!")
    resposta = client.post(
        f"/api/jobs/{job_id}/upload/complete", json={"totalChunks": 1, "size": 4}
    )
    assert resposta.status_code == 200
    from app.services import storage

    assert storage.zip_path(job_id).read_bytes() == b"ok!!"


def test_checksum_divergente_e_recusado(client):
    job_id = client.post("/api/jobs").json()["id"]
    client.post(
        f"/api/jobs/{job_id}/upload/init",
        json={"filename": "conversa.zip", "size": 2, "totalChunks": 1},
    )
    client.put(f"/api/jobs/{job_id}/upload/chunk?index=0", content=b"oi")
    resposta = client.post(
        f"/api/jobs/{job_id}/upload/complete",
        json={"totalChunks": 1, "size": 2, "sha256": "0" * 64},
    )
    assert resposta.status_code == 400


def test_job_inexistente_da_404(client):
    assert client.get("/api/jobs/naoexiste123").status_code == 404
    assert client.get("/api/jobs/../etc/passwd").status_code == 404


def test_filtros_de_evento(client, make_zip):
    import asyncio

    from app.jobs.worker import runner

    chat = (
        "25/08/2026 10:45 - Sanchai: primeira mensagem\n"
        "25/08/2026 10:46 - Rui: segunda com https://exemplo.com\n"
    )
    zip_path = make_zip(chat)
    job_id = client.post("/api/jobs").json()["id"]
    payload = zip_path.read_bytes()
    client.post(
        f"/api/jobs/{job_id}/upload/init",
        json={"filename": "c.zip", "size": len(payload), "totalChunks": 1},
    )
    client.put(f"/api/jobs/{job_id}/upload/chunk?index=0", content=payload)
    client.post(f"/api/jobs/{job_id}/upload/complete", json={"totalChunks": 1, "size": len(payload)})
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        runner.parse_job(db.get_job(job_id))
    )

    todos = client.get(f"/api/jobs/{job_id}/events").json()
    assert todos["total"] == 2

    busca = client.get(f"/api/jobs/{job_id}/events", params={"search": "segunda"}).json()
    assert busca["total"] == 1

    tipo = client.get(f"/api/jobs/{job_id}/events", params={"type": "text"}).json()
    assert tipo["total"] == 2

    invalido = client.get(f"/api/jobs/{job_id}/events", params={"type": "inexistente"})
    assert invalido.status_code == 400


def test_confirmacao_exige_provedor_configurado(client):
    job_id = client.post("/api/jobs").json()["id"]
    db.update_job(job_id, status=JobStatus.AWAITING_CONFIRMATION)
    resposta = client.post(f"/api/jobs/{job_id}/confirm")
    assert resposta.status_code == 409
    assert "OPENAI_API_KEY" in resposta.json()["detail"]


def test_lista_de_jobs(client):
    client.post("/api/jobs")
    client.post("/api/jobs")
    jobs = client.get("/api/jobs").json()["jobs"]
    assert len(jobs) >= 2
    assert all("id" in job for job in jobs)


def test_cancelamento_marca_o_job(client):
    job_id = client.post("/api/jobs").json()["id"]
    resposta = client.post(f"/api/jobs/{job_id}/cancel")
    assert resposta.json()["status"] == "cancelled"


@pytest.fixture
def client_com_senha(monkeypatch):
    """Sobe a aplicação com o gate de senha ligado."""
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr("app.config.settings.app_access_password", "segredo-de-teste")
    monkeypatch.setattr("app.config.settings.app_session_secret", "chave-de-assinatura-de-teste")

    with TestClient(app) as test_client:
        yield test_client


def test_gate_por_senha_bloqueia_e_libera(client_com_senha):
    assert client_com_senha.post("/api/jobs").status_code == 401

    errado = client_com_senha.post("/api/auth/login", json={"password": "errada"})
    assert errado.status_code == 401

    certo = client_com_senha.post("/api/auth/login", json={"password": "segredo-de-teste"})
    assert certo.status_code == 200
    assert client_com_senha.post("/api/jobs").status_code == 200

    client_com_senha.post("/api/auth/logout")
    assert client_com_senha.post("/api/jobs").status_code == 401
