#!/usr/bin/env python3
"""Gera um ZIP sintético no formato de exportação do WhatsApp.

Nenhum dado pessoal: as mídias são geradas artificialmente e o texto é fictício.
Uso: python3 gerar_zip.py [destino.zip]
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).parent
MEDIA = BASE / "media"

CHAT = """‎25/08/2026 10:40 - As mensagens e as chamadas são criptografadas de ponta a ponta.
25/08/2026 10:45 - Sanchai: Boa tarde, Sr. Rui
Consegui a condição que conversamos
25/08/2026 10:52 - Sanchai: audio.opus (arquivo anexado)
25/08/2026 11:03 - Rui: imagem.jpg (arquivo anexado)
Olha essa condição
25/08/2026 11:10 - Sanchai: documento.pdf (arquivo anexado)
25/08/2026 11:18 - Sanchai: contrato-com-extensao-errada.jpg (arquivo anexado)
25/08/2026 11:30 - Rui: dá uma olhada em https://example.com/proposta
25/08/2026 12:00 - Rui: video.mp4 (arquivo anexado)
25/08/2026 12:01 - Rui: ficou faltando o anexo aqui: nao-existe-no-zip.pdf (arquivo anexado)
25/08/2026 12:05 - Rui: perfeito 👍 <Esta mensagem foi editada>
"""

FILES = (
    "audio.opus",
    "imagem.jpg",
    "documento.pdf",
    "contrato-com-extensao-errada.jpg",
    "video.mp4",
    "orfao.jpg",
)


def build(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("_chat.txt", CHAT)
        for name in FILES:
            archive.write(MEDIA / name, name)
    return target


if __name__ == "__main__":
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "conversa-sintetica.zip"
    print(f"ZIP sintético gerado em {build(destino)}")
