# EPIC-3: Ingesta Multibanco Reanudable desde Google Play

* **Estado:** Pendiente. Especificación revisada el 2026-10-14; falta validación experimental del protocolo.
* **Dependencias:** EPIC-1 y EPIC-2. Los cambios de contratos y de despliegue descritos aquí son trabajo pendiente, no capacidades ya implementadas.
* **Directorios:** `services/ingestion-worker/`, `packages/voc-common/`, `infra/`, `experiments/playstore/`.

## Objetivo y límites de la garantía

Extraer reseñas textuales de BBVA, Nubank, Santander, Azteca y Banorte mediante
un cliente propio, con respaldo por página, publicación al menos una vez y
recuperación verificable. El endpoint `batchexecute` es interno: no tiene contrato
público de estabilidad, filtros temporales documentados ni garantía de enumerar
el histórico completo. El tamaño 199 es una política conservadora inicial,
**no un máximo demostrado**. Las cifras de la ficha de la app no constituyen
un denominador fiable para calcular el porcentaje de reseñas recuperadas.

La garantía implementable es conservar/reprocesar páginas ya aceptadas mientras
sus respaldos estén disponibles. No se promete cero duplicados en transporte,
ni recuperar registros que el origen deje de exponer. No se confunde el mínimo
observado con cobertura continua, ni un cursor guardado con una snapshot.

## Modelo de estado: progreso lógico y cursor físico son diferentes

### Tarea preparatoria: contratos v2 y migración en `voc-common`

Implementar modelos Pydantic con `extra="forbid"`, UTC y `schema_version=2`.
Estos contratos deben incorporarse antes de escribir el extractor; el watermark
v1 no permite expresar las garantías siguientes.

| Contrato | Campos y significado obligatorio |
| --- | --- |
| `IngestionWatermarkState` v2 | `bank_id`, `app_id`, `schema_version`, `revision`, `updated_at`; `observed_min_at`/`observed_max_at` descriptivos; `incremental` separado; referencias a planes/streams y manifiestos. Los contadores no demuestran cobertura. |
| `IncrementalProgress` | `committed_high_at`, referencia al conjunto completo de IDs de esa frontera, `active_run_id`, `baseline_high_at` congelado, `candidate_high_at`, `replay_from_at`, estado pendiente y cursor del scan en curso. |
| `HistoricalPlan` | `plan_id`, `started_at`, `upper_anchor_at` fijo, `requested_lower_at` (fecha o `None` para agotar origen), `stream_ids`, `status`, `completion_evidence`, `extension_events`. La cota anual se fija una vez: `started_at - 365 días`. |
| `ScanContext` | `app_id`, `lang`, `country`, `sort_order`, `star_filter`, `device_filter`, `page_size`, `protocol_version`; fingerprint determinista del contexto completo. |
| `ScanStreamState` | `stream_id`, `context`, `chain_epoch`, `status`, `frontier_page_id`, `frontier_oldest_at`, `anchor_page_id`, referencia al último cursor de entrada/salida, `last_success_at`, `recovery_status`. Un stream por contexto/estrella; no comparte tokens con otros. |
| `PageManifest` | `page_id`, `run_id`, `plan_id`, `stream_id`, `chain_epoch`, `ordinal`, contexto, cursores de entrada/salida, `fetched_at`, límites de fechas, referencia al ledger de IDs/revisiones, conteos crudos/válidos/descartados, fingerprint de contenido, URI/generación del respaldo, fase de publicación, fase de sanitización, `source_evidence`. |

* Los IDs y los campos de revisión son distintos: `(bank_id, id_resena)` identifica
  una reseña; una revisión incluye cambios de texto, estrellas, versión, votos y
  respuesta. `source_revision` es un digest determinista del contenido observado,
  sin fecha local de extracción. `event_id` se deriva de banco, ID y revisión.
* Los manifiestos/ledgers contienen metadatos e IDs, nunca copias de texto o
  usuarios. Los cursores se almacenan íntegros en estado protegido; no se imprimen
  en logs. El estado apunta a ledgers paginados; no crece con todo el corpus.
* No se trunca a 500 el conjunto usado como prueba de cierre de una frontera.
  Una caché acotada sirve para acelerar consultas, no para decidir que un scan
  terminó. Si se supera el límite se consulta el ledger o se continúa el scan.
