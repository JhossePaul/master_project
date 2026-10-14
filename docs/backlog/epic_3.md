# EPIC-3: Ingesta Paralela Multibanco desde Google Play Store (Scraper Propio Tolerante a Fallas)

* **Estado:** Pendiente
* **Semanas Objetivo:** Semana 2
* **Paquetes / Directorios Afectados:**
  * `services/ingestion-worker/pyproject.toml`
  * `services/ingestion-worker/Dockerfile`
  * `services/ingestion-worker/src/ingestion_worker/__init__.py`
  * `services/ingestion-worker/src/ingestion_worker/playstore_protocol.py`
  * `services/ingestion-worker/src/ingestion_worker/extractor.py`
  * `services/ingestion-worker/src/ingestion_worker/watermark_store.py`
  * `services/ingestion-worker/src/ingestion_worker/publisher.py`
  * `services/ingestion-worker/src/ingestion_worker/main.py`
  * `services/ingestion-worker/tests/__init__.py`
  * `services/ingestion-worker/tests/test_playstore_protocol.py`
  * `services/ingestion-worker/tests/test_extractor_and_recovery.py`
  * `services/ingestion-worker/tests/test_api_main.py`
* **Dependencias Previas:** `EPIC-1` (`voc-common` disponible en el workspace).

---

## 🎯 Contexto y Reglas Arquitectónicas para el Agente IA

Esta épica construye el microservicio contenerizado `services/ingestion-worker/` encargado de extraer las reseñas públicas de Google Play Store para `BBVA`, `NUBANK`, `SANTANDER`, `AZTECA` y `BANORTE`[cite: 1, 8].

En lugar de utilizar la librería externa `google-play-scraper` (cuyo `urllib.request` síncrono se bloquea ante *rate limits* y pierde el progreso en memoria), el Agente IA **DEBE implementar un motor de extracción propio** basado en la especificación exacta del protocolo RPC `batchexecute` (`oCPfdb`) de Google Play con las siguientes **5 Garantías de Resiliencia y Gobierno**:

1. **Checkpointing Atómico por Página (Tolerancia a Fallas Total):**
   * Jamás acumular miles de reseñas en una lista en memoria antes de guardar.
   * El flujo obligatorio dentro del bucle de extracción es **Página por Página (máximo 199 reseñas por lote RPC)**:
     `Extraer 1 página RPC` $\rightarrow$ `Validar con RawReviewEvent` $\rightarrow$ `Publicar lote en Cloud Pub/Sub` $\rightarrow$ `Actualizar y persistir IngestionWatermarkState (con oldest_page_token, min_review_timestamp y max_review_timestamp) en Cloud Storage`.
2. **Evasión de Rate Limit y Recuperación Elegante (*Graceful Degradation*):**
   * Cada petición HTTP hacia `/_/PlayStoreUi/data/batchexecute` debe rotar el encabezado `User-Agent` (desde `DEFAULT_USER_AGENTS`), inyectar cabeceras realistas (`Accept-Language: es-MX,es;q=0.9`, `Origin: https://play.google.com`) y soportar rotación de proxies HTTP/SOCKS5 (`scraper_proxy_pool_urls`).
   * Entre página y página se debe aplicar una pausa de `scraper_base_delay_sec + random.uniform(0, scraper_max_jitter_sec)`.
   * Si Google Play responde con `HTTP 429 (Too Many Requests)`, `HTTP 503`, `HTTP 403` o devuelve un bloque vacío inesperado (estrangulamiento silencioso), el cliente debe rotar al siguiente proxy del pool y reintentar con *Exponential Backoff + Jitter* (hasta `scraper_max_retries`).
   * Si se agotan los reintentos por bloqueo de IP, **el worker NO debe crashear perdiendo el estado**: debe persistir el `IngestionWatermarkState` con el `oldest_page_token` pendiente en Cloud Storage, registrar el evento en BigQuery y devolver un estado estructurado `status="PARTIAL_RATE_LIMITED"` para que la siguiente corrida retome exactamente desde ese `page_token`.
