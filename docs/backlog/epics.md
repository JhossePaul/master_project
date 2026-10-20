# Mapa de Épicas del Proyecto (App Store Label Noise & Incident Analyzer)

Este documento define las **6 Épicas Técnicas** necesarias para construir y
desplegar el motor analítico de NLP en Google Cloud Platform (GCP), diseñado
para corregir el *Label Noise Bias (LNB)* (sesgo de *Obligatory 5-Star*),
recalibrar la satisfacción hacia el **True Net Satisfaction Score (TNSS)** y
automatizar el triaje del backlog de ingeniería bajo lineamientos de *Ethics by
Design* y *Human-In-The-Loop (HITL)*[cite: 1, 8, 27].

---

## Resumen de Épicas, Estado y Cronograma

| ID | Nombre de la Épica | Estado Actual | Semanas | Directorios Principales Afectados | Archivo de Detalle |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **EPIC-1** | Fundamentos del Monorepo, Contratos de Datos v2 (`voc-common`) y Quality Gates | **IMPLEMENTADO** [Features 1.1–1.8](cite: 23) | Sem 1[cite: 23, 27] | `packages/voc-common/`, `docs/contracts/`, `.github/`[cite: 23] | `epic_1.md`[cite: 27] |
| **EPIC-2** | Aprovisionamiento de Infraestructura Serverless y Seguridad en GCP (IaC) | **IMPLEMENTADO** [Features 2.1–2.10 en Mocks](cite: 24) | Sem 1 - 2[cite: 24, 27] | `infra/`[cite: 24, 27] | `epic_2.md`[cite: 27] |
| **EPIC-3** | Ingesta Multibanco Reanudable desde Google Play (`batchexecute`) | **IMPLEMENTADO** [Features 3.1–3.5; sin despliegue](cite: 25) | Sem 2[cite: 27] | `services/ingestion-worker/`, `experiments/playstore/`[cite: 25] | `epic_3.md`[cite: 27] |
| **EPIC-4** | Sanitización PII (*Ethics by Design*), Persistencia Idempotente y Cobertura TDS | **IMPLEMENTADO** [Features 4.1–4.5; sin despliegue](cite: 26) | Sem 3 - 4[cite: 14, 27] | `services/sanitization-pipeline/`[cite: 26, 27] | `epic_4.md`[cite: 27] |
| **EPIC-5** | Core Analítico NLP: planteamiento, experimentación y despliegue | **EN CURSO** (fase 2: etiquetado y competencia de modelos; despliegue condicionado al registro de decisión) | Sem 4 - 6[cite: 27] | `experiments/analytics/`, `docs/analytics/`; después `services/ml-delora/`[cite: 27] | `epic_5.md`, `epic_5_deployment.md`[cite: 27] |
| **EPIC-6** | Exposición (FastAPI), Búsqueda Vectorial, Portal Web HITL y Gobernanza MLOps | **PENDIENTE** (Especificación v2 lista) | Sem 7 - 8[cite: 14, 27] | `services/api-backend/`, `web/hitl-portal/`, `docs/governance/`[cite: 27] | `epic_6.md`[cite: 27] |

---

## Descripción Detallada de las Épicas (Sincronizada con Arquitectura v2)

### EPIC-1: Fundamentos del Monorepo, Contratos de Datos v2 (`voc-common`) y Quality Gates

