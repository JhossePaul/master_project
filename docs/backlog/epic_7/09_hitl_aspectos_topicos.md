# Paso 9. Feature 7.7 (parte deseable): HITL de aspectos y curaduría de tópicos

* **Estado (2026-10-26):** Terminado en local (API, portal y pruebas); falta probarlo contra BigQuery de dev con el autor (casillas 1 y 2). Detalle en "Avance".
* **Nivel:** deseable. Se recorta antes que cualquier paso imprescindible o importante, y después de la tesis.
* **Depende de:** paso 4 (la cola, el bloqueo, la guía y el sanitizador) y la decisión B5.5 del paso 0.
* **Objetivo:** las otras dos curadurías de EPIC-5 en el portal: la codificación de familias y marcas (prototipo `experiments/analytics/src/voc_analytics/eda/aspects_v2_app.py`) y la curaduría de tópicos de cada versión de BERTopic (las fichas de `data/topics/phase4_v0/` de 5.5), que activa una versión nueva.

## 1. Cola de aspectos

### 1.1 Quién crea los casos

Ningún Job crea casos `task = aspects`. Con la recomendación de B5.5, el administrador crea **muestras** desde la pestaña Muestras de Administración:

* criterio: N reseñas al azar (50 por defecto) entre las negativas de dos palabras o más con fila en `review_aspects`, de una ventana (3 meses por defecto), con cuota igual por banco;
* cada caso es un `HitlItem` con `task = aspects`, `reason = manual`, `display_mode = blind`, `predicted` = `{families, flag_update, flag_security, praise, prompt_version}` de la última fila de `review_aspects`, `priority` fija e `item_id = aspects:manual:<lote>:<id_resena>:<text_key[:16]>`, más su evento `queued`;
* `POST /api/v1/admin/samples/aspects` con `{ size, months, reason }` (administrador), y `GET /api/v1/admin/samples` para ver los lotes y su avance.

### 1.2 Revisión

Las mismas reglas de cola del paso 4 (bloqueo de 15 minutos, saltar, reseña editada, nunca banco, estrellas, fecha ni motivo), con `require_reviewer(HitlTask.ASPECTS)` y la guía `v2.1` (`docs/analytics/eda/eda_aspects_guideline.md`).

* **Formulario** (como el prototipo, que se lee antes de construirlo, sobre todo las líneas 290-345):
  * "Sin problema concreto" (excluye las familias);
  * las 11 familias `aspects_v2_1`, **agrupadas en el orden de decisión de la guía**, con el nombre y la definición corta de cada una;
  * marca de actualización (`u`), marca de seguridad (`s`) y elogio;
  * comentario opcional.
* **Siempre a ciegas:** nunca se muestra lo que etiquetó Gemini.
* **Escritura:** `HitlReview` con `task = aspects`, `predicted_families` y `predicted_flag_update` y `_security` del caso, y `validated_*` del formulario; `outcome` por igualdad de familias y marcas, como valida el modelo.
* **Elogio:** `HitlReview` no tiene columna para el elogio. Recomendación: no guardarlo en esta versión y quitarlo del formulario, porque nada lo consume. Si el autor lo quiere, es un cambio de contrato (pregunta `H-07`).
* **Para qué sirve:** hoy nada consume estas revisiones. Quedan como insumo de una futura revalidación de las familias con anotación humana reciente, además de las 300 reseñas del autor.

## 2. Curaduría de tópicos

### 2.1 Cuándo hay algo que curar

Una versión de `topic_model_versions` más nueva que `topic_model_current` (la deja el re-ajuste trimestral o el botón del paso 8) tiene sus tópicos en `topic_catalog`, cada uno emparejado con el anterior de centroide más parecido (`previous_topic_id`, `centroid_similarity`). **La versión se activa cuando todos sus tópicos emparejados tienen una decisión en `curation_topics`** (vista `topic_model_current`); después, el delta lanza el backfill de tópicos del histórico. También se puede volver a curar un tópico de la versión vigente: la última decisión gana.

### 2.2 API (`sections/hitl/topics.py`)

Rol revisor con `topic` en `reviewer_tasks`.