* `observed_min_at` no significa que todo lo más reciente esté completo.
  Registrar segmentos de **traversal observado** mediante manifiestos enlazados.
  El límite del origen mutable y las comprobaciones de continuidad se mantienen
  explícitos en `completion_evidence`; no se certifica completitud absoluta.
* Un `None` de cursor no representa simultáneamente «no iniciado» y «terminado»:
  `status` distingue `NOT_STARTED`, `RUNNING`, `PAUSED`, `RECOVERY_REQUIRED`,
  `TARGET_REACHED`, `SOURCE_EXHAUSTED_OBSERVED` y `BLOCKED`.
* Migración v1: conservar sus campos como observaciones y cursores candidatos,
  marcar cobertura `UNVERIFIED` y validar/reconciliar la frontera. No convertir
  `backfill_one_year_completed`, `full_backfill_completed` o un máximo v1 en
  evidencia v2. `oldest_page_token` global queda obsoleto como fuente de verdad.
* El avance se realiza por página mediante un reducer validado, no con llamadas
  por reseña a `update_bounds`. Permitir borrar explícitamente un cursor terminal.

### BACKFILL anual seguido de FULL_BACKFILL

1. Crear el plan anual en T0, con cota `T0 - 365 días`, y stream global NEWEST.
2. Guardar **la página completa** que cruza esa cota, incluidos los registros más
   antiguos que la cota. El margen extra evita cortar una página arbitrariamente.
3. Tras confirmar respaldo/publicación/checkpoint, marcar `TARGET_REACHED`.
   Conservar el cursor de entrada de esa página, su ledger y el cursor de salida.
4. Para FULL_BACKFILL con **el mismo contexto**, ampliar el objetivo del mismo
   plan a `requested_lower_at=None`, conservando `plan_id`, T0, páginas y cobertura
   observada; registrar el cambio en `extension_events`. No volver a empezar el
   año ni recalcular la cota. Replay de la página ancla y luego continuación.
5. El incremental obtiene novedades posteriores independientemente; no modifica
   el cursor histórico. Cambiar idioma, estrellas, tamaño o versión de protocolo
   crea un stream nuevo. Los datos existentes se reutilizan vía deduplicación,
   pero **no** se traslada un cursor global a las particiones por estrellas.

Una página ancla no hace estable el cursor. Si el origen inserta, modifica o
elimina reseñas, el replay puede ser distinto. Esta incertidumbre debe exponerse,
no reemplazarse por una garantía de snapshot.

Ejemplo conceptual del estado al terminar el anual (estructura abreviada;
las cadenas entre `<...>` son referencias, no cursores reales):

```json
{
  "schema_version": 2,
  "bank_id": "BBVA",
  "incremental": {
    "committed_high_at": "2026-10-13T08:00:00Z",
    "active_run_id": null
  },
  "historical_plan": {
    "plan_id": "initial-bbva-20261014",
    "upper_anchor_at": "2026-10-14T08:00:00Z",
    "requested_lower_at": "2025-10-14T08:00:00Z",
    "status": "TARGET_REACHED",
    "stream_ids": ["bbva-es-mx-newest-global-v1"]
  },
  "historical_stream": {
    "stream_id": "bbva-es-mx-newest-global-v1",
    "chain_epoch": 1,
    "frontier_oldest_at": "2025-10-12T07:00:00Z",
    "anchor_page_id": "<pagina-completa-que-cruzo-el-ano>",
    "input_cursor_ref": "<cursor-para-releer-esa-pagina>",
    "next_cursor_ref": "<cursor-devuelto-por-esa-pagina>",
    "recovery_status": "NOT_CHECKED_SINCE_LAST_COMMIT"
  }
}
```

Al pedir FULL, cambiar el objetivo inferior del **mismo plan** a `null`,
registrar la extensión y ponerlo `RUNNING`; conservar ancla, stream y T0.
El estado incremental permanece separado. No convertir el cursor en un número
de página ni usar `frontier_oldest_at` como parámetro de búsqueda del servidor.

### Recuperación por coste creciente

