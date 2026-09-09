"""Exportação do atendimento em TXT, Markdown e JSON.

Os três formatos mantêm sempre os dois níveis de conteúdo: o que foi escrito ou
enviado no WhatsApp, e o que a IA extraiu da mídia. Um nunca se disfarça do outro.
"""

from __future__ import annotations

import json
from datetime import datetime

from app.models.schemas import (
    SCHEMA_VERSION,
    Event,
    EventType,
    Job,
    LinkItem,
    ProcessingStatus,
)
from app.services.naming import camelize

SEPARATOR = "=" * 60

TYPE_LABEL = {
    EventType.TEXT: "TEXTO",
    EventType.AUDIO: "ÁUDIO",
    EventType.IMAGE: "IMAGEM",
    EventType.PDF: "PDF",
    EventType.VIDEO: "VÍDEO",
    EventType.LINK: "LINK",
    EventType.DOCUMENT: "DOCUMENTO",
    EventType.SYSTEM: "SISTEMA",
    EventType.UNKNOWN: "NÃO IDENTIFICADO",
}

TYPE_ICON = {
    EventType.TEXT: "💬",
    EventType.AUDIO: "🎙",
    EventType.IMAGE: "🖼",
    EventType.PDF: "📄",
    EventType.VIDEO: "🎥",
    EventType.LINK: "🔗",
    EventType.DOCUMENT: "📎",
    EventType.SYSTEM: "⚙",
    EventType.UNKNOWN: "❔",
}

STATUS_NOTE = {
    ProcessingStatus.PENDING: "[MÍDIA AINDA NÃO PROCESSADA]",
    ProcessingStatus.PROCESSING: "[PROCESSAMENTO EM ANDAMENTO]",
    ProcessingStatus.UNSUPPORTED: "[MÍDIA NÃO PROCESSADA]",
    ProcessingStatus.UNRESOLVED: "[ARQUIVO NÃO ASSOCIADO — CONTEÚDO INDISPONÍVEL]",
    ProcessingStatus.FAILED: "[FALHA AO PROCESSAR ESTA MÍDIA]",
}


def separar_avisos(events: list[Event]) -> tuple[list[Event], int]:
    """Separa o diálogo dos avisos automáticos do WhatsApp.

    Coisas como "Sua empresa usa um serviço seguro da Meta" ou "Fulano está na
    sua lista de contatos" foram escritas pelo aplicativo, não por uma pessoa.
    Elas continuam guardadas e podem ser exibidas a qualquer momento — só não
    entram no histórico por padrão, porque não fazem parte da conversa.
    """
    dialogo = [evento for evento in events if evento.type is not EventType.SYSTEM]
    return dialogo, len(events) - len(dialogo)


def _stamp(event: Event) -> str:
    return event.raw_timestamp or (event.timestamp.strftime("%d/%m/%Y %H:%M") if event.timestamp else "")


def _who(event: Event) -> str:
    return event.sender or "Sistema"


def _media_body(event: Event) -> list[str]:
    """Conteúdo decifrado da mídia, com os rótulos que o export precisa ter."""
    lines: list[str] = []
    if event.caption:
        lines += ["LEGENDA ORIGINAL:", event.caption, ""]

    if event.processing_status != ProcessingStatus.DONE:
        lines.append(STATUS_NOTE.get(event.processing_status, "[CONTEÚDO INDISPONÍVEL]"))
        if event.processing_error:
            lines.append(f"MOTIVO: {event.processing_error}")
        # Quando parte do conteúdo foi recuperada mesmo assim — o áudio de um
        # vídeo numa instalação sem FFmpeg, por exemplo —, ela entra logo abaixo
        # do motivo. Esconder o que já se sabe seria pior do que a limitação.
        recuperado = _conteudo(event)
        if any(linha.strip() for linha in recuperado):
            lines += ["", *recuperado]
        return lines

    return lines + _conteudo(event)


