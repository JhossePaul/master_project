# Paso 4. Feature 7.7 (parte imprescindible): HITL de sentimiento

* **Estado (2026-10-26):** Terminado en local y probado contra BigQuery de dev (solo lecturas); falta la revisión real del autor en dev (casillas 2 y 3). Detalle en "Avance".
* **Nivel:** imprescindible.
* **Depende de:** paso 2 y la decisión B5.1 del paso 0 (revisión "no evaluable").
* **Objetivo:** el equivalente en el portal del prototipo `experiments/analytics/src/voc_analytics/annotation/app.py`: el revisor entra y ve su cola, revisa un caso a la vez con la guía vigente a la vista y guarda su decisión en `hitl_reviews` con su modo, su guía y su tiempo. **La muestra de monitoreo y todo caso que pueda entrar al oro van a ciegas, y la explicación nunca se muestra aquí.**

## 1. Lo que hay en dev

* 497 casos `task = sentiment`: 197 `low_confidence` (`display_mode = assisted`, `priority = 1 − confidence`) creados por el delta, y 300 `monitor_sample` (`blind`, con la prioridad fija de las muestras) creados por el monitor. Cada lunes el monitor puede crear más, y cada día el delta.
* `hitl_queue` da el último estado de cada caso (`status`, `actor_hash`, `status_at`).
* `guidelines` tiene la `v2.2` de sentimiento (`content_uri = docs/analytics/labeling/annotation_guideline.md`) y la `v2.1` de aspectos.
* Lo que usan estas revisiones después: el κ trimestral del monitor (las `monitor_sample` de primera ronda), la tasa de corrección (las `low_confidence`), el reentrenamiento (las `low_confidence` y `drift_boost` sin `no_evaluable`) y el oro desde el HITL (paso 5).

## 2. Reglas de la cola

* **Quién:** rol revisor con `sentiment` en `reviewer_tasks`.
* **Orden:** `priority` descendente (primero las muestras, luego la menor confianza) y, a igual prioridad, `created_at`.
* **Tomar un caso:** al pedir el siguiente, la API escribe un evento `in_review` con el `actor_hash` del revisor. Ese caso no se ofrece a nadie más durante **15 minutos**; pasado ese tiempo sin guardar, vuelve a la cola. `assigned` no se usa en esta versión.
* **Saltar:** escribe `skipped`. El caso vuelve a la cola para los demás, pero no se le ofrece al mismo revisor durante 7 días.
* **Doble revisión** (`reason = agreement_sample`, que solo existe si la `risk_policy` configura la doble revisión): después de la primera revisión, el caso sigue en la cola para **otro** revisor, con `review_round = 2`. Nunca se le ofrece al mismo revisor dos veces.
* **Reseña editada:** `item_id` lleva los primeros 16 caracteres del `text_key` con el que se creó el caso. Si el texto actual del TDS ya no coincide (`TO_HEX(SHA256(texto_sanitizado))` no empieza igual), el caso se marca `expired` y se ofrece el siguiente.
* **Qué ve el revisor:** el texto sanitizado y, solo en `assisted`, la predicción (etiqueta preseleccionada y su probabilidad). **Nunca** el banco, las estrellas, la fecha, el motivo del caso (`reason`) ni la explicación: así no puede distinguir un caso de la muestra aleatoria de uno de baja confianza, como en el prototipo (pregunta `H-02`).

## 3. API (`sections/hitl/`)

| Método y ruta | Rol | Qué hace |
| :--- | :--- | :--- |
| `GET /api/v1/hitl/summary` | revisor | `HitlSummary`: por tarea permitida, `pending`, `mine_this_week`, `team_this_week`, `median_seconds` (30 días) y el avance de la muestra del trimestre (`monitor_done`, `monitor_target`). Solo conteos |
| `POST /api/v1/hitl/next` | revisor de la tarea | Cuerpo `{ task }`. Toma el siguiente caso y devuelve `HitlCase`, o 204 si no hay pendientes |
| `POST /api/v1/hitl/items/{item_id}/review` | revisor de la tarea | Cuerpo `SentimentReviewIn`. Guarda la revisión; devuelve `{ review_id, next_available }` |
| `POST /api/v1/hitl/items/{item_id}/skip` | revisor de la tarea | Escribe `skipped` |
| `POST /api/v1/hitl/items/{item_id}/release` | revisor de la tarea | Escribe `queued` (el revisor sale sin decidir); el portal lo llama al salir de la pantalla |
| `GET /api/v1/hitl/guidelines/{task}` | revisor de la tarea | `Guideline` vigente con su `guideline_version`, `valid_from` y el contenido en Markdown |

