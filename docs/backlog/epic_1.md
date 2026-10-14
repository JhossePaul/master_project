# EPIC-1: Fundamentos del Monorepo, Contratos de Datos (`voc-common`) y Quality Gates

* **Estado:** Pendiente
* **Semanas Objetivo:** Semana 1
* **Paquetes / Directorios Afectados:**
  * `packages/voc-common/pyproject.toml`
  * `packages/voc-common/src/voc_common/__init__.py`
  * `packages/voc-common/src/voc_common/constants.py`
  * `packages/voc-common/src/voc_common/text_utils.py`
  * `packages/voc-common/src/voc_common/schemas.py`
  * `packages/voc-common/src/voc_common/config.py`
  * `packages/voc-common/tests/__init__.py`
  * `packages/voc-common/tests/test_schemas.py`
  * `.env.example`
  * `.pre-commit-config.yaml`
  * `.github/workflows/ci.yaml`
* **Dependencias Previas:** Ninguna (Épica Fundacional).

---

## 🎯 Contexto y Reglas Arquitectónicas para el Agente IA

Esta épica construye el paquete compartido `voc-common`, la gestión centralizada de configuración (`config.py` / `.env`) y el pipeline de Integración Continua (GitHub Actions). Todos los servicios del monorepo importarán exclusivamente estos contratos.

El Agente IA **DEBE** implementar las siguientes 5 directrices de diseño en `voc-common`:

1. **Soporte Nativo para Scraper Propio (`batchexecute` RPC) sin `google-play-scraper`:**
   * No se debe incluir `google-play-scraper` como dependencia.
   * Los contratos deben modelar el protocolo interno de Google Play (`/_/PlayStoreUi/data/batchexecute`, RPC ID `oCPfdb`), donde el tamaño máximo de lote por petición es de **199 reseñas** y el token de paginación (`page_token`) es un `str` puro en Base64 serializable directamente en JSON.
2. **Tres Modos de Ingesta y Watermark Bidireccional en Cloud Storage:**
   * Soportar los modos `INCREMENTAL` (delta diario), `BACKFILL` (ventana histórica de 1 año / 365 días hacia atrás) y `FULL_BACKFILL` (extracción total hasta agotar páginas, soportando particionamiento por calificación de 1 a 5 estrellas para evadir límites de paginación profunda).
   * El esquema `IngestionWatermarkState` debe rastrear tanto la frontera superior (`max_review_timestamp` y `recent_review_ids`) como la frontera inferior (`min_review_timestamp`, `oldest_review_ids` y `oldest_page_token` por estrella/global), permitiendo guardar checkpoints atómicos en Cloud Storage (`gs://<bucket>/state/watermarks/{bank_id}.json`) tras cada página descargada.
3. **Separación Estricta entre Carga Cruda (Pre-DLP) y Tabla TDS (Post-DLP):**
   * `RawReviewEvent` modela el evento en tránsito hacia `Cloud Pub/Sub` y el staging efímero en `Cloud Storage` (conservando `texto` y `usuario` crudos para que sean inspeccionados por Cloud DLP).
   * `SanitizedReviewRecord` modela el registro post-DLP que persiste en `BigQuery (Trusted Data Source - TDS)`, donde `usuario` fue transformado irreversiblemente en `usuario_hash` (SHA-256 con sal), `imagen_usuario` fue eliminada, el PII textual fue reemplazado por tokens semánticos (`[PERSON_NAME]`, `[MX_CLABE_BANCARIA]`, etc.) preservando códigos técnicos como `ref: 3702`, y el conteo de palabras cumple el umbral del EDA (2 a 60 palabras).
4. **Compatibilidad con GCP Free Tier y Anti-Throttling:**
   * Proveer el contrato `SequentialBatchIngestionRequest` para que un único Job de Cloud Scheduler pueda detonar la extracción secuencial de los 5 bancos con pausas de *jitter* entre instituciones, evitando el bloqueo de IP de Cloud Run.
