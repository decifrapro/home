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


def test_configuracao_aguenta_variavel_vazia_da_hospedagem(monkeypatch):
    """A Vercel injeta variáveis próprias; uma delas vazia não pode derrubar tudo."""
    import os

    from app.config import Settings

    monkeypatch.setitem(os.environ, "PORT", "")
    monkeypatch.setitem(os.environ, "MAX_ZIP_MB", "")
    monkeypatch.setitem(os.environ, "APP_ACCESS_PASSWORD", "")

    config = Settings()

    assert config.port == 8000  # valor padrão, não quebra
    assert config.max_zip_mb == 500
    assert config.app_access_password == ""  # texto vazio continua valendo


def test_porta_pode_ser_ajustada_por_app_port(monkeypatch):
    import os

    from app.config import Settings

    monkeypatch.setitem(os.environ, "APP_PORT", "9000")
    assert Settings().port == 9000


def test_toda_variavel_documentada_e_realmente_lida(monkeypatch):
    """O .env.example é a documentação: tudo que está lá tem que funcionar.

    Este teste existe porque uma variável documentada com um nome e lida com
    outro deixou o sistema publicado sem enxergar o Supabase — e o sintoma não
    apontava para a causa.
    """
    import os
    from pathlib import Path

    from app.config import Settings

    exemplo = Path(__file__).resolve().parents[2] / ".env.example"
    nomes = [
        linha.split("=", 1)[0].strip()
        for linha in exemplo.read_text(encoding="utf-8").splitlines()
        if "=" in linha and not linha.strip().startswith("#")
    ]
    assert len(nomes) > 30, "o exemplo de configuração deveria listar tudo"

    for nome in nomes:
        monkeypatch.setitem(os.environ, nome, "")

    config = Settings()
    lidos = set(config.model_dump().keys())
    faltando = [
        nome
        for nome in nomes
        if nome.lower() not in lidos
        and nome not in {"SUPABASE_SERVICE_ROLE_KEY"}  # lido por apelido
        and nome not in {"APP_HOST", "APP_PORT"}  # lidos por apelido
    ]
    assert faltando == [], f"variáveis documentadas que o código não lê: {faltando}"


def test_chave_do_supabase_aceita_os_dois_nomes(monkeypatch):
    import os

    from app.config import Settings

    monkeypatch.setitem(os.environ, "SUPABASE_URL", "https://projeto.supabase.co")
    monkeypatch.setitem(os.environ, "SUPABASE_SERVICE_ROLE_KEY", "sb_secret_exemplo")
    config = Settings()
    assert config.supabase_service_key == "sb_secret_exemplo"
    assert config.storage_mode == "supabase"

    monkeypatch.delitem(os.environ, "SUPABASE_SERVICE_ROLE_KEY")
    monkeypatch.setitem(os.environ, "SUPABASE_SERVICE_KEY", "outro")
    assert Settings().supabase_service_key == "outro"


def test_entrada_da_vercel_define_app_no_nivel_de_cima():
    """A plataforma procura `app` no nível de cima do arquivo.

    Este teste existe porque esconder essa definição dentro de um `try` fez a
    Vercel recusar o build inteiro — e o sintoma que aparecia era o site
    continuar servindo a versão antiga, sem nenhum aviso.
    """
    import ast
    from pathlib import Path

    entrada = Path(__file__).resolve().parents[2] / "api" / "index.py"
    arvore = ast.parse(entrada.read_text(encoding="utf-8"))

    nomes_no_topo = {
        alvo.id
        for no in arvore.body
        if isinstance(no, ast.Assign)
        for alvo in no.targets
        if isinstance(alvo, ast.Name)
    }
    assert "app" in nomes_no_topo, "api/index.py precisa ter uma linha 'app = ...' no topo"


def test_entrada_da_vercel_sobe_pagina_de_socorro_quando_a_aplicacao_falha(monkeypatch):
    """Se a aplicação não carregar, a função ainda responde contando o motivo."""
    import sys
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[2]
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))

    import api.index as entrada

    socorro = entrada.PaginaDeSocorro("Traceback...\nModuleNotFoundError: falta alguma coisa")
    enviados = []

    async def send(mensagem):
        enviados.append(mensagem)

    async def receive():
        return {"type": "http.request"}

    import asyncio

    asyncio.run(socorro({"type": "http"}, receive, send))

    assert enviados[0]["status"] == 500
    corpo = enviados[1]["body"].decode("utf-8")
    assert "não conseguiu iniciar" in corpo
    assert "ModuleNotFoundError" in corpo


def test_pagina_de_socorro_nao_mostra_segredo(monkeypatch):
    import os
    import sys
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[2]
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    import api.index as entrada

    monkeypatch.setitem(os.environ, "OPENAI_API_KEY", "sk-segredo-que-nao-pode-vazar")
    texto = entrada._redigir("erro com a chave sk-segredo-que-nao-pode-vazar dentro")

    assert "sk-segredo-que-nao-pode-vazar" not in texto
    assert "[OPENAI_API_KEY oculta]" in texto
