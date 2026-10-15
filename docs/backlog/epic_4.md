# EPIC-4: Sanitización PII, Persistencia Idempotente y Cobertura TDS

* **Estado:** Pendiente. Especificación revisada el 2026-10-14.
* **Dependencias:** EPIC-1, EPIC-2 y contratos v2/manifestación de páginas de EPIC-3.
* **Directorios:** `services/sanitization-pipeline/`, `packages/voc-common/`, `infra/`.
* **Archivos:** pyproject, Dockerfile, `dlp_transforms.py`, `bq_writer.py`,
  `pipeline.py`, `processing_ledger.py` y tests de transformación/persistencia/acks.

## Objetivo y límites

Consumir páginas/eventos duraderos de EPIC-3, sanitizar antes de escribir en TDS,
filtrar el rango EDA 2–60 palabras, conservar revisiones y confirmar exactamente
qué eventos terminaron en TDS, fueron filtrados o quedaron pendientes/cuarentenados.
No existe tabla BigQuery de texto crudo. El nombre TDS describe el destino técnico:
no implica certificación corporativa automática.

«Cero fugas en el corpus de prueba» es un criterio de aceptación medible; ningún
NER/regex demuestra detección del 100% de PII real. Medir recall por tipo, corpus
anotado y fallos adversariales. El modo de regex local no sustituye NER en producción.
La ejecución serverless reduce cómputo ocioso; no garantiza costo cero. Medir bytes
DLP, solicitudes, almacenamiento, bytes de consultas/MERGE y reintentos.

## Contratos y estados compartidos con EPIC-3

* Mensajes: `event_id`, `page_id`, `plan_id`, `stream_id`, banco, ID de reseña y
  `source_revision`, más `RawReviewEvent`. La revisión se deriva del contenido
  del origen, no de `ingested_at`; todas las fechas UTC.
* `ProcessingReceipt`: identificador, revisión, estado, página, digest del resultado,
  referencias de job BQ, error codificado, `processed_at`; sin contenido crudo.
* Estados: `PENDING`, `PROCESSING`, `TDS_COMMITTED`, `FILTERED_LENGTH`,
  `QUARANTINED`, `RETRYABLE_ERROR`. `ACKED` es confirmación de transporte posterior,
  no sinónimo de escritura exitosa. Contadores por página deben reconciliarse.
* Una página `PUBLISHED` no cierra cobertura TDS. Emitir recepción de destino
  idempotente solo cuando todas sus revisiones tienen resultado duradero.
  Cuarentena se informa como hueco de calidad, no como dato exitoso en TDS.
* La cobertura histórica y la revisión incremental comparten clave estable y
  ledger. FULL reutiliza las revisiones ya procesadas del BACKFILL anual.
* Cambios de infra/contratos pendientes: ledger de eventos/recepciones y dataset
  de trabajo con expiración de tablas sanitizadas; modelo de revisiones (abajo).
  No implementar contra tablas/campos que todavía no se hayan aprovisionado.

## FEATURE 4.1: Paquete, runners y presupuestos

Workspace `sanitization-pipeline`, Python >=3.11, hatchling y `voc-common` de
workspace. Dependencias Apache Beam GCP, google-cloud-dlp/pubsub/bigquery/storage
y Pydantic v2, con versiones resueltas/probadas mediante uv. El lock común debe
verificar compatibilidad Beam/Pulumi/protobuf; si hay conflicto, aislar entornos
por grupo/servicio de forma explícita en CI y Docker, no ignorar el resolver.

CLI:

* `--execution-mode`: `BATCH_PULL_SERVERLESS` (default), `GCS_BACKFILL_FILES`,
  `DATAFLOW_MANAGED`.
* `--max-messages=5000` es presupuesto, no instrucción de cargar todo en memoria.
  Añadir límites de bytes, microbatch, tiempo y concurrencia; salir antes de 1800s.
* `--gcs-input-pattern` requiere selección de manifiestos/generaciones, no solo
  glob que reprocesa indefinidamente todo el staging.
* DirectRunner se ejecuta dentro del Job; Dataflow es un modo posterior opt-in.
  Migración de infra pendiente: identidad/roles Dataflow, APIs y staging separados.
  El flag de Vertex actual no es la interfaz correcta para activar Dataflow.
