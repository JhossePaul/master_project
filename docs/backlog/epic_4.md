# EPIC-4: Sanitización PII, Persistencia Idempotente y Cobertura TDS

* **Estado:** En implementación. Features 4.1–4.4 implementadas; feature 4.5 pendiente. Especificación revisada el 2026-10-15 contra EPIC-1–3 y EPIC-2; decisiones D1–D3 resueltas.
* **Semanas Objetivo:** Semanas 3 - 4
* **Dependencias:** `EPIC-1` (Features 1.1–1.8 implementadas), `EPIC-2` (Features 2.1–2.10 implementadas) y `EPIC-3` (Features 3.1–3.5 implementadas: `RawReviewEnvelope`, `PageManifest`, capturas JSONL.gz en `raw_staging/`, `WatermarkRepository`, `BacklogSignal` e imagen del worker).
* **Directorios Afectados:**
  * `pyproject.toml` (retirar `services/sanitization-pipeline` de `tool.uv.workspace.exclude`) y `uv.lock`
  * `.dockerignore` (lista de permitidos: añadir las rutas del servicio)
  * `.github/workflows/ci.yaml` (pruebas, cobertura y construcción de imagen)
  * `services/sanitization-pipeline/pyproject.toml`, `README.md` y `Dockerfile`
  * `services/sanitization-pipeline/src/sanitization_pipeline/__init__.py`
  * `services/sanitization-pipeline/src/sanitization_pipeline/config.py`
  * `services/sanitization-pipeline/src/sanitization_pipeline/dlp_transforms.py`
  * `services/sanitization-pipeline/src/sanitization_pipeline/bq_writer.py`
  * `services/sanitization-pipeline/src/sanitization_pipeline/processing_ledger.py`
  * `services/sanitization-pipeline/src/sanitization_pipeline/pipeline.py`
  * `services/sanitization-pipeline/tests/__init__.py`
  * `services/sanitization-pipeline/tests/test_execution_config.py` y `conftest.py`
  * `services/sanitization-pipeline/tests/test_dlp_transforms.py`
  * `services/sanitization-pipeline/tests/test_bq_writer_and_ledger.py`
  * `services/sanitization-pipeline/tests/test_pipeline.py`
  * `services/ingestion-worker/src/ingestion_worker/publisher.py` (solo exponer la lectura pública de capturas; ver 4.4)

---

## 🎯 Objetivo y Límites de la Garantía

Consumir los sobres versionados (`RawReviewEnvelope`) y respaldos de página duraderos emitidos por `EPIC-3`, desidentificar datos personales (PII) mediante **Cloud DLP + Regex de respaldo** antes de tocar BigQuery, aplicar el filtro del EDA (2 a 60 palabras inclusive), persistir de forma idempotente el estado vigente en `bbva_voc_tds.sanitized_reviews_tds` y emitir recibos inmutables (`ProcessingReceipt`) en Cloud Storage para reconciliar qué páginas publicadas por la ingesta quedaron resueltas en TDS.

* **Cero PII en BigQuery:** No existe tabla de texto crudo en BigQuery. Toda tabla temporal de staging para operaciones `MERGE` solo recibe registros **ya sanitizados** (`SanitizedReviewRecord`).
* **Criterio medible de privacidad:** «Cero fugas en el corpus de prueba» es un criterio de aceptación determinista; ningún modelo NER/regex demuestra detección del 100% de PII en lenguaje natural abierto. El modo de regex local (`LocalRegexFallbackSanitizer`) actúa como segunda barrera (*Defense in Depth*) después de Cloud DLP en producción o como herramienta explícita para pruebas offline (`use_cloud_dlp_api=False`); **en producción el sistema es *fail-closed*: si Cloud DLP falla o no está disponible, no se escribe en TDS usando solo regex**.
* **Estados reales del contrato:** no existe un estado `SANITIZED_COMMITTED`. Por evento se usa `ProcessingStatus` (`TDS_COMMITTED`, `FILTERED_LENGTH`, `QUARANTINED`, `RETRYABLE_ERROR`); por página, `SanitizationStatus` (`PENDING`, `PROCESSING`, `RESOLVED`, `GAPS_DETECTED`). `PUBLISHED` en un manifiesto de ingesta no equivale a `TDS_COMMITTED`.
* **La sanitización no modifica el estado de la ingesta:** `PageManifest` es inmutable y la raíz `state/watermarks/{bank_id}.json` solo cambia bajo el lease/CAS de EPIC-3. Este pipeline **lee** manifiestos y ledgers sin adquirir lease y **escribe solo** recibos y cierres de página inmutables bajo `GCS_PROCESSING_RECEIPTS_PREFIX`. Exponer esa cobertura en `GET /api/v1/watermarks/{bank_id}` es un seguimiento posterior a 4.3.

---

## 🔗 Alineación Estricta con Contratos e Infraestructura Existente (EPIC-1, EPIC-2 y EPIC-3)

El Agente IA **DEBE** respetar las siguientes restricciones de acoplamiento con lo ya implementado en el monorepo:

1. **Uso Exclusivo de Sobres y Recibos de `voc-common` (Feature 1.8):**
   * **Prohibido crear modelos duplicados.** Importar directamente desde `voc_common`: `RawReviewEnvelope`, `SanitizedReviewEnvelope`, `SanitizedReviewRecord`, `ProcessingReceipt` (usando `ProcessingReceipt.from_event(...)`), `ProcessingStatus`, `SanitizationStatus`, `IngestionStorageLayout`, `Settings`, `compute_source_revision`, `compute_event_id`, `limpiar_texto_bancario` y `cumple_umbral_palabras`.
   * `SanitizedReviewRecord.from_raw_and_dlp(...)` copia `raw.titulo` **sin sanitizar** y solo recibe `texto_sanitizado`/`texto_respuesta_sanitizado`. Ambos adaptadores de Google Play fijan `titulo=None`. Por tanto, un `raw.titulo` no nulo se trata como `QUARANTINED` (`error_code="UNEXPECTED_TITLE"`) hasta que `voc-common` acepte un título sanitizado; nunca se envía a TDS.
   * `ProcessingReceipt.from_event(...)` exige `result_digest` y `bigquery_job_ids` para `TDS_COMMITTED`, y `error_code` para `QUARANTINED`/`RETRYABLE_ERROR`. `result_digest` es el SHA-256 del JSON canónico del `SanitizedReviewEnvelope` persistido.
