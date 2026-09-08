"""Abre um ZIP guardado no Supabase sem baixar o arquivo inteiro.

O ZIP de uma conversa passa fácil de 100 MB. Na Vercel não dá para baixar tudo
a cada passo: o tempo e a memória são curtos. Como o formato ZIP tem um índice
no fim do arquivo, dá para ler só os pedaços necessários — o índice primeiro, e
depois apenas os bytes da mídia que está sendo processada naquele momento.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable

BLOCO_PADRAO = 512 * 1024


class ArquivoPorFaixa(io.RawIOBase):
    """Arquivo virtual que busca os bytes sob demanda, em faixas."""

    def __init__(
        self,
        tamanho: int,
        ler_faixa: Callable[[int, int], bytes],
        bloco: int = BLOCO_PADRAO,
    ) -> None:
        self._tamanho = tamanho
        self._ler_faixa = ler_faixa
        self._bloco = max(32 * 1024, bloco)
        self._posicao = 0
        self._cache_inicio = 0
        self._cache = b""
        self.requisicoes = 0

    # ── io.RawIOBase ────────────────────────────────────────────────────────
    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False

    def tell(self) -> int:
        return self._posicao

    def seek(self, deslocamento: int, de_onde: int = io.SEEK_SET) -> int:
        if de_onde == io.SEEK_SET:
            nova = deslocamento
        elif de_onde == io.SEEK_CUR:
            nova = self._posicao + deslocamento
        elif de_onde == io.SEEK_END:
            nova = self._tamanho + deslocamento
        else:
            raise ValueError("origem de posicionamento inválida")
        self._posicao = max(0, min(self._tamanho, nova))
        return self._posicao

    def read(self, quantidade: int = -1) -> bytes:
        if quantidade is None or quantidade < 0:
            quantidade = self._tamanho - self._posicao
        quantidade = min(quantidade, self._tamanho - self._posicao)
        if quantidade <= 0:
            return b""

        pedacos: list[bytes] = []
        restante = quantidade
        while restante > 0:
            bloco = self._do_cache(self._posicao, restante)
            if not bloco:
                break
            pedacos.append(bloco)
            self._posicao += len(bloco)
            restante -= len(bloco)
        return b"".join(pedacos)

    def readinto(self, destino) -> int:  # type: ignore[override]
        dados = self.read(len(destino))
        destino[: len(dados)] = dados
        return len(dados)

    # ── cache de um bloco ───────────────────────────────────────────────────
    def _do_cache(self, posicao: int, quantidade: int) -> bytes:
        fim_cache = self._cache_inicio + len(self._cache)
        if not (self._cache and self._cache_inicio <= posicao < fim_cache):
            inicio = posicao
            fim = min(self._tamanho, inicio + max(self._bloco, quantidade)) - 1
            if fim < inicio:
                return b""
            self._cache = self._ler_faixa(inicio, fim)
            self._cache_inicio = inicio
            self.requisicoes += 1
            if not self._cache:
                return b""
            fim_cache = self._cache_inicio + len(self._cache)

        deslocamento = posicao - self._cache_inicio
        return self._cache[deslocamento : deslocamento + quantidade]


def abrir_zip_por_faixa(
    tamanho: int, ler_faixa: Callable[[int, int], bytes], bloco: int = BLOCO_PADRAO
) -> zipfile.ZipFile:
    """Devolve um ZipFile que lê o arquivo remoto sob demanda."""
    bruto = ArquivoPorFaixa(tamanho, ler_faixa, bloco)
    return zipfile.ZipFile(io.BufferedReader(bruto, buffer_size=bloco))
