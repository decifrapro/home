"""Supabase de mentira, na memória.

Serve para exercitar o modo Vercel inteiro sem precisar de um projeto real:
imita o suficiente do banco (filtros no estilo PostgREST) e do armazenamento
(inclusive leitura por faixa de bytes, que é como o ZIP é lido).
"""

from __future__ import annotations

from typing import Any


def _combina(linha: dict, campo: str, expressao: str) -> bool:
    operador, _, valor = expressao.partition(".")
    atual = linha.get(campo)
    if operador == "eq":
        return str(atual) == valor
    if operador == "neq":
        return str(atual) != valor
    if operador == "in":
        return str(atual) in valor.strip("()").split(",")
    if operador == "lt":
        return str(atual or "") < valor
    if operador == "gt":
        return str(atual or "") > valor
    if operador == "is":
        return atual is None if valor == "null" else str(atual) == valor
    raise AssertionError(f"operador não previsto no Supabase de teste: {operador}")


def _combina_ou(linha: dict, expressao: str) -> bool:
    partes = expressao.strip("()").split(",")
    for parte in partes:
        campo, _, resto = parte.partition(".")
        if _combina(linha, campo, resto):
            return True
    return False


class FakeSupabaseClient:
    """Mesma interface do cliente de verdade, guardando tudo em dicionários."""

    def __init__(self, bucket: str = "decifra") -> None:
        self.tabelas: dict[str, list[dict[str, Any]]] = {}
        self.arquivos: dict[str, bytes] = {}
        self.bucket = bucket
        self.leituras_por_faixa = 0

    # ── banco ───────────────────────────────────────────────────────────────
    def _linhas(self, tabela: str) -> list[dict[str, Any]]:
        return self.tabelas.setdefault(tabela, [])

    def _filtrar(self, tabela: str, filtros: dict[str, str] | None) -> list[dict[str, Any]]:
        linhas = self._linhas(tabela)
        for campo, expressao in (filtros or {}).items():
            if campo in {"select", "order", "limit"}:
                continue
            if campo == "or":
                linhas = [linha for linha in linhas if _combina_ou(linha, expressao)]
            else:
                linhas = [linha for linha in linhas if _combina(linha, campo, expressao)]
        return linhas

    def select(self, tabela, *, filtros=None, colunas="*", ordem=None, limite=None):
        linhas = list(self._filtrar(tabela, filtros))
        if ordem:
            campo, _, direcao = ordem.partition(".")
            linhas.sort(key=lambda linha: (linha.get(campo) is None, linha.get(campo)),
                        reverse=direcao == "desc")
        if limite:
            linhas = linhas[:limite]
        return [dict(linha) for linha in linhas]

    def insert(self, tabela, linhas):
        corpo = linhas if isinstance(linhas, list) else [linhas]
        self._linhas(tabela).extend(dict(linha) for linha in corpo)
        return [dict(linha) for linha in corpo]

    def upsert(self, tabela, linhas):
        self.insert(tabela, linhas)

    def update(self, tabela, filtros, valores):
        for linha in self._filtrar(tabela, filtros):
            linha.update(valores)

    def update_returning(self, tabela, filtros, valores):
        alvo = list(self._filtrar(tabela, filtros))
        for linha in alvo:
            linha.update(valores)
        return [dict(linha) for linha in alvo]

    def delete(self, tabela, filtros):
        alvo = {id(linha) for linha in self._filtrar(tabela, filtros)}
        self.tabelas[tabela] = [linha for linha in self._linhas(tabela) if id(linha) not in alvo]

    # ── armazenamento ───────────────────────────────────────────────────────
    def signed_upload_url(self, caminho):
        return {"path": caminho, "signedUrl": f"https://falso/{caminho}?token=abc", "token": "abc"}

    def signed_download_url(self, caminho, segundos=3600):
        return f"https://falso/{caminho}"

    def upload(self, caminho, conteudo, tipo="application/octet-stream"):
        self.arquivos[caminho] = conteudo

    def download(self, caminho):
        return self.arquivos[caminho]

    def download_range(self, caminho, inicio, fim):
        self.leituras_por_faixa += 1
        return self.arquivos[caminho][inicio : fim + 1]

    def file_size(self, caminho):
        return len(self.arquivos[caminho])

    def remove_prefix(self, prefixo):
        for caminho in list(self.arquivos):
            if caminho.startswith(prefixo):
                del self.arquivos[caminho]
