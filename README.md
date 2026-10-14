# BBVA VoC Analyzer: App Store Label Noise & Incident Analyzer

Motor analítico de procesamiento de lenguaje natural (NLP) en Google Cloud
Platform (GCP) para la recalibración de la métrica de satisfacción del cliente
(True Net Satisfaction Score - TNSS) y el triaje automatizado del backlog de
incidencias a partir de las reseñas de la App Store y Google Play.

Este proyecto está construido bajo un enfoque **Ethics by Design**, garantizando
la privacidad de los usuarios mediante la sanitización activa de PII (Cloud DLP)
e implementando un protocolo **Human-In-The-Loop (HITL)** para la priorización
del backlog.

## 🏗 Arquitectura de la Solución

El flujo de trabajo se divide en 4 capas principales desplegadas de forma
*serverless* en GCP:

1. **Capa de Ingesta:** Workers en Cloud Run orquestados por Cloud Scheduler que
  extraen reseñas y las validan estrictamente mediante Pydantic antes de
  publicarlas en Pub/Sub.
2. **Capa de Sanitización y Almacenamiento:** Pipeline en Apache Beam / Cloud
  Dataflow que integra Cloud DLP para enmascarar datos personales (PII) en tiempo
  real antes de persistir en BigQuery.
3. **Capa de Machine Learning:** Arquitectura Dual LoRA (Delora) desplegada en
  Vertex AI para aislar el *Label Noise Bias* (sesgo de 5 estrellas por
  obligación) y ejecutar análisis de sentimientos y extracción de tópicos (ABSA).
4. **Capa de Consumo:** Backend en FastAPI que expone búsqueda vectorial y
  métricas clave hacia una Single Page Application (SPA) en React para el triaje
  humano.

## 🗂 Estructura del Monorepo

El proyecto utiliza un enfoque de Monorepo gestionado nativamente mediante **uv
workspaces** para aislar dependencias de Python de forma eficiente.

```text
bbva-voc-analyzer/
├── .github/                # Workflows de CI/CD (Quality Gates y Cloud Build)
├── docs/governance/        # Artefactos normativos: Data Card, Model Card, Ethical FMEA
├── infra/                  # Infraestructura como Código (Pulumi - Python)
├── packages/
│   └── voc-common/         # Contratos de datos (Esquemas Pydantic) compartidos
├── services/
│   ├── ingestion-worker/   # Servicio de extracción de reseñas (Google Play/App Store)
│   ├── sanitization-pipeline/ # Job de Dataflow para limpieza y Cloud DLP
│   ├── ml-delora/          # Entrenamiento, inferencia y monitoreo de modelos en Vertex AI
│   └── api-backend/        # API RESTful (FastAPI) de consulta y ruteo
└── web/
    └── hitl-portal/        # Frontend (React + Vite) para exploración de incidentes
```

## 🛠 Stack Tecnológico

* **Lenguajes:** Python 3.11+, TypeScript
* **Gestión de Entornos:** `uv` (Workspaces)
* **Quality Gates (CI/CD):** `Ruff`, `Pytest`, `Bandit`, `Pyrefly`
* **Infraestructura como Código (IaC):** Pulumi (Provider GCP)
* **Google Cloud Platform:** Cloud Run, Pub/Sub, Dataflow, Cloud DLP, BigQuery, Vertex AI
* **Web:** FastAPI, React (Vite)

## 🚀 Instalación y Desarrollo Local

### Requisitos Previos

* [uv](https://docs.astral.sh/uv/getting-started/installation/) instalado globalmente.
* [Pulumi CLI](https://www.pulumi.com/docs/install/) instalado para el despliegue de infraestructura.
* [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) (`gcloud`) configurado y autenticado.
* Node.js y npm/pnpm (para el frontend en React).

### Configuración Inicial

1. **Clonar el repositorio:**

```bash
git clone <URL_DEL_REPOSITORIO>
cd bbva-voc-analyzer
```

2. **Sincronizar el Workspace de Python:**

Al ejecutar el siguiente comando, `uv` resolverá el árbol de dependencias
global, aislará los entornos e instalará los paquetes compartidos (como
`voc-common`) como enlaces locales para los servicios que lo requieran.

```bash
uv sync
```

3. **Ejecutar pruebas locales y Quality Gates:**

Validar que toda la base de código cumple con los estándares:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyrefly check
uv run bandit -c pyproject.toml -r .
uv run pytest packages/voc-common/tests --cov=packages/voc-common/src --cov-fail-under=85
```

El workflow `.github/workflows/ci.yaml` ejecuta estos gates en cada push y
pull request con Python 3.11 y las versiones de `uv.lock`. La cobertura mínima
de `voc-common` es del 85%. Los servicios e infraestructura vacíos se incorporan
al workspace al implementar sus respectivas épicas.

4. **Activar hooks locales:**

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

Los hooks ejecutan Ruff (lint con correcciones y formato) y Bandit usando el
mismo entorno de `uv` que CI. Los fallbacks de variables en CI son exclusivos
de pruebas; la sal real de producción se configura por separado.

## 🔐 Gobierno de Datos

Siguiendo los lineamientos de la Norma Data Governance y Privacidad, revisar la
carpeta `/docs/governance/` para consultar la documentación auditable:

* Origen de la ingesta y clasificación (*Trusted Data Source*).
* Matriz de Riesgos Éticos (FMEA).
* Protocolos de manejo de PII y *Fallback Plans* para *Model Drift*.
