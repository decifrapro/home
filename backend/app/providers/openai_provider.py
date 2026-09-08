"""Integração com a API da OpenAI (transcrição e visão).

Os modelos vêm de variável de ambiente (`OPENAI_TRANSCRIPTION_MODEL`,
`OPENAI_VISION_MODEL`); nenhum nome de modelo é fixado no código.
A chave existe apenas no servidor.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import random
from pathlib import Path

import httpx

from app.config import Settings
from app.providers.base import ProviderError, TranscriptionResult, VisionResult
from app.services.cost import transcription_cost, vision_call_cost

logger = logging.getLogger(__name__)

VISION_SYSTEM_PROMPT = (
    "Você analisa imagens vindas de uma conversa de WhatsApp para que outra pessoa "
    "entenda o que foi enviado sem abrir o arquivo. Responda SEMPRE em JSON com as "
    "chaves 'texto_visivel' e 'descricao_visual'. Em 'texto_visivel' transcreva "
    "literalmente todo texto legível (números, valores, datas, nomes, tabelas), "
    "preservando a grafia original; use o marcador [texto ilegível] onde não der "
    "para ler com segurança e deixe vazio se não houver texto. Em 'descricao_visual' "
    "descreva de forma factual o que a imagem mostra. Nunca invente informação, "
    "nunca traduza e nunca resuma valores ou condições."
)

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class OpenAIProvider:
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.available = bool(settings.openai_api_key)
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._settings.openai_base_url.rstrip("/"),
                headers={"Authorization": f"Bearer {self._settings.openai_api_key}"},
                timeout=httpx.Timeout(self._settings.openai_timeout_seconds),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post(self, url: str, **kwargs: object) -> httpx.Response:
        """POST com retry exponencial para erros temporários do provedor."""
        attempts = max(1, self._settings.provider_max_retries)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                response = await self._http().post(url, **kwargs)  # type: ignore[arg-type]
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = ProviderError(f"falha de rede ao falar com o provedor: {exc}", True)
            else:
                if response.status_code < 400:
                    return response
                retryable = response.status_code in RETRYABLE_STATUS
                detail = _error_detail(response)
                last_error = ProviderError(detail, retryable)
                if not retryable:
                    raise last_error
            delay = min(30.0, (2**attempt) + random.random())
            logger.warning("provedor respondeu erro temporário, nova tentativa em %.1fs", delay)
            await asyncio.sleep(delay)
        raise last_error or ProviderError("falha desconhecida no provedor", True)

    async def transcribe(
        self, path: Path, *, language: str | None = None, hint: str | None = None
    ) -> TranscriptionResult:
        model = self._settings.openai_transcription_model
        data: dict[str, str] = {"model": model, "response_format": "json"}
        if language:
            data["language"] = language
        if hint:
            data["prompt"] = hint[:900]

        mime = mimetypes.guess_type(path.name)[0] or "audio/mpeg"
        with path.open("rb") as handle:
            response = await self._post(
                "/audio/transcriptions",
                data=data,
                files={"file": (path.name, handle, mime)},
            )
        payload = response.json()
        text = (payload.get("text") or "").strip()
        seconds = payload.get("duration")
        return TranscriptionResult(
            text=text,
            duration_seconds=float(seconds) if seconds else None,
            model=model,
            metadata={"usage": payload.get("usage")},
        )

    async def describe_image(
        self, path: Path, *, context: str | None = None, purpose: str = "image"
    ) -> VisionResult:
        model = self._settings.openai_vision_model
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")

        user_text = {
            "image": "Analise esta imagem enviada na conversa.",
            "pdf_page": "Esta é a imagem de uma página de PDF. Transcreva o conteúdo da página.",
            "video_frame": "Este é um quadro extraído de um vídeo da conversa.",
        }.get(purpose, "Analise esta imagem.")
        if context:
            user_text += f"\nContexto da mensagem: {context[:600]}"

        response = await self._post(
            "/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": VISION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_text},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{encoded}"},
                            },
                        ],
                    },
                ],
                "response_format": {"type": "json_object"},
            },
        )
        payload = response.json()
        content = (payload.get("choices") or [{}])[0].get("message", {}).get("content") or "{}"
        visible, description = _parse_vision_payload(content)

        usage = payload.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        return VisionResult(
            visible_text=visible,
            description=description,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=vision_call_cost(self._settings, input_tokens, output_tokens),
        )

    def cost_for_audio(self, seconds: float) -> float:
        return transcription_cost(self._settings, seconds)


def _parse_vision_payload(content: str) -> tuple[str, str]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return ("", content.strip())
    visible = (data.get("texto_visivel") or data.get("visible_text") or "").strip()
    description = (data.get("descricao_visual") or data.get("description") or "").strip()
    return (visible, description)


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        message = payload.get("error", {}).get("message")
    except Exception:
        message = None
    return f"provedor respondeu {response.status_code}: {message or 'erro sem detalhe'}"
