# Paso 6. Feature 7.6: Explorador de reseñas, búsqueda semántica y explicación

* **Estado (2026-10-25):** Pendiente.
* **Nivel:** importante.
* **Depende de:** paso 2 y la decisión B5.2 del paso 0 (explicación con dirección).
* **Objetivo:** investigar reseñas y causas raíz (rol analista): una tabla de reseñas sanitizadas que responde a gráficas de agregados (*crossfilter*), búsqueda semántica con `VECTOR_SEARCH` sobre MiniLM y una ficha por reseña con la explicación por palabras. Es la única sección, aparte del HITL, que muestra texto, y **la única que muestra la explicación**.

## 1. Servicio privado `voc-ml-online`

PyTorch, RoBERTuito y MiniLM no caben en la API de 1 GiB, así que van a un servicio aparte con la imagen de `ml-inference`.

* **Código:** `services/ml-inference/src/ml_inference/online.py`, una aplicación FastAPI mínima (se agregan `fastapi` y `uvicorn` a `services/ml-inference/pyproject.toml`), y el comando `serve` en `ml_inference/__main__.py` (`python -m ml_inference serve`, uvicorn en `${PORT}`).

| Método y ruta | Cuerpo | Respuesta |
| :--- | :--- | :--- |
| `POST /explain` | `{ text, model_version }` | `{ model_version, method: "occlusion_v2", attributions: [{ start, end, d_neg, d_neu, d_pos }], p_neg, p_neu, p_pos }` |
| `POST /embed` | `{ text }` | `{ embedding_model, embedding: list[float] }` (384 valores) |
| `GET /healthz` | — | `{ status, loaded: [...] }` |

* Carga cada modelo la primera vez que se usa y lo conserva en memoria: el de sentimiento, desde los pesos de la versión pedida, como lo hace el delta (`engines._RobertuitoEngine`); MiniLM, con `voc_nlp.topics` (sin normalizar, 128 *tokens*, como el delta y el backfill, para que la consulta y los vectores guardados sean comparables).
* Tope de 128 palabras por texto en `/explain`.
* **Infra** (`infra/modules/cloud_run.py`): servicio `voc-ml-online` con la imagen de `ml-inference`, comando `serve`, 2 vCPU, 4 GiB, mínimo 0 y máximo 1 instancias, concurrencia 4, *timeout* de 120 s, *ingress* interno, sin IAP. Cuenta nueva `voc-sa-ml-online` con `roles/storage.objectViewer` en el bucket del datalake **con condición** de prefijo `ml_artifacts/`, y `roles/run.invoker` sobre el servicio solo para `voc-sa-portal-api`.
* **La API lo llama** con un ID token (`google.oauth2.id_token.fetch_id_token(request, audience=ML_ONLINE_URL)`), en `api_backend/online.py` (`OnlineClient.explain(...)` y `OnlineClient.embed(...)`), con *timeout* de 90 s.

### 1.1 Explicación con dirección (`occlusion_v2`)

Se decide en B5.2 del paso 0. Con la recomendación:

* **`packages/voc-nlp/src/voc_nlp/explain.py`:** agregar `occlusion_v2(model, text, temperature, batch_size) -> list[TokenAttributionV2]`. Por cada palabra (`\S+`, igual que `occlusion`), `d_c = p_c(texto) − p_c(texto sin la palabra)` para las tres clases, con las probabilidades **calibradas** por la temperatura de la versión. `d_neg > 0` quiere decir que la palabra empuja hacia `NEG`. `occlusion` (v1) no cambia.
* **Contrato:** `ReviewExplanation.method` acepta `occlusion_v1` y `occlusion_v2`; cada atribución de v2 es `{start, end, d_neg, d_neu, d_pos}`. Cambia `voc_common.operations_v3` y su prueba, y la sección 8 del [contrato v3](../../contracts/analytics_outputs_v3.md).
* **El delta** pasa a precalcular `occlusion_v2` para los casos HITL nuevos (`delta._Steps._hitl`); las filas `occlusion_v1` quedan como historia. Es un port con prueba: un texto sintético con una palabra claramente negativa da `d_neg > 0` en esa palabra.

## 2. API (`sections/reviews/` y `sections/explanations/`)

