"""De onde vêm os arquivos da conversa.

Duas situações, mesma interface:

- **servidor próprio**: o ZIP é descompactado no disco e os arquivos ficam lá;
- **Vercel + Supabase**: não há disco que dure, então o ZIP fica no Supabase e é
  lido por partes — o índice primeiro e, depois, só os bytes da mídia da vez.
"""

from __future__ import annotations

import hashlib
import logging
import zipfile
from pathlib import Path
from typing import Protocol

from app.config import Settings
from app.models.schemas import CatalogFile
from app.services.mime import detect_mime, mime_from_extension, sniff_bytes
from app.services.remote_zip import abrir_zip_por_faixa
from app.services.supabase_client import SupabaseClient
from app.services.zip_service import ExtractionResult, ZipRejected, extract_zip, read_text_file

logger = logging.getLogger(__name__)

# Cada faixa é uma ida à rede. Blocos pequenos multiplicavam essas idas por
# arquivo; 256 KB cobre a maioria das mídias do WhatsApp em uma ou duas.
BLOCO_CATALOGO = 256 * 1024
BYTES_DE_ASSINATURA = 4096


class FonteZip(Protocol):
    def catalogar(self) -> ExtractionResult: ...

    def ler_texto(self, caminho: str) -> str: ...

    def obter(self, caminho: str, destino: Path) -> Path: ...

    def fechar(self) -> None: ...


class FonteLocal:
    """ZIP descompactado em disco — o caminho do servidor próprio."""

    def __init__(self, zip_path: Path, destino: Path, settings: Settings) -> None:
        self._zip_path = zip_path
        self._destino = destino
        self._settings = settings

    def catalogar(self) -> ExtractionResult:
        return extract_zip(self._zip_path, self._destino, self._settings)

    def ler_texto(self, caminho: str) -> str:
        return read_text_file(self._destino / caminho)

    def obter(self, caminho: str, destino: Path) -> Path:
        origem = self._destino / caminho
        return origem if origem.exists() else destino

    def fechar(self) -> None:
        return None


class FonteSupabase:
    """ZIP guardado no Supabase, lido por faixas de bytes."""

    def __init__(self, cliente: SupabaseClient, caminho_zip: str, settings: Settings) -> None:
        self._cliente = cliente
        self._caminho = caminho_zip
        self._settings = settings
        self._zip: zipfile.ZipFile | None = None

    def _abrir(self) -> zipfile.ZipFile:
        if self._zip is None:
            tamanho = self._cliente.file_size(self._caminho)
            self._zip = abrir_zip_por_faixa(
                tamanho,
                lambda inicio, fim: self._cliente.download_range(self._caminho, inicio, fim),
                bloco=BLOCO_CATALOGO,
            )
        return self._zip

    def catalogar(self) -> ExtractionResult:
        """Lista os arquivos e descobre o tipo real lendo só o começo de cada um."""
        try:
            arquivo = self._abrir()
        except zipfile.BadZipFile as exc:
            raise ZipRejected("invalid_zip", "O arquivo enviado não é um ZIP válido.") from exc

        entradas = [item for item in arquivo.infolist() if not item.is_dir()]
        if len(entradas) > self._settings.max_files_per_zip:
            raise ZipRejected(
                "too_many_files",
                f"O ZIP tem {len(entradas)} arquivos e o limite é {self._settings.max_files_per_zip}.",
            )
        total_declarado = sum(item.file_size for item in entradas)
        if total_declarado > self._settings.max_uncompressed_mb * 1024 * 1024:
            raise ZipRejected(
                "too_large_uncompressed",
                f"O conteúdo descompactado passaria de {self._settings.max_uncompressed_mb} MB.",
            )

        arquivos: list[CatalogFile] = []
        total = 0
        for item in entradas:
            nome = item.filename.replace("\\", "/")
            cabecalho = b""
            try:
                with arquivo.open(item) as fluxo:
                    cabecalho = fluxo.read(BYTES_DE_ASSINATURA)
            except Exception as exc:  # entrada corrompida não derruba o catálogo
                logger.warning("não foi possível ler o início de %s: %s", nome, exc)

            detectado = sniff_bytes(cabecalho) or (_texto_ou_binario(cabecalho))
            por_extensao = mime_from_extension(nome)
            total += item.file_size
            arquivos.append(
                CatalogFile(
                    relative_path=nome,
                    name=nome.rsplit("/", 1)[-1],
                    original_path=nome,
                    original_name=nome.rsplit("/", 1)[-1],
                    size=item.file_size,
                    detected_mime=detectado,
                    extension_mime=por_extensao,
                    mime_mismatch=bool(detectado and por_extensao and detectado != por_extensao),
                )
            )

        candidatos = [
            item
            for item in arquivos
            if item.original_name.lower().endswith(".txt")
            or (item.detected_mime == "text/plain" and "." not in item.original_name)
        ]
        return ExtractionResult(files=arquivos, total_uncompressed=total, txt_candidates=candidatos)

    def ler_texto(self, caminho: str) -> str:
        dados = self._abrir().read(caminho)
        for codificacao in ("utf-8-sig", "utf-8", "utf-16", "cp1252", "latin-1"):
            try:
                return dados.decode(codificacao)
            except UnicodeDecodeError:
                continue
        return dados.decode("utf-8", errors="replace")

    def obter(self, caminho: str, destino: Path) -> Path:
        """Traz uma mídia para o disco temporário, só na hora de processar."""
        destino.parent.mkdir(parents=True, exist_ok=True)
        if destino.exists() and destino.stat().st_size > 0:
            return destino
        with self._abrir().open(caminho) as fluxo, destino.open("wb") as saida:
            while True:
                bloco = fluxo.read(1024 * 256)
                if not bloco:
                    break
                saida.write(bloco)
        return destino

    def fechar(self) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None


def _texto_ou_binario(cabecalho: bytes) -> str | None:
    if not cabecalho:
        return None
    try:
        cabecalho.decode("utf-8")
    except UnicodeDecodeError:
        return "application/octet-stream"
    return "text/plain"


def nome_temporario(job_id: str, caminho: str, raiz: Path) -> Path:
    """Nome curto e seguro no disco temporário, derivado do caminho dentro do ZIP."""
    digest = hashlib.sha1(caminho.encode("utf-8")).hexdigest()[:16]
    sufixo = Path(caminho).suffix[:10]
    return raiz / job_id / f"{digest}{sufixo}"


__all__ = [
    "FonteLocal",
    "FonteSupabase",
    "FonteZip",
    "detect_mime",
    "nome_temporario",
]
