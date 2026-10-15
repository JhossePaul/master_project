# EPIC-1: Fundamentos del Monorepo, Contratos de Datos (`voc-common`) y Quality Gates

* **Estado:** IMPLEMENTADO — Features 1.1–1.8 completadas y verificadas localmente. Contratos, eventos, reducer, configuración v2 disponibles; activación de recursos/consumidores corresponde a EPIC-2/EPIC-3/EPIC-4.
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
  * `packages/voc-common/src/voc_common/ingestion_state.py`
  * `packages/voc-common/tests/test_ingestion_contracts.py`
  * `packages/voc-common/tests/test_ingestion_state.py`
  * `packages/voc-common/tests/test_versioned_events.py`
  * `packages/voc-common/tests/fixtures/ingestion/`
  * `docs/contracts/ingestion_v2.md`
  * `.env.example`
  * `.pre-commit-config.yaml`
  * `.github/workflows/ci.yaml`
* **Dependencias Previas:** Ninguna (Épica Fundacional).

---

## Ampliación implementada para watermark v2

Las features 1.1–1.8 implementan los contratos compartidos actuales.
La feature **1.7** implementa reducer por página; **1.8** entrega eventos,
configuración y fixtures. La persistencia CAS se implementará en EPIC-3.
Los detalles de ejecución y recuperación se mantienen en EPIC-3.

---

## 🎯 Contexto y Reglas Arquitectónicas para el Agente IA

Esta épica construye el paquete compartido `voc-common`, la gestión centralizada de configuración (`config.py` / `.env`) y el pipeline de Integración Continua (GitHub Actions). Todos los servicios del monorepo importarán exclusivamente estos contratos.

El Agente IA **DEBE** implementar las siguientes 5 directrices de diseño en `voc-common`:

1. **Soporte Nativo para Scraper Propio (`batchexecute` RPC) sin `google-play-scraper`:**
   * No se debe incluir `google-play-scraper` como dependencia.
   * Los contratos deben modelar el protocolo interno de Google Play (`/_/PlayStoreUi/data/batchexecute`, RPC ID `oCPfdb`), con tamaño inicial de página **199 como política conservadora**, no máximo del origen: el sondeo devolvió 500 registros únicos en una petición. El token (`page_token`) es un `str` opaco serializable en JSON; no se decodifica ni se presupone formato Base64, TTL o estabilidad.
2. **Tres Modos de Ingesta y Watermark Bidireccional en Cloud Storage:**
   * Soportar los modos `INCREMENTAL` (delta diario), `BACKFILL` (ventana histórica de 1 año / 365 días hacia atrás) y `FULL_BACKFILL` (recorrido hasta agotamiento observado del origen; particionamiento por calificación de 1 a 5 estrellas como estrategia experimental, sin promesa de recuperar todo el histórico).
   * El esquema v2 separa observaciones, progreso incremental comprometido, planes históricos y streams contextualizados. El estado raíz reside en `gs://<bucket>/state/watermarks/{bank_id}.json`; el repositorio de EPIC-3 aplica CAS y lease. Una página descargada aún no autoriza el avance: requiere respaldo y confirmación de todas sus publicaciones.
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

**Status: IMPLEMENTADO**

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
    BankKey.AZTECA: "mx.com.bancoazteca.bazdigitalmovil",   # corregido 2026-10-15
    BankKey.BANORTE: "org.microemu.android.model.common.VTUserApplicationBNRTMB",   # corregido 2026-10-15
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
PLAYSTORE_BATCHEXECUTE_URL: str = "https://play.google.com/_/PlayStoreUi/data/batchexecute"
PLAYSTORE_REVIEWS_RPC_ID: str = "oCPfdb"
PLAYSTORE_DEFAULT_PAGE_SIZE: int = 199
PLAYSTORE_PAGE_SIZE_POLICY_LIMIT: int = 199
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

**Status: IMPLEMENTADO**

> **Notas de implementación:** Para cumplir la prueba de aceptación
> `test_limpiar_texto_bancario_preserves_error_codes_and_emojis` (Feature 1.5),
> la implementación final elimina hashtags completos (`#\w*`), colapsa espacios
> internos (`\s+` → `" "`) y no reduce dígitos repetidos (`(\D)\1{2,}`) para
> preservar códigos y montos. La 4ª función es `cumple_umbral_palabras`
> (rango `[MIN_REVIEW_WORDS, MAX_REVIEW_WORDS]`).

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

