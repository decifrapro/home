"""Layout em disco de cada atendimento e limpeza real dos arquivos."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from app.config import settings


def new_job_id() -> str:
    return uuid.uuid4().hex


def job_dir(job_id: str) -> Path:
    """Diretório do job. O id é hexadecimal, então nunca contém separador de caminho."""
    if not job_id.isalnum():
        raise ValueError("identificador de atendimento inválido")
    return settings.jobs_dir / job_id


def upload_dir(job_id: str) -> Path:
    return job_dir(job_id) / "upload"


def zip_path(job_id: str) -> Path:
    return job_dir(job_id) / "conversa.zip"


def extract_dir(job_id: str) -> Path:
    return job_dir(job_id) / "extracted"


def work_dir(job_id: str) -> Path:
    """Conversões temporárias: chunks de áudio, frames de vídeo, páginas de PDF."""
    return job_dir(job_id) / "work"


def ensure_job_dirs(job_id: str) -> Path:
    root = job_dir(job_id)
    for path in (root, upload_dir(job_id), extract_dir(job_id), work_dir(job_id)):
        path.mkdir(parents=True, exist_ok=True)
    return root


def purge_job(job_id: str) -> None:
    """Apaga de verdade tudo do atendimento: ZIP, extrações, conversões e frames."""
    shutil.rmtree(job_dir(job_id), ignore_errors=True)


def purge_work(job_id: str) -> None:
    shutil.rmtree(work_dir(job_id), ignore_errors=True)
    work_dir(job_id).mkdir(parents=True, exist_ok=True)


def resolve_inside(root: Path, relative: str) -> Path:
    """Resolve um caminho relativo garantindo que ele fique dentro de `root`."""
    target = (root / relative).resolve()
    root_resolved = root.resolve()
    if not str(target).startswith(str(root_resolved)):
        raise ValueError("caminho fora do diretório do atendimento")
    return target