3. **Soporte para los 3 Modos de Ingesta (`INCREMENTAL`, `BACKFILL`, `FULL_BACKFILL`):**
   * **`INCREMENTAL`:** Empieza siempre desde `page_token=None` (reseñas más nuevas de hoy hacia atrás) y corta el bucle en cuanto `watermark.should_stop_incremental(review.id_resena, review.fecha)` sea `True`.
   * **`BACKFILL` (1 año):** Si `watermark.oldest_page_token` existe y `not watermark.backfill_one_year_completed`, retoma directamente desde `oldest_page_token` hacia el pasado hasta que `watermark.has_reached_one_year_backfill(review.fecha)` sea `True`, momento en el que marca `backfill_one_year_completed = True`.
   * **`FULL_BACKFILL` (Exhaustivo):** Retoma desde `watermark.oldest_page_token` (o itera por particiones de estrellas `1..5` usando `watermark.star_partition_tokens`) hasta que Google Play devuelva `next_page_token = None` de forma legítima, marcando `full_backfill_completed = True`.
4. **Respaldo de Carga Cruda en Data Lake (Capa de Integración):**
   * Además de publicar cada lote de `RawReviewEvent` en `Cloud Pub/Sub` (`voc-raw-reviews-topic`)[cite: 11, 13], el publicador escribe un archivo comprimido JSONL (`.jsonl.gz`) del lote en `gs://<gcs_raw_datalake_bucket>/raw_staging/{bank_id}/{date}/{batch_uuid}.jsonl.gz` para cumplir con la Capa 2 del diagrama de arquitectura [*Almacenamiento crudo en Cloud Storage Data Lake*](cite: 11, 12).
5. **Exposición Dual (Individual y Secuencial para Free Tier):**
   * Exponer en FastAPI los endpoints `POST /api/v1/ingest` (para un banco individual) y `POST /api/v1/ingest/all` (para iterar secuencialmente sobre los 5 bancos con pausa intermedia en modo *Free Tier*).

---

## 📦 Desglose de Features e Historias Técnicas

### FEATURE 3.1: Configuración del Servicio `ingestion-worker` y Protocolo `batchexecute` (`playstore_protocol.py`)

**Objetivo:** Configurar las dependencias del microservicio y programar el serializador/parser puro del protocolo interno de Google Play Store basado en `constants/request.py`, `constants/regex.py` y `constants/element.py` de `google-play-scraper`.

#### Tarea 3.1.1: Configurar `services/ingestion-worker/pyproject.toml`

Escribir `services/ingestion-worker/pyproject.toml`:

```toml
[project]
name = "ingestion-worker"
version = "0.1.0"
description = "Worker Cloud Run para extraccion resiliente de resenas en Google Play Store y publicacion en Pub/Sub"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110.0,<1.0.0",
    "uvicorn[standard]>=0.28.0,<1.0.0",
    "httpx[socks]>=0.27.0,<1.0.0",
    "tenacity>=8.2.3,<10.0.0",
    "google-cloud-pubsub>=2.21.0,<3.0.0",
    "google-cloud-storage>=2.16.0,<3.0.0",
    "google-cloud-bigquery>=3.20.0,<4.0.0",
    "pydantic>=2.6.0,<3.0.0",
    "voc-common",
]

[tool.uv.sources]
voc-common = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

```

#### Tarea 3.1.2: Implementar `services/ingestion-worker/src/ingestion_worker/playstore_protocol.py`

Implementar la codificación de payloads y extracción posicional segura:

1. **Generación de URL y Payload (`build_batchexecute_request`):**

* Función `build_batchexecute_url(lang: str = "es", country: str = "mx") -> str`:
* Retorna `f"{PLAYSTORE_BATCHEXECUTE_URL}?hl={lang}&gl={country}"`.

* Función `build_batchexecute_body(app_id: str, sort_order: PlayStoreSortOrder = PlayStoreSortOrder.NEWEST, count: int = 199, filter_score_with: int | None = None, filter_device_with: int | None = None, page_token: str | None = None) -> bytes`:
* Basado exactamente en `Formats.Reviews` de `google-play-scraper/constants/request.py`:
* Si `score` o `device` son `None`, en el payload interno se representan con la cadena literal `"null"`.
* **Cuando `page_token is None` (Primera página):**

```python
inner_payload = f'[[null,[2,{ int(sort_order) },[{count}],null,[null,{score_str},null,null,null,{device_str}]],["{app_id}",7]]]'

```

* **Cuando `page_token is not None` (Páginas subsecuentes con cursor):**

```python
inner_payload = f'[[null,[2,{ int(sort_order) },[{count},null,"{page_token}"],null,[null,{score_str},null,null,null,{device_str}]],["{app_id}",7]]]'

```

