# EPIC-4: Sanitización PII, Persistencia Idempotente y Cobertura TDS

* **Estado:** Pendiente. Especificación actualizada y sincronizada con contratos v2 (EPIC-1), IAM/Tablas (EPIC-2) y Publisher/Watermarks (EPIC-3).
* **Semanas Objetivo:** Semanas 3 - 4
* **Dependencias:** `EPIC-1` (Features 1.1–1.8 implementadas), `EPIC-2` (Features 2.1–2.10 implementadas) y `EPIC-3` (Features 3.1–3.3 implementadas: `RawReviewEnvelope`, `PageManifest` y `IngestionStorageLayout`).
* **Directorios Afectados:**
  * `services/sanitization-pipeline/pyproject.toml`
  * `services/sanitization-pipeline/Dockerfile`
  * `services/sanitization-pipeline/src/sanitization_pipeline/__init__.py`
  * `services/sanitization-pipeline/src/sanitization_pipeline/dlp_transforms.py`
  * `services/sanitization-pipeline/src/sanitization_pipeline/bq_writer.py`
  * `services/sanitization-pipeline/src/sanitization_pipeline/processing_ledger.py`
  * `services/sanitization-pipeline/src/sanitization_pipeline/pipeline.py`
  * `services/sanitization-pipeline/tests/__init__.py`
  * `services/sanitization-pipeline/tests/test_dlp_transforms.py`
  * `services/sanitization-pipeline/tests/test_bq_writer_and_ledger.py`
  * `services/sanitization-pipeline/tests/test_pipeline.py`

---

## 🎯 Objetivo y Límites de la Garantía

Consumir los sobres versionados (`RawReviewEnvelope`) y respaldos de página duraderos emitidos por `EPIC-3`, desidentificar datos personales (PII) mediante **Cloud DLP + Regex de respaldo** antes de tocar BigQuery, aplicar el filtro del EDA (2 a 60 palabras inclusive), persistir de forma idempotente el estado vigente en `bbva_voc_tds.sanitized_reviews_tds` y emitir recibos inmutables (`ProcessingReceipt`) en Cloud Storage para reconciliar qué páginas pasaron de `PUBLISHED` a `SANITIZED_COMMITTED`.

* **Cero PII en BigQuery:** No existe tabla de texto crudo en BigQuery. Toda tabla temporal de staging para operaciones `MERGE` solo recibe registros **ya sanitizados** (`SanitizedReviewRecord`).
* **Criterio medible de privacidad:** «Cero fugas en el corpus de prueba» es un criterio de aceptación determinista; ningún modelo NER/regex demuestra detección del 100% de PII en lenguaje natural abierto. El modo de regex local (`LocalRegexFallbackSanitizer`) actúa como segunda barrera (*Defense in Depth*) después de Cloud DLP en producción o como herramienta explícita para pruebas offline (`use_cloud_dlp_api=False`); **en producción el sistema es *fail-closed*: si Cloud DLP falla o no está disponible, no se escribe en TDS usando solo regex**.

---

## 🔗 Alineación Estricta con Contratos e Infraestructura Existente (EPIC-1, EPIC-2 y EPIC-3)

El Agente IA **DEBE** respetar las siguientes 5 restricciones de acoplamiento con lo ya implementado en el monorepo:

1. **Uso Exclusivo de Sobres y Recibos de `voc-common` (Feature 1.8):**
   * **Prohibido crear modelos duplicados.** Importar directamente desde `voc_common`: `RawReviewEnvelope`, `SanitizedReviewEnvelope`, `SanitizedReviewRecord`, `ProcessingReceipt` (usando `ProcessingReceipt.from_event(...)`), `compute_source_revision` y `compute_event_id`.
