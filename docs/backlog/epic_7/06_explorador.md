# Paso 6. Feature 7.6: Explorador de reseñas, búsqueda semántica y explicación

* **Estado (2026-10-26):** Terminado en local, con las consultas probadas contra BigQuery de dev (solo lecturas); `voc-ml-online` ya está desplegado (revisión 00001 con la imagen de `b7aa586`); falta medir la búsqueda con el servicio real. Detalle en "Avance".
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

* [x] La tabla responde a los filtros dentro de la ventana, con menos de 2 GB facturados por página (anotar la cifra). (1.10 GB una página de 12 meses; ver "Avance".)
* [ ] La búsqueda devuelve vecinos con su distancia en menos de 10 s con el servicio caliente. (Las consultas de BigQuery suman unos 6 s; falta medirla con el servicio real.)
* [ ] La ficha muestra la explicación con su versión de modelo; una explicación bajo pedido queda en `review_explanations` con `on_demand`. (Probado con modelos falsos; falta con el servicio real.)
* [x] F-15 (el Explorador amplía quién lee reseñas) queda calificada en la FMEA con los controles de esta sección (rol analista, sin descarga de texto, consultas no registradas, auditoría de BigQuery); se anota en el paso 10. (Controles anotados en F-15; se califica en el paso 10.)

## Decisiones al implementar

* **B5.2 aplicada (2026-10-26, recomendación del paso 0).** `occlusion_v2` calibrada con la temperatura de la versión. Para no cambiar el esquema de BigQuery (`attributions` es una lista de JSON) `TokenAttribution` pasó a tener `weight` (v1) o `d_neg`, `d_neu` y `d_pos` (v2), y `ReviewExplanation` exige la forma que dice su método. El delta precalcula v2; las filas v1 quedan como historia.
* **`voc-ml-online` sin ingress interno.** El paso pedía ingress interno, pero la API no tiene acceso a la VPC y Cloud Run rechaza ahí a quien llega por la URL pública. Queda con ingress abierto y `roles/run.invoker` solo para `voc-sa-portal-api`; sin `allUsers` (prueba de infra). Endurecerlo a ingress interno exige salida por VPC en la API.
* **Temperatura desde `model_versions`.** `/explain` recibe solo `{ text, model_version }`; el servicio lee la temperatura de esa tabla (permiso por tabla para `voc-sa-ml-online`, más `objectViewer` en el bucket condicionado a `ml_artifacts/` y a listar el bucket).
* **Texto de la página en una segunda consulta.** La tabla no une el TDS: trae las filas de la página sin texto y después pide el texto de esas reseñas con la fecha acotada al rango de la página (10 MB). Así la unión no escanea el TDS entero. El texto solo cuenta si su hash es el `text_key` de la predicción; si la reseña cambió, el campo queda vacío y la tabla lo dice.
* **Facets con todos los filtros** (incluidos los de su propia dimensión), como pide el paso: al elegir `NEG`, la gráfica de sentimiento muestra solo `NEG`. Un banco elegido en su gráfica se suma al filtro global de bancos.
* **Sin virtualizar ni TanStack Table:** 50 filas por página no lo piden, y la API de la versión 9 de TanStack Table cambió; es una tabla simple con paginación del servidor. Se reabre si el tamaño de página crece.
* **La consulta de la búsqueda** no va a la URL, a la caché de consultas ni al registro; la mutación no guarda resultados (`gcTime: 0`). La ficha sí va a la URL (`ficha=BANCO:id`): es un identificador, no texto.
* **`bytes_billed`** de la búsqueda lo mide el lector (`stats`), no una consulta aparte.

