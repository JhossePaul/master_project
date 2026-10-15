# ingestion-worker

Features 3.1–3.3: protocolo oCPfdb, cliente HTTP por página, repositorio GCS
con leases/CAS, auditoría, publicación durable y endpoint de progreso.
Recorridos y ejecutables de extracción corresponden a 3.4–3.5.

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
