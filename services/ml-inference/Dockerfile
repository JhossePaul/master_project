# syntax=docker/dockerfile:1.7
# Imagen de ml-inference: Jobs voc-ml-inference-delta (`delta`) y
# voc-ml-monitor (`monitor`); Pulumi pasa el subcomando como argumento.
# Construir desde la raíz del workspace:
#   docker build -f services/ml-inference/Dockerfile .
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
# Capa de dependencias: metadatos del workspace y el lockfile (torch de CPU).
COPY pyproject.toml uv.lock ./
COPY infra/pyproject.toml infra/
COPY packages/voc-common/pyproject.toml packages/voc-common/
COPY packages/voc-nlp/pyproject.toml packages/voc-nlp/
COPY services/ml-inference/pyproject.toml services/ml-inference/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package ml-inference --no-install-workspace
# Código: voc-common, voc-nlp (con el léxico y el prompt) y el servicio.
COPY packages/voc-common/src packages/voc-common/src
COPY packages/voc-nlp/src packages/voc-nlp/src
COPY services/ml-inference/src services/ml-inference/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package ml-inference --no-editable

FROM ${PYTHON_IMAGE} AS runtime
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home app
COPY --from=builder --chown=root:root /opt/venv /opt/venv
# Sin descargas en producción: los modelos llegan de ml_artifacts/.
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 \
    HF_HOME=/tmp/huggingface \
    NUMBA_CACHE_DIR=/tmp/numba \
    MPLCONFIGDIR=/tmp/matplotlib \
    KAGGLE_CONFIG_DIR=/tmp/kaggle
WORKDIR /app
USER 10001:10001
ENTRYPOINT ["python", "-m", "ml_inference"]