**Status: IMPLEMENTADO**

> **Notas de implementación:**
>
> * Todos los modelos usan `extra="forbid"`; todas las `datetime` se normalizan a UTC (las *naive* se asumen UTC) vía `ensure_utc`.
> * El watermark separa observaciones, progreso incremental y planes históricos;
>   los cursores pertenecen a streams con contexto completo y las fronteras se
>   respaldan mediante referencias a ledgers, sin truncamiento de IDs.
> * `SanitizedReviewRecord` valida además que `conteo_palabras` coincida con `texto_limpio`. `AnalyzedReviewPrediction.is_obligatory_5_star_bias` siempre se recalcula.

**Objetivo:** Definir todos los modelos de transferencia de datos entre capas en `packages/voc-common/src/voc_common/schemas.py`.

#### Tarea 1.3.1: Esquemas de Solicitud de Ingesta y Cursor RPC

1. **`PlayStoreRpcCursor(BaseModel)`**:

* `app_id: str`
* `lang: str = DEFAULT_PLAYSTORE_LANG`
* `country: str = DEFAULT_PLAYSTORE_COUNTRY`
* `sort_order: PlayStoreSortOrder = PlayStoreSortOrder.NEWEST`
* `star_filter: int | None = Field(default=None, ge=1, le=5)` (`None` consulta todas las estrellas; `1..5` identifica streams experimentales separados, sin garantía de superar límites del origen).
* `page_token: str | None = None` (Cursor opaco devuelto por `batchexecute`, ligado al contexto completo del stream).

1. **`IngestionRequestPayload(BaseModel)`**:

* `bank_id: BankKey`
* `mode: IngestionMode = IngestionMode.INCREMENTAL`
* `page_size: int = Field(default=PLAYSTORE_DEFAULT_PAGE_SIZE, ge=1, le=PLAYSTORE_PAGE_SIZE_POLICY_LIMIT)`
* `max_reviews_per_run: int = Field(default=5000, ge=1, le=250000)`
* `partition_by_stars: bool = False` (Si es `True` en `FULL_BACKFILL`, extrae por separado 1, 2, 3, 4 y 5 estrellas).

1. **`SequentialBatchIngestionRequest(BaseModel)`**:

* Contrato para el Job Maestro en modo Free Tier (`/api/v1/ingest/all`):
* `banks: list[BankKey] = Field(default_factory=lambda: list(BankKey))`
* `mode: IngestionMode = IngestionMode.INCREMENTAL`
* `max_reviews_per_bank: int = Field(default=1000, ge=1, le=50000)`
* `inter_bank_delay_sec: float = Field(default=15.0, ge=1.0, le=120.0)`

#### Tarea 1.3.2: Contratos de estado de ingesta

El único contrato de estado es `IngestionWatermarkState` con `schema_version=2`.
Contiene identidad, revisión, fechas observadas, progreso incremental y referencias
a planes, streams y ledgers. El avance se aplica por página confirmada, nunca
por una reseña conocida o por un mínimo/máximo aislado. Ver features 1.6–1.7.
El primer despliegue empieza con un estado vacío; IaC no crea esos objetos.

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
* `source_observed_at: datetime` (obligatorio; `raw.ingested_at`, tiempo de captura en el origen. Añadido por la decisión D1 de EPIC-4 para ordenar revisiones con igual `fecha`; `SanitizedReviewEnvelope.from_event` exige que coincida con el sobre crudo).
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

**Status: IMPLEMENTADO**

