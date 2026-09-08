"""Porta de entrada do Decifra Pro na Vercel.

A Vercel executa este arquivo como função. Ele só aponta para a aplicação que já
existe em `backend/app` — nenhuma lógica mora aqui, para não haver duas versões
do mesmo programa.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
BACKEND = RAIZ / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402  (o caminho precisa ser ajustado antes do import)

__all__ = ["app"]