* Escapar comillas dobles en `inner_payload` (o serializar con `json.dumps(["oCPfdb", inner_payload, None, "generic"])`) y envolver en `f"f.req={urllib.parse.quote(outer_json)}".encode("utf-8")`.

1. **Extracción Regex y Mapeo Posicional (`parse_batchexecute_response`):**

* Expresión regular pre-compilada basada en `Regex.REVIEWS`:

```python
_WRB_FR_REGEX = re.compile(r"\)]}'\n\n([\s\S]+)")

```

* Función `parse_batchexecute_response(raw_text: str, bank_id: BankKey, app_id: str) -> tuple[list[RawReviewEvent], str | None]`:
* Elimina el prefijo de seguridad XSS `)]}'\n\n`, localiza la línea JSON que contiene `"wrb.fr"` y `"oCPfdb"`, y ejecuta `parsed_root = json.loads(line)`.
* Extrae el payload interno: `inner_data = json.loads(parsed_root[0][2])`.
* Si `inner_data` está vacío o no tiene elementos: retorna `([], None)`.
* La lista de reseñas crudas se encuentra en `raw_reviews_list = inner_data[0]` (si existe).
* El `next_page_token: str | None` se extrae de forma segura desde `inner_data[-1][-1]` si `isinstance(inner_data[-1], list) and len(inner_data[-1]) > 0 and isinstance(inner_data[-1][-1], str)` (exactamente como `token = _nested_lookup(dom, [-1, -1])` en `google-play-scraper`).
* Para cada elemento `entry` en `raw_reviews_list`, extrae con una función auxiliar segura `_nested_lookup(obj: Any, indexes: list[int], default: Any = None) -> Any` (equivalente a `ElementSpec.extract_content`):
* `id_resena`: `_nested_lookup(entry, [0])`
* `usuario`: `_nested_lookup(entry, [1, 0]) or "Usuario de Google"`
* `imagen_usuario`: `_nested_lookup(entry, [1, 1, 3, 2])`
* `estrellas`: `int(_nested_lookup(entry, [2], 0))`
* `votos_utilidad`: `int(_nested_lookup(entry, [3], 0))`
* `texto`: `_nested_lookup(entry, [4]) or ""`
* `fecha`: `datetime.fromtimestamp(_nested_lookup(entry, [5, 0]), tz=timezone.utc)`
* `texto_respuesta`: `_nested_lookup(entry, [7, 1])`
* `fecha_respuesta`: `datetime.fromtimestamp(ts, tz=timezone.utc)` si `ts := _nested_lookup(entry, [7, 2, 0])` existe, si no `None`.
* `version_app`: `_nested_lookup(entry, [10]) or "UNKNOWN"`

* Filtra cualquier reseña cuyo `texto.strip()` esté vacío (reseñas sin comentario textual) e instancia `RawReviewEvent` de `voc-common`.

---

### FEATURE 3.2: Almacén de Estado y Continuidad (`watermark_store.py`)

**Objetivo:** Gestionar la lectura y escritura atómica del estado de paginación (`IngestionWatermarkState`) en Cloud Storage y el registro de linaje en BigQuery para garantizar la continuidad del proceso ante interrupciones o bloqueos.

#### Tarea 3.2.1: Implementar `services/ingestion-worker/src/ingestion_worker/watermark_store.py`

Crear la clase `WatermarkRepository`:

```python
class WatermarkRepository:
    def __init__(self, settings: Settings, storage_client: storage.Client | None = None, bq_client: bigquery.Client | None = None) -> None:

```

1. **`load_watermark(self, bank_id: BankKey) -> IngestionWatermarkState`**:

* Busca el blob `f"{self.settings.gcs_watermark_prefix}/{bank_id.value}.json"` en el bucket `self.settings.gcs_raw_datalake_bucket`.
* Si no existe (primera ejecución histórica), devuelve una instancia limpia de `IngestionWatermarkState(bank_id=bank_id, app_id=PLAYSTORE_BANK_APPS[bank_id])`.
* Si existe, descarga el JSON y lo valida con `IngestionWatermarkState.model_validate_json(...)`.

1. **`save_watermark_checkpoint(self, state: IngestionWatermarkState) -> None`**:

* Se invoca **después de cada lote (página) exitoso** o al capturar un corte por *rate limit*.
* Actualiza `state.updated_at = datetime.now(timezone.utc)` y sube el JSON de forma atómica a `gs://<bucket>/state/watermarks/{bank_id.value}.json`.