> **Notas de implementación y revisión (2026-10-14):**
>
> * `Settings` incluye todos los campos del contrato y `.env.example` cubre
>   exactamente sus variables. `get_settings()` usa caché; se puede invalidar
>   mediante `get_settings.cache_clear()`.
> * El pool de proxies acepta JSON, CSV y valores vacíos. Las plantillas DLP
>   vacías se normalizan a `None`. Las variables del proceso tienen prioridad
>   sobre `.env`.
> * Se validan límites del scraper, valores numéricos finitos, umbral HITL y
>   sal de al menos 16 caracteres sin contar espacios en los extremos. La sal
>   de desarrollo se rechaza en `prod` / `production`.
> * Se exporta la API pública mediante `__all__`. Se requiere
>   `pydantic-settings>=2.7.0` por el uso de `NoDecode`.
> * Los nombres coinciden con la especificación de la Épica 2; la integración
>   con Pulumi se verifica en EPIC-2 (2.7–2.10).
> * La revisión de Features 1.1–1.3 añade validación del límite de 500 IDs al
>   cargar checkpoints. La cobertura ahora mide solo código de `voc-common`.
> * Validación local con Python 3.11.14 y 3.12.10: 89 pruebas pasan, cobertura del código
>   fuente del 100%; Ruff (lint y formato), Pyrefly y Bandit sin errores.
>   La Feature 1.5 configura la ejecución automatizada en Python 3.11.

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
    bq_ingestion_runs_log_table: str = "ingestion_runs_log_v2"
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

**Status: IMPLEMENTADO**

> **Notas de implementación y verificación (2026-10-14):**
>
> * GitHub Actions ejecuta los gates en `push` y `pull_request`, con Python 3.11,
>   `astral-sh/setup-uv@v3`, permisos de lectura y límite de 15 minutos.
> * `GCP_PROJECT_ID`, `USER_HASH_SALT` y `SCRAPER_PROXY_POOL_URLS` se obtienen
>   de secrets con fallbacks de prueba; `ENVIRONMENT=test`. No se requieren
>   credenciales GCP para las pruebas unitarias.
> * La sincronización usa `--locked` y los comandos `uv run --frozen` para
>   conservar las versiones de `uv.lock`. Los hooks locales `ruff`,
>   `ruff-format` y `bandit` usan el mismo entorno; no se incluye `gitleaks`.
> * La suite existente supera el mínimo de 10 pruebas y cubre todos los casos
>   de aceptación, incluida la limpieza exacta del texto del notebook.
> * Verificado en Python 3.11.14: 89 pruebas pasan, cobertura de código fuente
>   del 100%, Ruff (lint/formato), Pyrefly y Bandit sin errores. Los tres hooks
>   pasan con `pre-commit run --all-files`; configuración y YAML válidos.
> * El workflow está implementado; su primera ejecución en GitHub Actions
>   se producirá al hacer push o abrir un pull request.

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
4. **Contratos y transiciones del estado de ingesta:** validar round-trip UTC,
fronteras mediante ledger, idempotencia por página, fallo de publicación y
anual -> FULL con T0 fijo, según las suites de features 1.6–1.7.

5. **`test_obligatory_5_star_label_noise_detection`**: Comprobar que `AnalyzedReviewPrediction` marque `is_obligatory_5_star_bias=True` cuando `estrellas=5` y `tnss_score=SentimentLabel.NEG`.

---

### FEATURE 1.6: Contratos de Estado v2, Planes Históricos y Streams de Paginación

**Status: IMPLEMENTADO**

**Objetivo:** Definir contratos capaces de describir avance
incremental, histórico y recuperación sin confundir cursor con cobertura.
**Dependencias:** Features 1.1–1.5. Contrato funcional coordinado con EPIC-3.
**Archivos:** `schemas.py`, `constants.py`, `__init__.py` y `tests/test_schemas.py` y `tests/test_ingestion_contracts.py`
del paquete `voc-common`.

> **Notas de implementación:**
>
> * `IngestionWatermarkState` es el único contrato raíz y usa schema_version=2.
> * Los modelos v2 son inmutables, estrictos ante campos extra, normalizan UTC y
>   usan referencias de ledger; tokens opacos se conservan pero se ocultan en repr.
> * El fingerprint incluye el contexto completo; las validaciones locales cubren
>   identidad banco/app, fechas, contadores y evidencia de cierre. Las relaciones
>   entre objetos no cargados se comprobarán en el reducer/repositorio de 1.7/3.2.
> * Se incluyen recibos tipados; generar eventos/revisiones e integrar destinos
>   se implementa en 1.8. La feature 1.6 no incluye CAS ni acceso GCP.
> * Verificación: 177 pruebas conjuntas (voc-common + infra), cobertura del 100%
>   del código medido; Ruff lint/formato, Pyrefly y Bandit sin errores. Persiste
>   la advertencia de deprecación interna del SDK Pulumi GCP Storage.

#### Tarea 1.6.1: Implementar y exportar contratos v2

