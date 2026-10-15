# Contratos de ingesta v2

`voc-common` implementa contratos, transiciones puras y configuración.
EPIC-3 (3.1–3.5) implementa protocolo, repositorio, publicación durable,
recorridos, API, Job e imagen; EPIC-4 implementa el consumidor de sanitización
(recibos y cierres de página bajo el prefijo de recibos). Almacenamiento, auditoría
y Job histórico están declarados en EPIC-2 (2.7–2.9); no desplegados.
Las funciones puras no comprueban objetos GCS, permisos, publicación ni resultados
DLP/BigQuery. Esas comprobaciones corresponden a sus repositorios/pipelines.

## Identidad y transporte

Crear `RawReviewEnvelope.from_raw(raw, page_id=..., stream_id=..., plan_id=...)`.
El sobre guarda una copia inmutable del payload y valida banco/app/reseña.
`schema_version=2` identifica el contrato de serialización.

`source_revision` es SHA-256 del JSON canónico del `RawReviewEvent` normalizado:
claves ordenadas, separadores `,`/`:`, Unicode sin escape, UTF-8 y sin `ingested_at`.
Incluye ID/banco/app, usuario/imagen, título/texto, estrellas, fecha, versión,
votos y respuesta/fecha de respuesta. El cambio de cualquier campo del origen
produce otra revisión; una captura posterior del mismo contenido conserva el ID.
No normalizar adicionalmente el texto ni quitar votos antes de calcularla.

`event_id` es SHA-256 de la lista JSON canónica
`[bank_id, review_id, source_revision]`. No incluye página, plan ni stream:
BACKFILL, FULL y redelivery reutilizan el evento. El ledger debe mantener también
las asociaciones de cada página con el evento; deduplicar el transporte no elimina
la necesidad de completar los recibos de todas las páginas que lo referencian.
Cambiar este algoritmo requiere una migración explícita de identidad.

Después de DLP, crear `SanitizedReviewEnvelope.from_event(event, record)`.
Conserva la identidad y valida los metadatos del origen, pero solo contiene el
registro sanitizado. Su fábrica no acredita que se haya ejecutado DLP. No enviar
el sobre crudo a BigQuery ni transformar el digest del origen con DLP.

`ProcessingReceipt.from_event(...)` propaga ID, revisión y página sin texto crudo.
Distingue `PENDING`, `PROCESSING`, `TDS_COMMITTED`, `FILTERED_LENGTH` (heredado: ya no se emite),
`QUARANTINED` y `RETRYABLE_ERROR`. TDS exige digest de resultado e IDs de jobs BQ;
cuarentena/error exige código. Solo emitir el recibo después de confirmar su
resultado duradero. `PUBLISHED` en un manifiesto no equivale a `TDS_COMMITTED`.

`IngestionRunAudit` es el contrato de la única tabla de auditoría de ingesta,
`ingestion_runs_log_v2` (EPIC-2 feature 2.8):
`audit_event_id`, versión, banco/app, corrida, modo, estado y fecha son obligatorios;
plan/stream, motivo, revisión de estado, cotas y contadores son opcionales.
Estados: `STARTED`, `PAUSED`, `RECOVERY_REQUIRED`, `FAILED`, `COMPLETED`.
Contadores: `pages_committed`, `reviews_extracted`, `reviews_published`,
`reviews_discarded`, `recovery_requests`. Extraídas cuenta filas observadas antes
de descartar; publicadas cuenta confirmaciones lógicas, no intentos de envío.
Publicadas + descartadas no puede superar extraídas cuando se conocen los tres.
Son enteros no negativos; no fabricar
ceros cuando un evento inicial aún no tiene métricas. Reutilizar `audit_event_id`
en reintentos; la tabla append-only puede requerir deduplicación al consultar.
El modelo no admite cursores, blobs ni campos de texto de reseñas.
La tabla particiona por `updated_at` y agrupa por banco/corrida/estado; no existe
escritura dual ni tabla anterior. El primer despliegue parte directamente de este
contrato: no hay datos ni despliegues previos que migrar.