2. **Alineación con las 16 Columnas de `sanitized_reviews_tds` (Feature 2.4 / 2.10):**
   * La tabla `bbva_voc_tds.sanitized_reviews_tds` en BigQuery tiene un esquema fijo de **16 columnas** (`id_resena`, `bank_id`, `app_id`, `usuario_hash`, `titulo`, `texto_sanitizado`, `texto_limpio`, `conteo_palabras`, `pii_findings_count`, `estrellas`, `votos_utilidad`, `version_app`, `fecha`, `texto_respuesta_sanitizado`, `fecha_respuesta`, `sanitized_at`).
   * **No agregar columnas no aprovisionadas al insert de BigQuery.** La trazabilidad de versión y transporte (`event_id`, `source_revision`, `page_id`, `plan_id`, `stream_id`, `processed_at` y digest del resultado) se persiste de forma duradera en los archivos de recibos (`ProcessingReceipt`) y sobres (`SanitizedReviewEnvelope`) dentro de Cloud Storage bajo los prefijos de `IngestionStorageLayout`.
3. **Cálculo Exacto de `pii_findings_count: int` por Fila (`INTEGER REQUIRED`):**
   * En `SanitizedReviewRecord` y en BigQuery, `pii_findings_count` es un entero obligatorio (`>= 0`, no nulo).
   * Dado que la plantilla `voc-dlp-deidentify-template` (Feature 2.3) fue configurada con `replace_config` para insertar tokens explícitos con corchetes (`[PERSON_NAME]`, `[EMAIL_ADDRESS]`, `[PHONE_NUMBER]`, `[CREDIT_CARD_NUMBER]`, `[MEXICO_CURP_NUMBER]`, `[MX_CLABE_BANCARIA]`, `[MX_RFC_TAX_ID]`, `[BBVA_ACCOUNT_NUMBER]`), el conteo exacto de hallazgos por reseña se calcula contando las apariciones de dichos tokens semánticos en las celdas desidentificadas de esa fila más cualquier reemplazo adicional del `LocalRegexFallbackSanitizer`.
4. **Tablas Temporales de Staging para `MERGE` dentro de `bbva_voc_tds`:**
   * En `EPIC-2` existe un único dataset (`bbva_voc_tds`) y la cuenta `voc-sa-sanitization` posee `roles/bigquery.dataEditor` y `roles/bigquery.jobUser`.
   * Para ejecutar el `MERGE` idempotente sin usar *Streaming Inserts*, `bq_writer.py` creará tablas de trabajo efímeras dentro del mismo dataset `bbva_voc_tds` con prefijo `_staging_sanitized_{batch_id}` y expiración automática (`table.expires = utcnow() + timedelta(hours=1)`), cargará allí únicamente filas **ya sanitizadas** mediante `load_table_from_json` (`FILE_LOADS`), ejecutará el `MERGE` hacia `sanitized_reviews_tds` y eliminará la tabla temporal al finalizar.
5. **Manejo de Cuarentena y DLQ acorde a Permisos IAM de `voc-sa-sanitization`:**
   * En `EPIC-2` (Feature 2.2 y 2.7), `voc-sa-sanitization` tiene `roles/pubsub.subscriber`, `roles/pubsub.viewer` y `roles/storage.objectUser` en el bucket `voc-datalake`, pero **no tiene `roles/pubsub.publisher`**.
   * Por tanto, ante un error permanente (`QUARANTINED`), el pipeline **no** publica manualmente en un tópico de Pub/Sub: persiste el recibo `ProcessingReceipt(status="QUARANTINED", ...)` y la referencia de diagnóstico en Cloud Storage bajo el prefijo de recibos/cuarentena del `voc-datalake` y confirma (`ack`) el mensaje en Pub/Sub para no ciclar la cola. Para errores transitorios (`RETRYABLE_ERROR`), no envía `ack` (o aplica `modify_ack_deadline(0)`), permitiendo que el agente nativo de Pub/Sub gestione los reintentos y el envío automático a `voc-raw-reviews-dlq` tras 5 intentos.

---

## 📦 Desglose de Features e Historias Técnicas

### FEATURE 4.1: Configuración del Paquete `sanitization-pipeline`, Runners y Presupuestos

**Objetivo:** Integrar `sanitization-pipeline` al workspace de `uv` asegurando compatibilidad de dependencias en `uv.lock` y definir la interfaz CLI con presupuestos acotados.

