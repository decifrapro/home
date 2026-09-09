"""Aplicação FastAPI: API, worker de background e frontend compilado.

Um único servidor, um único container. O worker roda no mesmo processo, em
tarefa separada do request HTTP — o processamento não depende de conexão aberta.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.api.routes import router
from app.config import settings
from app.jobs.worker import purge_expired, runner

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("decifra")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db.connect()
    except Exception as exc:
        # Numa função sem processo de pé, morrer aqui derruba toda requisição,
        # inclusive a de diagnóstico. Melhor subir e deixar o erro aparecer na
        # tela, com texto que diga o que fazer.
        logger.error("não consegui falar com o banco: %s", exc)
    if not settings.serverless:
        # Servidor próprio: existe processo de pé, então o worker roda aqui.
        purge_expired()
        await runner.start()
    logger.info(
        "%s no ar — ia=%s guarda=%s",
        settings.app_name,
        settings.ai_enabled,
        db.backend,
    )
    yield
    if not settings.serverless:
        await runner.stop()


app = FastAPI(
    # Um título vazio faz o FastAPI recusar subir. O nome vem da configuração,
    # mas nunca pode ficar em branco por causa de uma variável mal preenchida.
    title=settings.app_name or "Decifra Pro",
    description=settings.app_description or "Leitor multimodal de conversas do WhatsApp",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/api/diag", include_in_schema=False)
def diagnostico() -> dict:
    """Diz o que está configurado e o que responde. Nunca mostra segredo."""
    resultado: dict = {
        "app": settings.app_name,
        "guarda": db.backend,
        "iaConfigurada": settings.ai_enabled,
        "supabaseConfigurado": bool(settings.supabase_url and settings.supabase_service_key),
        "senhaDeAcesso": settings.access_gate_enabled,
        "segredoDeSessao": bool(settings.app_session_secret),
        "ffmpeg": settings.storage_mode != "supabase",
        "frontendCompilado": (settings.frontend_dist / "index.html").exists(),
        "faltaConfigurar": settings.pendencias_de_configuracao(),
    }
    try:
        db.connect()
        resultado["banco"] = "ok"
    except Exception as exc:
        resultado["banco"] = f"falhou: {str(exc)[:300]}"

    # Nomes das variáveis de ambiente e se alguma chegou vazia. Nunca os valores:
    # variável vazia no lugar errado já derrubou o sistema uma vez, e sem isso
    # não havia como enxergar.
    resultado["variaveis"] = {
        nome: ("vazia" if valor == "" else f"{len(valor)} caracteres")
        for nome, valor in sorted(os.environ.items())
        if not nome.startswith(("AWS_", "LAMBDA_", "_", "npm_"))
    }
    return resultado


@app.exception_handler(ValueError)
async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve o frontend compilado, com fallback de SPA para as rotas do app."""
    if not dist.is_dir() or not (dist / "index.html").exists():
        logger.info("frontend compilado não encontrado em %s (modo somente API)", dist)
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        candidate = (dist / full_path).resolve()
        if full_path and str(candidate).startswith(str(dist.resolve())) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


mount_frontend(app, settings.frontend_dist)
