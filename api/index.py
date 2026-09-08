"""Porta de entrada do Decifra Pro na Vercel.

A Vercel executa este arquivo como função. Ele aponta para a aplicação que já
existe em `backend/app` — nenhuma lógica de negócio mora aqui.

Se a aplicação não conseguir nem ser carregada, este arquivo sobe no lugar dela
uma página de socorro que explica o que aconteceu. Sem isso, qualquer erro na
subida vira só "esta função falhou", sem dizer o motivo, e não há como
descobrir nada pelo navegador.
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


def _inventario_do_ambiente() -> dict:
    """Nomes das variáveis configuradas e se alguma chegou vazia — nunca os valores."""
    interessantes = {
        nome: ("vazia" if valor == "" else f"{len(valor)} caracteres")
        for nome, valor in sorted(os.environ.items())
        if not nome.startswith(("AWS_", "LAMBDA_", "_", "npm_"))
    }
    return interessantes


try:
    from app.main import app  # noqa: E402  (o caminho precisa ser ajustado antes)
except Exception:  # a aplicação nem carregou
    _ERRO = _redigir(traceback.format_exc())

    async def app(scope, receive, send):  # type: ignore[misc]
        """Página de socorro: conta o que impediu o sistema de subir."""
        if scope["type"] != "http":
            return

        corpo = json.dumps(
            {
                "erro": "O sistema não conseguiu iniciar.",
                "detalhe": _ERRO.splitlines()[-1] if _ERRO else "",
                "tracebackCompleto": _ERRO,
                "variaveisConfiguradas": _inventario_do_ambiente(),
                "oQueFazer": (
                    "Copie esta tela inteira e mande para quem cuida do sistema. "
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


__all__ = ["app"]
