"""Gate de acesso opcional por senha.

Vazio em `APP_ACCESS_PASSWORD`: aplicativo aberto. Preenchido: exige login antes
de qualquer operação de atendimento.
"""

from __future__ import annotations

import hmac

from fastapi import Cookie, Depends, HTTPException, Response, status
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import Settings, settings

COOKIE_NAME = "decifra_sessao"
MAX_AGE_SECONDS = 60 * 60 * 12


def _serializer(config: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.session_secret, salt="decifra-gate")


def issue_session(response: Response, config: Settings = settings) -> None:
    token = _serializer(config).dumps({"ok": True})
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,  # atrás de proxy HTTPS o próprio navegador já protege o cookie
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


def password_matches(candidate: str, config: Settings = settings) -> bool:
    return hmac.compare_digest(candidate or "", config.app_access_password)


def session_is_valid(token: str | None, config: Settings = settings) -> bool:
    if not token:
        return False
    try:
        _serializer(config).loads(token, max_age=MAX_AGE_SECONDS)
    except BadSignature:
        return False
    except Exception:
        return False
    return True


def get_settings_dep() -> Settings:
    return settings


def require_access(
    decifra_sessao: str | None = Cookie(default=None),
    config: Settings = Depends(get_settings_dep),
) -> None:
    if not config.access_gate_enabled:
        return
    if not session_is_valid(decifra_sessao, config):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Acesso protegido por senha. Entre para continuar.",
        )