* **Estado:** **IMPLEMENTADO** [Features 1.1 a 1.8 verificadas localmente con cobertura del 100%](cite: 23).
* **Objetivo Técnico:** Establecer la columna vertebral de tipado, contratos inmutables (`extra="forbid"`, normalización UTC), reducer de estado por página y tubería de integración continua (CI) antes de acoplar servicios o infraestructura[cite: 23, 27].
* **Alcance y Componentes Implementados:**
  * **Catálogo y Constantes (`constants.py`):** Definición de instituciones (`BBVA`, `NUBANK`, `SANTANDER`, `AZTECA`, `BANORTE`), modos de ingesta (`INCREMENTAL`, `BACKFILL` anual, `FULL_BACKFILL`), tópicos `ABSATopic`, parámetros del protocolo interno `batchexecute` (RPC `oCPfdb`, tamaño inicial de política `199`) y umbrales del EDA [2 a 60 palabras](cite: 23).
  * **Utilidades de Limpieza y Privacidad (`text_utils.py`):** Limpieza determinista de textos bancarios preservando emojis y códigos diagnósticos (`ref: 3702:65c5:9xhchi`), conteo de palabras y anonimización irreversible `hash_username_pii` [SHA-256 con sal](cite: 23).
  * **Contratos de Datos y Sobres Versionados (`schemas.py`):**
    1. `RawReviewEvent` y `RawReviewEnvelope`: Evento crudo en tránsito con identidad determinista (`event_id`, `source_revision` derivado del contenido, nunca de `ingested_at`)[cite: 23].
    2. `SanitizedReviewRecord` y `SanitizedReviewEnvelope`: Registro post-DLP con 0% de `usuario` o `imagen_usuario` en texto plano, listo para las 17 columnas de BigQuery [*Trusted Data Source - TDS*](cite: 23, 24).
    3. `IngestionWatermarkState` (v2), `IncrementalProgress`, `HistoricalPlan`, `ScanContext`, `ScanStreamState`, `PageManifest` y `ProcessingReceipt`: Separación estricta entre límites observados, progreso incremental comprometido, planes históricos con ancla $T_0$ fija y recibos de procesamiento por fase[cite: 23, 25].
    4. `AnalyzedReviewPrediction`, `IncidentAlertMessage`, `HitlTriageAuditRecord` e `IngestionRunAudit`[cite: 23].
  * **Reducer Puro y Quality Gates (`ingestion_state.py`, `.github/workflows/ci.yaml`):** Transiciones verificables por página confirmada y validación automatizada con `Ruff`, `Pyrefly`, `Bandit` y `Pytest`[cite: 23].

---

### EPIC-2: Aprovisionamiento de Infraestructura Serverless y Seguridad en GCP (IaC)

* **Estado:** **IMPLEMENTADO** [Features 2.1 a 2.10 verificadas localmente con Pulumi Mocks; preview/despliegue real sujeto a inicialización del stack en GCP](cite: 24).
* **Objetivo Técnico:** Codificar en **Pulumi (Python)** el despliegue reproducible, de mínimo privilegio y compatible con **GCP Free Tier** de las 5 capas de la solución[cite: 24, 27].
* **Alcance y Componentes Implementados:**
  * **Seguridad e IAM (`kms_iam.py`):** 4 *Service Accounts* dedicadas (`voc-sa-ingestion`, `voc-sa-scheduler`, `voc-sa-sanitization`, `voc-sa-ml-backend`) con permisos acotados por recurso (`roles/storage.objectUser` a nivel bucket, `roles/run.jobsExecutorWithOverrides` sobre el Job histórico) y soporte condicional para llaves KMS/CMEK (`enable_cmek`)[cite: 24].
  * **Privacidad por Diseño (`dlp.py`):** Plantillas regionales de inspección y desidentificación en **Cloud DLP** con 5 detectores NER nativos, 3 detectores REGEX bancarios mexicanos (`MX_CLABE_BANCARIA`, `MX_RFC_TAX_ID`, `BBVA_ACCOUNT_NUMBER`), reemplazo explícito por tokens entre corchetes (`[<INFO_TYPE>]`) y regla de exclusión parcial (`ExclusionRule`) para preservar códigos técnicos `ref: 3702`[cite: 24].
  * **Mensajería y Almacenamiento (`pubsub.py`, `storage_bq.py`):**
    * Tópicos y suscripciones Pull en Cloud Pub/Sub (`voc-raw-reviews-topic`, `voc-raw-reviews-dlq` con 5 intentos, `voc-incident-alerts-topic`)[cite: 24].
    * Bucket `voc-datalake-{project_id}` con `IngestionStorageLayout` que aplica TTL de 7 días exclusivamente a `raw_staging/` y `temp_beam/`, preservando indefinidamente `state/watermarks/` y `state/ingestion/` [manifiestos, ledgers y recibos](cite: 24).
    * Dataset `bbva_voc_tds` en **BigQuery** sin tablas de texto crudo, aprovisionando 4 tablas estrictas particionadas y clusterizadas: `sanitized_reviews_tds` (17 columnas, incluida `source_observed_at`), `delora_predictions` (15 columnas incluyendo `embedding_vector` `FLOAT REPEATED`), `ingestion_runs_log_v2` (20 columnas) y `hitl_triage_audit_log` [10 columnas](cite: 24).
  * **Cómputo Serverless y Orquestación (`cloud_run.py`, `cloud_scheduler.py`, `vertex_ai.py`):** Servicios *scale-to-zero* (`voc-ingestion-worker`, `voc-api-backend`), 2 Cloud Run Jobs privados (`voc-sanitization-job` y `voc-ingestion-history-job` para backfills largos fuera del ciclo HTTP), programación en Cloud Scheduler optimizada a 2 jobs en modo *Free Tier* (o 6 en modo normal) y recursos de Vertex AI condicionales (`enable_dedicated_vertex_endpoints`)[cite: 24].

---