* Incorporar modelos estrictos (`extra="forbid"`, fechas UTC, `schema_version=2`):
  `IngestionWatermarkState`, `IncrementalProgress`, `HistoricalPlan`, `ScanContext`,
  `ScanStreamState`, `PageManifest` y `ProcessingReceipt`, según EPIC-3/EPIC-4.
  La raíz conserva revisión y referencias; ledgers paginados contienen los IDs,
  sin cargar todo el corpus ni textos/usuarios en el watermark.
* Separar `observed_min_at`/`observed_max_at` de `committed_high_at`. Los límites
  observados no demuestran cobertura; un máximo no descarta publicaciones tardías.
  Mantener baseline incremental congelado, frontera completa y reconciliación.
  Un ID conocido aislado no cierra el scan. No truncar a 500 los IDs necesarios
  como evidencia: usar referencias al ledger cuando superen la caché.
* `HistoricalPlan` fija T0 y corte anual T0-365 días. Anual -> FULL elimina la cota
  inferior del mismo plan y registra la extensión; conserva ancla, páginas y T0.
  Guardar completa la página que cruza el corte. No recalcularlo al reanudar.
* `ScanContext` incluye app, idioma, país, orden, filtros, tamaño y versión de
  protocolo; su fingerprint delimita el stream. Cambiar contexto crea otro stream,
  sin heredar tokens. `None` de cursor no distingue inicio de EOF: usar estado
  explícito. El replay recupera el nuevo cursor de salida de la página ancla.
* Versionar manifiestos inmutables con cursores de entrada/salida, fingerprint de
  contenido, respaldo URI/generación y fases de publicación/sanitización separadas.
  Identificar páginas independientemente del token: se observó distinto token de
  continuación con idénticos IDs. `SOURCE_EXHAUSTED_OBSERVED` no certifica que el
  origen exponga todo su histórico.

#### Evidencia experimental y consecuencias para el contrato (2026-10-15 UTC)

El sondeo de BBVA, contexto es/mx/NEWEST/global y páginas de 199, registró:

* La cabecera incorporó dos IDs nuevos; el cursor de entrada guardado para la
  página 2 devolvió los mismos 199 IDs, mismo orden, unos 30 minutos después.
* Seguir el cursor de la cabecera nueva devolvió primero los dos IDs desplazados
  de la cabecera original y después los primeros 197 de la página 2 original.
  No hubo solapamiento con la cabecera nueva. La respuesta 016 coincide con los
  IDs de `report (3).json` y recupera ambos registros de frontera.
* La unión cabecera nueva + página 2 antigua omite esos dos IDs si no se conservó
  la cabecera original. Por tanto, no mezclar cadenas/contextos ni descartar
  evidencia anterior al reconciliar. Los IDs ya respaldados siguen disponibles.
* Distintos tokens de salida devolvieron páginas con iguales IDs: separar identidad
  lógica de página, fingerprint de contenido y token físico. No deducir offsets,
  snapshots, caducidad global ni exhaustividad a partir de este sondeo.

Esta evidencia basta para fijar los contratos v2; la continuación desde el token
reproducido antiguo, cadenas de 500, recuperación tras expiración y otros bancos
siguen como aceptación experimental de EPIC-3, no como bloqueos de estos modelos.

#### Tarea 1.6.2: Definir estados y validar referencias

* Tipar estados de plan/stream, fases por página y evidencia de cierre. Distinguir
  `NOT_STARTED`, `RUNNING`, `PAUSED`, `RECOVERY_REQUIRED`, `TARGET_REACHED`,
  `SOURCE_EXHAUSTED_OBSERVED` y `BLOCKED`, según las transiciones de EPIC-3.
* Validar identidad banco/app/contexto entre plan, stream y página; rechazar
  fechas y contadores contradictorios. Los checks entre objetos referenciados
  corresponden al reducer/repositorio, no a un modelo que no los haya cargado.

**Criterios de aceptación:**

* [x] Modelos/exportaciones v2 y round-trip JSON estrictos, con fechas UTC.
* [x] Anual y FULL se representan con el mismo plan; incremental independiente.
* [x] Contexto distinto no reutiliza stream/token; EOF no se deduce de `None`.
* [x] Fronteras de más de 500 IDs se representan mediante ledger sin truncamiento.

---

### FEATURE 1.7: Transiciones por Página y Recuperación Verificable

