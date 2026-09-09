"""Porta de entrada do Decifra Pro na Vercel.

A Vercel executa este arquivo como função e procura, **no nível de cima do
arquivo**, uma variável chamada `app`. Ela precisa estar aqui de forma simples e
visível: se a definição ficar escondida dentro de um `try`, a plataforma não a
encontra e recusa a publicação inteira.

Por isso o carregamento acontece dentro de uma função e o resultado é atribuído
a `app` numa linha só. Se a aplicação de verdade não puder ser carregada, entra
no lugar dela uma página de socorro que conta o motivo — sem isso, qualquer erro
na subida vira só "esta função falhou", sem dizer nada.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
BACKEND = RAIZ / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Variáveis cujo valor nunca pode aparecer numa tela de erro.
SEGREDOS = (
    "OPENAI_API_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_SERVICE_KEY",
    "APP_ACCESS_PASSWORD",
    "APP_SESSION_SECRET",
    "CRON_SECRET",
)


def _redigir(texto: str) -> str:
    """Tira do texto qualquer segredo que tenha vazado para a mensagem de erro."""
    for nome in SEGREDOS:
        valor = os.environ.get(nome)
        if valor and len(valor) > 6:
            texto = texto.replace(valor, f"[{nome} oculta]")
    return texto


def _variaveis_configuradas() -> dict:
    """Nomes das variáveis e se alguma chegou vazia — nunca os valores."""
    return {
        nome: ("vazia" if valor == "" else f"{len(valor)} caracteres")
        for nome, valor in sorted(os.environ.items())
        if not nome.startswith(("AWS_", "LAMBDA_", "_", "npm_", "VERCEL_OIDC"))
    }


class PaginaDeSocorro:
    """Aplicação mínima que só existe para contar por que a de verdade não subiu."""

    def __init__(self, erro: str) -> None:
        self.erro = erro

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return
        corpo = json.dumps(
            {
                "erro": "O sistema não conseguiu iniciar.",
                "resumo": self.erro.strip().splitlines()[-1] if self.erro.strip() else "",
                "detalhe": self.erro,
                "variaveisConfiguradas": _variaveis_configuradas(),
                "oQueFazer": (
                    "Mande esta tela inteira para quem cuida do sistema. "
                    "Nenhuma senha ou chave aparece aqui."
                ),
            },
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": corpo})


def _carregar_aplicacao():
    try:
        from app.main import app as aplicacao

        return aplicacao
    except Exception:
        return PaginaDeSocorro(_redigir(traceback.format_exc()))


app = _carregar_aplicacao()