### EPIC-3: Ingesta Multibanco Reanudable desde Google Play (`batchexecute`)

* **Estado:** **IMPLEMENTADO** [Features 3.1–3.5 completadas y validadas localmente; despliegue pendiente](cite: 25).
* **Objetivo Técnico:** Construir el servicio y Job contenerizado en `services/ingestion-worker/` capaz de extraer reseñas públicas de Google Play Store mediante un cliente propio sobre el protocolo interno `batchexecute` (`oCPfdb`), con respaldo duradero por página, control de concurrencia CAS/lease y recuperación verificable[cite: 25, 27].
* **Alcance y Componentes:**
  * **Adaptador de Protocolo (`playstore_protocol.py` — Implementado):** Serialización estructural de peticiones `batchexecute`, parser posicional validado contra respuestas reales de BBVA (`ocpfdb-2026-10-15.1`) y clasificación estricta de estados y errores (`PAGE_WITH_CURSOR`, `END_CANDIDATE`, `EMPTY_WITH_CURSOR`, `RateLimitedError`, `ProtocolError`)[cite: 25].
  * **Repositorio de Estado y Auditoría (`watermark_store.py`, `audit.py` — Implementado):** Persistencia en GCS con precondiciones `if_generation_match` (CAS), lease por banco con *fencing epoch*, snapshots de planes/streams/manifiestos/ledgers y entrega durable de `IngestionRunAudit` hacia `ingestion_runs_log_v2`[cite: 25].
  * **Publicación Duradera por Página (`publisher.py` — Implementado):** Escritura condicional de capturas reproducibles `.jsonl.gz` en `raw_staging/`, registro de `PageManifest` pendiente y emisión de sobres `RawReviewEnvelope` a Pub/Sub verificando cada `future.result()` antes de avanzar el estado a `PUBLISHED`[cite: 25].
  * **Motor de Extracción, Políticas de Recuperación, API y Job Histórico (`extractor.py`, `main.py`, `job.py` — Features 3.4 y 3.5):** Ejecución de modos `INCREMENTAL`, `BACKFILL` (anual con $T_0$ fijo) y `FULL_BACKFILL` (extensión del mismo plan y replay de página ancla), escalera de recuperación de coste creciente, control de presupuestos y exposición de endpoints HTTP más CLI para `voc-ingestion-history-job`[cite: 24, 25].

---

### EPIC-4: Sanitización PII (*Ethics by Design*), Persistencia Idempotente y Cobertura TDS

* **Estado:** **IMPLEMENTADO** [Features 4.1–4.5 completadas y validadas localmente; despliegue pendiente](cite: 26).
* **Objetivo Técnico:** Desarrollar el pipeline en **Apache Beam** (`services/sanitization-pipeline/`) ejecutable con `DirectRunner` dentro de `voc-sanitization-job` (`DataflowRunner` queda opt-in hasta aprovisionar Dataflow) que drena los sobres `RawReviewEnvelope`, desidentifica PII mediante **Cloud DLP + Regex de segunda barrera**, filtra el umbral de 2 a 60 palabras del EDA, actualiza `bbva_voc_tds.sanitized_reviews_tds` de forma idempotente y emite recibos `ProcessingReceipt` para cerrar la cobertura TDS por página[cite: 24, 26, 27].
* **Alcance y Componentes:**
  * **Transformación DLP Tabular y *Fail-Closed* (`dlp_transforms.py`):** Empaquetador dual ($\le 250$ filas y $\le 400\text{ KB}$) con *sidecar* posicional para no enviar IDs a DLP, protección de códigos diagnósticos `ref: 3702` mediante nonce, segunda barrera `LocalRegexFallbackSanitizer`, conteo exacto de tokens `[<INFO_TYPE>]` por fila (`pii_findings_count: int`) y política *fail-closed* en producción[cite: 24, 26].
  * **Upsert Idempotente en BigQuery (`bq_writer.py`):** Carga de lotes sanitizados en tablas temporales con expiración de 1 hora dentro de `bbva_voc_tds` mediante `FILE_LOADS` (`load_table_from_json`) seguida de `MERGE` determinista hacia las 17 columnas de `sanitized_reviews_tds` sin usar *Streaming Inserts* y sin revertir revisiones más recientes[cite: 24, 26].
  * **Ledger de Procesamiento y Leases de Ack (`processing_ledger.py`, `pipeline.py`):** Renovación periódica de `ack_deadline` (>600s), deduplicación preservando todos los `ack_ids` de redeliveries, gestión de cuarentena en GCS (acorde a los permisos IAM de `voc-sa-sanitization`), confirmación (`ack`) exclusiva tras persistencia en BigQuery + GCS, y cierre de páginas publicadas como `RESOLVED` o `GAPS_DETECTED` sin escribir en el estado de la ingesta[cite: 24, 25, 26].