#### Tarea 4.1.1: Configurar `services/sanitization-pipeline/pyproject.toml`

Escribir `services/sanitization-pipeline/pyproject.toml` y sincronizar el workspace verificando que no existan conflictos de resolución con `pulumi-gcp` ni `protobuf`:

```toml
[project]
name = "sanitization-pipeline"
version = "0.1.0"
description = "Pipeline Apache Beam / Cloud DLP para sanitizacion activa de PII, cobertura TDS y emision de recibos v2"
requires-python = ">=3.11"
dependencies = [
    "apache-beam[gcp]>=2.55.0,<3.0.0",
    "google-cloud-dlp>=3.16.0,<4.0.0",
    "google-cloud-pubsub>=2.21.0,<3.0.0",
    "google-cloud-bigquery>=3.20.0,<4.0.0",
    "google-cloud-storage>=2.16.0,<3.0.0",
    "tenacity>=8.2.3,<10.0.0",
    "pydantic>=2.6.0,<3.0.0",
    "voc-common",
]

[tool.uv.sources]
voc-common = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

```

#### Tarea 4.1.2: Parámetros de Ejecución y Presupuestos Acotados

El CLI en `pipeline.py` debe soportar:

* `--execution-mode`: `BATCH_PULL_SERVERLESS` (default ejecutado por `voc-sanitization-job` en Cloud Run con `DirectRunner`), `GCS_BACKFILL_MANIFESTS` (procesamiento de páginas pendientes seleccionadas por manifiesto/generación en GCS, no mediante un glob ciego que reprocese todo `raw_staging/`), y `DATAFLOW_MANAGED` (modo opt-in posterior).

* `--max-messages`: `int = 2000` (Presupuesto máximo por corrida, drenado en microbatches acotados para jamás cargar miles de textos simultáneamente en RAM).

* `--microbatch-size`: `int = 200` (Máximo de sobres procesados por iteración de pull/beam).
* `--max-runtime-sec`: `int = 1500` (Presupuesto de tiempo con margen de seguridad de 300s antes del timeout de `1800s` del `voc-sanitization-job` en Cloud Run).

---

### FEATURE 4.2: Desidentificación Tabular en Cloud DLP, Protección de Diagnósticos y *Fail-Closed* (`dlp_transforms.py`)

**Objetivo:** Implementar el sanitizador local de respaldo y el `DoFn` de Apache Beam que empaqueta lotes respetando límites de filas y bytes de Cloud DLP, protege códigos `ref: 3702`, calcula `pii_findings_count` por fila y aplica el filtro de 2 a 60 palabras del EDA.

#### Tarea 4.2.1: Implementar `LocalRegexFallbackSanitizer` en `dlp_transforms.py`

1. **Tokens Oficiales Reconocidos (`DLP_INFO_TYPE_TOKENS`):**

* Tupla constante con los 8 tokens exactos configurados en `infra/modules/dlp.py` (Feature 2.3): `("[PERSON_NAME]", "[EMAIL_ADDRESS]", "[PHONE_NUMBER]", "[CREDIT_CARD_NUMBER]", "[MEXICO_CURP_NUMBER]", "[MX_CLABE_BANCARIA]", "[MX_RFC_TAX_ID]", "[BBVA_ACCOUNT_NUMBER]")`.

1. **Protección de Códigos Técnicos (`ref: 3702:65c5:9xhchi`) y Tokens Existentes:**

* Antes de evaluar expresiones regulares locales (o antes de enviar a DLP si se usa pre-enmascarado con nonce único por lote), identificar exclusivamente el fragmento que coincida con `r"ref\s*:\s*\d{4}\s*:\s*[a-zA-Z0-9]+\s*:\s*[a-zA-Z0-9]+"` y sustituirlo temporalmente por un placeholder con *nonce* criptográfico por ejecución (`__VOC_DIAG_{nonce}_{idx}__`) que no pueda ser inyectado adversarialmente por un usuario.

