"""Contrato do provedor de IA.

Trocar de provedor é trocar esta implementação — nenhum nome de modelo e
nenhuma chamada HTTP de provedor deve existir fora daqui.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class ProviderError(RuntimeError):
    """Falha do provedor. `retryable` indica erro temporário (429, 5xx, timeout)."""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass
class TranscriptionResult:
    text: str
    duration_seconds: float | None = None
    model: str | None = None
    cost_usd: float = 0.0
    metadata: dict = field(default_factory=dict)


@dataclass
class VisionResult:
    visible_text: str
    description: str
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    metadata: dict = field(default_factory=dict)


class AIProvider(Protocol):
    name: str
    available: bool

    async def transcribe(
        self, path: Path, *, language: str | None = None, hint: str | None = None
    ) -> TranscriptionResult: ...

    async def describe_image(
        self, path: Path, *, context: str | None = None, purpose: str = "image"
    ) -> VisionResult: ...

    async def aclose(self) -> None: ...


class UnavailableProvider:
    """Usado quando não há chave configurada: o motor roda, a IA não."""

    name = "none"
    available = False

    async def transcribe(self, path: Path, **_: object) -> TranscriptionResult:
        raise ProviderError("Nenhum provedor de IA configurado (defina OPENAI_API_KEY).")

    async def describe_image(self, path: Path, **_: object) -> VisionResult:
        raise ProviderError("Nenhum provedor de IA configurado (defina OPENAI_API_KEY).")

    async def aclose(self) -> None:
        return None