**Status: IMPLEMENTADO**

**Objetivo:** Aplicar avance lógico puro por páginas completas, con checks de
identidad/contexto/revisión y sin confundir respaldo/publicación con resultado TDS.
**Dependencias:** Feature 1.6.
**Archivos:** `ingestion_state.py`, pruebas y exports de `voc-common`.

#### Tarea 1.7.1: Reducer de páginas y reanudación

* `commit_page` valida stream/contexto/epoch, secuencia, revisión esperada y
  publicación completa. El repositorio suministra manifiestos/ledgers verificados.
* Repetir un commit no incrementa contadores; un commit contradictorio se rechaza.
* Pausa/recuperación son explícitas. El replay de ancla con contenido inalterado
  renueva la continuación sin contar dos veces la página y conserva cada intento
  en su manifiesto. Cambios de contenido exigen reconciliación.
* Cursores nulos se pueden borrar explícitamente sin inferir EOF. No mezclar
  cabeceras nuevas con páginas de otra cadena ni usar caches truncadas como prueba.

#### Tarea 1.7.2: Planes e incremental independientes

* Extender anual -> FULL conserva plan, T0, streams, páginas y evidencia anterior.
  Mantener completa la página que cruza el corte; no recalcular el año al reanudar.
* Baseline incremental congelado, candidato y frontera comprometida distintos.
  El cierre requiere evidencia/ledger completos; respaldos y publicación parcial
  no comprometen el máximo. El cierre histórico exige todos los streams del plan.
* Reducer sin I/O. El repositorio de EPIC-3 verifica objetos/publicaciones y aplica
  CAS/lease; las validaciones locales no proporcionan transacciones entre objetos.

**Criterios de aceptación:**

* [x] Commit/extensión idempotentes y publicación parcial sin avance.
* [x] T0 fijo, fronteras >500 IDs mediante ledger y cursor terminal probados.
* [x] Fixture de cabecera mutable detecta huecos por mezcla de cadenas.
* [x] Tokens distintos con mismo contenido no duplican avance; intentos auditables.
* [x] Un único contrato y estado inicial vacío, sin lectores alternativos.

---

### FEATURE 1.8: Eventos Versionados, Configuración y Pruebas de Contratos

**Status: IMPLEMENTADO**

**Objetivo:** Entregar a EPIC-2/EPIC-3 contratos y configuración coherentes para
publicar, auditar y procesar páginas de forma idempotente.
**Dependencias:** Features 1.6–1.7; contratos de destino acordados con EPIC-4.
**Archivos:** `schemas.py`, `config.py`, `constants.py`, `__init__.py`, pruebas del
paquete, `.env.example` y documentación de configuración.

> **Notas de implementación:**
>
> * Sobres `RawReviewEnvelope`/`SanitizedReviewEnvelope` con snapshots inmutables,
>   identidad determinista y propagación a `ProcessingReceipt.from_event`.
>   `compute_source_revision` excluye `ingested_at`; `compute_event_id` no incluye
>   página/stream/plan. Payload y digest contradictorios se rechazan.
> * `IngestionRunAudit` define el contrato separado de auditoría v2. No se crea
>   su tabla en esta feature; EPIC-2 2.8 aprovisiona solo la tabla actual.
> * Settings y payloads usan default/límite de política separados (ambos 199);
>   Cloud Run y Scheduler consumen esos defaults
>   compartidos. No se habilitaron páginas de 500 sin validar sus cadenas.
> * Settings valida prefijos persistentes separados de staging, budgets positivos,
>   margen de checkpoint y heartbeat/lease. V2 está desactivado por defecto; el
>   preflight histórico exige la referencia del Job que exportará Pulumi 2.9.
> * `.env.example` cubre todos los campos. Fixtures sintéticas de eventos, recibos,
>   auditoría y estado inicial quedan en `packages/voc-common/tests/fixtures/ingestion/`.
> * Algoritmo, variables y orden de activación documentados en
>   [contratos de ingesta v2](../contracts/ingestion_v2.md). Esta feature completa
>   EPIC-1; recursos 2.7–2.10, consumidores y CAS/leases siguen en sus épicas.
> * Verificación final: 234 pruebas conjuntas (voc-common + infra) y cobertura
>   medida del 100%; Ruff lint/formato, Pyrefly, Bandit y diff-check pasan.
>   Persiste la advertencia de deprecación interna conocida del SDK Pulumi GCP.

