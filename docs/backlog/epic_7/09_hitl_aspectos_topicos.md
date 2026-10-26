# Paso 9. Feature 7.7 (parte deseable): HITL de aspectos y curaduría de tópicos

* **Estado (2026-10-25):** Pendiente.
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

* [ ] La cola de aspectos reproduce el flujo del prototipo y escribe en `hitl_reviews` con `task = aspects`, a ciegas.
* [ ] La curaduría de una versión nueva escribe en `curation_topics` y, al completarse, activa la versión (en dev, después del primer re-ajuste trimestral o del botón del paso 8).

## Decisiones al implementar

_(Se llena al ejecutar.)_

## Avance

_(Se llena al ejecutar.)_
