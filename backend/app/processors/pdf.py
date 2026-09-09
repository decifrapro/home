"""Leitura de PDF, página por página.

Primeiro o texto é extraído localmente (grátis e fiel). Só as páginas pobres em
texto — escaneadas, ou com tabela e layout que o extrator não recupera — são
renderizadas como imagem e complementadas com visão.

Nada aqui resume: valores, parcelas, nomes, datas e condições saem inteiros.
"""

from __future__ import annotations

import logging

from app.models.schemas import Event, EventType, ProcessingStatus
from app.processors.base import BudgetExceeded, MediaProcessor, ProcessingContext, ProcessingOutcome
from app.providers.base import ProviderError
from app.services.cost import (
    VISION_INPUT_TOKENS_PER_IMAGE,
    VISION_OUTPUT_TOKENS_PER_IMAGE,
    vision_call_cost,
)

logger = logging.getLogger(__name__)
RENDER_DPI = 170


class PdfProcessor(MediaProcessor):
    category = "pdf"
    handles = (EventType.PDF,)

    async def process(self, event: Event, context: ProcessingContext) -> ProcessingOutcome:
        path = await context.midia(event)
        if path is None:
            return ProcessingOutcome(
                status=ProcessingStatus.UNRESOLVED,
                error="Arquivo PDF não encontrado no ZIP.",
                category=self.category,
            )

        try:
            import fitz  # PyMuPDF
        except ImportError:  # pragma: no cover
            return ProcessingOutcome(
                status=ProcessingStatus.UNSUPPORTED,
                error="Leitor de PDF indisponível no servidor.",
                category=self.category,
            )

        settings = context.settings
        pages: list[dict] = []
        cost = 0.0
        failures: list[str] = []
        stopped_by_budget = False

        try:
            document = fitz.open(path)
        except Exception as exc:
            return ProcessingOutcome(
                status=ProcessingStatus.FAILED,
                error=f"PDF ilegível ou protegido: {exc}",
                category=self.category,
            )

        with document:
            if document.needs_pass:
                return ProcessingOutcome(
                    status=ProcessingStatus.UNSUPPORTED,
                    error="PDF protegido por senha.",
                    category=self.category,
                )

            total_pages = document.page_count
            limit = min(total_pages, settings.pdf_max_pages)

            for number in range(limit):
                page = document.load_page(number)
                text = (page.get_text("text") or "").strip()
                entry = {"page": number + 1, "text": text, "source": "text"}

                if len(text) < settings.pdf_min_chars_per_page and context.provider.available:
                    try:
                        context.budget.check(
                            vision_call_cost(
                                settings, VISION_INPUT_TOKENS_PER_IMAGE, VISION_OUTPUT_TOKENS_PER_IMAGE
                            )
                        )
                    except BudgetExceeded:
                        stopped_by_budget = True
                        pages.append(entry)
                        break

                    image_path = context.scratch(event, f"pagina-{number + 1:04d}.png")
                    try:
                        pixmap = page.get_pixmap(dpi=RENDER_DPI)
                        pixmap.save(image_path)
                        result = await context.provider.describe_image(
                            image_path, context=event.caption, purpose="pdf_page"
                        )
                    except ProviderError as exc:
                        failures.append(f"página {number + 1}: {exc}")
                        pages.append(entry)
                        continue
                    except Exception as exc:  # renderização falhou
                        failures.append(f"página {number + 1}: {exc}")
                        pages.append(entry)
                        continue

                    context.budget.spend(result.cost_usd)
                    cost += result.cost_usd
                    combined = "\n\n".join(
                        piece for piece in (text, result.visible_text, result.description) if piece
                    )
                    entry = {"page": number + 1, "text": combined.strip(), "source": "vision"}

                pages.append(entry)

        body = "\n\n".join(
            f"Página {item['page']}:\n{item['text']}" for item in pages if item["text"]
        ).strip()

        metadata = {
            "pages": pages,
            "pages_count": len(pages),
            "pages_total": total_pages,
            "cost": round(cost, 6),
        }
        if total_pages > limit:
            metadata["pages_skipped"] = total_pages - limit
            failures.append(
                f"o PDF tem {total_pages} páginas e o limite configurado é {settings.pdf_max_pages}"
            )

        if stopped_by_budget:
            return ProcessingOutcome(
                status=ProcessingStatus.PENDING,
                text=body or None,
                metadata=metadata,
                error="Teto de custo atingido antes de terminar o PDF.",
                cost_usd=cost,
                category=self.category,
            )

        if not body:
            return ProcessingOutcome(
                status=ProcessingStatus.FAILED,
                metadata=metadata,
                error="Nenhum texto pôde ser extraído deste PDF.",
                cost_usd=cost,
                category=self.category,
            )

        return ProcessingOutcome(
            status=ProcessingStatus.DONE,
            text=body,
            metadata=metadata | ({"partial_failures": failures} if failures else {}),
            cost_usd=cost,
            category=self.category,
        )
