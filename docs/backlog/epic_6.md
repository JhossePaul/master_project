# EPIC-6: Despliegue del Core Analítico (Contratos, Infraestructura e Inferencia)

* **Estado (2026-10-22):** Pendiente. Las features están delimitadas; el **registro de decisión de EPIC-5 (5.8) se aprobó el 2026-10-22**, así que la primera tarea es detallarlas (archivos, firmas y pruebas) a partir de él. Esta épica se creó al reorganizar el backlog y junta lo que antes estaba disperso:
  * la fase 3 de EPIC-5 (antes `epic_5_deployment.md`, que se conserva como [anexo no vigente](#anexo-especificación-anterior-de-la-fase-3-no-vigente));
  * los cambios que la experimentación exige en los contratos de EPIC-1 y en la infraestructura de EPIC-2, que esas épicas marcaban como "condicionados a 5.8";
  * la base de datos de curadurías (antes tarea 6.7.2 del portal) y el monitor de *drift* (antes tarea 6.5.1).
* **Antes de empezar:** el [registro de decisión de 5.8](../analytics/decision_record.md) está aprobado y las [incompatibilidades](epic_5.md#incompatibilidades-entre-el-diseño-de-epic-6-y-epic-7-y-la-evidencia) resueltas (2026-10-22). Solo 6.4 espera a 5.9, por los umbrales de la señal de incidentes (P9-1).
* **Semanas Objetivo:** tras 5.8 y antes de [EPIC-7](epic_7.md).
* **Dependencias:** [EPIC-5](epic_5.md) (5.6 calibración y umbral HITL, 5.7 escala, ciclo de vida y monitoreo, 5.8 registro de decisión; 5.9, incidentes y versiones, solo para 6.4) y EPIC-1 a EPIC-4, cerradas ([estado](epics.md#cierre-de-las-épicas-1-a-4)).
* **La consume:** [EPIC-7](epic_7.md), cuya API y portal leen las tablas de salida, escriben en la base de curadurías y muestran las alertas.
* **Directorios (provisionales):**
  * `packages/voc-common/`: contratos de predicción, elegibilidad y curaduría;
  * `infra/`: tablas de BigQuery, Cloud Run Jobs, Scheduler e IAM;
  * `services/ml-<nombre>/`: servicio de inferencia. El nombre `ml-delora` queda obsoleto porque 5.4 descartó Delora; se fija en 6.3;
  * `docs/contracts/`: contrato de predicción, como `ingestion_v2.md` para la ingesta.

---

## 🎯 Objetivo

Llevar a producción la estrategia que fije 5.8: un backfill único sobre los textos únicos elegibles y un delta diario, con salidas versionadas en BigQuery, alertas por familia de aspectos y marca `u`, y una base de curadurías que alimente el reentrenamiento. Esta épica no decide modelos ni umbrales; implementa los que decida EPIC-5.

---

## 🧭 Insumos de EPIC-5 que cambian EPIC-1 y EPIC-2

Lo implementado en EPIC-1 y EPIC-2 sigue en el código hasta que esta épica lo reemplace. Cada fila dice qué cambia y qué feature de EPIC-5 lo decide.

| Tema | Hoy (EPIC-1 y EPIC-2) | Evidencia o decisión de EPIC-5 | Decide | Feature aquí |
| :--- | :--- | :--- | :---: | :---: |
| Modelo de sentimiento | `sentimiento_roberta` y el docstring "DeLoRA" en `AnalyzedReviewPrediction` | **Decidido: M4 RoBERTuito** (P8-1): κ 0.929 en el oro *test*, contra 0.943 de M9, diferencia no significativa. Delora (M8) se descartó. `pysentimiento` es solo para uso no comercial. M4 ya tiene pesos guardados (lote `m4_ppi`, 5.6) | 5.8 (P8-1, P8-2) | 6.1, 6.3 |
| Taxonomía | 8 `ABSATopic`; `topico` obligatorio y único por reseña | 11 familias `aspects_v2_1` multi-etiqueta más las marcas `u` y `s`; los tópicos son una capa aparte, con versión y curada | 5.5 (aprobado) | 6.1, 6.2 |
| Filtro de longitud | `MIN_REVIEW_WORDS`/`MAX_REVIEW_WORDS = (2, 60)` y `cumple_umbral_palabras` | Sin filtro de longitud, porque la longitud predice las estrellas. Elegibilidad por reglas deterministas con código (`NOT_PREDICTED`); `TOPIC_TOO_SHORT` con k = 1 | 5.1, 5.2; `TNSS_SINGLE_WORD` en 5.8 | 6.1 |
| Tabla de salida | `delora_predictions`: 15 columnas, agrupada por `topico` | Predicción por reseña versionada por modelo y corrida; tópicos por periodo; catálogo de tópicos con ciclo de vida; estado de elegibilidad; registro de corridas | 5.8 (P8-5) | 6.2 |
| Embeddings | `embedding_vector` de 768 dimensiones | Delora descartado; los tópicos usan MiniLM (384). La búsqueda semántica de EPIC-7 necesita su propio encoder | 5.8 (P8-6) | 6.2 |
| Umbral HITL | `hitl_entropy_threshold = 0.65` en `Settings` | Probabilidad máxima de M4 calibrado; **90 % de cobertura por defecto** (se revisa el ~10 % menos seguro, ~350 textos por semana), como parámetro configurable. La curva de cobertura y riesgo y el parámetro son estado de la aplicación: se guardan versionados y el frontal los muestra ([plan de 5.6](../analytics/calibration/calibration_design.md#31-decisión-del-autor-2026-10-22)) | 5.6 (decidido 2026-10-22) | 6.1 a 6.4 |
| Calibración | Ninguna | *Temperature scaling* con una T por semilla de M4 (≈ 1.7) | 5.6 (decidido 2026-10-22) | 6.1, 6.3 |
| Priorización | Fórmulas de `tnss_numeric_calibrated` y `priority_weight_score` | Se descartan: ordenan los incidentes igual que contar negativas, y los votos empeoran el orden. Se prioriza por volumen de negativas por familia y marca `u`, en nivel y en anomalía; los votos solo como contexto ([reporte de 5.6](../analytics/calibration/calibration_report.md#4-priorización-q4-decidido)) | 5.6 (decidido 2026-10-22) | 6.1, 6.3 |
| *Concept drift* | JSD de los 8 tópicos por versión | Proporción de las familias y de la marca `u`, que se adelantó a los incidentes de BBVA | 5.9 (P9-1); 5.7 (P7-6) | 6.4 |
| Curaduría | `hitl_triage_audit_log` (sentimiento y un tópico) | Curadurías de sentimiento, aspectos y tópicos, inmutables, con versión de guía, modelo y prompt | 5.5 (aprobado); tabla de sentimiento en 5.8 (P8-11) | 6.2 |
| Entorno de cómputo | Sin definir | M4 infiere ~2 500 textos/s en la T4 y 39–53 en CPU; el backfill en Kaggle sacaría el corpus de GCP | 5.7 (P7-1, P7-2) | 6.2, 6.3 |
| Etiquetador y M9 | `enable_vertex_ai_api`; `enable_dedicated_vertex_endpoints = False` | Gemini por Vertex AI dentro del proyecto, sin endpoints dedicados; las familias en producción dependen de quién las etiquete | 5.3; 5.8 (P8-1, P8-7) | 6.2 |

## 🔒 Restricciones de despliegue que siguen vigentes

Vienen de la especificación anterior y no dependen del modelo:

* inferencia batch incremental sobre BigQuery en CPU (Cloud Run Job), con Vertex Endpoints solo como opción;
* persistencia por tabla temporal y `MERGE` idempotente, sin *Streaming Inserts* (patrón de EPIC-4);
* alertas validadas con `IncidentAlertMessage`, sin texto ni PII;
* inferencia una vez por texto único elegible, propagada a sus filas; la fila excluida queda `NOT_PREDICTED` con su código;
* el backfill de tópicos va después del de sentimiento, porque `TOPIC_NOT_NEGATIVE` usa el TNSS predicho;
* paquete en el workspace `uv`, imagen multi-stage sin root;
* pruebas deterministas sin red ni descargas de modelos.

---

## 📦 Features

Cada feature se detalla (archivos, firmas y pruebas) al aprobarse 5.8.

### FEATURE 6.1: Contratos de predicción v3 en `voc-common`

**Objetivo:** reemplazar los contratos de predicción de EPIC-1 por los que fije 5.8.

* `AnalyzedReviewPrediction` con el modelo elegido, versión de modelo y de corrida, familias multi-etiqueta, marcas `u` y `s`, y estado de elegibilidad con su código.
* Quitar `priority_weight_score` y `tnss_numeric_calibrated` (5.6). Retirar o versionar `ABSATopic`, `MIN_REVIEW_WORDS`/`MAX_REVIEW_WORDS` y `cumple_umbral_palabras`; revisar `IncidentAlertMessage` y `HitlTriageAuditRecord`, que hoy usan `ABSATopic`.
* Contratos de las curadurías (6.2) y del registro de corridas.
* **Dos políticas versionadas y de solo inserción:** el **apetito de riesgo HITL** (`RiskPolicy`, tabla `risk_policy`), **global**, con las subidas temporales por banco en `hitl_boosts`; y la **configuración de alertas de deriva** (`DriftPolicy`, tabla `drift_policy`), **por banco**, creada desde `drift_policy_template`. Los parámetros HITL son: versión de modelo y de calibración (T), señal (`prob_max`), cobertura objetivo, umbral equivalente, fecha de vigencia, quién la fijó (hash) y motivo. Y **curva de cobertura y riesgo** (`HitlCoverageCurve`) por versión de modelo: puntos de cobertura, riesgo con su IC, umbral, errores atrapados, revisiones por semana y minutos estimados. El valor por defecto es el de 5.6 (90 %) y reemplaza a `hitl_entropy_threshold` de `Settings`.
* Contrato documentado en `docs/contracts/`.
* **Terminado cuando:** contratos con pruebas, cobertura ≥ 85 % y consumidores actualizados; EPIC-1 anota qué contratos quedaron reemplazados.

### FEATURE 6.2: Infraestructura de salidas y curadurías (Pulumi)

**Objetivo:** aprovisionar en `infra/` las tablas y los recursos que necesita la inferencia.

* Tablas de salida que reemplazan `delora_predictions`, con un plan de migración (la tabla está vacía).
* Base de curadurías para el reentrenamiento. Punto de partida: el [borrador de tablas de 5.5](../analytics/topics/topics_decision_note.md#borrador-del-modelo-de-datos-de-curaduría) (`curation_sentiment` o ampliar `hitl_triage_audit_log`, `curation_aspects`, `topic_model_versions`, `topic_catalog`, `curation_topics`, `topic_assignments`). Principios: registros inmutables (solo inserción); revisor como hash SHA-256; cada registro guarda la versión de la guía, del modelo y del prompt que produjo la predicción revisada; solo texto sanitizado.
* Tablas `risk_policy` (global), `hitl_boosts`, `drift_policy` y `drift_policy_template` (por banco) y `hitl_coverage_curves` y `hitl_coverage_curves` (una curva por versión de modelo y de calibración), en BigQuery y de solo inserción, con los contratos de 6.1. Las lee la inferencia (6.3) y la API de EPIC-7.
* Cloud Run Job de inferencia y su Scheduler, IAM de `voc-sa-ml-backend` (Vertex AI si 5.8 elige M9) y el registro de versiones de modelo que proponga 5.7.
* **Terminado cuando:** `pulumi preview` con mocks pasa, EPIC-2 anota qué recursos quedaron reemplazados y la matriz FMEA tiene su fila si se almacena texto.

### FEATURE 6.3: Servicio de inferencia batch

**Objetivo:** el paquete desplegable que antes describía la fase 3 de EPIC-5.

* Backfill único y delta diario sobre `sanitized_reviews_tds`, con las reglas de elegibilidad aprobadas en 5.8.
* Sentimiento con el modelo elegido y su calibración. La marca `requires_hitl` sale de la política HITL vigente (6.2), y cada predicción guarda la versión de política con la que se marcó, familias `aspects_v2_1` y asignación de tópicos con versión.
* Persistencia por `MERGE` en las tablas de 6.2 y alertas `IncidentAlertMessage` por familia y marca `u`.
* **Terminado cuando:** el backfill cabe en el tiempo y costo medidos en 5.7, el delta corre en el Job programado y los *quality gates* pasan sin red.

### FEATURE 6.4: Monitoreo y ciclo de vida

**Objetivo:** el plan de monitoreo y de ciclo de vida de 5.7, en producción.

* Monitor de *drift*: entrada (longitud, vocabulario, `version_app`, proporción de no predecibles), predicción (proporción de `NEG` por banco y versión) y familias con la marca `u`, con los umbrales y la regla de entrada de la `drift_policy` de cada banco (plantilla de 5.7: z ≥ 4, PSI ≥ 0.25, 12 meses con 200 filas). Publica en `voc-incident-alerts-topic`. La especificación anterior está en el [anexo, A.7](#a7-monitor-de-drift-antes-tarea-651-del-portal).
* Regla de promoción y rollback de modelos, y política de *re-scoring* del histórico.
* **Al promover o recalibrar un modelo,** se recalcula la curva de cobertura y riesgo sobre el oro *dev* (como `voc_analytics.calibration.selective`), se guarda en `hitl_coverage_curves` y se propone el umbral equivalente a la cobertura vigente. El volumen semanal y los minutos estimados se actualizan con el volumen real y el tiempo medido por revisión en las curadurías.
* Una alerta de deriva sube temporalmente la revisión HITL **solo del banco que alertó** (P7-6): se registra en `hitl_boosts` con las reglas de `risk_policy` (cobertura, duración y tope), nunca como un cambio silencioso.
* Re-ajuste trimestral de tópicos con emparejamiento de identificadores entre versiones.
* **Desempeño de M4 y reentrenamiento (P7-10):** el κ de M4 en la muestra humana trimestral (`monitor_sample`, 300 revisiones) se guarda en `model_quality`; si queda debajo de 0.89, se pide reentrenar (candidato en Kaggle, registro en Vertex, promoción con la regla de 5.4). Dos avisos semanales que no disparan solos: la tasa de corrección de la cola HITL (> 28 % en 4 semanas) y el acuerdo M4–Gemini sobre 500 textos por semana (< 94 % en 4 semanas; ~$0.02 por semana).
* **Calidad de las familias (P7-11):** al cambiar el modelo o el prompt de Gemini se repite el prompt sobre las 300 reseñas de `muestra_v21` (~$0.03) y el cambio se acepta solo si el acuerdo exacto es ≥ 53 % y ninguna familia con prevalencia ≥ 5 % baja del límite inferior de su IC.
* **Depende de 5.9:** los umbrales de la señal y de las alertas salen de la lista de incidentes validada (P9-1).
* **Terminado cuando:** las alertas llegan al tópico con los umbrales de 5.9, `model_quality` registra cada medición de P7-10 y P7-11, y el portal de EPIC-7 puede consultarlas.

---

## ✅ Checklist de Aceptación de la Épica 6

* [ ] Contratos de predicción, elegibilidad y curaduría v3 en `voc-common`, con su documento en `docs/contracts/` (6.1).
* [ ] Tablas de salida y de curaduría, Job de inferencia e IAM aprovisionados con Pulumi; `delora_predictions` migrada o retirada (6.2).
* [ ] Backfill del corpus y delta diario en operación, dentro del costo medido en 5.7 (6.3).
* [ ] Política HITL y curva de cobertura y riesgo versionadas en BigQuery; la inferencia marca con la política vigente (6.1 a 6.3).
* [ ] Monitor de *drift*, promoción y rollback, recálculo de la curva al promover un modelo y *re-scoring* documentados y probados (6.4).
* [ ] *Quality gates* del monorepo (`ruff`, `pyrefly`, `bandit`, `pytest` con cobertura ≥ 85 %) sin errores.

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