* `BEAM_RUNNER=DirectRunner` y CLI/default deben ser consistentes con infra. Un
  Runner no transforma por sí solo una fuente streaming en un pipeline acotado.

## FEATURE 4.2: DLP tabular, diagnóstico técnico y fail-closed

### Sanitizador local

`LocalRegexFallbackSanitizer.sanitize(text) -> tuple[str, int]` cubre CLABE,
cuentas, tarjetas, RFC, CURP, correos y teléfonos; nombres libres requieren NER.
Probar separadores, Unicode y bordes RE2/Python; no asumir que sus `\b` son
idénticos. Proteger tokens ya sanitizados para evitar reemplazos anidados.

La protección de códigos `ref: 3702:65c5:9xhchi` usa una tabla de placeholders
por celda, con nonce/colisión comprobada, o la regla DLP validada. Solo se excluye
el fragmento diagnóstico reconocido, no el resto de la oración. Restaurar después
de DLP/fallback y comprobar que PII adyacente no queda excluida. No permitir que
texto parecido a un placeholder o a un token sintético evite la inspección.

Regex local es doble barrera después de DLP o herramienta offline explícita.
Si DLP no está disponible en producción, **no escribir éxito TDS usando solo
regex**. Reintentar/acotar/cuarentenar de forma duradera según tipo de fallo.

### `BatchCloudDlpDeidentifyDoFn`

Cliente creado una vez en `setup`; modelos Pydantic compartidos. Salidas
`sanitized_valid`, `filtered_heavy_tail`, `dlq_error` tipadas con referencias de evento.

1. BatchElements propone lotes, pero un empaquetador final limita **filas y bytes**:
   hasta 250 filas y presupuesto configurable por debajo de 0.5 MB (p.ej. 400 KB),
   medido serializando el request protobuf completo con plantillas y overhead.
   Aceptar lotes menores de 50 en el último tramo; dividir/reintentar por tamaño.
2. La tabla enviada a DLP contiene columnas de contenido `texto`,
   `texto_respuesta` y `titulo` cuando exista. **No enviar `id_resena` a un
   transformador de todos los campos**. Mantener un sidecar posicional con IDs;
   validar número de filas, columnas y alineación al recibir la respuesta.
3. Plantillas regionales de EPIC-2, `include_quote=False`, tokens `[INFO_TYPE]`
   mediante los reemplazos explícitos existentes. Proteger diagnósticos y aplicar
   regex adicional sobre todas las celdas textuales que puedan persistir.
4. Hash del usuario con sal secreta versionada; no persistir usuario/imagen.
   Sanitizar también título/respuesta; ampliar `from_raw_and_dlp` para recibir
   título sanitizado o fijarlo a None en Google Play. No copiar campos crudos.
5. `pii_findings_count` por reseña requiere correspondencia comprobable de
   transformación/celda. Los summaries globales del lote **no** se reparten como
   si fueran un conteo por fila. Si la API no da esa correspondencia, definir
   explícitamente `None`/métrica agregada y migrar contrato/esquema, o implementar
   una atribución validada; no hacer RPC por fila solo para fabricar ese conteo.
6. Aplicar limpieza y filtrar 2–60 palabras después de sanitizar. Emitir recepción
   `FILTERED_LENGTH` con ID, conteo y motivo, sin texto crudo. Es resultado terminal
   para esa revisión, no error de transporte ni garantía de retención del 77.4%.
7. Timeout/429/503 DLP => reintento con backoff y presupuesto; credenciales,
   configuración, respuesta desalineada o resultado incompleto => fallo explícito.
   No emitir registros de éxito cuando el resultado no esté íntegro.

## FEATURE 4.3: BigQuery idempotente, revisiones y ledger

### Identidad y política de cambios

* `record_to_bq_row` usa UTC, enums serializables y schemas versionados.
* Clave de reseña `(bank_id, id_resena)`; clave de revisión
  `(bank_id, id_resena, source_revision)`. Duplicado de transporte != edición.
* Persistir revisiones sanitizadas append-only en una tabla versionada y exponer
  estado vigente mediante vista/tabla materializada controlada. Incorporar
  `source_revision`, `first_seen_at`, `last_seen_at`, `sanitizer_version`,
  `salt_version` y `processing_receipt` mediante migración de infra antes de usar.
