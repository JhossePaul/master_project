# syntax=docker/dockerfile:1.7
# Imagen del worker de ingesta: API (CMD por defecto) y Job histórico
# (`python -m ingestion_worker.job`, comando fijado por Pulumi).
# Construir desde la raíz del workspace:
#   docker build -f services/ingestion-worker/Dockerfile .
ARG PYTHON_IMAGE=python:3.11-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.1

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /workspace
# Capa de dependencias: solo metadatos del workspace y el lockfile.
COPY pyproject.toml uv.lock ./
COPY infra/pyproject.toml infra/
COPY packages/voc-common/pyproject.toml packages/voc-common/
COPY services/ingestion-worker/pyproject.toml services/ingestion-worker/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package ingestion-worker \
        --no-install-workspace
# Código: voc-common y el worker como paquetes instalados (sin editable).
COPY packages/voc-common/src packages/voc-common/src
COPY services/ingestion-worker/src services/ingestion-worker/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package ingestion-worker --no-editable

FROM ${PYTHON_IMAGE} AS runtime
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home app
COPY --from=builder --chown=root:root /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080
WORKDIR /app
USER 10001:10001
EXPOSE 8080
# Cloud Run inyecta PORT; exec para recibir SIGTERM directamente.
CMD ["sh", "-c", "exec uvicorn ingestion_worker.main:app --host 0.0.0.0 --port \"${PORT:-8080}\" --no-access-log"]
