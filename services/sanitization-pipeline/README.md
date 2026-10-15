# sanitization-pipeline

EPIC-4: sanitización PII por regex local (Cloud DLP opcional), persistencia
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
| `--[no-]use-cloud-dlp-api` | desactivado | Activa Cloud DLP como capa previa a la regex (entorno corporativo); desactivado = solo regex local |

Preflight (*fail-closed*, antes de cualquier pull): `INGESTION_V2_ENABLED` y
`BEAM_RUNNER=DirectRunner`. Con `--use-cloud-dlp-api` exige además plantillas
`DLP_INSPECT_TEMPLATE_ID` / `DLP_DEIDENTIFY_TEMPLATE_ID` con nombre completo
dentro de `projects/{GCP_PROJECT_ID}/locations/{GCP_REGION}` (son regionales).

## Política de sanitización (decisión basada en datos)

Solo el texto de la reseña llega al TDS. Se tomó el 2026-10-15 con una
medición sobre las capturas de `evidence/` (798 reseñas únicas de BBVA,
parseadas con el adaptador del proyecto; muestra no aleatoria, mediana de 4
palabras, 133 reseñas con ≥20 palabras y 63 con ≥40):

| Medición | Resultado |
| --- | --- |
| Tokens de PII que introduce la regex local en el texto del usuario | 0 de 798 |
| Presentaciones ("me llamo…") y cierres con nombre; URLs, @usuarios | 0 |
| Nombre de usuario dentro de su propio texto | 2 (0.3 %) |
| Respuestas de la entidad que contienen el nombre de pila del autor | 249 de 302 (82.5 %) |

Con 0 de 798, la tasa de lo que la regex detecta queda por debajo de ~0.4 %
(regla del tres, 95 %); en reseñas largas (≥40 palabras) la cota es de ~5 %.
Consecuencias:

* **La respuesta de la entidad y el título se descartan** antes de sanitizar
  y nunca se persisten (`titulo`, `texto_respuesta_sanitizado` y
  `fecha_respuesta` quedan en `NULL`); ya no van a Cloud DLP ni se
  ponen en cuarentena (se retiró `UNEXPECTED_TITLE`). El sobre crudo en Pub/Sub
  y en `raw_staging/` (TTL de 7 días) sigue trayéndolos hasta que la ingesta los
  deje de capturar.
* **Por defecto solo regex local** (`LocalRegexFallbackSanitizer`: correo,
  CLABE, CURP, tarjeta, RFC, teléfono y cuenta). No hay llamada a Cloud DLP, ni
  costo, ni fallo externo que reintentar.
* **Riesgo residual:** nombres propios dentro del texto libre, que una regex no
  detecta. No aparecieron en la muestra, pero eso no demuestra su ausencia; va
  como modo de falla en la Matriz Ethical FMEA. Cloud DLP sigue disponible
  (`--use-cloud-dlp-api`) para un entorno que lo requiera, con la política
  *fail-closed* descrita abajo.
* `usuario_hash` se conserva (SHA-256 salado); `usuario` e `imagen_usuario` no
  existen en el contrato curado.

Códigos de salida: 0 sin pendientes, 64 configuración inválida (incluido un
rechazo de permisos o plantillas DLP), 70 modo sin registrar, 75 eventos
devueltos o fallo transitorio (mensajes sin `ack`).

## Desidentificación (4.2)

El ejemplo muestra el modo opcional con Cloud DLP; el modo por defecto es
`BatchSanitizer(user_hash_salt=...)` sin `deidentifier`.

```python
from sanitization_pipeline.dlp_transforms import BatchSanitizer, CloudDlpDeidentifier

deidentifier = CloudDlpDeidentifier(
    dlp_client, parent=parent,
    inspect_template=settings.dlp_inspect_template_id,
    deidentify_template=settings.dlp_deidentify_template_id,
)
result = BatchSanitizer(
    user_hash_salt=settings.user_hash_salt,
    deidentifier=deidentifier,
    use_cloud_dlp_api=True,
).sanitize(envelopes)
# result.valid / filtered / quarantined / retryable
```

* En modo Cloud DLP solo viaja `texto` (tabla de 2 columnas, con la segunda
  vacía); los identificadores quedan en un *sidecar* posicional.
* Sub-lotes de ≤250 filas y ≤400 KB de texto; una fila mayor va a cuarentena
  (`DLP_ROW_TOO_LARGE`).
* `pii_findings_count` = tokens `[<INFO_TYPE>]` introducidos (los literales que
  el usuario ya escribió no cuentan).
* Fuera de [2, 60] palabras tras limpiar: recibo `FILTERED_LENGTH`.
* Modo Cloud DLP: DLP caído o respuesta desalineada producen recibos
  `RETRYABLE_ERROR` y ningún sobre válido; errores de permisos/plantillas
  detienen la corrida.

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