* Proteger igualmente tokens `[<INFO_TYPE>]` ya emitidos por Cloud DLP para evitar reemplazos anidados.

1. **Reglas Regex de Segunda Barrera:**

* Reemplazar CLABE (18 dígitos) $\rightarrow$ `[MX_CLABE_BANCARIA]`.

* Reemplazar Tarjeta (16 dígitos con o sin espacios/guiones) $\rightarrow$ `[CREDIT_CARD_NUMBER]`.

* Reemplazar Cuenta BBVA (10 dígitos aislados) $\rightarrow$ `[BBVA_ACCOUNT_NUMBER]`.

* Reemplazar RFC (`\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b`, case-insensitive) $\rightarrow$ `[MX_RFC_TAX_ID]`.

* Reemplazar CURP (18 caracteres alfanuméricos formato oficial) $\rightarrow$ `[MEXICO_CURP_NUMBER]`.

* Reemplazar Email $\rightarrow$ `[EMAIL_ADDRESS]` y Teléfonos de 10 dígitos $\rightarrow$ `[PHONE_NUMBER]`.

* Restaurar los placeholders diagnósticos `ref: 3702...`.

1. **Conteo Exacto de Hallazgos por Fila (`count_pii_tokens_in_row`):**

* Función determinista que cuenta el total de ocurrencias de `DLP_INFO_TYPE_TOKENS` en `titulo_sanitizado`, `texto_sanitizado` y `texto_respuesta_sanitizado` para poblar `pii_findings_count: int` en `SanitizedReviewRecord`.

#### Tarea 4.2.2: Empaquetador por Filas y Bytes (`DlpRowBatchPacker`) y `BatchCloudDlpDeidentifyDoFn`

1. **Límite Dual de Lote (Filas $\le 250$ y Payload Serializado $\le 400\text{ KB}$):**

* Cloud DLP impone un límite estricto de `524,288 bytes` (0.5 MB) por request de `deidentify_content`.

* Implementar un empaquetador que divida cualquier lote de `RawReviewEnvelope` en sub-lotes que no superen **250 filas** ni **400 KB** de bytes UTF-8 acumulados, aceptando lotes menores en el último tramo.

1. **Alineación Posicional Sidecar (Prohibido enviar `id_resena` o `event_id` como celda transformable a DLP):**

* La `dlp_v2.Table` enviada a `dlp_client.deidentify_content` debe contener **únicamente las 3 columnas de texto libre**: `["titulo", "texto", "texto_respuesta"]`.

* Los identificadores (`event_id`, `id_resena`, `source_revision`) se conservan en una lista *sidecar* en memoria indexada por posición `0..N-1`.

* Al recibir `response.item.table.rows`, validar estrictamente que `len(response.item.table.rows) == len(sidecar)` y que cada fila tenga exactamente 3 celdas; si hay desalineación, lanzar error explícito (*fail-closed*).

1. **Política *Fail-Closed* y Reintentos en Cloud DLP:**

* En producción (`use_cloud_dlp_api=True`), si `dlp_inspect_template_id` o `dlp_deidentify_template_id` son `None` o inválidos, fallar inmediatamente en `setup()`.

* Ante errores transitorios de DLP (`429 ResourceExhausted`, `503 ServiceUnavailable`, `504 DeadlineExceeded`), reintentar con backoff exponencial acotado (`tenacity`). Si el lote falla tras agotar reintentos, emitir los eventos por la salida `OUTPUT_TAG_RETRYABLE_ERROR` para que **no** se haga `ack` en Pub/Sub ni se escriba en BigQuery.

1. **Construcción de `SanitizedReviewEnvelope` y Salidas Tipadas (`TaggedOutputs`):**

* Tras obtener las celdas sanitizadas por Cloud DLP y pasar la segunda barrera de `LocalRegexFallbackSanitizer`:

* Limpiar el texto con `limpiar_texto_bancario(texto_sanitizado)` y evaluar `cumple_umbral_palabras(texto_limpio)` (rango `[2, 60]` palabras de Feature 1.2).

