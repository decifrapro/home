"""Documentos que não são PDF: texto, CSV, vCard e .docx.

Tudo é lido localmente, sem custo. Formato que não dá para ler com fidelidade é
marcado como não suportado, com o motivo visível — nunca some da timeline.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from app.models.schemas import Event, EventType, ProcessingStatus
from app.processors.base import MediaProcessor, ProcessingContext, ProcessingOutcome

MAX_CHARS = 200_000
TEXT_MIMES = {"text/plain", "text/csv", "text/vcard", "text/markdown", "application/json"}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_TAG = re.compile(r"<[^>]+>")


class DocumentProcessor(MediaProcessor):
    category = "document"
    handles = (EventType.DOCUMENT, EventType.UNKNOWN)

    async def process(self, event: Event, context: ProcessingContext) -> ProcessingOutcome:
        path = context.media_path(event)
        if path is None:
            return ProcessingOutcome(
                status=ProcessingStatus.UNRESOLVED,
                error="Arquivo não encontrado no ZIP.",
                category=self.category,
            )

        mime = (event.detected_mime or "").lower()
        name = (event.attachment_name or path.name).lower()

        if mime in TEXT_MIMES or name.endswith((".txt", ".csv", ".vcf", ".md", ".json")):
            text = _read_text(path)
            if text is None:
                return ProcessingOutcome(
                    status=ProcessingStatus.FAILED,
                    error="Não foi possível ler o conteúdo deste arquivo de texto.",
                    category=self.category,
                )
            return ProcessingOutcome(
                status=ProcessingStatus.DONE,
                text=text[:MAX_CHARS],
                metadata={"chars": len(text), "source": "texto local"},
                category=self.category,
            )

        if mime == DOCX_MIME or name.endswith(".docx"):
            text = _read_docx(path)
            if text:
                return ProcessingOutcome(
                    status=ProcessingStatus.DONE,
                    text=text[:MAX_CHARS],
                    metadata={"chars": len(text), "source": "docx"},
                    category=self.category,
                )
            return ProcessingOutcome(
                status=ProcessingStatus.FAILED,
                error="O .docx não pôde ser lido.",
                category=self.category,
            )

        return ProcessingOutcome(
            status=ProcessingStatus.UNSUPPORTED,
            error=f"Este formato não é lido nesta versão ({mime or 'tipo desconhecido'}). "
            "O arquivo continua na conversa, apenas sem conteúdo extraído.",
            category=self.category,
        )


def _read_text(path: Path) -> str | None:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _read_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    except Exception:
        return ""
    xml = xml.replace("</w:p>", "\n")
    return "\n".join(line.strip() for line in _TAG.sub("", xml).splitlines() if line.strip())