def _conteudo(event: Event) -> list[str]:
    """O que a IA extraiu, no formato de cada tipo de mídia."""
    lines: list[str] = []
    meta = event.metadata or {}
    if event.type == EventType.AUDIO:
        lines += ["[TRANSCRIÇÃO DO ÁUDIO]", event.processed_text or ""]
    elif event.type == EventType.IMAGE:
        if meta.get("ocr_text"):
            lines += ["[TEXTO IDENTIFICADO NA IMAGEM]", meta["ocr_text"], ""]
        if meta.get("visual_description"):
            lines += ["[DESCRIÇÃO VISUAL]", meta["visual_description"]]
        if not meta.get("ocr_text") and not meta.get("visual_description"):
            lines += ["[ANÁLISE DA IMAGEM]", event.processed_text or ""]
    elif event.type == EventType.PDF:
        pages = meta.get("pages") or []
        if pages:
            lines.append("[CONTEÚDO DO PDF]")
            for page in pages:
                origin = " (lido por visão)" if page.get("source") == "vision" else ""
                lines += [f"Página {page.get('page')}{origin}:", (page.get("text") or "").strip(), ""]
        else:
            lines += ["[CONTEÚDO DO PDF]", event.processed_text or ""]
    elif event.type == EventType.VIDEO:
        if meta.get("transcript"):
            lines += ["[TRANSCRIÇÃO DO ÁUDIO DO VÍDEO]", meta["transcript"], ""]
        if meta.get("visual_description"):
            lines += ["[DESCRIÇÃO VISUAL]", meta["visual_description"]]
        if not meta.get("transcript") and not meta.get("visual_description"):
            lines += ["[ANÁLISE DO VÍDEO]", event.processed_text or ""]
    else:
        lines += ["[CONTEÚDO EXTRAÍDO]", event.processed_text or ""]
    return lines


def _link_block(link: LinkItem) -> list[str]:
    lines = [f"URL: {link.url}"]
    if link.status == ProcessingStatus.DONE:
        if link.title:
            lines.append(f"TÍTULO: {link.title}")
        if link.description:
            lines.append(f"DESCRIÇÃO: {link.description}")
        if link.content:
            lines += ["[CONTEÚDO DA PÁGINA]", link.content]
    elif link.status == ProcessingStatus.FAILED:
        lines.append(f"[LINK NÃO LIDO] {link.error or 'falha ao acessar'}")
    else:
        lines.append("[LINK AINDA NÃO LIDO]")
    return lines


def export_txt(job: Job, events: list[Event], incluir_avisos: bool = False) -> str:
    """Formato estável e legível, pensado para leitura humana e auditoria."""
    omitidos = 0
    if not incluir_avisos:
        events, omitidos = separar_avisos(events)
    out: list[str] = [
        SEPARATOR,
        f"HISTÓRICO DA CONVERSA — {job.original_filename or 'exportação do WhatsApp'}",
        f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        f"Eventos: {len(events)}   Cobertura: {job.coverage.percent}%",
    ]
    if omitidos:
        out.append(
            f"Avisos automáticos do WhatsApp fora do histórico: {omitidos} "
            "(nada foi apagado; eles continuam no atendimento)"
        )
    out += [SEPARATOR, ""]

    for event in events:
        header = f"{_stamp(event)} — {_who(event)}"
        simple = event.type in (EventType.TEXT, EventType.SYSTEM) and not event.attachment_name
        if simple and not event.links:
            out += [header, event.raw_text.strip(), ""]
            continue

        out += [SEPARATOR, header, f"TIPO: {TYPE_LABEL[event.type]}"]
        if event.attachment_name:
            out.append(f"ARQUIVO: {event.attachment_name}")
        if event.detected_mime:
            out.append(f"MIME: {event.detected_mime}")
        out += [SEPARATOR, ""]

        if event.type in (EventType.TEXT, EventType.LINK, EventType.SYSTEM):
            if event.raw_text.strip():
                out += ["MENSAGEM ORIGINAL:", event.raw_text.strip(), ""]
        else:
            out += _media_body(event) + [""]

        for link in event.links:
            out += _link_block(link) + [""]
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def export_markdown(job: Job, events: list[Event], incluir_avisos: bool = False) -> str:
    """Histórico estruturado, fácil de colar em outra IA."""
    omitidos = 0
    if not incluir_avisos:
        events, omitidos = separar_avisos(events)
    out: list[str] = [
        f"# Histórico — {job.original_filename or 'conversa do WhatsApp'}",
        "",
        f"- Eventos: {len(events)}",
        f"- Período: {_range(job)}",
        f"- Cobertura do processamento: {job.coverage.percent}%",
    ]
    if omitidos:
        out.append(
            f"- Avisos automáticos do WhatsApp fora do histórico: {omitidos} "
            "(nada foi apagado)"
        )
    out += [
        "",
        "> Conteúdo original do WhatsApp e conteúdo extraído por IA aparecem separados.",
        "",
        "---",
        "",
    ]

    for event in events:
        icon = TYPE_ICON[event.type]
        out.append(f"### {icon} {_stamp(event)} — {_who(event)}")
        if event.attachment_name:
            out.append(f"`{event.attachment_name}`")
        out.append("")

        if event.type in (EventType.TEXT, EventType.LINK, EventType.SYSTEM):
            if event.raw_text.strip():
                out += [event.raw_text.strip(), ""]
        else:
            if event.caption:
                out += [f"**Legenda original:** {event.caption}", ""]
            body = _media_body(event)
            if event.caption:
                body = body[3:]
            out += _as_markdown(body) + [""]

        for link in event.links:
            out += _as_markdown(_link_block(link)) + [""]

    return "\n".join(out).rstrip() + "\n"