* `fecha` del review no se presume timestamp de edición fiable. Para resolver el
  vigente usar observación del origen/orden de captures y criterio documentado;
  replays viejos no deben revertir una revisión reciente. Si es ambiguo,
  conservar ambas observaciones y marcar conflicto, no inventar temporalidad.
* Reprocesar una revisión para mejorar sanitización es otra versión de proceso,
  no nueva revisión del origen; gestionar correcciones/borrado de PII de forma
  explícita. No llamar «inmutable» a una tabla que debe corregir privacidad.

### Carga y MERGE

`BigQueryTdsUpsertManager` recibe un microbatch y devuelve resultados confirmados
por evento. La entrada llega desde el runner mediante una fase/sink implementada:
una `PCollection` no es una lista iterable disponible después de cerrar el pipeline.

1. Cargar únicamente filas **sanitizadas** en tabla de trabajo con expiración;
   `job_id` determinista por lote/tipo/revisión de proceso y reconciliación de
   jobs ya creados. `load_table_from_json`/FILE_LOADS no equivalen a escritura final.
2. Deduplicar fuente por clave de revisión con `ROW_NUMBER` y criterio estable
   antes del MERGE. Evitar dos escritores concurrentes para las mismas claves:
   lease/fencing de procesamiento y serialización de la fase de publicación TDS.
3. MERGE idempotente de revisiones/recepciones. Leer `.result()` y comprobar
   errores del job. Después confirmar ledger; si ledger falla tras BQ, el replay
   verifica la fila/revisión y repara la recepción sin duplicar ni revertir.
4. Si un lote falla no declarar éxito ni enviar ack. No asumir deduplicación
   permanente por `insertId` ni por una ventana Beam.
5. `DATAFLOW_MANAGED` escribe FILE_LOADS a **staging sanitizado**, nunca
   `WRITE_APPEND` directo a TDS. Una fase acotada de commit/merge/dedupe confirma
   destino y recepciones. Hasta implementarla, ese modo no se declara listo.
6. Medir bytes de consulta de MERGE, particiones tocadas y coste. Cargas batch
   evitan cargos de inserción streaming clásicos, pero consultas/almacenamiento
   pueden facturarse. No describir un MERGE o FILE_LOADS como gratis sin límites.

## FEATURE 4.4: Orquestación, leases de ack y replay desde GCS

### Pull acotado

1. Drenar microbatches con límites de cantidad/bytes/tiempo y backpressure. Un Pull
   vacío es evidencia temporal de cola sin mensajes entregados, no certeza de
   que no quedan mensajes en vuelo o backlog. No acumular 5000 textos por default.
2. Mantener/renovar ack deadline durante DLP/Beam/BQ. La suscripción tiene 600s y
   el Job puede durar 1800s: usar lease management o `modify_ack_deadline` periódico.
   Si se pierde el lease, aceptar redelivery y resolver por event_id/ledger.
3. Deduplicar por clave de evento, manteniendo **todos** los ack_ids de redeliveries
   de ese evento; `beam.Distinct()` sobre modelos completos no implementa esto.
4. Ejecutar microbatch como grafo acotado, con empaquetado por bytes, sidecar y
   salidas tipadas. Mantener receipts fuera de memoria efímera para reintentos.
5. Ack solo para eventos `TDS_COMMITTED` o `FILTERED_LENGTH` duraderos.
   En errores transitorios no ack; en permanentes enviar cuarentena controlada
   y confirmar su persistencia antes de ack. No republicar crudos en alertas.
6. Cuarentena debe ser accesible para recuperación, con TTL explícito y metadata
   separada del cuerpo. Alinear esto con la DLQ de EPIC-2 y sus permisos; la tabla
   de auditoría no lleva cuerpo crudo. Si vence el cuerpo pendiente, abrir hueco.
7. Una página finaliza cuando sus eventos/revisiones tienen receipts duraderos.
   Consumidor escribe un receipt de página; ingesta reconcilia el estado raíz
   usando CAS/lease propio. Sanitización no sobrescribe el watermark del scraper.
8. Acks exitosos no se confunden con persistencia: si ack falla tras BQ, redelivery
   consulta receipts y repite ack, sin repetir una transformación innecesaria.

