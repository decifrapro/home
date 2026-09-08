"""Extração segura do ZIP exportado e catalogação dos arquivos."""

from __future__ import annotations

import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.models.schemas import CatalogFile
from app.services.mime import detect_mime, mime_from_extension

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._\- ]")


class ZipRejected(Exception):
    """ZIP recusado por violar um limite ou por tentar escapar do diretório do job."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ExtractionResult:
    files: list[CatalogFile]
    total_uncompressed: int
    txt_candidates: list[CatalogFile]


def _safe_relative_path(name: str) -> str | None:
    """Nome saneado e garantidamente dentro do diretório do job (anti Zip Slip)."""
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized.split("/")[0][1:2]:
        return None
    parts: list[str] = []
    for part in normalized.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        safe = _UNSAFE_NAME.sub("_", unicodedata.normalize("NFC", part)).strip()
        parts.append(safe[:180] or "arquivo")
    if not parts:
        return None
    return "/".join(parts)


def extract_zip(zip_path: Path, destination: Path, settings: Settings) -> ExtractionResult:
    """Descompacta em disco, em streaming, aplicando todos os limites configurados."""
    destination.mkdir(parents=True, exist_ok=True)
    destination_resolved = destination.resolve()

    max_uncompressed = settings.max_uncompressed_mb * 1024 * 1024
    max_single = settings.max_single_file_mb * 1024 * 1024

    files: list[CatalogFile] = []
    total = 0

    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise ZipRejected("invalid_zip", "O arquivo enviado não é um ZIP válido.") from exc

    with archive:
        entries = [item for item in archive.infolist() if not item.is_dir()]
        if len(entries) > settings.max_files_per_zip:
            raise ZipRejected(
                "too_many_files",
                f"O ZIP tem {len(entries)} arquivos e o limite é {settings.max_files_per_zip}.",
            )

        compressed_total = sum(item.compress_size for item in entries) or 1
        declared_total = sum(item.file_size for item in entries)
        if declared_total > max_uncompressed:
            raise ZipRejected(
                "too_large_uncompressed",
                f"O conteúdo descompactado passaria de {settings.max_uncompressed_mb} MB.",
            )
        if declared_total / compressed_total > settings.max_compression_ratio:
            raise ZipRejected(
                "suspicious_compression",
                "A taxa de compressão do ZIP é suspeita e o arquivo foi recusado.",
            )

        for item in entries:
            relative = _safe_relative_path(item.filename)
            if relative is None:
                raise ZipRejected(
                    "path_traversal",
                    "O ZIP contém caminho inválido, tentando escrever fora da pasta do atendimento.",
                )
            if item.file_size > max_single:
                raise ZipRejected(
                    "file_too_large",
                    f"O arquivo {relative} passa do limite de {settings.max_single_file_mb} MB.",
                )

            target = (destination / relative).resolve()
            if not str(target).startswith(str(destination_resolved) + "/"):
                raise ZipRejected("path_traversal", "O ZIP tentou escrever fora da pasta do atendimento.")
            target.parent.mkdir(parents=True, exist_ok=True)

            written = 0
            with archive.open(item) as source, target.open("wb") as sink:
                while True:
                    block = source.read(1024 * 512)
                    if not block:
                        break
                    written += len(block)
                    total += len(block)
                    if written > max_single or total > max_uncompressed:
                        sink.close()
                        target.unlink(missing_ok=True)
                        raise ZipRejected(
                            "too_large_uncompressed",
                            "O conteúdo descompactado passou do limite configurado.",
                        )
                    sink.write(block)

            detected = detect_mime(target)
            by_extension = mime_from_extension(relative)
            original = unicodedata.normalize("NFC", item.filename.replace("\\", "/"))
            files.append(
                CatalogFile(
                    relative_path=relative,
                    name=relative.rsplit("/", 1)[-1],
                    original_path=original,
                    original_name=original.rsplit("/", 1)[-1],
                    size=written,
                    detected_mime=detected,
                    extension_mime=by_extension,
                    mime_mismatch=bool(detected and by_extension and detected != by_extension),
                )
            )

    txt_candidates = [
        item
        for item in files
        if item.original_name.lower().endswith(".txt")
        or (item.detected_mime == "text/plain" and "." not in item.original_name)
    ]
    return ExtractionResult(files=files, total_uncompressed=total, txt_candidates=txt_candidates)


_TIMESTAMP_LINE = re.compile(r"^\s*[\[]?\d{1,4}[./-]\d{1,2}[./-]\d{2,4}[,]?\s+\d{1,2}:\d{2}")


def read_text_file(path: Path) -> str:
    """Lê o TXT tolerando as codificações que aparecem nas exportações reais."""
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def score_txt_candidate(path: Path) -> tuple[int, int]:
    """Pontua um TXT: quantas linhas começam com timestamp válido, e seu tamanho."""
    try:
        content = read_text_file(path)
    except OSError:
        return (0, 0)
    lines = content.splitlines()
    valid = sum(1 for line in lines[:5000] if _TIMESTAMP_LINE.match(line.lstrip("‎‏﻿")))
    return (valid, len(content))


def choose_main_txt(
    candidates: list[CatalogFile], root: Path
) -> tuple[CatalogFile | None, list[dict]]:
    """Escolhe o TXT principal da exportação.

    Heurística, nesta ordem: quantidade de linhas com timestamp válido, depois
    tamanho do arquivo. A escolha e as alternativas ficam registradas.
    """
    if not candidates:
        return None, []
    scored = []
    for candidate in candidates:
        valid, size = score_txt_candidate(root / candidate.relative_path)
        scored.append((valid, size, candidate))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best = scored[0]
    log = [
        {"file": item[2].relative_path, "timestamp_lines": item[0], "chars": item[1]}
        for item in scored
    ]
    if best[0] == 0:
        return None, log
    return best[2], log
