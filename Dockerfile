# ─────────────────────────────────────────────────────────────
# Decifra Pro — imagem única: frontend compilado + API + worker
# ─────────────────────────────────────────────────────────────

# 1) Frontend
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2) Backend + runtime
FROM python:3.11-slim AS runtime

# FFmpeg e ffprobe são obrigatórios (áudio e vídeo).
# libmagic complementa a detecção de tipo por conteúdo.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg \
      libmagic1 \
      tini \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    FRONTEND_DIST=/app/frontend

WORKDIR /app

COPY backend/requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt

# Navegador headless para o fallback de links que dependem de JavaScript.
# Desligado por padrão porque pesa bastante na imagem.
ARG INSTALL_PLAYWRIGHT=false
RUN if [ "$INSTALL_PLAYWRIGHT" = "true" ]; then \
      pip install --no-cache-dir playwright && playwright install --with-deps chromium; \
    fi

COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY --from=frontend /frontend/dist ./frontend

RUN mkdir -p /data/jobs

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
