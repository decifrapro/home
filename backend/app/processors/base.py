"""Contrato dos processadores de mídia.

Cada tipo de mídia tem um processador independente. Uma falha em um item nunca
derruba o job inteiro: o evento fica marcado como falho, continua na timeline e
pode ser reprocessado sozinho.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.config import Settings
from app.models.schemas import Event, EventType, LinkItem, ProcessingStatus
from app.providers.base import AIProvider


class BudgetExceeded(RuntimeError):
    """Teto de custo do job atingido. O processamento para sem apagar nada."""


@dataclass
class Budget:
    """Controle do teto de custo do atendimento."""

    cap_usd: float
    spent_usd: float = 0.0

    def check(self, projected: float = 0.0) -> None:
        if self.cap_usd <= 0:
            return
        if self.spent_usd + projected > self.cap_usd:
            raise BudgetExceeded(
                f"teto de US$ {self.cap_usd:.2f} atingido (consumido US$ {self.spent_usd:.4f})"
            )

    def spend(self, amount: float) -> None:
        self.spent_usd = round(self.spent_usd + max(0.0, amount), 6)
        self.check()


@dataclass
class ProcessingContext:
    """Tudo que um processador precisa para trabalhar em um evento."""

    job_id: str
    extract_root: Path
    work_root: Path
    settings: Settings
    provider: AIProvider
    budget: Budget
    conversation_hint: str | None = None
    # Quando o arquivo não está no disco (Vercel), quem sabe buscá-lo é esta função.
    obter_midia: Callable[[Event], Path | None] | None = None

    def media_path(self, event: Event) -> Path | None:
        if not event.attachment_path:
            return None
        if self.obter_midia is not None:
            return self.obter_midia(event)
        path = self.extract_root / event.attachment_path
        return path if path.exists() else None

    def scratch(self, event: Event, name: str) -> Path:
        target = self.work_root / event.id / name
        target.parent.mkdir(parents=True, exist_ok=True)
        return target


@dataclass
class ProcessingOutcome:
    """Resultado de um processador — nunca lança exceção para fora do worker."""

    status: ProcessingStatus
    text: str | None = None
    metadata: dict = field(default_factory=dict)
    error: str | None = None
    cost_usd: float = 0.0
    category: str = "document"


class MediaProcessor(ABC):
    """Ponto de extensão: um processador por tipo de mídia."""

    category: str = "document"
    handles: tuple[EventType, ...] = ()

    @abstractmethod
    async def process(self, event: Event, context: ProcessingContext) -> ProcessingOutcome:
        """Processa um evento e devolve o conteúdo decifrado ou a falha."""

    def estimate_seconds(self, event: Event) -> float:  # pragma: no cover - informativo
        return 0.0


class LinkProcessorBase(ABC):
    """Links são subitens do evento e têm ciclo próprio."""

    category = "link"

    @abstractmethod
    async def process(self, link: LinkItem, context: ProcessingContext) -> ProcessingOutcome:
        ...