1. Si hay página respaldada pero publicación pendiente, completar su entrega
   desde GCS antes de consultar de nuevo el origen. No avanzar el cursor.
2. Replay del cursor **de entrada** de la última página comprometida, manteniendo
   todo el contexto. Comparar IDs/revisiones, fechas y estructura con el manifiesto;
   persistir cualquier cambio como nueva observación. El solapamiento se evalúa
   como evidencia, no como prueba matemática de que no existen saltos.
3. Con ancla consistente, continuar con el cursor **devuelto por el replay**.
   No asumir que el token viejo conserva la misma página o TTL.
4. Si falla/deriva, probar unas pocas anclas anteriores de la misma cadena
   (presupuesto configurable), sin mezclar contextos. Registrar cada intento.
5. Si ninguna sirve, abrir `chain_epoch` nuevo y recorrer desde la cabeza hasta
   conectar con el ledger/frontera anterior. Las fechas ayudan a detectar la
   región objetivo; **no son un filtro temporal enviado al endpoint**. Saltar
   escritura de revisiones ya confirmadas, pero no simular que esto ahorra las
   solicitudes necesarias para atravesar páginas del origen.
6. Limitar la recuperación por solicitudes y tiempo; si no conecta, devolver
   `RECOVERY_REQUIRED`. Mantener segmentos separados y no cerrar un hueco.

**Límite inevitable:** si Google invalida todos los cursores y no ofrece una
búsqueda temporal verificable, recuperar la posición requiere volver a recorrer
el prefijo. No hay salto directo fiable ni búsqueda binaria por fecha usando
este contrato. Ejecutar bloques largos en Jobs reduce interrupciones; guardar
anclas reduce riesgo y puede reducir coste, pero no elimina ese peor caso.

## FEATURE 3.1: Paquete y adaptación del protocolo

### Dependencias y archivos

Workspace `ingestion-worker`, Python >=3.11, hatchling, `voc-common` desde
workspace. Dependencias: FastAPI, uvicorn, `httpx[socks]`, tenacity, clientes GCP
Pub/Sub, Storage y BigQuery y Pydantic v2. Mantener rangos compatibles probados
al implementar y resolver con uv; no instalar `google-play-scraper` en producción.
Archivos: `playstore_protocol.py`, `extractor.py`, `watermark_store.py`,
`publisher.py`, `main.py`, `job.py`, Dockerfile y tests de cada módulo.

### Serialización estructural, no concatenación de f-strings

`build_batchexecute_body(app_id, sort_order=NEWEST, count=199,
filter_score_with=None, filter_device_with=None, page_token=None) -> bytes`.
Hipótesis de protocolo de referencia consultada el 2026-10-14:

```python
pagination = [count] if page_token is None else [count, None, page_token]
filters = [None, filter_score_with, None, None, None, None, None, None,
           filter_device_with]
inner = [None, [2, int(sort_order), pagination, None, filters], [app_id, 7]]
outer = [[["oCPfdb", json.dumps(inner), None, "generic"]]]
body = urllib.parse.urlencode({"f.req": json.dumps(outer)}).encode("utf-8")
```

`None` se serializa como JSON `null`. URL construida con `urlencode` para `hl`
y `gl`; Content-Type form-urlencoded. Tokens opacos, sin decodificarlos ni
editar su contenido. `page_size` se fija por stream; solo cambiarlo al crear uno.
Versionar el adaptador y registrar el commit/fingerprint de la referencia cuando
se incorporen fixtures reales. No importar código remoto dinámicamente.

### Parser y errores

Retornar `RpcPageResult`: filas válidas, cantidad de filas crudas, descartes
explícitos, cursor, `protocol_version`, evidencia y clasificación. Separar
`ProtocolError`, `TransportError`, `RateLimitedError`, `InvalidCursorError` y
`EmptyAmbiguousError`. No transformar errores en `([], None)`.

* Reconocer prefijo XSSI y frames JSON con `wrb.fr`/`oCPfdb`, permitiendo líneas
  de longitud. Una regex que captura todo el documento no basta. HTML, JSON
  truncado, frame ausente/ambiguo o estructura desconocida fallan explícitamente.
