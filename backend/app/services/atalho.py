"""Chave pessoal do Atalho do iPhone.

O iPhone não deixa um site aparecer no botão Compartilhar do WhatsApp — só
aplicativo publicado na App Store. O caminho que existe, e que não custa nada, é
o app Atalhos: um atalho criado uma vez aparece no Compartilhar como se fosse um
aplicativo, e manda o ZIP para cá.

Como o Atalho não sabe fazer login nem renovar sessão, ele se identifica por uma
chave. A chave é derivada do segredo do servidor — não fica guardada em lugar
nenhum, e trocar `APP_SESSION_SECRET` invalida a antiga.
"""

from __future__ import annotations

import hashlib
import hmac

from app.config import Settings

ROTULO = b"decifra-atalho-v1"
CABECALHO = "x-decifra-chave"


class AtalhoIndisponivel(RuntimeError):
    """Falta configurar o segredo do servidor para a chave ser estável."""


def chave_disponivel(settings: Settings) -> bool:
    """Sem `APP_SESSION_SECRET` a chave mudaria a cada reinício do servidor."""
    return bool(settings.app_session_secret)


def gerar_chave(settings: Settings) -> str:
    if not chave_disponivel(settings):
        raise AtalhoIndisponivel(
            "Defina APP_SESSION_SECRET no servidor para poder usar o atalho do iPhone."
        )
    assinatura = hmac.new(settings.app_session_secret.encode("utf-8"), ROTULO, hashlib.sha256)
    return assinatura.hexdigest()[:40]


def chave_confere(candidata: str | None, settings: Settings) -> bool:
    if not candidata or not chave_disponivel(settings):
        return False
    return hmac.compare_digest(candidata.strip(), gerar_chave(settings))