* **Si está fuera del rango `[2, 60]` palabras:** Emitir en `OUTPUT_TAG_FILTERED_LENGTH` un `ProcessingReceipt.from_event(envelope, status="FILTERED_LENGTH", ...)` (sin cuerpo crudo).

* **Si cumple el rango `[2, 60]` palabras:** Construir `SanitizedReviewRecord.from_raw_and_dlp(...)` (que hashea `usuario` con `user_hash_salt`, descarta `imagen_usuario` y verifica `conteo_palabras`), envolverlo en `SanitizedReviewEnvelope` conservando `event_id`, `page_id`, `plan_id`, `stream_id` y `source_revision`, y emitirlo en la salida principal `OUTPUT_TAG_SANITIZED_VALID`.

* **Si el registro de entrada viola contratos de forma irrecuperable:** Emitir `ProcessingReceipt.from_event(envelope, status="QUARANTINED", ...)` en `OUTPUT_TAG_QUARANTINED`.

---

### FEATURE 4.3: Persistencia Idempotente en BigQuery TDS y Ledger de Recibos (`bq_writer.py`, `processing_ledger.py`)

**Objetivo:** Persistir los lotes de `SanitizedReviewEnvelope` en `bbva_voc_tds.sanitized_reviews_tds` mediante cargas batch y `MERGE` determinista, y escribir los recibos `ProcessingReceipt` en Cloud Storage respetando el layout de `EPIC-2`/`EPIC-3`.

#### Tarea 4.3.1: Implementar `BigQueryTdsUpsertManager` en `bq_writer.py`

1. **Serialización Estricta de las 16 Columnas (`record_to_bq_row`):**

* Convierte `envelope.record` (`SanitizedReviewRecord`) a diccionario JSON compatible con las 16 columnas de `bbva_voc_tds.sanitized_reviews_tds`, formateando `fecha`, `fecha_respuesta` y `sanitized_at` en UTC ISO-8601.

1. **Deduplicación en Lote y Tabla Efímera con Expiración:**

* Antes de subir a BigQuery, deduplicar en memoria por `(bank_id, id_resena)` conservando la observación más reciente en caso de que el mismo microbatch traiga dos entregas del mismo registro.

* Crear una tabla temporal `bbva_voc_tds._staging_sanitized_{run_id}_{batch_seq}` con el mismo `schema` de 16 columnas y `expires = datetime.now(timezone.utc) + timedelta(hours=1)`.

* Cargar el lote sanitizado mediante `bq_client.load_table_from_json(..., job_id=f"voc_load_{deterministic_batch_hash}")` y esperar `.result()`.

1. **Sentencia `MERGE` Idempotente sin Reversión Temporal:**

* Ejecutar `MERGE INTO` hacia `bbva_voc_tds.sanitized_reviews_tds` (`target`) desde la tabla temporal (`source`) con clave `ON target.bank_id = source.bank_id AND target.id_resena = source.id_resena`:
* `WHEN MATCHED AND source.fecha >= target.fecha THEN UPDATE SET ...` (protege contra replays antiguos para que nunca sobrescriban una edición más reciente de la reseña).

* `WHEN NOT MATCHED THEN INSERT ...`

* Esperar `query_job.result()`, verificar `query_job.errors is None`, eliminar la tabla temporal en un bloque `finally` y devolver el `query_job.job_id` para estamparlo en los `ProcessingReceipt` (`TDS_COMMITTED`).

#### Tarea 4.3.2: Implementar `ProcessingLedgerRepository` en `processing_ledger.py`

Utilizar `IngestionStorageLayout` y los modelos de `voc_common` (Features 1.6–1.8 y 2.7):

1. **`write_event_receipts(self, receipts: list[ProcessingReceipt]) -> None`**:

* Persiste en Cloud Storage los recibos terminales (`TDS_COMMITTED`, `FILTERED_LENGTH`, `QUARANTINED`) bajo el prefijo de recibos configurado en `Settings`.

1. **`find_already_processed_event_ids(self, event_ids: set[str]) -> dict[str, ProcessingReceipt]`**:

* Permite que al recibir un *redelivery* de Pub/Sub (por ejemplo, si falló el `ack` en una corrida previa después de haber hecho commit en BigQuery), el orquestador detecte que el `event_id` ya tiene un recibo terminal `TDS_COMMITTED` o `FILTERED_LENGTH` y haga `ack` inmediato sin volver a invocar Cloud DLP ni BigQuery.

1. **`reconcile_page_sanitization_status(self, bank_id: BankKey, page_id: str) -> bool`**:

* Comprueba contra el `PageManifest` escrito por `EPIC-3` (Feature 3.3) si todos los `event_id` válidos de esa página ya cuentan con un recibo terminal (`TDS_COMMITTED` o `FILTERED_LENGTH`).

* Cuando la página está completa, emite el recibo de cierre de página para que el estado pase de `PUBLISHED` a `SANITIZED_COMMITTED` sin sobrescribir el watermark del scraper. Si existen eventos en `QUARANTINED` o el archivo en `raw_staging/` expiró tras los 7 días de TTL antes de procesarse, registra explícitamente el hueco de calidad/cobertura.

---

### FEATURE 4.4: Orquestador del Pipeline, Renovación de Lease de Ack y Replay desde GCS (`pipeline.py`, `Dockerfile`)

**Objetivo:** Coordinar el ciclo completo de drenado por microbatches desde Pub/Sub (o desde manifiestos en GCS), manteniendo vivo el *ack deadline* durante la ejecución de DLP + BigQuery y confirmando mensajes únicamente tras persistencia duradera.

#### Tarea 4.4.1: Implementar `services/sanitization-pipeline/src/sanitization_pipeline/pipeline.py`

1. **Drenado Acotado y Agrupación de `ack_ids` por `event_id`:**

* En modo `BATCH_PULL_SERVERLESS`, solicitar hasta `--microbatch-size` mensajes de `voc-raw-reviews-sub`.

* Parsear cada mensaje como `RawReviewEnvelope`.

* **Deduplicación con preservación de `ack_ids`:** Si el mismo `event_id` llega duplicado en el lote de Pub/Sub (por reintento de publicación o redelivery), agrupar en un diccionario `ack_ids_by_event_id: dict[str, list[str]]` para que al terminar el procesamiento de ese único `RawReviewEnvelope`, se envíe `acknowledge()` a **todos** los `ack_id` asociados a ese `event_id`.

* Consultar primero `ledger.find_already_processed_event_ids(...)`: si algún `event_id` ya fue procesado en una corrida previa, hacer `ack` inmediato de sus `ack_ids` y excluirlo del lote de Cloud DLP.

1. **Renovación Periódica de Lease de Ack (`AckDeadlineRenewer`):**

* La suscripción `voc-raw-reviews-sub` tiene `ack_deadline_seconds=600` y el Job puede correr hasta `1800s`.

* Iniciar un hilo/tarea de background mientras dura el procesamiento del microbatch que invoque `subscriber.modify_ack_deadline(subscription=..., ack_ids=active_ack_ids, ack_deadline_seconds=600)` cada 180 segundos hasta que el lote termine.

1. **Ejecución del Grafo Apache Beam (`DirectRunner`) y Orden de Confirmación:**

* Ejecutar el pipeline sobre el microbatch con `BatchCloudDlpDeidentifyDoFn`.

* **Orden transaccional estricto post-Beam:**

1. Ejecutar `bq_writer.upsert_sanitized_batch(sanitized_valid_envelopes)` hacia `bbva_voc_tds.sanitized_reviews_tds`.

2. Construir los `ProcessingReceipt` para `TDS_COMMITTED`, `FILTERED_LENGTH` y `QUARANTINED` y persistirlos en GCS con `ledger.write_event_receipts(...)`.

3. Reconciliar el estado de las páginas tocadas (`ledger.reconcile_page_sanitization_status`).