5. **Quality Gates Activos:**
   * La restricción de `gitleaks` se encuentra temporalmente deshabilitada. Todo el código debe pasar estrictamente: **`ruff`**, **`pyrefly`**, **`bandit`** y **`pytest` ($\ge 80\%$ de cobertura)**.

---

## 📦 Desglose de Features e Historias Técnicas

### FEATURE 1.1: Configuración del Paquete `voc-common` y Catálogo de Constantes (`constants.py`)

**Objetivo:** Configurar el paquete dentro del workspace de `uv` y declarar todas las enumeraciones, constantes del protocolo RPC de Google Play y parámetros del EDA.

#### Tarea 1.1.1: Configurar `packages/voc-common/pyproject.toml`

Escribir exactamente el siguiente contenido en `packages/voc-common/pyproject.toml`:

```toml
[project]
name = "voc-common"
version = "0.1.0"
description = "Contratos Pydantic, constantes RPC y configuracion centralizada para BBVA VoC Analyzer"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.6.0,<3.0.0",
    "pydantic-settings>=2.2.0,<3.0.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

```

#### Tarea 1.1.2: Implementar `packages/voc-common/src/voc_common/constants.py`

Implementar el módulo con tipado estricto e incluir las siguientes definiciones:

```python
from enum import Enum

class BankKey(str, Enum):
    BBVA = "BBVA"
    NUBANK = "NUBANK"
    SANTANDER = "SANTANDER"
    AZTECA = "AZTECA"
    BANORTE = "BANORTE"

PLAYSTORE_BANK_APPS: dict[BankKey, str] = {
    BankKey.BBVA: "com.bancomer.mbanking",
    BankKey.NUBANK: "com.nu.production",
    BankKey.SANTANDER: "mx.bancosantander.supermovil",
    BankKey.AZTECA: "baz.app.bancoazteca",
    BankKey.BANORTE: "com.banorte.movil",
}

class IngestionMode(str, Enum):
    INCREMENTAL = "INCREMENTAL"       # Extrae novedades hasta tocar max_review_timestamp
    BACKFILL = "BACKFILL"             # Extrae hacia el pasado hasta (hoy - 365 dias)
    FULL_BACKFILL = "FULL_BACKFILL"   # Extrae hacia el pasado hasta agotar tokens en Play Store

class PlayStoreSortOrder(int, Enum):
    MOST_RELEVANT = 1
    NEWEST = 2
    RATING = 3

class SentimentLabel(str, Enum):
    NEG = "NEG"
    NEU = "NEU"
    POS = "POS"

SENTIMENT_DISPLAY_MAP: dict[SentimentLabel, str] = {
    SentimentLabel.NEG: "Negativo",
    SentimentLabel.NEU: "Neutral",
    SentimentLabel.POS: "Positivo",
}

class ABSATopic(str, Enum):
    BIOMETRIA_RECONOCIMIENTO = "BIOMETRIA_RECONOCIMIENTO"
    BLOQUEO_SEGURIDAD_3702 = "BLOQUEO_SEGURIDAD_3702"
    TRANSFERENCIAS_SPEI = "TRANSFERENCIAS_SPEI"
    RENDIMIENTO_CRASH_POST_RELEASE = "RENDIMIENTO_CRASH_POST_RELEASE"
    SALDOS_Y_APARTADOS = "SALDOS_Y_APARTADOS"
    TOKEN_Y_NOTIFICACIONES = "TOKEN_Y_NOTIFICACIONES"
    UX_INTERFAZ_Y_PUBLICIDAD = "UX_INTERFAZ_Y_PUBLICIDAD"
    OTROS_SERVICIOS_GENERALES = "OTROS_SERVICIOS_GENERALES"

# Constantes del EDA (Filtrado de Colas Pesadas)
MIN_REVIEW_WORDS: int = 2
MAX_REVIEW_WORDS: int = 60
BACKFILL_LOOKBACK_DAYS: int = 365

# Constantes del Protocolo Interno Google Play (batchexecute RPC)
PLAYSTORE_BATCHEXECUTE_URL: str = "[https://play.google.com/_/PlayStoreUi/data/batchexecute](https://play.google.com/_/PlayStoreUi/data/batchexecute)"
PLAYSTORE_REVIEWS_RPC_ID: str = "oCPfdb"
PLAYSTORE_MAX_PAGE_SIZE: int = 199
DEFAULT_PLAYSTORE_LANG: str = "es"
DEFAULT_PLAYSTORE_COUNTRY: str = "mx"

# Pool de User-Agents modernos para rotación Anti-Throttling
DEFAULT_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.6; rv:129.0) Gecko/20100101 Firefox/129.0",
)

```

