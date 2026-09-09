"""Testes do modo Vercel + Supabase: ZIP lido por partes, processamento em blocos."""

from __future__ import annotations

import json
import os
import zipfile

import httpx
import pytest

from app.config import settings
from app.models.schemas import JobStatus, ProcessingStatus
from app.services.fonte_zip import FonteSupabase
from app.services.remote_zip import ArquivoPorFaixa, abrir_zip_por_faixa
from tests.conftest import MEDIA
from tests.fakes import FakeProvider

CHAT = """25/08/2026 10:45 - Sanchai: Boa tarde, Sr. Rui
25/08/2026 10:52 - Sanchai: audio.opus (arquivo anexado)
25/08/2026 11:03 - Rui: imagem.jpg (arquivo anexado)
25/08/2026 11:30 - Rui: veja https://exemplo.com/proposta
"""


class ArmazenamentoFalso:
    """Imita o Supabase Storage guardando os bytes na memória, e conta as leituras."""

    def __init__(self, conteudo: bytes) -> None:
        self.conteudo = conteudo
        self.bytes_lidos = 0
        self.leituras = 0

    def file_size(self, _caminho: str) -> int:
        return len(self.conteudo)

    def download_range(self, _caminho: str, inicio: int, fim: int) -> bytes:
        self.leituras += 1
        pedaco = self.conteudo[inicio : fim + 1]
        self.bytes_lidos += len(pedaco)
        return pedaco


def montar_zip(tmp_path, arquivos: dict[str, bytes]) -> bytes:
    caminho = tmp_path / "conversa.zip"
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as pacote:
        for nome, conteudo in arquivos.items():
            pacote.writestr(nome, conteudo)
    return caminho.read_bytes()


# ── Leitura por faixas ──────────────────────────────────────────────────────
def test_arquivo_por_faixa_le_so_o_pedaco_pedido():
    dados = bytes(range(256)) * 100
    lidos: list[tuple[int, int]] = []

    def ler(inicio, fim):
        lidos.append((inicio, fim))
        return dados[inicio : fim + 1]

    arquivo = ArquivoPorFaixa(len(dados), ler, bloco=1024)
    arquivo.seek(5000)
    assert arquivo.read(10) == dados[5000:5010]
    assert lidos and lidos[0][0] == 5000
    assert arquivo.tell() == 5010


def test_zip_no_supabase_e_lido_sem_baixar_o_arquivo_inteiro(tmp_path, sample_media):
    # Bytes aleatórios: não comprimem, então o ZIP fica realmente grande.
    grande = os.urandom(3 * 1024 * 1024)
    bruto = montar_zip(
        tmp_path,
        {
            "_chat.txt": CHAT.encode("utf-8"),
            "audio.opus": (MEDIA / "audio.opus").read_bytes(),
            "peso-morto.bin": grande,
        },
    )
    armazenamento = ArmazenamentoFalso(bruto)
    pacote = abrir_zip_por_faixa(
        len(bruto), lambda i, f: armazenamento.download_range("z", i, f), bloco=64 * 1024
    )

    nomes = [item.filename for item in pacote.infolist()]
    assert "_chat.txt" in nomes
    assert pacote.read("_chat.txt").decode("utf-8").startswith("25/08/2026")
    assert armazenamento.bytes_lidos < len(bruto) / 2, "não deve baixar o ZIP inteiro"


def test_catalogo_pelo_supabase_identifica_o_tipo_real(tmp_path, sample_media):
    bruto = montar_zip(
        tmp_path,
        {
            "_chat.txt": CHAT.encode("utf-8"),
            "audio.opus": (MEDIA / "audio.opus").read_bytes(),
            "contrato.jpg": (MEDIA / "documento.pdf").read_bytes(),
        },
    )
    fonte = FonteSupabase(ArmazenamentoFalso(bruto), "job/conversa.zip", settings)

    catalogo = fonte.catalogar()
    por_nome = {item.name: item for item in catalogo.files}

    assert por_nome["audio.opus"].detected_mime == "audio/ogg"
    assert por_nome["contrato.jpg"].detected_mime == "application/pdf"
    assert por_nome["contrato.jpg"].mime_mismatch is True
    assert [item.name for item in catalogo.txt_candidates] == ["_chat.txt"]

    destino = tmp_path / "tmp" / "audio.opus"
    assert fonte.obter("audio.opus", destino).read_bytes()[:4] == b"OggS"
    fonte.fechar()


