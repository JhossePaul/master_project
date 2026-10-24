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
3. **Capa de Machine Learning:** RoBERTuito ajustado para sentimiento, con
  *temperature scaling* y revisión humana por apetito de riesgo; familias de
  aspectos con Gemini en Vertex AI y tópicos con BERTopic congelado. Corre como
  Cloud Run Jobs en CPU (delta diario) y escribe salidas versionadas en
  BigQuery (EPIC-5 decide los modelos; EPIC-6 los despliega).
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
│   ├── voc-common/         # Contratos de datos (Esquemas Pydantic) compartidos
│   └── voc-nlp/            # Lógica de inferencia portada de EPIC-5 (elegibilidad, modelos)
├── services/
│   ├── ingestion-worker/   # Servicio de extracción de reseñas (Google Play/App Store)
│   ├── sanitization-pipeline/ # Job de Dataflow para limpieza y Cloud DLP
│   ├── ml-inference/       # Jobs de inferencia batch, cargas y siembra (EPIC-6)
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
de `voc-common` es del 85%. Los servicios vacíos se incorporan
al workspace al implementar sus respectivas épicas.

4. **Activar hooks locales:**

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

Los hooks ejecutan Ruff (lint con correcciones y formato) y Bandit usando el
mismo entorno de `uv` que CI. Los fallbacks de variables en CI son exclusivos
de pruebas; la sal real de producción se configura por separado.

### Contratos de ingesta v2 (Épica 1)

`voc-common` incluye eventos versionados, IDs de revisión estables, manifiestos,
recibos y reducer por página con un único contrato de estado.
La configuración v2 queda desactivada por defecto hasta aprovisionar sus recursos.
Consultar [contratos, configuración y activación](docs/contracts/ingestion_v2.md)
para los defaults, fixtures y orden de activación con las épicas 2–4.

### Infraestructura Pulumi (Épica 2 implementada)

La suite integrada y el orden del primer despliegue se documentan en
[activación y preview](docs/operations/deployment.md). El preview con proveedor sigue
pendiente de configurar el stack/backend y credenciales reales.

`infra` forma parte del workspace. Sincroniza desde la raíz con
`uv sync --all-packages --locked` antes de ejecutar Pulumi; el runtime utiliza
el entorno compartido `.venv`.

La opción del runtime se documenta en la
[referencia de proyectos Pulumi](https://www.pulumi.com/docs/iac/concepts/projects/project-file/).

La validación de infraestructura usa mocks y no requiere credenciales GCP:

```bash
uv run pytest infra/tests --cov=infra/modules --cov-fail-under=80
```

Para revisar el plan de desarrollo, instala la CLI de Pulumi, configura su
backend y las credenciales GCP con permisos de activación de servicios, ajusta
el proyecto en `infra/Pulumi.dev.yaml` y ejecuta desde `infra`:

```bash
pulumi preview --stack dev
```

El plan activa las APIs y crea las cuatro cuentas de servicio con sus roles.
Con `bbva-voc-infra:enable_cmek=true` también crea el keyring regional y una
llave de cifrado con rotación cada 90 días; por defecto CMEK está desactivado.
Las asignaciones usan
[`projects.IAMMember`](https://www.pulumi.com/registry/packages/gcp%407.x/api-docs/projects/iammember/)
para agregar permisos sin reemplazar los miembros existentes de cada rol.
El plan también crea las plantillas DLP regionales de inspección y
desidentificación, con detectores bancarios y exclusión para códigos técnicos.
La sustitución explícita por detector produce tokens con corchetes, como
`[PERSON_NAME]`; la
[sustitución nativa por infoType](https://docs.cloud.google.com/sensitive-data-protection/docs/deidentify-sensitive-data#replacewithinfotypeconfig)
devuelve nombres sin corchetes. Se exportan los IDs de ambas plantillas para
el futuro pipeline de sanitización.
El plan crea también Pub/Sub con DLQ, un bucket de staging con eliminación
por edad de 7 días y el dataset BigQuery con cuatro tablas curadas/auditoría.
No hay tabla de reseñas crudas. Los prefijos de watermarks quedan fuera de la
regla de eliminación. CMEK, cuando está activado, incluye permisos para los
agentes de servicio y se aplica a todos los repositorios. El borrado de contenido
al destruir recursos solo está habilitado en `dev`.
El cómputo incluye dos servicios Cloud Run privados con escala mínima cero,
un Job de sanitización con DirectRunner y dos jobs diarios de Scheduler en
modo Free Tier (08:00 ingesta, 08:30 sanitización, America/Mexico_City).
Con `free_tier_mode=false`, hay cinco ingestas escalonadas y sanitización
a las 09:30. Con el flag de Vertex activo también se define el endpoint y
un índice vectorial batch; primero deben existir embeddings en
`gs://<bucket>/vertex/embeddings/`.

Antes de desplegar, publica las imágenes indicadas por `ingestion_worker_image`,
`sanitization_job_image` y `api_backend_image`. En producción configura la sal
desde `infra` con `pulumi config set --secret user_hash_salt '<sal-propia>'`.
El pool de proxies admite una lista JSON en `scraper_proxy_pool_urls`, también
configurable como secreto. Estos valores se mantienen secretos en el estado
Pulumi; Cloud Run recibe las variables necesarias para ejecutar los servicios.
La suite de aceptación `infra/tests/test_infra.py` comprueba BigQuery sin PII
cruda, reglas DLP, escala mínima cero, cuota de dos jobs Free Tier y lifecycle
del staging, además del grafo de dependencias declarado. Hay 37 pruebas de
infraestructura con 100% de cobertura de los módulos, ejecutadas también en CI.
La implementación de las seis features está terminada; el preview y la
validación real de despliegue siguen pendientes.

## 🔐 Gobierno de Datos

Siguiendo los lineamientos de la Norma Data Governance y Privacidad, revisar la
carpeta `/docs/governance/` para consultar la documentación auditable:

* Origen de la ingesta y clasificación (*Trusted Data Source*).
* Matriz de Riesgos Éticos (FMEA).
* Protocolos de manejo de PII y *Fallback Plans* para *Model Drift*.