---

### FEATURE 1.2: Utilidades de Limpieza de Texto y Hash Criptográfico (`text_utils.py`)

**Objetivo:** Aislar en funciones puras, deterministas y fácilmente testeables la lógica de pre-limpieza probada en el notebook del EDA y la anonimización SHA-256 de usuarios.

#### Tarea 1.2.1: Implementar `packages/voc-common/src/voc_common/text_utils.py`

Implementar las siguientes 4 funciones con expresiones regulares pre-compiladas:

```python
import hashlib
import re

_URL_REGEX = re.compile(r"http\S+|www\S+|https\S+", flags=re.MULTILINE)
_MENTION_HASHTAG_REGEX = re.compile(r"\@\w+|\#")
_REPEATED_CHARS_REGEX = re.compile(r"(.)\1{2,}")

def limpiar_texto_bancario(texto: str) -> str:
    """
    Pipeline de limpieza ajustado a textos ultracortos bancarios (EDA):
    1. Convierte a minúsculas.
    2. Elimina URLs (http, https, www), preservando signos de puntuación, códigos ref: 3702 y emojis.
    3. Elimina menciones (@usuario) y símbolos #.
    4. Reduce caracteres repetidos excesivos (3 o más idénticos a 2, ej. 'noooo sirveee' -> 'noo sirvee').
    5. Elimina espacios en blanco iniciales/finales.
    """
    cleaned = str(texto).lower()
    cleaned = _URL_REGEX.sub("", cleaned)
    cleaned = _MENTION_HASHTAG_REGEX.sub("", cleaned)
    cleaned = _REPEATED_CHARS_REGEX.sub(r"\1\1", cleaned)
    return cleaned.strip()

def contar_palabras(texto: str) -> int:
    """Calcula la cantidad de palabras separadas por espacios."""
    stripped = str(texto).strip()
    if not stripped:
        return 0
    return len(stripped.split())

def hash_username_pii(username: str, salt: str) -> str:
    """Genera un digest SHA-256 irreversible a partir del userName y la sal criptográfica."""
    normalized = f"{salt}:{username.strip().lower()}".encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()

```

---

### FEATURE 1.3: Contratos de Datos Estrictos en Pydantic v2 (`schemas.py`)

**Objetivo:** Definir todos los modelos de transferencia de datos entre capas en `packages/voc-common/src/voc_common/schemas.py`.

#### Tarea 1.3.1: Esquemas de Solicitud de Ingesta y Cursor RPC

1. **`PlayStoreRpcCursor(BaseModel)`**:

* `app_id: str`
* `lang: str = DEFAULT_PLAYSTORE_LANG`
* `country: str = DEFAULT_PLAYSTORE_COUNTRY`
* `sort_order: PlayStoreSortOrder = PlayStoreSortOrder.NEWEST`
* `star_filter: int | None = Field(default=None, ge=1, le=5)` (`None` consulta todas las estrellas; `1..5` permite particionar consultas en `FULL_BACKFILL` para superar el límite de paginación de Google Play).
* `page_token: str | None = None` (Cursor en Base64 devuelto por `batchexecute`).

1. **`IngestionRequestPayload(BaseModel)`**:

* `bank_id: BankKey`
* `mode: IngestionMode = IngestionMode.INCREMENTAL`
* `page_size: int = Field(default=PLAYSTORE_MAX_PAGE_SIZE, ge=1, le=PLAYSTORE_MAX_PAGE_SIZE)`
* `max_reviews_per_run: int = Field(default=5000, ge=1, le=250000)`
* `partition_by_stars: bool = False` (Si es `True` en `FULL_BACKFILL`, extrae por separado 1, 2, 3, 4 y 5 estrellas).

1. **`SequentialBatchIngestionRequest(BaseModel)`**:

* Contrato para el Job Maestro en modo Free Tier (`/api/v1/ingest/all`):
* `banks: list[BankKey] = Field(default_factory=lambda: list(BankKey))`
* `mode: IngestionMode = IngestionMode.INCREMENTAL`
* `max_reviews_per_bank: int = Field(default=1000, ge=1, le=50000)`
* `inter_bank_delay_sec: float = Field(default=15.0, ge=1.0, le=120.0)`

#### Tarea 1.3.2: Esquema de Watermark Bidireccional (`IngestionWatermarkState`)

Modela el archivo `gs://<bucket>/state/watermarks/{bank_id}.json` y la tabla de auditoría en BigQuery:

* `bank_id: BankKey`
* `app_id: str`
* `max_review_timestamp: datetime | None = None` (Fecha UTC de la reseña más nueva ya extraída).
* `min_review_timestamp: datetime | None = None` (Fecha UTC de la reseña más antigua ya extraída).
* `recent_review_ids: set[str] = Field(default_factory=set)` (IDs en la frontera `max_review_timestamp`, acotado a los últimos 500 IDs para búsqueda $O(1)$).
* `oldest_review_ids: set[str] = Field(default_factory=set)` (IDs en la frontera `min_review_timestamp`).
* `oldest_page_token: str | None = None` (Último `page_token` Base64 válido en la frontera inferior global para reanudar `BACKFILL` / `FULL_BACKFILL` tras una rotación de IP o corte de ejecución).
* `star_partition_tokens: dict[int, str | None] = Field(default_factory=dict)` (Tokens de continuación por calificación `1..5` cuando se usa particionamiento en `FULL_BACKFILL`).
* `backfill_one_year_completed: bool = False`
* `full_backfill_completed: bool = False`
* `total_extracted_count: int = Field(default=0, ge=0)`
* `updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))`
* **Métodos de negocio obligatorios en `IngestionWatermarkState`:**

1. `should_stop_incremental(self, review_id: str, review_date: datetime) -> bool`:

* Asegura que `review_date` tenga zona horaria UTC.
* Retorna `True` si `review_id in self.recent_review_ids` o si `self.max_review_timestamp is not None and review_date < self.max_review_timestamp`.

1. `has_reached_one_year_backfill(self, review_date: datetime, reference_now: datetime | None = None) -> bool`:

* Calcula `cutoff = (reference_now or datetime.now(timezone.utc)) - timedelta(days=BACKFILL_LOOKBACK_DAYS)`.
* Retorna `True` si `review_date <= cutoff`.

1. `update_bounds(self, review_id: str, review_date: datetime, next_page_token: str | None = None) -> None`:

* Actualiza dinámicamente `max_review_timestamp`, `min_review_timestamp`, `recent_review_ids`, `oldest_review_ids`, `oldest_page_token` e incrementa `total_extracted_count`.

#### Tarea 1.3.3: Esquema de Carga Cruda (`RawReviewEvent`) — Pre-DLP

Modela la reseña extraída por el scraper propio o desde diccionarios crudos del notebook antes de pasar por Cloud DLP:

* `id_resena: str = Field(..., min_length=1)`
* `bank_id: BankKey`
* `app_id: str`
* `usuario: str = Field(..., min_length=1)` (Conservado temporalmente en la carga cruda hacia Pub/Sub para ser hasheado y descartado en el pipeline de sanitización).
* `imagen_usuario: str | None = None`
* `titulo: str | None = None`
* `texto: str = Field(..., min_length=1)`
* `estrellas: int = Field(..., ge=1, le=5)`
* `fecha: datetime` (Con validador `@field_validator("fecha")` que fuerce `timezone.utc`).
* `version_app: str = Field(default="UNKNOWN")` (Si llega `None` o cadena vacía desde Play Store, normalizar a `"UNKNOWN"`).
* `votos_utilidad: int = Field(default=0, ge=0)`
* `texto_respuesta: str | None = None`
* `fecha_respuesta: datetime | None = None`
* `ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))`
* **Métodos de fábrica obligatorios:**

1. `@classmethod def from_playstore_dict(cls, raw_dict: dict[str, Any], bank_id: BankKey, app_id: str) -> "RawReviewEvent"`: Traduce las llaves del formato `google-play-scraper` (`reviewId`, `userName`, `content`, `score`, `at`, `reviewCreatedVersion`, `userImage`, `thumbsUpCount`, `replyContent`, `repliedAt`), ignora `appVersion` y asigna `titulo=None`.
2. `@classmethod def from_batchexecute_entry(cls, raw_entry: list[Any], bank_id: BankKey, app_id: str) -> "RawReviewEvent"`: Parsea una fila cruda de la matriz JSON del RPC `oCPfdb` de Google Play Store.

#### Tarea 1.3.4: Esquema Curado y Sanitizado (`SanitizedReviewRecord`) — Post-DLP (BigQuery TDS)

Modela el registro limpio en la tabla `sanitized_reviews_tds`:

* `id_resena: str`
* `bank_id: BankKey`
* `app_id: str`
* `usuario_hash: str = Field(..., min_length=64, max_length=64)` (Hash SHA-256 hexadecimal).
* `titulo: str | None = None`
* `texto_sanitizado: str = Field(..., min_length=1)`
* `texto_limpio: str = Field(..., min_length=1)`
* `conteo_palabras: int = Field(..., ge=MIN_REVIEW_WORDS, le=MAX_REVIEW_WORDS)` (Restricción estricta de 2 a 60 palabras del EDA).
* `pii_findings_count: int = Field(default=0, ge=0)`
* `estrellas: int = Field(..., ge=1, le=5)`
* `votos_utilidad: int = Field(default=0, ge=0)`
* `version_app: str = Field(default="UNKNOWN")`
* `fecha: datetime`
* `texto_respuesta_sanitizado: str | None = None`
* `fecha_respuesta: datetime | None = None`
* `sanitized_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))`
* **Método de construcción obligatorio:**
* `@classmethod def from_raw_and_dlp(cls, raw: RawReviewEvent, texto_sanitizado: str, pii_findings_count: int, user_hash_salt: str, texto_respuesta_sanitizado: str | None = None) -> "SanitizedReviewRecord"`: Calcula `usuario_hash` usando `hash_username_pii(raw.usuario, user_hash_salt)`, aplica `limpiar_texto_bancario(texto_sanitizado)`, calcula `conteo_palabras` y valida el rango `[2, 60]`.

#### Tarea 1.3.5: Esquemas de Predicción (`AnalyzedReviewPrediction`), Alertas (`IncidentAlertMessage`) y Auditoría HITL (`HitlTriageAuditRecord`)

1. **`AnalyzedReviewPrediction(BaseModel)`**:

* `id_resena: str`
* `bank_id: BankKey`
* `version_app: str`
* `fecha: datetime`
* `estrellas: int = Field(..., ge=1, le=5)`
* `votos_utilidad: int = Field(default=0, ge=0)`
* `sentimiento_roberta: SentimentLabel`
* `tnss_score: SentimentLabel`
* `tnss_numeric_calibrated: float = Field(..., ge=1.0, le=5.0)`
* `is_obligatory_5_star_bias: bool` (Con `@model_validator(mode="after")` o cálculo automático: `True` si `estrellas >= 4 and tnss_score == SentimentLabel.NEG`).
* `topico: ABSATopic`
* `priority_weight_score: float = Field(..., ge=0.0)`
* `prediction_entropy: float = Field(..., ge=0.0, le=1.0)`
* `requires_hitl: bool`
* `embedding_vector: list[float] = Field(default_factory=list)`

