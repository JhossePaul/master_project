# ingestion-worker

Features 3.1–3.4: protocolo oCPfdb, cliente HTTP por página, repositorio GCS
con leases/CAS, auditoría, publicación durable, endpoint de progreso y
recorridos reanudables con recuperación. API y Job ejecutables son 3.5.

Desde la raíz:

```sh
uv sync --all-packages --locked --python 3.11
uv run --frozen pytest services/ingestion-worker/tests --cov=ingestion_worker --cov-fail-under=85
```

## Contrato

`build_batchexecute_body` usa JSON y form encoding; conserva el cursor opaco,
filtros y tamaño. Admite tamaños experimentales: 199 es la política de
configuración compartida, no un límite inferido del servidor.
`parse_batchexecute_response` reconoce XSSI, líneas de longitud y un único
frame oCPfdb. Las líneas de longitud se reconocen, no se certifica su valor.
El cursor sale de `inner[1][1]`, previa validación de toda la estructura.
El bloque auxiliar observado se valida contra las fixtures de esta versión;
cambios exigen revisar el adaptador.

Cada resultado incluye snapshots congeladas del contrato compartido,
conteos crudos, descartes explícitos de reseñas sin texto, orden temporal,
cursor, cuerpo original y hash SHA-256. El cuerpo permite respaldar la página
en la siguiente feature; no se imprime en repr. No registrar cuerpos ni cursores.

Clasificaciones: `PAGE_WITH_CURSOR`, `END_CANDIDATE`, `EMPTY_WITH_CURSOR`,
`EMPTY_AMBIGUOUS`. `PROTOCOL_ERROR` es el vocabulario reservado para auditoría;
el adaptador lanza `ProtocolError`, nunca un resultado exitoso vacío por error.
Una página sin texto con cursor permite continuar. Se procesa toda la página
aunque sus fechas estén desordenadas. Ninguna clasificación confirma EOF.

`PlayStoreClient` recibe un `httpx.AsyncClient` cuya vida controla el llamador.
Hace un solo POST, con timeout total, presupuesto de bytes decodificados,
sin redirecciones ni reintentos automáticos. Traduce HTTP 429 a
`RateLimitedError` con Retry-After (segundos o fecha); otros errores HTTP/red
son `TransportError`. HTML y formas desconocidas son `ProtocolError`;
una respuesta vacía ambigua lanza `EmptyAmbiguousError` con la evidencia.
`InvalidCursorError` solo identifica entradas locales inválidas: no tenemos
una muestra que pruebe expiración de cursor en el servidor.

Uso desde código asíncrono (efectúa una petición si se ejecuta):

```python
import httpx
from ingestion_worker import PROTOCOL_VERSION, PlayStoreClient
from voc_common import BankKey, PLAYSTORE_BANK_APPS, ScanContext

async def fetch_one_page():
    context = ScanContext(
        app_id=PLAYSTORE_BANK_APPS[BankKey.BBVA],
        protocol_version=PROTOCOL_VERSION,
    )
    async with httpx.AsyncClient() as http:
        return await PlayStoreClient(http).fetch_page(BankKey.BBVA, context)
```

## Evidencia y límites