## Configuración y responsables

La fuente local de defaults/validación es `Settings`; `.env.example` incluye todos
sus campos. EPIC-2 debe inyectar los valores desplegados en servicio y Job; EPIC-3
debe aplicar presupuestos, heartbeat y preflight en ejecución.

| Variables | Default / uso |
| --- | --- |
| `GCS_WATERMARK_PREFIX` | `state/watermarks`: raíz por banco |
| `GCS_INGESTION_STATE_PREFIX` | `state/ingestion`: metadatos persistentes |
| `GCS_INGESTION_MANIFESTS_PREFIX` | `state/ingestion/manifests` |
| `GCS_INGESTION_LEDGERS_PREFIX` | `state/ingestion/ledgers` |
| `GCS_PROCESSING_RECEIPTS_PREFIX` | `state/ingestion/receipts` |
| `BQ_INGESTION_RUNS_LOG_TABLE` | `ingestion_runs_log_v2`; EPIC-2 feature 2.8 |
| `INGESTION_V2_ENABLED` | `false`; activar después de aprovisionar soporte v2 |
| `INGESTION_HISTORY_JOB_NAME` | Sin default; usar salida real del Job Pulumi 2.9 |
| `INGESTION_MAX_REQUESTS` | 100 solicitudes por ejecución |
| `INGESTION_MAX_RESPONSE_BYTES` | 20 000 000 bytes acumulados por ejecución |
| `INGESTION_MAX_RUNTIME_SEC` | 780 segundos por ejecución |
| `INGESTION_CONTAINER_TIMEOUT_SEC` | 900; debe coincidir con timeout desplegado |
| `INGESTION_CHECKPOINT_MARGIN_SEC` | 60; incluye margen para una solicitud en vuelo |
| `INGESTION_LEASE_DURATION_SEC` | 120; lease GCS de EPIC-3 |
| `INGESTION_HEARTBEAT_INTERVAL_SEC` | 30; menor que la duración del lease |

Los presupuestos son positivos; runtime + margen no puede superar timeout y el
margen no puede ser menor que `SCRAPER_TIMEOUT_SEC`. Para el Job histórico,
Pulumi puede cambiar estos valores conjuntamente, manteniendo las invariantes.
Los prefijos de manifiestos/ledgers/recibos son distintos y están bajo el prefijo
de metadatos. Estado y metadatos no se solapan con `raw_staging`/`temp_beam`.
Los respaldos crudos siguen sujetos al lifecycle de EPIC-2: preservar el ledger
no prolonga su disponibilidad. Cambiar un prefijo no mueve objetos existentes.

Antes de ejecutar un consumidor v2, llamar `settings.require_ingestion_v2()`;
para lanzar históricos, `settings.require_ingestion_v2(historical=True)` también
exige la referencia del Job. Este preflight es local: no garantiza que tabla,
Job o permisos existan. La activación requiere el despliegue de EPIC-2 primero.

`PLAYSTORE_DEFAULT_PAGE_SIZE=199` y `PLAYSTORE_PAGE_SIZE_POLICY_LIMIT=199` son
políticas locales separadas. Settings y payloads de ingesta usan las mismas constantes.
`ScanContext` puede describir páginas experimentales de otro tamaño; eso no las
habilita en producción. Antes de permitir 500, validar cadenas y actualizar el
límite, tests y configuración desplegada conjuntamente; cambiar contexto crea
otro stream y no permite transferir tokens. Los lotes DLP son independientes.

## Estado inicial y fixtures

El primer despliegue inicializa directamente `IngestionWatermarkState` con
schema_version=2, revisión 0, cobertura `UNVERIFIED` y sin fronteras ni planes.
Leer con `IngestionWatermarkState.model_validate_json`; las versiones no admitidas
fallan por validación y los campos adicionales se rechazan. No hay scripts,
lectores alternativos o fixtures de contratos descartados.