1. **`IncidentAlertMessage(BaseModel)`**:

* `alert_id: str`
* `bank_id: BankKey`
* `version_app: str`
* `topico: ABSATopic`
* `negative_reviews_spike_count: int = Field(..., ge=1)`
* `accumulated_utility_votes: int = Field(..., ge=0)`
* `sample_review_ids: list[str]`
* `triggered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))`

1. **`HitlTriageAuditRecord(BaseModel)`**:

* Espejo exacto de la tabla `hitl_triage_audit_log` de la Épica 2:
* `audit_id: str`
* `id_resena: str`
* `bank_id: BankKey`
* `original_tnss: SentimentLabel`
* `validated_tnss: SentimentLabel`
* `original_topic: ABSATopic`
* `validated_topic: ABSATopic`
* `reviewer_email_hash: str`
* `backlog_jira_ticket: str | None = None`
* `reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))`

---

### FEATURE 1.4: Configuración Centralizada con Soporte Free Tier y Anti-Throttling (`config.py`)

**Objetivo:** Implementar `packages/voc-common/src/voc_common/config.py` sincronizado al 100% con las variables de entorno inyectadas por Pulumi en la Épica 2.

#### Tarea 1.4.1: Implementar `Settings(BaseSettings)` en `config.py`

```python
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Entorno y Proyecto GCP
    environment: str = "dev"
    free_tier_mode: bool = True
    gcp_project_id: str = "bbva-voc-analyzer-dev"
    gcp_region: str = "us-central1"

    # Almacenamiento (Cloud Storage Data Lake & Watermarks)
    gcs_raw_datalake_bucket: str = "voc-datalake-bbva-voc-analyzer-dev"
    gcs_watermark_prefix: str = "state/watermarks"
    gcs_raw_staging_prefix: str = "raw_staging"

    # BigQuery (Trusted Data Source - TDS)
    bq_dataset_id: str = "bbva_voc_tds"
    bq_sanitized_tds_table: str = "sanitized_reviews_tds"
    bq_predictions_table: str = "delora_predictions"
    bq_watermarks_log_table: str = "ingestion_watermarks_log"
    bq_hitl_audit_table: str = "hitl_triage_audit_log"

    # Cloud Pub/Sub
    pubsub_raw_reviews_topic: str = "voc-raw-reviews-topic"
    pubsub_raw_subscription: str = "voc-raw-reviews-sub"
    pubsub_alerts_topic: str = "voc-incident-alerts-topic"

    # Cloud DLP (Ethics by Design)
    dlp_inspect_template_id: str | None = None
    dlp_deidentify_template_id: str | None = None
    user_hash_salt: str = Field(default="dev-only-salt-override-in-prod", min_length=16)

    # Scraper Propio (batchexecute) y Anti-Throttling
    scraper_proxy_pool_urls: list[str] = Field(default_factory=list)
    scraper_rotate_proxy_every_n_batches: int = 5
    scraper_page_size: int = 199
    scraper_base_delay_sec: float = 1.5
    scraper_max_jitter_sec: float = 2.0
    scraper_max_retries: int = 5
    scraper_timeout_sec: float = 30.0

    # Parámetros MLOps y HITL
    hitl_entropy_threshold: float = 0.65
    enable_dedicated_vertex_endpoints: bool = False

@lru_cache
def get_settings() -> Settings:
    return Settings()

```

#### Tarea 1.4.2: Exportar API pública en `packages/voc-common/src/voc_common/__init__.py`

Re-exportar explícitamente todas las clases de `constants.py`, `text_utils.py`, `schemas.py` y `config.py` mediante `__all__` en `__init__.py`.

#### Tarea 1.4.3: Crear plantilla `.env.example`

Generar en la raíz del repositorio el archivo `.env.example` con comentarios explicativos para cada bloque de `Settings`.

