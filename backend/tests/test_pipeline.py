"""Testes de ponta a ponta: upload em partes, job completo, exports e retomada."""

from __future__ import annotations

import hashlib

import pytest

from app import db
from app.jobs.worker import PARSE, runner
from app.models.schemas import JobStatus, ProcessingStatus
from tests.conftest import MEDIA
from tests.fakes import FakeProvider

CHAT = """‎25/08/2026 10:40 - As mensagens e as chamadas são criptografadas de ponta a ponta.
25/08/2026 10:45 - Sanchai: Boa tarde, Sr. Rui
25/08/2026 10:52 - Sanchai: audio.opus (arquivo anexado)
25/08/2026 11:03 - Rui: imagem.jpg (arquivo anexado)
Olha essa condição
25/08/2026 11:10 - Sanchai: documento.pdf (arquivo anexado)
25/08/2026 11:30 - Rui: veja https://exemplo.com/proposta
25/08/2026 12:01 - Rui: nao-existe.pdf (arquivo anexado)
"""

ARQUIVOS = {
    "audio.opus": MEDIA / "audio.opus",
    "imagem.jpg": MEDIA / "imagem.jpg",
    "documento.pdf": MEDIA / "documento.pdf",
    "orfao.jpg": MEDIA / "orfao.jpg",
}


