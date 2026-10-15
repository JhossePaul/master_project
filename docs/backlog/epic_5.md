# EPIC-5: Core Analítico NLP: Baseline RoBERTa, Arquitectura Dual LoRA (*Delora*), ABSA e Inferencia Idempotente

* **Estado:** Pendiente. Especificación sincronizada con contratos v2 (`EPIC-1`), esquemas BigQuery/IAM (`EPIC-2`) y cobertura TDS (`EPIC-4`).
* **Semanas Objetivo:** Semanas 4 - 6
* **Dependencias:** `EPIC-1` (`AnalyzedReviewPrediction`, `IncidentAlertMessage`, `ABSATopic`, `SentimentLabel`), `EPIC-2` (Tabla `delora_predictions`, tópico `voc-incident-alerts-topic`, cuenta `voc-sa-ml-backend`) y `EPIC-4` (Registros curados en `bbva_voc_tds.sanitized_reviews_tds`).
* **Directorios y Archivos Afectados:**
  * `services/ml-delora/pyproject.toml`
  * `services/ml-delora/Dockerfile`
  * `services/ml-delora/src/ml_delora/__init__.py`
  * `services/ml-delora/src/ml_delora/baseline_roberta.py`
  * `services/ml-delora/src/ml_delora/model.py`
  * `services/ml-delora/src/ml_delora/absa_classifier.py`
  * `services/ml-delora/src/ml_delora/scoring_and_entropy.py`
  * `services/ml-delora/src/ml_delora/train.py`
  * `services/ml-delora/src/ml_delora/evaluate.py`
  * `services/ml-delora/src/ml_delora/inference_pipeline.py`
  * `services/ml-delora/tests/__init__.py`
  * `services/ml-delora/tests/test_model_and_scoring.py`
  * `services/ml-delora/tests/test_absa_and_dialect.py`
  * `services/ml-delora/tests/test_inference_and_alerts.py`

---

## 🎯 Objetivo y Límites de la Garantía

Consumir las reseñas curadas y desidentificadas desde `bbva_voc_tds.sanitized_reviews_tds` (`texto_limpio`, `estrellas`, `votos_utilidad`, `version_app`), ejecutar el modelo baseline (**RoBERTa** en español), aplicar la arquitectura **Dual LoRA (*Delora*)** para desacoplar el *Label Noise Bias* (*Obligatory 5-Star*) y obtener el **True Net Satisfaction Score (TNSS)**, clasificar la categoría de fallo operativo (**ABSA**), generar *embeddings* densos de **768 dimensiones**, persistir de forma idempotente en `bbva_voc_tds.delora_predictions` y emitir alertas hacia `voc-incident-alerts-topic` cuando se detecten picos de quejas con alta tracción comunitaria.

* **Límite de inferencia y generalización:** La separación entre la rama *Clean* (`θ + Δθ_c`) y la rama *Noisy* (`Δθ_n` condicionada a `estrellas`) reduce la contaminación por etiquetas ruidosas, pero no certifica verdad absoluta sobre la intención subjetiva del usuario. Por ello, las predicciones con entropía normalizada `prediction_entropy >= hitl_entropy_threshold` (`0.65`) o alta severidad activan obligatoriamente `requires_hitl = True` para validación humana en `EPIC-6`.
* **No re-inspeccionar ni alterar tokens DLP:** El modelo recibe `texto_limpio` junto con los tokens semánticos entre corchetes (`[PERSON_NAME]`, `[MX_CLABE_BANCARIA]`, `[BBVA_ACCOUNT_NUMBER]`, etc.) y códigos técnicos conservados (`ref: 3702:65c5:9xhchi`). El tokenizador debe tratar dichos tokens como vocabulario válido sin eliminarlos, ya que aportan contexto semántico directo para tópicos como `BLOQUEO_SEGURIDAD_3702` o `TRANSFERENCIAS_SPEI`.

---

## 🔗 Alineación Estricta con Contratos e Infraestructura Existente (EPIC-1, EPIC-2 y EPIC-4)

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

---

## 📦 Desglose de Features e Historias Técnicas

### FEATURE 5.1: Configuración del Paquete `ml-delora` y Baseline RoBERTa (`baseline_roberta.py`)