#### Tarea 1.8.1: Implementar identidad de revisión, sobre y recibos

* Añadir un sobre de evento con `event_id`, `page_id`, `plan_id`, `stream_id`,
  banco, ID y `source_revision`, más `RawReviewEvent`. Derivar revisión del contenido
  del origen (incluidos cambios de votos/respuesta), nunca de `ingested_at`.
  Propagar identidad/revisión al resultado sanitizado y `ProcessingReceipt` según
  EPIC-4. Repetir la misma revisión es idempotente; cambiar contenido produce otra.
* Definir modelo de auditoría separado para `ingestion_runs_log_v2` de EPIC-2,
  sin cursores completos ni texto crudo. Publicación confirmada y resultado TDS
  son estados distintos; recibos de filtrado/cuarentena no equivalen a fila TDS.

#### Tarea 1.8.2: Actualizar configuración y límites de política

* Default y límite de política son constantes separadas; ambos valen 199
  inicialmente, sin afirmar un máximo nativo del endpoint. Antes de
  habilitar 500, validar paginación y actualizar conjuntamente `Settings`, payloads,
  pruebas y configuración de EPIC-2. Los lotes DLP tienen límites independientes.
* Añadir configuración de prefijos de manifiestos/ledgers, tabla de auditoría v2,
  referencia del Job histórico y presupuestos de tiempo/solicitudes/bytes. Definir
  propietario de cada parámetro y defaults compatibles con EPIC-2/EPIC-3; conservar
  el contrato único de estado. No activar consumidores antes de aprovisionar sus
  tablas y Jobs.
* Exponer prefijo de estado `state/watermarks`, prefijo de metadatos
  `state/ingestion` y tabla `ingestion_runs_log_v2`. El nombre del Job se obtiene
  del recurso Pulumi, sin un nombre físico supuesto. Presupuestos positivos y
  configuración de lease/heartbeat deben validarse; los valores de ejecución
  deben dejar margen de checkpoint antes del timeout del contenedor.

#### Tarea 1.8.3: Verificar contratos públicos y regresiones

* Mantener fixtures del contrato actual compartidas con las
  pruebas del extractor y de infraestructura. Actualizar consumidores y exports
  que supongan el esquema anterior; no limitarse a añadir clases sin integrarlas.
* Ejecutar Ruff, Pyrefly, Bandit y pytest con el umbral de cobertura del paquete.
  Las pruebas CAS/lease y del endpoint real pertenecen a EPIC-3, no a estos tests.

**Criterios de aceptación:**

* [x] Misma revisión genera mismo ID; cambios de contenido generan nueva revisión.
* [x] Recibos distinguen TDS, filtrado, cuarentena y errores; publicación no es TDS.
* [x] Settings/payloads/defaults coinciden; 199 no se documenta como máximo nativo.
* [x] Configuración y fixtures v2 disponibles; quality gates y regresiones pasan.

---

## ✅ Criterios de Aceptación de la Épica 1 (Checklist de Verificación)

* [x] `voc-common` no depende de `google-play-scraper` y modela los tokens de paginación como `str` opacos compatibles con el RPC `oCPfdb` de `batchexecute`.
* [x] Los tres modos de `IngestionMode` comparten contratos de planes/streams y progreso incremental independientes.
* [x] `SanitizedReviewRecord` garantiza 0% de almacenamiento de `usuario` o `imagen_usuario` en texto plano y preserva códigos de error `ref: 3702`.
* [x] Los 4 Quality Gates (`ruff`, `pyrefly`, `bandit`, `pytest`) pasan sin errores con cobertura $\ge 85\%$.

Criterios adicionales de contratos y transiciones:

* [x] Modelos v2, eventos/revisiones y recibos compartidos implementados y exportados.
* [x] Estado inicial vacío con cobertura `UNVERIFIED`, sin datos inferidos.
* [x] Reducer por página, T0 fijo y referencias a fronteras completas probados.
* [x] Configuración/contratos y fixtures definidos para recursos y consumidores v2; su activación queda en EPIC-2/EPIC-3/EPIC-4.
* [x] Quality gates y pruebas del contrato pasan; activación de consumidores aún pendiente en sus épicas.