2. **Alineación con las 17 Columnas de `sanitized_reviews_tds` (Feature 2.4 / 2.10 y decisión D1):**
   * La tabla `bbva_voc_tds.sanitized_reviews_tds` en BigQuery tiene un esquema fijo de **17 columnas** (`id_resena`, `bank_id`, `app_id`, `usuario_hash`, `titulo`, `texto_sanitizado`, `texto_limpio`, `conteo_palabras`, `pii_findings_count`, `estrellas`, `votos_utilidad`, `version_app`, `fecha`, `texto_respuesta_sanitizado`, `fecha_respuesta`, `sanitized_at`, `source_observed_at`), particionada por día en `fecha` y agrupada por `bank_id, version_app`.
   * `source_observed_at` (`TIMESTAMP REQUIRED`) es el tiempo de captura en el origen (`raw.ingested_at`, congelado por EPIC-3 al `fetched_at` de la página). `SanitizedReviewRecord.from_raw_and_dlp` lo copia y `SanitizedReviewEnvelope.from_event` exige que coincida con el sobre crudo. `sanitized_at` sigue siendo tiempo de proceso.
   * **No agregar columnas no aprovisionadas al insert de BigQuery.** La trazabilidad de versión y transporte (`event_id`, `source_revision`, `page_id`, `plan_id`, `stream_id`, `processed_at` y digest del resultado) se persiste de forma duradera en los recibos (`ProcessingReceipt`) dentro de Cloud Storage bajo los prefijos de `IngestionStorageLayout`.
   * El orden entre revisiones es `(fecha, source_observed_at)`: con igual `fecha` (cambian votos o respuesta) gana la observación más reciente del origen, no la última procesada.
3. **Cálculo Exacto de `pii_findings_count: int` por Fila (`INTEGER REQUIRED`):**
   * En `SanitizedReviewRecord` y en BigQuery, `pii_findings_count` es un entero obligatorio (`>= 0`, no nulo).
   * La plantilla `voc-dlp-deidentify-template` (Feature 2.3, `infra/modules/dlp.py`) usa `replace_config` con valores literales con corchetes, porque `replaceWithInfoTypeConfig` no los agrega: `[PERSON_NAME]`, `[EMAIL_ADDRESS]`, `[PHONE_NUMBER]`, `[CREDIT_CARD_NUMBER]`, `[MEXICO_CURP_NUMBER]`, `[MX_CLABE_BANCARIA]`, `[MX_RFC_TAX_ID]`, `[BBVA_ACCOUNT_NUMBER]`.
   * El conteo es **de tokens introducidos**: ocurrencias en la salida (DLP + segunda barrera) **menos** las ocurrencias literales que el usuario ya había escrito en la entrada. Se cuenta sobre `texto_sanitizado`/`texto_respuesta_sanitizado`, antes de `limpiar_texto_bancario` (que pasa a minúsculas).
4. **Plantillas DLP regionales:**
   * Pulumi inyecta `DLP_INSPECT_TEMPLATE_ID` y `DLP_DEIDENTIFY_TEMPLATE_ID` con el **nombre completo** del recurso (`projects/{p}/locations/{region}/inspectTemplates/...` y `.../deidentifyTemplates/...`). Las solicitudes usan `parent=projects/{GCP_PROJECT_ID}/locations/{GCP_REGION}`; en `setup()` se valida que ambos nombres pertenezcan a ese mismo `parent` (*fail-closed*).
   * La plantilla de inspección ya excluye `PHONE_NUMBER` y `BBVA_ACCOUNT_NUMBER` cuando coinciden con el patrón `ref: 3702:...`. El pre-enmascarado local de diagnósticos es una defensa adicional, no un sustituto.
5. **Tablas Temporales de Staging para `MERGE` dentro de `bbva_voc_tds`:**
   * En `EPIC-2` existe un único dataset (`bbva_voc_tds`) y la cuenta `voc-sa-sanitization` posee `roles/bigquery.dataEditor` y `roles/bigquery.jobUser`.
   * Para ejecutar el `MERGE` idempotente sin usar *Streaming Inserts*, `bq_writer.py` crea tablas efímeras dentro de `bbva_voc_tds` con prefijo `_staging_sanitized_` y expiración automática de 1 hora, carga allí únicamente filas **ya sanitizadas** mediante `load_table_from_json` (`FILE_LOADS`), ejecuta el `MERGE` hacia `sanitized_reviews_tds` y elimina la tabla temporal al finalizar.
6. **Manejo de Cuarentena y DLQ acorde a Permisos IAM de `voc-sa-sanitization`:**
   * En `EPIC-2` (Feature 2.2 y 2.7), `voc-sa-sanitization` tiene `roles/pubsub.subscriber`, `roles/pubsub.viewer`, `roles/dlp.user`, `roles/bigquery.dataEditor`, `roles/bigquery.jobUser` y `roles/storage.objectUser` en el bucket `voc-datalake`, pero **no tiene `roles/pubsub.publisher`**.
   * Ante un error permanente (`QUARANTINED`), el pipeline **no** publica manualmente en Pub/Sub: persiste el recibo `ProcessingReceipt(status="QUARANTINED", error_code=...)` en Cloud Storage y confirma (`ack`) el mensaje para no ciclar la cola. Para errores transitorios (`RETRYABLE_ERROR`), no envía `ack` (o aplica `modify_ack_deadline(0)`); el agente de Pub/Sub (con los grants `voc-dlq-forward-publisher`/`voc-dlq-source-subscriber` ya aprovisionados) reintenta y reenvía a `voc-raw-reviews-dlq` tras 5 entregas.
7. **Ventanas temporales que acotan la recuperación:** `voc-raw-reviews-sub` retiene mensajes 7 días con `ack_deadline_seconds=600`; el lifecycle borra `raw_staging/` a los 7 días; Scheduler lanza `voc-sanitization-job` a las 08:30 (30 min después de la ingesta), con 1 tarea, 1 CPU, 1 GiB, timeout de 1800 s, `max_retries=1` y `BEAM_RUNNER=DirectRunner`. El Job no recibe argumentos: los defaults del CLI deben ser válidos en producción.
8. **Acceso de solo lectura al estado de la ingesta:** para localizar manifiestos, ledgers y capturas se reutiliza `ingestion_worker.WatermarkRepository` (`load`, `find_page`, `get_manifest`, `iter_ledger`) como dependencia de workspace, **sin** `acquire_lease`, `commit_page` ni escrituras en la raíz. No se reimplementan los modelos privados del catálogo/índice (riesgo de divergencia). Ver D2.

---

## 📦 Desglose de Features e Historias Técnicas

### FEATURE 4.1: Configuración del Paquete `sanitization-pipeline`, Runners y Presupuestos

**Objetivo:** Integrar `sanitization-pipeline` al workspace de `uv` sin alterar versiones compartidas, definir la configuración de ejecución validada y la interfaz CLI con presupuestos acotados, y dejar CI y la imagen preparados para las features siguientes.