1. **`log_run_to_bigquery(self, state: IngestionWatermarkState, mode: IngestionMode, extracted_in_run: int, status: str) -> None`**:

* Al finalizar la ejecución del banco, inserta una fila de auditoría en la tabla `ingestion_watermarks_log` de BigQuery.

---

### FEATURE 3.3: Publicador por Lotes hacia Pub/Sub y Respaldo en Data Lake (`publisher.py`)

**Objetivo:** Publicar asíncronamente los lotes de `RawReviewEvent` en Cloud Pub/Sub e inyectar el respaldo crudo en Cloud Storage (Data Lake) antes de avanzar el cursor del watermark.

#### Tarea 3.3.1: Implementar `services/ingestion-worker/src/ingestion_worker/publisher.py`

Crear la clase `RawReviewBatchPublisher`:

1. **`publish_page_batch(self, events: list[RawReviewEvent], bank_id: BankKey, mode: IngestionMode) -> int`**:

* Si `events` está vacío, retorna `0`.
* **Paso 1 (Respaldo en Data Lake - Capa 2):** Serializa la lista de `RawReviewEvent` en formato JSON Lines comprimido con `gzip` y la sube a `gs://{bucket}/{gcs_raw_staging_prefix}/{bank_id.value}/{fecha_utc_iso}/{batch_id}.jsonl.gz`.
* **Paso 2 (Emisión a Cloud Pub/Sub - Capa 1):**
* Publica cada `event.model_dump_json().encode("utf-8")` en `projects/{project_id}/topics/{pubsub_raw_reviews_topic}` adjuntando como atributos del mensaje:
* `bank_id=event.bank_id.value`
* `app_id=event.app_id`
* `id_resena=event.id_resena`
* `version_app=event.version_app`
* `ingestion_mode=mode.value`

* Espera la confirmación de los futuros (`concurrent.futures.wait`) antes de retornar `len(events)` para garantizar **Entrega Al Menos Una Vez (*At-Least-Once Delivery*)** antes de actualizar el watermark.

---

### FEATURE 3.4: Motor de Extracción Resiliente con Rotación de Proxies y Reintentos (`extractor.py`)

**Objetivo:** Orquestar la extracción paginada combinando el protocolo RPC, la rotación de IPs/User-Agents, el corte temprano por watermark y la recuperación ante *throttling*.

#### Tarea 3.4.1: Implementar Excepciones y Resultado de Ejecución en `extractor.py`

Definir:

* `class PlayStoreRateLimitError(Exception)`: Lanzada cuando Google Play responde con HTTP 429, 503, 403 o bloquea la IP.
* `class IngestionRunResult(BaseModel)`:
* `bank_id: BankKey`
* `app_id: str`
* `mode: IngestionMode`
* `status: Literal["COMPLETED", "PARTIAL_RATE_LIMITED", "MAX_LIMIT_REACHED"]`
* `reviews_extracted: int`
* `pages_fetched: int`
* `resumed_from_token: str | None`
* `last_saved_token: str | None`
* `max_review_timestamp: datetime | None`
* `min_review_timestamp: datetime | None`

#### Tarea 3.4.2: Implementar `PlayStoreResilientExtractor` en `extractor.py`

```python
class PlayStoreResilientExtractor:
    def __init__(
        self,
        settings: Settings,
        watermark_repo: WatermarkRepository,
        publisher: RawReviewBatchPublisher,
    ) -> None:

```

1. **Rotador de Clientes HTTP y Proxies (`_get_http_headers` y `_get_current_proxy`):**

* Mantiene un índice rotatorio sobre `settings.scraper_proxy_pool_urls` (si la lista no está vacía).
* En cada petición o tras cada `scraper_rotate_proxy_every_n_batches` lotes, o **inmediatamente si ocurre un `PlayStoreRateLimitError**`, avanza al siguiente proxy del pool y selecciona un `User-Agent` distinto de `DEFAULT_USER_AGENTS`.

1. **Petición RPC con Backoff Exponencial y Jitter (`_fetch_single_rpc_page`):**

* Utiliza `httpx.AsyncClient(proxy=current_proxy, timeout=settings.scraper_timeout_sec)`.
* Envuelto con lógica de reintentos de `tenacity` (`stop_after_attempt(settings.scraper_max_retries)`, `wait_random_exponential(multiplier=settings.scraper_base_delay_sec, max=60.0)`):
* Si el código HTTP es `429`, `503` o `403`, rota el proxy en el `before_sleep` hook y lanza `PlayStoreRateLimitError`.
* Parsea la respuesta con `parse_batchexecute_response(...)`.