def _upload(client, zip_path, chunk_size=1024 * 512):
    """Sobe um ZIP em partes, como o frontend faz."""
    job_id = client.post("/api/jobs").json()["id"]
    payload = zip_path.read_bytes()
    chunks = [payload[i : i + chunk_size] for i in range(0, len(payload), chunk_size)] or [b""]

    resposta = client.post(
        f"/api/jobs/{job_id}/upload/init",
        json={"filename": zip_path.name, "size": len(payload), "totalChunks": len(chunks)},
    )
    assert resposta.status_code == 200

    for index, chunk in enumerate(chunks):
        resposta = client.put(f"/api/jobs/{job_id}/upload/chunk?index={index}", content=chunk)
        assert resposta.status_code == 200
        assert resposta.json()["received"] == len(chunk)

    resposta = client.post(
        f"/api/jobs/{job_id}/upload/complete",
        json={
            "totalChunks": len(chunks),
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
    )
    assert resposta.status_code == 200, resposta.text
    return job_id


async def _parse_now(job_id: str) -> None:
    job = db.get_job(job_id)
    await runner.parse_job(job)


@pytest.fixture
def zip_completo(make_zip):
    return make_zip(CHAT, ARQUIVOS, name="Conversa do WhatsApp com Cliente Exemplo.zip")


async def test_job_completo_monta_timeline_fiel(client, zip_completo):
    job_id = _upload(client, zip_completo)
    await _parse_now(job_id)

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["inventory"]["text"] == 2  # mensagem simples + mensagem com link
    assert job["inventory"]["audio"] == 1
    assert job["inventory"]["image"] == 1
    assert job["inventory"]["pdf"] == 2  # o PDF anexado e o PDF citado que não veio no ZIP
    assert job["inventory"]["links"] == 1
    assert job["inventory"]["attachmentsMatched"] == 3
    assert job["inventory"]["attachmentsUnresolved"] == 1
    assert job["inventory"]["orphanFiles"] == 1

    resposta = client.get(f"/api/jobs/{job_id}/events").json()
    eventos = resposta["events"]
    assert [evento["index"] for evento in eventos] == sorted(e["index"] for e in eventos)
    # Avisos automáticos do WhatsApp não entram na leitura da conversa por padrão…
    assert all(evento["type"] != "system" for evento in eventos)
    assert resposta["avisosOcultos"] >= 1
    audio = next(e for e in eventos if e["type"] == "audio")
    assert audio["processingStatus"] == "pending"
    assert any(e["caption"] == "Olha essa condição" for e in eventos)
    ausente = next(e for e in eventos if e["attachmentName"] == "nao-existe.pdf")
    assert ausente["processingStatus"] == "unresolved"

    # …mas nada foi apagado: com o interruptor ligado eles voltam, na posição original.
    completos = client.get(f"/api/jobs/{job_id}/events?avisos=true").json()["events"]
    assert completos[0]["type"] == "system"
    assert len(completos) > len(eventos)


async def test_evento_nao_resolvido_permanece_na_posicao(client, zip_completo):
    job_id = _upload(client, zip_completo)
    await _parse_now(job_id)
    eventos = client.get(f"/api/jobs/{job_id}/events").json()["events"]
    indices = [e["index"] for e in eventos]
    assert len(indices) == len(set(indices))
    assert eventos[-1]["attachmentName"] == "nao-existe.pdf"


async def test_processamento_preenche_midias_e_cobertura(client, zip_completo, monkeypatch):
    provider = FakeProvider(transcript="boa tarde seu Rui")
    monkeypatch.setattr("app.jobs.worker.build_provider", lambda _settings: provider)
    monkeypatch.setattr("app.jobs.worker.settings.openai_api_key", "chave-fake", raising=False)

    async def fake_link(url, timeout, limit_bytes):
        return 200, url, "text/html", "<html><title>Proposta</title><body>conteúdo</body></html>"

    monkeypatch.setattr("app.processors.link._fetch", fake_link)

    job_id = _upload(client, zip_completo)
    await _parse_now(job_id)
    await runner.process_job(db.get_job(job_id))

    job = client.get(f"/api/jobs/{job_id}").json()
    eventos = client.get(f"/api/jobs/{job_id}/events").json()["events"]

    audio = next(e for e in eventos if e["type"] == "audio")
    assert audio["processingStatus"] == "done"
    assert audio["processedText"] == "boa tarde seu Rui"

    imagem = next(e for e in eventos if e["type"] == "image")
    assert imagem["metadata"]["ocrText"] == "Valor: R$ 4.200,00"

    link = next(e for e in eventos if e["links"])["links"][0]
    assert link["status"] == "done"
    assert link["title"] == "Proposta"

    # O anexo ausente segue impedindo 100% — e o job termina como parcial.
    assert job["status"] == "partial"
    assert job["coverage"]["percent"] < 100
    assert job["cost"]["totalUsd"] > 0


async def test_cobertura_so_marca_cem_por_cento_quando_tudo_foi_decifrado(client, make_zip, monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr("app.jobs.worker.build_provider", lambda _settings: provider)
    monkeypatch.setattr("app.jobs.worker.settings.openai_api_key", "chave-fake", raising=False)

    chat = "25/08/2026 10:45 - Sanchai: oi\n25/08/2026 11:03 - Rui: imagem.jpg (arquivo anexado)\n"
    zip_path = make_zip(chat, {"imagem.jpg": MEDIA / "imagem.jpg"})
    job_id = _upload(client, zip_path)
    await _parse_now(job_id)
    await runner.process_job(db.get_job(job_id))

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "completed"
    assert job["coverage"]["percent"] == 100.0
    assert job["coverage"]["complete"] is True


async def test_teto_de_custo_deixa_job_parcial_sem_apagar_nada(client, make_zip, monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr("app.jobs.worker.build_provider", lambda _settings: provider)
    monkeypatch.setattr("app.jobs.worker.settings.openai_api_key", "chave-fake", raising=False)
    monkeypatch.setattr("app.jobs.worker.settings.max_job_cost_usd", 0.0000001, raising=False)

    chat = "25/08/2026 11:03 - Rui: imagem.jpg (arquivo anexado)\n"
    zip_path = make_zip(chat, {"imagem.jpg": MEDIA / "imagem.jpg"})
    job_id = _upload(client, zip_path)
    await _parse_now(job_id)
    await runner.process_job(db.get_job(job_id))

    job = client.get(f"/api/jobs/{job_id}").json()
    eventos = client.get(f"/api/jobs/{job_id}/events").json()["events"]
    assert job["status"] == "partial"
    assert any(w["code"] == "budget" for w in job["warnings"])
    assert eventos[0]["processingStatus"] == "pending"
    assert len(eventos) == 1


async def test_reprocessamento_de_um_evento_com_falha(client, make_zip, monkeypatch):
    falho = FakeProvider(permanent_failure=True)
    monkeypatch.setattr("app.jobs.worker.build_provider", lambda _settings: falho)
    monkeypatch.setattr("app.jobs.worker.settings.openai_api_key", "chave-fake", raising=False)

    chat = "25/08/2026 11:03 - Rui: imagem.jpg (arquivo anexado)\n"
    zip_path = make_zip(chat, {"imagem.jpg": MEDIA / "imagem.jpg"})
    job_id = _upload(client, zip_path)
    await _parse_now(job_id)
    await runner.process_job(db.get_job(job_id))

    evento = client.get(f"/api/jobs/{job_id}/events").json()["events"][0]
    assert evento["processingStatus"] == "failed"

    bom = FakeProvider(visible_text="agora foi", description="ok")
    monkeypatch.setattr("app.jobs.worker.build_provider", lambda _settings: bom)
    await runner.process_job(db.get_job(job_id), retry_failed=True, only_event=evento["id"])

    evento = client.get(f"/api/jobs/{job_id}/events").json()["events"][0]
    assert evento["processingStatus"] == "done"
    assert "agora foi" in evento["processedText"]


async def test_cancelamento_interrompe_o_processamento(client, zip_completo, monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr("app.jobs.worker.build_provider", lambda _settings: provider)
    monkeypatch.setattr("app.jobs.worker.settings.openai_api_key", "chave-fake", raising=False)

    job_id = _upload(client, zip_completo)
    await _parse_now(job_id)
    runner.cancel(job_id)
    await runner.process_job(db.get_job(job_id))

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "cancelled"
    assert provider.transcribe_calls == []


async def test_exports_nos_tres_formatos(client, zip_completo):
    job_id = _upload(client, zip_completo)
    await _parse_now(job_id)

    txt = client.get(f"/api/jobs/{job_id}/export/txt")
    assert txt.status_code == 200
    assert "TIPO: ÁUDIO" in txt.text
    assert "ARQUIVO: audio.opus" in txt.text
    assert "[MÍDIA AINDA NÃO PROCESSADA]" in txt.text
    assert "Boa tarde, Sr. Rui" in txt.text
    assert "attachment" in txt.headers["content-disposition"]

    md = client.get(f"/api/jobs/{job_id}/export/md")
    assert md.status_code == 200
    assert md.text.startswith("# Histórico —")
    assert "🎙" in md.text

    data = client.get(f"/api/jobs/{job_id}/export/json").json()
    assert data["schemaVersion"] == 2
    assert len(data["events"]) == 7
    assert data["events"][2]["original"]["attachmentName"] == "audio.opus"
    assert data["events"][2]["processed"]["status"] == "pending"
    assert data["inventory"]["orphanFiles"] == 1
    assert data["coverage"]["percent"] < 100


async def test_export_txt_preserva_texto_original_sem_alterar(client, make_zip):
    original = "olha só,, isso aqui  ta  errado mas nao pode ser corrigido 😅"
    chat = f"25/08/2026 10:45 - Rui: {original}\n"
    job_id = _upload(client, make_zip(chat))
    await _parse_now(job_id)
    assert original in client.get(f"/api/jobs/{job_id}/export/txt").text


async def test_export_deixa_os_avisos_do_whatsapp_fora_do_historico(client, make_zip):
    """Aviso do aplicativo não é diálogo — sai do histórico, mas não é apagado."""
    chat = (
        "25/08/2026 10:40 - As mensagens são criptografadas de ponta a ponta.\n"
        "25/08/2026 10:41 - Rui está na sua lista de contatos\n"
        "25/08/2026 10:45 - Rui: bom dia\n"
    )
    job_id = _upload(client, make_zip(chat))
    await _parse_now(job_id)

    padrao = client.get(f"/api/jobs/{job_id}/export/txt").text
    assert "bom dia" in padrao
    assert "lista de contatos" not in padrao
    assert "criptografadas" not in padrao
    assert "Avisos automáticos do WhatsApp fora do histórico: 2" in padrao

    completo = client.get(f"/api/jobs/{job_id}/export/txt?avisos=true").text
    assert "lista de contatos" in completo
    assert "criptografadas" in completo

    # O JSON é o formato de auditoria: continua trazendo tudo.
    assert "lista de contatos" in client.get(f"/api/jobs/{job_id}/export/json").text


async def test_exclusao_do_job_apaga_arquivos(client, zip_completo):
    from app.services import storage

    job_id = _upload(client, zip_completo)
    await _parse_now(job_id)
    assert storage.job_dir(job_id).exists()

    resposta = client.delete(f"/api/jobs/{job_id}")
    assert resposta.status_code == 200
    assert not storage.job_dir(job_id).exists()
    assert db.get_job(job_id) is None
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


async def test_retomada_de_job_apos_reinicio(client, zip_completo):
    job_id = _upload(client, zip_completo)
    # Estado de quem foi derrubado no meio do parse.
    db.update_job(job_id, status=JobStatus.PARSING)

    pendentes = runner.pending_tasks()
    assert [task.action for task in pendentes if task.job_id == job_id] == [PARSE]

    for task in pendentes:
        await runner._run(task)

    job = db.get_job(job_id)
    assert job.status in {JobStatus.PARTIAL, JobStatus.COMPLETED, JobStatus.AWAITING_CONFIRMATION}
    assert job.event_count == 7


async def test_zip_sem_txt_da_erro_amigavel(client, make_zip):
    zip_path = make_zip("", {})
    import zipfile

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(MEDIA / "imagem.jpg", "imagem.jpg")

    job_id = _upload(client, zip_path)
    await _parse_now(job_id)
    job = db.get_job(job_id)
    assert job.status == JobStatus.FAILED
    assert "Exporte a conversa pelo WhatsApp" in job.error


async def test_exportacao_sem_midia_avisa_o_usuario(client, make_zip):
    chat = "25/08/2026 10:45 - Rui: <Mídia oculta>\n25/08/2026 10:46 - Rui: <Mídia oculta>\n"
    job_id = _upload(client, make_zip(chat))
    await _parse_now(job_id)

    job = client.get(f"/api/jobs/{job_id}").json()
    aviso = next(w for w in job["warnings"] if w["code"] == "media_omitted")
    assert "Incluir mídia" in aviso["message"]
    eventos = client.get(f"/api/jobs/{job_id}/events").json()["events"]
    assert all(e["processingStatus"] == ProcessingStatus.UNSUPPORTED.value for e in eventos)


async def test_cobertura_separa_o_que_veio_pela_metade_do_que_nao_veio(client, make_zip):
    """Vídeo com a fala transcrita não pode ser contado igual a vídeo sem nada."""
    from app.models.schemas import Event, EventType, ProcessingStatus
    from app.services.coverage import compute_coverage

    com_fala = Event(
        id="a", index=0, raw_timestamp="x", type=EventType.VIDEO,
        processing_status=ProcessingStatus.UNSUPPORTED,
        processed_text="bom dia", metadata={"transcript": "bom dia"},
    )
    sem_nada = Event(
        id="b", index=1, raw_timestamp="x", type=EventType.VIDEO,
        processing_status=ProcessingStatus.UNSUPPORTED,
    )

    cobertura = compute_coverage([com_fala, sem_nada])
    video = cobertura.categories["video"]

    assert video.total == 2
    assert video.partial == 1
    assert video.unsupported == 2
    # Nada disso conta como decifrado: a cobertura continua abaixo de 100%.
    assert video.done == 0
    assert not video.complete
