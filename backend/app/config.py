"""Configuração central do Decifra Pro.

Tudo que muda entre ambientes (nome do produto, limites, modelos de IA, preços)
vive aqui e vem de variável de ambiente. Nada disso deve ser escrito direto no
código do resto do projeto.
"""

from __future__ import annotations

import secrets
import shutil
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.versao import VERSAO


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # Identidade
    app_name: str = "Decifra Pro"
    app_short_name: str = "Decifra"
    app_description: str = "Leitor multimodal de conversas exportadas do WhatsApp"

    # Servidor. Os nomes levam APP_ na frente de propósito: `PORT` e `HOST` são
    # usados por várias plataformas de hospedagem, e uma delas chegando vazia
    # derrubava a configuração inteira.
    host: str = Field(default="0.0.0.0", alias="APP_HOST")
    port: int = Field(default=8000, alias="APP_PORT")
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Armazenamento local (servidor próprio, Docker, desenvolvimento)
    data_dir: Path = Path("/data")
    database_path: str = ""

    # Armazenamento na nuvem (Vercel + Supabase). Preenchido, passa a valer no
    # lugar do SQLite e do disco local.
    supabase_url: str = ""
    # A chave é conhecida por dois nomes: o do Supabase antigo (service_role) e o
    # curto. Os dois valem, para o que está escrito na documentação sempre funcionar.
    supabase_service_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_KEY", "supabase_service_key"
        ),
    )
    supabase_bucket: str = "decifra"
    supabase_table_prefix: str = "decifra_"
    supabase_timeout_seconds: int = 60

    # Processamento em blocos curtos, para caber no tempo da função da Vercel.
    # A função da Vercel é morta aos 60 s. O bloco mira 30 s de trabalho e a
    # resposta sai, no pior caso, aos 50 — nunca sem resposta.
    tick_budget_seconds: int = 30
    tick_hard_limit_seconds: int = 50
    tick_max_items: int = 8
    cron_secret: str = ""

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
    # Teto do arquivo aceito pela API de transcrição (25 MB); sem FFmpeg não dá
    # para dividir, então acima disso o áudio fica marcado como não processado.
    audio_max_upload_mb: int = 24
    audio_chunk_seconds: int = 600
    pdf_max_pages: int = 300
    pdf_min_chars_per_page: int = 180
    link_timeout_seconds: int = 20
    link_max_download_mb: int = 8
    enable_playwright: bool = False

    # Custo
    max_job_cost_usd: float = 5.0
    auto_confirm_processing: bool = True
    price_transcription_per_minute: float = 0.006
    price_vision_input_per_mtok: float = 0.40
    price_vision_output_per_mtok: float = 1.60

    # Ferramentas externas
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"

    # Diretório do frontend compilado (servido pelo backend em produção)
    frontend_dist: Path = Field(default=Path("/app/frontend"))

    @model_validator(mode="before")
    @classmethod
    def _ignorar_vazios(cls, valores: object) -> object:
        """Variável de ambiente vazia vale como "não preenchida", sempre.

        Vale para qualquer campo, inclusive os de texto: cadastrar o nome da
        variável sem valor é o mesmo que não cadastrar. Uma variável vazia já
        derrubou o sistema duas vezes — uma num campo de número e outra no nome
        do aplicativo, que virou título vazio e o servidor recusou subir. Quem
        precisa mesmo de valor é conferido depois, em `pendencias_de_configuracao`.
        """
        if not isinstance(valores, dict):
            return valores
        return {chave: valor for chave, valor in valores.items() if valor != ""}

    @field_validator("data_dir", "frontend_dist", mode="before")
    @classmethod
    def _as_path(cls, value: object) -> object:
        return Path(str(value)) if value else value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def storage_mode(self) -> str:
        """"supabase" quando as credenciais existem; "local" caso contrário."""
        return "supabase" if (self.supabase_url and self.supabase_service_key) else "local"

    @property
    def tempo_limite_de_chamada(self) -> int:
        """Quanto uma chamada de IA pode demorar, sem ultrapassar a vida da função.

        Em servidor próprio vale o valor configurado. Na Vercel a função morre
        em 60 segundos, então esperar 180 por uma resposta só garantiria que o
        trabalho fosse cortado no meio, sem registrar nada.
        """
        if not self.serverless:
            return self.openai_timeout_seconds
        return max(10, min(self.openai_timeout_seconds, self.tick_budget_seconds))

    @property
    def serverless(self) -> bool:
        """Roda em função de curta duração (Vercel), sem disco que dure."""
        return self.storage_mode == "supabase"

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

    def pendencias_de_configuracao(self) -> list[str]:
        """O que ainda falta preencher para o sistema fazer o trabalho todo."""
        faltando = []
        if not self.supabase_url or not self.supabase_service_key:
            faltando.append(
                "SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY: sem elas não há onde guardar "
                "as conversas nem os arquivos."
            )
        if not self.openai_api_key:
            faltando.append(
                "OPENAI_API_KEY: sem ela a conversa é montada, mas áudios, imagens e PDFs "
                "ficam sem ser decifrados."
            )
        if not self.app_access_password:
            faltando.append(
                "APP_ACCESS_PASSWORD: sem senha, qualquer pessoa com o endereço entra."
            )
        if not self.app_session_secret:
            faltando.append(
                "APP_SESSION_SECRET: precisa de um texto longo e aleatório para a senha "
                "de acesso e o atalho do iPhone funcionarem."
            )
        return faltando

    def public_config(self) -> dict:
        """Configuração que o frontend pode conhecer. Nunca inclui segredo."""
        return {
            "versao": VERSAO,
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
            "storageMode": self.storage_mode,
            "ffmpegAvailable": ffmpeg_disponivel(),
            "videoSupported": ffmpeg_disponivel(),
        }


@lru_cache
def ffmpeg_disponivel() -> bool:
    """Existe FFmpeg nesta máquina?

    Em servidor próprio existe e tudo funciona. Na Vercel não existe: nesse caso
    o áudio vai direto para a transcrição, sem conversão, e vídeo não é analisado.
    """
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


_RUNTIME_SECRET = secrets.token_urlsafe(32)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Ambiente sem disco gravável (função da Vercel): só /tmp aceita escrita.
        settings.data_dir = Path("/tmp/decifra")
        settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