---

### FEATURE 1.5: Pipeline CI en GitHub Actions y Suite de Pruebas Unitarias (`test_schemas.py`)

**Objetivo:** Configurar la validación automatizada en GitHub Actions y asegurar cobertura $\ge 85\%$ en `voc-common`.

#### Tarea 1.5.1: Implementar `.pre-commit-config.yaml` y `.github/workflows/ci.yaml`

1. En `.pre-commit-config.yaml`: Configurar hooks para `ruff` (`ruff` y `ruff-format`) y `bandit` (sin `gitleaks`).
2. En `.github/workflows/ci.yaml`:

* Configurar trigger en `push` y `pull_request`.
* Instalar `uv` (`astral-sh/setup-uv@v3`) y Python 3.11.
* Mapear variables de entorno desde `secrets` (`GCP_PROJECT_ID`, `USER_HASH_SALT`, `SCRAPER_PROXY_POOL_URLS`) con valores fallback seguros si corren en entorno de pruebas.
* Ejecutar:
* `uv sync --all-packages`
* `uv run ruff check .`
* `uv run ruff format --check .`
* `uv run pyrefly check`
* `uv run bandit -c pyproject.toml -r .`
* `uv run pytest packages/voc-common/tests --cov=packages/voc-common/src --cov-fail-under=85`

#### Tarea 1.5.2: Implementar `packages/voc-common/tests/test_schemas.py`

Escribir mínimo 10 pruebas unitarias que validen:

1. **`test_limpiar_texto_bancario_preserves_error_codes_and_emojis`**: Comprobar que el texto real del notebook `"no me deja entrar me sale que restringieron mi cuenta por motivos de seguridad: ref: 3702:65c5:9xhchi. noooo sirveee 😡 http://spam.com @bbva #asco"` se convierta en `"no me deja entrar me sale que restringieron mi cuenta por motivos de seguridad: ref: 3702:65c5:9xhchi. noo sirvee 😡"`.
2. **`test_raw_review_from_playstore_dict`**: Verificar mapeo exacto de columnas del notebook, eliminación de `appVersion` e inyección de `titulo=None`.
3. **`test_sanitized_review_record_word_count_bounds`**: Comprobar que una reseña de 1 palabra (`"excelente"`) o de 61 palabras dispare `ValidationError`, mientras que una de 2 a 60 palabras se construya correctamente y genere un `usuario_hash` SHA-256 de 64 caracteres hexadecimales.
4. **`test_watermark_bidirectional_incremental_and_backfill`**:

* Verificar que `should_stop_incremental` retorne `True` por ID duplicado en la frontera o por `review_date < max_review_timestamp`.
* Verificar que `has_reached_one_year_backfill` detecte con exactitud el corte de 365 días.
* Verificar que `update_bounds` actualice `max_review_timestamp`, `min_review_timestamp` y `oldest_page_token` (string Base64).

1. **`test_obligatory_5_star_label_noise_detection`**: Comprobar que `AnalyzedReviewPrediction` marque `is_obligatory_5_star_bias=True` cuando `estrellas=5` y `tnss_score=SentimentLabel.NEG`.

---

## ✅ Criterios de Aceptación de la Épica 1 (Checklist de Verificación)

* [ ] `voc-common` no depende de `google-play-scraper` y modela los tokens de paginación como `str` Base64 compatibles con el RPC `oCPfdb` de `batchexecute`.
* [ ] Existen los 3 modos en `IngestionMode` (`INCREMENTAL`, `BACKFILL`, `FULL_BACKFILL`) y `IngestionWatermarkState` gestiona fechas máxima/mínima y tokens por partición de estrellas.
* [ ] `SanitizedReviewRecord` garantiza 0% de almacenamiento de `usuario` o `imagen_usuario` en texto plano y preserva códigos de error `ref: 3702`.
* [ ] Los 4 Quality Gates (`ruff`, `pyrefly`, `bandit`, `pytest`) pasan sin errores con cobertura $\ge 85\%$.