Todas de rol analista. **Filtros comunes** (`ReviewFilters`): `banks`, `date_from`, `date_to` (la API recorta el rango a `review_window_months`, 12 meses por defecto, y lo dice en la respuesta), `sentiment: list`, `families: list`, `flag_update: bool | None`, `flag_security: bool | None`, `topic_id: str | None`, `stars: list[int]`, `version: str | None`, `hitl_reviewed: bool | None`.

| Método y ruta | Respuesta |
| :--- | :--- |
| `GET /api/v1/reviews/facets` | `Facets`: conteos con los filtros aplicados, por banco, por mes, por sentimiento, por estrellas, por familia, por marca `u` y `s`, por tópico (los 20 principales) y por si pasó por HITL. Solo agregados (`cache=True`) |
| `GET /api/v1/reviews?page=&page_size=&sort=` | `ReviewPage { rows: list[ReviewRow], total, page, page_size, window_applied }`. `page_size` por defecto 50 y máximo 200; `sort` en `fecha_desc` (por defecto), `confidence_asc` o `estrellas_asc` |
| `GET /api/v1/reviews/{bank_id}/{id_resena}` | `ReviewDetail`: la fila completa, más las revisiones HITL del texto (resultado, etiqueta validada y fecha, **sin revisor**) y la explicación disponible (`method`, `model_version`, `source`) |
| `POST /api/v1/reviews/search` | Cuerpo `{ query, banks, months, k }` (`query` de 3 a 300 caracteres; `months` ≤ `review_window_months`; `k` ≤ 50). `SearchResponse { hits: list[SearchHit], embedding_model, months_searched, bytes_billed }` |
| `GET /api/v1/explanations/{text_key}?model_version=` | La explicación guardada (`occlusion_v2` si existe; si no, `occlusion_v1`), o 404 |
| `POST /api/v1/explanations/{text_key}` | Cuerpo `{ bank_id, id_resena }`. Comprueba que el `text_key` coincide con el texto actual, la calcula en `voc-ml-online`, la guarda en `review_explanations` (`source = on_demand`) y la devuelve. Si ya existía para el modelo promovido, la devuelve sin recalcular |

```python
class ReviewRow(BaseModel):
    id_resena: str
    bank_id: str
    text_key: str
    fecha: date
    version_app: str | None
    estrellas: int
    text: str                         # texto_sanitizado
    sentiment: str
    p_neg: float | None; p_neu: float | None; p_pos: float | None
    confidence: float | None
    model_version: str | None
    families: list[str]
    flag_update: bool | None; flag_security: bool | None
    topics: list[TopicRef]            # topic_id y nombre curado
    hitl_reviewed: bool

class SearchHit(BaseModel):
    text_key: str
    bank_id: str
    distance: float                   # coseno: 0 es idéntico
    n_reviews: int                    # reseñas con ese texto en la ventana
    example: ReviewRow                # la reseña más reciente con ese texto
```

### 2.1 Consultas

* **Tabla:** `review_predictions_current` filtrada por fecha y banco, con `LEFT JOIN` a la última fila de `review_aspects` por `id_resena`, a `topic_assignments` (versión de `topic_model_current`, agregadas por `id_resena`) y a `sanitized_reviews_tds` por `id_resena` **y** `TO_HEX(SHA256(t.texto_sanitizado)) = p.text_key`, con el mismo filtro de fecha sobre el TDS para podar sus particiones diarias. `hitl_reviewed` es `EXISTS` en `hitl_reviews` por `id_resena`. Se mide con `dry_run`; el criterio de terminado pide menos de 2 GB por página.
* **Búsqueda:**

```sql
SELECT base.text_key, base.bank_id, base.mes, distance
FROM VECTOR_SEARCH(
  (SELECT text_key, bank_id, mes, embedding FROM `…text_embeddings`
   WHERE mes >= @from_month AND bank_id IN UNNEST(@banks)),
  'embedding',
  (SELECT @query_embedding AS embedding),
  top_k => @k_raw,
  distance_type => 'COSINE')
```

  `@query_embedding` es un `ARRAY<FLOAT64>` como parámetro. La subconsulta sobre `mes` poda particiones: es lo que acota el costo según el [experimento de búsqueda](../../analytics/scale/scale_report.md). `text_embeddings` tiene una fila por texto × banco × mes, así que se pide `k_raw = 3 × k` y se deja un resultado por (`text_key`, `bank_id`). Después se unen las reseñas para `n_reviews` y `example`. Sin índice vectorial: se crea solo si la latencia pasa de 10 s.
