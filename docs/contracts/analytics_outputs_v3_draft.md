# Salidas analíticas v3: borrador de esquemas y migración

> **Estado (2026-10-22): aprobado por el autor con una condición** (P8-5 y P8-11 del [registro](../backlog/epic_5.md#decisiones-pendientes)): que cubra todas las necesidades del frontal de EPIC-7. **Revisada el 2026-10-22** contra el frontal reescrito (P8-12; [sección 6](#6-cobertura-del-frontal-de-epic-7)): se agregaron el modo ciego del HITL, la doble revisión, las explicaciones fuera del HITL (`review_explanations`), las guías (`guidelines`), las estimaciones del cockpit (`kpi_estimates`) y la historia de las alertas (`incident_alert_events`). Incorpora sus cambios del 2026-10-22: valores explícitos en `eligibility_code` y `sentiment`, inferencia por texto único en el backfill, versiones del oro a partir del HITL y comentario del revisor. Reemplazaría a `delora_predictions` y `hitl_triage_audit_log` de EPIC-2 y a sus contratos de EPIC-1. Se implementa en [EPIC-6](../backlog/epic_6.md) (6.1 y 6.2) cuando se apruebe el registro de decisión (5.8). Los nombres de columnas son provisionales.

## Principios

* **Solo inserción** en todo lo que es historia (predicciones, revisiones, políticas, eventos). Lo vigente se obtiene con la última fila por clave, en una vista.
* **Todo lleva su versión:** de modelo, de calibración, de prompt, de guía, de reglas de elegibilidad y de política. Un número del portal se puede rastrear hasta lo que lo produjo.
* **Una inferencia por texto único** (`text_key`), propagada a sus reseñas. El backfill y el *re-scoring* predicen solo los textos únicos (1 429 675 en el backfill de 5.8) y luego materializan las filas por reseña con un *join*; el costo de inferencia no depende de la granularidad de la tabla. En el delta diario se predice igual por texto, aunque ahí el ahorro importa menos.
* **Sin valores nulos que mezclen conceptos:** un valor explícito dice qué pasó (`ELEGIBLE`, `NO_PREDICTED`); el nulo se reserva para "no calculado todavía" o para una ausencia real (las probabilidades de una reseña sin modelo).
* **Sin PII:** solo `texto_sanitizado` (que ya vive en el TDS) y revisores como hash SHA-256. Las tablas nuevas no copian texto: lo leen del TDS por `id_resena`.
* **BigQuery:** particionadas por mes de `fecha` (o de la fecha del evento) y agrupadas por `bank_id`, como el TDS.

## 1. Salidas del modelo

### `review_predictions` (una fila por reseña × versión de modelo)

| Columna | Tipo | Nota |
| :--- | :--- | :--- |
| `id_resena`, `bank_id` | STRING | Clave del TDS |
| `text_key` | STRING | SHA-256 hexadecimal de `texto_sanitizado`, igual en BigQuery (`TO_HEX(SHA256(...))`) y en Python; es la clave del backfill de 5.8 (1 429 675 textos únicos) |
| `fecha`, `version_app`, `estrellas` | | Copiados del TDS para las series sin *join* |
| `eligibility_rules_version` | STRING | `eligibility_rules_v1` |
| `eligibility_code` | STRING | `ELEGIBLE`, o el código de la regla que la excluye (`TNSS_TIME_OUTLIER`, `TNSS_NO_TEXT_CONTENT`…). Nulo solo si las reglas todavía no se evaluaron |
| `label_source` | STRING | `MODEL`, `RULE_BASED` (léxico de una palabra, P8-3) o `NO_PREDICTED` |
| `sentiment` | STRING | `NEG`, `NEU`, `POS` o `NO_PREDICTED` (reseña no elegible: hereda el motivo de `eligibility_code`). Nulo solo si aún no se procesa |
| `p_neg`, `p_neu`, `p_pos` | FLOAT64 | Calibradas con la T de la versión. Nulas cuando no hay modelo (`RULE_BASED` o `NO_PREDICTED`): aquí el nulo sí significa ausencia |
| `confidence` | FLOAT64 | Probabilidad máxima calibrada (la señal HITL de 5.6) |
| `model_version`, `calibration_version` | STRING | Del registro de modelos (P7-3) |
| `risk_policy_version`, `hitl_boost_id` | STRING | Política global con la que se marcó `requires_hitl` y, si había una subida activa para el banco, su `boost_id` |
| `requires_hitl` | BOOL | `confidence` < umbral de la política; `false` si no hay modelo |
| `run_id`, `predicted_at` | STRING, TIMESTAMP | Corrida que la escribió |

El *re-scoring* (P7-4) inserta filas nuevas con otra `model_version`; la vista `review_predictions_current` toma la versión promovida. `estrellas_clase` y las marcas de incongruencia no se guardan: se calculan en la vista.

### `review_aspects` (una fila por reseña negativa elegible × versión de prompt)

| Columna | Tipo | Nota |
| :--- | :--- | :--- |
| `id_resena`, `bank_id`, `text_key`, `fecha` | | |
| `families` | ARRAY<STRING> | Familias `aspects_v2_1`; vacío = sin problema concreto |
| `flag_update` (`u`), `flag_security` (`s`), `praise` | BOOL | |
| `prompt_version`, `llm_model`, `guideline_version` | STRING | `aspects_v2_1`, `gemini-3.6-flash`, `v2.1` |
| `sentiment_model_version` | STRING | El modelo cuyo `NEG` hizo elegible a la reseña (`TOPIC_NOT_NEGATIVE`) |
| `run_id`, `labeled_at` | | |

### Tópicos

`topic_model_versions`, `topic_catalog` y `topic_assignments`, como en el [borrador de 5.5](../analytics/topics/topics_decision_note.md#borrador-del-modelo-de-datos-de-curaduría), sin cambios.

### `text_embeddings` (para la búsqueda semántica, P8-6)

`text_key`, `bank_id`, `mes`, `embedding` (ARRAY<FLOAT64> de 384, MiniLM), `embedding_model`, `created_at`. Una fila por texto × banco × mes, **particionada por `mes`**: según el experimento de 5.7 (§5.1), solo la partición reduce lo que factura `VECTOR_SEARCH` (con 12 meses, ~2 000 búsquedas al mes en el free tier); una fila por texto único no se puede particionar. La búsqueda va acotada por defecto a una ventana de meses configurable.

## 2. Operación

| Tabla | Grano | Columnas principales |
| :--- | :--- | :--- |
| `model_versions` | Versión | `model_version`, `registry_uri` (Vertex o GCS, P7-3), `base_checkpoint`, `training_data` (plata, hash), `calibration_t`, métricas en el oro *dev* (κ, ECE, AURC), `license`, `status` (`candidate`, `promoted`, `retired`), `promoted_at`, `promoted_by_hash` |
| `inference_runs` | Corrida | `run_id`, `kind` (`backfill`, `delta`, `rescoring`), `environment` (`kaggle`, `cloudrun`), `model_version`, `started_at`, `ended_at`, `reviews`, `texts`, `status`, `cost_usd` |
| `drift_metrics` | Banco × mes × métrica | `metric` (longitud, vocabulario fuera del entrenamiento, no predecibles, proporción de `NEG`, familias, `u`), `value`, `baseline`, `z` o `psi`, `alert`, `drift_policy_version` |
| `incident_alerts` | Alerta | `alert_id`, `bank_id`, `period`, `signal`, `family`, `value`, `threshold`, `hitl_boost_id`, `created_at`. El estado vigente es el último de `incident_alert_events`; las confirmadas son la lista de incidentes (5.9) |
| `incident_alert_events` | Transición de una alerta | `event_id`, `alert_id`, `status` (`open`, `confirmed`, `dismissed`), `actor_hash`, `at`, `note` (sanitizada), `ticket`. Solo inserción (EPIC-7, 7.8) |
| `kpi_estimates` | Banco × periodo × métrica × corrida | `metric` (`neg`, `gap_estrellas`, `texto_peor`, `texto_mejor`, celdas de la matriz 3 × 3…), `bank_id`, `period`, `method` (`ppi` o `raw`), `estimate`, `ci_low`, `ci_high`, `n_gold`, `n_unlabeled`, `model_version`, `gold_version`, `computed_at`. Los KPI con PPI del cockpit (P8-9, P8-10); las series diarias crudas son vistas sobre `review_predictions_current` |
| `review_explanations` | Texto × versión de modelo | `text_key`, `model_version`, `method` (`occlusion_v1`), `attributions` (JSON por token), `source` (`precomputed_hitl` u `on_demand`), `computed_at`. Las lee solo el Explorador (EPIC-7, 7.6), nunca la pantalla HITL (P8-8) |
| `model_quality` | Modelo × periodo × señal | `model_version` (o `llm_model` y `prompt_version` para las familias), `signal` (`kappa_monitor`, `correction_rate`, `agreement_m4_gemini`, `families_validation`), `period`, `value`, `n`, `ic95`, `threshold`, `status` (`ok`, `warning`, `retrain`, `rejected`), `risk_policy_version` |

## 3. Políticas: apetito de riesgo (global) y alertas de deriva (por banco)

Son dos políticas distintas (decisión del autor, 2026-10-22):

* **`risk_policy` es el apetito de riesgo y es global:** cuánto error del modelo se acepta sin revisión humana. La evidencia de 5.6 es global (la curva se midió con el oro *dev* de los cinco bancos juntos; por banco habría ~160 ítems cada uno) y el umbral depende del modelo, no del banco.
* **`drift_policy` es la configuración del detector de deriva y es por banco:** cuándo se considera que un banco cambió. Cada banco tiene su propio volumen y ritmo de versiones, y el z ya se mide contra su historia.
* **Cómo se conectan:** el monitor detecta con la `drift_policy` del banco y emite una alerta; la `risk_policy` define cómo reacciona el HITL, y la reacción se aplica solo a ese banco (`hitl_boosts`).

### `risk_policy` (global; la vigente es la última versión con `valid_from` ≤ ahora)

| Columna | Nota |
| :--- | :--- |
| `policy_version`, `valid_from` | |
| `hitl_signal`, `hitl_target_coverage`, `hitl_threshold` | 5.6: `prob_max`, 0.90 y el umbral equivalente para `model_version` |
| `hitl_weekly_cap` | Tope de revisiones por semana |
| `drift_boost_coverage`, `drift_boost_days`, `drift_boost_weekly_cap` | Reacción automática a una alerta de deriva (P7-6): cobertura durante la subida, duración y tope; se aplica solo al banco que alertó |
| `monitor_sample_size`, `monitor_frequency` | Muestra humana de concepto (P7-7) |
| `topic_refit_frequency` | Re-ajuste de tópicos (P7-8); global porque los tópicos se ajustan con los cinco bancos juntos |
| `retrain_kappa_floor`, `monitor_sample_size` | Reentrenamiento (P7-10): pedirlo si el κ de M4 en la muestra trimestral queda debajo de 0.89, con 300 revisiones por trimestre |
| `warn_correction_rate`, `warn_agreement_floor`, `agreement_sample_weekly` | Avisos (P7-10), sin disparar solos: tasa de corrección de 4 semanas > 28 %; acuerdo M4–Gemini de 4 semanas < 94 %, con 500 textos por semana |
| `families_exact_floor`, `families_min_prevalence` | Revalidación de las familias al cambiar el modelo o el prompt de Gemini (P7-11): acuerdo exacto ≥ 53 % en `muestra_v21` y ninguna familia con prevalencia ≥ 5 % bajo el límite inferior de su IC |
| `set_by_hash`, `reason` | Revisor y dueño de negocio que la fijaron, y por qué |

### `hitl_boosts` (subidas temporales de la revisión, por banco)

`boost_id`, `bank_id`, `alert_id` (la alerta de deriva que la disparó), `risk_policy_version` (las reglas con que se aplicó), `coverage`, `weekly_cap`, `starts_at`, `ends_at`, `ended_reason` (`expired`, `alert_closed`, `manual`). Solo inserción. Mientras una subida está activa, la inferencia usa su cobertura para ese banco; al terminar vuelve la de `risk_policy`.

### `drift_policy` (por banco; la vigente de cada banco es su última versión con `valid_from` ≤ ahora)

| Columna | Nota |
| :--- | :--- |
| `drift_policy_version`, `bank_id`, `valid_from` | `bank_id` obligatorio |
| `template_version` | Plantilla de la que se creó, para ver qué cambió el banco |
| `thresholds` | JSON con el umbral de cada serie: plantilla de 5.7, z ≥ 4 (palabras medias, una palabra, más de 60, no predecibles, vocabulario fuera del entrenamiento, proporción de `NEG`) y PSI ≥ 0.25 (longitud) |
| `baseline_months`, `min_baseline_months` | 12 y 6 |
| `min_rows_per_month`, `entry_rule` | 200 filas; el banco entra con 12 meses seguidos que las cumplan |
| `incident_signal` | Umbrales de la señal de incidentes por familia y marca `u`; los fija 5.9 (P9-1) |
| `set_by_hash`, `reason` | |

### `drift_policy_template`

Mismas columnas que `drift_policy`, sin `bank_id`. Se usa al dar de alta un banco o al reiniciar su configuración; cambiarla no cambia a ningún banco.

### `hitl_coverage_curves` (una curva por `model_version` y `calibration_version`)

Puntos de cobertura con riesgo, IC, umbral, errores atrapados, revisiones por semana y minutos estimados (5.6), con el volumen semanal total y por banco (para estimar el costo de una subida). Lo lee la pantalla de administración (EPIC-7, 7.10).

## 4. HITL: estado e historia (P8-11)

El estado de cada caso es la **última transición** de su historia, así que nada se edita.

### `hitl_items` (un caso por reseña × tarea; se crea al entrar a la cola)

| Columna | Nota |
| :--- | :--- |
| `item_id`, `id_resena`, `bank_id`, `task` | `task`: `sentiment`, `aspects` o `topic` |
| `reason` | `low_confidence`, `drift_boost` (subida automática; con su `boost_id`), `monitor_sample` (muestra de concepto, P7-7), `agreement_sample` (doble revisión para medir el acuerdo entre personas) o `manual` |
| `display_mode` | `blind` (sin la predicción) o `assisted` (con la predicción). **`monitor_sample`, `agreement_sample` y todo caso que pueda entrar al oro van siempre `blind`** (decisión del autor, 2026-10-22, para evitar el anclaje medido en 5.3) |
| `model_version`, `risk_policy_version` | Con qué se generó el caso |
| `predicted` | JSON con lo que predijo el sistema (etiqueta y probabilidades, o familias). La API no lo envía a la pantalla cuando `display_mode = 'blind'` |
| `priority` | Para ordenar la cola: familia y marca `u` del mes (5.6), luego menor confianza |
| `created_at` | |

### `hitl_events` (transiciones de estado)

`event_id`, `item_id`, `status` (`queued`, `assigned`, `in_review`, `submitted`, `skipped`, `expired`), `actor_hash`, `at`. La vista `hitl_queue` toma el último estado por `item_id`.

### `hitl_reviews` (decisión humana, inmutable)

| Columna | Nota |
| :--- | :--- |
| `review_id`, `item_id`, `id_resena`, `task` | |
| `predicted_label`, `validated_label` | Sentimiento; o `predicted_families` y `validated_families` con las marcas `u` y `s` |
| `outcome` | `confirmed` o `corrected` |
| `display_mode`, `review_round` | Modo en que se revisó (copiado del caso) y número de revisión (1, o 2 en la doble revisión) |
| `flags` | `menciona_falla`, `duda`, `no_evaluable`, `nombre_persona` (guía `v2.2`) |
| `guideline_version`, `model_version`, `risk_policy_version` | `guideline_version` apunta a `guidelines` |
| `reviewer_hash` | |
| `opened_at`, `submitted_at`, `seconds_spent` | Mide el costo real de la revisión (alimenta los minutos de la curva) |
| `comment` | Comentario libre del revisor (opcional). Pasa por la sanitización de EPIC-4 antes de guardarse y se registra en la FMEA, porque es texto nuevo que podría traer PII |
| `ticket` | Ticket de backlog opcional |

Una segunda revisión del mismo caso es otra fila, con `review_round = 2` (sirve para medir acuerdo entre revisores).

### `guidelines` (guías vigentes a la vista del revisor)

`guideline_version`, `task` (`sentiment`, `aspects`, `topic`), `content_uri` (documento versionado, por ejemplo la guía `v2.2` de sentimiento o `v2.1` de aspectos), `valid_from`, `published_by_hash`. La vigente de cada tarea es la última con `valid_from` ≤ ahora. Las `low_confidence` son dirigidas y no dan cifras poblacionales (como el *dev* dirigido).

**Oro nuevo desde el HITL (decisión del autor, 2026-10-22).** La muestra de monitoreo no es una tabla aparte: es `hitl_items.reason = 'monitor_sample'`, una muestra aleatoria. Esas revisiones pueden entrar al oro, pero **separadas por versión** y no mezcladas con el oro de EPIC-5. Como `hitl_items`, `hitl_events` y `hitl_reviews` son de solo inserción y guardan `model_version`, `risk_policy_version`, `guideline_version` y fechas, ya son el historial; solo hace falta fijar qué entra en cada versión:

| Tabla | Grano | Columnas |
| :--- | :--- | :--- |
| `gold_versions` | Versión del oro | `gold_version` (p. ej. `gold_hitl_v1`), `criteria` (`reason = 'monitor_sample'`, periodo, `guideline_version`), `cutoff_at`, `items`, `created_by_hash`, `created_at` |

Los ítems de una versión se reproducen aplicando sus criterios a `hitl_reviews` con `submitted_at <= cutoff_at`. El oro de EPIC-5 (`gold_v0_r2` + `gold_v1`, con su *test* intacto) no cambia.

La curaduría de tópicos (`curation_topics` del borrador de 5.5) se queda aparte, porque su grano es el tópico y no la reseña.

## 5. Migración

| Hoy (EPIC-2) | Estado | Acción |
| :--- | :--- | :--- |
| `delora_predictions` (15 columnas) | Vacía | Se elimina; la reemplazan `review_predictions`, `review_aspects` y `text_embeddings` |
| `hitl_triage_audit_log` | Vacía, con `ABSATopic` | Se elimina (decisión del autor, P8-11); la reemplazan `hitl_items`, `hitl_events` y `hitl_reviews` |
| `sanitized_reviews_tds`, `ingestion_runs_log_v2` | En uso | Sin cambios |
| `AnalyzedReviewPrediction`, `HitlTriageAuditRecord`, `ABSATopic` (EPIC-1) | En `voc-common` | Se reemplazan por contratos v3 (6.1); `ABSATopic` se retira |
| Índice de Vertex de 768 dimensiones (EPIC-2) | Condicional, apagado | Se retira si P8-6 confirma BigQuery |
| `hitl_entropy_threshold` en `Settings` | Sin uso | Se retira; el umbral vive en `risk_policy` |

Como las dos tablas viejas están vacías, la migración no mueve datos: es un cambio de esquema en Pulumi y de contratos en `voc-common`. Orden propuesto: contratos (6.1), tablas nuevas (6.2), retiro de las viejas en la misma versión del stack.

## 6. Cobertura del frontal de EPIC-7

Revisión pantalla por pantalla (condición de P8-5, 2026-10-22) contra el [frontal reescrito](../backlog/epic_7.md).

| Pantalla (EPIC-7) | Lee | Escribe |
| :--- | :--- | :--- |
| Landing (7.3) | `ingestion_runs_log_v2` (EPIC-4), `inference_runs`, `incident_alerts` + `incident_alert_events`, `kpi_estimates` | — |
| Reporte (7.4) | Ninguna tabla: se publica desde `docs/analytics/` por versión | — |
| Cockpit (7.5) | `kpi_estimates` (PPI), vistas diarias sobre `review_predictions_current` y `review_aspects`, `topic_assignments`; la pestaña por versión usa `version_app` de `review_predictions` | — |
| Explorador (7.6) | `review_predictions_current`, `review_aspects`, `topic_assignments`, texto del TDS por `id_resena`, `text_embeddings`, `review_explanations` | `review_explanations` (bajo pedido) |
| HITL (7.7) | `hitl_queue`, `hitl_items` (sin `predicted` si es `blind`), `guidelines`, texto del TDS | `hitl_events`, `hitl_reviews`, curadurías de tópicos (5.5) |
| Alertas (7.8) | `incident_alerts`, `incident_alert_events`, `hitl_boosts`, `drift_metrics` | `incident_alert_events` |
| MLOps y AIOps (7.9) | `model_quality`, `hitl_coverage_curves`, `drift_metrics`, `model_versions`, `inference_runs`, `ingestion_runs_log_v2`, conteos por `eligibility_code` | — |
| Administración (7.10) | `risk_policy`, `hitl_boosts`, `drift_policy`, `drift_policy_template`, `hitl_coverage_curves`, `hitl_reviews` (tiempo medido), `gold_versions` | `risk_policy`, `drift_policy`, `gold_versions` |
| Seguridad (7.2) | Grupos de IAP y Cloud Audit Logs; no hay tabla de usuarios | — |

**Fuera del esquema, a propósito:** los usuarios y roles (los resuelve IAP), los registros de acceso (Cloud Audit Logs) y el contenido del reporte (documentos versionados del repositorio).

## Respuestas del autor (2026-10-22)

1. **`review_predictions` por reseña**, siempre que el backfill infiera por texto único para minimizar el costo (así queda en los principios).
2. **Las revisiones `monitor_sample` pueden entrar al oro, separadas por versión** (`gold_versions`, sección 4). La muestra es la marca `hitl_items.reason`, no una tabla.
3. **Sí se guarda un comentario del revisor** (`hitl_reviews.comment`), sanitizado antes de guardarse.

**Condición de la aprobación:** el esquema debe cubrir todas las necesidades del frontal de EPIC-7, que todavía no se revisa. Se vuelve a revisar al definir el alcance de EPIC-7 (P8-12).