1. **Flujo de Continuidad y Recuperación en `run_extraction(self, payload: IngestionRequestPayload) -> IngestionRunResult`:**

* Carga el estado actual: `watermark = self.watermark_repo.load_watermark(payload.bank_id)`.
* **Selección del Cursor Inicial según el Modo:**
* Si `payload.mode == IngestionMode.INCREMENTAL`:
* `current_token = None` (siempre inicia en la página 1 de las más recientes).

* Si `payload.mode in (IngestionMode.BACKFILL, IngestionMode.FULL_BACKFILL)`:
* Si `watermark.oldest_page_token` no es `None`, **retoma directamente desde `current_token = watermark.oldest_page_token**` (evitando volver a descargar páginas que ya se extrajeron en ejecuciones previas). Si es `None`, inicia en `None`.

* **Bucle de Paginación Tolerante a Fallas (`while total_extracted < payload.max_reviews_per_run:`):**
* Intenta `_fetch_single_rpc_page(app_id, page_token=current_token)`.
* **Si captura `PlayStoreRateLimitError` tras agotar todos los reintentos y proxies:**
* Guarda `watermark.oldest_page_token = current_token` en Cloud Storage (`save_watermark_checkpoint`).
* Registra en BigQuery con estado `"PARTIAL_RATE_LIMITED"`.
* Retorna `IngestionRunResult(status="PARTIAL_RATE_LIMITED", last_saved_token=current_token, ...)` sin lanzar excepción HTTP 500, asegurando que ningún lote previo se pierda y dejando listo el token para la siguiente ejecución.

* **Filtrado y Deduplicación lote por lote:**
* Para cada `review` en el lote descargado:
* En modo `INCREMENTAL`: si `watermark.should_stop_incremental(review.id_resena, review.fecha)` es `True`, marca `stop_pagination = True` y rompe el bucle interno (no incluye ni republica reseñas ya vistas).
* En modo `BACKFILL` (1 año): si `review.id_resena in watermark.oldest_review_ids`, la omite por duplicada; si `watermark.has_reached_one_year_backfill(review.fecha)` es `True`, marca `watermark.backfill_one_year_completed = True`, `stop_pagination = True` y rompe el bucle interno.
* En modo `FULL_BACKFILL`: omite si `review.id_resena in watermark.oldest_review_ids`.

* **Persistencia Inmediata del Lote Válido:**
* Publica las reseñas nuevas del lote con `self.publisher.publish_page_batch(new_reviews, ...)`.
* Actualiza el `watermark.update_bounds(...)` guardando `next_page_token` como nuevo `oldest_page_token` (si estamos en `BACKFILL` o `FULL_BACKFILL`, o si es la primera corrida histórica).
* Llama a `self.watermark_repo.save_watermark_checkpoint(watermark)` **en esa misma iteración**.

* Si `stop_pagination` es `True` o `next_page_token is None`:
* Si estábamos en `FULL_BACKFILL` y `next_page_token is None`, marca `watermark.full_backfill_completed = True` y guarda el watermark.
* Termina el bucle con `status="COMPLETED"`.

* Aplica pausa anti-throttling: `await asyncio.sleep(settings.scraper_base_delay_sec + random.uniform(0, settings.scraper_max_jitter_sec))`.

---

### FEATURE 3.5: API HTTP en FastAPI, Contenedor Docker y Suite de Pruebas (`main.py`, `Dockerfile`, `tests/`)

**Objetivo:** Exponer los endpoints para Cloud Scheduler / invocaciones manuales, empaquetar el contenedor Docker usando `uv` y garantizar cobertura $\ge 80\%$.

#### Tarea 3.5.1: Implementar `services/ingestion-worker/src/ingestion_worker/main.py`

Crear la aplicación FastAPI con los siguientes endpoints:

1. **`GET /health`**: Retorna `{"status": "healthy", "service": "ingestion-worker"}`.
2. **`POST /api/v1/ingest`**:

* Recibe `payload: IngestionRequestPayload`.
* Ejecuta `await extractor.run_extraction(payload)` y retorna `IngestionRunResult`.

1. **`POST /api/v1/ingest/all`** (Endpoint para el Job Maestro de Free Tier):

