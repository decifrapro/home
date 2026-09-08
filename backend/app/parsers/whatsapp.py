"""Parser de exportações de conversa do WhatsApp.

O TXT é a fonte da cronologia. Este módulo lê o arquivo linha a linha,
reconstrói cada evento na ordem original e devolve os dados brutos —
sem corrigir, resumir, traduzir ou reescrever nada do que foi escrito.

Suporta as variações reais de Android e iOS, 12h e 24h, e as marcações de
anexo e de mídia oculta nos idiomas mais comuns das exportações.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime

# ── Normalização ────────────────────────────────────────────────────────────
# As exportações vêm cheias de marcas de direção de texto (U+200E, U+200F) e
# espaços especiais. Elas são removidas apenas para comparar e associar; o
# texto original nunca é alterado.
INVISIBLE_CHARS = dict.fromkeys(
    map(ord, "‎‏​‌‍﻿⁦⁧⁨⁩‪‫‬‭‮"),
    None,
)
SPACE_CHARS = {ord(c): " " for c in "    ⁠"}


def strip_invisible(text: str) -> str:
    """Remove marcas invisíveis e normaliza espaços especiais para espaço comum."""
    return text.translate(INVISIBLE_CHARS).translate(SPACE_CHARS)


def normalize_for_match(text: str) -> str:
    """Forma canônica usada só para comparar nomes de arquivo."""
    return unicodedata.normalize("NFC", strip_invisible(text)).strip()


# ── Cabeçalhos de mensagem ──────────────────────────────────────────────────
_DATE = r"\d{1,4}[./-]\d{1,2}[./-]\d{2,4}"
_TIME = r"\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap]\.?\s*[Mm]\.?)?"

IOS_HEADER = re.compile(rf"^\[(?P<date>{_DATE}),?\s+(?P<time>{_TIME})\]\s*(?P<rest>.*)$", re.DOTALL)
ANDROID_HEADER = re.compile(
    rf"^(?P<date>{_DATE}),?\s+(?P<time>{_TIME})\s*[-–—]\s+(?P<rest>.*)$", re.DOTALL
)

SENDER_RE = re.compile(r"^(?P<sender>[^\n:]{1,60}):\s(?P<text>.*)$", re.DOTALL)

# ── Anexos ──────────────────────────────────────────────────────────────────
_ATTACH_WORDS_ANDROID = (
    r"arquivo anexado|arquivo em anexo|file attached|archivo adjunto|fichier joint|"
    r"Datei angeh[äa]ngt|file allegato|bijlage bijgevoegd|bestand bijgevoegd"
)
ATTACH_ANDROID = re.compile(
    rf"^\s*(?P<file>[^\n]+?)\s*\((?:{_ATTACH_WORDS_ANDROID})\)\s*(?P<caption>.*)$",
    re.IGNORECASE | re.DOTALL,
)
ATTACH_IOS = re.compile(
    r"<\s*(?:anexado|attached|adjunto|adjuntado|joint|allegato|angeh[äa]ngt)\s*:\s*(?P<file>[^>]+?)\s*>",
    re.IGNORECASE,
)

# ── Mídia não incluída na exportação ────────────────────────────────────────
MEDIA_OMITTED_BRACKET = re.compile(
    r"<\s*(?:M[íi]dia oculta|Arquivo de m[íi]dia oculto|Media omitted|Multimedia omitido|"
    r"Se omiti[óo] archivo multimedia|M[ée]dia omis|Medien weggelassen)\s*>",
    re.IGNORECASE,
)
MEDIA_OMITTED_INLINE = re.compile(
    r"^\s*(?P<kind>imagem|foto|figurinha|sticker|[áa]udio|v[íi]deo|documento|GIF|image|audio|video|"
    r"document|contact card|cart[ãa]o de contato)\s+(?:ocultad[ao]|omitid[ao]|omitted|oculto|omis)\s*$",
    re.IGNORECASE,
)

EDITED_RE = re.compile(
    r"<\s*(?:Esta mensagem foi editada|This message was edited|Mensaje editado|"
    r"Ce message a [ée]t[ée] modifi[ée])\s*>",
    re.IGNORECASE,
)
FORWARDED_RE = re.compile(
    r"^\s*(?:Encaminhada(?: muitas vezes)?|Forwarded(?: many times)?|Reenviado(?: muchas veces)?)\b",
    re.IGNORECASE,
)
DELETED_RE = re.compile(
    r"^\s*(?:Esta mensagem foi apagada|Você apagou esta mensagem|This message was deleted|"
    r"You deleted this message|Se elimin[óo] este mensaje)\s*\.?\s*$",
    re.IGNORECASE,
)

URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"'\]\)]+")

# Frases que identificam avisos do próprio WhatsApp, não mensagens de pessoas.
SYSTEM_PHRASES = (
    "mensagens e ligações são",
    "as mensagens e as chamadas",
    "messages and calls are",
    "los mensajes y las llamadas",
    "criptografia de ponta a ponta",
    "end-to-end encrypted",
    "criou o grupo",
    "created group",
    "created this group",
    "adicionou você",
    "added you",
    "mudou o assunto",
    "changed the subject",
    "mudou o número de telefone",
    "changed their phone number",
    "seu código de segurança",
    "security code changed",
    "as mensagens temporárias",
    "disappearing messages",
    "esta conversa é com uma conta empresarial",
    "business account",
    "chamada de voz perdida",
    "missed voice call",
    "chamada de vídeo perdida",
    "missed video call",
    "você bloqueou",
    "you blocked",
    "saiu do grupo",
    "left the group",
)

# Extensões usadas apenas como palpite inicial. O tipo real vem do sniffing.
EXT_TYPE_HINT = {
    "opus": "audio", "ogg": "audio", "mp3": "audio", "m4a": "audio", "aac": "audio",
    "wav": "audio", "amr": "audio", "oga": "audio",
    "jpg": "image", "jpeg": "image", "png": "image", "webp": "image", "gif": "image",
    "heic": "image", "heif": "image", "bmp": "image",
    "pdf": "pdf",
    "mp4": "video", "mov": "video", "3gp": "video", "avi": "video", "mkv": "video", "webm": "video",
    "doc": "document", "docx": "document", "xls": "document", "xlsx": "document",
    "ppt": "document", "pptx": "document", "txt": "document", "csv": "document",
    "vcf": "document", "zip": "document",
}

OMITTED_KIND_TYPE = {
    "imagem": "image", "foto": "image", "image": "image", "figurinha": "image",
    "sticker": "image", "gif": "image",
    "áudio": "audio", "audio": "audio",
    "vídeo": "video", "video": "video",
    "documento": "document", "document": "document",
    "cartão de contato": "document", "contact card": "document",
}


@dataclass
class RawMessage:
    """Um evento cru do TXT, ainda sem classificação de mídia."""

    index: int
    raw_timestamp: str
    date_part: str
    time_part: str
    sender: str | None
    text: str
    is_system: bool


@dataclass
class ParsedEvent:
    """Evento já classificado, pronto para virar linha da timeline."""

    id: str
    index: int
    raw_timestamp: str
    timestamp: datetime | None
    sender: str | None
    type: str
    raw_text: str
    caption: str | None = None
    attachment_name: str | None = None
    urls: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class ParseResult:
    events: list[ParsedEvent]
    date_order: str
    media_omitted_count: int
    warnings: list[dict] = field(default_factory=list)
    looks_truncated: bool = False


# ── Datas ───────────────────────────────────────────────────────────────────

def _split_date(date_part: str) -> tuple[int, int, int] | None:
    pieces = re.split(r"[./-]", date_part.strip())
    if len(pieces) != 3:
        return None
    try:
        return int(pieces[0]), int(pieces[1]), int(pieces[2])
    except ValueError:
        return None


def infer_date_order(dates: list[str]) -> str:
    """Descobre se a exportação usa dia/mês ou mês/dia observando o arquivo inteiro.

    Devolve "ymd", "dmy" ou "mdy". Quando os dois primeiros campos nunca passam
    de 12 o formato é ambíguo e assume-se dia/mês, que é o padrão do público do
    produto (pt-BR). A escolha fica registrada no relatório do job.
    """
    day_first = month_first = False
    for raw in dates:
        parts = _split_date(raw)
        if not parts:
            continue
        a, b, _c = parts
        if a > 31 or len(str(parts[0])) == 4:
            return "ymd"
        if a > 12:
            day_first = True
        elif b > 12:
            month_first = True
    if day_first and not month_first:
        return "dmy"
    if month_first and not day_first:
        return "mdy"
    return "dmy"


def _parse_time(time_part: str) -> tuple[int, int, int] | None:
    cleaned = strip_invisible(time_part).strip().lower().replace(".", "")
    ampm = None
    match = re.search(r"\b([ap])\s*m\b", cleaned)
    if match:
        ampm = match.group(1)
        cleaned = cleaned[: match.start()].strip()
    bits = cleaned.split(":")
    if len(bits) < 2:
        return None
    try:
        hour, minute = int(bits[0]), int(bits[1])
        second = int(bits[2]) if len(bits) > 2 else 0
    except ValueError:
        return None
    if ampm == "p" and hour < 12:
        hour += 12
    if ampm == "a" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        return None
    return hour, minute, second


def _assemble(parts: tuple[int, int, int], clock: tuple[int, int, int], order: str) -> datetime | None:
    a, b, c = parts
    if order == "ymd":
        year, month, day = a, b, c
    elif order == "mdy":
        month, day, year = a, b, c
    else:
        day, month, year = a, b, c
    if year < 100:
        year += 2000 if year < 70 else 1900
    try:
        return datetime(year, month, day, *clock)
    except ValueError:
        return None


def build_timestamp(date_part: str, time_part: str, order: str) -> datetime | None:
    """Monta a data do evento. Se a ordem inferida não formar data válida para
    esta linha específica, tenta as outras ordens antes de desistir — assim uma
    linha atípica não derruba o restante da timeline."""
    parts = _split_date(date_part)
    clock = _parse_time(time_part)
    if not parts or not clock:
        return None
    for candidate in (order, *(o for o in ("dmy", "mdy", "ymd") if o != order)):
        stamp = _assemble(parts, clock, candidate)
        if stamp is not None:
            return stamp
    return None


# ── Leitura do TXT ──────────────────────────────────────────────────────────

def _is_system_text(text: str) -> bool:
    lowered = strip_invisible(text).strip().lower()
    return any(phrase in lowered for phrase in SYSTEM_PHRASES)


def _looks_like_sender(candidate: str) -> bool:
    cleaned = strip_invisible(candidate).strip()
    if not cleaned or len(cleaned) > 60:
        return False
    if len(cleaned.split()) > 8:
        return False
    if cleaned.endswith((".", "!", "?")):
        return False
    return not _is_system_text(cleaned)


def split_messages(content: str) -> list[RawMessage]:
    """Quebra o TXT em eventos. Linha sem timestamp válido é continuação da anterior."""
    messages: list[RawMessage] = []
    current: RawMessage | None = None
    buffer: list[str] = []

    def flush() -> None:
        if current is not None:
            current.text = "\n".join(buffer).strip("\n")
            messages.append(current)

    for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        probe = strip_invisible(line).lstrip()
        header = IOS_HEADER.match(probe) or ANDROID_HEADER.match(probe)
        if header and _parse_time(header.group("time")):
            flush()
            rest = header.group("rest")
            sender: str | None = None
            body = rest
            sender_match = SENDER_RE.match(rest)
            if sender_match and _looks_like_sender(sender_match.group("sender")):
                sender = strip_invisible(sender_match.group("sender")).strip()
                body = sender_match.group("text")
            date_part = header.group("date")
            time_part = header.group("time").strip()
            current = RawMessage(
                index=len(messages),
                raw_timestamp=f"{date_part} {time_part}",
                date_part=date_part,
                time_part=time_part,
                sender=sender,
                text="",
                is_system=sender is None or _is_system_text(body),
            )
            buffer = [body]
        else:
            if current is None:
                # Lixo antes da primeira mensagem (cabeçalho de exportação, BOM).
                continue
            buffer.append(line)
    flush()
    return messages


def extract_urls(text: str) -> list[str]:
    """Extrai URLs preservando a forma original, sem pontuação final grudada."""
    found: list[str] = []
    for match in URL_RE.finditer(strip_invisible(text)):
        url = match.group(0).rstrip(".,;:!?»\"'")
        while url.endswith(")") and url.count("(") < url.count(")"):
            url = url[:-1]
        if url not in found:
            found.append(url)
    return found


def _extension_hint(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return EXT_TYPE_HINT.get(ext, "unknown")


def classify(message: RawMessage) -> ParsedEvent:
    """Transforma um evento cru em evento classificado (tipo, anexo, legenda, URLs)."""
    original = message.text
    probe = strip_invisible(original).strip()
    metadata: dict = {}
    event_type = "system" if message.is_system else "text"
    attachment: str | None = None
    caption: str | None = None
    text = original

    if EDITED_RE.search(probe):
        metadata["edited"] = True
    if FORWARDED_RE.match(probe):
        metadata["forwarded"] = True
    if DELETED_RE.match(probe):
        metadata["deleted"] = True

    ios = ATTACH_IOS.search(probe)
    android = None if ios else ATTACH_ANDROID.match(probe)

    if ios:
        attachment = strip_invisible(ios.group("file")).strip()
        remainder = (probe[: ios.start()] + probe[ios.end() :]).strip()
        caption = remainder or None
        event_type = _extension_hint(attachment)
    elif android:
        attachment = strip_invisible(android.group("file")).strip()
        caption = (android.group("caption") or "").strip() or None
        event_type = _extension_hint(attachment)
    elif MEDIA_OMITTED_BRACKET.search(probe) or MEDIA_OMITTED_INLINE.match(probe):
        inline = MEDIA_OMITTED_INLINE.match(probe)
        kind = strip_invisible(inline.group("kind")).strip().lower() if inline else ""
        event_type = OMITTED_KIND_TYPE.get(kind, "unknown")
        metadata["media_omitted"] = True

    urls = extract_urls(original)
    if urls and event_type == "text":
        stripped = probe
        for url in urls:
            stripped = stripped.replace(url, "")
        if not stripped.strip():
            event_type = "link"

    return ParsedEvent(
        id=str(uuid.uuid4()),
        index=message.index,
        raw_timestamp=message.raw_timestamp,
        timestamp=None,
        sender=message.sender,
        type=event_type,
        raw_text=text,
        caption=caption,
        attachment_name=attachment,
        urls=urls,
        metadata=metadata,
    )


def parse_chat(content: str) -> ParseResult:
    """Lê o TXT inteiro e devolve a timeline crua, na ordem original."""
    messages = split_messages(content)
    order = infer_date_order([m.date_part for m in messages])

    events: list[ParsedEvent] = []
    omitted = 0
    for message in messages:
        event = classify(message)
        event.timestamp = build_timestamp(message.date_part, message.time_part, order)
        if event.metadata.get("media_omitted"):
            omitted += 1
        events.append(event)

    warnings: list[dict] = []
    if omitted:
        warnings.append(
            {
                "code": "media_omitted",
                "message": (
                    "Esta exportação foi feita sem mídia. Refaça a exportação escolhendo "
                    "'Incluir mídia' para que áudios, imagens e documentos sejam lidos."
                ),
                "detail": f"{omitted} mensagens de mídia vieram sem o arquivo.",
            }
        )

    truncated = _looks_truncated(content, events)
    if truncated:
        warnings.append(
            {
                "code": "truncated_export",
                "message": "A exportação parece ter sido cortada pelo WhatsApp no início da conversa.",
                "detail": "Conversas muito longas são truncadas na exportação do aplicativo.",
            }
        )

    return ParseResult(
        events=events,
        date_order=order,
        media_omitted_count=omitted,
        warnings=warnings,
        looks_truncated=truncated,
    )


def _looks_truncated(content: str, events: list[ParsedEvent]) -> bool:
    """Heurística conservadora: exportação cortada não começa com o aviso de criptografia."""
    if not events:
        return False
    first_lines = strip_invisible(content).lstrip().lower()[:400]
    marks = ("criptograf", "encrypted", "cifrad", "verschlüsselt")
    return not any(mark in first_lines for mark in marks)