Fixtures sintéticas compartidas en `packages/voc-common/tests/fixtures/ingestion/`:
watermark inicial, sobres crudo/sanitizado, recibo y auditoría. Sus referencias GCS
y jobs son ficticias. Las pruebas validan round-trip e identidad determinista.
EPIC-2 y EPIC-3 deben reutilizarlas sin duplicar contratos divergentes.

## Persistencia e IAM de EPIC-2 feature 2.7

`IngestionStorageLayout` comparte defaults y validaciones de prefijos entre
`Settings` y Pulumi. El programa IaC lee exclusivamente `pulumi.Config` y exporta
los seis prefijos `gcs_*_prefix`; `Pulumi.dev.yaml` muestra sus valores. Los
servicios y el Job de sanitización reciben las variables correspondientes en
mayúsculas, además del bucket. No se crean carpetas ni archivos de estado desde
Pulumi: los prefijos describen nombres de objetos que escribirá el repositorio.

Rutas por defecto para el repositorio (todos los IDs deben validarse antes de
construir nombres; no aceptar segmentos de ruta aportados sin validar):

| Objeto | Ruta relativa al bucket |
| --- | --- |
| Raíz por banco | `state/watermarks/{bank_id}.json` |
| Plan | `state/ingestion/{bank_id}/plans/{plan_id}/{sha256}.json` |
| Stream | `state/ingestion/{bank_id}/streams/{stream_id}/{sha256}.json` |
| Manifiesto/versiones de fetch | `state/ingestion/manifests/{bank_id}/{stream_id}/{chain_epoch}/{page_id}/{manifest_version}-{fetch_attempt_id}.json` |
| Ledger paginado | `state/ingestion/ledgers/{bank_id}/{ledger_id}/...` |
| Recibo | `state/ingestion/receipts/{bank_id}/{page_id}/{receipt_id}.json` |
| Respaldo crudo | `raw_staging/{bank_id}/{run_id}/{page_id}/{fetch_attempt_id}.jsonl.gz` |

Usar los prefijos configurados, no concatenar literalmente estas rutas en el
extractor. Las referencias persistidas conservan URI/generación completas:
cambiar configuración no migra objetos ni invalida sus referencias anteriores.
Los tokens de paginación permanecen en estado protegido;
no en exports públicos de Pulumi ni en BigQuery. CAS y leases se implementan en
EPIC-3, no mediante recursos de infraestructura que posean esos objetos.

