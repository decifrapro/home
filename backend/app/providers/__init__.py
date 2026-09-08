"""Seleção do provedor de IA configurado."""

from __future__ import annotations

from app.config import Settings
from app.providers.base import (
    AIProvider,
    ProviderError,
    TranscriptionResult,
    UnavailableProvider,
    VisionResult,
)
from app.providers.openai_provider import OpenAIProvider

__all__ = [
    "AIProvider",
    "ProviderError",
    "TranscriptionResult",
    "VisionResult",
    "UnavailableProvider",
    "OpenAIProvider",
    "build_provider",
]


def build_provider(settings: Settings) -> AIProvider:
    if settings.ai_provider == "openai" and settings.openai_api_key:
        return OpenAIProvider(settings)
    return UnavailableProvider()