```python
class HitlCase(BaseModel):
    item_id: str
    task: Literal["sentiment"]
    text: str                               # texto_sanitizado del TDS
    display_mode: Literal["blind", "assisted"]
    proposal: SentimentProposal | None      # solo si assisted: label y p_neg, p_neu, p_pos
    guideline_version: str
    opened_at: datetime                     # el at del evento in_review
    review_round: Literal[1, 2]

class SentimentReviewIn(BaseModel):
    review_id: UUID                         # lo genera el portal al abrir el caso (idempotencia)
    validated_label: Literal["NEG", "NEU", "POS"] | None   # None solo con la marca no_evaluable
    flags: list[ReviewFlag]                 # menciona_falla, duda, no_evaluable, nombre_persona
    comment: str | None = Field(default=None, max_length=500)
    ticket: str | None = Field(default=None, max_length=100)
    guideline_version: str                  # la que se mostró
```

**Al guardar** (`service.py`):

1. Comprobar que el último evento del caso es `in_review` del mismo `actor_hash` (si no, 409 `conflict`: "el caso volvió a la cola; pide el siguiente").
2. Comprobar que `guideline_version` existe para la tarea.
3. Si hay `comment`, sanitizarlo con Cloud DLP (`api_backend/dlp.py`, sección 4). Si DLP falla, 502, sin guardar nada: el portal conserva el formulario.
4. Armar `HitlReview` de `voc-common`:
   * `predicted_label`, del `predicted` del caso, también cuando es `blind` (la comparación se hace en el servidor);
   * `outcome`, por igualdad (con `validated_label` nulo, `corrected`, según B5.1);
   * `display_mode` y `model_version`, del caso; `review_round`; `reviewer_hash`;
   * `opened_at` del evento `in_review`, `submitted_at` ahora, `seconds_spent` la diferencia en segundos.
5. `writer.insert("hitl_reviews", review, key=["review_id"])` y después el evento `submitted` (`key=["event_id"]`). Un reintento con el mismo `review_id` no duplica.

**Contenido de la guía:** `content_uri` es una ruta del repo (`docs/analytics/labeling/annotation_guideline.md`, `docs/analytics/eda/eda_aspects_guideline.md`). La imagen copia esos archivos a `/app/guidelines/<content_uri>` (se suman al `.dockerignore`) y la API lee el que diga la fila vigente; si falta, 404 con el `content_uri` en el mensaje.

**Texto del TDS:** `SELECT texto_sanitizado FROM sanitized_reviews_tds WHERE bank_id = @bank AND id_resena = @id`. El filtro por banco aprovecha la agrupación de la tabla. Se mide en la prueba de integración y, si pasa de 50 MB por consulta, se traen de una vez los textos de los 20 casos siguientes y se guardan en la memoria del proceso 15 minutos (nunca en el navegador).

## 4. Sanitización de comentarios (`api_backend/dlp.py`)

```python
class CommentSanitizer(Protocol):
    def sanitize(self, text: str) -> str: ...

class DlpCommentSanitizer:
    """deidentify_content con las plantillas de inspección y de des-identificación de la
    sanitización (infra/modules/dlp.py), que incluyen los detectores de nombres y los bancarios."""
```

* Usa `google-cloud-dlp` con `parent = projects/<proyecto>/locations/global`, las plantillas `DLP_INSPECT_TEMPLATE` y `DLP_DEIDENTIFY_TEMPLATE` y el texto como `item.value`. La pantalla avisa: "No copies el texto de la reseña; los nombres y datos personales se reemplazan antes de guardar".
* La usan también las notas de las alertas de deriva (paso 7).
* En pruebas y en modo local, un doble que reemplaza un nombre fijo ("Juan Pérez" → `[PERSON_NAME]`).

## 5. Pantalla (`src/sections/hitl/`)

### 5.1 Entrada (`/hitl`)

Al entrar se ve la cola de inmediato, con un submenú por tipo (Sentimiento; Aspectos y Tópicos en el paso 9, solo si el revisor tiene esa tarea). Por cada cola: pendientes, mis revisiones de la semana, las del equipo, tiempo mediano por caso y el avance de la muestra del trimestre ("Muestra de monitoreo: 0 de 300"). El botón **Empezar** abre el primer caso.

### 5.2 Revisión (`/hitl/sentimiento`)

Distribución en dos columnas (≥ 1 280 px): el caso a la izquierda (8 columnas) y la guía a la derecha (4 columnas, plegable).

