# EPIC-3: Ingesta Multibanco Reanudable desde Google Play

* **Estado (2026-10-25):** **Cerrada y desplegada** en el stack `dev` (cierre verificado el 2026-10-18, ver [epics.md](epics.md#cierre-de-las-épicas-1-a-4)). La nota siguiente es de cuando se implementó, antes del despliegue.
* **Estado al implementar:** Implementada (features 3.1–3.5). Validada localmente con dobles deterministas; sin despliegue ni solicitudes reales. Adaptador contrastado con respuestas del experimento; agotamiento y expiración de cursor aún no observados.
* **Dependencias:** EPIC-1 y EPIC-2 implementadas: contratos y recursos de estado v2 disponibles. La activación (`INGESTION_V2_ENABLED=true`) espera la imagen publicada, el despliegue por fases de EPIC-2 y el consumidor de EPIC-4.
* **Directorios:** `services/ingestion-worker/`, `packages/voc-common/`, `infra/`, `experiments/playstore/`.

## Objetivo y límites de la garantía

Extraer reseñas textuales de BBVA, Nubank, Santander, Azteca y Banorte mediante
un cliente propio, con respaldo por página, publicación al menos una vez y
recuperación verificable. El endpoint `batchexecute` es interno: no tiene contrato
público de estabilidad, filtros temporales documentados ni garantía de enumerar
el histórico completo. El tamaño 199 fue una política conservadora inicial,
**no un máximo demostrado**; el 2026-10-15 la política pasó a 500 tras validar una
cadena de 10 páginas (ver `docs/operations/full_backfill.md`). Las cifras de la ficha de la app no constituyen
un denominador fiable para calcular el porcentaje de reseñas recuperadas.

La garantía implementable es conservar/reprocesar páginas ya aceptadas mientras
sus respaldos estén disponibles. No se promete cero duplicados en transporte,
ni recuperar registros que el origen deje de exponer. No se confunde el mínimo
observado con cobertura continua, ni un cursor guardado con una snapshot.

## Modelo de estado: progreso lógico y cursor físico son diferentes

### Contratos compartidos de `voc-common` disponibles

Implementar modelos Pydantic con `extra="forbid"`, UTC y `schema_version=2`.
Estos contratos ya están implementados en EPIC-1. El extractor debe consumirlos
directamente e inicializar estado vacío cuando no exista objeto persistido.

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
* El avance se realiza por página mediante un reducer validado, no con llamadas
  por reseña. Permitir borrar explícitamente un cursor terminal.

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
    "stream_ids": ["bbva-es-mx-newest-global-probe"]
  },
  "historical_stream": {
    "stream_id": "bbva-es-mx-newest-global-probe",
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

**Estado: IMPLEMENTADA.** Paquete integrado al workspace y lockfile; adaptador
`ocpfdb-2026-10-15.1`, cliente HTTP asíncrono de una página y pruebas locales.
Fixtures estructurales derivadas de respuestas 014–016, con datos sustituidos
y hashes de procedencia en `tests/fixtures/provenance.json`.
Ver `services/ingestion-worker/README.md` para uso y límites.
El bloque auxiliar observado `[[None, [[1800], None, [72000]]]]` ocupa
`inner[2]`; una forma desconocida falla explícitamente.
No se ha observado una respuesta terminal ni un error de cursor del servidor:
`InvalidCursorError` valida entrada local; ningún HTTP 400 demuestra expiración.
Las formas terminales de los tests son sintéticas y no habilitan EOF confirmado.
Validación: 76 tests del worker y 332 tests conjuntos con contratos/infra,
100% de cobertura de líneas en los módulos medidos; Ruff, Pyrefly y Bandit
aprobados. Las tres respuestas originales completas también se parsearon
localmente: 199 reseñas válidas por respuesta. Sin nuevas peticiones al origen.

### Dependencias y archivos

Workspace `ingestion-worker`, Python >=3.11, hatchling, `voc-common` desde
workspace. Dependencias: FastAPI, uvicorn, `httpx[socks]`, tenacity, clientes GCP
Pub/Sub, Storage y BigQuery y Pydantic v2. Mantener rangos compatibles probados
al implementar y resolver con uv; no instalar `google-play-scraper` en producción.
Implementados: `playstore_protocol.py` y `extractor.py` (3.1),
`watermark_store.py` y `audit.py` (3.2), `publisher.py` (3.3), `runner.py`
(3.4), `runtime.py`, `main.py`, `job.py` y Dockerfile (3.5), con sus tests.
`google-auth`/`requests` llegan como dependencias transitivas de los clientes
GCP; declararlas explícitamente requiere regenerar `uv.lock`.

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

**Estado: IMPLEMENTADA.** `watermark_store.py` aplica el reducer compartido,
CAS y fencing en la misma generación raíz; snapshots inmutables de planes,
streams, catálogo e índice de páginas, ledgers completos y recibos inmutables.
`audit.py` entrega una cola durable de `IngestionRunAudit` a la tabla configurada,
con IDs estables y comprobación de errores por fila. `main.py` expone el GET
de progreso mediante clientes diferidos o repositorio inyectado.
Ver [diseño concreto de persistencia](../contracts/ingestion_v2.md#repositorio-de-epic-3-feature-32).
La producción de eventos/métricas y el heartbeat periódico corresponden al
ejecutor de 3.4; publicación y su confirmación real corresponden a 3.3.
Validación: 102 tests del worker (95.76% de cobertura de líneas),
358 tests conjuntos con contratos/infra aprobados; Ruff, Pyrefly y Bandit
sin errores. Integración real con GCS/BigQuery/IAM pendiente de despliegue.


`WatermarkRepository` implementa lectura del contrato actual, reducer de páginas,
ledger, adquisición/renovación/liberación de lease y CAS por generación GCS.

* Estado actual: `state/watermarks/{bank_id}.json`; planes/streams bajo
  `state/ingestion/{bank_id}/`; manifiestos, ledgers y recibos bajo sus prefijos
  configurados por banco. Usar el layout compartido y las rutas del
  [contrato de almacenamiento](../contracts/ingestion_v2.md), no un prefijo único
  literal. Leer datos y generación consistentemente.
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
  **Infra disponible (feature 2.8):** `ingestion_runs_log_v2` usa el contrato
  `IngestionRunAudit`. Es la única tabla de auditoría de ingesta; no hay tabla
  legado ni migración de datos. Usar `BQ_INGESTION_RUNS_LOG_TABLE`.
  BigQuery no es almacenamiento transaccional del estado vivo.
* Exponer `GET /api/v1/watermarks/{bank_id}` como progreso y cobertura observados,
  con huecos e incertidumbre. No devolver porcentaje ficticio de completitud.

## FEATURE 3.3: Página duradera y publicación al menos una vez

**Estado: IMPLEMENTADA.** `publisher.py` prepara capturas JSONL.gz reproducibles,
registra manifiesto pendiente en el catálogo bajo CAS y publica sobres v2
con atributos estables. Comprueba cada future con un presupuesto compartido de
espera, conserva estados parciales y solo compromete progreso tras PUBLISHED.
El catálogo permite reanudar por page_id sin repetir la petición al origen.
Los descartes NO_TEXT tienen ledger durable sin texto; páginas con filas crudas,
sin texto y con cursor pueden avanzar sin afirmar EOF.
Las versiones de manifiesto son crecientes (pueden tener saltos para distinguir
intentos huérfanos); el page_id y los event_id permanecen estables al reintentar.
El GET de progreso incluye páginas pendientes, fetched_at y sus conteos para
vigilar su antigüedad antes del TTL.
Validación: 118 tests del worker aprobados (94.40% de cobertura de líneas);
374 tests conjuntos con contratos/infra aprobados. Ruff, formato, Pyrefly y
Bandit sin errores. No se ejecutaron solicitudes reales a Pub/Sub/GCS ni se
desplegó el servicio.


`RawReviewBatchPublisher` opera con un `PageManifest`, no con un UUID nuevo por
cada reintento. `page_id` determinista por stream, epoch, input cursor y fingerprint
observado; la misma captura conserva su ID. Un replay cambiado es otra captura.

1. Persistir página completa JSONL.gz con el layout compartido en
   `{GCS_RAW_STAGING_PREFIX}/{bank_id}/{run_id}/{page_id}/{fetch_attempt_id}.jsonl.gz`
   con creación condicional y verificar generación/fingerprint. Si ya existe,
   reutilizar solo si coincide; no sobrescribir una captura diferente.
2. Publicar registros con `event_id`, `page_id`, `source_revision`, banco y modo.
   Confirmar **cada `future.result()`** con timeout; `wait()` por sí solo no basta.
3. Tras confirmar todos, comprometer manifiesto/estado raíz por CAS. Publicación
   parcial o fallo del CAS mantienen posibilidad de replay y duplicados. No hay
   transacción atómica GCS-Pub/Sub; la idempotencia de EPIC-4 cierra esa brecha.
4. Registrar filas sin texto o rechazadas con motivo y conteo. Errores de parser
   invalidan la página completa; no descartar silenciosamente un schema drift.
5. El estado de ingesta (`PUBLISHED`) es distinto de `TDS_COMMITTED` por evento y
   del cierre de página `RESOLVED`/`GAPS_DETECTED` que emite EPIC-4.
   La cobertura TDS solo avanza tras la confirmación de EPIC-4.

La retención cruda de siete días sigue vigente. Supervisar páginas pendientes
antes de expirar. Manifiestos solos no reconstruyen cuerpos borrados: si se
pierden ambas copias antes de confirmar destino, registrar hueco y recuperar
origen; no marcar completitud. El ledger final, sin texto, puede sobrevivir al
TTL del staging para deduplicación y auditoría.

## FEATURE 3.4: Extracción y políticas de recuperación

**Estado: IMPLEMENTADA.** `runner.py` expone `PlayStoreResilientExtractor`,
`ExtractionRequest`/`ExtractionResult` y `BacklogSignal` (por defecto sin
presión: aún no hay consumidor desplegado). Reducers puros nuevos en
`voc_common.ingestion_state`: `reanchor`, `restart_chain`, `close_stream`,
`reopen_stream` y `change_plan_status`; el repositorio los persiste con CAS.
Configuración conservadora nueva en `IngestionExecutionConfig` (páginas,
recuperación, anclas, backoff, circuit breaker, ventana de revisita 72 h,
bootstrap 7 días y rotación opcional de User-Agent por ejecución).
Evidencia usada (`experiments/playstore/evidence/`, no versionada): una corrida BBVA de 16
solicitudes; el replay del cursor fue idéntico a +10 s, +10 min y +30 min
aunque la cabeza cambió; el cursor devuelto cambia en cada respuesta; la
cabeza mostró ±2 reseñas entre solicitudes; tamaños 200 y 500 aceptados.
Sin 429, expiración, EOF ni filtro de estrellas observados: esos caminos se
prueban con un origen simulado.
Validación: 166 tests del worker (95.24% de cobertura), 444 tests conjuntos;
Ruff, formato, Pyrefly y Bandit sin errores. Sin solicitudes reales.

Decisiones y límites conocidos:

* Una ancla es consistente si la relectura conserva IDs y forma de la página;
  con contenido idéntico se versiona el mismo `page_id` con respaldo nuevo
  (el cursor devuelto cambia); con revisiones distintas se publica como
  observación nueva en la misma posición. Ninguna de las dos prueba snapshot.
* Un HTTP 4xx sobre un cursor se trata como síntoma de rechazo e inicia la
  recuperación; no se interpreta como expiración demostrada.
* `HEAD_RESCAN` abre `chain_epoch` nuevo y vuelve a publicar las páginas que
  recorre (al menos una vez); la deduplicación por `event_id` de EPIC-4 cierra
  esa brecha. No se omiten revisiones confirmadas durante el reescaneo.
* El incremental usa un stream por corrida (`inc-{run_id}`); la frontera
  confirmada guarda el ledger completo de IDs de la corrida. Las reseñas de la
  frontera anterior que no reaparecen se cuentan en `reconciliation_missing`
  como evidencia; no bloquean el cierre (la cabeza observada no es estable).
* EOF observado = página sin cursor más relectura consistente sin cursor.
* Un plan anual con particiones donde una alcanza EOF antes de la cota y otra
  la cota no puede cerrarse con el reducer de EPIC-1; queda `PAUSED` con
  `RECOVERY_REQUIRED/plan_mixed_terminal` hasta decidir el contrato.
* El circuit breaker y los reintentos son por invocación; no se persisten.
* La estrategia de particiones (estrellas u otra) sigue en discusión: el
  ejecutor es genérico sobre los streams de un plan. Las fechas no son un
  filtro del endpoint, así que «particionar por fecha» solo puede significar
  tramos sucesivos de un mismo stream.

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

**Estado: IMPLEMENTADA.** `runtime.py` cablea Settings con GCS, Pub/Sub,
BigQuery y un cliente HTTP por invocación (proxy y User-Agent opcionales por
ejecución). `main.py` expone `GET /health`, `GET /api/v1/watermarks/{bank}`,
`POST /api/v1/ingest` y `POST /api/v1/ingest/all`. `job.py` es el Cloud Run
Job histórico. Dockerfile multi-stage (uv, `--frozen --no-dev`, sin editable,
uid 10001) con `.dockerignore` por lista de permitidos: nunca entran `.env`,
`evidence/`, `.git` ni `.venv`. CI añade el job `ingestion-image`, que construye
la imagen amd64 y comprueba entrypoints y usuario; la publicación es del CD.
Validación: 182 tests del worker (95.98% de cobertura), 460 tests conjuntos;
Ruff, formato, Pyrefly y Bandit sin errores. Imagen construida y probada
localmente (`/health` 200, ingest 503 con v2 desactivado, Job sin overrides
termina con 64). Sin despliegue, IAM real ni solicitudes al origen.

Decisiones:

* **Incremental en la petición:** `POST /api/v1/ingest` con `INCREMENTAL` corre
  dentro del presupuesto HTTP (780 s) y responde 200 con el resultado tipado,
  o 409 si otra corrida tiene el lease. `max_reviews_per_run` es límite blando.
  `page_size` distinto del desplegado se rechaza (422): cambiarlo crea stream.
* **`/ingest/all`:** solo incremental (422 para históricos: nunca por cron).
  Bancos únicos en orden, pausa entre bancos, y reparto equitativo del
  presupuesto restante; un banco sin al menos 2×timeout queda `SKIPPED_BUDGET`.
* **Históricos:** `BACKFILL`/`FULL_BACKFILL` persisten el plan con
  `prepare_plan` (crear, o extender el mismo plan a FULL) bajo lease y lanzan
  `jobs.run` con overrides solo de `INGESTION_BANK_ID`, `INGESTION_PLAN_ID` e
  `INGESTION_STREAM_ID` (vacío = todos los streams). Respuesta 202 con plan y
  ejecución; 409 con lease activo o conflicto de plan; 502 si Cloud Run rechaza;
  503 sin Job configurado. `partition_by_stars` exige FULL (ver 3.4). Un plan
  cerrado no se reabre: una nueva solicitud crea otro plan.
* **Job:** continúa solo planes persistidos (nunca crea ni extiende); deriva el
  modo del plan. Salida 0 para fin o pausa con checkpoint (incluye rate limit),
  75 para transitorios reintentables (publicación incompleta, transporte,
  lease), 1 para intervención (recuperación, protocolo, bloqueo), 64 para
  configuración inválida y 143 tras SIGTERM (cancelación best effort).
  Log final JSON de una línea, sin cursores ni textos.
* La auditoría se entrega a BigQuery al final de cada corrida (best effort);
  la cola GCS conserva lo no entregado.

* `GET /health`; `POST /api/v1/ingest` individual; `POST /api/v1/ingest/all`
  secuencial, compatible con Scheduler. Las peticiones cortas usan los contratos
  compartidos ampliados/versionados; los resultados no prometen cero duplicados.
* **Iniciales largas:** CLI `python -m ingestion_worker.job` ejecutado como Cloud
  Run Job, con plan/stream y presupuesto. No usar FastAPI BackgroundTasks como
  persistencia. El servicio HTTP actual tiene timeout 900s y CPU bajo demanda:
  no da continuidad a un histórico largo después de responder o de un 504.
* Infra declarada en EPIC-2 2.9: Job histórico, perfiles y permiso de ejecución
  con overrides para la API de ingesta. Implementar el módulo `ingestion_worker.job`,
  la API lanzadora y el lease; publicar/verificar la imagen antes de activar v2.
  Usar los IDs/variables del contrato compartido; no activar históricos con cron.
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

Cobertura de la lista: (1) `tests/test_extractor.py`; (2)–(8)
`tests/test_runner.py` con origen simulado, GCS con generaciones y Pub/Sub
con fallos inyectados; (5) también `tests/test_watermark_store.py`. El smoke
real opt-in sigue siendo `experiments/playstore/protocol_probe.py`; no corre
en CI.

## Experimentos que desbloquean la implementación

Código autocontenido: `experiments/playstore/protocol_probe.py`, copiable en Colab.
Sondea tamaños, páginas consecutivas, replay inmediato/diferido y estrellas opcionales;
exporta `report.json`, `checkpoint.json` y respuestas crudas comprimidas opcionales.
Los resultados describen capacidad/estabilidad **observadas**: no establecen un máximo
global ni un TTL garantizado. Aprobar adaptador y política de recuperación después
de revisar los resultados; si no validan la hipótesis, versionar el protocolo.

## Checklist

* [x] Contratos actuales y auditoría de infraestructura implementados.
* [x] Adaptador validado con fixtures reales y sondeo opt-in; 199 documentado como política.
* [x] Anual -> FULL conserva páginas/contexto y reconoce recuperación cara cuando toca.
* [x] Lease + CAS, ledger y publicación al menos una vez probados por inyección de fallos.
* [x] Estado de transporte y cobertura TDS diferenciados; sin promesas de exhaustividad.
* [x] Job histórico y API incremental implementados con presupuestos y observabilidad
  (validados localmente; integración real con Cloud Run/IAM pendiente de despliegue).
* [x] Ruff, formato, Pyrefly, Bandit y pytest >=85% pasan.

Pendiente fuera de esta épica: publicar la imagen por digest y desplegar por
fases (EPIC-2), activar v2 tras integrar el consumidor (EPIC-4), una prueba
real de `jobs.run` con overrides y la decisión sobre particiones.

## Referencias técnicas (consulta 2026-10-14)

* [Payload de referencia](https://github.com/JoMingyu/google-play-scraper/blob/master/google_play_scraper/constants/request.py).
* [Mapeo de campos](https://github.com/JoMingyu/google-play-scraper/blob/master/google_play_scraper/constants/element.py).
* [Paginación de referencia](https://github.com/JoMingyu/google-play-scraper/blob/master/google_play_scraper/features/reviews.py).
* [Precondiciones GCS](https://docs.cloud.google.com/storage/docs/request-preconditions).
* [Timeout de Cloud Run](https://docs.cloud.google.com/run/docs/configuring/request-timeout).

Las ramas master son referencias cambiantes, no una especificación de Google.
