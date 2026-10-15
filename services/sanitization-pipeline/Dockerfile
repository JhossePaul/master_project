# syntax=docker/dockerfile:1.7
# Imagen de voc-sanitization-job (Cloud Run Job, sin argumentos).
# Construir desde la raíz del workspace:
#   docker build -f services/sanitization-pipeline/Dockerfile .
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
# Capa de dependencias: metadatos del workspace y el lockfile.
COPY pyproject.toml uv.lock ./
COPY infra/pyproject.toml infra/
COPY packages/voc-common/pyproject.toml packages/voc-common/
COPY services/ingestion-worker/pyproject.toml services/ingestion-worker/
COPY services/sanitization-pipeline/pyproject.toml services/sanitization-pipeline/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package sanitization-pipeline \
        --no-install-workspace
# Código: voc-common, ingestion-worker (solo lectura de estado) y el pipeline.
COPY packages/voc-common/src packages/voc-common/src
COPY services/ingestion-worker/src services/ingestion-worker/src
COPY services/sanitization-pipeline/src services/sanitization-pipeline/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package sanitization-pipeline --no-editable

FROM ${PYTHON_IMAGE} AS runtime
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home app
COPY --from=builder --chown=root:root /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
USER 10001:10001
# El Job de Pulumi no fija `command`: este ENTRYPOINT es lo que se ejecuta.
ENTRYPOINT ["python", "-m", "sanitization_pipeline.pipeline"]