Ingesta y sanitización reciben `roles/storage.objectUser` mediante
`gcp.storage.BucketIAMMember` aditivo sobre el único bucket del datalake. Sustituye
los grants de Storage a nivel proyecto y el anterior `objectAdmin` de sanitización.
El acceso cubre objetos de todo ese bucket; los prefijos no constituyen aislamiento
IAM entre ambos workers. No se amplían permisos BigQuery para manejar checkpoints.
Los contenedores esperan a los grants. Con CMEK, el agente de servicio de Storage
mantiene su grant KMS antes de crear el bucket; los workers acceden al objeto a
través de Storage, sin nuevas llaves ni grants KMS directos para esta feature.
Véase [roles de Cloud Storage](https://docs.cloud.google.com/storage/docs/access-control/iam-roles).

El lifecycle elimina objetos elegibles por edad de siete días solo bajo el
prefijo crudo configurado y `temp_beam/`. El modelo rechaza prefijos persistentes
que se solapen con ellos antes de declarar recursos. El lifecycle es asíncrono;
la edad no es una hora garantizada de borrado. Véase
[Object Lifecycle Management](https://docs.cloud.google.com/storage/docs/lifecycle).

No hay limpieza automática de metadatos en esta feature. Para eliminar objetos
obsoletos, el repositorio debe inventariar referencias de raíces, planes activos,
manifiestos, ledgers y recibos pendientes, bajo el mismo control de concurrencia
por banco. Conservar todo objeto alcanzable o necesario para recuperación/auditoría;
reconciliar huérfanos antes de considerarlos candidatos de borrado. Los respaldos
crudos mantienen su TTL aunque un plan siga activo: si faltan, registrar el hueco
y recuperar desde el origen cuando sea posible. Nunca simular cobertura TDS por
la sola existencia de un manifiesto. No crear un cron/TTL ciego de metadata.

La suite de mocks valida grafo, lifecycle, configuración e identidades; no prueba
acceso real a objetos cifrados ni continuidad del scraper. Revisar preview real
antes del despliegue, especialmente la sustitución de grants de proyecto por
bucket. La auditoría y el Job histórico están declarados en 2.8/2.9;
`INGESTION_V2_ENABLED` sigue desactivado por defecto.

## Job histórico de EPIC-2 feature 2.9

`voc-ingestion-history-job` usa la cuenta de ingesta, una tarea y paralelismo 1.
El perfil HTTP y el histórico usan el modelo puro `IngestionExecutionConfig`,
independiente del entorno local. `HistoricalExecutionConfig` fija defaults del
histórico y los conserva al aplicar overrides parciales.

Configurar en el namespace Pulumi `bbva-voc-infra`:

| Clave | Default y uso |
| --- | --- |
| `ingestion_execution` | Objeto con campos de `IngestionExecutionConfig`; perfil HTTP 900s, presupuesto 780s, margen 60s, 100 solicitudes, 20 MB |
| `historical_ingestion.execution` | Perfil histórico: timeout 3600s, presupuesto 3480s, margen 120s, 1000 solicitudes, 200 MB |
| `historical_ingestion.command` | `["python", "-m", "ingestion_worker.job"]` |
| `historical_ingestion.max_retries` | 1; mismo plan/stream dentro de los reintentos de una ejecución |
| `historical_job_image` | Usa `ingestion_worker_image` si se omite; configurar otra imagen si corresponde |
| `ingestion_v2_enabled` | false hasta disponer del runtime de EPIC-3 |

Las claves de cada perfil coinciden con Settings (`ingestion_max_requests`,
`ingestion_max_response_bytes`, etc.). `Pulumi.dev.yaml` muestra ambos objetos.
Los campos no especificados mantienen sus defaults del perfil correspondiente.
El timeout HTTP coincide con el configurado en el servicio, y el timeout histórico
con el configurado en el Job. Ambos reciben los prefijos, tabla de auditoría,
tópico y opciones del scraper; mantienen página de 199 y heartbeat menor al lease.
Los presupuestos y la salida anticipada deben hacerse cumplir en el runtime.

Exports: `ingestion_history_job_id`, `ingestion_history_job_name` (nombre completo
`projects/.../locations/.../jobs/...`) y `ingestion_history_job_region`. La API de
ingesta recibe el nombre completo en `INGESTION_HISTORY_JOB_NAME` y la región en
`GCP_REGION`. Espera al Job y al grant de ejecución antes de desplegarse.

La identidad de la API de ingesta recibe `roles/run.jobsExecutorWithOverrides`
solo sobre ese Job. El rol incluye `run.jobs.run` y `run.jobs.runWithOverrides`;
el `run.invoker` común no permite overrides. Véanse los
[roles oficiales de Cloud Run](https://docs.cloud.google.com/run/docs/reference/iam/roles).
Scheduler conserva grants concretos al servicio incremental y al Job de
sanitización, sin rol de invocación a nivel proyecto ni acceso al histórico.
El backend analítico no recibe permiso para ejecutar este Job directamente.

Contrato pendiente del runtime de EPIC-3: la API valida banco/plan/stream,
comprueba contexto y registra la solicitud; ejecuta `jobs.run` mediante su
identidad de servicio y devuelve la referencia de ejecución sin esperar al fin
del backfill. Usar overrides del contenedor `historical-ingestion` únicamente para
identificadores validados: `INGESTION_BANK_ID`, `INGESTION_PLAN_ID` y
`INGESTION_STREAM_ID`. No pasar tokens, estado JSON completo, comandos arbitrarios
ni presupuestos aportados por el cliente. El proceso falla si faltan identificadores
o v2 no está habilitado; no iniciar implícitamente FULL sin un plan persistido.
La validación/whitelist de overrides corresponde a la API, no a IAM.

Una tarea por ejecución no impide ejecuciones concurrentes. El Job debe adquirir
lease/CAS por banco y cargar el plan/contexto persistido; reintentos y siguientes
ejecuciones reutilizan el plan. Si llega al presupuesto, guardar checkpoint y
pausar explícitamente. Esta feature no añade una cadena automática de ejecuciones
ni un Scheduler histórico: cada lanzamiento continúa el plan bajo demanda.
El invocador no debe ejecutar backfill mediante BackgroundTasks o esperar tras
responder HTTP. No hay recursos `JobExecution` ni ejecución inmediata en Pulumi.

Runtime de EPIC-3 feature 3.5: la API persiste el plan (`prepare_plan`) antes de
lanzar y envía solo los tres identificadores; `INGESTION_STREAM_ID` vacío
continúa todos los streams del plan. `ingestion_worker.job` falla con 64 si
faltan banco/plan, v2 está desactivado o el plan no existe; deriva BACKFILL o
FULL del plan persistido. Crear el recurso no comprueba que la imagen publicada
contenga el módulo.
Antes de activar, publicar y validar la imagen y realizar integración real de
IAM, overrides, leases y recuperación. El preview real permanece pendiente del
stack/backend `dev`; no se ejecutó un despliegue ni un backfill.

## Repositorio de EPIC-3 feature 3.2

`WatermarkRepository` guarda el JSON de `IngestionWatermarkState` sin campos
adicionales en la raíz. Su metadata GCS incluye `lease` (owner, epoch,
heartbeat, expiración) y `catalog` (URI/generación/hash del catálogo inmutable).
Toda modificación, incluido heartbeat/liberación, vuelve a subir contenido y
metadata juntos con CAS de generación; ningún escritor debe usar un patch
independiente de metadata. Así una toma de lease cambia la misma generación
que debe comparar el commit del escritor anterior. No depende de Object
Versioning: las versiones de planes/streams usan nombres distintos por hash.

El catálogo referencia las versiones exactas de planes y streams, el índice
persistente de páginas y la cabeza de la cola de auditoría. Sus snapshots viven
en `{GCS_INGESTION_STATE_PREFIX}/{bank_id}/catalogs/{sha256}.json`.
El índice de páginas usa nodos inmutables bajo `.../{bank_id}/page-index/`,
hojas de hasta 128 entradas y ramificación por SHA-256: no recorre todo el
histórico en cada commit. Las hojas son índices de referencias, no copias de
reseñas. Solo son visibles desde un catálogo comprometido por CAS.

La creación usa generación 0; un 412 aborta con `StateConflict` y obliga a releer.
No hay reintento automático que sobreescriba al ganador. Leer raíz significa
leer metadata/generación y descargar contenido condicionado a esa generación;
se reintenta como máximo tres veces si cambia durante la lectura.
Los objetos referenciados verifican generación y hash; desaparecidos/cambiados
fallan explícitamente. Véanse las precondiciones del
[SDK de Cloud Storage](https://docs.cloud.google.com/python/docs/reference/storage/latest/google.cloud.storage.blob.Blob).

Los leases usan reloj UTC inyectable; producción requiere relojes sincronizados
y renovar antes del vencimiento. Cada adquisición incrementa epoch, incluso si
reutiliza run_id; un handle vencido no puede renovar, liberar ni comprometer.
Heartbeat y commit simultáneos también pueden provocar 412: serializar estas
operaciones en el llamador o releer/reconciliar. La renovación periódica será
responsabilidad del ejecutor de 3.4.

Los ledgers son listas de nodos inmutables paginados, cada uno con referencia
completa al anterior, conteo acumulado y hash del nodo. Nunca se corta la
enumeración a 500. Las entradas de reseñas contienen exclusivamente ID,
source_revision, event_id y fecha; el repositorio valida identidad, duplicados
y cotas antes de comprometer. El índice de manifiestos es otro ledger sin
texto. Un commit verifica respaldo/generación, ledger completo, continuidad y
publicación PUBLISHED mediante el reducer compartido, escribe los hijos y
finalmente cambia raíz/catálogo juntos. La confirmación real de todos los
futures de publicación corresponde a 3.3; el repositorio no publica por sí solo.

Fallos antes del CAS dejan objetos huérfanos invisibles al estado actual.
Reintentar la misma captura reutiliza objetos únicamente si su contenido coincide;
un page_id ya comprometido con contenido diferente falla. No reconstruir progreso
listando objetos huérfanos. No se implementa borrado automático de huérfanos.

`record_audit` incorpora un evento a la cola durable mediante otro CAS.
El ejecutor debe registrar los eventos de corrida y sus métricas (3.4);
el repositorio no inventa estados de ejecución. Solo se entregan eventos
alcanzables desde la raíz comprometida. `BigQueryAuditWriter.from_settings`
usa `BQ_INGESTION_RUNS_LOG_TABLE`, envía `audit_event_id` como row_id y comprueba
errores de inserción por fila. Tras confirmación escribe marcador inmutable
en `.../{bank_id}/audit-delivered/{audit_event_id}.json`.
BigQuery caído no borra la cola ni cambia progreso. Una caída entre inserción y
marcador puede duplicar filas: consultar deduplicando por audit_event_id, pues
[insertId solo ofrece deduplicación best effort](https://docs.cloud.google.com/bigquery/docs/write-api-rest).
La entrega acepta un presupuesto de eventos; conservar/reintentar el mismo ID.

`GET /api/v1/watermarks/{bank_id}` solo lee: devuelve observaciones, high
confirmado, estados/contadores por stream y evidencia de planes, huecos e
incertidumbre. No expone tokens, rutas GCS ni dueño del lease, ni porcentaje de
completitud. Ausencia de raíz devuelve persisted=false sin crear objetos;
identidad inválida produce 422 y estado ilegible/no disponible produce 503.
Los clientes cloud se crean al primer request con v2 habilitado, no al importar.

Pruebas locales usan un GCS falso que exige precondiciones y simulan carreras,
takeover, huérfanos, reintentos, referencias alteradas, más de 500 IDs y fallos
de BigQuery. No sustituyen la prueba real de IAM/GCS/BQ antes del despliegue.

## Página duradera de EPIC-3 feature 3.3

`RawReviewBatchPublisher.prepare_page` valida de nuevo la respuesta RPC, fija
ingested_at al fetched_at de captura y crea sobres mediante la fábrica compartida.
El fingerprint usa filas crudas ordenadas (sin el cursor de salida), event_ids,
descartes y conteo. page_id es SHA-256 del JSON canónico de
`[bank_id, stream_id, context.fingerprint, chain_epoch, input_token, fingerprint]`.
El token se trata como opaco y nunca aparece en el nombre de objeto.
Cambios de votos, respuestas, texto o filas descartadas producen otra captura.
La renovación del cursor de salida de una misma página exige el replay de 3.4;
no se sustituye silenciosamente un pendiente por otra respuesta.

El JSONL contiene una cabecera de captura con respuesta RPC completa codificada
en base64, protocolo, modo, fingerprint y descartes; las líneas restantes son
RawReviewEnvelope completos. Ambos textos crudos viven únicamente en el mismo
objeto sujeto al TTL. gzip usa mtime=0; creación condicional y hash/generación
impiden sobrescribir una captura distinta. La preparación exige fetched_at y
fetch_attempt_id estables; tras la caída se debe reanudar el pendiente guardado,
no regenerar timestamps ni IDs. El presupuesto de respaldo descomprimido es
configurable y se aplica también al restaurar.

Tras respaldo y ledgers se añade al catálogo `pending[page_id]` con referencias
inmutables a manifiesto/respaldo y modo, mediante CAS cercado por lease.
Ningún mensaje sale antes de este punto. El manifiesto inicial es versión 1;
cada resultado de publicación crea una versión mayor
`max(anterior + 1, time.time_ns())`. Se permiten saltos, evitando colisiones con
resultados huérfanos de un CAS perdido; las versiones originales no se editan.
Solo el catálogo identifica la versión autoritativa. La revisión lógica del
watermark puede aumentar al registrar pendientes sin avanzar el frontier.

`publish_page` restaura y valida la captura desde su generación/hash, verifica
contexto/continuidad/lease y envía cada RawReviewEnvelope v2 en JSON UTF-8.
Atributos: event_id, page_id, source_revision, bank_id, mode, schema_version.
Se reutiliza el PublisherClient inyectado, propiedad del llamador; no se cierra
ni recrea por página. Se envían los registros de la página y se llama
`future.result(timeout=restante)` para todos los futures devueltos, incluso
cuando alguno falla. El presupuesto de confirmación es compartido
(default 30s), no 30s multiplicados por reseña. Se comprueba el ID de mensaje,
no solo que el future haya terminado. Véase la
[confirmación oficial de publicación](https://docs.cloud.google.com/pubsub/docs/publisher).

Cualquier fallo síncrono o de future mantiene PENDING/PARTIAL con conteo de
confirmaciones y lanza PublicationIncomplete. Un timeout puede confirmarse más
tarde: el SDK puede seguir trabajando; no se presume cancelación ni se
descartan esas reseñas. Se reenvía la página completa con idénticos event_ids,
sin sumar confirmaciones de intentos distintos como reseñas nuevas.
Si se perdió el CAS que guardaba PUBLISHED, el replay puede duplicar todo.
Si PUBLISHED quedó comprometido en el catálogo y falló el CAS final,
se reintenta solo el commit, sin volver a publicar. El CAS final cambia
stream/frontier/ledger y elimina el pendiente juntos.

PageManifest conserva `discard_ledger` opcional, con validación de conteo; el
publisher siempre lo crea y los commits con descartes lo exigen. Sus nodos
contienen row_index, review_id y reason=NO_TEXT; no textos ni usuarios.
Los límites de la página describen todas las filas crudas válidas de protocolo;
las fechas del ledger de eventos deben estar dentro de esos límites.
El reducer permite filas crudas sin texto con cursor, pero rechaza páginas
sin filas o sin texto y sin cursor como evidencia ambigua.
Un parser roto invalida la página completa, sin descartar filas silenciosamente.

PUBLISHED nunca implica TDS_COMMITTED: este publisher deja sanitización
PENDING y no confirma high incremental, cobertura TDS ni EOF.
El respaldo sigue sujeto al TTL de siete días. Falta, cambio de generación/hash,
gzip inválido o incongruencia del contenido producen BackupUnavailable;
se conserva el pendiente y no se avanza ni se declara completitud.
El ejecutor de 3.4 debe registrar hueco/recuperación y supervisar los pendientes
antes de expirar. El GET ofrece sus fechas, estados y conteos. Los manifiestos
y ledgers sin texto sobreviven al TTL, pero no reconstruyen textos borrados.
La idempotencia final del consumidor corresponde a EPIC-4; no se promete una
transacción GCS–Pub/Sub ni entrega exactamente una vez.