4. **Solo si los pasos 1 y 2 tuvieron éxito**, enviar `subscriber.acknowledge()` para los `ack_ids` de los eventos con estado terminal (`TDS_COMMITTED`, `FILTERED_LENGTH`, `QUARANTINED`).

5. Para cualquier evento en `RETRYABLE_ERROR` (o si falló BigQuery/DLP), **no enviar `ack**`, liberando los mensajes para reintento seguro.

6. **Modo Replay desde Manifiestos en GCS (`GCS_BACKFILL_MANIFESTS`):**

* En lugar de hacer glob ciego sobre `raw_staging/`, lee los `PageManifest` en estado `PUBLISHED` cuyos eventos aún no tengan recibo terminal en `processing_ledger`, verifica la generación del archivo `.jsonl.gz` en `raw_staging/{bank_id}/{run_id}/{page_id}/{fetch_attempt_id}.jsonl.gz` (Feature 3.3), y los procesa por la misma tubería de DLP + BigQuery + Recibos. Si el objeto `.jsonl.gz` ya fue eliminado por la regla de Lifecycle de 7 días antes de sanitizarse, marca explícitamente el hueco en el ledger de la página (`STAGING_EXPIRED_GAP`).

#### Tarea 4.4.2: Implementar `services/sanitization-pipeline/Dockerfile`

Construir un `Dockerfile` multi-stage con `ghcr.io/astral-sh/uv:python3.11-bookworm-slim`, usuario no-root (`appuser`), instalando `voc-common` y `sanitization-pipeline` desde `uv.lock` y definiendo `ENTRYPOINT ["python", "-m", "sanitization_pipeline.pipeline"]`.

---

### FEATURE 4.5: Suite de Pruebas Deterministas y Observabilidad (`tests/`)

**Objetivo:** Validar con `pytest` y `apache_beam.testing.test_pipeline.TestPipeline` (sin red ni credenciales GCP en CI) todos los invariantes de privacidad, empaquetado DLP, idempotencia en BigQuery y manejo de leases de Pub/Sub.

#### Tarea 4.5.1: Implementar `test_dlp_transforms.py`, `test_bq_writer_and_ledger.py` y `test_pipeline.py`

La suite de pruebas debe cubrir obligatoriamente estos 9 escenarios:

1. **Cero Fugas en Corpus Bancario Anotado y Conteo Exacto de Hallazgos:**

* Inyectar reseñas con nombres propios, CLABE (18 dígitos), tarjetas (16 dígitos), cuentas BBVA (10 dígitos), RFC, CURP, correos, teléfonos y emojis en `titulo`, `texto` y `texto_respuesta`.

* Verificar que `SanitizedReviewRecord` no contenga ningún PII original, que `usuario_hash` sea un SHA-256 de 64 caracteres, y que `pii_findings_count` coincida exactamente con el número de tokens `[<INFO_TYPE>]` insertados en la fila.

1. **Preservación de Diagnósticos `ref: 3702` con PII Adyacente e Inyección Adversarial:**

* Probar `"mi cuenta 0123456789 marca error ref: 3702:65c5:9xhchi al llamar al 5512345678"`. Comprobar que `0123456789` y `5512345678` se enmascaran como `[BBVA_ACCOUNT_NUMBER]` y `[PHONE_NUMBER]`, mientras que `ref: 3702:65c5:9xhchi` permanece intacto en `texto_limpio`. Comprobar que si un usuario escribe un falso placeholder en su reseña, no logra evadir la sanitización.

1. **Empaquetado Dual (>250 filas y >400 KB) y Protección Sidecar de IDs:**

* Verificar que un lote que supere 400 KB o 250 filas se divida automáticamente en múltiples llamadas a `deidentify_content`, y que `id_resena` y `event_id` jamás se envíen dentro de `dlp_v2.Table`.

1. **Política *Fail-Closed* ante Error o Desalineación de Cloud DLP:**

* Simular que Cloud DLP devuelve menos filas que el sidecar o lanza `PermissionDenied`/`ServiceUnavailable`. Verificar que no se emita ningún `SanitizedReviewEnvelope` usando solo regex cuando `use_cloud_dlp_api=True`.