* **Arriba:** "Caso 3 de esta sesión · guía v2.2 · modo a ciegas" (o "asistido"). Sin banco, estrellas, fecha ni motivo.
* **Texto:** en un recuadro, con Source Serif 4 a 20 px e interlineado de 1.5, respetando los saltos de línea.
* **Propuesta** (solo `assisted`): "El modelo propone **NEG** (0.62)", con esa opción preseleccionada para aceptarla o cambiarla.
* **Formulario:**
  * sentimiento: `NEG`, `NEU`, `POS` y "No evaluable" (botones de radio grandes); obligatorio;
  * marcas: "Menciona falla", "Duda" y "Contiene nombre propio de una persona", con la ayuda del prototipo ("Nombre o apellido de una persona escrito en el texto, aunque no sea del autor. No cuentan los tokens como [PERSON_NAME] ni los nombres de bancos o apps");
  * comentario opcional ("sin copiar el texto") y ticket opcional;
  * **Guardar y seguir** (primario), **Saltar** y **Salir**.
* **Atajos** (`KeyboardHint` visible): `1` NEG, `2` NEU, `3` POS, `0` No evaluable, `F` falla, `D` duda, `N` nombre propio, `Enter` guardar (`Ctrl+Enter` dentro del comentario), `S` saltar, `G` mostrar u ocultar la guía.
* **Guía:** el Markdown de `GET /hitl/guidelines/sentiment`, con `react-markdown` y `remark-gfm` (se agregan en este paso), y su versión y fecha arriba.
* **Al guardar:** aviso breve ("Guardado") y el siguiente caso; sin cola, `EmptyState` "No quedan casos pendientes en esta cola".
* **Al salir** o cerrar la pestaña, `release` con `navigator.sendBeacon`.
* **Errores:** un 409 muestra "El caso volvió a la cola" y ofrece el siguiente; un 502 de DLP conserva el formulario y explica qué pasó.
* **Nada del caso** se guarda en `localStorage` ni en la URL (la URL no lleva `item_id`).

## 6. Pruebas

* **API:**
  * `blind` nunca devuelve `proposal`, aunque el caso tenga `predicted` (prueba explícita, también para `agreement_sample`);
  * ninguna respuesta del HITL trae banco, estrellas, `reason` ni explicación;
  * orden de la cola; bloqueo de 15 minutos (otro revisor no recibe el caso; pasado el tiempo, sí); saltado no vuelve al mismo revisor en 7 días; la segunda ronda va a otro revisor;
  * reseña editada → `expired`;
  * revisión: `outcome` correcto (incluido el caso "no evaluable" de B5.1), `seconds_spent`, `review_round`, guía validada, idempotencia por `review_id`, 409 sin `in_review` propio;
  * comentario: pasa por el sanitizador; si DLP falla, no se escribe nada;
  * rol: un analista sin rol de revisor recibe 403; un revisor de `aspects` no recibe casos de sentimiento.
* **Portal:** los atajos funcionan; en `blind` no aparece la propuesta; "No evaluable" envía `validated_label: null` con la marca; Guardar pide un sentimiento; `axe` sin violaciones; nada se escribe en `localStorage`.

## Terminado cuando

* [x] La cola reproduce el flujo del prototipo y escribe en `hitl_reviews` con su modo, su guía y su tiempo. (Probado con la cola en memoria; la escritura a BigQuery la prueba el autor al revisar en dev.)
* [ ] La muestra de monitoreo nunca muestra la predicción (prueba de API y revisión manual en dev con un caso `monitor_sample`). (Prueba de API hecha; falta la revisión manual en dev.)
* [ ] En dev, el autor revisa al menos 20 casos reales y el lunes siguiente el monitor los cuenta para el κ del trimestre (o la consulta de `quality.py` los lee, si el trimestre no cierra todavía).
* [x] El comentario sanitizado queda en la FMEA (fila del comentario del revisor), para calificar en el paso 10. (F-21 ya lo cubría; se anotó su control de este paso.)

## Decisiones al implementar