* Recibe `payload: SequentialBatchIngestionRequest`.
* Itera secuencialmente sobre `payload.banks` (`BBVA`, `NUBANK`, `SANTANDER`, `AZTECA`, `BANORTE`), ejecutando `run_extraction` para cada uno y esperando `await asyncio.sleep(payload.inter_bank_delay_sec)` entre bancos para evitar bloqueo de IP.
* Retorna `list[IngestionRunResult]`.

1. **`GET /api/v1/watermarks/{bank_id}`**:

* Devuelve el `IngestionWatermarkState` actual almacenado en Cloud Storage para monitoreo de qué porcentaje de historia se ha recuperado de cada banco.

#### Tarea 3.5.2: Implementar `services/ingestion-worker/Dockerfile`

Construir un `Dockerfile` multi-stage optimizado con `ghcr.io/astral-sh/uv:python3.11-bookworm-slim`, usuario no-root (`appuser`) para aprobar el escaneo de seguridad de `Bandit`/Docker, instalando `voc-common` y `ingestion-worker` desde el workspace y exponiendo el puerto `8080` con `uvicorn ingestion_worker.main:app --host 0.0.0.0 --port 8080`.

#### Tarea 3.5.3: Suite de Pruebas Unitarias y de Recuperación (`services/ingestion-worker/tests/`)

El Agente IA debe escribir pruebas exhaustivas usando `pytest` y `respx` / `unittest.mock` (sin realizar llamadas reales a internet ni a GCP):

1. **`test_playstore_protocol.py`**:

* Validar que `build_batchexecute_body` genere el payload exacto con y sin `page_token`.
* Simular una respuesta real de `batchexecute` con prefijo `)]}'\n\n` y estructura `["wrb.fr","oCPfdb", ...]` verificando que `parse_batchexecute_response` extraiga correctamente el `id_resena`, `texto`, `estrellas`, `version_app`, `votos_utilidad` y el `next_page_token` en Base64, filtrando reseñas sin texto.

1. **`test_extractor_and_recovery.py`**:

* **Test de Corte Incremental (`INCREMENTAL`):** Simular una página con 5 reseñas donde las primeras 3 son nuevas y la 4ta tiene un `id_resena` ya presente en `watermark.recent_review_ids`. Comprobar que solo se publican 3 reseñas en Pub/Sub, se detiene la paginación en la página 1 y se actualiza `max_review_timestamp`.
* **Test de Fallo por Rate Limit y Recuperación (`BACKFILL`):**
* *Corrida 1:* Simular que la Página 1 (`token="TOKEN_P1"`) responde HTTP 200 con 2 reseñas, pero la Página 2 responde `HTTP 429 Too Many Requests` en todos los reintentos. Verificar que el extractor rota los proxies del pool, publica las 2 reseñas de la Página 1, guarda `oldest_page_token="TOKEN_P1"` en el watermark y retorna `status="PARTIAL_RATE_LIMITED"`.
* *Corrida 2:* Volver a llamar `run_extraction` con el watermark guardado. Verificar que **no** vuelve a pedir la Página 1 (`token=None`), sino que arranca pidiendo directamente `page_token="TOKEN_P1"` hasta llegar a 1 año atrás (`has_reached_one_year_backfill == True`) y retorna `status="COMPLETED"`.

1. **`test_api_main.py`**:

* Probar `POST /api/v1/ingest` y `POST /api/v1/ingest/all` mediante `fastapi.testclient.TestClient`.

---

## ✅ Criterios de Aceptación de la Épica 3 (Checklist de Verificación)

* [ ] Cero dependencia del paquete `google-play-scraper`: toda la comunicación con Google Play se realiza vía `playstore_protocol.py` y `httpx` con soporte de proxies y rotación de `User-Agent`.
* [ ] Si ocurre un error HTTP 429/503 a mitad de un `BACKFILL` o `FULL_BACKFILL`, las páginas previas ya están publicadas en Pub/Sub y respaldadas en GCS, y el `oldest_page_token` queda guardado en `gs://<bucket>/state/watermarks/{bank_id}.json` para reanudar sin pérdida ni duplicación.
* [ ] Los comandos `uv run ruff check services/ingestion-worker`, `uv run pyrefly check`, `uv run bandit -c pyproject.toml -r services/ingestion-worker` y `uv run pytest services/ingestion-worker/tests --cov=services/ingestion-worker/src --cov-fail-under=85` pasan con **0 errores**.