### GCS histórico y deduplicación entre vías

* Seleccionar archivos por manifiesto/generación y usar las mismas claves que
  Pub/Sub. El mismo registro llegado por ambas vías produce una sola revisión
  confirmada; comprobarlo en tests de recuperación.
* JSONL.gz se procesa en lotes acotados; un archivo ya expirado es error observable,
  no «página vacía». No enumerar todo raw_staging cada día como mecanismo de progreso.
* Supervisar edad de eventos/archivos pendientes, backlogs y tiempo de vaciado.
  El TTL actual es siete días: garantizar operación antes de expirar con alertas,
  o cambiar conscientemente retención/presupuesto mediante infra. No conservar
  crudos indefinidamente para reducir coste de recuperación.

### Docker y configuración

Multi-stage uv, usuario no root, ENTRYPOINT `python -m sanitization_pipeline.pipeline`.
CLI, `BEAM_RUNNER`, plantillas DLP, sal versionada y Pub/Sub/GCS deben ser consistentes
con Cloud Run. Entorno offline requiere `use_cloud_dlp_api=False` explícito y no
puede mezclarse con el destino TDS de producción. No registrar texto/sal en errores.

## FEATURE 4.5: Pruebas y observabilidad

Pruebas deterministas con pytest y Beam TestPipeline; fixtures sintéticas,
respuestas DLP simuladas y tests de integración reales opt-in separados de CI.

1. Corpus anotado: nombres, CLABE, tarjetas, RFC/CURP, emails, teléfonos, Unicode,
   título/respuesta y texto; medir recall por tipo y verificar cero fugas en fixtures.
2. Códigos ref con PII adyacente y placeholders adversariales; no hay exclusión
   amplia que oculte cuentas verdaderas fuera del diagnóstico.
3. Batch >400 KB/250 filas, lote final pequeño, registro individual demasiado
   grande, fallo DLP/desalineación. IDs nunca son transformados por DLP.
4. Longitudes 1/2/60/61, duplicados con distintos ack_ids y clave por revisión.
5. BQ falla => no ack; BQ éxito + ack falla => replay no duplica; ledger falla
   después de BQ => reconciliación; dos escritores => fencing efectivo.
6. Pub/Sub + GCS entregan la misma revisión; cambio de texto/votos/estrellas
   conserva nueva revisión; replay viejo no revierte el vigente.
7. Lease de ack renovado por >600s, SIGTERM, deadline de tarea, cuarentena
   duradera/expirada y receipts de página con eventos filtrados.
8. DirectRunner y la fase de merge operan sin extraer una PCollection en el host;
   Dataflow no escribe directamente append-only a TDS.
9. Receipts TDS permiten reutilizar datos del anual al extender a FULL; contar
   solicitudes repetidas del origen separadamente de transformaciones evitadas.

Métricas: bytes/requests DLP, latencia, lotes divididos, recall por tipo, filas
válidas/filtradas/cuarentenadas, redeliveries, revisiones nuevas, duplicados
suprimidos, MERGE bytes, edad de backlog, páginas pendientes y huecos de cobertura.

## Checklist

* [ ] Contratos/revisiones/receipts y migraciones de infra implementados.
* [ ] DirectRunner acotado; filas/bytes y deadline de tarea probados.
* [ ] Fail-closed ante DLP/configuración inválidos; privacidad medida, sin garantía universal.
* [ ] FILE_LOADS/staging + fuente deduplicada + MERGE y escritor coordinado en todos los modos.
* [ ] Ack leases y outcomes terminales, redelivery y replay GCS sin doble procesamiento final.
* [ ] Cobertura TDS reconciliada por página; expiración cruda genera hueco explícito.
* [ ] Ruff, formato, Pyrefly, Bandit y pytest >=85% pasan.

## Referencias técnicas (consulta 2026-10-14)

* [Límites DLP](https://docs.cloud.google.com/sensitive-data-protection/limits).
* [Precios DLP](https://cloud.google.com/sensitive-data-protection/pricing).
* [Lease management Pub/Sub](https://docs.cloud.google.com/pubsub/docs/lease-management).
* [MERGE en BigQuery](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/dml-syntax).
* [Lifecycle GCS](https://docs.cloud.google.com/storage/docs/lifecycle).
