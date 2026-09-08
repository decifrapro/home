"""Detecção do tipo real de arquivo por magic bytes.

A extensão do arquivo é apenas um palpite: as exportações do WhatsApp trazem
arquivos sem extensão, com extensão errada e com nomes reaproveitados. O que
decide o pipeline de processamento é o conteúdo.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

try:  # libmagic é um complemento, não um requisito rígido
    import magic as _libmagic
except Exception:  # pragma: no cover - ambiente sem libmagic
    _libmagic = None

from app.models.schemas import EventType

_HEADER_BYTES = 4096


def _sniff_signature(head: bytes) -> str | None:
    """Assinaturas conhecidas, verificadas na ordem do mais específico."""
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image/gif"
    if head.startswith(b"BM"):
        return "image/bmp"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "audio/wav"
    if head.startswith(b"RIFF") and head[8:12] == b"AVI ":
        return "video/x-msvideo"
    if head.startswith(b"OggS"):
        return "audio/ogg" if b"OpusHead" in head[:256] or b"vorbis" in head[:256] else "application/ogg"
    if head.startswith(b"fLaC"):
        return "audio/flac"
    if head.startswith(b"#!AMR"):
        return "audio/amr"
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"M4A ", b"M4B ", b"M4P "):
            return "audio/mp4"
        if brand.startswith(b"hei") or brand.startswith(b"mif"):
            return "image/heic"
        if brand.startswith(b"3g"):
            return "video/3gpp"
        return "video/mp4"
    if head.startswith(b"PK\x03\x04"):
        return "application/zip"
    if head.startswith(b"BEGIN:VCARD") or head.startswith(b"\xef\xbb\xbfBEGIN:VCARD"):
        return "text/vcard"
    if head.startswith(b"%!PS"):
        return "application/postscript"
    return None


def sniff_bytes(head: bytes) -> str | None:
    return _sniff_signature(head)


def detect_mime(path: Path) -> str | None:
    """Tipo real do arquivo, por conteúdo. Nunca decide só pelo nome."""
    try:
        with path.open("rb") as handle:
            head = handle.read(_HEADER_BYTES)
    except OSError:
        return None
    if not head:
        return None

    detected = _sniff_signature(head)
    if detected:
        return detected

    if _libmagic is not None:
        try:
            guess = _libmagic.from_buffer(head, mime=True)
            if guess and guess != "application/octet-stream":
                return guess
        except Exception:
            pass

    # Texto simples é reconhecido por tentativa de decodificação, sem chute.
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        return "application/octet-stream"
    return "text/plain"


def mime_from_extension(name: str) -> str | None:
    guess, _ = mimetypes.guess_type(name)
    if guess:
        return guess
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return {"opus": "audio/ogg", "oga": "audio/ogg", "amr": "audio/amr", "heic": "image/heic"}.get(ext)


def type_for_mime(mime: str | None) -> EventType:
    """Mapeia o MIME real para o tipo de evento que define o pipeline."""
    if not mime:
        return EventType.UNKNOWN
    mime = mime.lower()
    if mime == "application/pdf":
        return EventType.PDF
    if mime.startswith("image/"):
        return EventType.IMAGE
    if mime.startswith("video/"):
        return EventType.VIDEO
    if mime.startswith("audio/") or mime == "application/ogg":
        return EventType.AUDIO
    if mime in {"text/plain", "text/vcard", "text/csv"} or mime.startswith("application/"):
        return EventType.DOCUMENT
    return EventType.UNKNOWN
