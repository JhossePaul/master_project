# Nota para el registro de decisión: estrategia de tópicos e incidentes (5.5 → 5.8)

> **Estado (2026-10-22): aprobada por el autor, con un agregado: los flujos de curaduría son requisitos de EPIC-7 y su almacenamiento de EPIC-6 (sección final; numeración del backlog reorganizado el 2026-10-22).** Resume la recomendación de 5.5 para `decision_record.md` (5.8). Evidencia completa: [`topics_report.md`](topics_report.md); plan: [`topics_design.md`](topics_design.md). Solo agregados.

## Decisión (aprobada el 2026-10-22)

**Híbrido con roles separados:**

1. **Núcleo de medición:** familias de aspectos `aspects_v2_1` (Gemini, multi-etiqueta, 11 familias; [guía](../eda/eda_aspects_guideline.md)) sobre cada reseña negativa elegible, con métricas por banco × periodo.
2. **Alerta de regresión:** la marca `u` (problema atribuido a una actualización), complementada por las series de las familias, que explican el incidente.
3. **Capa de detalle:** tópicos BERTopic por cláusulas (MiniLM), reajustados cada trimestre y curados por una persona, para dos audiencias: producto (negocio) e ingeniería.

`TOPIC_TOO_SHORT` con k = 1 (decisión del autor, 2026-10-22): del análisis solo se excluyen las negativas de una palabra.

## Alternativas descartadas

| Opción | Motivo |
| :--- | :--- |
| Solo tópicos dinámicos | Ningún esquema de tópicos recupera el multi-aspecto (κ ≤ 0.17 contra 24.7 % codificado); los nombres e identificadores requieren curaduría; en este corpus no encontraron temas fuera de la taxonomía |
| Solo taxonomía fija | Pierde la granularidad útil para producto e ingeniería (19 de 35 tópicos útiles según el autor) y la única vía de detectar lo nuevo (`OT` tiene κ 0) |
| Tópicos de reseña completa | Menor cobertura (63 % contra 76 %) y peor F1 de familias que las cláusulas |
| RoBERTuito base como encoder de tópicos | Colapsa en 2–5 grupos con cualquier configuración |

## Evidencia clave

* **Multi-aspecto:** 24.7 % de las negativas (`v2.1`); los tópicos predicen 13 % con κ 0.15.
* **Marca `u`:** 13 % de las negativas a 0–3 días de una versión, 21–22 % a 4–14 días y 7 % después de 30; 61 % en los meses de incidente de BBVA contra 14 % en el resto.
* **Señal mensual** (z ≥ 3 contra 12 meses, ≥ 10 filas), en los 3 incidentes conocidos de BBVA:

  | Series | Detectados | Aviso el mes previo | Meses con alerta fuera de incidentes |
  | :--- | ---: | ---: | ---: |
  | Tópicos (97) | 3 | 2 | 11 % |
  | Familias + `u` (12) | 3 | 3 | 22 % |
  | Solo `u` | 2 | 2 | 4 % |

  En BBVA 2025-09, `DV` y `UX` avisaron del rediseño un mes antes de que lo hicieran el volumen y los tópicos.
* **Revisión del autor de 35 tópicos:** 11 útiles para producto, 8 para ingeniería y 16 sin valor. Ningún tema nuevo. Cerca de un tercio del peso de los 20 tópicos principales es ruido o retórica.

## Matiz que debe quedar registrado

Los tópicos **no demostraron** descubrir temas fuera de la taxonomía en este corpus. Su valor demostrado es la granularidad dentro de cada familia y servir a dos audiencias, con un costo de curaduría de cerca de un tercio de ruido. La detección de lo nuevo queda como hipótesis por vigilar en 5.7 (prevalencia de `OT` y de los tópicos no alineados).

## Costo de operación estimado

* **Gemini:** ~$0.09 por 1 000 textos; ~6 400 negativas únicas nuevas al mes → ~$0.60 al mes (~$1.70 en un mes de incidente). Reprocesar el histórico: ~$60.
* **Tópicos:** embeddings y asignación en segundos al mes; reajuste trimestral en 1–2 min en local.
* **Curaduría:** ~30–60 min por trimestre (la primera revisión de 20 tópicos tomó ~45 min).
* **Identificadores:** congelados entre reajustes. El emparejamiento entre reajustes por centroides está pendiente de validar en 5.7.

## Dependencias y pendientes

* **5.7:** umbrales de la señal con más filas y una lista de incidentes etiquetados; análisis por versión, que la plata no alcanza; validación del emparejamiento de tópicos; *backfill*; monitoreo de `OT` y de los tópicos no alineados.
* **5.8:** el modelo de sentimiento que define las negativas en producción (M4 o M9), del que dependen las familias.
* **5.6:** priorización de alertas contra incidentes conocidos, si se adopta.

## Límites

Todo se midió sobre la plata `silver_v0` (40 382 negativas únicas, ponderadas por 1 / π). Las familias son etiquetas de Gemini (κ con el autor de 0.55 a 0.86; entre corridas de Gemini, `DV` 0.58 y `OT` 0.22). Solo hay 3 incidentes conocidos para la prueba hacia atrás, así que la señal es ilustrativa. Hay un único anotador humano.

