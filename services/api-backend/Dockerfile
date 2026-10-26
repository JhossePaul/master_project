# syntax=docker/dockerfile:1.7
# Imagen de la API y el portal (EPIC-7): FastAPI + `dist/` del frontal.
# Construir desde la raíz del workspace:
#   docker build -f services/api-backend/Dockerfile .
# Solo la API, con `dist/` vacío (`/` responde 404):
#   docker build -f services/api-backend/Dockerfile \
#     --build-arg WEB_SOURCE=web-empty .
ARG PYTHON_IMAGE=python:3.11-slim-bookworm
ARG NODE_IMAGE=node:24-bookworm-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.1
# `web-build` compila web/portal; `web-empty` deja dist/ vacío (la API
# responde 404 en `/`) para construir solo la API.
ARG WEB_SOURCE=web-build

FROM ${UV_IMAGE} AS uv

FROM ${NODE_IMAGE} AS web-build
WORKDIR /web/portal
COPY web/portal/package.json web/portal/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY web/portal/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS web-empty
RUN mkdir -p /web/portal/dist

FROM ${WEB_SOURCE} AS web

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
COPY packages/voc-nlp/pyproject.toml packages/voc-nlp/
COPY services/api-backend/pyproject.toml services/api-backend/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package api-backend \
        --no-install-workspace
# Código: voc-common, voc-nlp (sin extras) y la API como paquetes instalados.
COPY packages/voc-common/src packages/voc-common/src
COPY packages/voc-nlp/src packages/voc-nlp/src
COPY services/api-backend/src services/api-backend/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package api-backend --no-editable

FROM ${PYTHON_IMAGE} AS runtime
ARG BUILD_COMMIT=unknown
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home app
COPY --from=builder --chown=root:root /opt/venv /opt/venv
COPY --from=web --chown=root:root /web/portal/dist /app/static
# Guías de revisión: `guidelines.content_uri` es una ruta del repo.
COPY --chown=root:root docs/analytics/labeling/annotation_guideline.md \
    /app/guidelines/docs/analytics/labeling/annotation_guideline.md
COPY --chown=root:root docs/analytics/eda/eda_aspects_guideline.md \
    /app/guidelines/docs/analytics/eda/eda_aspects_guideline.md
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    STATIC_DIR=/app/static \
    GUIDELINES_DIR=/app/guidelines \
    BUILD_COMMIT=${BUILD_COMMIT}
WORKDIR /app
USER 10001:10001
EXPOSE 8080
# Cloud Run inyecta PORT; exec para recibir SIGTERM directamente. El registro
# de cada petición lo escribe la API (sin correo ni cuerpo): sin access log.
CMD ["sh", "-c", "exec uvicorn api_backend.main:app --host 0.0.0.0 --port \"${PORT:-8080}\" --no-access-log"]