* **Revisión del autor en dev (2026-10-26): la explicación resaltaba de amarillo y listaba palabras sin efecto.** Dos defectos: las palabras sin intensidad suficiente no tenían fondo y el navegador pinta de amarillo un `<mark>` sin estilo (ahora `bg-transparent`); y con una predicción segura (99 %) quitar una palabra mueve las probabilidades casi nada, así que el signo de una diferencia de 0.001 decidía en qué lista caía una palabra. El portal mide ahora el empuje en log-odds de `POS` contra `NEG` con y sin la palabra (las probabilidades sin ella salen de las del texto y los cambios guardados, `p − d`; no cambia el contrato), pinta solo las palabras que llegan al 15 % del mayor efecto del texto (mínimo 0.05) con intensidad relativa a ese máximo, y las listas "más empujan" usan solo esas. Si ninguna palabra llega, lo dice. La explicación de un texto a 99 % sigue siendo la menos informativa: es lo esperado, no un error.

## Avance

* **Modelo y contrato (2026-10-26):** `occlusion_v2` en `voc_nlp.explain` (4 pruebas: calibración, suma cero, temperatura, texto vacío), `TokenAttribution` y `ReviewExplanation` con las dos formas, contrato v3 actualizado y el delta con `occlusion_v2`.
* **`voc-ml-online` (2026-10-26):** `ml_inference/online.py` (`/explain`, `/embed`, `/healthz`; carga perezosa, un modelo de sentimiento en memoria, tope de 128 palabras, 7 pruebas con modelos falsos), comando `serve` y `fastapi` y `uvicorn` en `ml-inference` (`uv.lock` regenerado).
* **Infraestructura:** cuenta `voc-sa-ml-online`, servicio `voc-ml-online` (2 vCPU, 4 GiB, 0 a 1 instancias, concurrencia 4, 120 s, comando `serve`), invocador solo para la cuenta de la API y `ML_ONLINE_URL` en la API; 3 pruebas nuevas en `test_portal.py` y las de IAM ajustadas. `pulumi up` no se corrió.
* **API:** `sections/reviews/` y `sections/explanations/`, `api_backend/online.py`, `stats` en el lector; 44 pruebas nuevas en `test_reviews.py` (403 de lector y revisor, ventana, filtros, paginación, búsqueda con deduplicación, la consulta ausente de los registros, explicación bajo pedido sin recalcular, `text_key` obsoleto, SQL con poda de particiones). `openapi.json` y `schema.d.ts` regenerados.
* **Portal:** `/explorador` con búsqueda, doce resúmenes (mes con selección por arrastre, banco, sentimiento, estrellas, familia, marcas, tópico y revisión humana), fichas de filtros activos, tabla, ficha lateral con la explicación en dos colores, leyenda y palabras que más empujan, y CSV de agregados; 19 pruebas nuevas (entre ellas `axe` con la ficha abierta). `npm run check`, `tsc`, `npm test` (158) y `npm run build` pasan; el Explorador es un trozo perezoso de 10 KB comprimido.
* **Bytes y tiempos contra BigQuery de dev** (consultas reales de solo lectura, 2026-10-26):

| Consulta | Bytes facturados | Tiempo |
| :--- | ---: | ---: |
| Página de 50 reseñas, 12 meses y los cinco bancos | 1.10 GB | 3.0 s |
| Texto de esas 50 reseñas | 10 MB | 1.1 s |
| Resúmenes (`facets`), 12 meses | 0.55 GB | 4.0 s |
| Página filtrada (un banco, 30 días, `NEG`, 1 o 2 estrellas) | 1.08 GB | 2.6 s |
| Ficha: fecha de la reseña + fila | 0.46 + 1.08 GB | 1.4 + 1.9 s |
| Búsqueda vectorial (12 meses, 5 bancos, 10 vecinos) | 0.77 GB | 2.3 s |
| Reseñas de esos vecinos (`n_reviews` y ejemplo) | 1.10 GB | 2.3 s |

  La vista `review_predictions_current` no deja podar particiones (ya anotado en el cockpit), así que cada consulta que la lee cuesta cerca de 1 GB aunque el rango sea corto; ninguna pasa del tope de 2 GB de la API. La búsqueda completa suma 1.9 GB y unos 6 s antes del servicio de embeddings.
* **Pendiente:** desplegar `voc-ml-online` (imagen nueva de `ml-inference` y `pulumi up`), medir la búsqueda y la explicación con el servicio caliente y frío, y que el autor pruebe el Explorador en dev con una reseña real.