def _as_markdown(lines: list[str]) -> list[str]:
    rendered: list[str] = []
    for line in lines:
        if line.startswith("[") and line.endswith("]"):
            rendered.append(f"**{line.strip('[]')}**")
        elif line.startswith(("URL:", "TÍTULO:", "DESCRIÇÃO:", "MOTIVO:", "LEGENDA ORIGINAL:")):
            label, _, value = line.partition(":")
            rendered.append(f"**{label}:**{value}")
        else:
            rendered.append(line)
    return rendered


def _range(job: Job) -> str:
    if not job.conversation_start or not job.conversation_end:
        return "não identificado"
    fmt = "%d/%m/%Y %H:%M"
    return f"{job.conversation_start.strftime(fmt)} a {job.conversation_end.strftime(fmt)}"


def export_json(job: Job, events: list[Event]) -> dict:
    """Representação fiel da timeline, com os dois níveis de conteúdo."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now().isoformat(),
        "job": {
            "id": job.id,
            "status": job.status.value,
            "originalFilename": job.original_filename,
            "zipSize": job.zip_size,
            "createdAt": job.created_at.isoformat() if job.created_at else None,
            "conversationStart": job.conversation_start.isoformat() if job.conversation_start else None,
            "conversationEnd": job.conversation_end.isoformat() if job.conversation_end else None,
            "eventCount": job.event_count,
            "warnings": [warning.model_dump() for warning in job.warnings],
            "metadata": job.metadata,
        },
        "inventory": camelize(job.inventory.model_dump()),
        "coverage": {
            "categories": {
                name: bucket.model_dump() for name, bucket in job.coverage.categories.items()
            },
            "overallTotal": job.coverage.overall_total,
            "overallDone": job.coverage.overall_done,
            "percent": job.coverage.percent,
            "complete": job.coverage.complete,
        },
        "cost": {**job.cost.model_dump(), "totalUsd": job.cost.total_usd},
        "estimate": job.estimate.model_dump() if job.estimate else None,
        "events": [
            {
                "id": event.id,
                "index": event.index,
                "rawTimestamp": event.raw_timestamp,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                "sender": event.sender,
                "type": event.type.value,
                "original": {
                    "text": event.raw_text,
                    "caption": event.caption,
                    "attachmentName": event.attachment_name,
                },
                "media": {
                    "detectedMime": event.detected_mime,
                    "path": event.attachment_path,
                    **{
                        key: value
                        for key, value in (event.metadata or {}).items()
                        if key in {"duration_seconds", "file_size", "pages_count", "frames", "mime_mismatch"}
                    },
                },
                "processed": {
                    "text": event.processed_text,
                    "status": event.processing_status.value,
                    "error": event.processing_error,
                    "detail": {
                        key: value
                        for key, value in (event.metadata or {}).items()
                        if key in {"ocr_text", "visual_description", "transcript", "pages", "chunks"}
                    },
                },
                "cost": (event.metadata or {}).get("cost"),
                "metadata": event.metadata,
                "links": [
                    {
                        "id": link.id,
                        "url": link.url,
                        "status": link.status.value,
                        "title": link.title,
                        "description": link.description,
                        "content": link.content,
                        "error": link.error,
                        "metadata": link.metadata,
                    }
                    for link in event.links
                ],
            }
            for event in events
        ],
    }


def export_json_text(job: Job, events: list[Event]) -> str:
    return json.dumps(export_json(job, events), ensure_ascii=False, indent=2)