## Agregado del autor (2026-10-22): curaduría HITL en EPIC-6 y EPIC-7

**Decisión del autor:** las aplicaciones de curaduría que se usaron para el sentimiento, los aspectos y los tópicos forman parte del frontal HITL de [EPIC-7](../../backlog/epic_7.md) (feature 7.7). Además, se diseña una base de datos que guarde cada curaduría para el reentrenamiento ([EPIC-6](../../backlog/epic_6.md), feature 6.2). Esta sección es el insumo de 5.5. La especificación de EPIC-6 y EPIC-7 (`docs/backlog/`), los contratos (`docs/contracts/`) y la infraestructura no son rutas de 5.5: los adopta su dueño.

### Prototipos que pasan al frontal

| Prototipo actual (local) | Curaduría | Pantalla HITL equivalente |
| :--- | :--- | :--- |
| `annotation/app.py` (Streamlit, 5.3) | Etiqueta de sentimiento del oro (`NEG`/`NEU`/`POS`, `menciona_falla`, duda) | Cola de sentimiento (`HitlTriageQueue`) |
| `eda/aspects_app.py` y `eda/aspects_v2_app.py` (Streamlit, 5.2) | Familias `v2.1`, marcas `u` y `s`, elogio | Codificación de aspectos (nueva) |
| `data/topics/phase4_v0/` (fichas y CSV, 5.5) | Nombre, coherencia, audiencia, familias y tema nuevo de cada tópico; hipótesis | Curaduría de tópicos tras cada reajuste trimestral (nueva) |

### Borrador del modelo de datos de curaduría

Principios: los registros son inmutables (solo se inserta, como en `hitl_triage_audit_log`); el revisor se guarda como hash SHA-256; cada registro guarda la versión de la guía y del modelo o prompt que produjo la predicción revisada; y el texto se guarda solo sanitizado.

| Tabla | Grano | Columnas principales | Uso en el reentrenamiento |
| :--- | :--- | :--- | :--- |
| `curation_sentiment` (o ampliar `hitl_triage_audit_log`) | Reseña × decisión | `id_resena`, `predicted_label`, `validated_label`, `menciona_falla`, `duda`, `model_version`, `guideline_version`, `reviewer_hash`, `reviewed_at`, `origen` (cola HITL, oro, auditoría) | Ampliar el oro y re-medir κ; reentrenar M4 o M9 (5.4 y 5.7) |
| `curation_aspects` | Reseña × decisión | `id_resena`, `predicted_families[]`, `validated_families[]`, `u`, `s`, `elogio`, `prompt_version` (`aspects_v2_1`), `model_version` (Gemini), `guideline_version` (`v2.1`), `reviewer_hash`, `reviewed_at` | κ autor–Gemini por familia, ejemplos para el prompt y alarma si el acuerdo cae |
| `topic_model_versions` | Reajuste | `topic_model_version`, `fitted_at`, `embedding_model`, parámetros (`min_cluster_size`, `min_samples`, segmentador), muestra de ajuste | Trazabilidad y reproducibilidad |
| `topic_catalog` | Tópico × versión | `topic_model_version`, `topic_id`, términos, `previous_topic_id` y su similitud de centroides | Emparejar identificadores entre reajustes |
| `curation_topics` | Tópico × versión × decisión | `topic_model_version`, `topic_id`, `curated_name`, `coherence_1_5`, `audience` (producto, ingeniería, sin valor), `families[]`, `is_new_theme`, `mapping_confirmed`, `curator_hash`, `curated_at` | Conservar nombres y audiencias entre reajustes; descartar el ruido; detectar temas nuevos |
| `topic_assignments` | Reseña (o cláusula) × versión | `id_resena`, `segment_index`, `topic_model_version`, `topic_id` | Series por tópico y señal |

### Discrepancias de `epic_7.md` (antes `epic_6.md`) con la evidencia de 5.5 (registradas en las tablas de decisiones heredadas de `epic_6.md` y `epic_7.md`)

* **Tópicos:** asume los 8 `ABSATopic` de `voc_common.constants` como taxonomía (`get_prioritized_backlog_topics`, `predicted_topic` y el *concept drift*). La taxonomía validada son las 11 familias multi-etiqueta de `v2.1` más las marcas `u` y `s`, y una reseña puede tener varias familias; los tópicos son una capa aparte con versión.
* **Embeddings:** asume `embedding_vector` de 768 dimensiones del modelo Delora. 5.4 descartó Delora (M8), y los tópicos usan MiniLM (384 dimensiones). La búsqueda semántica necesita decidir su encoder (5.7 o 5.8).
* **Concept drift:** la propuesta de 5.5 es usar la proporción de las familias y de la marca `u`, que demostró adelantarse a los incidentes, en lugar de la JSD de 8 tópicos por versión. Los umbrales se fijan en 5.7.
* **Umbral HITL** (`entropy >= 0.65`): lo fija 5.6 con la curva de cobertura y riesgo, no a priori.
