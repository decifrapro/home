"""Conversa com o Supabase: banco (PostgREST) e arquivos (Storage).

Usado quando o Decifra Pro roda na Vercel, onde não existe disco que dure nem
banco local. A chave de serviço fica só no servidor.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class SupabaseError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class SupabaseClient:
    """Cliente mínimo: só o que o Decifra Pro precisa, sem SDK pesado."""

    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url or not settings.supabase_service_key:
            raise SupabaseError(
                "Supabase não configurado: defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY."
            )
        self._base = settings.supabase_url.rstrip("/")
        self._key = settings.supabase_service_key
        self._bucket = settings.supabase_bucket
        self._timeout = settings.supabase_timeout_seconds

    # ── infraestrutura ──────────────────────────────────────────────────────
    @property
    def bucket(self) -> str:
        return self._bucket

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
        }
        if extra:
            headers.update(extra)
        return headers

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=httpx.Timeout(self._timeout), follow_redirects=True)

    def _check(self, response: httpx.Response, acao: str) -> httpx.Response:
        if response.status_code >= 400:
            detalhe = response.text[:400]
            raise SupabaseError(f"{acao} falhou ({response.status_code}): {detalhe}", response.status_code)
        return response

    # ── banco de dados (PostgREST) ──────────────────────────────────────────
    def select(
        self,
        tabela: str,
        *,
        filtros: dict[str, str] | None = None,
        colunas: str = "*",
        ordem: str | None = None,
        limite: int | None = None,
    ) -> list[dict[str, Any]]:
        parametros: dict[str, str] = {"select": colunas}
        parametros.update(filtros or {})
        if ordem:
            parametros["order"] = ordem
        if limite:
            parametros["limit"] = str(limite)
        with self._client() as cliente:
            resposta = cliente.get(
                f"{self._base}/rest/v1/{tabela}", params=parametros, headers=self._headers()
            )
        return self._check(resposta, f"leitura de {tabela}").json()

    def insert(self, tabela: str, linhas: list[dict[str, Any]] | dict[str, Any]) -> list[dict[str, Any]]:
        corpo = linhas if isinstance(linhas, list) else [linhas]
        if not corpo:
            return []
        with self._client() as cliente:
            resposta = cliente.post(
                f"{self._base}/rest/v1/{tabela}",
                content=json.dumps(corpo, ensure_ascii=False, default=str),
                headers=self._headers(
                    {"Content-Type": "application/json", "Prefer": "return=representation"}
                ),
            )
        return self._check(resposta, f"gravação em {tabela}").json()

    def upsert(self, tabela: str, linhas: list[dict[str, Any]]) -> None:
        if not linhas:
            return
        with self._client() as cliente:
            resposta = cliente.post(
                f"{self._base}/rest/v1/{tabela}",
                content=json.dumps(linhas, ensure_ascii=False, default=str),
                headers=self._headers(
                    {
                        "Content-Type": "application/json",
                        "Prefer": "resolution=merge-duplicates,return=minimal",
                    }
                ),
            )
        self._check(resposta, f"gravação em {tabela}")

    def update(self, tabela: str, filtros: dict[str, str], valores: dict[str, Any]) -> None:
        with self._client() as cliente:
            resposta = cliente.patch(
                f"{self._base}/rest/v1/{tabela}",
                params=filtros,
                content=json.dumps(valores, ensure_ascii=False, default=str),
                headers=self._headers({"Content-Type": "application/json", "Prefer": "return=minimal"}),
            )
        self._check(resposta, f"atualização de {tabela}")

    def update_returning(
        self, tabela: str, filtros: dict[str, str], valores: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Atualiza e devolve o que mudou — usado para reservar um item sem corrida."""
        with self._client() as cliente:
            resposta = cliente.patch(
                f"{self._base}/rest/v1/{tabela}",
                params=filtros,
                content=json.dumps(valores, ensure_ascii=False, default=str),
                headers=self._headers(
                    {"Content-Type": "application/json", "Prefer": "return=representation"}
                ),
            )
        return self._check(resposta, f"reserva em {tabela}").json()

    def delete(self, tabela: str, filtros: dict[str, str]) -> None:
        with self._client() as cliente:
            resposta = cliente.delete(
                f"{self._base}/rest/v1/{tabela}",
                params=filtros,
                headers=self._headers({"Prefer": "return=minimal"}),
            )
        self._check(resposta, f"remoção em {tabela}")

    # ── arquivos (Storage) ──────────────────────────────────────────────────
    def signed_upload_url(self, caminho: str) -> dict[str, str]:
        """Link temporário para o navegador enviar o ZIP direto ao Supabase.

        O arquivo não passa pela Vercel — é o único jeito de subir 100 MB, já que
        a função só aceita requisições pequenas.
        """
        with self._client() as cliente:
            resposta = cliente.post(
                f"{self._base}/storage/v1/object/upload/sign/{self._bucket}/{caminho}",
                headers=self._headers({"Content-Type": "application/json"}),
                content="{}",
            )
        dados = self._check(resposta, "criação do link de envio").json()
        caminho_assinado = dados.get("url") or ""
        return {
            "path": caminho,
            "signedUrl": f"{self._base}/storage/v1{caminho_assinado}"
            if caminho_assinado.startswith("/")
            else caminho_assinado,
            "token": dados.get("token", ""),
        }

    def signed_download_url(self, caminho: str, segundos: int = 3600) -> str:
        with self._client() as cliente:
            resposta = cliente.post(
                f"{self._base}/storage/v1/object/sign/{self._bucket}/{caminho}",
                headers=self._headers({"Content-Type": "application/json"}),
                content=json.dumps({"expiresIn": segundos}),
            )
        dados = self._check(resposta, "criação do link de leitura").json()
        assinado = dados.get("signedURL") or dados.get("signedUrl") or ""
        return f"{self._base}/storage/v1{assinado}" if assinado.startswith("/") else assinado

    def upload(self, caminho: str, conteudo: bytes, tipo: str = "application/octet-stream") -> None:
        with self._client() as cliente:
            resposta = cliente.post(
                f"{self._base}/storage/v1/object/{self._bucket}/{caminho}",
                headers=self._headers({"Content-Type": tipo, "x-upsert": "true"}),
                content=conteudo,
            )
        self._check(resposta, "envio de arquivo")

    def download(self, caminho: str) -> bytes:
        with self._client() as cliente:
            resposta = cliente.get(
                f"{self._base}/storage/v1/object/{self._bucket}/{caminho}", headers=self._headers()
            )
        return self._check(resposta, "leitura de arquivo").content

    def download_range(self, caminho: str, inicio: int, fim: int) -> bytes:
        """Lê só um pedaço do arquivo — é o que permite abrir o ZIP sem baixar tudo."""
        with self._client() as cliente:
            resposta = cliente.get(
                f"{self._base}/storage/v1/object/{self._bucket}/{caminho}",
                headers=self._headers({"Range": f"bytes={inicio}-{fim}"}),
            )
        if resposta.status_code not in (200, 206):
            self._check(resposta, "leitura parcial de arquivo")
        return resposta.content

    def file_size(self, caminho: str) -> int:
        with self._client() as cliente:
            resposta = cliente.head(
                f"{self._base}/storage/v1/object/{self._bucket}/{caminho}", headers=self._headers()
            )
        if resposta.status_code >= 400:
            # HEAD pode não ser permitido: cai para uma leitura de 1 byte com Range.
            with self._client() as cliente:
                resposta = cliente.get(
                    f"{self._base}/storage/v1/object/{self._bucket}/{caminho}",
                    headers=self._headers({"Range": "bytes=0-0"}),
                )
            self._check(resposta, "consulta de tamanho")
            faixa = resposta.headers.get("content-range", "")
            if "/" in faixa:
                return int(faixa.rsplit("/", 1)[1])
            raise SupabaseError("não foi possível descobrir o tamanho do arquivo")
        return int(resposta.headers.get("content-length", 0))

    def remove_prefix(self, prefixo: str) -> None:
        """Apaga tudo de um atendimento."""
        with self._client() as cliente:
            listagem = cliente.post(
                f"{self._base}/storage/v1/object/list/{self._bucket}",
                headers=self._headers({"Content-Type": "application/json"}),
                content=json.dumps({"prefix": prefixo, "limit": 1000}),
            )
            arquivos = self._check(listagem, "listagem de arquivos").json()
            caminhos = [f"{prefixo}/{item['name']}" for item in arquivos if item.get("name")]
            if not caminhos:
                return
            resposta = cliente.request(
                "DELETE",
                f"{self._base}/storage/v1/object/{self._bucket}",
                headers=self._headers({"Content-Type": "application/json"}),
                content=json.dumps({"prefixes": caminhos}),
            )
        self._check(resposta, "remoção de arquivos")
