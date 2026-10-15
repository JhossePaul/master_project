# sanitization-pipeline

EPIC-4: sanitización PII con Cloud DLP y segunda barrera regex, persistencia
idempotente en `bbva_voc_tds.sanitized_reviews_tds` y recibos de
procesamiento en GCS. Especificación y límites en
[EPIC-4](../../docs/backlog/epic_4.md).

Estado: feature 4.1 (paquete, configuración, preflight y CLI). Los modos de
ejecución se registran en 4.4; hasta entonces el Job termina con código 70
sin hacer pull ni escribir en ningún destino.

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

Códigos de salida: 0 éxito, 64 configuración inválida, 70 modo no
implementado, 75 fallo transitorio (mensajes sin `ack`, desde 4.4).
