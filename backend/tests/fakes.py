"""Provedor de IA falso, para testar os processadores sem gastar dinheiro."""

from __future__ import annotations

from pathlib import Path

from app.providers.base import ProviderError, TranscriptionResult, VisionResult


class FakeProvider:
    name = "fake"
    available = True

    def __init__(
        self,
        transcript: str = "transcrição de teste",
        visible_text: str = "Valor: R$ 4.200,00",
        description: str = "Print de uma proposta comercial",
        fail_transcription_times: int = 0,
        fail_vision_times: int = 0,
        permanent_failure: bool = False,
    ) -> None:
        self.transcript = transcript
        self.visible_text = visible_text
        self.description = description
        self.fail_transcription_times = fail_transcription_times
        self.fail_vision_times = fail_vision_times
        self.permanent_failure = permanent_failure
        self.transcribe_calls: list[Path] = []
        self.vision_calls: list[tuple[Path, str]] = []
        self.closed = False

    async def transcribe(self, path: Path, *, language=None, hint=None) -> TranscriptionResult:
        self.transcribe_calls.append(path)
        if self.permanent_failure:
            raise ProviderError("provedor indisponível", retryable=False)
        if self.fail_transcription_times > 0:
            self.fail_transcription_times -= 1
            raise ProviderError("erro temporário do provedor", retryable=True)
        suffix = f" [{path.stem}]" if path.stem.startswith("chunk-") else ""
        return TranscriptionResult(text=self.transcript + suffix, model="fake-stt")

    async def describe_image(self, path: Path, *, context=None, purpose="image") -> VisionResult:
        self.vision_calls.append((path, purpose))
        if self.permanent_failure:
            raise ProviderError("provedor indisponível", retryable=False)
        if self.fail_vision_times > 0:
            self.fail_vision_times -= 1
            raise ProviderError("erro temporário do provedor", retryable=True)
        return VisionResult(
            visible_text=self.visible_text,
            description=self.description,
            model="fake-vision",
            input_tokens=1000,
            output_tokens=300,
            cost_usd=0.001,
        )

    async def aclose(self) -> None:
        self.closed = True