# ── Processamento em blocos ─────────────────────────────────────────────────
async def test_tick_avanca_aos_poucos_e_encerra_sozinho(client, make_zip, monkeypatch):
    from app import db
    from app.jobs.worker import runner

    provider = FakeProvider()
    monkeypatch.setattr("app.jobs.worker.build_provider", lambda _s: provider)
    monkeypatch.setattr("app.jobs.worker.settings.openai_api_key", "chave-fake", raising=False)

    async def link_falso(url, timeout, limite):
        return 200, url, "text/html", "<html><title>Proposta</title><body>oi</body></html>"

    monkeypatch.setattr("app.processors.link._fetch", link_falso)

    zip_path = make_zip(
        CHAT, {"audio.opus": MEDIA / "audio.opus", "imagem.jpg": MEDIA / "imagem.jpg"}
    )
    conteudo = zip_path.read_bytes()
    job_id = client.post("/api/jobs").json()["id"]
    client.post(
        f"/api/jobs/{job_id}/upload/init",
        json={"filename": "c.zip", "size": len(conteudo), "totalChunks": 1},
    )
    client.put(f"/api/jobs/{job_id}/upload/chunk?index=0", content=conteudo)
    client.post(f"/api/jobs/{job_id}/upload/complete", json={"totalChunks": 1, "size": len(conteudo)})
    await runner.parse_job(db.get_job(job_id))

    # Um item por chamada: três chamadas dão conta de áudio, imagem e link.
    passo1 = await runner.tick(db.get_job(job_id), max_items=1)
    assert passo1["processados"] == 1
    assert passo1["restantes"] == 2
    assert passo1["status"] == JobStatus.PROCESSING.value

    await runner.tick(db.get_job(job_id), max_items=1)
    final = await runner.tick(db.get_job(job_id), max_items=1)

    assert final["restantes"] == 0
    assert final["status"] in {JobStatus.COMPLETED.value, JobStatus.PARTIAL.value}
    eventos = db.get_events(job_id)
    assert all(e.processing_status == ProcessingStatus.DONE for e in eventos if e.type.is_media)
    assert db.get_links(job_id)[0].status == ProcessingStatus.DONE


async def test_tick_nao_processa_o_mesmo_item_duas_vezes(client, make_zip, monkeypatch):
    """A reserva impede que o aplicativo aberto e o agendamento repitam o trabalho."""
    from app import db
    from app.jobs.worker import runner

    provider = FakeProvider()
    monkeypatch.setattr("app.jobs.worker.build_provider", lambda _s: provider)
    monkeypatch.setattr("app.jobs.worker.settings.openai_api_key", "chave-fake", raising=False)

    zip_path = make_zip(
        "25/08/2026 11:03 - Rui: imagem.jpg (arquivo anexado)\n",
        {"imagem.jpg": MEDIA / "imagem.jpg"},
    )
    conteudo = zip_path.read_bytes()
    job_id = client.post("/api/jobs").json()["id"]
    client.post(
        f"/api/jobs/{job_id}/upload/init",
        json={"filename": "c.zip", "size": len(conteudo), "totalChunks": 1},
    )
    client.put(f"/api/jobs/{job_id}/upload/chunk?index=0", content=conteudo)
    client.post(f"/api/jobs/{job_id}/upload/complete", json={"totalChunks": 1, "size": len(conteudo)})
    await runner.parse_job(db.get_job(job_id))

    evento = db.get_events(job_id)[0]
    assert db.lease_event(job_id, evento.id) is True
    assert db.lease_event(job_id, evento.id) is False  # já está reservado

    resultado = await runner.tick(db.get_job(job_id), max_items=5)
    assert provider.vision_calls == []
    assert resultado["processados"] == 0


