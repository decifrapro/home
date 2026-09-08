"""Aplicação FastAPI: API, worker de background e frontend compilado.

Um único servidor, um único container. O worker roda no mesmo processo, em
tarefa separada do request HTTP — o processamento não depende de conexão aberta.
"""

from __future__ import annotations

import logging
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
    db.connect()
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
    title=settings.app_name,
    description=settings.app_description,
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