`tests/fixtures/observed_014.txt`–`observed_016.txt` son proyecciones pequeñas
de las respuestas compartidas del experimento: mantienen posiciones, fechas,
votos, estructuras de respuesta y metadatos. IDs, usuarios, textos, enlaces,
versiones y cursores se sustituyeron. El manifiesto registra índices originales,
hashes de los originales descomprimidos y de cada fixture, versión y fingerprint
del sondeo local usado como referencia. La referencia externa es
[google-play-scraper request.py](https://github.com/JoMingyu/google-play-scraper/blob/master/google_play_scraper/constants/request.py);
no se importa ni se ejecuta código remoto, ni se depende de ese paquete.

Los casos terminales, errores y límites HTTP se construyen sintéticamente.
Las muestras reales prueban páginas con cursor; no prueban EOF, expiración,
exhaustividad, estabilidad de filtros ni que el cursor represente una snapshot.
`evidence.terminal_confirmed` permanece falso. Para ejecutar recorridos, recuperación y cierre de un plan se necesita 3.4;
3.2 aporta la persistencia, sin inferir EOF del origen.

## Persistencia y progreso (3.2)

`WatermarkRepository` recibe un cliente Storage, bucket, layout compartido,
duración de lease y reloj UTC opcional. Flujo: `acquire_lease`, `register`
(plan y streams juntos), `start_incremental` para una corrida incremental,
`write_review_ledger` y `commit_page` después de confirmar publicación.
`renew_lease` conserva epoch; `release_lease` lo retiene para fencing posterior.
El ejecutor debe renovar antes del vencimiento; aún no hay bucle de extracción.

Un commit exige revisión lógica esperada. Un `StateConflict` requiere cargar
de nuevo y reconciliar; `LeaseConflict` exige abandonar el handle. No recuperar
un lease vencido usando heartbeat. Un reintento de la misma página ya confirmada
es idempotente; una versión distinta bajo el mismo ID/manifiesto falla.

`record_audit(handle, event)` persiste un `IngestionRunAudit` de corrida;
`BigQueryAuditWriter.from_settings(client, settings).flush(repository, bank)`
entrega la cola comprometida, con presupuesto opcional `max_events`.
BQ no es el estado vivo. Un fallo conserva el evento para reintento, y las
consultas deben deduplicar por audit_event_id. El ejecutor de 3.4 será responsable
de producir métricas/eventos y programar entregas.

`ingestion_worker.main:app` expone solamente
`GET /api/v1/watermarks/{bank_id}`. Usa Settings, exige v2 habilitado y crea
credenciales/clientes de forma diferida. Para pruebas, `create_app(repo)`
inyecta un repositorio sin credenciales. Este GET no ejecuta scraping.

Rutas de snapshots, catálogo, índice, cola, garantías CAS y límites en
[el contrato de persistencia](../../docs/contracts/ingestion_v2.md#repositorio-de-epic-3-feature-32).
No hay transacciones multiobjeto ni dependencia de Object Versioning:
la raíz publica referencias a hijos inmutables con un único CAS.

## Publicación durable (3.3)

Con lease y stream registrados, usar `RawReviewBatchPublisher(repo, pubsub, topic)`:

```python
manifest = publisher.prepare_page(
    lease, stream, rpc_page,
    mode=mode, fetched_at=fetched_at, fetch_attempt_id=fetch_attempt_id,
    input_token=input_token,
)
snapshot = publisher.publish_page(lease, manifest)
```

Los identificadores/timestamps de fetch se fijan una vez. Para reanudar tras
caída, cargar `repo.load(bank)`, obtener `repo.pending_capture(snapshot, page_id)`
y `repo.get_manifest(capture.manifest)`; pasar ese manifiesto a publish_page.
La captura se restaura de GCS, sin consultar de nuevo el origen. Un replay del
origen que cambie filas tiene otro page_id.

PublicationIncomplete conserva PENDING/PARTIAL y permite reenviar la página.
StateConflict exige releer/reconciliar; LeaseConflict obliga a abandonar el handle.
BackupUnavailable exige registrar recuperación/hueco, nunca avanzar con conteos.
La preparación y los envíos usan SDKs síncronos: los callers async deben
ejecutarlos en threadpool y serializar heartbeat/commit.

El publisher comprueba todos los futures con presupuesto compartido, mantiene
event_ids entre reenvíos y deja sanitización PENDING. La retención cruda sigue
siendo siete días; el endpoint de progreso expone la edad de los pendientes
mediante fetched_at. La supervisión y recuperación automática pertenecen a 3.4.
El [contrato de página durable](../../docs/contracts/ingestion_v2.md#página-duradera-de-epic-3-feature-33)
describe formato JSONL, estados y límites de entrega.

## Recorridos y recuperación (3.4)

`PlayStoreResilientExtractor(repo, publisher, client, config)` ejecuta una
invocación acotada; `run_extraction(ExtractionRequest(...))` devuelve un
`ExtractionResult` con estado, motivo, contadores, presupuesto consumido,
fronteras observadas/confirmadas y acciones de recuperación.

```python
extractor = PlayStoreResilientExtractor(repo, publisher, client, settings)
result = await extractor.run_extraction(
    ExtractionRequest(bank_id=BankKey.BBVA, mode=IngestionMode.INCREMENTAL)
)
```

Orden de cada invocación: entregar desde GCS las capturas pendientes (de la
misma corrida o de otra, sin consultar el origen), tomar el lease, y luego:

* **Incremental:** reanuda la corrida activa si existe; si no, registra un
  stream nuevo. Recorre desde la cabeza hasta `baseline - 72 h` (bootstrap:
  primera página - 7 días) y solo entonces confirma el high con el ledger
  completo de IDs. Una falla deja el high confirmado intacto.
* **Histórico:** BACKFILL crea un plan con cota `T0 - 365 días`; la página que
  la cruza se guarda completa. FULL extiende el mismo plan (mismo T0, streams
  y anclas) y continúa desde el ancla. El plan cierra cuando todos sus streams
  alcanzan la cota o un EOF observado.
* **Recuperación** al reanudar un stream o ante un cursor rechazado: replay del
  ancla, hasta `INGESTION_RECOVERY_MAX_ANCHORS` anclas anteriores y, si
  ninguna conecta, cadena nueva desde la cabeza. Sin presupuesto de
  recuperación el stream queda `RECOVERY_REQUIRED`.
* **Presupuestos:** solicitudes, páginas, bytes, duración y recuperación; el
  límite de reseñas es blando (se completa la página recibida). Pausa entre
  páginas `base + jitter`; Retry-After/backoff acotado; circuit breaker por
  fallos consecutivos; 403 termina en `BLOCKED` sin reintentar con otro
  User-Agent. El heartbeat renueva el lease entre páginas y durante esperas.
* **Backlog:** `BacklogSignal.should_pause` pausa solo el histórico; la
  implementación por defecto nunca pausa hasta que exista EPIC-4.

`select_user_agent(run_id, config)` devuelve un User-Agent fijo por ejecución
cuando `SCRAPER_ROTATE_USER_AGENT=true`; `PlayStoreClient(user_agent=...)` lo
usa en todas las solicitudes de ese cliente.

Las acciones de recuperación y los estados (`TARGET_REACHED`,
`SOURCE_EXHAUSTED_OBSERVED`, `BUDGET_EXHAUSTED`, `PARTIAL_RATE_LIMITED`,
`PAUSED_BACKLOG`, `PUBLICATION_INCOMPLETE`, `RECOVERY_REQUIRED`,
`PROTOCOL_ERROR`, `BLOCKED`, `TRANSPORT_ERROR`, `LEASE_CONFLICT`) describen
evidencia observada; ninguno certifica cobertura total del catálogo.
Límites conocidos en [EPIC-3 feature 3.4](../../docs/backlog/epic_3.md#feature-34-extracción-y-políticas-de-recuperación).
