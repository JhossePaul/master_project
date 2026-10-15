# sanitization-pipeline

EPIC-4: sanitización PII con Cloud DLP y segunda barrera regex, persistencia
idempotente en `bbva_voc_tds.sanitized_reviews_tds` y recibos de
procesamiento en GCS. Especificación y límites en
[EPIC-4](../../docs/backlog/epic_4.md).

Estado: features 4.1 (paquete, configuración, preflight y CLI), 4.2
(desidentificación DLP, segunda barrera regex, conteo de hallazgos, filtro EDA
y `DoFn`), 4.3 (upsert TDS, recibos y cierre de página) y 4.4 (orquestador,
renovación de ack, replay desde manifiestos e imagen).

Desde la raíz:

```sh
uv sync --all-packages --locked --python 3.11
uv run --frozen pytest services/sanitization-pipeline/tests --cov=sanitization_pipeline --cov-fail-under=85
```

## Dependencias

Apache Beam núcleo con `DirectRunner` (decisión D3). El extra `[gcp]` no se
declara: uv resuelve todos los extras en `uv.lock` y ese extra cambia
versiones compartidas del workspace; se añadirá al aprovisionar Dataflow.
Al importar Beam sin ese extra aparece un aviso sobre `apitools`; es esperado.
`DirectRunner` de Beam 2.77 intenta primero Prism, que descarga un binario en
tiempo de ejecución; el Job y las pruebas usan `in_process_runner()`
(`FnApiRunner` en proceso), sin red ni binarios externos.
`ingestion-worker` se usa solo para leer el estado de la ingesta (decisión D2):
nunca adquiere lease ni escribe en la raíz o en manifiestos.

## Configuración

El Job de Cloud Run no recibe argumentos, así que los defaults son válidos en
producción. Precedencia: default < variable `SANITIZATION_<CAMPO>` < flag.

| Campo / flag | Default | Regla |
| --- | --- | --- |
| `--execution-mode` | `BATCH_PULL_SERVERLESS` | `GCS_BACKFILL_MANIFESTS`; `DATAFLOW_MANAGED` se rechaza sin Dataflow aprovisionado |
| `--max-messages` | 2000 | Presupuesto por corrida |
| `--microbatch-size` | 200 | `<= max_messages` |
| `--max-runtime-sec` / `--checkpoint-margin-sec` | 1500 / 300 | Suma `<= --container-timeout-sec` (1800, igual al Job) |
| `--ack-deadline-sec` / `--ack-renew-interval-sec` | 600 / 180 | Renovación antes del vencimiento; máximo de Pub/Sub 600 |
| `--dlp-max-rows` / `--dlp-max-bytes` | 250 / 400000 | Bytes por debajo del límite DLP de 524288 |
| `--[no-]use-cloud-dlp-api` | activado | Desactivado solo offline; prohibido en producción |

Preflight (*fail-closed*, antes de cualquier pull): `INGESTION_V2_ENABLED`,
`BEAM_RUNNER=DirectRunner`, y plantillas `DLP_INSPECT_TEMPLATE_ID` /
`DLP_DEIDENTIFY_TEMPLATE_ID` con nombre completo dentro de
`projects/{GCP_PROJECT_ID}/locations/{GCP_REGION}` (son regionales).

Códigos de salida: 0 sin pendientes, 64 configuración inválida (incluido un
rechazo de permisos o plantillas DLP), 70 modo sin registrar, 75 eventos
devueltos o fallo transitorio (mensajes sin `ack`).

## Desidentificación (4.2)

```python
from sanitization_pipeline.dlp_transforms import BatchSanitizer, CloudDlpDeidentifier

deidentifier = CloudDlpDeidentifier(
    dlp_client, parent=parent,
    inspect_template=settings.dlp_inspect_template_id,
    deidentify_template=settings.dlp_deidentify_template_id,
)
result = BatchSanitizer(
    user_hash_salt=settings.user_hash_salt, deidentifier=deidentifier
).sanitize(envelopes)
# result.valid / filtered / quarantined / retryable
```

* A Cloud DLP solo viajan `texto` y `texto_respuesta` (tabla de 2 columnas);
  los identificadores quedan en un *sidecar* posicional. Un título no nulo se
  pone en cuarentena (`UNEXPECTED_TITLE`), porque el contrato lo copiaría sin
  sanitizar.
* Sub-lotes de ≤250 filas y ≤400 KB de texto; una fila mayor va a cuarentena
  (`DLP_ROW_TOO_LARGE`).
* `pii_findings_count` = tokens `[<INFO_TYPE>]` introducidos (los literales que
  el usuario ya escribió no cuentan).
* Fuera de [2, 60] palabras tras limpiar: recibo `FILTERED_LENGTH`.
* DLP caído o respuesta desalineada: recibos `RETRYABLE_ERROR` y ningún sobre
  válido; errores de permisos/plantillas detienen la corrida.

## Persistencia y recibos (4.3)

```python
commit = BigQueryTdsUpsertManager(
    bq_client, project=settings.gcp_project_id, dataset=settings.bq_dataset_id
).upsert_sanitized_batch(result.valid)
ledger.write_event_receipts(
    tds_committed_receipts(result.valid, commit.job_ids, now)
    + result.filtered + result.quarantined
)
ledger.reconcile_page(bank, stream_id, page_id)  # RESOLVED / GAPS_DETECTED / PENDING
```

* `MERGE` hacia las 17 columnas ordenado por `(fecha, source_observed_at)`;
  una fila por reseña en cada lote. Tabla temporal con TTL de 1 h, borrada al
  terminar; job IDs con prefijo (nunca deterministas).
* Recibos en `GCS_PROCESSING_RECEIPTS_PREFIX`: `{bank}/{page_id}/{event_id}.json`,
  índice `{bank}/_events/{event_id}.json` y cierre `{bank}/_pages/{page_id}.json`.
  Escritura condicional: el primer recibo terminal gana.
* El estado de la ingesta solo se lee (`WatermarkRepository.load`,
  `find_page`, `iter_ledger`); nunca se adquiere lease ni se escribe la raíz.

## Orquestación e imagen (4.4)

| Modo | Fuente | Confirmación |
| --- | --- | --- |
| `BATCH_PULL_SERVERLESS` (default) | Pull síncrono de `PUBSUB_RAW_SUBSCRIPTION` en microbatches | `ack` de terminales tras `MERGE` y recibos; `nack` de reintentables |
| `GCS_BACKFILL_MANIFESTS` | Páginas comprometidas sin cierre, desde su captura (URI + generación) | Sin Pub/Sub; captura expirada => cierre `STAGING_EXPIRED` |

Por microbatch: deduplicar por `event_id` (todos los `ack_ids`), confirmar lo
ya resuelto copiando el recibo a la página nueva, DLP en Beam (`FnApiRunner` en
proceso), `MERGE`, recibos, `ack`, cierre de páginas. Mientras tanto, un hilo
renueva el deadline cada 180 s. Los mensajes que no se pueden interpretar o
cuyos atributos no coinciden se confirman y solo se registra su `message_id`.

```sh
docker build -f services/sanitization-pipeline/Dockerfile -t sanitization-pipeline .
docker run --rm sanitization-pipeline                     # preflight + modo default
docker run --rm sanitization-pipeline --execution-mode GCS_BACKFILL_MANIFESTS
```

La imagen pesa ~650 MB (Beam, pyarrow, numpy). `cloudbuild.yaml` la publica
por SHA cuando el Dockerfile deja de estar vacío.