| Método y ruta | Respuesta |
| :--- | :--- |
| `GET /api/v1/hitl/topics/versions` | Versiones con tópicos por decidir: `topic_model_version`, `fitted_at`, tópicos, decididos y si al terminar se activa |
| `GET /api/v1/hitl/topics/{version}` | Por tópico: `topic_id`, `terms`, tamaño (cláusulas asignadas), su par anterior (`previous_topic_id`, similitud y la última curaduría de ese par: nombre, audiencia, familias) y la decisión vigente si existe |
| `GET /api/v1/hitl/topics/{version}/{topic_id}/examples?n=5` | 5 cláusulas o reseñas de ejemplo al azar del tópico (texto sanitizado del TDS por `id_resena`), con semilla fija por tópico para que el curador vea las mismas al volver |
| `POST /api/v1/hitl/topics/{version}/{topic_id}` | Cuerpo `{ curated_name, coherence_1_5, audience, families, is_new_theme, mapping_confirmed }`. Inserta `TopicCuration` con `curator_hash` y `curated_at` |

### 2.3 Pantalla (`/hitl/topicos`)

* Lista de versiones pendientes con su avance ("12 de 97 decididos") y el aviso "al decidir el último, la versión se activa y el histórico se re-asigna".
* Por tópico, una ficha:
  * términos;
  * tamaño;
  * ejemplos;
  * el par anterior con su nombre, audiencia y familias;
  * el formulario: nombre, coherencia de 1 a 5, audiencia (producto, ingeniería o sin valor), familias (selección múltiple), "es un tema nuevo" y "el emparejamiento es correcto".
* Atajos para pasar al tópico siguiente; filtro de pendientes.

## 3. Pruebas

* **API:**
  * la muestra de aspectos es aleatoria con cuota por banco y crea casos `blind` con su evento `queued`;
  * la cola de aspectos nunca devuelve la propuesta de Gemini;
  * `outcome` correcto con familias en otro orden;
  * un revisor de sentimiento recibe 403 en aspectos y tópicos;
  * la curaduría se valida con `TopicCuration`;
  * los ejemplos son estables con la semilla;
  * con todos los pares decididos, la consulta de `topic_model_current` en memoria cambia de versión.
* **Portal:** las familias aparecen en el orden de la guía; "Sin problema concreto" limpia las familias; `axe` sin violaciones.

## Terminado cuando

* [ ] (Hecho en local; falta la prueba en dev con una muestra real.) La cola de aspectos reproduce el flujo del prototipo y escribe en `hitl_reviews` con `task = aspects`, a ciegas.
* [ ] (Hecho en memoria; falta la prueba en dev.) La curaduría de una versión nueva escribe en `curation_topics` y, al completarse, activa la versión (en dev, después del primer re-ajuste trimestral o del botón del paso 8).

## Decisiones al implementar

Se leyó antes el paso 4 y sus cuatro rondas de rendimiento; lo que sigue evita repetirlas.