# ── Cliente do Supabase ─────────────────────────────────────────────────────
def test_cliente_supabase_monta_as_chamadas_certas():
    from app.services.supabase_client import SupabaseClient

    chamadas: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        chamadas.append(request)
        if request.method == "PATCH":
            return httpx.Response(200, json=[{"id": "e1"}])
        return httpx.Response(200, json=[{"id": "job1", "status": "created"}])

    config = settings.model_copy(
        update={"supabase_url": "https://projeto.supabase.co", "supabase_service_key": "chave"}
    )
    cliente = SupabaseClient(config)
    cliente._client = lambda: httpx.Client(transport=httpx.MockTransport(responder))  # type: ignore[method-assign]

    cliente.select("decifra_jobs", filtros={"id": "eq.job1"}, limite=1)
    assert chamadas[0].url.path == "/rest/v1/decifra_jobs"
    assert chamadas[0].headers["apikey"] == "chave"
    assert "id=eq.job1" in str(chamadas[0].url)

    atualizados = cliente.update_returning(
        "decifra_events", {"id": "eq.e1"}, {"processing_status": "processing"}
    )
    assert atualizados == [{"id": "e1"}]
    assert json.loads(chamadas[1].content)["processing_status"] == "processing"


def test_cliente_supabase_exige_configuracao():
    from app.services.supabase_client import SupabaseClient, SupabaseError

    with pytest.raises(SupabaseError):
        SupabaseClient(settings.model_copy(update={"supabase_url": "", "supabase_service_key": ""}))


def test_buscar_midias_ao_mesmo_tempo_nao_embaralha_os_bytes(tmp_path, make_zip):
    """As mídias do bloco são buscadas ao mesmo tempo: cada uma sai inteira.

    Guarda de regressão para o dia em que alguém trocar o leitor do ZIP remoto
    por outro que não proteja a posição de leitura.
    """
    import threading
    import time

    from app.config import settings
    from app.services.fonte_zip import FonteSupabase
    from tests.conftest import MEDIA
    from tests.fake_supabase import FakeSupabaseClient

    arquivos = {
        "audio.opus": MEDIA / "audio.opus",
        "imagem.jpg": MEDIA / "imagem.jpg",
        "documento.pdf": MEDIA / "documento.pdf",
        "video.mp4": MEDIA / "video.mp4",
    }
    zip_path = make_zip("25/08/2026 10:45 - Rui: oi\n", arquivos)
    cliente = FakeSupabaseClient()
    cliente.upload("job/conversa.zip", zip_path.read_bytes(), "application/zip")

    # A rede de verdade demora; sem essa espera as threads mal se cruzam e o
    # teste passaria mesmo com o leitor desprotegido.
    original = cliente.download_range

    def devagar(caminho, inicio, fim):
        time.sleep(0.005)
        return original(caminho, inicio, fim)

    cliente.download_range = devagar
    fonte = FonteSupabase(cliente, "job/conversa.zip", settings)

    esperado = {nome: origem.read_bytes() for nome, origem in arquivos.items()}
    obtidos: dict[str, bytes] = {}
    falhas: list[Exception] = []

    def buscar(nome: str) -> None:
        try:
            destino = fonte.obter(nome, tmp_path / f"paralelo-{nome}")
            obtidos[nome] = destino.read_bytes()
        except Exception as exc:  # noqa: BLE001 — o teste precisa ver a falha
            falhas.append(exc)

    linhas = [threading.Thread(target=buscar, args=(nome,)) for nome in arquivos]
    for linha in linhas:
        linha.start()
    for linha in linhas:
        linha.join()

    assert not falhas, falhas
    assert obtidos == esperado, "cada mídia tem que sair inteira e igual à original"