* Mapeo candidato: ID `[0]`, usuario `[1][0]`, imagen `[1][1][3][2]`, estrellas
  `[2]`, texto `[4]`, fecha `[5][0]`, **votos `[6]`**, respuesta `[7][1]`, fecha de
  respuesta `[7][2][0]`, versión `[10]`. Reutilizar/ajustar la fábrica compartida
  `RawReviewEvent.from_batchexecute_entry`, evitando parsers divergentes.
* Cursor candidato de la referencia actual: `inner_data[-2][-1]`, sujeto a
  estructura/fixtures. No buscar cualquier string en la respuesta ni aceptar
  `[-1][-1]` como fallback silencioso. Desconocido => cambio de protocolo.
* `PAGE_WITH_CURSOR`, `END_CANDIDATE`, `EMPTY_WITH_CURSOR`, `EMPTY_AMBIGUOUS`,
  `PROTOCOL_ERROR`. Una página sin reseñas textuales puede tener filas crudas y
  cursor: seguir. Una página vacía no demuestra agotamiento.
* EOF observado exige forma terminal validada y relectura consistente bajo el
  presupuesto. Registrar evidencia, no prometer enumeración total del catálogo.
  Una repetición HTTP 200 del mismo error no es validación terminal.
* Si aparecen fechas fuera de orden, no cortar inmediatamente al primer registro
  viejo: procesar página completa y abrir reconciliación por ventana/IDs.

## FEATURE 3.2: Repositorio de estado, leases y auditoría

`WatermarkRepository` implementa lectura v2, reducer de páginas, migración,
ledger, adquisición/renovación/liberación de lease y CAS por generación GCS.

* Estado actual: `state/watermarks/{bank_id}.json`; manifiestos y planes bajo
  `state/ingestion/{bank_id}/`. Leer datos y generación consistentemente.
* `if_generation_match=0` al crear; generación leída al actualizar. Un 412 no
  permite sobrescribir: releer, comprobar dueño/epoch y reconciliar o abandonar.
* Lease por banco con `owner_run_id`, vencimiento, heartbeat y fencing epoch;
  incremento con CAS. Antes de comprometer, el escritor confirma que conserva
  el lease. Un lock en memoria y `max_instance_count=1` no protegen reintentos
  ni procesos distintos. No asumir transacciones multiobjeto de GCS.
* Los manifiestos son inmutables por versión; estado raíz cambia con CAS tras
  todas las operaciones requeridas. Objetos huérfanos se reconcilian por ID;
  no reconstruir progreso usando únicamente contadores o timestamps.
* La auditoría conserva `run_id`, `plan_id`, stream, estado, motivo, páginas,
  conteos extraídos/publicados/descartados, solicitudes de recuperación y tiempos.
  **Migración de infra pendiente:** crear `ingestion_runs_log_v2` según el ajuste
  de EPIC-2, conservando `ingestion_watermarks_log` v1 durante la transición.
  La tabla actual no incluye `status`/`run_id`; no enviar eventos v2 a su schema.
  BigQuery no es almacenamiento transaccional del estado vivo.
* Exponer `GET /api/v1/watermarks/{bank_id}` como progreso y cobertura observados,
  con huecos e incertidumbre. No devolver porcentaje ficticio de completitud.

## FEATURE 3.3: Página duradera y publicación al menos una vez

`RawReviewBatchPublisher` opera con un `PageManifest`, no con un UUID nuevo por
cada reintento. `page_id` determinista por stream, epoch, input cursor y fingerprint
observado; la misma captura conserva su ID. Un replay cambiado es otra captura.

1. Persistir página completa JSONL.gz en `raw_staging/{bank_id}/{date}/{page_id}`
   con creación condicional y verificar generación/fingerprint. Si ya existe,
   reutilizar solo si coincide; no sobrescribir una captura diferente.
2. Publicar registros con `event_id`, `page_id`, `source_revision`, banco y modo.
   Confirmar **cada `future.result()`** con timeout; `wait()` por sí solo no basta.
3. Tras confirmar todos, comprometer manifiesto/estado raíz por CAS. Publicación
   parcial o fallo del CAS mantienen posibilidad de replay y duplicados. No hay
   transacción atómica GCS-Pub/Sub; la idempotencia de EPIC-4 cierra esa brecha.