1. **Bordes Exactos del EDA (1, 2, 60 y 61 palabras) post-sanitización:**

* Comprobar que longitudes de 1 y 61 palabras tras la sanitización generen `ProcessingReceipt(status="FILTERED_LENGTH")` y que longitudes de 2 y 60 palabras generen `SanitizedReviewEnvelope` válidos.

1. **Agrupación de `ack_ids` en Redeliveries e Idempotencia por Recibo Previo:**

* Simular que el mismo `RawReviewEnvelope` (`event_id="evt_1"`) llega 2 veces en el mismo Pull con `ack_id="a1"` y `ack_id="a2"`. Verificar que se procesa una sola vez en DLP/BigQuery y que al confirmar se hace `ack` de `["a1", "a2"]`.

* Simular que `evt_1` llega de nuevo en una corrida posterior cuando ya existe su `ProcessingReceipt(status="TDS_COMMITTED")` en GCS: verificar que se hace `ack` inmediato sin llamar a DLP ni a BigQuery.

1. **Atomicidad BigQuery $\rightarrow$ Ledger $\rightarrow$ Ack:**

* Si falla el `MERGE` en BigQuery, verificar que **no** se llame a `subscriber.acknowledge()`.

* Verificar que la tabla temporal `_staging_sanitized_*` siempre se elimine en el bloque `finally` y que el `MERGE` no sobrescriba una fila existente si el replay trae una `fecha` más antigua.

1. **Renovación de Lease de Ack (>600s):**

* Verificar mediante mock de reloj/timer que `AckDeadlineRenewer` invoca `modify_ack_deadline` periódicamente mientras el microbatch sigue en ejecución.

1. **Reconciliación de Página (`PUBLISHED` $\rightarrow$ `SANITIZED_COMMITTED`) y Detección de Expiración de Staging:**

* Verificar que cuando todos los eventos de un `PageManifest` tienen recibos `TDS_COMMITTED` o `FILTERED_LENGTH`, la página se marca como completada en el ledger de procesamiento; y si un archivo `.jsonl.gz` en `raw_staging/` ya expiró (404 NotFound tras 7 días), se registra el hueco explícito `STAGING_EXPIRED_GAP`.

---

## ✅ Checklist de Aceptación de la Épica 4

* [ ] Consume `RawReviewEnvelope` y emite `SanitizedReviewEnvelope` y `ProcessingReceipt` de `voc-common` sin duplicar contratos ni alterar las 16 columnas de `bbva_voc_tds.sanitized_reviews_tds`.

* [ ] Calcula `pii_findings_count: int` (`>= 0`) contando los tokens `[<INFO_TYPE>]` por fila, cumpliendo el contrato `INTEGER REQUIRED` de BigQuery.

* [ ] Empaqueta peticiones tabulares a Cloud DLP respetando simultáneamente $\le 250$ filas y $\le 400\text{ KB}$, manteniendo `id_resena` en un sidecar fuera de la tabla DLP.

* [ ] Opera en modo *fail-closed* en producción (`use_cloud_dlp_api=True`): jamás escribe en TDS usando solo regex si Cloud DLP falla.

* [ ] Carga lotes sanitizados en tablas temporales con TTL de 1 hora dentro de `bbva_voc_tds` y ejecuta `MERGE` idempotente sin usar *Streaming Inserts*.

* [ ] Gestiona cuarentena en GCS (acorde a los permisos IAM de `voc-sa-sanitization`), renueva leases de ack y confirma mensajes en Pub/Sub únicamente después de persistir en BigQuery y en el ledger de recibos.

* [ ] Los comandos `uv run ruff check services/sanitization-pipeline`, `uv run ruff format --check services/sanitization-pipeline`, `uv run pyrefly check`, `uv run bandit -c pyproject.toml -r services/sanitization-pipeline` y `uv run pytest services/sanitization-pipeline/tests --cov=services/sanitization-pipeline/src --cov-fail-under=85` pasan con **0 errores**.