**Estado: IMPLEMENTADA.** Paquete en el workspace; `uv.lock` añade 18 paquetes
(Apache Beam 2.77.0 núcleo, `google-cloud-dlp` y sus dependencias) **sin cambiar
ninguna versión compartida**. `config.py` define `SanitizationExecutionConfig`,
`load_config` (default < `SANITIZATION_*` < flag) y `preflight` (*fail-closed*);
`pipeline.py` es el entrypoint con códigos de salida 0/64/70/75 y un registro
de modos vacío hasta 4.4, de modo que el Job termina con 70 sin hacer pull ni
escribir. CI ejecuta la suite con cobertura >=85% y `.dockerignore` admite las
rutas del servicio. La imagen de ingesta se volvió a construir con el nuevo
miembro del workspace.
Desviación: el extra `dataflow = ["apache-beam[gcp]"]` **no** se declara. uv
resuelve todos los extras en `uv.lock`, y declararlo añadía 57 paquetes y bajaba
`tenacity` 9.2.1 → 9.1.4 aunque no se instale. Se añadirá con el
aprovisionamiento de Dataflow.
Validación: 26 tests del paquete (100% de cobertura de líneas); Ruff, formato,
Pyrefly y Bandit sin errores. Sin llamadas reales a DLP, Pub/Sub ni BigQuery.

**Evidencia de resolución (sondeo local del 2026-10-15 sobre una copia del workspace, sin modificar `uv.lock`):**

| Variante | Paquetes nuevos | Cambios en versiones compartidas |
| --- | --- | --- |
| Especificación anterior (`apache-beam[gcp]`, `google-cloud-storage<3`) | 76 | `google-cloud-storage` 3.17.0 → 2.19.0 en todo el workspace; `tenacity` bifurcado |
| `apache-beam[gcp]`, storage `<4` | 75 | `tenacity` 9.2.1 → 9.1.4 |
| **`apache-beam` (núcleo), storage `<4`** | **18** | **ninguno** (Beam 2.77.0, protobuf 6.33.6) |

`DirectRunner` y `TestPipeline` no requieren el extra `[gcp]`; los clientes de GCP se declaran directamente. El extra solo es necesario para `DATAFLOW_MANAGED`, que además requiere infraestructura no aprovisionada (ver 4.1.2).

#### Tarea 4.1.1: Configurar `services/sanitization-pipeline/pyproject.toml`

Rangos alineados con `ingestion-worker` para no degradar dependencias compartidas:

```toml
[project]
name = "sanitization-pipeline"
version = "0.1.0"
description = "Pipeline Apache Beam / Cloud DLP para sanitizacion activa de PII, cobertura TDS y emision de recibos v2"
requires-python = ">=3.11"
dependencies = [
    "apache-beam>=2.55,<3",
    "google-cloud-dlp>=3.16,<4",
    "google-cloud-pubsub>=2.23,<3",
    "google-cloud-bigquery>=3.27,<4",
    "google-cloud-storage>=2.19,<4",
    "tenacity>=9,<10",
    "pydantic>=2.6,<3",
    "voc-common",
    "ingestion-worker",
]

# Sin extra [gcp]: uv lo resolvería en uv.lock y cambiaría versiones
# compartidas. Se añadirá al aprovisionar Dataflow (DATAFLOW_MANAGED).

[tool.uv.sources]
voc-common = { workspace = true }
ingestion-worker = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Pasos de integración del workspace:

1. Retirar `"services/sanitization-pipeline"` de `tool.uv.workspace.exclude` en el `pyproject.toml` raíz.
2. Ejecutar `uv lock` y comprobar que **ninguna versión compartida cambia** (comparar `uv.lock` antes/después); solo se añaden paquetes. Confirmar que `uv sync --all-packages --locked --python 3.11` funciona.
3. Añadir a `.github/workflows/ci.yaml` el paso `uv run --frozen pytest services/sanitization-pipeline/tests --cov=sanitization_pipeline --cov-fail-under=85`.
4. Crear `services/sanitization-pipeline/README.md` con uso y límites.

#### Tarea 4.1.2: Configuración de Ejecución, Presupuestos y CLI (`config.py`, `pipeline.py`)

Modelo puro `SanitizationExecutionConfig` (Pydantic, `extra="forbid"`, `frozen=True`) en `config.py`, con defaults válidos para el Job y validación de invariantes:

| Campo / flag CLI | Default | Regla |
| --- | --- | --- |
| `execution_mode` / `--execution-mode` | `BATCH_PULL_SERVERLESS` | `GCS_BACKFILL_MANIFESTS` procesa páginas seleccionadas por manifiesto y generación, nunca un glob ciego de `raw_staging/`. `DATAFLOW_MANAGED` se rechaza con error explícito mientras falten la API `dataflow.googleapis.com` (hoy solo con `enable_vertex`), permisos de worker de Dataflow y el extra `dataflow` |
| `max_messages` / `--max-messages` | 2000 | `> 0`; drenado en microbatches |
| `microbatch_size` / `--microbatch-size` | 200 | `1..max_messages`; nunca más de esos textos en memoria a la vez |
| `max_runtime_sec` / `--max-runtime-sec` | 1500 | `max_runtime_sec + checkpoint_margin_sec <= container_timeout_sec` |
| `checkpoint_margin_sec` | 300 | Cubre el último microbatch en vuelo (DLP + carga + `MERGE`) |
| `container_timeout_sec` | 1800 | Debe coincidir con el timeout del Job |
| `ack_deadline_sec` | 600 | Igual a la suscripción |
| `ack_renew_interval_sec` | 180 | `< ack_deadline_sec` |
| `dlp_max_rows` / `dlp_max_bytes` | 250 / 400 000 | Por debajo del límite de 524 288 bytes por solicitud de DLP |
| `use_cloud_dlp_api` | `True` | `False` solo para pruebas offline; en producción (`Settings.is_production`) se rechaza |

* El CLI acepta flags y, en su ausencia, variables `SANITIZATION_*` equivalentes; sin argumentos produce una configuración válida para el Job.
* Preflight antes de procesar: `Settings.require_ingestion_v2()`, plantillas DLP presentes y del mismo `parent` regional (si `use_cloud_dlp_api`), `BEAM_RUNNER=DirectRunner` y sal de usuario válida (el validador de `Settings` ya prohíbe la sal de desarrollo en producción). Un preflight fallido termina con código distinto de cero antes de hacer *pull*.
* Códigos de salida alineados con el Job histórico: 0 ejecución completa o presupuesto agotado con estado consistente; 75 fallo transitorio (mensajes sin `ack`); 64 configuración inválida.

#### Tarea 4.1.3: Imagen y CI preparados

* Añadir a `.dockerignore` (lista de permitidos) `services/sanitization-pipeline/pyproject.toml` y `services/sanitization-pipeline/src/`; las rutas de `voc-common` e `ingestion-worker` ya están incluidas. Nunca entran `.env`, `evidence/`, `.git` ni `.venv`.
* El Dockerfile se completa en 4.4; `cloudbuild.yaml` omite Dockerfiles vacíos, así que la imagen no se publica antes.

---

### FEATURE 4.2: Desidentificación Tabular en Cloud DLP, Protección de Diagnósticos y *Fail-Closed* (`dlp_transforms.py`)

**Objetivo:** Implementar el sanitizador local de respaldo y el `DoFn` de Apache Beam que empaqueta lotes respetando límites de filas y bytes de Cloud DLP, protege códigos `ref: 3702`, calcula `pii_findings_count` por fila y aplica el filtro de 2 a 60 palabras del EDA.

**Estado: IMPLEMENTADA.** `dlp_transforms.py` contiene `LocalRegexFallbackSanitizer`,
`count_introduced_pii_tokens`, `DlpRowBatchPacker`, `CloudDlpDeidentifier`,
`BatchSanitizer` (lógica pura por microbatch) y `BatchCloudDlpDeidentifyDoFn`
(envoltorio Beam con salidas etiquetadas). Validación: 52 tests del paquete
(100% de cobertura de líneas), 532 tests conjuntos; Ruff, formato, Pyrefly y
Bandit sin errores. Sin llamadas reales a Cloud DLP: el DLP simulado reconoce
solo nombres y correos, de modo que el corpus prueba la segunda barrera.

Decisiones y hallazgos de la implementación:

* **Beam y Prism:** desde Beam 2.6x, `DirectRunner` intenta primero Prism, que
  descarga un binario (~65 MB) en tiempo de ejecución, y no hay opción para
  desactivarlo. `in_process_runner()` (`config.py`) devuelve el `FnApiRunner`
  en proceso; es la interpretación de `BEAM_RUNNER=DirectRunner` en el Job y en
  CI. Un test falla si Prism llega a ejecutarse.
* **Orden de reglas:** email primero (los dígitos de una dirección no deben
  partirla), luego CLABE, CURP antes de RFC (los 13 primeros caracteres de una
  CURP cumplen el patrón de RFC), tarjeta y teléfonos con formato. Los límites
  numéricos usan `(?<!\d)`/`(?!\d)` en lugar de `\b`, que no corta entre `_` y
  un dígito y permitiría evadir con `id_5512345678_x`.
* **10 dígitos:** se mira una ventana de 40 caracteres previos; decide la
  palabra de contexto más cercana (teléfono: `tel`, `cel`, `llam`, `whats`,
  `marc`, `número`, `contacto`; cuenta: `cuenta`, `cta`, `clabe`, `depósito`).
  Sin contexto, `[BBVA_ACCOUNT_NUMBER]`. Es una heurística: el número queda
  enmascarado en ambos casos.
* **Placeholders:** el nonce es de 16 letras aleatorias por instancia; ninguna
  regla numérica puede alterarlo y un usuario no puede predecirlo.
* **Fail-closed:** respuesta desalineada (filas o celdas) y transitorios
  agotados (`429`, `503`, `504`, `500`; 4 intentos, backoff exponencial ≤16 s,
  timeout de 60 s por llamada) emiten recibos `RETRYABLE_ERROR`
  (`DLP_MISALIGNED`/`DLP_UNAVAILABLE`) y ningún sobre válido. Permisos,
  credenciales, argumento inválido, plantilla inexistente o precondición
  fallida lanzan `DlpConfigurationError` y detienen la corrida.
* **Recibos:** `receipt_id = event_id`; los `RETRYABLE_ERROR` salen por su
  etiqueta para que 4.4 no haga `ack`, pero no se persisten como terminales.
  Un mensaje imposible de parsear como `RawReviewEnvelope` se trata en 4.4.
* **Pendiente para 4.4:** los reintentos de DLP no conocen el presupuesto de
  tiempo restante; el orquestador debe comprobarlo antes de cada microbatch.

#### Tarea 4.2.1: Implementar `LocalRegexFallbackSanitizer` en `dlp_transforms.py`

1. **Tokens Oficiales Reconocidos (`DLP_INFO_TYPE_TOKENS`):**
   * Tupla constante con los 8 tokens exactos de `infra/modules/dlp.py` (Feature 2.3). Un test compara la tupla con los info types declarados en infra para detectar divergencias.
2. **Protección de Códigos Técnicos (`ref: 3702:65c5:9xhchi`) y Tokens Existentes:**
   * Antes de evaluar expresiones regulares locales, sustituir exclusivamente los fragmentos que coincidan con `r"ref\s*:\s*\d{4}\s*:\s*[a-zA-Z0-9]+\s*:\s*[a-zA-Z0-9]+"` por un placeholder con *nonce* criptográfico por ejecución (`__VOC_DIAG_{nonce}_{idx}__`), que un usuario no puede predecir ni inyectar.
   * Proteger igualmente los tokens `[<INFO_TYPE>]` ya emitidos por Cloud DLP para evitar reemplazos anidados.
3. **Reglas Regex de Segunda Barrera (en este orden, sobre dígitos aislados):**
   * CLABE (18 dígitos) → `[MX_CLABE_BANCARIA]`.
   * CURP (18 caracteres con el formato oficial) → `[MEXICO_CURP_NUMBER]`.
   * Tarjeta (16 dígitos, con o sin espacios/guiones) → `[CREDIT_CARD_NUMBER]`.
   * RFC (`\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b`, sin distinguir mayúsculas) → `[MX_RFC_TAX_ID]`.
   * Email → `[EMAIL_ADDRESS]`.
   * **10 dígitos:** `[PHONE_NUMBER]` si tienen formato telefónico (`+52`, separadores) o una palabra de contexto previa cercana (`tel`, `cel`, `llam*`, `whats*`, `marca*`, `número`); en otro caso `[BBVA_ACCOUNT_NUMBER]`. Ambos patrones son de 10 dígitos: la regla de contexto es la única forma determinista de distinguirlos y se documenta como heurística.
   * Restaurar los placeholders diagnósticos `ref: 3702...`.
4. **Conteo Exacto de Hallazgos por Fila (`count_introduced_pii_tokens`):**
   * Función determinista que devuelve `tokens(salida) - tokens_literales(entrada)` sobre `texto` y `texto_respuesta`, para poblar `pii_findings_count`. Un usuario que escribe `[PHONE_NUMBER]` no infla el conteo.

#### Tarea 4.2.2: Empaquetador por Filas y Bytes (`DlpRowBatchPacker`) y `BatchCloudDlpDeidentifyDoFn`

1. **Límite Dual de Lote (Filas $\le 250$ y Payload Serializado $\le 400\text{ KB}$):**
   * Cloud DLP impone un límite de `524,288 bytes` (0.5 MB) por solicitud de `deidentify_content`.
   * Dividir cualquier lote de `RawReviewEnvelope` en sub-lotes que no superen **250 filas** ni **400 KB** de bytes UTF-8 acumulados, aceptando lotes menores en el último tramo. Una sola fila mayor de 400 KB se emite como `QUARANTINED` (`error_code="DLP_ROW_TOO_LARGE"`).
2. **Alineación Posicional Sidecar (prohibido enviar `id_resena` o `event_id` como celda transformable a DLP):**
   * La `dlp_v2.Table` enviada a `deidentify_content` contiene **únicamente las 2 columnas de texto libre que el contrato puede persistir**: `["texto", "texto_respuesta"]` (`texto_respuesta` vacío cuando es `None`). `titulo` no se envía: se rechaza antes (restricción 1).
   * Los identificadores (`event_id`, `id_resena`, `source_revision`) se conservan en una lista *sidecar* en memoria indexada por posición `0..N-1`.
   * Validar estrictamente que `len(response.item.table.rows) == len(sidecar)` y que cada fila tenga exactamente 2 celdas; si hay desalineación, error explícito (*fail-closed*).
3. **Política *Fail-Closed* y Reintentos en Cloud DLP:**
   * En producción (`use_cloud_dlp_api=True`), si las plantillas faltan, son inválidas o no pertenecen al `parent` regional, fallar en `setup()`.
   * Ante errores transitorios de DLP (`429 ResourceExhausted`, `503 ServiceUnavailable`, `504 DeadlineExceeded`), reintentar con backoff exponencial acotado (`tenacity`), dentro del presupuesto de tiempo restante. Si el lote falla tras agotar reintentos, emitir los eventos por `OUTPUT_TAG_RETRYABLE_ERROR`: **no** se hace `ack` ni se escribe en BigQuery. `PermissionDenied`/`InvalidArgument` también son *fail-closed*, pero detienen la corrida (configuración), sin poner eventos en cuarentena.
4. **Construcción de `SanitizedReviewEnvelope` y Salidas Tipadas (`TaggedOutputs`):**
   * Tras las celdas sanitizadas por Cloud DLP y la segunda barrera:
   * Limpiar el texto con `limpiar_texto_bancario(texto_sanitizado)` y evaluar `cumple_umbral_palabras(texto_limpio)` (rango `[2, 60]` palabras de Feature 1.2) **antes** de construir el registro, porque `from_raw_and_dlp` falla fuera de rango.
   * **Fuera del rango `[2, 60]`:** `ProcessingReceipt.from_event(envelope, status="FILTERED_LENGTH", ...)` (sin cuerpo crudo) en `OUTPUT_TAG_FILTERED_LENGTH`.
   * **Dentro del rango:** `SanitizedReviewRecord.from_raw_and_dlp(...)` (hashea `usuario` con `Settings.user_hash_salt`, descarta `imagen_usuario` y verifica `conteo_palabras`), envuelto con `SanitizedReviewEnvelope.from_event(...)` (conserva `event_id`, `page_id`, `plan_id`, `stream_id` y `source_revision`), en `OUTPUT_TAG_SANITIZED_VALID`.
   * **Violación irrecuperable del contrato** (JSON inválido, identidad inconsistente, título no nulo, fila sobredimensionada): `ProcessingReceipt.from_event(..., status="QUARANTINED", error_code=...)` en `OUTPUT_TAG_QUARANTINED`. Un mensaje que ni siquiera se puede parsear como `RawReviewEnvelope` no tiene evento: se registra un diagnóstico sin texto (atributos `event_id`/`page_id` y motivo) y se confirma.

---

### FEATURE 4.3: Persistencia Idempotente en BigQuery TDS y Ledger de Recibos (`bq_writer.py`, `processing_ledger.py`)

**Objetivo:** Persistir los lotes de `SanitizedReviewEnvelope` en `bbva_voc_tds.sanitized_reviews_tds` mediante cargas batch y `MERGE` determinista, y escribir los recibos `ProcessingReceipt` en Cloud Storage respetando el layout de `EPIC-2`/`EPIC-3`.

**Estado: IMPLEMENTADA.** `bq_writer.py` (`BigQueryTdsUpsertManager`,
`record_to_bq_row`, `latest_revisions`, `merge_statement`, `envelope_digest`) y
`processing_ledger.py` (`ProcessingLedgerRepository`, `PageClosure`,
`tds_committed_receipts`). Validación: 69 tests del paquete (100% de cobertura
de líneas), 549 tests conjuntos; Ruff, formato, Pyrefly y Bandit sin errores.
Sin BigQuery ni GCS reales: el `MERGE` se valida por su texto y la página se
compromete con `WatermarkRepository` sobre GCS simulado con generaciones.

Decisiones de la implementación:

* **Staging:** `_staging_sanitized_{hash16}_{aleatorio8}` en `bbva_voc_tds`,
  esquema de 17 columnas, expiración de 1 h, carga NDJSON `WRITE_TRUNCATE` y
  borrado en `finally` (`not_found_ok`). Si el borrado falla, la expiración la
  limpia. El sufijo aleatorio evita chocar con una tabla huérfana al reintentar.
* **Errores:** cualquier fallo de carga o `MERGE` (incluidos `errors` del job)
  se convierte en `TdsWriteError` sin propagar el mensaje de BigQuery, que puede
  citar datos. Los identificadores del `MERGE` se validan con expresión regular
  antes de componer el SQL (BigQuery no parametriza identificadores).
* **Recibos `TDS_COMMITTED`:** se emiten para todos los sobres del lote,
  incluidas las revisiones superadas por la deduplicación, con los IDs de los
  jobs de carga y `MERGE` y el digest de su propio sobre.
* **Ledger:** primer escritor gana. Un reintento con otro `processed_at`
  devuelve el recibo ya persistido. El índice `_events/` se escribe después del
  recibo de la página y conserva el primer resultado del evento.
  `copy_receipt_for_page` replica ese resultado para otra página sin volver a
  invocar DLP ni BigQuery.
* **Cierre de página:** `PageClosure` es un modelo local del paquete (no está
  en `voc-common`); se promoverá cuando el GET de progreso de la ingesta lo lea.
  `reconcile_page` devuelve `PENDING` sin escribir si la página aún no está
  comprometida (el publisher publica antes del commit) o si faltan recibos; con
  `staging_expired=True` los faltantes se cierran como hueco `STAGING_EXPIRED`.
  El cierre no toca la raíz ni los manifiestos de la ingesta (probado).
* **Rendimiento:** `find_already_processed_event_ids` hace una lectura por
  evento (≤ `microbatch_size`); paralelizarla queda para 4.4 si hace falta.

#### Tarea 4.3.1: Implementar `BigQueryTdsUpsertManager` en `bq_writer.py`

1. **Serialización Estricta de las 17 Columnas (`record_to_bq_row`):**
   * Convierte `envelope.record` a un diccionario con exactamente las 17 columnas, formateando `fecha`, `fecha_respuesta`, `sanitized_at` y `source_observed_at` en UTC ISO-8601. Un test compara las claves con el esquema `_SANITIZED` de `infra/modules/storage_bq.py`.
2. **Deduplicación en Lote y Tabla Efímera con Expiración:**
   * Deduplicar en memoria por `(bank_id, id_resena)`, conservando el mayor `(fecha, source_observed_at)`; en empate, el mayor `source_revision`.
   * Crear `bbva_voc_tds._staging_sanitized_{batch_id}`, donde `batch_id` es un hash corto en `[a-z0-9_]` (los IDs de corrida no se usan sin normalizar), con el mismo esquema de 17 columnas y `expires = now + 1 h`.
   * Cargar con `load_table_from_json(..., job_id_prefix="voc_tds_load_")`. **No usar `job_id` deterministas:** BigQuery rechaza reutilizar un ID ya usado (409), incluso si ese job falló; la idempotencia la aporta el `MERGE`.
3. **Sentencia `MERGE` Idempotente sin Reversión Temporal:**
   * `MERGE INTO` `sanitized_reviews_tds` (`target`) desde la tabla temporal (`source`) `ON target.bank_id = source.bank_id AND target.id_resena = source.id_resena`:
     * `WHEN MATCHED AND (source.fecha > target.fecha OR (source.fecha = target.fecha AND source.source_observed_at >= target.source_observed_at)) THEN UPDATE SET ...`: un replay con `fecha` anterior, o con igual `fecha` pero capturado antes, nunca sobrescribe una revisión más reciente; la misma observación reaplicada es idempotente.
     * `WHEN NOT MATCHED THEN INSERT ...`
   * Esperar `query_job.result()`, verificar que no haya errores, eliminar la tabla temporal en `finally` (`not_found_ok=True`) y devolver los IDs de los jobs de carga y `MERGE` para los recibos `TDS_COMMITTED`.
   * El orden depende del reloj del worker de ingesta que fijó `fetched_at`; dos capturas del mismo instante con contenidos distintos se resuelven por el desempate en lote (`source_revision`) y, entre lotes, gana la última aplicada. Se prueba explícitamente.

#### Tarea 4.3.2: Implementar `ProcessingLedgerRepository` en `processing_ledger.py`

Utilizar `IngestionStorageLayout`, nombres validados como segmentos seguros y escritura condicional (`if_generation_match=0`); ante 412, releer y aceptar solo si el contenido es idéntico. Rutas relativas a `GCS_PROCESSING_RECEIPTS_PREFIX`:

| Objeto | Ruta | Contenido |
| --- | --- | --- |
| Recibo de evento en una página | `{bank_id}/{page_id}/{event_id}.json` (`receipt_id = event_id`; coincide con la ruta de recibos de EPIC-2) | `ProcessingReceipt` |
| Índice de resultado por evento | `{bank_id}/_events/{event_id}.json` | Recibo terminal canónico del evento (primera página que lo resolvió) |
| Cierre de página | `{bank_id}/_pages/{page_id}.json` | `page_id`, `SanitizationStatus`, conteos por estado, eventos faltantes/en cuarentena y motivo (`STAGING_EXPIRED`, `QUARANTINED`); sin texto |

1. **`write_event_receipts(self, receipts: list[ProcessingReceipt]) -> None`**: persiste recibos terminales (`TDS_COMMITTED`, `FILTERED_LENGTH`, `QUARANTINED`) y el índice por evento. `RETRYABLE_ERROR` no se persiste como terminal.
2. **`find_already_processed_event_ids(self, bank_id, event_ids: set[str]) -> dict[str, ProcessingReceipt]`**: consulta el índice `_events/`. Si un evento llega desde **otra página** (BACKFILL y FULL comparten `event_id`), se escribe el recibo de esa página copiando el resultado, sin volver a invocar Cloud DLP ni BigQuery.
3. **`reconcile_page(self, bank_id, page_id) -> SanitizationStatus`**:
   * Localiza el `PageManifest` por lectura (restricción 8) y recorre su ledger completo de eventos (`iter_ledger`), sin truncar.
   * `RESOLVED` si todos los `event_id` válidos tienen recibo `TDS_COMMITTED` o `FILTERED_LENGTH`; `GAPS_DETECTED` si alguno está `QUARANTINED` o si la captura expiró antes de procesarse; `PENDING` en otro caso (no se escribe cierre).
   * Escribe el cierre de página una sola vez por estado terminal; no modifica manifiestos, raíz ni watermark.

---

### FEATURE 4.4: Orquestador del Pipeline, Renovación de Lease de Ack y Replay desde GCS (`pipeline.py`, `Dockerfile`)

**Objetivo:** Coordinar el ciclo completo de drenado por microbatches desde Pub/Sub (o desde manifiestos en GCS), manteniendo vivo el *ack deadline* durante la ejecución de DLP + BigQuery y confirmando mensajes únicamente tras persistencia duradera.

**Estado: IMPLEMENTADA.** `orchestrator.py` (`MicrobatchProcessor`,
`AckDeadlineRenewer`, `PubSubDrainer`, `ManifestBackfill`, `run_do_fn`,
`build_services`) registra `BATCH_PULL_SERVERLESS` y `GCS_BACKFILL_MANIFESTS`
en `pipeline.py`. `ingestion-worker` expone `restore_capture`,
`read_committed_capture` y `WatermarkRepository.read_backup` (lectura por URI y
generación del manifiesto). Dockerfile multi-stage (uid 10001, 651 MB por Beam,
pyarrow y numpy) y job de CI `sanitization-image`, que construye la imagen y
comprueba la salida 64 sin v2 y el usuario. La imagen se probó localmente sin
red: un microbatch en Beam se procesa sin descargar Prism.
Validación: 86 tests del paquete (100% de cobertura de líneas), 183 del worker
de ingesta, 567 tests conjuntos; Ruff, formato, Pyrefly y Bandit sin errores.
Las pruebas del orquestador capturan y publican una página con el publisher
real de EPIC-3 y usan esos mismos mensajes. Sin Pub/Sub, DLP, BigQuery ni GCS
reales.

Decisiones de la implementación:

* **Beam por microbatch:** `run_do_fn` ejecuta `BatchCloudDlpDeidentifyDoFn`
  con el `FnApiRunner` en proceso y recoge las cuatro salidas mediante una
  función de módulo (Beam serializa por valor los cierres definidos en
  `__main__`). El DoFn, y por tanto el cliente DLP, se crea por microbatch.
* **Mensajes veneno:** JSON inválido o atributos que no coinciden con el sobre
  (`event_id`, `page_id`, `source_revision`, `bank_id`, `schema_version`) se
  confirman con un log que solo incluye `message_id`; no hay evento con el que
  emitir un recibo.
* **Fallos parciales:** si falla el `MERGE`, solo los eventos válidos se
  devuelven (`nack`); los `FILTERED_LENGTH`/`QUARANTINED` se persisten y se
  confirman. Un fallo al escribir recibos (GCS) devuelve todo el microbatch y
  detiene la corrida (salida 75). `DlpConfigurationError` devuelve el
  microbatch y termina con 64. Un error inesperado devuelve el microbatch y
  se propaga.
* **Orden:** recibos → `ack` → cierre de páginas. Un fallo al cerrar se cuenta
  como `ERROR` en el reporte y no bloquea el `ack` (el cierre se repite).
* **Renovación:** un hilo renueva el deadline (600 s) cada 180 s mientras dura
  el microbatch; un fallo de renovación solo se registra (la reentrega es
  segura).
* **Presupuestos:** el tiempo se comprueba antes de cada pull; el peor caso de
  DLP por sub-lote (4 intentos × 60 s + esperas ≤16 s) cabe en el margen de
  300 s. El backfill cuenta eventos contra `max_messages`.
* **Backfill:** toma la última versión de cada página del ledger de
  manifiestos de la ingesta, omite las que ya tienen cierre, lee la captura por
  URI/generación y, si ya no existe, cierra la página como `STAGING_EXPIRED`.
* **Salida:** 0 sin pendientes; 75 si quedó algún evento devuelto o hubo un
  fallo transitorio; 64 por configuración. Log final JSON de una línea con
  conteos, sin textos ni PII.

#### Tarea 4.4.1: Implementar `services/sanitization-pipeline/src/sanitization_pipeline/pipeline.py`

1. **Drenado Acotado y Agrupación de `ack_ids` por `event_id`:**
   * En modo `BATCH_PULL_SERVERLESS`, solicitar hasta `microbatch_size` mensajes de `PUBSUB_RAW_SUBSCRIPTION` (pull síncrono) mientras quede presupuesto de mensajes y tiempo.
   * Parsear cada mensaje como `RawReviewEnvelope` y verificar que coincida con sus atributos (`event_id`, `page_id`, `source_revision`, `bank_id`, `schema_version="2"`) que publica `RawReviewBatchPublisher`.
   * **Deduplicación con preservación de `ack_ids`:** agrupar en `ack_ids_by_event_id: dict[str, list[str]]` y hacer `acknowledge()` de **todos** los `ack_id` del evento al terminar. Las páginas distintas de un mismo evento se conservan para escribir sus recibos.
   * Consultar primero `ledger.find_already_processed_event_ids(...)`: los eventos ya resueltos se confirman de inmediato (tras escribir el recibo de la página nueva, si falta) y se excluyen del lote de DLP.
2. **Renovación Periódica de Lease de Ack (`AckDeadlineRenewer`):**
   * Mientras dura el microbatch, invocar `modify_ack_deadline(ack_ids=active_ack_ids, ack_deadline_seconds=600)` cada `ack_renew_interval_sec` (180 s). Detenerlo siempre en `finally`. Reloj y temporizador inyectables para pruebas.
3. **Ejecución del Grafo Apache Beam (`DirectRunner`) y Orden de Confirmación:**
   * Ejecutar el pipeline sobre el microbatch con `BatchCloudDlpDeidentifyDoFn`.
   * **Orden transaccional estricto post-Beam:**
     1. `bq_writer.upsert_sanitized_batch(sanitized_valid_envelopes)`.
     2. Construir y persistir los `ProcessingReceipt` terminales con `ledger.write_event_receipts(...)`.
     3. **Solo si 1 y 2 tuvieron éxito**, `acknowledge()` de los eventos terminales (`TDS_COMMITTED`, `FILTERED_LENGTH`, `QUARANTINED`).
     4. Reconciliar las páginas tocadas (`ledger.reconcile_page`). Su fallo no impide el `ack`: la reconciliación es idempotente y se repite en la siguiente corrida.
     5. Para `RETRYABLE_ERROR` (o si falló BigQuery/DLP), **no** hacer `ack`.
   * Al agotarse el presupuesto, terminar el microbatch en curso y salir; los mensajes no confirmados quedan para la siguiente corrida.
4. **Modo Replay desde Manifiestos en GCS (`GCS_BACKFILL_MANIFESTS`):**
   * Recorrer los manifiestos comprometidos del banco por lectura (raíz → catálogo → ledger de manifiestos) y seleccionar los `PUBLISHED` sin cierre de página.
   * Leer la captura desde `backup_uri` y `backup_generation` del manifiesto (nunca construir la ruta ni hacer glob) mediante una función **pública** de lectura de capturas que expone `ingestion-worker` (refactor mínimo de `RawReviewBatchPublisher._restore`, con las mismas validaciones de fingerprint).
   * Procesar los sobres por la misma tubería de DLP + BigQuery + recibos, sin Pub/Sub ni `ack`.
   * Si la captura ya no existe (404 o generación distinta tras el lifecycle de 7 días), escribir el cierre de página `GAPS_DETECTED` con motivo `STAGING_EXPIRED`. La recuperación desde el origen pertenece a EPIC-3.

#### Tarea 4.4.2: Implementar `services/sanitization-pipeline/Dockerfile`

Mismo patrón que `services/ingestion-worker/Dockerfile`: multi-stage con `python:3.11-slim-bookworm` y `uv` copiado desde `ghcr.io/astral-sh/uv` (versión fijada), `uv sync --frozen --no-dev --package sanitization-pipeline --no-editable`, usuario no root (uid 10001), contexto en la raíz del workspace y `ENTRYPOINT ["python", "-m", "sanitization_pipeline.pipeline"]`. El Job de Pulumi no fija `command`, así que el `ENTRYPOINT` es el que se ejecuta. CI añade un job que construye la imagen y comprueba entrypoint y usuario, como `ingestion-image`.

---

### FEATURE 4.5: Suite de Pruebas Deterministas y Observabilidad (`tests/`)

**Objetivo:** Validar con `pytest` y `apache_beam.testing.test_pipeline.TestPipeline` (sin red ni credenciales GCP en CI) todos los invariantes de privacidad, empaquetado DLP, idempotencia en BigQuery y manejo de leases de Pub/Sub.

#### Tarea 4.5.1: Implementar `test_dlp_transforms.py`, `test_bq_writer_and_ledger.py` y `test_pipeline.py`

La suite debe cubrir obligatoriamente estos escenarios:

1. **Cero fugas en corpus bancario anotado y conteo exacto de hallazgos:** reseñas con nombres propios, CLABE, tarjetas, cuentas BBVA, RFC, CURP, correos, teléfonos y emojis en `texto` y `texto_respuesta`. `SanitizedReviewRecord` no contiene ningún PII original, `usuario_hash` es SHA-256 de 64 caracteres y `pii_findings_count` coincide con los tokens introducidos (un token literal escrito por el usuario no cuenta).
2. **Preservación de diagnósticos `ref: 3702` con PII adyacente e inyección adversarial:** `"mi cuenta 0123456789 marca error ref: 3702:65c5:9xhchi al llamar al 5512345678"` enmascara `[BBVA_ACCOUNT_NUMBER]` y `[PHONE_NUMBER]` y conserva `ref: 3702:65c5:9xhchi` en `texto_limpio`. Un falso placeholder escrito por el usuario no evade la sanitización.
3. **Empaquetado dual (>250 filas y >400 KB) y protección sidecar de IDs:** el lote se divide en varias llamadas a `deidentify_content`; `id_resena`, `event_id` y `titulo` nunca viajan en `dlp_v2.Table`; una fila sobredimensionada queda en cuarentena.
4. **Política *fail-closed*:** menos filas o celdas que el sidecar, `PermissionDenied`, `ServiceUnavailable` agotado o plantillas de otra región no emiten ningún `SanitizedReviewEnvelope` con solo regex cuando `use_cloud_dlp_api=True`.
5. **Bordes exactos del EDA (1, 2, 60 y 61 palabras) post-sanitización:** 1 y 61 generan `FILTERED_LENGTH`; 2 y 60 generan `SanitizedReviewEnvelope`.
6. **Agrupación de `ack_ids` e idempotencia por recibo previo:** `evt_1` dos veces en el mismo pull (`a1`, `a2`) se procesa una vez y confirma `["a1", "a2"]`; en una corrida posterior con recibo `TDS_COMMITTED` se confirma sin llamar a DLP ni a BigQuery; desde otra página escribe el recibo de esa página sin DLP.
7. **Atomicidad BigQuery → ledger → ack:** si falla el `MERGE` o la escritura de recibos, no se llama a `acknowledge()`; la tabla `_staging_sanitized_*` siempre se elimina; un replay con `fecha` más antigua, o con igual `fecha` y `source_observed_at` anterior, no sobrescribe; un reintento de carga no reutiliza `job_id`.
8. **Renovación de lease de ack (>600 s):** con reloj/temporizador simulados, `AckDeadlineRenewer` invoca `modify_ack_deadline` periódicamente y se detiene al terminar o fallar el microbatch.
9. **Reconciliación de página y expiración de staging:** con todos los eventos `TDS_COMMITTED`/`FILTERED_LENGTH` el cierre es `RESOLVED`; con cuarentena es `GAPS_DETECTED`; si la captura ya no existe (404), el cierre es `GAPS_DETECTED` con `STAGING_EXPIRED`. Ninguna operación escribe en la raíz ni en manifiestos de la ingesta.
10. **Configuración y contratos cruzados:** defaults válidos sin argumentos; invariantes de presupuesto; `DATAFLOW_MANAGED` rechazado; tokens DLP y 17 columnas idénticos a los declarados en `infra/`.

#### Tarea 4.5.2: Observabilidad

* Log final JSON de una línea por corrida (sin textos ni PII): mensajes recibidos, eventos por estado, duplicados confirmados, páginas `RESOLVED`/`GAPS_DETECTED`, jobs de BigQuery y presupuesto consumido.
* Señal de backlog para EPIC-3 (`BacklogSignal`): la ingesta ya acepta una señal inyectable que hoy nunca pausa. Una implementación real (p. ej., antigüedad del mensaje más viejo sin `ack` vía Cloud Monitoring) requiere `roles/monitoring.viewer` para la cuenta de ingesta, no aprovisionado. Queda como seguimiento con cambio explícito de IAM en EPIC-2.

---

## 🧭 Decisiones resueltas (2026-10-15)

* **D1 — Orden de revisiones en el `MERGE`: columna `source_observed_at` añadida ya.** `SanitizedReviewRecord` (voc-common), el esquema `_SANITIZED` de `infra/modules/storage_bq.py`, la fixture `sanitized_envelope_v2.json` y las pruebas de ambos paquetes se actualizaron antes del primer despliegue (no hay datos que migrar). El `MERGE` ordena por `(fecha, source_observed_at)`.
* **D2 — Lectura del estado de la ingesta: dependencia de `ingestion-worker` solo para lectura.** Sin lease ni escrituras en la raíz o en manifiestos; la única modificación en ese paquete es exponer la lectura pública de capturas (4.4).
* **D3 — Beam en el Job: núcleo de `apache-beam` con `DirectRunner`.** El extra `[gcp]` no se declara todavía (ver estado de 4.1); `DATAFLOW_MANAGED` permanece rechazado por el preflight hasta aprovisionar Dataflow.

---

## ✅ Checklist de Aceptación de la Épica 4

* [ ] Consume `RawReviewEnvelope` y emite `SanitizedReviewEnvelope` y `ProcessingReceipt` de `voc-common` sin duplicar contratos ni alterar las 17 columnas de `bbva_voc_tds.sanitized_reviews_tds`.
* [ ] Integra el paquete al workspace sin cambiar versiones compartidas de `uv.lock`.
* [ ] Calcula `pii_findings_count: int` (`>= 0`) contando los tokens introducidos por fila, cumpliendo el contrato `INTEGER REQUIRED` de BigQuery.
* [ ] Empaqueta peticiones tabulares a Cloud DLP respetando simultáneamente $\le 250$ filas y $\le 400\text{ KB}$, manteniendo identificadores en un sidecar fuera de la tabla DLP.
* [ ] Opera en modo *fail-closed* en producción (`use_cloud_dlp_api=True`): jamás escribe en TDS usando solo regex si Cloud DLP falla.
* [ ] Carga lotes sanitizados en tablas temporales con TTL de 1 hora dentro de `bbva_voc_tds` y ejecuta `MERGE` idempotente sin usar *Streaming Inserts*.
* [ ] Gestiona cuarentena en GCS (acorde a los permisos IAM de `voc-sa-sanitization`), renueva leases de ack y confirma mensajes en Pub/Sub únicamente después de persistir en BigQuery y en el ledger de recibos.
* [ ] Cierra páginas como `RESOLVED`/`GAPS_DETECTED` sin escribir en el estado de la ingesta.
* [ ] Los comandos `uv run ruff check services/sanitization-pipeline`, `uv run ruff format --check services/sanitization-pipeline`, `uv run pyrefly check`, `uv run bandit -c pyproject.toml -r services/sanitization-pipeline` y `uv run pytest services/sanitization-pipeline/tests --cov=sanitization_pipeline --cov-fail-under=85` pasan con **0 errores**.