4. Registrar filas sin texto o rechazadas con motivo y conteo. Errores de parser
   invalidan la página completa; no descartar silenciosamente un schema drift.
5. El estado de ingesta (`PUBLISHED`) es distinto de `SANITIZED_COMMITTED`.
   La cobertura TDS solo avanza tras la confirmación de EPIC-4.

La retención cruda de siete días sigue vigente. Supervisar páginas pendientes
antes de expirar. Manifiestos solos no reconstruyen cuerpos borrados: si se
pierden ambas copias antes de confirmar destino, registrar hueco y recuperar
origen; no marcar completitud. El ledger final, sin texto, puede sobrevivir al
TTL del staging para deduplicación y auditoría.

## FEATURE 3.4: Extracción y políticas de recuperación

`PlayStoreResilientExtractor.run_extraction` devuelve un resultado tipado con
`run_id`, plan/stream, status y motivo, contadores, presupuesto consumido,
fronteras observadas/confirmadas y recuperación. Estados al menos:
`TARGET_REACHED`, `SOURCE_EXHAUSTED_OBSERVED`, `PARTIAL_RATE_LIMITED`,
`BUDGET_EXHAUSTED`, `RECOVERY_REQUIRED`, `PROTOCOL_ERROR`, `LEASE_CONFLICT`.

### Incremental

* Usar copia congelada del **high confirmado**, no el máximo observado actualizado
  por página. Reanudar la corrida pendiente antes de abrir otra.
* Candidato high y progreso se guardan por página, pero high confirmado solo
  avanza tras cerrar el traversal hasta la frontera anterior, con reconciliación.
* Cortar por ventana conservadora/ledger de IDs, no por el primer ID duplicado.
  Revisitar una ventana configurable para cambios, revisiones tardías o empates.
  La ventana reduce riesgo pero no demuestra que capture todas las ediciones.
* Bootstrap puede confirmar una ventana reciente explícita; nunca declarar que
  esa ventana inicial representa todo el histórico que aún no se recorrió.

### Histórico y particiones

* Aplicar el plan y recuperación anteriores. Guardar y publicar páginas completas,
  incluida la que cruza el cutoff anual. El FULL conserva toda esa captura.
* Hacer checkpoints por stream/estrella. Missing state = no iniciado; estado EOF
  explícito = agotamiento observado. No compartir límites temporales de particiones
  para deduplicar: consultar el ledger de reseñas/revisiones.
* Terminar plan particionado solo cuando todos sus streams alcanzan el objetivo
  o EOF validado, sin huecos pendientes. Cambios de estrellas pueden producir
  duplicados y movimientos; reconciliar mediante el ID estable de la reseña.

### Presupuestos y HTTP

* Reservar capacidad para el delta diario durante la carga inicial. El histórico
  no debe publicar más de lo que sanitización puede drenar antes del TTL crudo.
  Coordinar sus presupuestos con edad/backlog de EPIC-4 y pausar el histórico
  cuando se supera el umbral. La misma suscripción no ofrece prioridad por modo;
  si se requiere aislamiento real, crear colas/suscripciones y filtros mediante
  migración explícita de infra, conservando las mismas claves de deduplicación.
* Presupuestos por solicitudes, páginas, bytes, duración y recuperación; no cortar
  una página ya recibida a mitad. El límite de reseñas es **blando por página**:
  puede excederse hasta la página validada; documentarlo o introducir una API de
  límite de páginas. Un límite estricto requiere persistir el resto antes de avanzar.
* Honrar Retry-After; 429/503 => backoff acotado con jitter y circuit breaker.
  403/HTML desconocido => investigar antes de tratarlo como rate limit. Proxies
  son configuración opcional, no garantía de recuperación ni de acceso permitido.
  En experimentos se detiene el sondeo al bloqueo; no se rota para eludirlo.
* Mantener cliente HTTP reutilizable por contexto; no abrir conexión por reseña.
  La rotación de User-Agent no cambia el modelo de confiabilidad del origen.
* Salir por presupuesto de tiempo antes del timeout para comprometer la última
  página. Cancelación/SIGTERM => best effort; el respaldo/ledger permiten reintentar.

## FEATURE 3.5: API, Job histórico, Docker y aceptación