**Objetivo:** Configurar el paquete dentro del workspace de `uv` (usando ruedas de PyTorch CPU ligeras en CI/Docker para no exceder límites de imagen ni memoria en Cloud Run) e implementar el evaluador base con RoBERTa en español (`pysentimiento` / `robertuito-sentiment-analysis`) validado en el notebook del EDA.

#### Tarea 5.1.1: Configurar `services/ml-delora/pyproject.toml`

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

#### Tarea 5.1.2: Implementar `BaselineRobertaEvaluator` en `baseline_roberta.py`

1. **Modelo Base Fundacional:**

* Utilizar el checkpoint en español `pysentimiento/robertuito-sentiment-analysis` (basado en RoBERTa con dimensión oculta $d = 768$) a través de `AutoTokenizer` y `AutoModelForSequenceClassification` de `transformers`.
* Soportar carga desde caché local o ruta en Cloud Storage (`gs://voc-datalake-{project_id}/ml_artifacts/roberta_base/`) y permitir inyección de un modelo/tokenizador *mock* ligero para pruebas unitarias en CI sin descargas de red.

1. **Inferencia en Batch y Extracción de Embeddings (768-d):**

* Implementar `predict_batch(self, texts: list[str], batch_size: int = 32) -> list[BaselineOutput]`:
* Devuelve para cada `texto_limpio`:
* `label: SentimentLabel` (`NEG`, `NEU`, `POS`).
* `probabilities: tuple[float, float, float]` ($P(\text{NEG}), P(\text{NEU}), P(\text{POS})$ tras `softmax`).
* `pooled_embedding: list[float]` (Vector normalizado $L_2$ de **768 dimensiones** extraído del estado oculto del token `<s>` / mean pooling de la última capa, listo para almacenarse en `embedding_vector`).

---

### FEATURE 5.2: Arquitectura Dual LoRA (*Delora*) para Desacoplamiento de Ruido y Cálculo de TNSS (`model.py`, `scoring_and_entropy.py`)

**Objetivo:** Implementar la arquitectura matemática **Dual LoRA (*Delora*)** en PyTorch para separar la polaridad semántica real (**TNSS**) del sesgo conductual de calificación por estrellas (*Label Noise Bias*), junto con las funciones puras de calibración numérica, entropía de Shannon y ponderación de severidad.

#### Tarea 5.2.1: Implementar `DeloraDualAdapterModel(nn.Module)` en `model.py`

1. **Estructura de Doble Rama sobre el Encoder Base ($d = 768$):**

* **Rama Limpia (*Clean Adapter* — $\Delta\theta_{\text{clean}}$):** Adaptador LoRA ($r=8, \alpha=16$, aplicado sobre proyecciones `query` y `value`) conectado al cabezal de clasificación limpio $W_{\text{clean}} \in \mathbb{R}^{768 \times 3}$. Esta rama recibe **únicamente el texto** (`input_ids`, `attention_mask`) y produce los logits depurados $z_{\text{clean}} = (z_{\text{NEG}}, z_{\text{NEU}}, z_{\text{POS}})$ que determinan el **`tnss_score`** (`SentimentLabel`).
* **Rama de Ruido (*Noisy Adapter / Transition Matrix* — $\Delta\theta_{\text{noisy}}$):** Segundo adaptador LoRA + módulo de transición condicional $T(h, y_{\text{stars}})$ que recibe la representación oculta $h$ y el embedding de `estrellas` ($1..5$) durante el entrenamiento para absorber la discrepancia sistemática donde textos con quejas operativas fueron etiquetados con 4 o 5 estrellas (*Obligatory 5-Star*).
* **Desacoplamiento en Tiempo de Inferencia (`forward_clean_inference`):** Durante la inferencia en producción para calcular el **TNSS**, se desactiva la rama de ruido ($\Delta\theta_{\text{noisy}}$) y se evalúa exclusivamente la rama limpia ($\theta_0 + \Delta\theta_{\text{clean}}$), aislando el sentimiento real del texto sin contaminación de la calificación inercial.

#### Tarea 5.2.2: Implementar Fórmulas de Calibración, Entropía y Priorización en `scoring_and_entropy.py`

Implementar funciones matemáticas puras, deterministas y 100% testeables sin GPU:

1. **Score Continuo Recalibrado (`compute_tnss_numeric_calibrated`):**

* Dadas las probabilidades limpias $p = (p_{\text{NEG}}, p_{\text{NEU}}, p_{\text{POS}})$ donde $\sum p_i = 1$:

$$\text{tnss\_numeric\_calibrated} = \text{clip}\left(1.0 \cdot p_{\text{NEG}} + 3.0 \cdot p_{\text{NEU}} + 5.0 \cdot p_{\text{POS}},\, 1.0,\, 5.0\right)$$

* Permite calcular directamente el **Satisfaction Gap** ($\overline{\text{TNSS}}_{\text{calibrado}} - \overline{\text{Estrellas}}_{\text{oficial}}$) en escala de 1.0 a 5.0 para los dashboards de `EPIC-6`.

1. **Entropía Normalizada de Shannon y Disparo HITL (`compute_entropy_and_hitl_flag`):**

* Calcula la entropía sobre la distribución de probabilidad limpia $p \in \Delta^2$ normalizada por $\ln(3)$ para que viva estrictamente en el intervalo $[0.0, 1.0]$ requerido por `AnalyzedReviewPrediction`:

$$H_{\text{norm}}(p) = -\frac{1}{\ln(3)} \sum_{c \in \{\text{NEG, NEU, POS}\}} p_c \ln(\max(p_c, 10^{-12}))$$

* Determina `requires_hitl: bool`:
* Retorna `True` si `prediction_entropy >= hitl_entropy_threshold` (`0.65` por defecto en `Settings`), **o** si `is_obligatory_5_star_bias is True and votos_utilidad >= 5`, asegurando que tanto las predicciones inciertas como las quejas graves ocultas en 5 estrellas con tracción comunitaria pasen a validación humana.

1. **Ponderador de Severidad para el Backlog (`compute_priority_weight_score`):**

* Basado en el hallazgo del gráfico de violín del EDA (donde las reseñas negativas concentran picos de hasta ~100 votos de utilidad, validando tracción comunitaria):

$$\text{priority\_weight\_score} = \text{round}\left( \left(p_{\text{NEG}} + 0.5 \cdot \mathbb{I}[\text{is\_obligatory\_5\_star\_bias}]\right) \cdot \left(1.0 + \ln(1 + \text{votos\_utilidad})\right),\, 4 \right)$$

* Si `tnss_score == SentimentLabel.POS`, el multiplicador de severidad se atenúa por $(1 - p_{\text{POS}})$ para no inflar el backlog de ingeniería con comentarios positivos.

---

### FEATURE 5.3: Clasificador por Aspectos (ABSA) Híbrido para Dominio Bancario (`absa_classifier.py`)

**Objetivo:** Asignar cada reseña a uno de los 8 tópicos de `ABSATopic` (`voc-common`) combinando reglas léxicas de alta precisión para códigos/fallos bancarios explícitos con clasificación basada en similitud de embeddings / cabezal neuronal.

#### Tarea 5.3.1: Implementar `BankingABSAClassifier` en `absa_classifier.py`

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

---

### FEATURE 5.4: Entrenamiento, Evaluación EDD y Paridad Dialectal (`train.py`, `evaluate.py`)

**Objetivo:** Proveer los scripts de entrenamiento de los adaptadores Dual LoRA y la suite de **Eval-Driven Development (EDD)** que audita los KPIs técnicos exigidos por la gobernanza de modelos de BBVA: *Negative Recall*, *Eficacia de Desacoplamiento de Ruido* y *Paridad Dialectal* en español mexicano.

#### Tarea 5.4.1: Implementar `train.py` y Gestión de Artefactos en GCS

* Permitir entrenar los adaptadores `clean_adapter` y `noisy_adapter` a partir de un dataset en formato Parquet/JSONL o tabla de BigQuery (`sanitized_reviews_tds`), utilizando una función de pérdida conjunta con regularización de separación para que el adaptador limpio maximice la coherencia semántica con el texto mientras el adaptador ruidoso absorbe la transición hacia `estrellas`.
* Guardar y cargar los pesos de los adaptadores en `gs://voc-datalake-{project_id}/ml_artifacts/delora_v1/`.

#### Tarea 5.4.2: Implementar `evaluate.py` con las 3 Métricas de Gobernanza (KPIs)

Implementar la función `evaluate_delora_governance_metrics(...) -> GovernanceEvaluationReport`:

1. **`negative_recall` ($\ge 0.85$ objetivo):** Recall de la clase `SentimentLabel.NEG` sobre el conjunto de evaluación curado, asegurando mínima omisión de quejas legítimas.
2. **`noise_decoupling_efficacy`:** Porcentaje de reseñas en el subconjunto ruidoso (*Obligatory 5-Star*: texto comprobadamente negativo pero con `estrellas` $\in \{4, 5\}$) donde `tnss_score` predice correctamente `SentimentLabel.NEG` en contraste con un clasificador condicionado a las estrellas.
3. **`dialect_parity_gap` (*Ethics by Design — Paridad Dialectal*):**

* Evalúa la diferencia absoluta de *Negative Recall* y *F1-Score* entre reseñas en **español estándar** (ej. `"la aplicación no funciona correctamente y presenta errores"`) y reseñas equivalentes con **modismos regionales mexicanos** reales presentes en el corpus del EDA (ej. `"no jala"`, `"se traba bien feo"`, `"chafa"`, `"un batallar"`, `"no pasa de ahí"`, `"a lo menso"`).
* Verifica que la brecha de precisión $\vert{}\text{Recall}_{\text{estándar}} - \text{Recall}_{\text{modismos\_mx}}\vert{} \le 0.05$ (degradación menor al 5%).

---

### FEATURE 5.5: Pipeline de Inferencia Incremental hacia BigQuery y Motor de Alertas Pub/Sub (`inference_pipeline.py`, `Dockerfile`)

**Objetivo:** Ejecutar la inferencia por lotes sobre las reseñas nuevas en `sanitized_reviews_tds`, persistir las 15 columnas en `delora_predictions` mediante `MERGE` y emitir alertas `IncidentAlertMessage` hacia `voc-incident-alerts-topic` cuando se detecten anomalías operativas post-release.

#### Tarea 5.5.1: Implementar `DeloraBatchInferenceRunner` en `inference_pipeline.py`

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

#### Tarea 5.5.2: Implementar `services/ml-delora/Dockerfile`

Construir un `Dockerfile` multi-stage con `ghcr.io/astral-sh/uv:python3.11-bookworm-slim`, usuario no-root (`appuser`), instalando PyTorch CPU y el paquete `ml-delora` desde el workspace, con `ENTRYPOINT ["python", "-m", "ml_delora.inference_pipeline"]`.

---

### FEATURE 5.6: Suite de Pruebas Unitarias, Matemáticas y de Paridad Dialectal (`tests/`)

**Objetivo:** Verificar determinísticamente en CI (en menos de 10 segundos y sin descargar modelos pesados de HuggingFace ni conectarse a GCP) toda la arquitectura Dual LoRA, las ecuaciones de calibración/entropía/severidad, el clasificador ABSA y el disparo de alertas.

#### Tarea 5.6.1: Implementar `test_model_and_scoring.py`, `test_absa_and_dialect.py` y `test_inference_and_alerts.py`

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

---

## ✅ Checklist de Aceptación de la Épica 5

* [ ] Genera objetos `AnalyzedReviewPrediction` 100% compatibles con las 15 columnas de `bbva_voc_tds.delora_predictions` en BigQuery, incluyendo `embedding_vector` de 768 dimensiones.
* [ ] Aísla el sesgo *Obligatory 5-Star* (`is_obligatory_5_star_bias = True` cuando `estrellas >= 4` y `tnss_score == NEG`) y calcula el score continuo `tnss_numeric_calibrated` en escala `[1.0, 5.0]`.
* [ ] Clasifica los 8 tópicos de `ABSATopic` aprovechando tanto códigos preservados (`ref: 3702`) y tokens DLP (`[MX_CLABE_BANCARIA]`) como similitud semántica.
* [ ] Opera por defecto en modo batch incremental sobre BigQuery (`FILE_LOADS` + `MERGE` sin *Streaming Inserts*), respetando el modo *Free Tier* (`enable_dedicated_vertex_endpoints: false`).
* [ ] Emite alertas `IncidentAlertMessage` hacia `voc-incident-alerts-topic` sin exponer PII ni texto crudo.
* [ ] Los comandos `uv run ruff check services/ml-delora`, `uv run ruff format --check services/ml-delora`, `uv run pyrefly check`, `uv run bandit -c pyproject.toml -r services/ml-delora` y `uv run pytest services/ml-delora/tests --cov=services/ml-delora/src --cov-fail-under=85` pasan con **0 errores**.
