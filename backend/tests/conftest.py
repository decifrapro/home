"""Ambiente isolado para os testes: dados em diretório temporário, sem IA real."""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import pytest

TMP_ROOT = Path(tempfile.mkdtemp(prefix="decifra-testes-"))
os.environ.update(
    {
        "DATA_DIR": str(TMP_ROOT),
        "DATABASE_PATH": str(TMP_ROOT / "teste.sqlite3"),
        "OPENAI_API_KEY": "",
        "APP_ACCESS_PASSWORD": "",
        "AUTO_CONFIRM_PROCESSING": "false",
        "MAX_JOB_COST_USD": "5",
        "UPLOAD_CHUNK_MB": "1",
        "LOG_LEVEL": "WARNING",
    }
)

FIXTURES = Path(__file__).resolve().parents[2] / "tests-fixtures" / "synthetic"
MEDIA = FIXTURES / "media"


@pytest.fixture(scope="session", autouse=True)
def _cleanup_tmp():
    yield
    shutil.rmtree(TMP_ROOT, ignore_errors=True)


@pytest.fixture
def data_root() -> Path:
    return TMP_ROOT


def build_zip(target: Path, chat: str, files: dict[str, Path | bytes] | None = None) -> Path:
    """Monta um ZIP de exportação sintético com o TXT e as mídias indicadas."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("_chat.txt", chat)
        for name, source in (files or {}).items():
            if isinstance(source, bytes):
                archive.writestr(name, source)
            else:
                archive.write(source, name)
    return target


@pytest.fixture
def make_zip(tmp_path):
    def factory(chat: str, files: dict[str, Path | bytes] | None = None, name: str = "conversa.zip"):
        return build_zip(tmp_path / name, chat, files)

    return factory


@pytest.fixture
def sample_media() -> dict[str, Path]:
    return {
        "audio.opus": MEDIA / "audio.opus",
        "imagem.jpg": MEDIA / "imagem.jpg",
        "documento.pdf": MEDIA / "documento.pdf",
        "contrato-com-extensao-errada.jpg": MEDIA / "contrato-com-extensao-errada.jpg",
        "video.mp4": MEDIA / "video.mp4",
        "orfao.jpg": MEDIA / "orfao.jpg",
    }


@pytest.fixture
def client():
    """Cliente HTTP com o ciclo de vida da aplicação ativo (worker rodando)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _clean_database():
    from app import db

    yield
    conn = db.connect()
    for table in ("events", "links", "files", "jobs"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