---

### EPIC-5: Core Analítico NLP — Planteamiento, Experimentación y Despliegue

* **Estado:** **EN CURSO** (fase 2). Estado por feature y siguientes pasos en `epic_5.md`; historia de los resultados en [`docs/analytics/`](../analytics/README.md). El despliegue (`epic_5_deployment.md`) es un borrador condicionado al registro de decisión.
* **Objetivo Técnico:** Decidir con evidencia el pipeline analítico sobre las 2 649 047 reseñas de los 5 bancos antes de construir el paquete desplegable: sentimiento real separado de las estrellas, tópicos recurrentes y su evolución, detección de incidentes y priorización.
* **Alcance y Componentes:**
  * **Planteamiento y EDA (5.1–5.2):** etiquetas y guía de anotación, elegibilidad por tarea (con motivo para lo no predecible), envolvente de volumetría y costo, EDA de 15 años × 5 bancos y reglas de limpieza.
  * **Etiquetado (5.3):** plata con Gemini Flash (deduplicada, por lotes y con tope de gasto) y oro humano de 1 000–2 000 reseñas (40 % aleatorio estratificado, 60 % dirigido, submuestra a ciegas).
  * **Competencia de modelos (5.4):** de las estrellas como referencia y TF-IDF hasta encoders ajustados, métodos de ruido (*label smoothing*, corrección *forward*, *Confident Learning*), Delora adaptado y Gemini como clasificador; mismo protocolo y métricas de calidad y costo.
  * **Tópicos (5.5):** descubrimiento dinámico sobre negativos y decisión entre ABSA, tópicos dinámicos o híbrido, con señal de incidentes probada hacia atrás.
  * **Calibración, escala y ciclo de vida (5.6–5.7)** y **registro de decisión (5.8)**, que habilita el despliegue (fase 3).

---

### EPIC-6: Exposición (FastAPI), Búsqueda Vectorial, Portal Web HITL y Gobernanza MLOps

* **Estado:** **PENDIENTE** (Especificación técnica actualizada a contratos v2).
* **Objetivo Técnico:** Construir la capa de exposición e interpretabilidad (`services/api-backend/` y `web/hitl-portal/`) para consulta del *Satisfaction Gap*, búsqueda vectorial de causa raíz, explicabilidad local (**SHAP / LIME**) y ejecución del protocolo **Human-In-The-Loop (HITL)**, junto con el monitoreo estadístico de *Drift* y los artefactos normativos de BBVA[cite: 8, 11, 16, 17, 18, 27].
* **Alcance y Componentes:**
  * **API Backend y Búsqueda Vectorial (`services/api-backend/`):** Endpoints RESTful en FastAPI conectados a BigQuery para métricas del *Satisfaction Gap* (BBVA vs. `NUBANK`, `SANTANDER`, `AZTECA`, `BANORTE`), series de tiempo de quejas por `version_app`, ranking de backlog y búsqueda semántica por distancia coseno sobre `embedding_vector` (768-d) en BigQuery [con soporte condicional para Vertex AI Vector Search](cite: 5, 8, 10, 11, 24, 27).
  * **Explicabilidad Local y Bitácora HITL (`explainability.py`, `hitl_service.py`):** Motor ligero de atribución por perturbación/oclusión de tokens (LIME / SHAP contrastivo compatible con `1 vCPU / 1 GiB RAM` en Cloud Run) y servicio de validación humana que persiste decisiones inmutables `HitlTriageAuditRecord` en `bbva_voc_tds.hitl_triage_audit_log` hasheando el correo del revisor con SHA-256[cite: 8, 17, 20, 23, 24, 27].
  * **Portal Interactivo React SPA (`web/hitl-portal/`):** Interfaz con paleta institucional (`#002D72`, `#215347`, `#7A1A37`, `#B9975B`) integrada por `SatisfactionGapDashboard`, `VectorRootCauseExplorer` (con visor de calor de atribuciones por palabra) y `HitlTriageQueue`[cite: 2, 8, 11, 27].
  * **Monitoreo de Drift y Gobernanza (`drift_monitor.py`, `docs/governance/`):** Cálculo de *Data Drift* (PSI/JSD) y *Concept Drift* entre versiones de la app con alerta hacia `voc-incident-alerts-topic` para activar el *Fallback Plan*, y entrega formal de la **Data Card**, **Model Card** y **Matriz Ethical FMEA**[cite: 8, 14, 15, 16, 17, 18, 27].