* **B5.1 aplicada (2026-10-26, recomendación del paso 0).** `HitlReview` acepta `validated_label` nulo solo con la marca `no_evaluable` (y esa marca exige etiqueta nula); el resultado es siempre `corrected`. El reentrenamiento ya excluía las revisiones sin etiqueta o con la marca. El κ del monitor (`quality.py`) contaba una revisión sin etiqueta como pendiente y no calculaba nunca: ahora distingue "sin revisar" de "no evaluable" (columna `reviewed`) y deja fuera del κ solo a las segundas.
* **El `item_id` que ve el portal es opaco** (hallazgo de la prueba de "ninguna respuesta trae el motivo"). El real empieza por el motivo (`monitor_sample:2026Q3:…` contra `sentiment:…`), así que mandarlo al navegador dejaba distinguir la muestra de un caso de baja confianza. La API entrega `public_id` (los primeros 32 caracteres del SHA-256 del `item_id`) y busca el caso por él (`LEFT(TO_HEX(SHA256(item_id)), 32)` en BigQuery).
* **Tomar un caso es escribir y volver a leer.** Se escribe `in_review` y se relee el estado del caso; si el último evento no es del revisor, otro lo tomó al mismo tiempo y se pasa al siguiente. Si el revisor ya tenía un caso abierto (menos de 15 minutos), `next` se lo devuelve con su `opened_at` original, así que recargar la pantalla no pierde el tiempo medido ni deja el caso bloqueado.
* **Idempotencia.** El evento `submitted` lleva `event_id = "<review_id>:submitted"`; un reintento con el mismo `review_id` y el caso ya enviado devuelve 200 sin escribir de nuevo. `release` sobre un caso que ya no es del revisor no hace nada (204), porque lo llama `sendBeacon` y nadie lee su respuesta; `skip` sí da 409.
* **Casos sin predicción válida no se ofrecen** (el delta puede dejar `label` nulo): no se podría calcular `outcome`. Se registra una advertencia.
* **Cuatro consultas por cola de BigQuery con un tope de 500 casos** (`QUEUE_LIMIT`, ordenados por prioridad). Si un revisor saltara más de 500 casos seguidos no vería el resto; no pasa con los 497 de dev.
* **DLP:** el `parent` es `projects/<proyecto>/locations/<región>` y no `global`, porque las plantillas de `infra/modules/dlp.py` viven en la región del stack. `GUIDELINES_DIR` (por defecto `/app/guidelines`) lo fija la imagen; en `PORTAL_DATA=fixtures` la guía sale de `sample_data/sample_guideline.md`.
* **Una sola cola en el menú.** El submenú por tipo (Aspectos y Tópicos) llega con el paso 9; con una sola tarea la entrada muestra su tarjeta sin pestañas.
* **Sin `react-hook-form` en la pantalla de revisión:** el formulario tiene cinco campos y los atajos necesitan el estado a la mano; se usa estado de React y entradas nativas (radio y casilla) con el foco visible.
* **Nada del caso en `localStorage` ni en la URL.** Lo único que queda en `localStorage` es la preferencia de menú plegado del shell.

* **Sin campo `ticket` en la pantalla (decisión del autor, 2026-10-26).** Nada lo lee y estorbaba; `SentimentReviewIn` ya no lo recibe y `hitl_reviews.ticket` se guarda nulo (el contrato lo admite). Sustituye a H-05 para esta pantalla; las alertas (paso 7) conservan su campo.
* **Guardar devuelve el siguiente caso** (`ReviewOut.next`, ya tomado) en vez de `next_available`: el portal no espera otra ronda y la API no relee la cola para contar. Si tomar el siguiente falla, la revisión ya está guardada y `next` es nulo (el portal pide `/next`).
* **Menos esperas por caso** (la revisión del autor en dev tardaba unos 10 a 13 s entre casos): la cola se guarda 15 s en memoria del proceso y se mantiene al día con lo que ese proceso escribe; los textos del TDS se traen en lotes de 20 y se guardan 15 minutos; las lecturas del caso y de las guías, y las dos escrituras del guardado, corren en paralelo. Como la memoria puede ir atrasada respecto de otras instancias, al tomar un caso se relee su estado sin memoria y, si ya tenía revisión, se vuelve a cerrar y se pasa al siguiente. La solución de fondo queda en EPIC-8 (12).
* **El texto del TDS cuesta más de lo que anoté:** buscar un `id_resena` escanea la agrupación del banco (157 MB y 5 s una consulta suelta, 276 MB y 5 s un lote de 10); mi cifra anterior de 0 bytes venía de la caché de resultados de BigQuery. Sigue bajo el tope de 2 GB de la API.