* **Mismo motor que sentimiento, sin tocarlo.** La API generaliza `service.py` (tarea del caso, `_open_for_save`, `_commit`, `_build_review`) y el portal estrena `useCaseQueue.ts`: precarga del siguiente con `exclude`, casos ya revisados recordados, guardado en segundo plano, "Volver a ese caso" y `release` al salir. `SentimentReview.tsx` no se migró al hook para no arriesgar el flujo que el autor ya validó en dev; migrarlo es limpieza pendiente.
* **Ruta propia de guardado:** `POST /hitl/items/{item_id}/review-aspects` con `AspectsReviewIn` (`families`, `flag_update`, `flag_security`, comentario). El caso de otra tarea da 422. El elogio no se guarda ni está en el formulario (recomendación de la spec; sigue abierta la pregunta H-07).
* **Siempre a ciegas:** `_proposal` devuelve nulo para toda tarea que no sea sentimiento, y el `item_id` que ve el portal sigue siendo el resumen opaco (no delata `manual`). `outcome` compara conjuntos de familias, así que el orden no importa; se guardan ordenadas.
* **`text_matches` por tarea:** en aspectos el `text_key[:16]` va al final del `item_id` (`aspects:manual:<lote>:<id_resena>:<text_key>`), no antes de la versión del modelo.
* **Resumen:** las dos colas se consultan en paralelo y la de aspectos se salta la consulta de la muestra de monitoreo (4 consultas menos por visita).
* **Muestras en una sola escritura.** Crear 50 casos con `insert` por fila eran 100 trabajos de BigQuery de unos 2 s. `BigQueryWriter.insert_many` arma un `INSERT … UNION ALL` por tabla (parámetros con sufijo `__fila`, misma idempotencia por clave): dos sentencias, una por tabla, casos primero y luego los eventos `queued`. Un `INSERT` suelto sigue siendo el caso de una fila.
* **Sorteo en BigQuery, sin texto.** `review_predictions_current` (NEG, 2 o más palabras, ventana) ∩ última fila de `review_aspects` de cada reseña, menos las reseñas que ya tienen un caso de aspectos; cada banco aporta hasta `size` filas ordenadas por `FARM_FINGERPRINT(semilla, id_resena)` y la API reparte la cuota igual por vueltas (si un banco se queda corto, los otros completan). El lote es la semilla; `priority` fija en 1.0 como la muestra de monitoreo. El motivo de la pestaña va al registro estructurado, no a una columna.
* **Curaduría de tópicos:** `topics.py` con memoria de 15 minutos solo para lo que no cambia con una decisión (catálogo con tamaños, ejemplos); las decisiones y el avance se leen siempre sin memoria. El par anterior sale de la versión inmediatamente anterior por `fitted_at`. La lista de versiones incluye la vigente (para volver a curar) y marca `activates_on_completion`. Guardar devuelve `paired`, `decided` y `completed`; el portal avisa cuando la versión queda completa. El portal propone la curaduría del tópico anterior (nombre, audiencia, familias) como punto de partida.
* **Ejemplos:** reseñas completas (recortadas a 600 caracteres) con una sola consulta por lote al TDS, como `prefetch_texts` en sentimiento; la semilla es `sha256(versión:tópico)`. Nunca salen banco ni identificador.
* **Atajos:** aspectos `0`, `U`, `E`, `S`, `G`, `Enter`; tópicos `J`/`K` y `Ctrl+Enter`. Las familias no llevan atajo (11 más "sin problema").

## Avance

* **API (2026-10-26):** `sections/hitl/topics.py`, `sections/admin/samples.py`, `insert_many` en el escritor, `review-aspects` y la tarea `aspects` en `service.py`, `openapi.json` y `schema.d.ts` regenerados. 26 pruebas nuevas en `test_hitl_aspects.py` (a ciegas sin Gemini, `outcome` con familias en otro orden, comentario por el sanitizador, idempotencia, 403 entre tareas, expiración, cuota por banco, sin repetir reseñas, versión que cambia al decidir el último par, última decisión gana, ejemplos estables) y 2 en `test_writer.py`.
* **Portal:** `/hitl/aspectos`, `/hitl/topicos`, tarjetas nuevas en `/hitl` y la pestaña Muestras de Administración. 10 pruebas nuevas (familias en el orden de la guía, "Sin problema concreto" limpia las familias, validación, atajos, `axe`, sin `localStorage`, ficha de tópico, filtro de pendientes, creación de una muestra). `tsc`, `biome`, `vitest` (215) y `build` pasan; las dos pantallas son trozos perezosos de unos 4 KB comprimidos.
* **Pendiente del autor en dev:** crear una muestra desde Muestras (revisa que `hitl_items` y `hitl_events` se escriban en dos sentencias y el tiempo de crear 50), revisar unos casos de aspectos (medir el ciclo como en sentimiento) y curar una versión de tópicos cuando exista una más nueva que la vigente. Los permisos ya alcanzan: `PORTAL_WRITABLE_TABLES` incluye `hitl_items` y `curation_topics`. Las consultas nuevas (`topics_*`, `admin_aspects_candidates`, `admin_sample_batches`) no se midieron contra BigQuery: solo se probaron con la lógica en memoria.
