"""Configuração central do Decifra Pro.

Tudo que muda entre ambientes (nome do produto, limites, modelos de IA, preços)
vive aqui e vem de variável de ambiente. Nada disso deve ser escrito direto no
código do resto do projeto.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Identidade
    app_name: str = "Decifra Pro"
    app_short_name: str = "Decifra"
    app_description: str = "Leitor multimodal de conversas exportadas do WhatsApp"

    # Servidor
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Armazenamento
    data_dir: Path = Path("/data")
    database_path: str = ""

    # Acesso
    app_access_password: str = ""
    app_session_secret: str = ""

    # Limites de ZIP e upload
    max_zip_mb: int = 500
    max_uncompressed_mb: int = 2000
    max_files_per_zip: int = 5000
    max_single_file_mb: int = 500
    max_compression_ratio: int = 120
    upload_chunk_mb: int = 5
    job_retention_hours: int = 24

    # Provedor de IA
    ai_provider: str = "openai"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_transcription_model: str = "gpt-4o-transcribe"
    openai_vision_model: str = "gpt-4.1-mini"
    openai_timeout_seconds: int = 180

    # Concorrência
    audio_concurrency: int = 3
    image_concurrency: int = 3
    pdf_concurrency: int = 2
    video_concurrency: int = 1
    link_concurrency: int = 3
    provider_max_retries: int = 4

    # Mídia
    video_max_frames: int = 16
    audio_chunk_max_mb: int = 20
    audio_chunk_seconds: int = 600
    pdf_max_pages: int = 300
    pdf_min_chars_per_page: int = 180
    link_timeout_seconds: int = 20
    link_max_download_mb: int = 8
    enable_playwright: bool = False

    # Custo
    max_job_cost_usd: float = 5.0
    auto_confirm_processing: bool = False
    price_transcription_per_minute: float = 0.006
    price_vision_input_per_mtok: float = 0.40
    price_vision_output_per_mtok: float = 1.60

    # Ferramentas externas
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"

    # Diretório do frontend compilado (servido pelo backend em produção)
    frontend_dist: Path = Field(default=Path("/app/frontend"))

    @field_validator("data_dir", "frontend_dist", mode="before")
    @classmethod
    def _as_path(cls, value: object) -> object:
        return Path(str(value)) if value else value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def db_path(self) -> Path:
        if self.database_path:
            return Path(self.database_path)
        return self.data_dir / "decifra.sqlite3"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def session_secret(self) -> str:
        return self.app_session_secret or _RUNTIME_SECRET

    @property
    def access_gate_enabled(self) -> bool:
        return bool(self.app_access_password)

    @property
    def ai_enabled(self) -> bool:
        """Há provedor de IA utilizável? Sem isso o sistema roda só como motor."""
        return bool(self.openai_api_key) and self.ai_provider != "none"

    def public_config(self) -> dict:
        """Configuração que o frontend pode conhecer. Nunca inclui segredo."""
        return {
            "appName": self.app_name,
            "appShortName": self.app_short_name,
            "appDescription": self.app_description,
            "accessGate": self.access_gate_enabled,
            "aiEnabled": self.ai_enabled,
            "uploadChunkBytes": self.upload_chunk_mb * 1024 * 1024,
            "maxZipMb": self.max_zip_mb,
            "maxJobCostUsd": self.max_job_cost_usd,
            "jobRetentionHours": self.job_retention_hours,
            "autoConfirmProcessing": self.auto_confirm_processing,
        }


_RUNTIME_SECRET = secrets.token_urlsafe(32)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
