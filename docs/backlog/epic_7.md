# EPIC-7: Exposición (FastAPI), Búsqueda Vectorial, Explicabilidad (SHAP/LIME), Portal Web HITL y Gobernanza MLOps

* **Estado:** Pendiente. Era EPIC-6 hasta la reorganización del backlog (2026-10-22): sus features pasaron de 6.x a 7.x. El monitor de *drift* (antes tarea 6.5.1) y la base de curadurías (antes 6.7.2) pasaron a [EPIC-6](epic_6.md), que despliega el core analítico. El texto original asume las predicciones Dual LoRA de EPIC-5; donde la evidencia de EPIC-5 lo contradice rige la tabla de [decisiones heredadas](#-decisiones-heredadas-de-55-2026-10-22).
* **Semanas Objetivo:** tras EPIC-6.
* **Dependencias:** `EPIC-1` (`HitlTriageAuditRecord`, `AnalyzedReviewPrediction`, `IncidentAlertMessage`), `EPIC-2` (`voc-api-backend`, `voc-sa-ml-backend`, tabla `hitl_triage_audit_log`), `EPIC-4` (`sanitized_reviews_tds`) y `EPIC-6` (tablas de salida que reemplazan `delora_predictions`, base de curadurías y alertas de *drift*).
* **Directorios y Archivos Afectados:**
  * `services/api-backend/pyproject.toml`
  * `services/api-backend/Dockerfile`
  * `services/api-backend/src/api_backend/__init__.py`
  * `services/api-backend/src/api_backend/main.py`
  * `services/api-backend/src/api_backend/routes.py`
  * `services/api-backend/src/api_backend/bq_Vector_and_analytics.py`
  * `services/api-backend/src/api_backend/explainability.py`
  * `services/api-backend/src/api_backend/hitl_service.py`
  * `services/api-backend/tests/__init__.py`
  * `services/api-backend/tests/test_api_routes.py`
  * `services/api-backend/tests/test_explainability_and_hitl.py`
  * `web/hitl-portal/package.json`
  * `web/hitl-portal/vite.config.ts`
  * `web/hitl-portal/Dockerfile`
  * `web/hitl-portal/src/App.tsx`
  * `web/hitl-portal/src/api/client.ts`
  * `web/hitl-portal/src/components/SatisfactionGapDashboard.tsx`
  * `web/hitl-portal/src/components/VectorRootCauseExplorer.tsx`
  * `web/hitl-portal/src/components/HitlTriageQueue.tsx`
  * `docs/governance/data_card.md`
  * `docs/governance/model_card.md`
  * `docs/governance/ethical_fmea_matrix.md`

---

## 🎯 Objetivo y Límites de la Garantía

Construir la capa de consumo analítico, explicabilidad e intervención humana (**HITL**) que permite a los equipos de *Client Solutions*, *Customer Experience (CX)*, *Program Managers* y *Product Owners* explorar la brecha de satisfacción real (**Satisfaction Gap**: Rating Oficial vs. **TNSS**), buscar causas raíz semánticamente mediante *embeddings* de 768 dimensiones, inspeccionar mapas de atribución de tokens (**SHAP / LIME**), auditar y reclasificar predicciones de alta entropía hacia el backlog de ingeniería, mostrar las alertas de *drift* que emite EPIC-6, y entregar la documentación normativa alineada a los estándares de BBVA *Norma Data Governance* y *Norma de Gobierno de Modelos de Analítica Avanzada*.

* **Límite de Explicabilidad Local:** Los valores de atribución por token (SHAP/LIME/oclusión de perturbación) explican qué palabras o tokens DLP (`ref: 3702`, `[MX_CLABE_BANCARIA]`, `"pantalla azul"`) empujaron la predicción local del modelo hacia `NEG` o hacia un `ABSATopic` específico, pero no constituyen prueba de causalidad técnica en el código fuente móvil el cual debe correlacionarse con telemetría APM en sistemas de ingeniería.
* **Agencia Humana (HITL):** Ninguna predicción con `requires_hitl = True` (`prediction_entropy >= 0.65` o sesgo *Obligatory 5-Star* de alto impacto) modifica automáticamente prioridades definitivas sin registrar un `HitlTriageAuditRecord` firmado por un revisor humano autenticado (almacenando únicamente `reviewer_email_hash` SHA-256 para cumplir con minimización de PII).

---

## 🔗 Alineación Estricta con Contratos e Infraestructura Existente (EPIC-1 a EPIC-6)

El Agente IA **DEBE** acatar las siguientes 5 reglas de integración con lo ya construido en el monorepo:

1. **Inmutabilidad del Historial del Modelo vs. Bitácora HITL (`hitl_triage_audit_log`):**
   * En `EPIC-2` (Feature 2.4.2), se aprovisionaron dos tablas separadas en el dataset `bbva_voc_tds`: `delora_predictions` (15 columnas) y `hitl_triage_audit_log` (10 columnas: `audit_id`, `id_resena`, `bank_id`, `original_tnss`, `validated_tnss`, `original_topic`, `validated_topic`, `reviewer_email_hash`, `backlog_jira_ticket`, `reviewed_at`).
   * Cuando un Product Owner o líder de CX aprueba o corrige una predicción en el portal HITL, el backend **NO** sobrescribe destructivamente `original_tnss` ni `original_topic`: inserta un registro inmutable `HitlTriageAuditRecord` en `hitl_triage_audit_log`. Las consultas analíticas del backend hacen un `LEFT JOIN` con la última decisión de `hitl_triage_audit_log` (`COALESCE(h.validated_tnss, p.tnss_score)`) para reflejar la verdad validada por humanos preservando la trazabilidad para auditoría de QA y recálculo de desempeño del modelo.
2. **Búsqueda Vectorial Dual (BigQuery Cosine Distance en Free Tier vs. Vertex AI Vector Search):**
   * En `EPIC-2` (Feature 2.5.3), `enable_dedicated_vertex_endpoints` es `False` por defecto.
   * Si `settings.enable_dedicated_vertex_endpoints` es `False`, el motor de búsqueda semántica ejecuta el cálculo de distancia coseno directamente en **BigQuery** sobre la columna `embedding_vector` (`ARRAY<FLOAT64>` de 768 dimensiones en `delora_predictions`) unida con `sanitized_reviews_tds`, logrando latencias sub-segundo sobre decenas de miles de reseñas a **$0.00 USD de costo fijo en reposo**. Si el flag es `True`, delega la consulta de vecinos más cercanos al `AiEndpoint` / `AiIndex` de Vertex AI.
3. **Cero Exposición de PII en la API y en el Portal Web:**
   * La API en FastAPI (`voc-api-backend`) lee exclusivamente de `sanitized_reviews_tds`, `delora_predictions`, `hitl_triage_audit_log` e `ingestion_runs_log_v2`. Jamás accede a `raw_staging/` ni expone `usuario` o correos de revisores sin hashear (`hash_username_pii` de `voc-common`).
4. **Explicabilidad Ligera Compatible con Cloud Run (`1 vCPU / 1 GiB RAM`):**
   * En `EPIC-2` (Feature 2.5.1), `voc-api-backend` tiene límites de `cpu="1"` y `memory="1Gi"`. Ejecutar miles de permutaciones pesadas de KernelSHAP sobre un modelo Transformer completo por cada petición HTTP agotaría la RAM o el timeout.
   * Por tanto, `explainability.py` debe implementar un **Explicador de Atribución por Oclusión/Perturbación Léxica Rápida (LIME / Leave-One-Out Token Attribution)** que evalúa la caída/subida marginal de probabilidad $\Delta P(\text{NEG})$ y $\Delta P(\text{topico})$ al enmascarar cada token o sintagma clave de `texto_limpio`, devolviendo pesos normalizados en $< 150\text{ ms}$ y garantizando contraste de "negativos pertinentes" qué palabras habrían cambiado la predicción si no estuvieran presentes.
5. **Alertas de *drift*:** el monitor (`drift_monitor.py`) se construye en [EPIC-6](epic_6.md) (feature 6.4) y publica en `voc-incident-alerts-topic`; esta épica solo las consulta y muestra.

---

## 🧭 Decisiones heredadas de 5.5 (2026-10-22)

El autor aprobó la recomendación híbrida de 5.5 ([nota de decisión](../analytics/topics/topics_decision_note.md)). Donde el texto original de esta épica la contradice, se conserva para trazabilidad y rige lo siguiente:

| Texto original de EPIC-7 | Decisión heredada de 5.5 | Se fija en |
| :--- | :--- | :--- |
| Taxonomía de los 8 `ABSATopic` (ranking de backlog, `predicted_topic`, `validated_topic`, filtros) | Núcleo: las 11 familias multi-etiqueta de `aspects_v2_1` más las marcas `u` y `s`; una reseña puede tener varias familias. Los tópicos de BERTopic son una capa de detalle aparte, con versión y curada. | 7.1 a 7.4 al implementarlas; contratos de `voc_common` en EPIC-6 (6.1) |
| `embedding_vector` de 768 dimensiones del modelo Delora (búsqueda semántica) | 5.4 descartó Delora (M8); los tópicos usan MiniLM (384 dimensiones). La búsqueda semántica debe decidir su encoder. | 5.7 o 5.8; columna en EPIC-6 (6.2) |
| *Concept drift* con JSD de la distribución de los 8 tópicos por versión | Proporción de las familias y de la marca `u`, que se adelantó a los incidentes de BBVA. | Umbrales en 5.7; monitor en EPIC-6 (6.4) |
| Umbral HITL `prediction_entropy >= 0.65` fijado a priori | Lo fija 5.6 con la curva cobertura–riesgo en el oro *dev*. | 5.6 |

---

## 📦 Desglose de Features e Historias Técnicas

### FEATURE 7.1: Configuración del Paquete `api-backend` y Servicio Analítico/Vectorial en BigQuery (`bq_vector_and_analytics.py`)

**Objetivo:** Configurar el microservicio FastAPI dentro del workspace de `uv` e implementar las consultas parametrizadas a BigQuery para KPIs ejecutivos (*Satisfaction Gap*, evolución por versión y comparación competitiva frente a Nubank, Santander, Azteca y Banorte) y búsqueda semántica de causa raíz.

#### Tarea 7.1.1: Configurar `services/api-backend/pyproject.toml`

Escribir `services/api-backend/pyproject.toml`:

```toml
[project]
name = "api-backend"
version = "0.1.0"
description = "API RESTful FastAPI para Consumo de Predicciones TNSS, Busqueda Vectorial, Explicabilidad SHAP/LIME y Triaje HITL"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110.0,<1.0.0",
    "uvicorn[standard]>=0.28.0,<1.0.0",
    "google-cloud-bigquery>=3.20.0,<4.0.0",
    "google-cloud-pubsub>=2.21.0,<3.0.0",
    "numpy>=1.26.0,<3.0.0",
    "pydantic>=2.6.0,<3.0.0",
    "voc-common",
]

[tool.uv.sources]
voc-common = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

```

#### Tarea 7.1.2: Implementar Consultas de KPIs y Búsqueda Semántica en `bq_vector_and_analytics.py`

Crear la clase `VocAnalyticsAndVectorRepository`:

1. **`get_satisfaction_gap_kpis(self, bank_id: BankKey = BankKey.BBVA, days_window: int = 30) -> SatisfactionGapReport`**:

* Calcula sobre la unión de `sanitized_reviews_tds` (`s`), `delora_predictions` (`p`) y la última validación humana en `hitl_triage_audit_log` (`h`):
* `official_avg_stars: float` ($\overline{\text{estrellas}}$ reportado en tienda).

* `recalibrated_tnss_avg: float` ($\overline{\text{tnss\_numeric\_calibrated}}$).

* `satisfaction_gap: float` (`recalibrated_tnss_avg - official_avg_stars`, ej. `-1.11` pts).

* `obligatory_5_star_ratio: float` (Porcentaje de reseñas de 4 y 5 estrellas con sentimiento real `NEG`).

* `competitor_benchmark: list[BankBenchmarkItem]` (Comparativa lado a lado de `BBVA`, `NUBANK`, `SANTANDER`, `AZTECA`, `BANORTE`).

1. **`get_version_concept_drift_series(self, bank_id: BankKey = BankKey.BBVA, top_n_versions: int = 8) -> list[VersionTimeseriesPoint]`**:

* Devuelve la serie temporal diaria de quejas negativas fragmentada por `version_app` (replicando y automatizando la gráfica *"Volumen reviews negativos por Versión de App (Top 8)"* del EDA para detectar migración de quejas tras un release como `26.90.12`).

1. **`get_prioritized_backlog_topics(self, bank_id: BankKey = BankKey.BBVA, version_app: str | None = None) -> list[BacklogTopicSummary]`**:

* Agrupa por `ABSATopic` ordenando descendentemente por `SUM(priority_weight_score)` y `SUM(votos_utilidad)`, entregando a los Product Owners el ranking objetivo de severidad transaccional.

1. **`semantic_vector_search(self, query_embedding: list[float], bank_id: BankKey | None = None, topico: ABSATopic | None = None, top_k: int = 20) -> list[SemanticSearchHit]`**:

* Valida que `len(query_embedding) == 768`.

* Ejecuta en BigQuery el cálculo de similitud coseno entre `@query_embedding` y `p.embedding_vector` (filtrando por `bank_id` y `topico` si se especifican), devolviendo las `top_k` reseñas sanitizadas (`texto_sanitizado`, `version_app`, `estrellas`, `tnss_score`, `votos_utilidad`, `cosine_similarity`) para exploración de causa raíz.

---

### FEATURE 7.2: Motor de Explicabilidad Local (SHAP / LIME Token Attribution) y Servicio HITL (`explainability.py`, `hitl_service.py`)

**Objetivo:** Dotar a los analistas de CX y Product Owners de mapas de atribución de palabras sobre cualquier reseña individual y gestionar la bandeja de validación humana HITL con persistencia auditada en `bbva_voc_tds.hitl_triage_audit_log`.

#### Tarea 7.2.1: Implementar `LocalTokenAttributionExplainer` en `explainability.py`

Definir los modelos de respuesta:

```python
class TokenAttributionItem(BaseModel):
    token: str
    position: int
    attribution_weight: float = Field(..., ge=-1.0, le=1.0)
    direction: Literal["TOWARDS_NEG_INCIDENT", "TOWARDS_POS_SATISFACTION", "NEUTRAL"]
    is_pertinent_negative_trigger: bool

class ReviewExplanationResponse(BaseModel):
    id_resena: str
    bank_id: BankKey
    texto_limpio: str
    predicted_tnss: SentimentLabel
    predicted_topic: ABSATopic
    prediction_entropy: float
    token_attributions: list[TokenAttributionItem]
    top_incident_drivers: list[str]

```

* **Algoritmo de atribución local (LIME / Leave-One-Out Perturbation):**
* Dado el `texto_limpio` de una reseña (de 2 a 60 palabras según el umbral del EDA), genera las variantes perturbadas ocultando un token (o n-grama de dominio bancario como `ref: 3702`, `reconocimiento facial`, `pantalla azul`, `[MX_CLABE_BANCARIA]`) a la vez.

* Calcula el cambio marginal en el puntaje de negatividad/severidad $\Delta S_i = S(\text{texto completo}) - S(\text{texto sin token}_i)$ y normaliza los pesos al intervalo $[-1.0, 1.0]$.
* Identifica qué tokens son los detonantes críticos (*top incident drivers*) cuya ausencia cambiaría la clasificación (explicación contrastiva).

#### Tarea 7.2.2: Implementar `HitlTriageService` en `hitl_service.py`

1. **`list_pending_hitl_reviews(self, bank_id: BankKey | None = None, limit: int = 50) -> list[HitlQueueItem]`**:

* Consulta en BigQuery las reseñas donde `p.requires_hitl = TRUE` que aún **no** tengan un registro en `hitl_triage_audit_log`, ordenadas por `p.priority_weight_score DESC, p.prediction_entropy DESC`.

1. **`submit_human_validation(self, request: HitlDecisionRequest) -> HitlTriageAuditRecord`**:

* Recibe la decisión del usuario humano (`id_resena`, `bank_id`, `validated_tnss: SentimentLabel`, `validated_topic: ABSATopic`, `reviewer_email: str`, `backlog_jira_ticket: str | None`).
* Aplica inmediatamente `hash_username_pii(request.reviewer_email, settings.user_hash_salt)` de `voc-common` para obtener `reviewer_email_hash` (jamás guarda el email en texto plano en BigQuery).

* Construye y valida `HitlTriageAuditRecord` (EPIC-1 Feature 1.3.5) y lo persiste en `bbva_voc_tds.hitl_triage_audit_log`.

---

### FEATURE 7.3: Rutas RESTful en FastAPI y Contenedor Docker (`routes.py`, `main.py`, `Dockerfile`)

**Objetivo:** Exponer la API de alto rendimiento con validación estricta Pydantic, CORS configurado para la SPA en React y empaquetado Docker seguro.

#### Tarea 7.3.1: Implementar Endpoints en `routes.py` y `main.py`

Exponer bajo el prefijo `/api/v1`:

1. `GET /health`: Estado de salud del servicio `api-backend`.
2. `GET /api/v1/analytics/satisfaction-gap`: Devuelve `SatisfactionGapReport` (filtrable por `bank_id` y `days_window`).

3. `GET /api/v1/analytics/version-drift`: Devuelve la evolución temporal de quejas por `version_app`.

4. `GET /api/v1/analytics/backlog-ranking`: Devuelve el ranking de tópicos `ABSATopic` ponderado por severidad y votos de utilidad.

5. `POST /api/v1/search/semantic`: Recibe una consulta en lenguaje natural (`query_text: str`, `bank_id`, `topico`, `top_k`), genera su vector de 768 dimensiones y retorna los `SemanticSearchHit` más cercanos.

6. `GET /api/v1/reviews/{bank_id}/{id_resena}/explanation`: Devuelve `ReviewExplanationResponse` con el mapa de atribución de tokens SHAP/LIME.

7. `GET /api/v1/hitl/queue`: Lista las reseñas pendientes de validación humana (`requires_hitl = True`).

8. `POST /api/v1/hitl/validate`: Registra la decisión humana y devuelve el `HitlTriageAuditRecord` confirmado.

#### Tarea 7.3.2: Implementar `services/api-backend/Dockerfile`

Construir `Dockerfile` multi-stage con `ghcr.io/astral-sh/uv:python3.11-bookworm-slim`, usuario no-root `appuser`, instalando `voc-common` y `api-backend` desde `uv.lock`, exponiendo el puerto `8080` con `uvicorn api_backend.main:app --host 0.0.0.0 --port 8080`.

---

### FEATURE 7.4: Portal Interactivo React SPA para Triaje HITL (`web/hitl-portal/`)

**Objetivo:** Desarrollar la Single Page Application (React + TypeScript + Vite) utilizando la paleta institucional definida en el notebook del EDA (`Azul: #002D72`, `Verde: #215347`, `Vino: #7A1A37`, `Dorado: #B9975B`) para que los stakeholders naveguen por las incidencias y ejecuten el protocolo HITL.

#### Tarea 7.4.1: Implementar los 3 Módulos Visuales en `web/hitl-portal/src/`

1. **`SatisfactionGapDashboard.tsx`:**

* Tarjetas ejecutivas mostrando el Rating Oficial Inercial vs. **TNSS Recalibrado**, el *Satisfaction Gap*, el porcentaje de *Obligatory 5-Star* detectado, la comparativa frente a `NUBANK`, `SANTANDER`, `AZTECA` y `BANORTE`, y el gráfico apilado de quejas por `version_app`.

1. **`VectorRootCauseExplorer.tsx`:**

* Buscador semántico donde el Product Owner escribe una hipótesis de fallo (ej. *"bloqueo por antivirus o accesibilidad código 3702"*), visualiza las reseñas semánticamente más cercanas con sus votos de utilidad y, al hacer clic en una reseña, despliega el **Mapa de Calor de Atribución SHAP/LIME** resaltando en color Vino (`#7A1A37`) los tokens que impulsan la polaridad negativa y en Verde (`#215347`) los positivos.

1. **`HitlTriageQueue.tsx`:**

* Bandeja interactiva que muestra las reseñas con `requires_hitl = True` (alta entropía o alto impacto), permitiendo al revisor confirmar o reclasificar el `tnss_score` (`NEG`/`NEU`/`POS`) y el `ABSATopic`, vincular opcionalmente un ID de ticket de Jira/Backlog y enviar la validación hacia `POST /api/v1/hitl/validate`.

---

### FEATURE 7.5: Artefactos Normativos de Gobernanza (`docs/governance/`)

**Objetivo:** Redactar los 3 documentos normativos obligatorios para la auditoría de *Data Governance*, *QA Responsible* y *Compliance* de BBVA.

#### Tarea 7.5.1: Redactar los 3 Artefactos de Gobernanza en `docs/governance/`

Completar con rigor técnico y normativo:

1. **`docs/governance/data_card.md`** (Estándar Gebru et al. / Hutchinson et al. y Norma Data Governance BBVA Código N.º 0000010007):

* Documentar el origen público (Google Play Store México para los 5 bancos), clasificación como *Trusted Data Source (TDS)* en `bbva_voc_tds.sanitized_reviews_tds`, roles asignados (*Data Owner*, *Service Line Owner*), flujo End-to-End de sanitización PII (Cloud DLP NER + 3 detectores REGEX bancarios + regla de exclusión `ref: 3702` + anonimización SHA-256 de usuarios), recorte de colas pesadas (2 a 60 palabras) y análisis de desbalances dialectales.

1. **`docs/governance/model_card.md`** (Estándar Mitchell et al. y Norma de Gobierno de Modelos BBVA NCDATA0001_18):

* Especificar la arquitectura del modelo baseline (`pysentimiento/robertuito-sentiment-analysis`) y la arquitectura **Dual LoRA (*Delora*)** ($\Delta\theta_{\text{clean}}$ vs. $\Delta\theta_{\text{noisy}}$), definición matemática del **TNSS**, métricas auditables (*Negative Recall*, *Eficacia de Desacoplamiento de Ruido*, *Paridad Dialectal* en modismos mexicanos), umbrales de entropía para disparo de HITL (`0.65`) y limitaciones conocidas.

1. **`docs/governance/ethical_fmea_matrix.md`** (Matriz de Análisis de Modos y Efectos de Falla Ética alineada a NIST AI RMF 1.0 e INAI/LFPDPPP):

* Incluir tabla FMEA completa con Severidad ($S$), Ocurrencia ($O$), Detectabilidad ($D$), Número Prioritario de Riesgo ($RPN = S \times O \times D$) y Controles de Mitigación implementados en el monorepo para al menos 6 modos de falla críticos:

1. *Fuga inadvertida de PII bancario (CLABE/Cuenta/Nombre) en reseñas abiertas* $\rightarrow$ Mitigado por Cloud DLP + `LocalRegexFallbackSanitizer` *fail-closed* en `EPIC-4`.

2. *Sesgo de confirmación por Obligatory 5-Star (Label Noise Bias)* $\rightarrow$ Mitigado por desacoplamiento Dual LoRA en `EPIC-5`.

3. *Sesgo dialectal contra modismos regionales mexicanos* $\rightarrow$ Mitigado por pruebas de Paridad Dialectal en `evaluate.py`.

4. *Ocultamiento de códigos diagnósticos de ciberseguridad (`ref: 3702`) por sobre-enmascaramiento DLP* $\rightarrow$ Mitigado por `ExclusionRule` en `EPIC-2` y placeholder con nonce en `EPIC-4`.

5. *Priorización errónea del backlog en predicciones de alta incertidumbre* $\rightarrow$ Mitigado por umbral de entropía (`>= 0.65`) y protocolo obligatorio HITL en `EPIC-7`.

6. *Degradación silenciosa tras nueva actualización de la App (Concept Drift)* $\rightarrow$ Mitigado por `drift_monitor.py` (EPIC-6) y alertas Pub/Sub.

---

### FEATURE 7.6: Suite de Pruebas Unitarias de API, Explicabilidad y HITL (`tests/`)

**Objetivo:** Certificar con `pytest` y `fastapi.testclient.TestClient` (sin requerir conexión a GCP en CI) todos los endpoints del backend, el motor de atribución de tokens y la bitácora HITL. Las pruebas del monitor de *drift* están en EPIC-6.

#### Tarea 7.6.1: Implementar `test_api_routes.py` y `test_explainability_and_hitl.py`

Escribir pruebas deterministas que validen:

1. **`test_satisfaction_gap_and_competitor_benchmark_endpoint`**:

* Verificar que `GET /api/v1/analytics/satisfaction-gap` calcule correctamente el diferencial negativo entre el rating oficial (ej. `4.68`) y el TNSS recalibrado (ej. `3.57`, gap `-1.11`) y devuelva la comparativa de los 5 bancos de `BankKey`.

1. **`test_semantic_vector_search_validation_and_ranking`**:

* Comprobar que `POST /api/v1/search/semantic` valide dimensiones (`768`), filtre por `bank_id` y `ABSATopic`, y ordene los resultados por similitud coseno descendente.

1. **`test_token_attribution_explainer_identifies_incident_keywords`**:

* Pasar la reseña `"pésima actualización se traba la pantalla azul y marca error ref: 3702:65c5:9xhchi"` a `LocalTokenAttributionExplainer`. Verificar que los tokens `"pésima"`, `"traba"` y `"ref: 3702:65c5:9xhchi"` reciban los pesos de atribución más altos con dirección `"TOWARDS_NEG_INCIDENT"`.

1. **`test_hitl_validation_hashes_reviewer_email_and_creates_audit_record`**:

* Enviar una decisión humana a `POST /api/v1/hitl/validate` con `reviewer_email="claudia.martinez@bbva.com"`. Comprobar que el `HitlTriageAuditRecord` insertado en `hitl_triage_audit_log` contenga un `reviewer_email_hash` SHA-256 de 64 caracteres, nunca el email en texto plano, y que refleje el cambio de tópico/TNSS validado.

---

### FEATURE 7.7: Frontales de Curaduría HITL (agregado del autor, 2026-10-22)

**Decisión del autor:** todos los aplicativos de curaduría desarrollados en EPIC-5 (sentimiento y tópicos) pertenecen también al frontal de EPIC-7. La base de datos que guarda las curadurías para el reentrenamiento se diseña en [EPIC-6](epic_6.md) (feature 6.2). Insumo: sección final de la [nota de decisión](../analytics/topics/topics_decision_note.md).

#### Tarea 7.7.1: Frontales de curaduría en `web/hitl-portal/`

| Prototipo actual (local, EPIC-5) | Pantalla en el portal |
| :--- | :--- |
| `annotation/app.py` (Streamlit, 5.3): etiqueta de sentimiento, `menciona_falla`, duda | Cola de sentimiento (`HitlTriageQueue`) |
| `eda/aspects_app.py` y `eda/aspects_v2_app.py` (Streamlit, 5.2): familias `v2.1`, marcas `u` y `s` | Codificación de aspectos (nueva) |
| Fichas y CSV de `data/topics/phase4_v0/` (5.5) | Curaduría de tópicos en la revisión trimestral de la fase 4 (nueva) |

* Criterio de terminado: cada pantalla reproduce el flujo del prototipo, escribe en la base de curadurías de EPIC-6 (6.2) y muestra solo texto sanitizado.

---

## ✅ Checklist de Aceptación de la Épica 7 (Cierre del Proyecto)

* [ ] `api-backend` expone los endpoints de KPIs (*Satisfaction Gap*), series de tiempo por versión, búsqueda vectorial de 768 dimensiones, explicabilidad SHAP/LIME y cola de validación HITL.

* [ ] Las decisiones humanas del protocolo HITL se registran de forma inmutable en `bbva_voc_tds.hitl_triage_audit_log` usando `HitlTriageAuditRecord` con el correo del revisor hasheado con SHA-256.

* [ ] El portal muestra las alertas de *drift* de EPIC-6 (6.4).

* [ ] Los 3 artefactos de gobernanza (`data_card.md`, `model_card.md` y `ethical_fmea_matrix.md`) están redactados y completos en `docs/governance/`.

* [ ] El portal web en `web/hitl-portal/` compila sin errores de TypeScript (`npm run build`).
* [ ] Todos los *Quality Gates* del monorepo (`uv run ruff check .`, `uv run ruff format --check .`, `uv run pyrefly check`, `uv run bandit -c pyproject.toml -r .` y `uv run pytest --cov-fail-under=85`) pasan con **0 errores**.

* [ ] Los frontales de curaduría de sentimiento, aspectos y tópicos están en el portal y escriben en la base de curadurías para el reentrenamiento (7.7).
