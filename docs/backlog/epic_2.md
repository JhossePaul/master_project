# EPIC-2: Aprovisionamiento de Infraestructura Serverless y Seguridad en GCP (IaC con Pulumi)

* **Estado:** IMPLEMENTADO — Features 2.1–2.10 verificadas localmente con mocks. Contrato único de estado/auditoría. Preview con proveedor y despliegue pendientes de stack/backend y credenciales reales.
* **Recursos de predicción condicionados (2026-10-18; actualizado 2026-10-22):** la tabla `delora_predictions` (15 columnas, agrupada por `topico`), `hitl_triage_audit_log` y el flag `enable_dedicated_vertex_endpoints` se reemplazan o amplían en [EPIC-6](epic_6.md) (feature 6.2), junto con las tablas de curaduría y el Job de inferencia, cuando se apruebe el registro de decisión de EPIC-5 (5.8); no se reescriben antes. Qué cambia y qué lo decide: [insumos de EPIC-5 en EPIC-6](epic_6.md#-insumos-de-epic-5-que-cambian-epic-1-y-epic-2).
* **Semanas Objetivo:** Semanas 1 - 2
* **Paquetes / Directorios Afectados:**
  * `packages/voc-common/src/voc_common/config.py` (Ampliación de variables para Scraper Propio y Flags de Infraestructura)
  * `infra/pyproject.toml`
  * `infra/Pulumi.yaml`
  * `infra/Pulumi.dev.yaml`
  * `infra/__main__.py`
  * `infra/modules/__init__.py`
  * `infra/modules/apis.py`
  * `infra/modules/kms_iam.py`
  * `infra/modules/dlp.py`
  * `infra/modules/pubsub.py`
  * `infra/modules/storage_bq.py`
  * `infra/modules/cloud_run.py`
  * `infra/modules/cloud_scheduler.py`
  * `infra/modules/vertex_ai.py`
  * `infra/tests/__init__.py`
  * `infra/tests/test_infra.py`
* **Dependencias Previas:** `EPIC-1` completada (`voc-common` disponible e instalable en el workspace).

---

## Base actual sin compatibilidad de despliegues anteriores

No existe despliegue ni datos de una versión anterior. El contrato actual es la
base del primer despliegue: no implementar escritura dual, tablas legado ni
migraciones preventivas. La versión del schema sigue siendo útil para evoluciones
futuras, pero no obliga a conservar diseños descartados.

## Ampliación para watermark v2

Features 2.1–2.6 corresponden a la base implementada. **2.7** incorpora
almacenamiento/permisos v2, **2.8** la auditoría y **2.9** el Job histórico.
**2.10** completa la aceptación local de infraestructura.
Los contratos y transiciones puras pertenecen a EPIC-1 (1.6–1.8), y CAS/lease/replay
al repositorio de EPIC-3.

---

## 🎯 Contexto y Reglas Arquitectónicas para el Agente IA

Esta épica codifica en **Pulumi (Python)** el despliegue reproducible de las 5 capas de la solución en Google Cloud Platform (GCP).
Dado que el entorno de desarrollo inicial opera bajo restricciones de **GCP Free Tier** y que el sistema utilizará un **motor propio de extracción HTTP (`batchexecute`) con rotación de IPs** para superar el *throttling* de Google Play Store a gran escala, el Agente IA **DEBE** implementar las siguientes 5 reglas de diseño:

1. **Modo Free Tier Parametrizable (`free_tier_mode: true` por defecto):**
   * **Cifrado CMEK Condicional (`enable_cmek: false`):** El módulo `kms_iam.py` debe contener el código completo de `gcp.kms.KeyRing` y `gcp.kms.CryptoKey`. Si `enable_cmek` es `False`, las funciones retornan `kms_key_name = None` y los recursos de Cloud Storage, BigQuery y Pub/Sub utilizan el cifrado AES-256 gratuito administrado por Google. Si es `True`, se enlaza la llave CMEK a todos los repositorios.
   * **Ejecución Serverless de Apache Beam (`use_dataflow_Flex_runner: false`):** Para no agotar la cuota de vCPUs de Compute Engine en Free Tier ni pagar VMs encendidas 24/7 para un flujo diario promedio de ~166 reseñas por banco, el pipeline de sanitización (`Apache Beam + Cloud DLP`) se aprovisiona por defecto como un **Cloud Run Job (`gcp.cloudrunv2.Job`)** ejecutando `DirectRunner` que drena la suscripción Pull de Pub/Sub una vez al día y se apaga a costo $0.
   * **Búsqueda Vectorial en BigQuery (`enable_dedicated_vertex_endpoints: false`):** Los vectores de embeddings (`ARRAY<FLOAT64>`) se almacenan en BigQuery para realizar búsqueda semántica por similitud coseno (`VECTOR_SEARCH` / `ML.DISTANCE`) sin pagar nodos dedicados de Vertex AI Vector Search en reposo (~$150 USD/mes). Los recursos `AiIndex` y `AiEndpoint` quedan codificados tras este flag booleano.
2. **Privacidad por Diseño (Cero PII en BigQuery):**
   * En estricto apego a la normativa de *Ethics by Design* y LFPDPPP, **no existe tabla de datos crudos en BigQuery**.
   * El flujo físico es: `Cloud Run Worker` $\rightarrow$ `Pub/Sub (voc-raw-reviews-topic)` (con staging efímero en Cloud Storage con regla de autodestrucción a los 7 días) $\rightarrow$ `Pipeline Sanitización + Cloud DLP` $\rightarrow$ `BigQuery Trusted Data Source (sanitized_reviews_tds)`.
3. **Soporte de Infraestructura para Scraper Propio Anti-Throttling:**
   * No se dependerá de la librería externa `google-play-scraper`. El contenedor `voc-ingestion-worker` recibirá por variables de entorno los parámetros para el cliente propio de `batchexecute` (`SCRAPER_PROXY_POOL_URLS`, `SCRAPER_ROTATE_PROXY_EVERY_N_BATCHES`, `SCRAPER_PAGE_SIZE`, `SCRAPER_BASE_DELAY_SEC`, `SCRAPER_MAX_JITTER_SEC`).
4. **Watermarks Atómicos en Cloud Storage + Auditoría en BigQuery:**
   * El estado vivo v2 reside en `gs://<bucket>/state/watermarks/{bank_id}.json`, con CAS por generación y lease con fencing; una sobrescritura incondicional no es un checkpoint seguro. Planes, streams, manifiestos y ledgers se referencian bajo `state/ingestion/{bank_id}/`. El contrato detallado de persistencia se define en EPIC-3. BigQuery conserva auditoría append-only, nunca decide el avance transaccional. El checkpoint se confirma por página completa respaldada y con todas sus publicaciones confirmadas; no por un número fijo de reseñas ni por mínimos/máximos observados.
5. **Ahorro de Cuota en Cloud Scheduler (Límite de 3 Jobs gratuitos):**
   * En `free_tier_mode: true`, se crean únicamente **2 Jobs en Cloud Scheduler**: (1) un job maestro que invoca la ingesta secuencial escalonada de los 5 bancos (`BBVA`, `NUBANK`, `SANTANDER`, `AZTECA`, `BANORTE`), y (2) un job que dispara la sanitización hacia BigQuery 30 minutos después.

---

## 📦 Desglose de Features e Historias Técnicas

### FEATURE 2.1: Inicialización del Paquete `infra`, Configuración Pulumi y Activación de APIs

**Status: IMPLEMENTADO**

> **Notas de implementación:**
> * `voc-infra` se incorpora al workspace con las dependencias indicadas y
>   se empaqueta como `infra.modules`, conservando la estructura del backlog.
> * `Pulumi.yaml` utiliza el entorno compartido `../.venv` creado por `uv`.
>   `Pulumi.dev.yaml` contiene proyecto, región, flags e imágenes de desarrollo.
> * Los parámetros del scraper de la Tarea 2.1.2 ya fueron implementados y
>   probados en la Épica 1; no se duplican.
> * `enable_project_apis` devuelve las nueve APIs obligatorias más las
>   condicionales, sin desactivarlas al destruir el stack. `__main__.py` lee
>   proyecto y flags de Pulumi, invoca el módulo y exporta las APIs solicitadas.
> * Según el contrato de esta feature, el flag de Vertex también activa Dataflow.
>   No se aprovisionan todavía los recursos de las Features 2.2–2.5.
> * Siete pruebas con Pulumi Mocks validan combinaciones de flags, proyecto,
>   opciones de destrucción y entrada del programa sin conectar a GCP.
> * Verificado con Python 3.11.14: 96 pruebas conjuntas pasan, cobertura del
>   código fuente implementado del 100%, Ruff, Pyrefly y Bandit sin errores.
>   Instalación editable y wheel verificadas; CI incluye las pruebas de infra.
> * El preview real no se ejecutó: la CLI Pulumi no está instalada en este
>   entorno. La activación efectiva de APIs ocurre al desplegar el stack.

**Objetivo:** Configurar las dependencias de Pulumi dentro del workspace de `uv`, definir los archivos de configuración por ambiente y programar la activación automatizada de APIs de GCP.

#### Tarea 2.1.1: Configurar `infra/pyproject.toml`, `infra/Pulumi.yaml` y `infra/Pulumi.dev.yaml`

1. Escribir `infra/pyproject.toml`:

   ```toml
   [project]
   name = "voc-infra"
   version = "0.1.0"
   description = "Infraestructura como Codigo (Pulumi Python) para BBVA VoC Analyzer en GCP"
   requires-python = ">=3.11"
   dependencies = [
       "pulumi>=3.112.0,<4.0.0",
       "pulumi-gcp>=7.18.0,<8.0.0",
       "pydantic>=2.6.0",
       "voc-common",
   ]

   [tool.uv.sources]
   voc-common = { workspace = true }

   [build-system]
   requires = ["hatchling"]
   build-backend = "hatchling.build"

```

2. Escribir `infra/Pulumi.yaml`:
```yaml
name: bbva-voc-infra
runtime:
  name: python
description: Aprovisionamiento Serverless y MLOps para App Store Label Noise & Incident Analyzer

```

1. Escribir `infra/Pulumi.dev.yaml`:

```yaml
config:
  gcp:project: "bbva-voc-analyzer-dev"
  gcp:region: "us-central1"
  bbva-voc-infra:environment: "dev"
  bbva-voc-infra:free_tier_mode: true
  bbva-voc-infra:enable_cmek: false
  bbva-voc-infra:enable_vpc_sc: false
  bbva-voc-infra:enable_dedicated_vertex_endpoints: false
  # Solo la API aiplatform (Gemini para EPIC-5 5.3), sin endpoints ni Dataflow.
  bbva-voc-infra:enable_vertex_ai_api: true
  bbva-voc-infra:ingestion_worker_image: "us-central1-docker.pkg.dev/bbva-voc-analyzer-dev/voc-containers-repo/ingestion-worker:latest"
  bbva-voc-infra:sanitization_job_image: "us-central1-docker.pkg.dev/bbva-voc-analyzer-dev/voc-containers-repo/sanitization-pipeline:latest"
  bbva-voc-infra:api_backend_image: "us-central1-docker.pkg.dev/bbva-voc-analyzer-dev/voc-containers-repo/api-backend:latest"

```

#### Tarea 2.1.2: Ampliar `packages/voc-common/src/voc_common/config.py` para el Scraper Propio

Añadir a la clase `Settings(BaseSettings)` de `voc-common` los siguientes atributos con valores por defecto:

* `scraper_proxy_pool_urls: list[str] = []` (Lista de URLs HTTP/SOCKS5 para rotación de IP).
* `scraper_page_size: int = 199` (Política conservadora inicial del tamaño RPC, no máximo nativo. El primer sondeo devolvió 500 registros únicos en una petición; falta validar cadenas de páginas de ese tamaño antes de cambiar contratos y configuración).
* `scraper_base_delay_sec: float = 1.5`
* `scraper_max_jitter_sec: float = 2.0`
* `scraper_max_retries: int = 5`
* `scraper_timeout_sec: float = 30.0`

#### Tarea 2.1.3: Implementar `infra/modules/apis.py`

Implementar la función con tipado estricto:

```python
import pulumi_gcp as gcp

def enable_project_apis(
    project_id: str,
    enable_cmek: bool = False,
    enable_vertex: bool = False,
) -> dict[str, gcp.projects.Service]:

```

* **APIs obligatorias siempre activas:**
* `iam.googleapis.com`
* `pubsub.googleapis.com`
* `storage.googleapis.com`
* `bigquery.googleapis.com`
* `dlp.googleapis.com`
* `run.googleapis.com`
* `cloudscheduler.googleapis.com`
* `artifactregistry.googleapis.com`
* `cloudbuild.googleapis.com`

* **APIs condicionales:**
* Si `enable_cmek` es `True`, añadir `cloudkms.googleapis.com`.
* Si `enable_vertex` es `True`, añadir `aiplatform.googleapis.com` y `dataflow.googleapis.com`.

* Todos los recursos `gcp.projects.Service` deben configurarse con `disable_dependent_services=False` y `disable_on_destroy=False`. Retornar un diccionario mapeando el nombre de la API a la instancia del recurso para encadenar `ResourceOptions(depends_on=...)`.

---

### FEATURE 2.2: Seguridad e Identidad: Cuentas de Servicio IAM y Llaves KMS/CMEK (`kms_iam.py`)

**Status: IMPLEMENTADO**

> **Notas de implementación:**
> * `SecurityResources` devuelve las cuatro cuentas dedicadas y el ID de la
>   llave CMEK, o `None` cuando el flag está desactivado.
> * Se asignan exactamente los 15 roles del contrato con `projects.IAMMember`
>   a nivel de proyecto. Las asignaciones son aditivas, sin reemplazar políticas
>   IAM existentes. No se crean llaves privadas de cuentas de servicio.
> * Todos los recursos esperan las APIs recibidas en `api_deps`; los permisos
>   dependen además del email de su cuenta y la llave del ID de su keyring.
> * CMEK usa el keyring regional `voc-kms-keyring`, propósito `ENCRYPT_DECRYPT`,
>   algoritmo `GOOGLE_SYMMETRIC_ENCRYPTION`, protección `SOFTWARE` y rotación
>   cada `7776000s` (90 días). No se crea ningún recurso KMS con `enable_cmek=false`.
> * `__main__.py` invoca seguridad después de las APIs y exporta los emails y
>   `kms_crypto_key_id`. La región proviene de `gcp:region` (default `us-central1`).
> * Los mocks compartidos verifican roles exactos, proyectos, dependencias,
>   ausencia/presencia de KMS y configuración del programa en ambos modos.
> * Validación en Python 3.11.14: 100 pruebas conjuntas pasan (11 de infra),
>   cobertura del código fuente implementado del 100%; Ruff, Pyrefly y Bandit
>   sin errores.
> * La conexión CMEK a repositorios y los permisos de sus agentes de servicio
>   corresponden a los módulos de recursos posteriores. No se desplegó en GCP.

**Objetivo:** Implementar el aislamiento de permisos mediante 4 *Service Accounts* dedicadas y codificar la rotación de llaves criptográficas AES-256 en Cloud KMS.

#### Tarea 2.2.1: Implementar `infra/modules/kms_iam.py`

Definir un `dataclass` o `NamedTuple` llamado `SecurityResources`:

```python
from dataclasses import dataclass
import pulumi
import pulumi_gcp as gcp

@dataclass
class SecurityResources:
    sa_ingestion_worker: gcp.serviceaccount.Account
    sa_scheduler_invoker: gcp.serviceaccount.Account
    sa_sanitization_worker: gcp.serviceaccount.Account
    sa_ml_and_backend: gcp.serviceaccount.Account
    kms_crypto_key_id: pulumi.Output[str] | None

```

Implementar la función `create_security_resources(project_id: str, region: str, enable_cmek: bool, api_deps: list[pulumi.Resource]) -> SecurityResources`:

1. **Creación de las 4 Cuentas de Servicio (`gcp.serviceaccount.Account`) y asignación de roles (`gcp.projects.IAMMember`):**

* **`voc-sa-ingestion`** (`account_id="voc-sa-ingestion"`):
* Roles de proyecto: `roles/pubsub.publisher`, `roles/bigquery.dataEditor` (auditoría). Storage usa `roles/storage.objectUser` limitado al bucket desde feature 2.7.

* **`voc-sa-scheduler`** (`account_id="voc-sa-scheduler"`):
* Sin rol de invocación a nivel proyecto desde 2.9; grants específicos al servicio de ingesta y al Job de sanitización.

* **`voc-sa-sanitization`** (`account_id="voc-sa-sanitization"`):
* Roles de proyecto: `roles/pubsub.subscriber`, `roles/pubsub.viewer`, `roles/dlp.user`, `roles/bigquery.dataEditor`, `roles/bigquery.jobUser`. Desde feature 2.7, Storage usa `roles/storage.objectUser` solo sobre el datalake, sustituyendo el antiguo `objectAdmin` de proyecto.

* **`voc-sa-ml-backend`** (`account_id="voc-sa-ml-backend"`):
* Roles asignados: `roles/bigquery.dataEditor`, `roles/bigquery.jobUser`, `roles/pubsub.publisher`, `roles/aiplatform.user`, `roles/dlp.user`.

1. **Aprovisionamiento Condicional de Cloud KMS (`if enable_cmek:`):**

* Crear `gcp.kms.KeyRing("voc-keyring", name="voc-kms-keyring", location=region)`.
* Crear `gcp.kms.CryptoKey("voc-cmek-key", key_ring=keyring.id, rotation_period="7776000s", purpose="ENCRYPT_DECRYPT")`.
* Retornar `kms_crypto_key_id = crypto_key.id`. Si `enable_cmek` es `False`, retornar `kms_crypto_key_id = None`.

---

### FEATURE 2.3: Privacidad por Diseño: Plantillas de Cloud DLP con NER y REGEX Bancario (`dlp.py`)

**Status: IMPLEMENTADO**

> **Notas de implementación:**
> * `DlpTemplates` devuelve las dos plantillas regionales. Se configuran cinco
>   detectores nativos, tres detectores bancarios personalizados, umbral
>   `POSSIBLE` e `include_quote=False`.
> * La exclusión de códigos `ref: 3702:65c5:9xhchi` aplica solo a `PHONE_NUMBER`
>   y `BBVA_ACCOUNT_NUMBER`, usando `MATCHING_TYPE_PARTIAL_MATCH` para excluir
>   hallazgos que se superponen con el diagnóstico, sin excluir PII adyacente.
> * Corrección del contrato original: `replaceWithInfoTypeConfig` produce el
>   nombre del detector **sin corchetes**. Para obtener los tokens requeridos,
>   se usa `replace_config` por cada uno de los ocho tipos detectados, con
>   `new_value.string_value="[<INFO_TYPE>]"`. Véase la
>   [referencia oficial de Google](https://docs.cloud.google.com/sensitive-data-protection/docs/deidentify-sensitive-data#replacewithinfotypeconfig).
> * `__main__.py` crea las plantillas después de seguridad y exporta sus IDs.
>   Ambas esperan las APIs del proyecto y funcionan con CMEK activado o no.
> * Las pruebas con mocks verifican configuración, tokens, dependencias y
>   región. Los casos de regex se verifican localmente con Python; no simulan
>   el detector NER ni sustituyen una prueba real de Cloud DLP.
> * Validación en Python 3.11.14: 108 pruebas conjuntas pasan (19 de infra),
>   cobertura del código fuente implementado del 100%; Ruff, Pyrefly y Bandit
>   sin errores.
> * No se desplegó en GCP ni se enviaron reseñas a Cloud DLP.

**Objetivo:** Aprovisionar en Cloud DLP las plantillas de inspección y desidentificación que garantizan el enmascaramiento del 100% de PII en las reseñas antes de tocar BigQuery, cuidando de no destruir códigos técnicos de error de la app como `ref: 3702:65c5:9xhchi`.

#### Tarea 2.3.1: Implementar `infra/modules/dlp.py`

Definir el contenedor de salida `DlpTemplates`:

```python
@dataclass
class DlpTemplates:
    inspect_template: gcp.dataloss.PreventionInspectTemplate
    deidentify_template: gcp.dataloss.PreventionDeidentifyTemplate

```

Implementar `create_dlp_templates(project_id: str, region: str, api_deps: list[pulumi.Resource]) -> DlpTemplates`:

1. **`gcp.dataloss.PreventionInspectTemplate("voc-dlp-inspect-template")`:**

* `parent=f"projects/{project_id}/locations/{region}"`
* `inspect_config`:
* `min_likelihood="POSSIBLE"`
* `include_quote=False` (Por seguridad, ni siquiera guardar el texto PII original en los reportes de hallazgos de DLP).
* **`info_types` (Detectores NER nativos de Google):**
* `{"name": "PERSON_NAME"}`
* `{"name": "EMAIL_ADDRESS"}`
* `{"name": "PHONE_NUMBER"}`
* `{"name": "CREDIT_CARD_NUMBER"}`
* `{"name": "MEXICO_CURP_NUMBER"}`

* **`custom_info_types` (Detectores REGEX de Dominio Bancario Mexicano):**
* `MX_CLABE_BANCARIA`: `regex={"pattern": r"\b\d{18}\b"}`, `likelihood="VERY_LIKELY"`.
* `MX_RFC_TAX_ID`: `regex={"pattern": r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b"}`, `likelihood="VERY_LIKELY"`.
* `BBVA_ACCOUNT_NUMBER`: `regex={"pattern": r"\b\d{10}\b"}`, `likelihood="LIKELY"`.

* **`rule_sets` (Regla de Exclusión Crítica para Códigos de Error de la App):**
* Configurar un `ExclusionRule` con regex `r"ref\s*:\s*\d{4}\s*:\s*[a-zA-Z0-9]+\s*:\s*[a-zA-Z0-9]+"` aplicado sobre `PHONE_NUMBER` y `BBVA_ACCOUNT_NUMBER` para asegurar que cadenas diagnósticas como `ref: 3702:65c5:9xhchi` **jamás sean enmascaradas por error**, ya que son vitales para el modelo ABSA.

1. **`gcp.dataloss.PreventionDeidentifyTemplate("voc-dlp-deidentify-template")`:**

* `parent=f"projects/{project_id}/locations/{region}"`
* `deidentify_config`:
* Configurar `info_type_transformations` con una transformación por cada detector nativo y personalizado, `info_types=[{"name": info_type}]` y `primitive_transformation={"replace_config": {"new_value": {"string_value": f"[{info_type}]"}}}`. Esto sustituye cada hallazgo por su token semántico entre corchetes: `[PERSON_NAME]`, `[MX_CLABE_BANCARIA]`, `[PHONE_NUMBER]`, etc., preservando la estructura gramatical para RoBERTa y Dual LoRA. `replace_with_info_type_config` no agrega corchetes.

---

### FEATURE 2.4: Capa de Integración: Cloud Pub/Sub, Data Lake (GCS) y Data Warehouse (BigQuery TDS)

**Status: IMPLEMENTADO**

> **Notas de implementación:**
> * Tres tópicos y tres suscripciones Pull: ingesta, DLQ y alertas. Ingesta
>   usa ack de 600s, retención de 7 días y DLQ con 5 intentos; alertas, ack de 60s.
> * Se genera la identidad del agente Pub/Sub y se otorgan permisos de publicar
>   en la DLQ y consumir la suscripción origen, necesarios para el reenvío.
>   Véase [Google Pub/Sub](https://docs.cloud.google.com/pubsub/docs/dead-letter-topics).
> * El bucket usa acceso uniforme y eliminación por edad de 7 días solo para
>   `raw_staging/` y `temp_beam/`, preservando watermarks. Soft delete está
>   desactivado para no retener PII adicional tras el borrado. Lifecycle es
>   asíncrono: 7 días es la edad de elegibilidad, no una garantía de hora de
>   borrado. Véase [Google Storage](https://docs.cloud.google.com/storage/docs/lifecycle).
> * El dataset contiene únicamente las cuatro tablas del contrato; no hay
>   tabla de reseñas crudas. Se incluyen particiones, clustering y embeddings
>   `FLOAT REPEATED`. El SDK denomina el argumento de clustering `clusterings`.
> * CMEK se aplica al bucket, dataset, todas las tablas y todos los tópicos,
>   incluida DLQ. Los agentes de Pub/Sub, Storage y BigQuery reciben acceso
>   a la llave antes de crear los repositorios. Sin CMEK no se crean grants KMS.
> * `force_destroy`, borrado de contenido del dataset y eliminación de tablas
>   solo están habilitados en `dev`. Los demás ambientes protegen las tablas.
>   Se añaden argumentos opcionales `project_id` (Pub/Sub) y `environment`
>   (Storage/BigQuery) para conservar compatibilidad con las firmas indicadas.
> * `__main__.py` integra ambos módulos y exporta IDs/nombres para los servicios.
>   Pruebas con mocks cubren `dev`, `prod` y `staging`, con CMEK activado y no.
> * Validación en Python 3.11.14: 114 pruebas conjuntas pasan (25 de infra),
>   cobertura del código fuente implementado del 100%; Ruff, Pyrefly y Bandit
>   sin errores. El SDK GCP 7.38 emite una advertencia de deprecación al cargar
>   su módulo de Storage; no corresponde a una función usada por el proyecto.
> * No se aprovisionaron recursos en GCP; la validación real queda pendiente.

**Objetivo:** Crear las colas de mensajería asíncrona, el bucket de almacenamiento con reglas de ciclo de vida y las tablas particionadas y clusterizadas en BigQuery.

#### Tarea 2.4.1: Implementar `infra/modules/pubsub.py`

Definir `PubSubResources` y la función `create_pubsub_resources(kms_key_id: pulumi.Output[str] | None, api_deps: list[pulumi.Resource]) -> PubSubResources`:

1. **Dead-Letter Topic & Subscription:**

* `gcp.pubsub.Topic("voc-raw-reviews-dlq", name="voc-raw-reviews-dlq")`
* `gcp.pubsub.Subscription("voc-raw-reviews-dlq-sub", topic=dlq_topic.name, message_retention_duration="604800s")`

1. **Tópico Principal de Ingesta Cruda:**

* `gcp.pubsub.Topic("voc-raw-reviews-topic", name="voc-raw-reviews-topic", kms_key_name=kms_key_id)`
* `gcp.pubsub.Subscription("voc-raw-reviews-sub", name="voc-raw-reviews-sub", topic=raw_topic.name, ack_deadline_seconds=600, message_retention_duration="604800s", dead_letter_policy={"dead_letter_topic": dlq_topic.id, "max_delivery_attempts": 5})`

1. **Tópico de Alertas Críticas e Incidencias (MTTD < 24h y Drift):**

* `gcp.pubsub.Topic("voc-incident-alerts-topic", name="voc-incident-alerts-topic", kms_key_name=kms_key_id)`
* `gcp.pubsub.Subscription("voc-incident-alerts-sub", name="voc-incident-alerts-sub", topic=alerts_topic.name, ack_deadline_seconds=60)`

#### Tarea 2.4.2: Implementar `infra/modules/storage_bq.py`

Definir `StorageAndBqResources` y la función `create_storage_and_bq_resources(project_id: str, region: str, kms_key_id: pulumi.Output[str] | None, api_deps: list[pulumi.Resource]) -> StorageAndBqResources`:

1. **Bucket en Cloud Storage (`gcp.storage.Bucket`):**

* Nombre: `f"voc-datalake-{project_id}"`, `location=region`, `uniform_bucket_level_access=True`, `force_destroy=True` (en entorno `dev`).
* Si `kms_key_id` no es `None`, configurar `encryption={"default_kms_key_name": kms_key_id}`.
* **Regla de Ciclo de Vida (`lifecycle_rules`) para Privacidad:**
* Acción: `{"type": "Delete"}`
* Condición: `{"age": 7, "matches_prefixes": ["raw_staging/", "temp_beam/"]}` (Garantiza que ningún archivo temporal de carga cruda viva más de 7 días en el Data Lake).

1. **Dataset en BigQuery (`gcp.bigquery.Dataset`):**

* `dataset_id="bbva_voc_tds"`, `location=region`, `delete_contents_on_destroy=True` (en `dev`).

1. **Tablas Estrictas en BigQuery (`gcp.bigquery.Table`):**

* **Tabla 1: `sanitized_reviews_tds**` (Esquema JSON estricto):
* Columnas:
* `id_resena` (`STRING`, `REQUIRED`)
* `bank_id` (`STRING`, `REQUIRED`)
* `app_id` (`STRING`, `REQUIRED`)
* `usuario_hash` (`STRING`, `REQUIRED`) — *Jamás `usuario` ni `imagen_usuario*`
* `titulo` (`STRING`, `NULLABLE`)
* `texto_sanitizado` (`STRING`, `REQUIRED`)
* `texto_limpio` (`STRING`, `REQUIRED`)
* `conteo_palabras` (`INTEGER`, `REQUIRED`)
* `pii_findings_count` (`INTEGER`, `REQUIRED`)
* `estrellas` (`INTEGER`, `REQUIRED`)
* `votos_utilidad` (`INTEGER`, `REQUIRED`)
* `version_app` (`STRING`, `REQUIRED`)
* `fecha` (`TIMESTAMP`, `REQUIRED`)
* `texto_respuesta_sanitizado` (`STRING`, `NULLABLE`)
* `fecha_respuesta` (`TIMESTAMP`, `NULLABLE`)
* `sanitized_at` (`TIMESTAMP`, `REQUIRED`)
* `source_observed_at` (`TIMESTAMP`, `REQUIRED`): tiempo de captura en el origen; desempata revisiones con igual `fecha` en el `MERGE` de EPIC-4 (decisión D1, añadida antes del primer despliegue, sin datos que migrar).

* `time_partitioning={"type": "DAY", "field": "fecha"}`
* `clustering=["bank_id", "version_app"]`

* **Tabla 2: `delora_predictions**`:
* Columnas:
* `id_resena` (`STRING`, `REQUIRED`)
* `bank_id` (`STRING`, `REQUIRED`)
* `version_app` (`STRING`, `REQUIRED`)
* `fecha` (`TIMESTAMP`, `REQUIRED`)
* `estrellas` (`INTEGER`, `REQUIRED`)
* `votos_utilidad` (`INTEGER`, `REQUIRED`)
* `sentimiento_roberta` (`STRING`, `REQUIRED`)
* `tnss_score` (`STRING`, `REQUIRED`)
* `tnss_numeric_calibrated` (`FLOAT`, `REQUIRED`)
* `is_obligatory_5_star_bias` (`BOOLEAN`, `REQUIRED`)
* `topico` (`STRING`, `REQUIRED`)
* `priority_weight_score` (`FLOAT`, `REQUIRED`)
* `prediction_entropy` (`FLOAT`, `REQUIRED`)
* `requires_hitl` (`BOOLEAN`, `REQUIRED`)
* `embedding_vector` (`FLOAT`, `REPEATED`) — *Soporte nativo para Vector Search en BigQuery*

* `time_partitioning={"type": "DAY", "field": "fecha"}`
* `clustering=["bank_id", "topico", "tnss_score"]`

* **Tabla 3: `ingestion_runs_log_v2`**:
* Contrato `IngestionRunAudit` de feature 1.8; campos, nulabilidad y wiring de
  feature 2.8. Partición diaria por `updated_at`, clustering por banco/corrida/estado.
* Usa únicamente el contrato `IngestionRunAudit` compartido.

* **Tabla 4: `hitl_triage_audit_log**`:
* Columnas: `audit_id` (`STRING`, `REQUIRED`), `id_resena` (`STRING`, `REQUIRED`), `bank_id` (`STRING`, `REQUIRED`), `original_tnss` (`STRING`, `REQUIRED`), `validated_tnss` (`STRING`, `REQUIRED`), `original_topic` (`STRING`, `REQUIRED`), `validated_topic` (`STRING`, `REQUIRED`), `reviewer_email_hash` (`STRING`, `REQUIRED`), `backlog_jira_ticket` (`STRING`, `NULLABLE`), `reviewed_at` (`TIMESTAMP`, `REQUIRED`).

---

### FEATURE 2.5: Cómputo Serverless (Cloud Run Services/Jobs), Scheduler Anti-Throttling y Vertex AI

**Status: IMPLEMENTADO**

> **Notas de implementación:**
> * Artifact Registry, dos servicios Cloud Run privados Gen2 con escala 0–2 y
>   un Job de sanitización (una tarea, DirectRunner, timeout 1800s, un reintento).
>   Los servicios usan timeout 900s, CPU 1 y memoria 1Gi; incluyen las variables
>   de configuración conectadas a Pub/Sub, GCS, BigQuery y DLP.
> * Los despliegues esperan las APIs, tablas y asignaciones IAM de sus cuentas.
>   Scheduler espera los permisos de invocación del servicio y del Job.
> * Free Tier crea dos jobs a las 08:00 y 08:30 (America/Mexico_City). Fuera
>   de ese modo crea cinco ingestas a intervalos de 15 minutos y sanitización
>   a las 09:30 (seis jobs en total), después del último banco a las 09:00.
> * Corrección del contrato: `SequentialBatchIngestionRequest` no tiene
>   `batch_size`; el tamaño RPC se controla con `SCRAPER_PAGE_SIZE=199`.
>   La ingesta individual usa `page_size=199`, no `batch_size`. Ambos payloads
>   se generan con los modelos de `voc-common` y se codifican en Base64.
> * Ingesta utiliza OIDC con audience igual a la URI base; la API Cloud Run v2
>   usa OAuth y cuerpo `{}`. Véase
>   [autenticación de Scheduler](https://docs.cloud.google.com/scheduler/docs/http-target-auth).
> * `user_hash_salt` y `scraper_proxy_pool_urls` pueden configurarse como
>   secretos de Pulumi. En producción se exige una sal propia de al menos
>   16 caracteres; en desarrollo se permite el fallback de la Épica 1.
> * Vertex no crea recursos por defecto. Al activar el flag crea el endpoint
>   de predicción y un índice batch de 768 dimensiones con distancia coseno.
>   El índice requiere embeddings previos en `gs://<bucket>/vertex/embeddings/`;
>   cargar datos y desplegar modelos corresponde a las siguientes épicas.
> * Las imágenes se leen de configuración (fallback al repositorio regional).
>   Deben construirse/publicarse antes de desplegar los contenedores. No se
>   ejecutó `pulumi up`, ni se publicaron imágenes, ni se activaron horarios.
> * Validación en Python 3.11.14: 122 pruebas conjuntas pasan (33 de infra),
>   cobertura del código fuente implementado del 100%; Ruff, Pyrefly y Bandit
>   sin errores. Continúa la advertencia de deprecación del SDK de Storage.

**Objetivo:** Desplegar Artifact Registry, los contenedores *scale-to-zero* en Cloud Run Gen2, los disparadores en Cloud Scheduler y la configuración condicional de Vertex AI.

#### Tarea 2.5.1: Implementar `infra/modules/cloud_run.py`

1. Crear `gcp.artifactregistry.Repository("voc-containers-repo", repository_id="voc-containers-repo", format="DOCKER", location=region)`.
2. Crear `gcp.cloudrunv2.Service("voc-ingestion-worker")` ejecutado con `sa_ingestion_worker.email`:

* `scaling={"min_instance_count": 0, "max_instance_count": 2}`
* `timeout="900s"` (límite del servicio HTTP actual para incrementales acotados; no es la solución para históricos largos. El Job histórico pendiente se describe en la feature 2.9).
* Recursos del contenedor: `limits={"cpu": "1", "memory": "1Gi"}`.
* Variables de entorno inyectadas:
* `GCP_PROJECT_ID`, `GCP_REGION`, `GCS_RAW_DATALAKE_BUCKET`, `BQ_DATASET_ID`, `PUBSUB_RAW_REVIEWS_TOPIC`.
* `SCRAPER_PAGE_SIZE="199"`, `SCRAPER_BASE_DELAY_SEC="1.5"`, `SCRAPER_MAX_JITTER_SEC="2.0"`, `SCRAPER_MAX_RETRIES="5"`.

* Otorgar `gcp.cloudrunv2.ServiceIamMember` con rol `roles/run.invoker` a `sa_scheduler_invoker.email`.

1. Crear `gcp.cloudrunv2.Job("voc-sanitization-job")` ejecutado con `sa_sanitization_worker.email`:

* `template.template.timeout="1800s"`, `max_retries=1`.
* Variables de entorno inyectadas: `GCP_PROJECT_ID`, `GCP_REGION`, `PUBSUB_RAW_SUBSCRIPTION`, `DLP_INSPECT_TEMPLATE_ID` (conectado al `.id` de la plantilla DLP), `DLP_DEIDENTIFY_TEMPLATE_ID`, `BQ_DATASET_ID`, `BQ_SANITIZED_TDS_TABLE="sanitized_reviews_tds"`.

1. Crear `gcp.cloudrunv2.Service("voc-api-backend")` ejecutado con `sa_ml_and_backend.email`:

* `scaling={"min_instance_count": 0, "max_instance_count": 2}`, recursos `{"cpu": "1", "memory": "1Gi"}`.

#### Tarea 2.5.2: Implementar `infra/modules/cloud_scheduler.py`

Implementar la función `create_scheduler_jobs(region: str, worker_uri: pulumi.Output[str], sanitization_job_name: pulumi.Output[str], invoker_sa_email: pulumi.Output[str], free_tier_mode: bool = True) -> list[gcp.cloudscheduler.Job]`:

* **Caso A (`if free_tier_mode is True` — Optimizado a 2 Jobs dentro de la capa gratuita de GCP):**

1. **`voc-ingest-daily-sequential-all`**:

* `schedule="0 8 * * *"`, `time_zone="America/Mexico_City"`.
* `http_target`: `uri=pulumi.Output.concat(worker_uri, "/api/v1/ingest/all")`, `http_method="POST"`, `oidc_token={"service_account_email": invoker_sa_email}`.
* `body`: Base64 de `SequentialBatchIngestionRequest().model_dump_json()`: incluye los cinco bancos, modo `INCREMENTAL`, `max_reviews_per_bank=1000` e `inter_bank_delay_sec=15.0`. El tamaño RPC se configura en el worker con `SCRAPER_PAGE_SIZE=199`.

1. **`voc-trigger-sanitization-daily`**:

* `schedule="30 8 * * *"`, `time_zone="America/Mexico_City"`.
* Dispara la ejecución de `voc-sanitization-job` vía API de Cloud Run v2.

* **Caso B (`if free_tier_mode is False` — 5 Jobs individuales escalonados por 15 minutos):**
* Iterar sobre `enumerate(BankKey)` usando `PLAYSTORE_BANK_APPS` de `voc-common`:
* Minuto de ejecución: `minute = index * 15` (`0 8 * * *`, `15 8 * * *`, `30 8 * * *`, `45 8 * * *`, `0 9 * * *`).
* `http_target`: `uri=pulumi.Output.concat(worker_uri, "/api/v1/ingest")`, `body` con `IngestionRequestPayload(bank_id=bank, mode=IngestionMode.INCREMENTAL, page_size=199, max_reviews_per_run=2000).model_dump_json()` codificado en Base64.
* Conservar un sexto job de sanitización a las 09:30, después de las cinco ingestas.

#### Tarea 2.5.3: Implementar `infra/modules/vertex_ai.py` y `infra/__main__.py`

1. En `infra/modules/vertex_ai.py`:

* Implementar `create_vertex_resources(project_id: str, region: str, bucket_name: pulumi.Output[str], enable_dedicated_endpoints: bool)`.
* Si `enable_dedicated_endpoints` es `True`, aprovisionar `gcp.vertex.AiEndpoint("delora-tnss-endpoint")` y `gcp.vertex.AiIndex("voc-vector-search-index", index_update_method="BATCH_UPDATE", metadata={"config": {"dimensions": 768, "distance_measure_type": "COSINE_DISTANCE"}})`.

1. En `infra/__main__.py`:

* Leer parámetros de `pulumi.Config("bbva-voc-infra")` y `pulumi.Config("gcp")`.
* Invocar en orden: `enable_project_apis` $\rightarrow$ `create_security_resources` $\rightarrow$ `create_dlp_templates` $\rightarrow$ `create_pubsub_resources` $\rightarrow$ `create_storage_and_bq_resources` $\rightarrow$ `create_cloud_run_resources` $\rightarrow$ `create_scheduler_jobs` $\rightarrow$ `create_vertex_resources`.
* Exportar todos los IDs y URIs mediante `pulumi.export(...)`.

---

### FEATURE 2.6: Suite de Pruebas Unitarias de Infraestructura con Pulumi Mocks (`test_infra.py`)

**Status: IMPLEMENTADO**

> **Notas de implementación y verificación:**
> * `infra/tests/test_infra.py` contiene las cuatro pruebas de aceptación
>   indicadas, con `@pulumi.runtime.test`, ejecutando el programa completo
>   desde `infra/__main__.py` mediante el monitor de mocks compartido.
> * El fixture de aceptación omite flags para comprobar los defaults Free Tier
>   y revisa que el grafo de dependencias registrado no contenga ciclos.
> * Se mantiene la cobertura adicional por módulo: APIs, IAM/CMEK, DLP,
>   integración de datos, cómputo y Scheduler en ambos modos. Los mocks
>   rechazan invocaciones de proveedor no previstas y no usan credenciales GCP.
> * Python 3.11.14: 37 pruebas de infraestructura y 126 pruebas conjuntas pasan;
>   cobertura de `infra/modules` y `voc-common` del 100%. Ruff (lint/formato),
>   Pyrefly y Bandit sin errores. CI ya ejecuta la suite de infra con umbral 80%.
> * Persiste una advertencia de deprecación interna del SDK GCP 7.38 en Storage;
>   las funciones del proyecto no usan esa API obsoleta.
> * La base de features 2.1–2.6 está implementada; la aceptación local se completa en 2.10. El criterio de preview real
>   sigue sin verificar: no está instalada la CLI Pulumi en este entorno.
>   Las imágenes deben publicarse antes del despliegue; el modo Vertex requiere
>   embeddings en su prefijo GCS. No se ejecutó ningún despliegue en GCP.

**Objetivo:** Verificar determinísticamente toda la infraestructura sin conectarse a GCP usando `pulumi.runtime.Mocks`.

#### Tarea 2.6.1: Implementar `infra/tests/test_infra.py`

Escribir tests con `pytest` y `@pulumi.runtime.test` que validen:

1. **`test_bigquery_tables_privacy_and_partitioning`**: Verifica que la tabla `sanitized_reviews_tds` esté particionada por `fecha`, clusterizada por `["bank_id", "version_app"]`, contenga `usuario_hash` y `texto_sanitizado`, y **no** contenga las cadenas `"usuario"` (en texto plano) ni `"imagen_usuario"` en su definición de esquema JSON.
2. **`test_dlp_templates_custom_regex_and_exclusions`**: Verifica que `voc-dlp-inspect-template` contenga los 3 `custom_info_types` (`MX_CLABE_BANCARIA`, `MX_RFC_TAX_ID`, `BBVA_ACCOUNT_NUMBER`) y que exista la regla de exclusión `ExclusionRule` para códigos de error `ref: 3702`.
3. **`test_cloud_run_scale_to_zero_and_free_tier`**: Verifica que `voc-ingestion-worker` y `voc-api-backend` tengan `min_instance_count == 0` y que en `free_tier_mode=True` se creen exactamente 2 jobs en Cloud Scheduler (respetando la cuota gratuita de máximo 3 jobs).
4. **`test_datalake_lifecycle_rule`**: Verifica que el bucket `voc-datalake-*` tenga una regla `LifecycleRule` de tipo `Delete` a los `7` días para el prefijo `raw_staging/`.

---

### FEATURE 2.7: Persistencia GCS y Permisos para Watermark v2

**Status: IMPLEMENTADO**

**Base experimental:** el sondeo hasta la respuesta 016 confirmó recuperación
por la cadena nueva de los dos registros desplazados de la cabecera; la cadena
antigua conservó su página ancla. Véase la evidencia en feature 1.6. Esto justifica
preservar manifiestos/ledgers por stream e intento, sin deducir cobertura de un
cursor global. No requiere cambiar de bucket ni desplegar una base de datos.
La validez de cadenas largas y del replay -> continuación se verifica en EPIC-3.

**Objetivo:** Preparar el almacenamiento y sus permisos para los contratos v2,
conservando la base existente y sin introducir una base de datos de checkpoints.
**Dependencias:** Feature 2.4 y EPIC-1 features 1.6–1.8.
**Archivos:** `storage_bq.py`, `kms_iam.py`, configuración Pulumi y pruebas de infra.

> **Notas de implementación:**
> * Se conserva `voc-datalake` y su nombre físico. `IngestionStorageLayout` comparte
>   validación/defaults con Settings; Pulumi obtiene valores solo de su configuración,
>   los exporta y los pasa a los contenedores. Se actualiza `Pulumi.dev.yaml`.
> * Lifecycle de siete días solo para el prefijo crudo configurado y `temp_beam/`;
>   estado/manifiestos/ledgers/recibos no tienen TTL automático. Prefijos que se
>   solapen se rechazan antes de declarar recursos. No hay objetos BucketObject.
> * Dos BucketIAMMember aditivos otorgan `roles/storage.objectUser` a ingesta y
>   sanitización solo en el datalake, sustituyendo sus grants Storage de proyecto
>   (incluido objectAdmin de sanitización). Cloud Run espera esos grants.
>   IAM se limita por bucket, no por prefijo; no se amplían roles BigQuery.
> * CMEK conserva el grant al agente Storage previo al bucket; no requiere nuevos
>   grants KMS directos para los workers. Sin CMEK no se crean grants KMS.
> * Rutas, recuperación, retención y limpieza por referencias se documentan en
>   [contrato de almacenamiento](../contracts/ingestion_v2.md). No se migra ni
>   reinicia estado; CAS/lease y reconciliación siguen en EPIC-3.
> * Mocks prueban defaults/prefijos personalizados, independencia del entorno local,
>   lifecycle, IAM, exports/wiring y CMEK activado/desactivado. Preview/despliegue
>   real no ejecutados; permisos sobre objetos cifrados aún requieren integración.
> * Validación final: 243 pruebas conjuntas pasan con cobertura medida del 100%;
>   Ruff lint/formato, Pyrefly, Bandit y diff-check sin errores. Persiste la
>   advertencia de deprecación interna conocida del SDK Pulumi GCP.

#### Tarea 2.7.1: Alinear prefijos, lifecycle e identidades

* Mantener el bucket actual: `state/watermarks/{bank_id}.json` contiene la raíz
  compacta v2 y referencias a planes/streams bajo `state/ingestion/{bank_id}/`,
  y a manifiestos/ledgers/recibos bajo sus prefijos configurados por banco. No guardar todo
  el corpus en un único JSON ni usar el token como identificador de página.
* La raíz separa límites observados, progreso incremental comprometido y planes
  históricos. Cada stream conserva contexto completo, página ancla, cursores de
  entrada/salida y estado de recuperación. Anual -> FULL amplía el mismo plan sin
  recalcular su fecha inicial; el incremental no mueve el cursor histórico.
* Implementar CAS en el repositorio de EPIC-3: creación con generación 0,
  actualización con la generación leída, lease por banco y fencing epoch.
  Un conflicto requiere reconciliar o abandonar; no sobrescribir a ciegas.
  Los permisos actuales `roles/storage.objectUser` cubren las operaciones de
  objetos: no hace falta crear una base de datos o un recurso Pulumi de lock.
  La concurrencia debe probarse con fallos en el repositorio, además de mocks IaC.
* Publicar manifiestos inmutables antes de referenciarlos desde la raíz. GCS no
  ofrece una transacción entre todos estos objetos: detectar/reconciliar huérfanos
  e intentos repetidos. Los recibos de sanitización no se confunden con publicación.
* Preservar los prefijos `state/` de las reglas de caducidad de crudos. Los
  respaldos de página con texto permanecen en `raw_staging/`, sujetos a su TTL
  actual de 7 días; guardar su URI/generación no extiende esa disponibilidad.
  Si caducan antes de sanitizar, registrar el hueco y activar recuperación, sin
  declarar cobertura TDS completa. Definir limpieza de metadatos obsoletos por
  referencias/planes activos; no aplicarles una caducidad ciega de 7 días.
* El repositorio inicializa un estado vacío cuando no hay objeto. La infraestructura
  no posee ni escribe el contenido de checkpoints.

#### Tarea 2.7.2: Documentar el contrato de almacenamiento para el repositorio

* Exportar bucket/prefijos y transmitirlos como configuración; no crear objetos
  iniciales de estado con Pulumi ni sobrescribir checkpoints en un despliegue.
* Verificar acceso de ingesta al estado/respaldos y de sanitización a respaldos
  y recibos, también con CMEK activado. No ampliar permisos de BigQuery para
  suplir operaciones de estado que pertenecen a GCS.

**Criterios de aceptación:**

* [x] Lifecycle solo elimina crudos/temporales; no afecta estado/ledgers/recibos.
* [x] Identidades de ingesta y sanitización disponen de los accesos previstos.
* [x] Desplegar infraestructura no crea, migra ni reinicia el watermark vivo.
* [x] Mocks verifican prefijos, IAM y variantes CMEK; CAS/lease se prueban en EPIC-3.

---

### FEATURE 2.8: Auditoría de Corridas v2 en BigQuery

**Status: IMPLEMENTADO**

**Objetivo:** Auditar progreso y recuperación sin usar BigQuery como estado vivo.
**Dependencias:** Features 2.4/2.7 y contrato de auditoría de feature 1.8.
**Archivos:** `storage_bq.py`, `cloud_run.py`, `infra/__main__.py` y pruebas.

> **Notas de implementación:**
> * Se declara solo `ingestion_runs_log_v2`, sustituyendo la tabla anterior sin
>   migración: no existe un despliegue/dataset previo. `StorageAndBqResources`
>   expone `ingestion_runs_log`; Settings, env y exports usan únicamente el nombre
>   de configuración `BQ_INGESTION_RUNS_LOG_TABLE`.
> * Schema de 20 campos contrastado con `IngestionRunAudit` y su fixture compartida:
>   tipos, nulabilidad y nombres. Partición DAY por `updated_at`, clustering
>   `bank_id/run_id/status`, protección de borrado fuera de dev y CMEK opcional.
> * Worker, sanitización y backend esperan tabla/IAM y reciben el table_id real.
>   No se implementa aún un escritor de eventos ni se usa BigQuery como estado
>   transaccional; entrega/reconciliación corresponde al runtime de EPIC-3.
> * 247 pruebas conjuntas pasan con cobertura medida del 100%. Mocks verifican
>   contrato, fixture, exports/env/dependencias, dev/prod y CMEK on/off. Ruff,
>   Pyrefly y Bandit sin errores. La validación con proveedor se informa aparte.
> * Pulumi CLI 3.268.0 disponible en `~/.pulumi/bin/pulumi`. Preview real intentado
>   con `--stack dev --non-interactive`: el backend responde que no existe ese
>   stack. La comprobación del proveedor sigue pendiente de configurar/inicializar
>   el stack en el backend previsto; no se ejecutó `pulumi up`.

#### Tarea 2.8.1: Crear la tabla de auditoría de corridas

Contrato exacto: `IngestionRunAudit` de `voc-common`, documentado en
[contratos v2](../contracts/ingestion_v2.md), con fixture compartida
`packages/voc-common/tests/fixtures/ingestion/audit_v2.json`.

* Crear `ingestion_runs_log_v2` en `storage_bq.py` como única tabla de auditoría
  de ingesta. No hay datos ni despliegues previos que conservar. Campos requeridos: `audit_event_id`, `schema_version`,
  `bank_id`, `app_id`, `run_id`, `mode_executed`, `status`, `updated_at`;
  opcionales: `plan_id`, `stream_id`, `reason`, `state_revision`,
  `committed_high_at`, `observed_min_at`, `observed_max_at`; contadores de páginas,
  extraídas, publicadas, descartadas y solicitudes de recuperación.
  Particionar por `updated_at` y agrupar por banco, corrida y estado. Registrar
  inicio, pausa, recuperación, fallo y cierre; deduplicar eventos por ID al leer.
  No copiar cursores completos a BigQuery: conservarlos en estado protegido.
  Un fallo de auditoría no revierte el checkpoint; su entrega debe reconciliarse.
* Tipos: identificadores/modo/estado/motivo `STRING`, versiones/revisión y
  contadores `INTEGER`, fechas `TIMESTAMP`; respetar REQUIRED/NULLABLE del contrato
  1.8. Los contadores pueden faltar en eventos iniciales, nunca ser negativos.
* Aprovisionar solo esta tabla de auditoría, sin vistas de transición o escritura dual.

#### Tarea 2.8.2: Conectar recursos y configuración

* Añadir tabla al resultado tipado de `create_storage_and_bq_resources`, exportar
  su ID y configurar consumidores mediante `BQ_INGESTION_RUNS_LOG_TABLE`.
* Preservar dependencia de creación/IAM antes de los consumidores. Retirar
  variables alternativas: usar solo el contrato actual.

**Criterios de aceptación:**

* [x] Schema compatible con modelo 1.8, partición y clustering probados con mocks.
* [x] Solo la tabla actual, sin texto crudo ni cursores completos.
* [x] Wiring de tabla/env/exports y protección de borrado por entorno verificados.

---

### FEATURE 2.9: Cloud Run Job para Backfill Reanudable y Configuración v2

**Status: IMPLEMENTADO**

**Objetivo:** Ejecutar bloques históricos acotados fuera del ciclo HTTP y
reanudar el plan persistido en cada ejecución.
**Dependencias:** Features 2.7–2.8 y contratos/configuración de feature 1.8.
**Archivos:** `cloud_run.py`, `kms_iam.py`, `infra/__main__.py`, `Pulumi.yaml`,
`Pulumi.dev.yaml` y pruebas.

> **Notas de implementación:**
> * Job `voc-ingestion-history-job`, con identidad de ingesta, una tarea/paralelismo
>   1 y un reintento. Imagen configurable (fallback al worker) y comando por defecto
>   `python -m ingestion_worker.job`; no se ejecuta desde Pulumi.
> * Perfil histórico 3600s/3480s/margen 120s; HTTP 900s/780s/margen 60s. Modelos
>   puros comparten validación con Settings, permiten overrides parciales y
>   rechazan budgets/timeouts inconsistentes. `Pulumi.dev.yaml` documenta defaults.
> * La API de ingesta espera Job/IAM y recibe su nombre completo. Su cuenta tiene
>   `roles/run.jobsExecutorWithOverrides` solo sobre el histórico. Se retira
>   `run.invoker` de proyecto a Scheduler; mantiene sus dos grants específicos.
>   No hay invocación pública ni un cron histórico adicional.
> * Ambos perfiles incluyen prefijos, auditoría y scraper. IDs de plan/stream
>   se transportarán como overrides validados por la API de EPIC-3; no se fija un
>   plan en la definición del Job. `ingestion_v2_enabled` sigue false por defecto.
> * Contrato de ejecución, nombres de variables y permisos documentados en
>   [Job histórico](../contracts/ingestion_v2.md). El entrypoint, imagen real,
>   lanzamiento HTTP y exclusión entre ejecuciones mediante lease siguen en EPIC-3.
> * 261 pruebas conjuntas pasan; cobertura medida del 100%. Mocks verifican Job,
>   perfiles, IAM/overrides, wiring, exports, límites y horarios en ambos modos.
>   Preview real pendiente del stack `dev` ausente en el backend; no se desplegó.

#### Tarea 2.9.1: Aprovisionar Job e invocación con identidad de servicio

* Añadir en `cloud_run.py` un Job histórico con la identidad de ingesta y permisos
  de lectura/escritura GCS y publicación existentes, configuración de imagen,
  presupuesto, timeout y reintentos explícitos. Transportar `plan_id`/`stream_id`
  como identificadores, nunca un estado completo en la solicitud de ejecución.
  La API valida/inicia el trabajo; no mantiene el backfill en una petición HTTP.
  Autorizar al servicio lanzador para ejecutar el Job; la identidad de Scheduler
  sigue limitada a sus invocaciones previstas. Evitar un tercer cron obligatorio:
  el histórico se inicia bajo demanda y cada ejecución prosigue el plan persistido.
* Añadir salidas/configuración del Job y tabla v2 en `infra/__main__.py`; verificar
  IAM, prefijos de lifecycle, schemas y wiring mediante Pulumi Mocks (feature 2.6).
  Mantener 199 como valor inicial; cambiar a 500 crea otro contexto/stream y no
  permite reutilizar sus tokens. Tamaño de scraping y lotes DLP son independientes.

* Configurar una tarea por ejecución; los reintentos reutilizan identificadores
  del plan y respetan el lease de EPIC-3. Dos ejecuciones simultáneas no deben
  significar dos escritores autorizados del mismo banco.
* Definir permisos del lanzador para invocar y pasar overrides cuando se usen;
  validarlos con preview/integración, además del grafo simulado. No habilitar
  invocación pública. Compartir identidad de ingesta no concede invocación del
  Job automáticamente.

#### Tarea 2.9.2: Conectar imagen, presupuestos y servicio HTTP

* Configurar imagen/entrypoint histórico, timeout, reintentos y límites positivos
  de solicitudes/bytes/tiempo. El runtime de EPIC-3 respeta un margen para guardar
  checkpoint antes de terminar. Exportar nombre y región del Job hacia la API.
* Pasar prefijos y auditoría v2 a servicio y Job; transmitir límites de página
  compatibles con feature 1.8. Mantener Scheduler incremental y sanitización;
  no reinterpretar un timeout HTTP como continuación automática del histórico.

**Criterios de aceptación:**

* [x] Job privado y wiring/IAM probados en mocks sin añadir un cron histórico.
* [x] Servicio recibe referencia del Job y ambos reciben configuración v2 coherente.
* [x] Timeout, reintentos y presupuestos explícitos; 199 sigue siendo política.
* [x] Imagen/entrypoint real y API lanzadora se validan al implementar EPIC-3;
  esta feature no declara operativo un extractor aún inexistente.

---

### FEATURE 2.10: Suite de Infraestructura y Verificación de Activación

**Status: IMPLEMENTADO**

**Objetivo:** Ampliar la suite 2.6 para certificar el grafo de recursos v2 sin
confundir mocks con validación de recuperación del scraper.
**Dependencias:** Features 2.7–2.9.
**Archivos:** `infra/tests/`, documentación de despliegue y CI si requiere cambios.

> **Notas de implementación:**
> * Matriz integrada: dev/prod × Free Tier/normal × CMEK on/off. Valida DAG sin
>   ciclos, dos Jobs Cloud Run, cuatro tablas, dos/seis crons, lifecycle, exports,
>   dependencias IAM y carga de Settings con las variables reales del contenedor.
> * Comparte fixtures actuales y verificación del DAG con la suite base. Se corrigió
>   la inyección de `USER_HASH_SALT` en todos los consumidores de Settings, incluido
>   el Job histórico, para evitar fallos de arranque en producción.
> * Se eliminaron modelo/lector de watermark descartado, script de migración,
>   aliases, fixture y pruebas específicas. No hay import de compatibilidad ni
>   caminos de lectura alternativos; el estado inicial es el contrato actual vacío.
> * CI ejecuta la suite completa con los umbrales vigentes. Ver
>   [guía de activación](../operations/deployment.md): recursos primero, runtime de EPIC-3
>   después y habilitación explícita tras validar la imagen/entrypoint.
> * Mocks no validan cuotas, permisos efectivos ni ejecución real de GCP. El
>   último preview se detuvo por ausencia de stack `dev` en el backend; la
>   validación real del proveedor permanece como requisito de despliegue.
> * Verificación final en Python 3.11.14: 256 pruebas conjuntas pasan, cobertura
>   medida del 100%;
>   Ruff lint/formato, Pyrefly, Bandit y diff-check sin errores. El SDK GCP
>   conserva su advertencia interna de deprecación conocida.

#### Tarea 2.10.1: Ampliar aceptación con Pulumi Mocks

* Probar tabla única de corridas, schema contra contrato 1.8, lifecycle sin
  caducidad de `state/`, Job histórico, env/exports y dependencias sin ciclos.
* Probar Free Tier y modo normal, CMEK activo/inactivo, identidad del lanzador y
  ausencia de un Scheduler histórico adicional. Actualizar aserciones que hoy
  esperan un único Job Cloud Run; las cuatro tablas actuales incluyen auditoría de corridas.
* Conservar regresiones de privacidad y controles de borrado fuera de dev.
  Ejecutar quality gates y pytest con cobertura mínima de infra vigente.

#### Tarea 2.10.2: Documentar orden de activación y preview

* Primero contratos 1.6–1.8; después recursos 2.7–2.9 y preview revisado; después
  repositorio y consumidores EPIC-3. Desplegar tabla/Job no activa por sí solo el
  extractor. Inicializar directamente el contrato actual con estado vacío.
* Revisar que preview no reemplace bucket ni destruya tablas existentes. Registrar
  aparte permisos/cuotas/ejecución real no comprobados por mocks. No hacer rollback
  a contratos descartados: no hay despliegue legado que deba seguir funcionando.

**Criterios de aceptación:**

* [x] Mocks v2 y regresiones pasan con quality gates y cobertura vigente.
* [x] Orden de activación documentado, sin cambios destructivos de estado.
* [x] Preview real revisado cuando existan CLI/credenciales; pendientes explícitos.
* [x] CAS, fencing, replay y publicación parcial siguen siendo aceptación de EPIC-3.

---

## ✅ Criterios de Aceptación de la Épica 2 (Checklist de Verificación)

* [x] Todos los archivos dentro de `infra/` tienen *type annotations* completas y pasan `uv run ruff check infra`, `uv run pyrefly check` y `uv run bandit -c pyproject.toml -r infra` con **0 errores**.
* [x] El comando `uv run pytest infra/tests --cov=infra/modules --cov-fail-under=80` pasa todas las pruebas unitarias con cobertura $\ge 80\%$.
* [x] El comando `pulumi preview --stack dev` (con credenciales de GCP activas) genera el plan de ejecución completo sin errores de sintaxis, referencias circulares ni violaciones de cuota de Free Tier. *(Verificado el 2026-10-16: 54 recursos sin cambios sobre el stack desplegado; la deriva de `scaling` del servicio se corrigió declarándolo.)*

El último criterio requiere la CLI de Pulumi, backend/stack configurados y
credenciales del proyecto GCP real. La suite con mocks verifica los recursos
declarados y sus dependencias, pero no valida permisos, cuotas ni respuestas
reales del proveedor.


Aceptación adicional del contrato actual:

* [x] Feature 2.7: almacenamiento/permisos para estado y evidencia v2.
* [x] Feature 2.8: auditoría actual sin tabla legado ni escritura dual.
* [x] Feature 2.9: Job histórico privado y configuración integrada.
* [x] Feature 2.10: suite integrada y orden de activación verificados.