* `GET /health`; `POST /api/v1/ingest` individual; `POST /api/v1/ingest/all`
  secuencial, compatible con Scheduler. Las peticiones cortas usan los contratos
  compartidos ampliados/versionados; los resultados no prometen cero duplicados.
* **Iniciales largas:** CLI `python -m ingestion_worker.job` ejecutado como Cloud
  Run Job, con plan/stream y presupuesto. No usar FastAPI BackgroundTasks como
  persistencia. El servicio HTTP actual tiene timeout 900s y CPU bajo demanda:
  no da continuidad a un histórico largo después de responder o de un 504.
* Cambios de infra pendientes: declarar Job de ingesta histórica, imágenes y
  permisos de invocación propios, tiempo de tarea acotado, flags/entorno y saltos
  de versión de estado. No activar históricos masivos con cron diario por defecto.
* Docker multi-stage con uv workspace y usuario no root. Ajustar pyproject root
  y CI al incorporar el servicio; pruebas y cobertura >=85% del código del worker.

### Tests obligatorios

1. Payload exacto, null/escapes, token opaco, protocolo versionado y fixtures
   estructurales; votos [6], cursor observado, frames/HTML/error no confundidos con EOF.
2. Incremental: falla tras página 1; high confirmado no cambia y la página 2 se
   recupera antes de cerrar la corrida. Empates >500 y orden no monotónico.
3. Anual: página cruza cutoff y contiene filas anteriores; FULL mismo contexto
   reusa plan/ancla, no pierde la cola de esa página ni recorre el año si el cursor sirve.
4. Cursor inválido/derivado, ancla anterior válida, todas las anclas inválidas,
   conexión desde cabeza y presupuesto agotado sin declarar cobertura cerrada.
5. Publicación parcialmente fallida, respaldo duplicado, CAS 412, lease vencido,
   dos workers y falla de auditoría: ninguna fase avanza por una confirmación falsa.
6. Página de 199 con presupuesto restante 5: procesar entera o guardar el resto.
7. Particiones 1..5, contexto cambiado, token repetido, EOF por partición y ediciones
   de estrellas; deduplicación no elimina revisiones nuevas.
8. Staging expirado antes de destino: hueco observable y recuperación explícita.
9. Pruebas deterministas sin internet en CI; smoke real separado y opt-in.

## Experimentos que desbloquean la implementación

Código autocontenido: `experiments/playstore/protocol_probe.py`, copiable en Colab.
Sondea tamaños, páginas consecutivas, replay inmediato/diferido y estrellas opcionales;
exporta `report.json`, `checkpoint.json` y respuestas crudas comprimidas opcionales.
Los resultados describen capacidad/estabilidad **observadas**: no establecen un máximo
global ni un TTL garantizado. Aprobar adaptador y política de recuperación después
de revisar los resultados; si no validan la hipótesis, versionar el protocolo.

## Checklist

* [ ] Contratos v2/migración y auditoría de infra implementados.
* [ ] Adaptador validado con fixtures reales y sondeo opt-in; 199 documentado como política.
* [ ] Anual -> FULL conserva páginas/contexto y reconoce recuperación cara cuando toca.
* [ ] Lease + CAS, ledger y publicación al menos una vez probados por inyección de fallos.
* [ ] Estado de transporte y cobertura TDS diferenciados; sin promesas de exhaustividad.
* [ ] Job histórico y API incremental operativos con presupuestos y observabilidad.
* [ ] Ruff, formato, Pyrefly, Bandit y pytest >=85% pasan.

## Referencias técnicas (consulta 2026-10-14)

* [Payload de referencia](https://github.com/JoMingyu/google-play-scraper/blob/master/google_play_scraper/constants/request.py).
* [Mapeo de campos](https://github.com/JoMingyu/google-play-scraper/blob/master/google_play_scraper/constants/element.py).
* [Paginación de referencia](https://github.com/JoMingyu/google-play-scraper/blob/master/google_play_scraper/features/reviews.py).
* [Precondiciones GCS](https://docs.cloud.google.com/storage/docs/request-preconditions).
* [Timeout de Cloud Run](https://docs.cloud.google.com/run/docs/configuring/request-timeout).

Las ramas master son referencias cambiantes, no una especificación de Google.