* **Revisión del autor en dev (2026-10-26): seguía en unos 10 s por caso.** Causa: la memoria de la cola duraba 15 s y una revisión humana dura más, así que al guardar siempre estaba vencida (otra lectura de 2 s), y aun con todo en memoria quedan 6 a 7 s de escrituras y relecturas de BigQuery. Cambios:
  * la cola se guarda 5 minutos; como puede ir atrasada respecto de otras instancias, antes de tomar un caso se relee su estado sin memoria (y eso corrige la cola guardada);
  * **precarga:** al mostrar un caso, el portal pide el siguiente con `POST /hitl/next` y `exclude` (los casos que ya tiene abiertos), que lo bloquea para el revisor mientras lee. Guardar lo muestra al instante y envía la revisión en segundo plano con `claim_next: false`. Una petición normal y no un hilo en segundo plano, porque Cloud Run limita el CPU fuera de las peticiones;
  * si el guardado en segundo plano falla: un 409 avisa con un mensaje (el caso ya no era suyo); cualquier otro error muestra un aviso "No se guardó la revisión del caso anterior" con **Volver a ese caso** (restaura el formulario y el mismo `review_id`, así que reintentar no duplica) y el caso que se veía pasa a ser el precargado. Si la precarga falla se usa la forma clásica;
  * **Salir** espera los guardados en curso y suelta los dos casos abiertos; cerrar la pestaña los suelta con `sendBeacon`. Si la pestaña se cierra con un guardado en vuelo, esa revisión se pierde y el caso vuelve a la cola a los 15 minutos;
  * el tiempo que ve el revisor entre un caso y otro pasa a ser el de pintar el siguiente; el guardado y el bloqueo siguen costando lo mismo en BigQuery y por eso la actividad 12 de EPIC-8 sigue abierta.
* **Textos de las marcas** (a petición del autor): "Menciona falla" → "Menciona una falla concreta" y "Duda" → "Tengo dudas con esta etiqueta", cada una con su ayuda tomada de la guía.

## Avance

* **API (2026-10-26):** `sections/hitl/` (`router`, `schemas`, `service`, `repository`, `sample`), `api_backend/dlp.py`, `writer_for`, `GUIDELINES_DIR`, `openapi.json` y `schema.d.ts` regenerados. 33 pruebas nuevas en `test_hitl.py`: orden, `blind` sin propuesta (incluido un caso asistido con motivo `agreement_sample`), ninguna respuesta trae banco, motivo ni explicación, bloqueo de 15 minutos, salto de 7 días, segunda ronda a otro revisor, reseña editada, `outcome`, `no_evaluable`, `seconds_spent`, guía validada, idempotencia, 409, DLP caído (502 y nada escrito), roles y rutas de la guía. La imagen copia las dos guías a `/app/guidelines` y el `.dockerignore` las deja pasar.
* **Portal (2026-10-26):** `/hitl` (cola con conteos y avance de la muestra) y `/hitl/sentimiento` (texto en Source Serif 4 a 20 px, propuesta solo asistida, radios grandes, marcas, comentario, ticket, atajos con `KeyboardHint`, guía plegable con `react-markdown` y `remark-gfm`, `sendBeacon` al salir). 14 pruebas nuevas, entre ellas `axe` sin violaciones. `npm run check`, `tsc`, `npm test` (137) y `npm run build` pasan; la pantalla de revisión es un trozo perezoso de 51 KB comprimido.
* **Revisada en local** (`PORTAL_DATA=fixtures`): se abrió el caso, se eligió NEG con la tecla `1`, se guardó con `Enter` y pasó al siguiente.
* **Contra BigQuery de dev** (`RUN_BIGQUERY_TESTS=1`, solo lecturas): las consultas de la cola, del caso por `public_id`, de las guías, del texto del TDS y del resumen devuelven resultados. Bytes facturados: la cola y la búsqueda de un caso 30 MB cada una (la vista `hitl_queue` más las dos agregaciones), la muestra de monitoreo 20 MB, las demás 0 (el texto del TDS se corrige abajo). El umbral de 50 MB del texto sí se pasa (ver las decisiones), así que se agregó la memoria de textos. Tiempos antes de la memoria: cola 1.9 s, caso 1.3 s, texto 1.3 s; un "siguiente" suma unos 5 s (cola, texto, escritura y relectura).
* **Optimización (2026-10-26):** `CachedHitlRepository`, `review_texts` por lote, guardar con el siguiente caso y sin `ticket`; 6 pruebas nuevas en `test_hitl.py` y 2 en el portal (memoria que se mantiene al día, un solo lote de textos, vencimiento, caso revisado por otra instancia). Pendiente medir el ciclo en dev con el autor.
* **Pendiente del autor:** revisar en dev al menos 20 casos reales (con al menos uno `monitor_sample`, a ciegas) y comprobar el lunes siguiente que el monitor los cuenta para el κ del trimestre. La escritura real a `hitl_reviews` y `hitl_events` por la API se estrena en esa revisión: la cuenta de servicio de la API necesita `bigquery.dataEditor` en esas tablas y permiso de DLP (paso 1).
