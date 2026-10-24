# EPIC-6: Despliegue del Core Analítico (Contratos, Infraestructura e Inferencia)

* **Estado (2026-10-24):** **6.1 y 6.2 implementadas** en la rama `feature/epic6-contracts` (PR a `develop`, las dos juntas para no romper `main`); 6.2 desplegada en el stack dev por el autor ([estado de 6.1](#estado-de-61-2026-10-23) y [de 6.2](#estado-de-62-2026-10-23)). 6.3 y 6.4 pendientes. **Features 6.1 a 6.4 detalladas** (archivos, tablas, firmas, pruebas y criterio de terminado) a partir del [registro de decisión de 5.8](../analytics/decision_record.md) y del [esquema v3](../contracts/analytics_outputs_v3.md), con las [decisiones de diseño del autor](#-decisiones-de-diseño-de-epic-6-autor-2026-10-23) del 2026-10-23. Esta épica se creó al reorganizar el backlog y junta lo que antes estaba disperso:
  * la fase 3 de EPIC-5 (antes `epic_5_deployment.md`, que se conserva como [anexo no vigente](#anexo-especificación-anterior-de-la-fase-3-no-vigente));
  * los cambios que la experimentación exige en los contratos de EPIC-1 y en la infraestructura de EPIC-2, que esas épicas marcaban como "condicionados a 5.8";
  * la base de datos de curadurías (antes tarea 6.7.2 del portal) y el monitor de *drift* (antes tarea 6.5.1).
* **Antes de empezar:** el [registro de decisión de 5.8](../analytics/decision_record.md) está aprobado y las [incompatibilidades](epic_5.md#incompatibilidades-entre-el-diseño-de-epic-6-y-epic-7-y-la-evidencia) resueltas (2026-10-22). Ninguna feature espera a 5.9: el autor la acotó a lo descriptivo el 2026-10-22 y la detección de incidentes quedó fuera del alcance. 6.3 carga los backfills que dejó 5.9. Los parámetros de apetito de riesgo sin evidencia se siembran nulos y los fija el dueño de negocio en 7.10 ([D12](#huecos-que-decide-el-autor)); el re-ajuste de tópicos y su emparejamiento se deciden en 6.4.
* **Semanas Objetivo:** tras 5.8 y antes de [EPIC-7](epic_7.md).
* **Dependencias:** [EPIC-5](epic_5.md) (5.6 calibración y umbral HITL, 5.7 escala, ciclo de vida y monitoreo, 5.8 registro de decisión; 5.9, backfills de familias, tópicos y embeddings y top 5 diario de temas, para 6.3) y EPIC-1 a EPIC-4, cerradas ([estado](epics.md#cierre-de-las-épicas-1-a-4)).
* **La consume:** [EPIC-7](epic_7.md), cuya API y portal leen las tablas de salida, escriben en la base de curadurías y muestran las alertas de deriva.
* **Orden:** 6.1 → 6.2 → 6.3 → 6.4 → 6.5. 6.2 deriva sus esquemas de los contratos de 6.1; 6.4 lee lo que escribe 6.3; 6.5 (reentrenamiento, D14) usa la promoción de 6.4 y el *re-scoring* de 6.3.
* **Directorios:**
  * `packages/voc-common/`: contratos v3 (modelos Pydantic, enums y códigos);
  * `packages/voc-nlp/` (nuevo): lógica pura compartida (elegibilidad, léxico, calibración, curva HITL, deriva, PPI, carga del modelo de sentimiento, oclusión, familias y tópicos). La usan `ml-inference` y, en EPIC-7, el servicio de explicaciones bajo pedido;
  * `services/ml-inference/` (nuevo): una imagen con los comandos `delta`, `backfill`, `load-local`, `seed`, `register`, `promote` y `monitor`. Reemplaza al stub vacío `services/ml-delora/`, que se borra;
  * `infra/`: tablas y vistas de BigQuery, Cloud Run Jobs, Scheduler e IAM;
  * `docs/contracts/analytics_outputs_v3.md`: contrato definitivo (antes el borrador `analytics_outputs_v3_draft.md`), como `ingestion_v2.md` para la ingesta.

---

## 🎯 Objetivo

Llevar a producción la estrategia que fijó 5.8: cargar los backfills de 5.8 y 5.9, correr un delta diario, guardar salidas versionadas en BigQuery, emitir alertas de deriva por banco y mantener una base de curadurías que alimente el reentrenamiento. Esta épica no decide modelos ni umbrales; implementa los que decidió EPIC-5.

---

## 🧭 Insumos de EPIC-5 que cambian EPIC-1 y EPIC-2

Lo implementado en EPIC-1 y EPIC-2 sigue en el código hasta que esta épica lo reemplace. Cada fila dice qué cambia y qué feature de EPIC-5 lo decide.

| Tema | Hoy (EPIC-1 y EPIC-2) | Evidencia o decisión de EPIC-5 | Decide | Feature aquí |
| :--- | :--- | :--- | :---: | :---: |
| Modelo de sentimiento | `sentimiento_roberta` y el docstring "DeLoRA" en `AnalyzedReviewPrediction` | **Decidido: RoBERTuito ajustado** (M4 en EPIC-5, P8-1): κ 0.929 en el oro *test*, contra 0.943 de M9, diferencia no significativa. Delora (M8) se descartó. `pysentimiento` es solo para uso no comercial. RoBERTuito ya tiene pesos guardados (lote `m4_ppi`, 5.6) | 5.8 (P8-1, P8-2) | 6.1, 6.3 |
| Taxonomía | 8 `ABSATopic`; `topico` obligatorio y único por reseña | 11 familias `aspects_v2_1` multi-etiqueta más las marcas `u` y `s`; los tópicos son una capa aparte, con versión y curada | 5.5 (aprobado) | 6.1, 6.2 |
| Filtro de longitud | `MIN_REVIEW_WORDS`/`MAX_REVIEW_WORDS = (2, 60)` y `cumple_umbral_palabras` | Sin filtro de longitud, porque la longitud predice las estrellas. Elegibilidad por reglas deterministas con código (`NO_PREDICTED`); `TOPIC_TOO_SHORT` con k = 1 | 5.1, 5.2; `TNSS_SINGLE_WORD` en 5.8 | 6.1 |
| Tabla de salida | `delora_predictions`: 15 columnas, agrupada por `topico` | Predicción por reseña versionada por modelo y corrida; tópicos por periodo; catálogo de tópicos con ciclo de vida; estado de elegibilidad; registro de corridas | 5.8 (P8-5) | 6.2 |
| Embeddings | `embedding_vector` de 768 dimensiones | Delora descartado; los tópicos usan MiniLM (384). La búsqueda semántica de EPIC-7 necesita su propio encoder | 5.8 (P8-6) | 6.2 |
| Umbral HITL | `hitl_entropy_threshold = 0.65` en `Settings` | Probabilidad máxima de RoBERTuito calibrado; **90 % de cobertura por defecto** (se revisa el ~10 % menos seguro, ~350 textos por semana), como parámetro configurable. La curva de cobertura y riesgo y el parámetro son estado de la aplicación: se guardan versionados y el frontal los muestra ([plan de 5.6](../analytics/calibration/calibration_design.md#31-decisión-del-autor-2026-10-22)) | 5.6 (decidido 2026-10-22) | 6.1 a 6.4 |
| Calibración | Ninguna | *Temperature scaling* con una T por semilla de RoBERTuito (≈ 1.7) | 5.6 (decidido 2026-10-22) | 6.1, 6.3 |
| Priorización | Fórmulas de `tnss_numeric_calibrated` y `priority_weight_score` | Se descartan: ordenan los incidentes igual que contar negativas, y los votos empeoran el orden. Se prioriza por volumen de negativas por familia y marca `u`, en nivel y en anomalía; los votos solo como contexto ([reporte de 5.6](../analytics/calibration/calibration_report.md#4-priorización-q4-decidido)) | 5.6 (decidido 2026-10-22) | 6.1, 6.3 |
| *Concept drift* | JSD de los 8 tópicos por versión | Proporción de las familias y de la marca `u` como series del monitor de deriva por banco; la señal de incidentes quedó fuera del alcance (5.9, 2026-10-22) | 5.7 (P7-6, P7-9) | 6.4 |
| Curaduría | `hitl_triage_audit_log` (sentimiento y un tópico) | Curadurías de sentimiento, aspectos y tópicos, inmutables, con versión de guía, modelo y prompt | 5.5 (aprobado); tabla de sentimiento en 5.8 (P8-11) | 6.2 |
| Entorno de cómputo | Sin definir | RoBERTuito infiere ~2 500 textos/s en la T4 y 39–53 en CPU; el backfill en Kaggle sacaría el corpus de GCP | 5.7 (P7-1, P7-2) | 6.2, 6.3 |
| Etiquetador y M9 | `enable_vertex_ai_api`; `enable_dedicated_vertex_endpoints = False` | Gemini por Vertex AI dentro del proyecto, sin endpoints dedicados; las familias en producción dependen de quién las etiquete | 5.3; 5.8 (P8-1, P8-7) | 6.2 |

## 🔒 Restricciones de despliegue que siguen vigentes

Vienen de la especificación anterior y no dependen del modelo:

* inferencia batch incremental sobre BigQuery en CPU (Cloud Run Job), con Vertex Endpoints solo como opción;
* persistencia por tabla temporal y `MERGE` idempotente, sin *Streaming Inserts* (patrón de EPIC-4);
* alertas validadas con un contrato de `voc-common` (`DriftAlertMessage`, que reemplaza a `IncidentAlertMessage`), sin texto ni PII;
* inferencia una vez por texto único elegible, propagada a sus filas; la fila excluida queda `NO_PREDICTED` con su código;
* el backfill de tópicos va después del de sentimiento, porque `TOPIC_NOT_NEGATIVE` usa el TNSS predicho;
* paquete en el workspace `uv`, imagen multi-stage sin root;
* pruebas deterministas sin red ni descargas de modelos.

## 🧱 Decisiones de diseño de EPIC-6 (autor, 2026-10-23)

Tomadas al detallar las features. Ninguna cambia una decisión de EPIC-5.

| # | Tema | Decisión |
| :---: | :--- | :--- |
| D1 | Dónde vive el código | `voc-common` solo con contratos y códigos; `packages/voc-nlp/` con la lógica pura, compartida con EPIC-7; `services/ml-inference/`, una imagen con varios comandos. Se borra el stub `services/ml-delora/` |
| D2 | Léxico `lexicon_v1` | Versionado en git dentro de `voc-nlp` (JSON con su SHA-256). Son 151 formas con su etiqueta agregada (soporte ≥ 3, pureza ≥ 0.9), no reseñas ni etiquetas individuales; es una excepción aprobada a la regla de datos |
| D3 | Alertas | Todas en 6.4 (`drift_alerts`). 6.3 solo predice y escribe |
| D4 | Precisión del delta (P7-2) | RoBERTuito en fp32 en el Job de 1 vCPU: ~25 s al día. Los pesos fp16 del registro (218 MB, la versión de modelo de 5.7) se cargan en fp32, así que hay un solo artefacto que versionar; sin int8 |
| D5 | Backfill y *re-scoring* en Kaggle (P7-1, P7-4) | **Reemplazada por D13 (2026-10-24).** Era una CLI que corría el autor desde su máquina, con el token de Kaggle en local: repetía el flujo de experimentación y bajaba los datos al equipo |
| D6 | Histórico de familias, tópicos y embeddings | Ya hechos en 5.9 ([reporte, §2](../analytics/incidents/incidents_report.md#2-backfill-de-familias-y-tópicos-p9-3)); 6.3 solo los carga |
| D7 | Piezas del esquema sin dueño | 6.3 crea los casos `low_confidence` de `hitl_items` y precalcula su oclusión (`review_explanations`). 6.4 crea `monitor_sample` y `agreement_sample` y calcula `kpi_estimates` con PPI sobre el oro *dev* aleatorio de EPIC-5, más las versiones `gold_hitl` cuando existan |
| D8 | Familias y marca `u` en el monitor | Se calculan y se guardan en `drift_metrics` con su z, con umbral nulo: nunca crean una alerta ni una subida HITL. MLOps las muestra como contexto |
| D9 | Organización del delta | Un solo Job con pasos en serie (RoBERTuito, Gemini, MiniLM y tópicos), liberando cada modelo antes del siguiente. Se mide la memoria; si 2 GiB no alcanza, se sube a 4 GiB |
| D10 | Oro en producción | Tabla `gold_labels` en BigQuery, cargada una vez desde local: oro *dev* aleatorio de EPIC-5 y las 300 etiquetas de familias de `aspects_gold_v2_1`. Agregada al [esquema v3](../contracts/analytics_outputs_v3.md#gold_labels-oro-en-producción-d10-de-epic-6) el 2026-10-23 |
| D11 | Nombres sin la jerga de EPIC-5 (autor, 2026-10-24) | El código y los valores que se guardan en BigQuery usan nombres que se entienden sin leer EPIC-5. Equivalencias: M4 (cuarto de los nueve modelos de 5.4) → RoBERTuito, módulo `sentiment_model.py`, `SentimentModel`, `load_sentiment_model` y extra `[sentiment]`; `M4_robertuito_s1_ppi` → `model_version` `robertuito_sentiment_v1` (semilla 1, T 1.6811); `model_v0` (BERTopic de 5.5) → `topic_model_version` `topics_v1`; `clauses_v0` → segmentador `clause_segmenter_v1`; `muestra_v21` → `GoldSplit.ASPECTS_GOLD_V2_1` (`aspects_gold_v2_1`). Los archivos locales de EPIC-5 conservan su nombre: la carga los traduce |
| D12 | Parámetros del apetito de riesgo sin evidencia (autor, 2026-10-24) | El tope semanal, la subida por deriva y la doble revisión de `risk_policy` los fija el dueño de negocio en 7.10. La v1 de `seed` los deja nulos (sin tope, sin subida automática, sin doble revisión); la subida y la doble revisión se configuran completas o no se configuran. `RiskPolicy` (`voc-common`) los acepta nulos. Con esto, la siembra ya no espera al autor |
| D13 | *Re-scoring* orquestado desde GCP (autor, 2026-10-24; reemplaza D5; se implementa en 6.4) | Un Cloud Run Job (`voc-ml-rescoring`, comando `rescore`, imagen `ml-inference`) hace el ciclo completo sin pasar por la máquina de nadie. (1) `EXPORT DATA` de los textos únicos a `gs://…/backfill/<corrida>/`. (2) Sube un dataset privado de Kaggle por corrida y lanza el kernel de GPU con los pesos del registro. (3) Espera el kernel, trae las predicciones a GCS y las carga con `MERGE` y la `model_version` nueva. (4) Verifica los conteos y entonces borra el dataset de Kaggle (F-14). El token de Kaggle vive en Secret Manager (`voc-kaggle-token`), y solo `voc-sa-ml-backend` lo lee. Lo dispara la promoción (6.4) o el autor con `gcloud run jobs execute`. Los datos siguen saliendo a Kaggle, como aceptó el autor en P7-1, pero ya no pasan por equipos locales. La carga inicial de los backfills de 5.8 y 5.9 (`load-local`) sigue siendo única y desde local, porque esos archivos ya existen en la máquina del autor |
| D14 | Reentrenamiento automatizado (autor, 2026-10-24) | Feature nueva, 6.5, que se detalla después de 6.4. El aviso `retrain` de `model_quality` o el autor disparan un Job que arma el conjunto de entrenamiento en BigQuery (la plata de Gemini más las correcciones del HITL) y entrena en GPU (un kernel de Kaggle, dentro de las 30 h semanales, o Cloud Run con GPU si el proyecto tiene cuota). Después evalúa en el oro *dev* con la regla de 5.4 y registra un candidato en Vertex Model Registry. La promoción la aprueba una persona y dispara el *re-scoring* (D13). El entrenamiento manda texto y etiquetas a Kaggle: F-13 |
| D15 | Avisos fuera del portal (autor, 2026-10-24) | Las alertas de deriva (`voc-incident-alerts-topic`) y los avisos de `model_quality` (`warning`, `retrain`, `rejected`) llegan por correo con un canal de notificación de Cloud Monitoring. Los avisos de calidad también publican un mensaje sin texto ni PII. Lo implementa 6.4, con su infraestructura en `infra/` |
| D16 | Carga del backfill (autor, 2026-10-24) | `load-local` corre en el Mac del autor: lee del TDS solo `id_resena`, `bank_id`, `fecha` y `texto_limpio`, en memoria y sin guardarlos, para la elegibilidad (FMEA F-11). Lo demás viaja sin texto: parquet con `text_key` en tablas temporales de BigQuery, y las tablas finales se arman con `MERGE` dentro de BigQuery |
| D17 | Oro y curva (autor, 2026-10-24) | `gold_labels` suma `weight` (1/π del oro *dev* aleatorio, para cifras poblacionales en la curva y en PPI) y su `id_resena` es nulo en el oro de aspectos (textos únicos). El oro se exporta con las funciones de EPIC-5 (`voc_analytics.labeling.export_gold_v3`) a un parquet sin texto. `CoveragePoint` acepta el intervalo de riesgo nulo donde 5.6 no lo midió (cobertura 1.0) |

### Huecos que decide el autor

Los tres primeros no son huecos del diseño sino **parámetros del apetito de riesgo**: los fijan el revisor y el dueño de negocio en la pantalla de administración (EPIC-7, 7.10), como dice el [registro de decisión](../analytics/decision_record.md) (sección 4, P7-6 a P7-8). No hay evidencia en EPIC-5 para ellos, así que la `risk_policy` v1 los siembra nulos (D12). Los dos últimos sí son decisiones de diseño del autor, y se resuelven en 6.4.

| Parámetro | Dónde | Estado |
| :--- | :--- | :--- |
| `hitl_weekly_cap` | `risk_policy` | Nulo en v1 = sin tope. Referencia para 7.10: la semana real de 5.9 dio 387 casos con el umbral del 90 % (cobertura real 86.4 %) |
| `drift_boost_coverage`, `drift_boost_days`, `drift_boost_weekly_cap` | `risk_policy` | Nulos en v1 = la alerta de deriva se registra, pero no crea una subida. Se configuran los tres juntos. La curva de 5.6 da el costo de cada cobertura |
| Tamaño y frecuencia de `agreement_sample` | `risk_policy` (`human_agreement_sample_size`, `human_agreement_frequency`) | Nulos en v1 = sin doble revisión entre personas (EPIC-7, 7.7). Se configuran juntos |
| Dónde corre el re-ajuste trimestral de tópicos (P7-8) | 6.4 | BERTopic sobre ~1 M de cláusulas no cabe en el Job de monitoreo (1 vCPU, 2 GiB); en 5.5 y 5.9 corrió en el Mac. Opciones: CLI del autor en local (copia local, F-11), un Job aparte con más memoria o Kaggle (texto fuera de GCP, como F-14) |
| Emparejamiento de tópicos entre reajustes | 6.4 | 5.5 no lo validó (ARI entre semillas de 0.40 a 0.97). Sin umbral automático: se propone el par de mayor similitud de centroides y el curador confirma cada uno |

---

## 📦 Features

### FEATURE 6.1: Contratos de predicción v3 en `voc-common`

**Objetivo:** reemplazar los contratos de predicción de EPIC-1 por los del esquema v3, con un modelo por tabla.

**Archivos que se crean:**

* `packages/voc-common/src/voc_common/analytics_codes.py`: enums (`StrEnum`) del esquema v3:
  * `EligibilityCode`: `ELEGIBLE`, `TNSS_EMPTY`, `TNSS_NO_TEXT_CONTENT`, `TNSS_TIME_OUTLIER`, `TNSS_SINGLE_WORD`;
  * `TopicEligibilityCode`: `ELEGIBLE`, `TOPIC_TNSS_NOT_PREDICTED`, `TOPIC_NOT_NEGATIVE`, `TOPIC_TOO_SHORT`;
  * `LabelSource`: `MODEL`, `RULE_BASED`, `NO_PREDICTED`;
  * `SentimentValue`: `NEG`, `NEU`, `POS`, `NO_PREDICTED` (`SentimentLabel` se queda para las tres clases);
  * `AspectFamily`: `AC`, `TR`, `DI`, `PR`, `AT`, `FA`, `LE`, `CO`, `DV`, `UX`, `OT`;
  * HITL: `HitlTask`, `HitlReason`, `DisplayMode`, `HitlStatus`, `ReviewOutcome`;
  * operación: `RunKind`, `RunEnvironment`, `ModelStatus`, `AlertStatus`, `BoostEndReason`, `QualitySignal`, `QualityStatus`, `KpiMethod`, `ExplanationSource`.
* `packages/voc-common/src/voc_common/predictions_v3.py`: salidas del modelo:
  * `ReviewPrediction` (`review_predictions`), `ReviewAspects` (`review_aspects`), `TextEmbedding` (`text_embeddings`, 384 floats);
  * tópicos: `TopicModelVersion`, `TopicCatalogEntry`, `TopicAssignment`, `TopicCuration` (`curation_topics`).
* `packages/voc-common/src/voc_common/operations_v3.py`: `ModelVersion`, `InferenceRun`, `DriftMetric`, `DriftAlert`, `DriftAlertEvent`, `KpiEstimate`, `ReviewExplanation`, `ModelQuality`, `GoldLabel` (D10) y el mensaje de Pub/Sub `DriftAlertMessage`.
* `packages/voc-common/src/voc_common/policies.py`: `RiskPolicy`, `HitlBoost`, `DriftThresholds` (el JSON de umbrales), `DriftPolicy`, `DriftPolicyTemplate`, `CoveragePoint` y `HitlCoverageCurve`.
* `packages/voc-common/src/voc_common/hitl_v3.py`: `HitlItem`, `HitlEvent`, `HitlReview`, `Guideline`, `GoldVersion`.
* `packages/voc-common/src/voc_common/bq_schema.py`: deriva el esquema de BigQuery de cada modelo, para que `infra/` no repita las columnas a mano.
* `docs/contracts/analytics_outputs_v3.md`: el borrador pasa a contrato, con una tabla "tabla → modelo → módulo".

**Estilo:** como los contratos v2 (`_StateV2`): `extra="forbid"`, `frozen=True`, `UtcDatetime`, validadores `mode="after"`. Columnas de dominio en español (`id_resena`, `estrellas`, `fecha`) y técnicas en inglés, como el esquema v3.

**Firmas principales:**

```python
def text_key(texto_sanitizado: str) -> str: ...  # voc_common.text_utils; SHA-256 hex de UTF-8, igual a TO_HEX(SHA256(...))

class ReviewPrediction(_AnalyticsRecord):
    id_resena: NonEmpty; bank_id: NonEmpty; text_key: Digest
    fecha: UtcDatetime; version_app: str | None; estrellas: int  # 1–5
    eligibility_rules_version: Literal["eligibility_rules_v1"]
    eligibility_code: EligibilityCode | None
    label_source: LabelSource; sentiment: SentimentValue | None
    p_neg: float | None; p_neu: float | None; p_pos: float | None
    confidence: float | None
    model_version: str | None; calibration_version: str | None
    risk_policy_version: str | None; hitl_boost_id: str | None
    requires_hitl: bool; run_id: NonEmpty; predicted_at: UtcDatetime

class DriftAlertMessage(_AnalyticsRecord):  # payload de voc-incident-alerts-topic; sin texto
    alert_id: str; bank_id: str; period: str; series: str
    value: float; threshold: float; drift_policy_version: str
    hitl_boost_id: str | None; triggered_at: UtcDatetime

BqField = tuple[str, str, str]  # (nombre, tipo, modo), como storage_bq._schema
def bq_schema(model: type[BaseModel]) -> tuple[BqField, ...]: ...
```

* `bq_schema` mapea `str` → `STRING`, `int` → `INT64`, `float` → `FLOAT64`, `bool` → `BOOL`, `datetime` → `TIMESTAMP`, `date` → `DATE`, `list[...]` → `REPEATED`, submodelos y `dict` → `JSON`; `Optional` → `NULLABLE`.

**Invariantes que validan los modelos** (las reglas del esquema v3):

* `ReviewPrediction`:
  * `eligibility_code != ELEGIBLE` ⇔ `label_source = NO_PREDICTED` ⇔ `sentiment = NO_PREDICTED`;
  * probabilidades y `confidence` presentes solo con `label_source = MODEL`; suman 1 (tolerancia 1e-6) y `confidence = max(p)`;
  * `requires_hitl` es `false` sin modelo; `hitl_boost_id` exige `risk_policy_version`.
* `ReviewAspects`: familias sin repetir; `sentiment_model_version` obligatorio.
* `HitlItem`: `reason` en (`monitor_sample`, `agreement_sample`) exige `display_mode = blind`; `drift_boost` exige `boost_id`.
* `HitlReview`: `review_round` en (1, 2); `outcome = confirmed` ⇔ etiqueta validada igual a la predicha.
* `RiskPolicy`: coberturas y pisos en [0, 1]; `set_by_hash` es un SHA-256.
* `DriftThresholds`: z y PSI positivos o nulos. Nulo = serie sin alerta (D8).

**Se retira de `voc-common`:**

* `AnalyzedReviewPrediction`, `HitlTriageAuditRecord`, `IncidentAlertMessage` (`schemas.py`);
* `ABSATopic`, `MIN_REVIEW_WORDS` y `MAX_REVIEW_WORDS` (`constants.py`), y `cumple_umbral_palabras` (`text_utils.py`);
* de `Settings` (`config.py`): `bq_predictions_table`, `bq_hitl_audit_table` y `hitl_entropy_threshold`. Se quitan también de `.env.example`, porque `test_config.py` exige que coincidan;
* las exportaciones de `__init__.py` y su `__all__`.

**Consumidores que se actualizan en la misma feature:** ningún servicio usa los contratos retirados. Los usan `infra/modules/storage_bq.py` (`_PREDICTIONS`, `_AUDIT`), `infra/modules/cloud_run.py` (variables `BQ_PREDICTIONS_TABLE` y `BQ_HITL_AUDIT_TABLE`), `infra/__main__.py` (exportaciones) y cuatro pruebas de `infra/tests/`. Para no romper `main`, 6.1 y 6.2 entran juntas en un mismo PR, o 6.1 deja los contratos viejos como obsoletos hasta 6.2.

**Pruebas** (`packages/voc-common/tests/`):

* `test_analytics_codes.py`: los valores de cada enum coinciden con el esquema v3 y con `eligibility_rules.md`.
* `test_predictions_v3.py`: los invariantes de arriba, parametrizados con casos válidos e inválidos; fábricas `_prediction(**overrides)` como en `test_schemas.py`.
* `test_text_key.py`: el hash de un texto sintético con acentos y emojis coincide con un valor fijo calculado con `TO_HEX(SHA256(...))`.
* `test_policies.py`: una `RiskPolicy` y una `DriftPolicy` sintéticas se serializan y vuelven igual; los umbrales nulos se aceptan.
* `test_hitl_v3.py`: `monitor_sample` asistido se rechaza; una segunda revisión es otra fila.
* `test_bq_schema.py`: cada modelo produce el tipo y el modo esperados, y un tipo no soportado falla.
* Fixtures JSON sintéticos en `tests/fixtures/analytics_v3/`, sin texto de reseñas.

**Terminado cuando:**

* los contratos y sus pruebas pasan con cobertura ≥ 85 % de `voc-common`;
* no queda ningún uso de los nombres retirados fuera de `docs/`;
* `docs/contracts/analytics_outputs_v3.md` reemplaza al borrador;
* EPIC-1 anota qué contratos quedaron reemplazados.

#### Estado de 6.1 (2026-10-23)

**Implementada; cumple los cuatro criterios.**

* **Código:** `analytics_codes.py`, `predictions_v3.py`, `operations_v3.py`, `policies.py`, `hitl_v3.py` y `bq_schema.py` (con `ANALYTICS_V3_TABLES`, el registro de las 26 tablas), más `text_key` en `text_utils.py`. Base común en `_analytics_base.py`. Fixtures sintéticas en `tests/fixtures/analytics_v3/`.
* **Pruebas:** `test_analytics_codes.py`, `test_text_key.py`, `test_predictions_v3.py`, `test_operations_v3.py`, `test_policies.py`, `test_hitl_v3.py` y `test_bq_schema.py`. Cobertura de `voc-common`: 99.9 % (piso 85 %).
* **Retiro:** los nombres de EPIC-1 ya no aparecen fuera de `docs/`. `enable_dedicated_vertex_endpoints` también salió de `Settings`, junto con su flag de infraestructura (6.2).
* **Enums que el detalle no nombraba** (aprobados por el autor): `TopicAudience`, `GoldSplit`, `RunStatus` y `ReviewFlag`.
* **Columnas que el borrador dejaba abiertas:** fijadas con el autor y anotadas en la [sección 8 del contrato](../contracts/analytics_outputs_v3.md#8-columnas-fijadas-al-implementar-2026-10-23).
* **Contrato:** `analytics_outputs_v3.md` reemplaza al borrador, con la tabla "tabla → modelo → módulo" (sección 7). EPIC-1 anota lo reemplazado.

### FEATURE 6.2: Infraestructura de salidas y curadurías (Pulumi)

**Objetivo:** aprovisionar en `infra/` las tablas, vistas, Jobs y permisos del esquema v3, y retirar lo de EPIC-2 que quedó obsoleto.

**Archivos que se crean:**

* `infra/modules/analytics_bq.py`: tablas y vistas v3, con esquemas de `bq_schema` (6.1).

  ```python
  @dataclass(frozen=True)
  class AnalyticsBqResources:
      tables: Mapping[str, gcp.bigquery.Table]
      views: Mapping[str, gcp.bigquery.Table]

  def create_analytics_bq(
      project: str, dataset: gcp.bigquery.Dataset, kms_key: str | None, is_dev: bool
  ) -> AnalyticsBqResources: ...
  ```

* `infra/modules/sql/*.sql`: una consulta por vista.
* `infra/tests/test_analytics_bq.py`.

**Tablas** (dataset `bbva_voc_tds`; columnas del esquema v3 vía su modelo de 6.1; todas de solo inserción):

| Grupo | Tabla | Partición (mes) | Agrupada por |
| :--- | :--- | :--- | :--- |
| Salidas | `review_predictions` | `fecha` | `bank_id`, `model_version`, `sentiment` |
| Salidas | `review_aspects` | `fecha` | `bank_id`, `prompt_version` |
| Salidas | `text_embeddings` | `mes` (P8-6) | `bank_id` |
| Tópicos | `topic_model_versions`, `topic_catalog`, `curation_topics` | — | `topic_model_version` |
| Tópicos | `topic_assignments` | `fecha` | `bank_id`, `topic_model_version` |
| Operación | `model_versions`, `inference_runs` | `inference_runs`: `started_at` | — |
| Operación | `drift_metrics`, `drift_alerts`, `drift_alert_events` | `period` / `created_at` / `at` | `bank_id` |
| Operación | `kpi_estimates`, `review_explanations`, `model_quality` | `computed_at` / — / — | `bank_id` donde exista |
| Políticas | `risk_policy`, `hitl_boosts`, `drift_policy`, `drift_policy_template`, `hitl_coverage_curves` | — | `bank_id` en `hitl_boosts` y `drift_policy` |
| HITL | `hitl_items`, `hitl_events`, `hitl_reviews` | `created_at` / `at` / `submitted_at` | `bank_id`, `task` |
| HITL | `guidelines`, `gold_versions`, `gold_labels` (D10) | — | — |

**Vistas** (`infra/modules/sql/`):

* `review_predictions_current`: la versión promovida (`model_versions.status = 'promoted'`) y, por `id_resena`, la última fila; calcula `estrellas_clase` y las marcas de incongruencia;
* `risk_policy_current` (global) y `drift_policy_current` (por banco): la última versión con `valid_from` ≤ ahora;
* `hitl_boosts_active`, `hitl_queue` (último estado por `item_id`) y `drift_alerts_current` (último evento por `alert_id`);
* `daily_topic_labels`: port en SQL de `voc_analytics.incidents.daily_topics` (5.9, P9-4); 6.3 la valida;
* `eligibility_counts`: conteos por banco, mes y `eligibility_code`, para MLOps (EPIC-7, 7.9).

**Archivos que cambian:**

* `infra/modules/storage_bq.py`: se borran `_PREDICTIONS`, `_AUDIT`, las tablas `delora_predictions` e `hitl_triage_audit_log` y sus campos de `StorageAndBqResources`. El helper `table()` acepta partición mensual (`type="MONTH"`) y tablas sin partición. El bucket `voc-datalake-<proyecto>` suma los prefijos `ml_artifacts/` (pesos de RoBERTuito, modelo de tópicos `topics_v1`) y `backfill/<corrida>/`, este último con el borrado a 7 días de `raw_staging/`.
* `infra/modules/vertex_ai.py`: se retiran el índice de 768 dimensiones y el endpoint `delora-tnss-endpoint` (P8-6). Queda `enable_vertex_ai_api`, que habilita Gemini y Model Registry; el flag `enable_dedicated_vertex_endpoints` se retira.
* `infra/modules/cloud_run.py`:
  * Job `voc-ml-inference-delta`: imagen `ml-inference`, comando `delta`, 1 vCPU y 2 GiB (4 GiB si la medición de 6.3 lo pide, D9), *timeout* 1 800 s, un reintento, cuenta `voc-sa-ml-backend`;
  * Job `voc-ml-monitor`: misma imagen, comando `monitor`, 1 vCPU y 2 GiB (6.4);
  * se quitan `BQ_PREDICTIONS_TABLE` y `BQ_HITL_AUDIT_TABLE`; `WorkloadImages` suma `ml_inference`.
* `infra/modules/cloud_scheduler.py`: `voc-trigger-ml-delta-daily`, una hora después de la sanitización (patrón de `voc-trigger-sanitization-daily`), y `voc-trigger-ml-monitor-weekly`, los lunes; zona `America/Mexico_City`.
* `infra/modules/kms_iam.py`: `create_datalake_access` da `roles/storage.objectUser` a `voc-sa-ml-backend` (pesos y exportaciones). Ya tiene `aiplatform.user`, `bigquery.dataEditor`, `bigquery.jobUser` y `pubsub.publisher`.
* `infra/__main__.py`: llama a `create_analytics_bq`, lee `ml_inference_image` y exporta las tablas nuevas en lugar de `bq_predictions_table` y `bq_hitl_audit_table`.
* `infra/Pulumi.dev.yaml`: `ml_inference_image` (digest) y sin `enable_dedicated_vertex_endpoints`.
* Fuera de `infra/`: `.github/workflows/cd-cloud-build.yaml` (lista `known` y mapa servicio → clave de config), `.github/workflows/ci.yaml` (job de imagen), `.dockerignore` (lista permitida) y la raíz `pyproject.toml` (deja de excluir el servicio nuevo y suma `voc-nlp`).

**Vertex Model Registry:** no es un recurso de Pulumi. 6.2 solo deja la API y el permiso; el registro y la promoción los hace `ml_inference register|promote` (6.3, 6.4).

**Pruebas** (`infra/tests/`, con los *mocks* de `conftest.py`):

* `test_analytics_bq.py`:
  * cada tabla v3 existe y su esquema es `bq_schema` de su modelo;
  * partición mensual y agrupación como en la tabla de arriba;
  * `deletion_protection` fuera de dev;
  * cada vista solo referencia tablas que existen.
* Se actualizan las que fijan las cuatro tablas de hoy: `test_infra.py`, `test_infra_v2.py`, `test_ingestion_audit.py` y `test_integration.py`. Esta última compara cada esquema con un modelo de `voc-common` y hoy solo acepta `STRING`, `INTEGER`, `TIMESTAMP`, `FLOAT` y `BOOLEAN`; pasa a aceptar `JSON`, `DATE` y los modos `REPEATED`.
* `test_compute.py`: sin el índice de 768; los dos Jobs con su memoria, comando y cuenta; el Scheduler con su permiso de invocación.
* `test_deployment_phases.py`: el servicio nuevo en el flujo de CD.

**Terminado cuando:**

* las pruebas de `infra/tests/` pasan con *mocks* y cobertura ≥ 80 % de `infra/modules`;
* el `pulumi preview` del stack dev (lo corre el autor) solo muestra las altas y bajas esperadas, y `delora_predictions` y `hitl_triage_audit_log` se borran (están vacías, así que no se mueven datos);
* EPIC-2 anota qué recursos quedaron reemplazados;
* la FMEA tiene su fila para el texto nuevo que guarda el esquema (`hitl_reviews.comment`, `drift_alert_events.note`) y para `gold_labels`.

#### Estado de 6.2 (2026-10-23)

**Implementada y desplegada en el stack dev (`pulumi up` del autor, 2026-10-24).**

* **Tablas y vistas:** `infra/modules/analytics_bq.py` crea las 26 tablas con `bq_schema`, partición mensual y la agrupación de la tabla de arriba, donde la columna existe: `drift_alert_events`, `hitl_events` y `model_quality` no tienen `bank_id`, y `hitl_reviews` se agrupa solo por `task`. Las 8 vistas están en `infra/modules/sql/`.
* **`daily_topic_labels`:** toma la versión de tópicos más reciente por `fitted_at` y el día en UTC. 6.3 la valida contra `daily_topics_v0`.
* **`storage_bq.py`:** sin `delora_predictions` ni `hitl_triage_audit_log`. El helper pasó a `bq_table()` (partición mensual o ninguna). `backfill/` se borra a los 7 días; `ml_artifacts/` no caduca.
* **Vertex:** se borró `vertex_ai.py` (índice de 768 y endpoint) y el flag `enable_dedicated_vertex_endpoints`. `enable_vertex_ai_api` sigue (Gemini y Model Registry).
* **Jobs y Scheduler:** `voc-ml-inference-delta` y `voc-ml-monitor` (1 vCPU, 2 GiB, 1 800 s, un reintento, `voc-sa-ml-backend`, subcomando como argumento), con `roles/run.invoker` para el Scheduler. Los triggers son `voc-trigger-ml-delta-daily`, una hora después de la sanitización (09:30 en free tier, 10:30 fuera de él), y `voc-trigger-ml-monitor-weekly`, los lunes una hora después del delta.
  * **Se crean solo si el stack tiene `ml_inference_image`**, porque la imagen se publica en 6.3; hasta entonces el preview no muestra Jobs nuevos.
* **IAM:** `voc-sa-ml-backend` recibe `roles/storage.objectUser` en el bucket.
* **CD:** `cd-cloud-build.yaml` conoce `ml-inference` (clave `ml_inference_image`) y lo omite mientras no tenga `Dockerfile`. `.dockerignore` permite `voc-nlp` y `ml-inference`.
* **Pasan a 6.3**, porque el servicio todavía no existe:
  * el job de imagen de `ci.yaml`;
  * el `pyproject.toml` de la raíz (quitar `services/ml-delora` de `exclude` al borrar el stub);
  * el digest de `ml_inference_image` en `Pulumi.dev.yaml`.
* **Pruebas:** `test_analytics_bq.py` nueva. Se actualizaron `test_integration.py` (acepta `INT64`, `FLOAT64`, `BOOL`, `DATE` y `JSON`), `test_infra.py`, `test_infra_v2.py`, `test_ingestion_audit.py`, `test_compute.py` (Jobs, triggers e invocadores; sin Vertex), `test_apis.py`, `test_watermark_storage.py` y `test_deployment_phases.py`. Cobertura de `infra/modules`: 100 % (piso 80 %).
* **Despliegue en dev (autor, 2026-10-24):**
  * el preview mostró lo esperado: 35 altas (26 tablas, 8 vistas y el permiso del bucket), 4 actualizaciones (la regla de borrado del bucket y una revisión nueva de los tres workloads de ingesta y sanitización, porque salen tres variables de entorno) y 2 bajas (`delora_predictions` y `hitl_triage_audit_log`, vacías);
  * el primer `pulumi up` falló en `hitl_queue` y `drift_alerts_current`: la columna `at` es palabra reservada de BigQuery y las vistas la leían sin comillas invertidas. Se corrigió y `test_analytics_bq.py` comprueba que ninguna vista lea sin comillas una columna con nombre reservado;
  * el segundo `pulumi up` completó el resto (2 vistas, la revisión de `voc-ingestion-worker` y las 2 bajas), y un preview posterior da 0 cambios (88 sin cambios). `INT64`, `FLOAT64` y `BOOL` no dejan diff permanente, así que `bq_schema` los conserva.
* **FMEA:** F-21 calificada (S 5, O 2, D 4, RPN 40; decisión del autor). EPIC-2 anota lo reemplazado.

### FEATURE 6.3: Servicio de inferencia batch

**Objetivo:** cargar los backfills de 5.8 y 5.9 y correr el delta diario, escribiendo en las tablas de 6.2.

**Paquete `packages/voc-nlp/` (nuevo):** lógica pura, portada de `voc_analytics` sin cambiar el criterio. Las dependencias pesadas van en *extras*: `[sentiment]` (torch CPU, transformers, pysentimiento), `[gemini]` (google-genai) y `[topics]` (sentence-transformers, umap-learn, hdbscan, bertopic).

| Módulo | Port de | Firmas principales |
| :--- | :--- | :--- |
| `eligibility.py` | `labeling/eligibility.py` (`with_tnss_rule_v1`) y las reglas de tópicos de `eda/eligibility_counts.py` | `RULES_VERSION = "eligibility_rules_v1"`; `count_words(texto_limpio: str) -> int`; `tnss_rule(texto_limpio: str, fecha: datetime, bank_id: str, lexicon: Lexicon) -> TnssDecision` (código, `LabelSource` y etiqueta del léxico); `topic_rule(sentiment: SentimentValue, palabras: int) -> TopicEligibilityCode` |
| `lexicon.py` y `data/lexicon_v1.json` | `eda/eda_lexicon.py` (`form`) y `data/eda/lexicon_v1.parquet` (D2) | `form(text: str \| None) -> str`; `load_lexicon() -> Lexicon` (valida el SHA-256) |
| `calibration.py` | `calibration/calibrate.py` (solo temperatura) | `apply_temperature(proba: np.ndarray, t: float) -> np.ndarray`; `confidence(proba: np.ndarray) -> np.ndarray` |
| `hitl.py` | Regla de 5.6 | `threshold_for(policy: RiskPolicy, boost: HitlBoost \| None, curve: HitlCoverageCurve) -> float`; `requires_hitl(confidence: float \| None, threshold: float) -> bool` |
| `sentiment_model.py` `[sentiment]` | `sentiment/encoder.py` y `scale/benchmark.py` | `load_sentiment_model(weights_dir: Path) -> SentimentModel` (fp32, CPU, D4); `predict_proba(model: SentimentModel, texts: Sequence[str], batch_size: int = 64) -> np.ndarray`, con `preprocess_tweet`, tope de 128 tokens, orden por longitud y verificación de `id2label` |
| `explain.py` `[sentiment]` | Experimento de 5.7 (§4) | `occlusion(model: SentimentModel, text: str) -> list[TokenAttribution]` (`occlusion_v1`); la reusa el servicio bajo pedido de EPIC-7 |
| `aspects.py` y `prompts/aspects_v2_1.md` `[gemini]` | `labeling/label_gemini.py`, `topics/aspects_scale.py` y `eda/eda_aspects_v2.py` (`parse`) | `parse(text: str) -> list[AspectLabel]`; `label_batch(client: genai.Client, items: Sequence[tuple[str, str]], prompt: str, model: str) -> list[AspectLabel]`, con reintento en lotes más chicos cuando falta un id |
| `topics.py` `[topics]` | `topics/units.py` (`clauses_v0` en EPIC-5; `clause_segmenter_v1` aquí), `topics/working_set.py` y `incidents/backfill_topics.py` | `segment(text: str) -> list[str]`; `embed(texts: Sequence[str]) -> np.ndarray` (MiniLM, 384, 128 tokens); `load_topic_model(path: Path) -> FrozenTopicModel`; `assign(model: FrozenTopicModel, embeddings: np.ndarray) -> list[int]` |

* `benchmark.encode` de 5.7 no aplicaba `preprocess_tweet`. `sentiment_model.py` lo aplica, como el entrenamiento y el backfill.
* La copia del prompt `aspects_v2_1.md` es idéntica a la de `voc_analytics/eda/prompts/` (una prueba compara el SHA-256).

**Servicio `services/ml-inference/` (nuevo):**

* Reemplaza al stub `services/ml-delora/` (9 archivos vacíos), que se borra junto con su entrada en el `exclude` del `pyproject.toml` raíz (D1). `README.md` deja de describir la arquitectura Dual LoRA (Delora) y lista `voc-nlp` y `ml-inference` en la estructura del monorepo.

* `pyproject.toml` (`voc-common`, `voc-nlp[sentiment,gemini,topics]`, `google-cloud-bigquery`, `google-cloud-storage`, `google-cloud-pubsub`, `google-cloud-aiplatform`; ruedas de torch CPU) y `Dockerfile` (patrón de `sanitization-pipeline`: uv multi-stage, usuario 10001, `ENTRYPOINT ["python", "-m", "ml_inference"]`).
* `src/ml_inference/__main__.py`: subcomandos `delta`, `backfill`, `load-local`, `seed`, `register`, `promote`, `monitor` (6.4).
* `config.py`: `InferenceSettings` (alias del modelo, `produccion`; URIs de artefactos; tamaños de lote; límite de textos por corrida).
* `bq_io.py`: generaliza `BigQueryTdsUpsertManager` de EPIC-4.

  ```python
  class StagingMergeWriter:
      def write(self, table: str, rows: Sequence[BaseModel], key: Sequence[str], run_id: str) -> int: ...
      # tabla temporal con expiración de 1 h → load_table_from_json → MERGE … WHEN NOT MATCHED THEN INSERT
      # → delete_table en finally; las tablas son de solo inserción, así que la clave hace idempotente la escritura
  ```

* `registry.py`:

  ```python
  def register(weights_uri: str, model_version: str, calibration_t: float,
               curve: HitlCoverageCurve, metrics: Mapping[str, float]) -> ModelVersion: ...
  def promote(model_version: str, actor_hash: str, reason: str) -> ModelVersion: ...  # mueve el alias produccion (mergeVersionAliases)
  def resolve(alias: str = "produccion") -> ModelVersion: ...
  ```

  El contenedor de *serving* que exige el registro es la imagen `ml-inference`, que nunca se despliega como endpoint (5.7, §6).

* `delta.py`: `run_delta(settings: InferenceSettings, clients: Clients, now: datetime) -> InferenceRun`. Pasos en serie (D9):
  1. **Pendientes:** filas del TDS sin fila en `review_predictions` para la versión promovida y su `text_key`, hasta el límite por corrida. Una reseña editada cambia de `text_key` y recibe otra fila; la vista toma la última.
  2. **Sentimiento:** elegibilidad v1 por fila; RoBERTuito una vez por texto único `MODEL`, ordenado por longitud; T de la versión; umbral de la `risk_policy` vigente o de la subida activa del banco; `MERGE` en `review_predictions`.
  3. **Familias:** negativas de dos palabras o más (`TOPIC_TOO_SHORT` con k = 1) sin fila en `review_aspects` para el mismo `text_key` y `prompt_version`; Gemini `aspects_v2_1` en lotes de 100; el texto que Gemini omite se reintenta en lotes más chicos y, si sigue fallando, queda pendiente para el día siguiente (no se guarda vacío).
  4. **Embeddings y tópicos:** MiniLM por `text_key` nuevo, una fila por banco × mes en `text_embeddings`; cláusulas y tópicos con `topics_v1` en `topic_assignments`.
  5. **HITL:** casos `low_confidence` en `hitl_items` (con `drift_boost` y su `boost_id` si hay una subida activa), modo `assisted`, hasta el tope semanal de la política; oclusión precalculada en `review_explanations` (`precomputed_hitl`).
  6. **Registro:** fila en `inference_runs` con conteos, duración, memoria pico y costo de Gemini.
* `load_local.py`: `load_backfill(run_dir: Path, run_id: str) -> list[InferenceRun]`. Carga única, desde la máquina del autor, de `experiments/analytics/data/backfill/20261022/` (fuera de git):
  * `preds/preds_s1.parquet` (`text_key`, `p_NEG`, `p_NEU`, `p_POS`, sin calibrar; semilla 1) con su T (1.6811), unida por `text_key` con las filas del TDS y la elegibilidad v1 → `review_predictions`;
  * `aspects/labels_by_key.parquet` (659 316 negativas) → `review_aspects`;
  * `topics/topics_by_key.parquet`, `segment_topics_v0.parquet` y el modelo `model_v0` de EPIC-5 → `topic_assignments`, `topic_model_versions` y `topic_catalog`, como `topics_v1`; la curaduría de 5.5 (fase 4) → `curation_topics`;
  * `embeddings/emb_minilm.npy` con `keys.parquet` → `text_embeddings`, replicada por banco × mes;
  * sube a `ml_artifacts/` los pesos de RoBERTuito (carpeta local `M4_robertuito_s1_ppi`, versión `robertuito_sentiment_v1`) y el modelo de tópicos (`topics_v1`).
  * Las 99 reseñas sin predicción, el lote de 100 textos que Gemini no etiqueta y los textos posteriores al snapshot entran con el primer delta.
* `seed.py`: `seed(settings: InferenceSettings, actor_hash: str, reason: str) -> None`. Inserta las versiones iniciales:
  * `model_versions`: `robertuito_sentiment_v1` promovido, con T 1.6811 y sus métricas en el oro *dev*;
  * `hitl_coverage_curves`: la curva de la semilla 1 de `selective_v0_metrics.json` (5.6);
  * `risk_policy` v1: `prob_max`, cobertura 0.90, umbral 0.974 (5.6), muestra de monitoreo de 300 por trimestre (P7-7, P7-10), re-ajuste trimestral (P7-8), piso de κ 0.89, avisos de 28 % y 94 % con 500 textos por semana (P7-10), familias con 53 % y prevalencia 5 % (P7-11). Tope semanal, subida por deriva y doble revisión nulos hasta que el dueño de negocio los fije en 7.10 ([D12](#huecos-que-decide-el-autor)).
  * `drift_policy_template` v1 y una `drift_policy` por banco desde ella: z ≥ 4 en las series de entrada y de `NEG`, PSI ≥ 0.25 en la longitud, 12 y 6 meses de línea base, 200 filas y 12 meses seguidos para entrar (P7-9); familias y `u` con umbral nulo (D8);
  * `guidelines`: `v2.2` de sentimiento y `v2.1` de aspectos;
  * `gold_labels`: el oro *dev* aleatorio y `aspects_gold_v2_1` (`muestra_v21` en EPIC-5), desde local (D10).

**Pruebas** (sin red ni descargas; cobertura ≥ 85 %):

* `packages/voc-nlp/tests/`:
  * `test_eligibility.py`: cada regla con casos sintéticos, el orden de precedencia, el corte de NUBANK y los tokens de PII;
  * `test_lexicon.py`: 151 formas (22 `NEG`, 7 `NEU`, 117 `POS`, 5 `NA`) y el SHA-256;
  * `test_calibration.py`: la T no cambia el argmax y T = 1 es la identidad;
  * `test_hitl.py`: el umbral sale de la política o de la subida del banco;
  * `test_aspects.py`: `parse` con líneas válidas, marcas `u`, `s` y elogio, y códigos desconocidos; la copia del prompt;
  * `test_m4.py`: modelo diminuto con configuración aleatoria, sin descarga; el orden por longitud se deshace bien;
  * `test_topics.py`: `segment` con cláusulas sintéticas y `assign` con un modelo falso.
* `services/ml-inference/tests/` (con un `FakeBigQuery` como el de `sanitization-pipeline` y RoBERTuito, Gemini y MiniLM falsos):
  * `test_delta.py`:
    * una inferencia por `text_key`, propagada a sus filas;
    * la fila no elegible queda `NO_PREDICTED` con su código y sin probabilidades; la de una palabra del léxico, `RULE_BASED`;
    * `requires_hitl` con el umbral de la política, y con la subida activa solo para su banco;
    * una segunda corrida no inserta nada;
    * la tabla temporal se borra aunque falle el `MERGE`;
    * un texto que Gemini omite queda pendiente.
  * `test_load_local.py`: parquet sintéticos con las columnas reales; la T se aplica y las probabilidades suman 1.
  * `test_registry.py`: `aiplatform` simulado; `promote` mueve el alias y escribe en `model_versions`.
* CI: `voc-nlp` y `ml-inference` en el job de calidad con su piso de cobertura, y un job de imagen (import de prueba, usuario 10001).

**Terminado cuando:**

* `review_predictions` tiene una fila por reseña del export del 2026-10-20 (2 653 238), con `robertuito_sentiment_v1` y su T, y los conteos por banco y `eligibility_code` reproducen `eligibility_v1_counts.json` salvo las reseñas que cambiaron después del snapshot;
* `review_aspects` tiene los 659 316 textos de 5.9, `text_embeddings` los 1 429 675 `text_key` y `topic_assignments` los tópicos de `topics_v1`;
* `daily_topic_labels` reproduce `daily_topics_v0` de 5.9 en una muestra de días × banco (comprobación local única);
* el Job programado corre el delta dentro de 2 GiB (o 4 GiB, D9), con su duración y memoria en `inference_runs`, y su primera corrida cubre los textos pendientes;
* los *quality gates* pasan sin red.

#### Estado de 6.3 (2026-10-24)

**Código y pruebas listos; faltan los pasos que corre el autor** (siembra, carga, imagen y primera corrida).

* **`packages/voc-nlp/`:** `eligibility`, `lexicon` (con `data/lexicon_v1.json`), `calibration`, `hitl`, `sentiment_model`, `explain`, `aspects` (con `prompts/aspects_v2_1.md`) y `topics`. Pruebas sin red ni descargas, con un RoBERTa diminuto aleatorio; cobertura 100 %.
  * Contraste con EPIC-5: la elegibilidad y `form` dan lo mismo en 662 filas sintéticas, que incluyen las 151 formas del léxico. RoBERTuito da probabilidades idénticas con los pesos reales de la semilla 1 (diferencia máxima 0.0).
  * La oclusión (`occlusion_v1`) guarda, por palabra, cuánto baja la probabilidad de la clase predicha al quitarla (decisión del autor). El experimento de 5.7 solo había medido el tiempo.
  * `aspects` acepta una respuesta parcial de Gemini y reintenta los ids faltantes en lotes más chicos. Una respuesta sin líneas válidas, con ids repetidos o ajenos, o con códigos desconocidos se reintenta hasta tres veces. Un texto que sigue sin etiqueta queda pendiente.
* **`services/ml-inference/`:** `delta`, `seed`, `load-local`, `register`, `promote` y `monitor`, que no hace nada hasta 6.4. Le sirven `config`, `bq_io` (tabla temporal + `MERGE` de solo inserción, con nulos iguales en la clave y consultas con identificadores validados), `state`, `engines` (un modelo cargado a la vez, D9) y `artifacts`. Cobertura 98 %.
  * El delta cubre los criterios de prueba de 6.3: una inferencia por `text_key`, `NO_PREDICTED` y `RULE_BASED`, el umbral de la política o de la subida del banco, el tope semanal (sin tope si es nulo, D12) y la idempotencia. También que la tabla temporal se borra aunque falle el `MERGE` y que el texto que Gemini omite queda pendiente. Las etiquetas y los embeddings ya conocidos se reutilizan sin volver a llamar al modelo.
  * La prioridad de los casos `low_confidence` es `1 − confidence`, porque al crearlos todavía no se conoce la familia.
* **Imagen:** `Dockerfile` multi-stage con torch de CPU (2.48 GB), usuario 10001 y sin descargas en tiempo de ejecución (`HF_HUB_OFFLINE`). La versión de torch para Linux sale del índice de CPU (`pyproject.toml` de la raíz).
* **CI y CD:** pasos de prueba de `voc-nlp` y `ml-inference`, el job `ml-inference-image` y 25 minutos de tope para el job de calidad. `tools/deploy_images.py` fija las tres imágenes del mismo commit.
* **Retiros:** el stub `services/ml-delora/` y su `exclude`. `README.md` ya no describe Delora.
* **Fuera de 6.3:** el *re-scoring* (D13) se implementa en 6.4, junto con `promote` y el *rollback* que lo disparan (decisión del autor, 2026-10-24).
* **Lo que hereda 6.4:**
  * la curva sembrada no tiene volumen por banco (`weekly_volume_by_bank = {}`): lo agrega el recálculo, que inserta con la clave `(model_version, calibration_version, computed_at)`;
  * las series de deriva que siembra `seed` son las de la sección 8 del contrato, y el monitor las lee por esos nombres;
  * `monitor` no hace nada hasta 6.4, para que el Job semanal no falle si se crea antes.
* **Datos:** las 2 etiquetas del backfill con el código inventado `UI` quedan sin familia, porque solo valen las 11 familias.
* **Pasos del autor, en orden:**
  1. Exportar el oro: `uv run python -m voc_analytics.labeling.export_gold_v3`, en `experiments/analytics`.
  2. Mezclar en `main`, esperar el CD y fijar las tres imágenes: `uv run python tools/deploy_images.py --project <proyecto> --apply`. Esto crea los Jobs y sus triggers; después hay que commitear `infra/Pulumi.dev.yaml`.
  3. Sembrar: `uv run python -m ml_inference seed --actor-hash <sha256> --reason "..."`.
  4. Cargar el backfill: `uv run python -m ml_inference load-local --actor-hash <sha256> --work <carpeta>`. La primera vez guarda MiniLM en `<carpeta>/minilm`.
  5. Ejecutar el delta una vez (`gcloud run jobs execute voc-ml-inference-delta`) y revisar duración y memoria en `inference_runs` (D9).
  6. Validar `daily_topic_labels` contra `daily_topics_v0` en una muestra de días × banco.
  7. Borrar las copias locales que cargó 6.3 (F-11).

### FEATURE 6.4: Monitoreo y ciclo de vida

**Objetivo:** el plan de monitoreo y de ciclo de vida de 5.7, en producción. Ya no espera a 5.9: la señal de incidentes quedó fuera del alcance y las familias son series de contexto, sin umbral (D8).

**En `packages/voc-nlp/`:**

| Módulo | Port de | Firmas principales |
| :--- | :--- | :--- |
| `drift.py` | `scale/drift_baseline.py` | `BINS = (0, 1, 2, 5, 10, 20, 40, 60, 10_000)`; `robust_z(values: Sequence[float], baseline: int = 12, min_baseline: int = 6) -> float \| None` (mediana y 1.4826·MAD de los meses previos); `psi(current: Sequence[int], reference: Sequence[int], floor: float = 1e-4) -> float`; `entry_month(rows_by_month: Mapping[str, int], min_rows: int = 200, months: int = 12) -> str \| None` |
| `selective.py` | `calibration/selective.py` | `curve(conf, err, w) -> tuple[np.ndarray, np.ndarray, np.ndarray]`; `at_coverage(conf, err, w, target: float) -> CoveragePoint`; `boot_risk(conf, err, w, strata, target: float) -> tuple[float, float]` |
| `ppi.py` | `calibration/ppi.py` | `ppi_mean(y_gold: np.ndarray, yhat_gold: np.ndarray, yhat_unlabeled: np.ndarray, w: np.ndarray \| None = None) -> Estimate` (estimación con IC 95 %); `gap_stars(...) -> Estimate` (P8-9) |
| `agreement.py` | `scale/model_monitor.py` | `cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float`; `exact_agreement(a: Sequence[frozenset[str]], b: Sequence[frozenset[str]]) -> float`; `family_kappa(a, b, family: str) -> FamilyAgreement` (κ con IC *bootstrap* y prevalencia; la regla de 5.7 compara κ, no prevalencias) |
| `topics_refit.py` `[topics]` | `topics/pilot.py` y `topics/dynamics.py` | `refit(segments: Sequence[str], embeddings: np.ndarray, params: TopicParams) -> FrozenTopicModel`; `match(previous: Sequence[TopicCatalogEntry], new: Sequence[TopicCatalogEntry]) -> list[TopicMatch]` (par de mayor similitud de centroides; sin umbral automático) |

**En `services/ml-inference/src/ml_inference/monitor/`** (comando `monitor`, Job semanal de 6.2):

* `drift_job.py`: `run_drift(settings, clients, now) -> list[DriftAlert]`.
  * Por banco, con su `drift_policy` vigente y desde su mes de entrada: cada mes cerrado que falte.
  * Series: palabras medias, textos de una palabra, de más de 60, no predecibles, vocabulario fuera del entrenamiento, proporción de `NEG` (z) y distribución de longitud (PSI). Familias y `u` con umbral nulo (D8).
  * Escribe `drift_metrics`. Si una serie cruza su umbral: `drift_alerts`, evento `open` en `drift_alert_events`, `DriftAlertMessage` en `voc-incident-alerts-topic` (nombre heredado de EPIC-2) y una subida en `hitl_boosts` solo para ese banco, con las reglas de `risk_policy` (P7-6).
  * `close_boosts(now)`: inserta la fila de cierre (`expired` o `alert_closed`) de cada subida vencida; nunca edita.
  * Sin subida configurada en la `risk_policy` vigente (D12), la alerta se registra y se publica, pero no crea una subida.
* Avisos por correo (D15): en `infra/`, una suscripción al tópico de alertas y un canal de correo de Cloud Monitoring. `quality.py` publica los `warning`, `retrain` y `rejected` en un tópico propio (`voc-model-quality-topic`), con un mensaje de `voc-common` sin texto.
* `samples.py`:
  * `create_monitor_sample(quarter: str, size: int) -> list[HitlItem]`: muestra aleatoria con semilla registrada entre las reseñas predichas por el modelo en el trimestre, siempre `blind` (P7-7);
  * `create_agreement_sample(...) -> list[HitlItem]`: doble revisión, `blind`; tamaño y frecuencia de la `risk_policy` vigente; con los dos nulos no crea casos (D12).
* `quality.py` (P7-10, P7-11) → `model_quality`:
  * `kappa_monitor(quarter: str) -> ModelQuality`: κ de RoBERTuito contra las revisiones de `monitor_sample`; `retrain` si queda debajo de `retrain_kappa_floor` (0.89);
  * `correction_rate(weeks: int = 4) -> ModelQuality`: `warning` si pasa de 28 % en la cola HITL;
  * `gemini_agreement(week: str) -> ModelQuality`: 500 textos por semana etiquetados por Gemini (~$0.02); `warning` si el acuerdo de 4 semanas baja de 94 %;
  * `families_validation(llm_model: str, prompt_version: str) -> ModelQuality`: corre al cambiar el modelo o el prompt de Gemini, sobre las 300 reseñas de `aspects_gold_v2_1` en `gold_labels` (~$0.03); `rejected` si el acuerdo exacto es < 53 % o una familia con prevalencia ≥ 5 % queda bajo el límite inferior de su IC.
  * Los avisos no disparan nada solos: los ve MLOps (EPIC-7, 7.9).
* `kpis.py`: `compute_kpis(period: str) -> list[KpiEstimate]`. `neg`, `gap_estrellas` (P8-9), `texto_peor`, `texto_mejor` y las celdas de la matriz 3 × 3 por banco y periodo, con PPI sobre el oro *dev* aleatorio de `gold_labels` (más las versiones `gold_hitl` cuando existan, D7) y su versión cruda (P8-10). Recalcula el mes en curso y el anterior.
* `lifecycle.py` (ciclo de vida de 5.7, §7):
  * `recompute_curve(model_version: str) -> HitlCoverageCurve`: curva sobre el oro *dev* de `gold_labels` (como `voc_analytics.calibration.selective`), con el volumen semanal real por banco y los minutos de `hitl_reviews.seconds_spent`; se guarda en `hitl_coverage_curves`;
  * `propose_risk_policy(curve: HitlCoverageCurve, coverage: float) -> RiskPolicy`: propone el umbral equivalente a la cobertura vigente; la nueva versión solo se inserta con quién y motivo (pantalla de administración de EPIC-7 o CLI del autor);
  * **promoción:** con la regla de 5.4 (diferencia pareada en el oro *dev* que excluye el 0, o empate a menor costo); `promote` mueve el alias, se recalcula la curva y el autor corre el *re-scoring* completo en Kaggle (`backfill`, P7-4), que inserta filas con la `model_version` nueva;
  * **rollback:** `promote` a la versión anterior; sus predicciones siguen en la tabla, así que no se re-predice;
  * **re-ajuste trimestral de tópicos** (P7-8): `refit` y `match`; el curador confirma cada emparejamiento en `curation_topics` (`mapping_confirmed`) antes de que la versión nueva asigne.

**En `services/ml-inference/src/ml_inference/rescore.py`** (D13; se implementa en 6.4, decisión del autor del 2026-10-24):

* `rescore.py` (D13; antes `backfill.py`, D5): el pipeline de `voc_analytics.scale.backfill`, sin constantes de proyecto, como pasos de un Job: `export(run)`, `push_dataset(run)`, `run_kernel(run, model_version)`, `wait_kernel(run, timeout)`, `pull(run)` (predicciones a GCS), `load(run, model_version)` y `cleanup(run)`. Corre en el Job `voc-ml-rescoring` con la API de Kaggle y el token de Secret Manager; nada pasa por un equipo local. Los pesos salen del registro. El kernel predice en GPU, y la calibración con la T de la versión se aplica en `load`. Cada corrida sube su propio dataset privado (`voc-backfill-corpus-<corrida>`), y `cleanup` lo borra de Kaggle en cuanto `load` verifica la carga en BigQuery (conteos por `text_key` y por `model_version`); si la verificación falla, el dataset se queda y la corrida no se da por terminada (FMEA F-14, decisión del autor, 2026-10-23). Paralelizar el `preprocess_tweet` antes de subir (5.7, §9: 27 min en la CPU de Kaggle).
* Infraestructura que suma 6.4 (D13): el Job `voc-ml-rescoring` (1 vCPU, 4 GiB por el dataset que arma en memoria, *timeout* de 3 h, sin Scheduler), el secreto `voc-kaggle-token` con `roles/secretmanager.secretAccessor` solo para `voc-sa-ml-backend`, y la API `secretmanager.googleapis.com`. El autor carga el valor del secreto, que no pasa por Pulumi ni por git.

**Pruebas** (sin red; cobertura ≥ 85 %):

* `voc-nlp`: `robust_z`, `psi` y `entry_month` reproducen `drift_baseline` en series sintéticas; `at_coverage` da el umbral esperado en un caso construido; `ppi_mean` coincide con una solución calculada a mano; `match` empareja centroides sintéticos.
* `ml-inference`:
  * `test_drift_job.py`: un banco antes de su mes de entrada no alerta; una serie con z ≥ 4 crea alerta, evento, mensaje y subida solo para su banco; familias y `u` nunca alertan; la subida vencida recibe su fila de cierre;
  * `DriftAlertMessage` no tiene campos de texto;
  * `test_samples.py`: `monitor_sample` siempre `blind` y reproducible con su semilla;
  * `test_quality.py`: κ debajo del piso da `retrain`; corrección de 30 % da `warning`; la regla de las familias acepta y rechaza en los bordes;
  * `test_lifecycle.py`: `promote` y *rollback* con `aiplatform` simulado; la curva recalculada coincide con `selective` en datos sintéticos.
  * `test_rescore.py`: Kaggle y Secret Manager simulados; el `EXPORT DATA` usa `TO_HEX(SHA256(texto_sanitizado))`; un kernel fallido o que excede el tiempo deja la corrida en `failed` sin cargar nada; `cleanup` borra el dataset de la corrida solo después de una carga verificada.

**Terminado cuando:**

* corrido sobre el histórico, el monitor reproduce las tasas de alerta de 5.7 (§2: de 0 a 1.4 meses al año por serie y banco);
* las alertas de deriva llegan al tópico con los umbrales de la `drift_policy` de cada banco, crean su subida HITL si la `risk_policy` la configura y llegan por correo (D15);
* `model_quality` registra cada medición de P7-10 y P7-11, y `kpi_estimates` llena el cockpit;
* promover recalcula y guarda la curva, y el *rollback* no re-predice;
* el portal de EPIC-7 puede consultar todo lo anterior.

#### Estado de 6.4 (2026-10-24)

**En curso.** Hecho:

* `voc_nlp.drift`: `BINS`, `length_bin`, `length_histogram`, `robust_z`, `psi` y `entry_month`. `robust_z` reproduce `drift_baseline.robust_z` en una serie sintética con nulos; los intervalos de longitud coinciden con `pl.cut(BINS[1:-1], left_closed=False)` de 0 a 199 palabras. Un mes ausente corta la racha de `entry_month`.
* `voc_nlp.selective`: `curve`, `at_coverage` (devuelve `CoveragePoint`), `resample` (el *bootstrap* estratificado de `sentiment.metrics`) y `boot_risk`, sin redondeo (es de presentación).
* `voc_nlp.ppi`: `ppi_mean` (PPI++ con λ en [0, 1], con pesos 1 / π del oro y del corpus por separado), `combine` (celdas pesadas por tamaño poblacional) y `gap_stars` (estrellas − texto, = −`brecha_neta` de 5.6). `Estimate` lleva también la versión solo-oro y la cruda del predictor (P8-10).
* `voc_nlp.agreement`: `cohen_kappa` sin scikit-learn (igual a `cohen_kappa_score` con pesos), `exact_agreement` y su IC, y `family_kappa`. Cambio frente a la firma prevista: la regla de 5.7 juzga el κ de cada familia con prevalencia ≥ 5 % contra su IC, así que `prevalence_ci` se reemplazó por `family_kappa`.
* Cobertura de `voc-nlp`: 100 % (108 pruebas).
* `ml_inference.monitor.drift_job` y el comando `monitor` (cierra subidas y corre la deriva):
  * dos consultas por corrida: `review_predictions_current` (palabras medias, una palabra, más de 60, no predecibles, `neg_share` sobre lo predicho y el histograma de `BINS`) y `review_aspects` (última etiqueta por reseña: `family_<código>` y `flag_update_share`);
  * calcula solo las series que nombra la `drift_policy` del banco, desde el mes siguiente al de entrada (como 5.7) hasta el último mes cerrado, y solo los meses sin filas en `drift_metrics`; alerta con `|z|` ≥ umbral o PSI ≥ umbral;
  * ids deterministas (`drift_<banco>_<mes>_<serie>`, `<alerta>_open`, `boost_<alerta>`) y `drift_metrics` se escribe al final: una corrida fallida se repite sin duplicar filas (el mensaje puede llegar dos veces);
  * una subida por banco: si ya tiene una activa, la alerta la cita y no abre otra. `close_boosts` cierra con `expired` las vencidas y con `alert_closed` las de alertas descartadas (`dismissed`);
  * `test_drift_job.py` cubre los criterios de la sección (cobertura de `ml-inference`: 98 %). Suma la dependencia `google-cloud-pubsub` y `drift_topic` en la configuración.
* `out_of_vocabulary_share` (decisión del autor, 2026-10-24: artefacto junto a los pesos): `ml_inference build-vocab` arma el vocabulario de 5.7 (palabras en minúsculas de la partición de entrenamiento de la plata) leyendo `archive/epic5/labels/silver_v0/` en memoria y lo sube a `ml_artifacts/sentiment/<model_version>/training_vocab.txt`, sin pasar por disco ni salir de GCP (F-01, F-11). Con el archivo real da las mismas 44 997 palabras que `drift_baseline.training_vocab`. El monitor baja el vocabulario del modelo promovido, lo carga en una tabla temporal y calcula la fracción de tokens de `texto_sanitizado` fuera de él, por banco y mes; sin vocabulario, la serie se omite con un aviso.
* `ml_inference.monitor.samples` (en el comando `monitor`, después de la deriva):
  * `create_monitor_sample`: `monitor_sample_size` reseñas del último trimestre cerrado, entre las predichas por el modelo promovido (`label_source = MODEL`); `create_agreement_sample`: `human_agreement_sample_size` del último periodo cerrado de `human_agreement_frequency` (`monthly` o `quarterly`), sin casos si los dos son nulos (D12);
  * siempre `blind`; la predicción se guarda en `predicted` para medir κ, y la API no la envía. Prioridad 1.0: van antes que los de baja confianza (prioridad 1 − confianza);
  * la semilla son 64 bits del SHA-256 de `<motivo>:<periodo>` y los candidatos se ordenan por `id_resena` antes de sortear: la muestra se reproduce. Ids `<motivo>:<periodo>:<id_resena>:<text_key[:16]>:<modelo>` con su evento `queued`; un periodo que ya tiene casos no se vuelve a muestrear;
  * `monitor_frequency` distinta de `quarterly` se registra como aviso y no muestrea.
* `ml_inference.monitor.quality` (en el comando `monitor`, después de las muestras), una fila de `model_quality` por sujeto × señal × periodo, sin repetirla:
  * `kappa_monitor`: κ de la primera revisión de la muestra del último trimestre cerrado, con IC *bootstrap*; se mide cuando toda la muestra está revisada; `retrain` bajo `retrain_kappa_floor`;
  * `correction_rate`: revisiones de `low_confidence` y `drift_boost` de las últimas 4 semanas que no confirman al modelo, una fila por semana ISO; `warning` arriba de `warn_correction_rate`;
  * `families_validation`: corre una vez por par `llm_model` × `prompt_version` (~$0.03). Etiqueta con Gemini las 300 reseñas de `aspects_gold_v2_1` (texto del TDS por `text_key`, dentro de GCP, F-10) y rechaza si el acuerdo exacto queda bajo `families_exact_floor` o si una familia con prevalencia ≥ `families_min_prevalence` queda con κ bajo el límite inferior de su IC de 5.7 (`FAMILY_BASELINE`, de `model_monitor_v0_metrics.json`). Si Gemini deja textos sin etiqueta, no escribe y se repite la semana siguiente;
  * los avisos (`warning`, `retrain`, `rejected`) se publican como `ModelQualityMessage` (nuevo en `voc-common`, sin texto ni IC) en `voc-model-quality-topic`;
  * `gemini_agreement` (antes `agreement_m4_gemini`; decisión del autor, 2026-10-24: nombres en lenguaje común): cada semana sortea en BigQuery `agreement_sample_weekly` textos que predijo el modelo en la semana ISO cerrada (semilla `gemini_agreement:<semana>`, solo salen los textos elegidos), los etiqueta con `voc_nlp.sentiment_gemini` (el prompt de la plata, `sentiment_v3.md`, idéntico a `prompt_v3`) y guarda el acuerdo de la semana sin los `NA`. El aviso se decide con el acuerdo combinado de esa semana y las 3 anteriores (ponderado por `n`) contra `warn_agreement_floor`. Las etiquetas de Gemini no se guardan: basta la fila semanal.
* Lenguaje común (decisión del autor, 2026-10-24): los módulos de 6.4 y sus pruebas ya no citan códigos del backlog (M4, P7-x, D-x, F-x, números de feature); cuando importa la evidencia, citan el reporte de `docs/analytics/`. Después se limpiaron igual los módulos de 6.3, `voc-common` (incluidos los títulos "Tarea 1.3.x" y "Feature x.y" de EPIC-1 a EPIC-4) y el contrato v3, que ahora enlaza los reportes de `docs/analytics/` en lugar de las preguntas y decisiones del backlog y ya no lleva la historia del borrador (está en el backlog y en git). `seed.EPIC5_MODEL` pasó a `REPORTS_MODEL`. Se conservan los valores de datos que ya pueden estar en BigQuery o en GCS (`gold_epic5_v1`, `archive/epic5/`).
* Infraestructura de avisos (D15), en `infra/` (sin aplicar en dev):
  * `voc-model-quality-topic` con su suscripción `voc-model-quality-sub` (7 días de retención), con la CMEK de los demás tópicos;
  * `voc-sa-ml-backend` publica solo en `voc-incident-alerts-topic` y `voc-model-quality-topic`: el `roles/pubsub.publisher` de proyecto se reemplazó por permisos por tópico (la API no publica). Los Jobs de ML reciben `DRIFT_TOPIC` y `QUALITY_TOPIC`;
  * `modules/alerting.py`: canal de correo de Cloud Monitoring y una política por tópico sobre `topic/send_request_count` (> 0 en 5 minutos, cierre automático a los 30). Cloud Monitoring no lee el mensaje: el correo dice qué pasó y de qué suscripción leerlo. Se crea solo con `bbva-voc-infra:alert_email` fijado (el correo no se versiona en el YAML). Suma `monitoring.googleapis.com`;
  * el `pulumi preview` de dev también trae una actualización de `gold_labels` que no viene de este cambio: `id_resena` pasa a `NULLABLE` (D17), más `BOOLEAN` → `BOOL` en tres columnas, que es el mismo tipo.
* **Pendiente del autor:** `pulumi config set bbva-voc-infra:alert_email <correo>` y `pulumi up` en dev; Cloud Monitoring manda un correo de verificación al canal.

Sigue, en orden: `kpis.py`, `lifecycle.py` (curva, promoción y *rollback*), `rescore.py` e infraestructura (Job `voc-ml-rescoring` y secreto `voc-kaggle-token`). `topics_refit.py` va con el re-ajuste trimestral.

### FEATURE 6.5: Reentrenamiento automatizado (D14)

**Objetivo:** que reentrenar RoBERTuito no dependa de repetir la experimentación de EPIC-5 en local.

**Se detalla después de 6.4**, con el mismo formato que las demás features. Partes previstas:

* un Job que arma el conjunto de entrenamiento en BigQuery: la plata de Gemini más las revisiones del HITL, sin el oro *test* (consumido en 5.8);
* entrenamiento en GPU: un kernel de Kaggle (el `finetune` de 5.4 sin constantes de proyecto) o Cloud Run con GPU si el proyecto tiene cuota;
* evaluación en el oro *dev* de `gold_labels` con la regla de 5.4, nueva T y curva de cobertura y riesgo, y registro del candidato en Vertex Model Registry;
* promoción con aprobación humana (pantalla de EPIC-7 o el autor), que dispara el *re-scoring* de D13.

---

## ✅ Checklist de Aceptación de la Épica 6

* [x] Contratos v3 en `voc-common`, con `bq_schema` y su documento en `docs/contracts/` (6.1).
* [ ] Tablas y vistas v3, Jobs de inferencia y de monitoreo, Scheduler e IAM aprovisionados con Pulumi; `delora_predictions`, `hitl_triage_audit_log` y el índice de 768 retirados (6.2). *Desplegado en dev el 2026-10-24; los Jobs de inferencia y monitoreo esperan la imagen de 6.3.*
* [ ] Backfills de 5.8 y 5.9 cargados y delta diario en operación con RoBERTuito fp32, Gemini y `topics_v1` (6.3).
* [ ] Política HITL y curva de cobertura y riesgo versionadas en BigQuery; la inferencia marca con la política vigente (6.1 a 6.3).
* [ ] Monitor de deriva por banco, subidas HITL, calidad de RoBERTuito y de las familias, KPI con PPI, promoción, *rollback* y re-ajuste de tópicos probados (6.4).
* [ ] Reentrenamiento automatizado con aprobación humana de la promoción (6.5, D14).
* [ ] *Quality gates* del monorepo (`ruff`, `pyrefly`, `bandit`, `pytest` con cobertura ≥ 85 %, ≥ 80 % en `infra/`) sin errores.

---

## Cambios en otros documentos

Salen de este detalle y se aplicaron el 2026-10-23, al mezclarlo en `feature/analytics`:

1. **[Esquema v3](../contracts/analytics_outputs_v3.md):** tabla `gold_labels` (D10); `text_key`, `bank_id` y `fecha` en `topic_assignments`; `palabras` en `review_predictions`; `local` en `inference_runs.environment`; `monitor_sample_size` sin repetir y `human_agreement_sample_size` y `human_agreement_frequency` en `risk_policy`; familias y `u` con umbral nulo en `drift_metrics` y `drift_policy.thresholds` (D8).
2. **[FMEA](../governance/ethical_fmea_matrix.md):** fila F-21, por el texto nuevo del esquema (`hitl_reviews.comment`, `drift_alert_events.note`) y las etiquetas de `gold_labels` en BigQuery. Se califica en 6.2.
3. **[`CLAUDE.md`](../../CLAUDE.md):** filas de EPIC-6 en el mapa de áreas, `voc-nlp` en los módulos compartidos y la excepción del léxico (D2).
4. **[`epic_5.md`](epic_5.md):** P7-2 decidida en fp32 (D4).

---

## Anexo: especificación anterior de la fase 3 (no vigente)

> Es la especificación original de EPIC-5, escrita antes de tener evidencia (antes `epic_5_deployment.md`, "borrador condicionado"). Se conserva por trazabilidad. Sus features se renombraron de 5.1–5.6 a A.1–A.6 para no confundirlas con las de `epic_5.md`; A.7 viene de la tarea 6.5.1 del portal. Lo que contradice la tabla de [insumos de EPIC-5](#-insumos-de-epic-5-que-cambian-epic-1-y-epic-2) **no se implementa**: los 8 `ABSATopic`, la arquitectura Dual LoRA, el filtro de 2 a 60 palabras, las 15 columnas de `delora_predictions` con 768 dimensiones, el umbral de 0.65 y la paridad dialectal con corpus sintético (se sustituye por paridad entre bancos y periodos).

### A.0: Objetivo y límites de la garantía

Consumir las reseñas curadas y desidentificadas desde `bbva_voc_tds.sanitized_reviews_tds` (`texto_limpio`, `estrellas`, `votos_utilidad`, `version_app`), ejecutar el modelo baseline (**RoBERTa** en español), aplicar la arquitectura **Dual LoRA (*Delora*)** para desacoplar el *Label Noise Bias* (*Obligatory 5-Star*) y obtener el **True Net Satisfaction Score (TNSS)**, clasificar la categoría de fallo operativo (**ABSA**), generar *embeddings* densos de **768 dimensiones**, persistir de forma idempotente en `bbva_voc_tds.delora_predictions` y emitir alertas hacia `voc-incident-alerts-topic` cuando se detecten picos de quejas con alta tracción comunitaria.

* **Límite de inferencia y generalización:** La separación entre la rama *Clean* (`θ + Δθ_c`) y la rama *Noisy* (`Δθ_n` condicionada a `estrellas`) reduce la contaminación por etiquetas ruidosas, pero no certifica verdad absoluta sobre la intención subjetiva del usuario. Por ello, las predicciones con entropía normalizada `prediction_entropy >= hitl_entropy_threshold` (`0.65`) o alta severidad activan obligatoriamente `requires_hitl = True` para validación humana en `EPIC-7`.
* **No re-inspeccionar ni alterar tokens DLP:** El modelo recibe `texto_limpio` junto con los tokens semánticos entre corchetes (`[PERSON_NAME]`, `[MX_CLABE_BANCARIA]`, `[BBVA_ACCOUNT_NUMBER]`, etc.) y códigos técnicos conservados (`ref: 3702:65c5:9xhchi`). El tokenizador debe tratar dichos tokens como vocabulario válido sin eliminarlos, ya que aportan contexto semántico directo para tópicos como `BLOQUEO_SEGURIDAD_3702` o `TRANSFERENCIAS_SPEI`.

### A.0b: Alineación con contratos e infraestructura (EPIC-1, EPIC-2 y EPIC-4)

El Agente IA **DEBE** acatar las siguientes 5 restricciones de acoplamiento con lo ya implementado en el monorepo:

1. **Esquema Fijo de 15 Columnas en `bbva_voc_tds.delora_predictions` (EPIC-1 Feature 1.3.5 y EPIC-2 Feature 2.4.2):**
   * Prohibido añadir o renombrar columnas al escribir en BigQuery. Toda fila insertada debe validarse previamente con `AnalyzedReviewPrediction` de `voc_common` (`extra="forbid"`), respetando exactamente las 15 columnas aprovisionadas en `storage_bq.py`:
     `id_resena`, `bank_id`, `version_app`, `fecha`, `estrellas`, `votos_utilidad`, `sentimiento_roberta`, `tnss_score`, `tnss_numeric_calibrated`, `is_obligatory_5_star_bias`, `topico`, `priority_weight_score`, `prediction_entropy`, `requires_hitl`, y `embedding_vector` (`FLOAT REPEATED` de longitud **768**, coincidiendo con la dimensión declarada en `infra/modules/vertex_ai.py`).
2. **Invariante del Sesgo *Obligatory 5-Star* (`is_obligatory_5_star_bias`):**
   * En `AnalyzedReviewPrediction` (EPIC-1), `is_obligatory_5_star_bias` se recalcula automáticamente como `bool(estrellas >= 4 and tnss_score == SentimentLabel.NEG)`. El motor analítico no debe sobreescribir esta regla con heurísticas contradictorias.
3. **Ejecución Batch Serverless Compatible con GCP Free Tier (`enable_dedicated_vertex_endpoints: false`):**
   * En `EPIC-2`, los endpoints dedicados de Vertex AI y Vertex Vector Search están desactivados por defecto (`enable_dedicated_vertex_endpoints=False`) para evitar cargos de nodos encendidos 24/7.
   * Por tanto, `inference_pipeline.py` debe operar por defecto en modo **`BATCH_BIGQUERY_INCREMENTAL`** (ejecutable en CPU local/Cloud Run Job bajo la identidad `voc-sa-ml-backend`), seleccionando únicamente las filas de `sanitized_reviews_tds` que aún no tienen predicción vigente en `delora_predictions`, y dejando el modo `VERTEX_ENDPOINT_ONLINE` como adaptador opt-in cuando el flag esté activo.
4. **Persistencia Idempotente vía Tabla Temporal y `MERGE` (Sin *Streaming Inserts*):**
   * Siguiendo el mismo patrón de `EPIC-4`, las predicciones no se insertan mediante `insert_all` (streaming). Se cargan en una tabla efímera `bbva_voc_tds._staging_predictions_{run_id}` (con expiración de 1 hora) vía `load_table_from_json` (`FILE_LOADS`) y se consolidan en `bbva_voc_tds.delora_predictions` mediante una sentencia `MERGE` por `(bank_id, id_resena)`.
5. **Emisión de Alertas Estrictamente Tipadas (`IncidentAlertMessage`):**
   * La cuenta `voc-sa-ml-backend` ya cuenta con `roles/pubsub.publisher` (EPIC-2 Feature 2.2). Las alertas enviadas a `voc-incident-alerts-topic` deben serializarse con `IncidentAlertMessage` de `voc-common`, sin incluir jamás textos crudos ni PII en el payload.

### A.1: Configuración del Paquete `ml-delora` y Baseline RoBERTa (`baseline_roberta.py`)

**Objetivo:** Configurar el paquete dentro del workspace de `uv` (usando ruedas de PyTorch CPU ligeras en CI/Docker para no exceder límites de imagen ni memoria en Cloud Run) e implementar el evaluador base con RoBERTa en español (`pysentimiento` / `robertuito-sentiment-analysis`) validado en el notebook del EDA.

#### Tarea A.1.1: Configurar `services/ml-delora/pyproject.toml`

Escribir `services/ml-delora/pyproject.toml` integrando `voc-common` desde el workspace:

```toml
[project]
name = "ml-delora"
version = "0.1.0"
description = "Core Analitico NLP: Baseline RoBERTa, Arquitectura Dual LoRA (Delora), ABSA e Inferencia hacia BigQuery"
requires-python = ">=3.11"
dependencies = [
    "torch>=2.2.0,<3.0.0",
    "transformers>=4.40.0,<5.0.0",
    "peft>=0.10.0,<1.0.0",
    "numpy>=1.26.0,<3.0.0",
    "scikit-learn>=1.4.0,<2.0.0",
    "google-cloud-bigquery>=3.20.0,<4.0.0",
    "google-cloud-storage>=2.16.0,<3.0.0",
    "google-cloud-pubsub>=2.21.0,<3.0.0",
    "pydantic>=2.6.0,<3.0.0",
    "voc-common",
]

[tool.uv.sources]
voc-common = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

```

#### Tarea A.1.2: Implementar `BaselineRobertaEvaluator` en `baseline_roberta.py`

1. **Modelo Base Fundacional:**

* Utilizar el checkpoint en español `pysentimiento/robertuito-sentiment-analysis` (basado en RoBERTa con dimensión oculta $d = 768$) a través de `AutoTokenizer` y `AutoModelForSequenceClassification` de `transformers`.
* Soportar carga desde caché local o ruta en Cloud Storage (`gs://voc-datalake-{project_id}/ml_artifacts/roberta_base/`) y permitir inyección de un modelo/tokenizador *mock* ligero para pruebas unitarias en CI sin descargas de red.

1. **Inferencia en Batch y Extracción de Embeddings (768-d):**

* Implementar `predict_batch(self, texts: list[str], batch_size: int = 32) -> list[BaselineOutput]`:
* Devuelve para cada `texto_limpio`:
* `label: SentimentLabel` (`NEG`, `NEU`, `POS`).
* `probabilities: tuple[float, float, float]` ($P(\text{NEG}), P(\text{NEU}), P(\text{POS})$ tras `softmax`).
* `pooled_embedding: list[float]` (Vector normalizado $L_2$ de **768 dimensiones** extraído del estado oculto del token `<s>` / mean pooling de la última capa, listo para almacenarse en `embedding_vector`).

### A.2: Arquitectura Dual LoRA (*Delora*) para Desacoplamiento de Ruido y Cálculo de TNSS (`model.py`, `scoring_and_entropy.py`)

**Objetivo:** Implementar la arquitectura matemática **Dual LoRA (*Delora*)** en PyTorch para separar la polaridad semántica real (**TNSS**) del sesgo conductual de calificación por estrellas (*Label Noise Bias*), junto con las funciones puras de calibración numérica, entropía de Shannon y ponderación de severidad.

#### Tarea A.2.1: Implementar `DeloraDualAdapterModel(nn.Module)` en `model.py`

1. **Estructura de Doble Rama sobre el Encoder Base ($d = 768$):**

* **Rama Limpia (*Clean Adapter* — $\Delta\theta_{\text{clean}}$):** Adaptador LoRA ($r=8, \alpha=16$, aplicado sobre proyecciones `query` y `value`) conectado al cabezal de clasificación limpio $W_{\text{clean}} \in \mathbb{R}^{768 \times 3}$. Esta rama recibe **únicamente el texto** (`input_ids`, `attention_mask`) y produce los logits depurados $z_{\text{clean}} = (z_{\text{NEG}}, z_{\text{NEU}}, z_{\text{POS}})$ que determinan el **`tnss_score`** (`SentimentLabel`).
* **Rama de Ruido (*Noisy Adapter / Transition Matrix* — $\Delta\theta_{\text{noisy}}$):** Segundo adaptador LoRA + módulo de transición condicional $T(h, y_{\text{stars}})$ que recibe la representación oculta $h$ y el embedding de `estrellas` ($1..5$) durante el entrenamiento para absorber la discrepancia sistemática donde textos con quejas operativas fueron etiquetados con 4 o 5 estrellas (*Obligatory 5-Star*).
* **Desacoplamiento en Tiempo de Inferencia (`forward_clean_inference`):** Durante la inferencia en producción para calcular el **TNSS**, se desactiva la rama de ruido ($\Delta\theta_{\text{noisy}}$) y se evalúa exclusivamente la rama limpia ($\theta_0 + \Delta\theta_{\text{clean}}$), aislando el sentimiento real del texto sin contaminación de la calificación inercial.

#### Tarea A.2.2: Implementar Fórmulas de Calibración, Entropía y Priorización en `scoring_and_entropy.py`

Implementar funciones matemáticas puras, deterministas y 100% testeables sin GPU:

1. **Score Continuo Recalibrado (`compute_tnss_numeric_calibrated`):**

* Dadas las probabilidades limpias $p = (p_{\text{NEG}}, p_{\text{NEU}}, p_{\text{POS}})$ donde $\sum p_i = 1$:

$$\text{tnss\_numeric\_calibrated} = \text{clip}\left(1.0 \cdot p_{\text{NEG}} + 3.0 \cdot p_{\text{NEU}} + 5.0 \cdot p_{\text{POS}},\, 1.0,\, 5.0\right)$$

* Permite calcular directamente el **Satisfaction Gap** ($\overline{\text{TNSS}}_{\text{calibrado}} - \overline{\text{Estrellas}}_{\text{oficial}}$) en escala de 1.0 a 5.0 para los dashboards de `EPIC-7`.

1. **Entropía Normalizada de Shannon y Disparo HITL (`compute_entropy_and_hitl_flag`):**

* Calcula la entropía sobre la distribución de probabilidad limpia $p \in \Delta^2$ normalizada por $\ln(3)$ para que viva estrictamente en el intervalo $[0.0, 1.0]$ requerido por `AnalyzedReviewPrediction`:

$$H_{\text{norm}}(p) = -\frac{1}{\ln(3)} \sum_{c \in \{\text{NEG, NEU, POS}\}} p_c \ln(\max(p_c, 10^{-12}))$$

* Determina `requires_hitl: bool`:
* Retorna `True` si `prediction_entropy >= hitl_entropy_threshold` (`0.65` por defecto en `Settings`), **o** si `is_obligatory_5_star_bias is True and votos_utilidad >= 5`, asegurando que tanto las predicciones inciertas como las quejas graves ocultas en 5 estrellas con tracción comunitaria pasen a validación humana.

1. **Ponderador de Severidad para el Backlog (`compute_priority_weight_score`):**

* Basado en el hallazgo del gráfico de violín del EDA (donde las reseñas negativas concentran picos de hasta ~100 votos de utilidad, validando tracción comunitaria):

$$\text{priority\_weight\_score} = \text{round}\left( \left(p_{\text{NEG}} + 0.5 \cdot \mathbb{I}[\text{is\_obligatory\_5\_star\_bias}]\right) \cdot \left(1.0 + \ln(1 + \text{votos\_utilidad})\right),\, 4 \right)$$

* Si `tnss_score == SentimentLabel.POS`, el multiplicador de severidad se atenúa por $(1 - p_{\text{POS}})$ para no inflar el backlog de ingeniería con comentarios positivos.

### A.3: Clasificador por Aspectos (ABSA) Híbrido para Dominio Bancario (`absa_classifier.py`)

**Objetivo:** Asignar cada reseña a uno de los 8 tópicos de `ABSATopic` (`voc-common`) combinando reglas léxicas de alta precisión para códigos/fallos bancarios explícitos con clasificación basada en similitud de embeddings / cabezal neuronal.

#### Tarea A.3.1: Implementar `BankingABSAClassifier` en `absa_classifier.py`

Clasificar el `texto_limpio` hacia las 8 categorías exactas de `ABSATopic`:

1. **`BLOQUEO_SEGURIDAD_3702`:** Prioridad alta ante presencia de códigos `ref: 3702`, `"suspendimos temporalmente tu acceso"`, `"motivos de seguridad"`, `"restaurar de fábrica"`, `"formatear"`, `"antivirus"`, `"opciones de accesibilidad"`, `"app sospechosa"`.
2. **`BIOMETRIA_RECONOCIMIENTO`:** Patrones y semántica de `"reconocimiento facial"`, `"huella dactilar"`, `"face id"`, `"biométrico"`, `"escaneo de mi cara"`, `"selfie"`, `"lector de huella"`.
3. **`TRANSFERENCIAS_SPEI`:** `"spei"`, `"transferencia"`, `"pago en tránsito"`, `"no llega el depósito"`, `"clabe"`, `"enviar dinero"`, `"codi"`, `[MX_CLABE_BANCARIA]`.
4. **`RENDIMIENTO_CRASH_POST_RELEASE`:** `"pantalla azul"`, `"pantalla en blanco"`, `"pantalla negra"`, `"se congela"`, `"se cierra forzosamente"`, `"borrar caché"`, `"forzar cierre"`, `"consume mucha batería"`, `"segundo plano"`, `"muy lenta"`.
5. **`SALDOS_Y_APARTADOS`:** `"apartados"`, `"aparecen unos puntitos"`, `"no veo mi saldo"`, `"desapareció mi dinero"`, `"historial de movimientos"`, `"saldo negativo"`.
6. **`TOKEN_Y_NOTIFICACIONES`:** `"token móvil"`, `"activar el token"`, `"notificaciones"`, `"no me avisa"`, `"código sms"`.
7. **`UX_INTERFAZ_Y_PUBLICIDAD`:** `"interfaz"`, `"nuevo diseño"`, `"publicidad"`, `"anuncios"`, `"ofertas de préstamos"`, `"versión anterior era más sencilla"`, `"poco intuitiva"`.
8. **`OTROS_SERVICIOS_GENERALES`:** Categoría por defecto o cuando el sentimiento es puramente elogioso general (`"excelente app"`, `"muy buen banco"`) sin fricción específica.

* **Mecanismo de respaldo semántico:** Cuando ninguna regla léxica de alta precisión dispara un match directo, calcular la similitud coseno entre el `embedding_vector` (768-d) de la reseña y los centroides prototípicos de cada `ABSATopic` (o cabezal lineal entrenado), seleccionando el `argmax`.

### A.4: Entrenamiento, Evaluación EDD y Paridad Dialectal (`train.py`, `evaluate.py`)

**Objetivo:** Proveer los scripts de entrenamiento de los adaptadores Dual LoRA y la suite de **Eval-Driven Development (EDD)** que audita los KPIs técnicos exigidos por la gobernanza de modelos de BBVA: *Negative Recall*, *Eficacia de Desacoplamiento de Ruido* y *Paridad Dialectal* en español mexicano.

#### Tarea A.4.1: Implementar `train.py` y Gestión de Artefactos en GCS

* Permitir entrenar los adaptadores `clean_adapter` y `noisy_adapter` a partir de un dataset en formato Parquet/JSONL o tabla de BigQuery (`sanitized_reviews_tds`), utilizando una función de pérdida conjunta con regularización de separación para que el adaptador limpio maximice la coherencia semántica con el texto mientras el adaptador ruidoso absorbe la transición hacia `estrellas`.
* Guardar y cargar los pesos de los adaptadores en `gs://voc-datalake-{project_id}/ml_artifacts/delora_v1/`.

#### Tarea A.4.2: Implementar `evaluate.py` con las 3 Métricas de Gobernanza (KPIs)

Implementar la función `evaluate_delora_governance_metrics(...) -> GovernanceEvaluationReport`:

1. **`negative_recall` ($\ge 0.85$ objetivo):** Recall de la clase `SentimentLabel.NEG` sobre el conjunto de evaluación curado, asegurando mínima omisión de quejas legítimas.
2. **`noise_decoupling_efficacy`:** Porcentaje de reseñas en el subconjunto ruidoso (*Obligatory 5-Star*: texto comprobadamente negativo pero con `estrellas` $\in \{4, 5\}$) donde `tnss_score` predice correctamente `SentimentLabel.NEG` en contraste con un clasificador condicionado a las estrellas.
3. **`dialect_parity_gap` (*Ethics by Design — Paridad Dialectal*):**

* Evalúa la diferencia absoluta de *Negative Recall* y *F1-Score* entre reseñas en **español estándar** (ej. `"la aplicación no funciona correctamente y presenta errores"`) y reseñas equivalentes con **modismos regionales mexicanos** reales presentes en el corpus del EDA (ej. `"no jala"`, `"se traba bien feo"`, `"chafa"`, `"un batallar"`, `"no pasa de ahí"`, `"a lo menso"`).
* Verifica que la brecha de precisión $\vert{}\text{Recall}_{\text{estándar}} - \text{Recall}_{\text{modismos\_mx}}\vert{} \le 0.05$ (degradación menor al 5%).

### A.5: Pipeline de Inferencia Incremental hacia BigQuery y Motor de Alertas Pub/Sub (`inference_pipeline.py`, `Dockerfile`)

**Objetivo:** Ejecutar la inferencia por lotes sobre las reseñas nuevas en `sanitized_reviews_tds`, persistir las 15 columnas en `delora_predictions` mediante `MERGE` y emitir alertas `IncidentAlertMessage` hacia `voc-incident-alerts-topic` cuando se detecten anomalías operativas post-release.

#### Tarea A.5.1: Implementar `DeloraBatchInferenceRunner` en `inference_pipeline.py`

1. **Consulta Incremental (Delta de Inferencia):**

* Consultar en BigQuery únicamente los registros de `bbva_voc_tds.sanitized_reviews_tds` (`s`) que no existan aún en `bbva_voc_tds.delora_predictions` (`p`) o cuya `s.sanitized_at > p.fecha` (acotado por `--limit`, default `2000` reseñas por ejecución):

```sql
SELECT s.id_resena, s.bank_id, s.version_app, s.fecha, s.estrellas, s.votos_utilidad, s.texto_limpio
FROM `{project}.{dataset}.sanitized_reviews_tds` s
LEFT JOIN `{project}.{dataset}.delora_predictions` p
  ON s.bank_id = p.bank_id AND s.id_resena = p.id_resena
WHERE p.id_resena IS NULL
ORDER BY s.fecha DESC
LIMIT @batch_limit

```

1. **Ejecución del Core Analítico y Validación Pydantic:**

* Procesar los textos en micro-lotes obteniendo `sentimiento_roberta`, `embedding_vector` (768 floats), `tnss_score`, `tnss_numeric_calibrated`, `is_obligatory_5_star_bias`, `topico`, `priority_weight_score`, `prediction_entropy` y `requires_hitl`.
* Instanciar y validar cada fila con `AnalyzedReviewPrediction` de `voc-common`.

1. **Upsert Idempotente en `bbva_voc_tds.delora_predictions`:**

* Crear tabla temporal `bbva_voc_tds._staging_predictions_{run_id}` con TTL de 1 hora, cargar el lote mediante `load_table_from_json` (`FILE_LOADS`), ejecutar `MERGE INTO bbva_voc_tds.delora_predictions` por `ON target.bank_id = source.bank_id AND target.id_resena = source.id_resena` y borrar la tabla temporal en un bloque `finally`.

1. **Detector de Picos de Incidencias y Publicación en `voc-incident-alerts-topic`:**

* Agrupar las predicciones recién procesadas por `(bank_id, version_app, topico)` donde `tnss_score == SentimentLabel.NEG`.
* Si para una tupla `(bank_id, version_app, topico)` el conteo de quejas negativas en la ventana supera `spike_min_reviews_threshold` (default `10`) **y** la suma de `votos_utilidad` supera `spike_min_utility_votes` (default `25`, reflejando validación comunitaria alta), construir un `IncidentAlertMessage` con hasta 10 `sample_review_ids` y publicarlo en `projects/{project_id}/topics/{pubsub_alerts_topic}`.

#### Tarea A.5.2: Implementar `services/ml-delora/Dockerfile`

Construir un `Dockerfile` multi-stage con `ghcr.io/astral-sh/uv:python3.11-bookworm-slim`, usuario no-root (`appuser`), instalando PyTorch CPU y el paquete `ml-delora` desde el workspace, con `ENTRYPOINT ["python", "-m", "ml_delora.inference_pipeline"]`.

### A.6: Suite de Pruebas Unitarias, Matemáticas y de Paridad Dialectal (`tests/`)

**Objetivo:** Verificar determinísticamente en CI (en menos de 10 segundos y sin descargar modelos pesados de HuggingFace ni conectarse a GCP) toda la arquitectura Dual LoRA, las ecuaciones de calibración/entropía/severidad, el clasificador ABSA y el disparo de alertas.

#### Tarea A.6.1: Implementar `test_model_and_scoring.py`, `test_absa_and_dialect.py` y `test_inference_and_alerts.py`

Escribir pruebas con `pytest` que verifiquen obligatoriamente:

1. **`test_delora_dual_branch_decoupling_and_dimensions`**:

* Instanciar `DeloraDualAdapterModel` con una configuración mini/sintética ($d=768$ en la salida de proyección). Verificar que `forward_clean_inference` produzca logits de 3 clases (`NEG`, `NEU`, `POS`), probabilidades que sumen `1.0` y un `embedding_vector` de exactamente **768 floats** sin requerir la entrada `estrellas`.

1. **`test_tnss_calibration_entropy_and_hitl_thresholds`**:

* Para una distribución uniforme $p = (1/3, 1/3, 1/3)$, comprobar que `prediction_entropy` sea `1.0` (`>= 0.65`) y active `requires_hitl = True`.
* Para una distribución segura $p = (0.95, 0.03, 0.02)$ con `estrellas = 5` (*Obligatory 5-Star*) y `votos_utilidad = 20`, comprobar que `tnss_score == SentimentLabel.NEG`, `is_obligatory_5_star_bias is True`, `tnss_numeric_calibrated` sea cercano a `1.14` (evidenciando un *Satisfaction Gap* de `-3.86` puntos frente a las 5 estrellas) y que `priority_weight_score` pondere logarítmicamente los votos de utilidad.

1. **`test_absa_classification_on_real_eda_examples`**:

* Probar ejemplos reales del notebook del EDA:
* `"no me deja entrar me sale que restringieron mi cuenta por motivos de seguridad: ref: 3702:65c5:9xhchi"` $\rightarrow$ `ABSATopic.BLOQUEO_SEGURIDAD_3702`.
* `"pide reconocimiento facial y no la valida dice que es incorrecto"` $\rightarrow$ `ABSATopic.BIOMETRIA_RECONOCIMIENTO`.
* `"las transferencias spei a otros bancos son muy tardías"` $\rightarrow$ `ABSATopic.TRANSFERENCIAS_SPEI`.
* `"se queda congelada en la pantalla azul y tengo que borrar caché"` $\rightarrow$ `ABSATopic.RENDIMIENTO_CRASH_POST_RELEASE`.
* `"desapareció mis apartados y solo se ven unos puntitos en mi saldo"` $\rightarrow$ `ABSATopic.SALDOS_Y_APARTADOS`.

1. **`test_mexican_dialect_parity_evaluation`**:

* Ejecutar `evaluate_delora_governance_metrics` sobre un corpus sintético pareado (español estándar vs. modismos mexicanos como `"no jala la app"`, `"está bien chafa"`, `"puro batallar"`), verificando el cálculo de `negative_recall`, `noise_decoupling_efficacy` y `dialect_parity_gap`.

1. **`test_bigquery_merge_schema_and_pubsub_spike_alert`**:

* Verificar con mocks de BigQuery y Pub/Sub que `DeloraBatchInferenceRunner` serialice exactamente las **15 columnas** de `delora_predictions`, limpie la tabla temporal `_staging_predictions_*` en el bloque `finally`, y emita un `IncidentAlertMessage` válido en `voc-incident-alerts-topic` cuando un tópico supere los umbrales de quejas y votos de utilidad.

### A.7: Monitor de *drift* (antes tarea 6.5.1 del portal)

#### Tarea A.7.1: Implementar `ModelDriftMonitor` en `services/ml-delora/src/ml_delora/drift_monitor.py`

1. **Detección de *Data Drift* (Divergencia de Entrada):**

* Calcula la divergencia de Jensen-Shannon ($JSD \in [0, 1]$) y el *Population Stability Index (PSI)* entre la distribución de longitud de palabras / frecuencia de tokens de la ventana actual y la distribución del baseline de entrenamiento.

1. **Detección de *Concept Drift* (Transición entre Versiones de la App):**

* Calcula la divergencia de Jensen-Shannon entre la distribución de los 8 tópicos de `ABSATopic` de la versión saliente de la app y la versión entrante, así como el cambio abrupto en la proporción de *Label Noise Bias* ($P(\text{TNSS}=\text{NEG} \mid \text{estrellas} \ge 4)$).

1. **Disparo Automático del *Fallback Plan*:**

* Si `data_drift_psi >= 0.25` o `concept_drift_jsd >= 0.20`, construye una alerta crítica y la publica en `voc-incident-alerts-topic` recomendando congelar pesos adaptativos, activar ruteo conservador a HITL y detonar reentrenamiento en Vertex AI.

#### Prueba (antes en la tarea 6.6.1)

1. **`test_drift_monitor_detects_concept_shift_and_publishes_alert`**:

* Simular un cambio drástico en la distribución de tópicos entre la versión `26.80.11` y `26.90.12` (ej. `BLOQUEO_SEGURIDAD_3702` pasa del 5% al 65% de las quejas). Comprobar que `ModelDriftMonitor` calcule `concept_drift_jsd >= 0.20` y publique una alerta en `voc-incident-alerts-topic`.

### Checklist anterior (no vigente)

* [ ] Genera objetos `AnalyzedReviewPrediction` 100% compatibles con las 15 columnas de `bbva_voc_tds.delora_predictions` en BigQuery, incluyendo `embedding_vector` de 768 dimensiones.
* [ ] Aísla el sesgo *Obligatory 5-Star* (`is_obligatory_5_star_bias = True` cuando `estrellas >= 4` y `tnss_score == NEG`) y calcula el score continuo `tnss_numeric_calibrated` en escala `[1.0, 5.0]`.
* [ ] Clasifica los 8 tópicos de `ABSATopic` aprovechando tanto códigos preservados (`ref: 3702`) y tokens DLP (`[MX_CLABE_BANCARIA]`) como similitud semántica.
* [ ] Opera por defecto en modo batch incremental sobre BigQuery (`FILE_LOADS` + `MERGE` sin *Streaming Inserts*), respetando el modo *Free Tier* (`enable_dedicated_vertex_endpoints: false`).
* [ ] Emite alertas `IncidentAlertMessage` hacia `voc-incident-alerts-topic` sin exponer PII ni texto crudo.
* [ ] Los comandos `uv run ruff check services/ml-delora`, `uv run ruff format --check services/ml-delora`, `uv run pyrefly check`, `uv run bandit -c pyproject.toml -r services/ml-delora` y `uv run pytest services/ml-delora/tests --cov=services/ml-delora/src --cov-fail-under=85` pasan con **0 errores**.