* **Texto de la consulta:** no se guarda ni se registra; solo viaja a `voc-ml-online` dentro de GCP.

## 3. Pantalla (`src/sections/explorer/`)

1. **Barra de búsqueda semántica** arriba: "Describe el problema que buscas (por ejemplo: no llega el código para entrar)". Con resultados, la tabla pasa a modo búsqueda: columna de distancia, orden por distancia y un botón "Volver a la tabla".
2. **Gráficas de agregados** (de `facets`), pequeñas y en una fila: reseñas por mes (con *brush* que fija `desde` y `hasta`), por banco, por sentimiento, por estrellas, por familia, por marca y por tópico (los 20 principales). Pulsar una barra agrega el filtro a la URL (`sentimiento`, `estrellas`, `familia`, `u`, `s`, `topico`, `hitl`) y todas las gráficas y la tabla se recalculan. Los filtros activos se ven como fichas que se pueden quitar. Los filtros que llegan del cockpit se aplican al entrar.
3. **Tabla** (`DataTable` con TanStack Table y filas virtualizadas): fecha, banco (seudónimo y color), versión, estrellas, sentimiento con sus probabilidades (barra apilada pequeña), confianza, familias, marcas, tópico, HITL y el texto recortado a dos líneas. Paginación del servidor.
4. **Ficha** (panel lateral al pulsar una fila):
   * texto completo, fecha, versión, estrellas;
   * predicción con sus probabilidades calibradas y `VersionChip` del modelo;
   * familias y marcas con su `prompt_version`; tópicos con su nombre curado;
   * revisiones HITL del texto, si las hay;
   * **explicación:** si existe, se dibuja; si no, el botón "Calcular explicación" (con el aviso "puede tardar hasta un minuto si el servicio estaba en reposo"). Cada palabra lleva de fondo el color de la clase hacia la que empuja (ladrillo hacia `NEG`, verde hacia `POS`), con opacidad proporcional a `|d_pos − d_neg|`; al pasar el cursor, los tres valores. Debajo: la leyenda con su escala, las tres palabras que más empujan hacia cada lado y el texto fijo "Indica qué palabras movieron la predicción del modelo; no es la causa técnica del fallo". Si solo hay `occlusion_v1`, se dibuja en una sola dirección con el aviso "explicación anterior: solo mide cuánto sostiene cada palabra la clase predicha".
5. **Exportación:** solo los agregados de las gráficas, en CSV. No hay descarga de texto.

## 4. Pruebas

* **`voc-nlp`:** `occlusion_v2` con un modelo de prueba determinista (como las pruebas actuales de `explain.py`): signos, posiciones y suma con la temperatura.
* **`ml-inference`:** `online.py` con modelos falsos: contratos de `/explain` y `/embed`, tope de palabras, carga perezosa.
* **API:**
  * 403 para lector y revisor en todas las rutas;
  * la ventana se recorta y se informa;
  * la búsqueda deduplica por texto y banco y ordena por distancia;
  * la consulta no aparece en los registros (se revisa con `caplog`);
  * la explicación bajo pedido verifica el `text_key`, se guarda con `on_demand` y no se recalcula si ya existe;
  * los `facets` no traen texto.
* **Portal:** pulsar una barra filtra la tabla y las demás gráficas (con MSW); la ficha dibuja la explicación con los dos colores y la leyenda; sin explicación aparece el botón; el modo búsqueda muestra la distancia; `axe` sin violaciones.

## Terminado cuando

* [ ] La tabla responde a los filtros dentro de la ventana, con menos de 2 GB facturados por página (anotar la cifra).
* [ ] La búsqueda devuelve vecinos con su distancia en menos de 10 s con el servicio caliente.
* [ ] La ficha muestra la explicación con su versión de modelo; una explicación bajo pedido queda en `review_explanations` con `on_demand`.
* [ ] F-15 (el Explorador amplía quién lee reseñas) queda calificada en la FMEA con los controles de esta sección (rol analista, sin descarga de texto, consultas no registradas, auditoría de BigQuery); se anota en el paso 10.

## Decisiones al implementar

_(Se llena al ejecutar.)_

## Avance

_(Se llena al ejecutar.)_
