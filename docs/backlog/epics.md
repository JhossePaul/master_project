# Mapa de Épicas del Proyecto (App Store Label Noise & Incident Analyzer)

El proyecto se divide en **7 épicas técnicas** para construir y desplegar en Google Cloud Platform (GCP) el motor analítico de NLP: medir el sentimiento real del texto separado de las estrellas (*Label Noise Bias*, sesgo de *Obligatory 5-Star*), detectar y priorizar incidencias, y exponerlo con revisión humana (HITL) bajo lineamientos de *Ethics by Design*.

* **Estado (2026-10-22):** EPIC-1 a EPIC-4 cerradas; EPIC-5 en curso (5.1 a 5.9 cerradas; faltan sus criterios de cierre); EPIC-6 y EPIC-7 pendientes. Lo que falta decidir antes de montar la infraestructura está en el [registro de decisiones](epic_5.md#decisiones-pendientes).
* **Reorganización (2026-10-22):** se agregó EPIC-6 (despliegue del core analítico), que absorbe la antigua fase 3 de EPIC-5 (`epic_5_deployment.md`) y los cambios a los contratos de EPIC-1 y a la infraestructura de EPIC-2. El portal pasó de EPIC-6 a EPIC-7 (features 6.x → 7.x). El cierre de EPIC-1 a EPIC-4, que estaba en `closure_epics_1_4.md`, quedó en la sección [Cierre de las épicas 1 a 4](#cierre-de-las-épicas-1-a-4).

---

## Resumen de épicas

| ID | Nombre | Estado | Directorios principales | Detalle |
| :--- | :--- | :---: | :--- | :--- |
| **EPIC-1** | Fundamentos del monorepo, contratos de datos v2 (`voc-common`) y *quality gates* | **Cerrada** | `packages/voc-common/`, `docs/contracts/`, `.github/` | [`epic_1.md`](epic_1.md) |
| **EPIC-2** | Infraestructura *serverless* y seguridad en GCP (Pulumi) | **Cerrada** | `infra/` | [`epic_2.md`](epic_2.md) |
| **EPIC-3** | Ingesta multibanco reanudable desde Google Play (`batchexecute`) | **Cerrada** | `services/ingestion-worker/`, `experiments/playstore/` | [`epic_3.md`](epic_3.md) |
| **EPIC-4** | Sanitización PII, persistencia idempotente y cobertura TDS | **Cerrada** | `services/sanitization-pipeline/` | [`epic_4.md`](epic_4.md) |
| **EPIC-5** | Planteamiento analítico y experimentación del core NLP | **En curso** (5.1–5.9 cerradas; faltan los criterios de cierre) | `experiments/analytics/`, `docs/analytics/` | [`epic_5.md`](epic_5.md) |
| **EPIC-6** | Despliegue del core analítico: contratos, infraestructura e inferencia | **Pendiente** (5.8 aprobada; se detalla al empezar) | `packages/voc-common/`, `infra/`, `services/ml-*/` | [`epic_6.md`](epic_6.md) |
| **EPIC-7** | API (FastAPI), búsqueda vectorial, explicabilidad, portal web HITL y gobernanza | **Pendiente** | `services/api-backend/`, `web/hitl-portal/`, `docs/governance/` | [`epic_7.md`](epic_7.md) |

Orden: cada épica usa los contratos y recursos de las anteriores. EPIC-6 empieza al aprobarse el registro de decisión de EPIC-5 (5.8), y EPIC-7 lee lo que despliega EPIC-6.

---

## Cierre de las épicas 1 a 4

Al 2026-10-18 la ingeniería de extracción queda **cerrada**: el histórico está cargado y verificado, la operación diaria funciona sin intervención y los accesos temporales se retiraron.

| Épica | Entregado | Verificado en producción (stack `dev`) |
| :--- | :--- | :--- |
| 1. `voc-common` y CI | Contratos, constantes, configuración, estado v2, logs estructurados, CI (ruff, pyrefly, bandit, pytest) | Los cuatro gates pasan; se usó en las 5 ingestas históricas y en la sanitización |
| 2. Infraestructura (Pulumi) | APIs, IAM, KMS, Pub/Sub (+DLQ), GCS, BigQuery, Cloud Run Service/Jobs, Schedulers | `pulumi preview` sin cambios (54 recursos); desplegado con imágenes fijadas por digest |
| 3. Ingesta | Cliente `batchexecute`, lease + CAS, páginas duraderas, runner, API incremental, Job histórico | Los 5 bancos recorridos hasta agotar el cursor (reseñas hasta el 2026-10-14) |
| 4. Sanitización | Pipeline Pub/Sub → regex local → BigQuery `MERGE`, ledger de recibos, replay desde GCS | El replay rápido (`GCS_FAST_REPLAY`) cargó el histórico completo |

* **Resultado:** 2 649 047 filas únicas en `bbva_voc_tds.sanitized_reviews_tds`, sin duplicados por `(bank_id, id_resena)`. Conteos por banco y ritmos de la carga en [`full_backfill.md`](../operations/full_backfill.md#resultado-de-la-carga-al-tds-2026-10-16).
* **Límites del corpus** (reseñas sin texto, NUBANK antes de 2020, retraso de ~24 h, PII residual, cobertura inferida, `fecha` de última edición): [*Data Card*](../governance/data_card.md).
* **Incidentes de la puesta en marcha:** [`full_backfill.md`](../operations/full_backfill.md#incidentes-de-la-puesta-en-marcha-resumen). **Validación de la operación diaria** y observaciones abiertas (contador `PENDING` del informe, tres cuentas con `roles/owner`): [`deployment.md`](../operations/deployment.md#validación-de-la-operación-diaria-2026-10-18).
* **Herramientas de operación:** `tools/backfill_controller.py` (`drain`, `ingest`) y `tools/deploy_images.py`; ver [`deployment.md`](../operations/deployment.md).

---

## Descripción de las épicas

### EPIC-1: Fundamentos del Monorepo, Contratos de Datos v2 (`voc-common`) y Quality Gates

* **Estado:** **Cerrada.** Features 1.1 a 1.8 verificadas localmente con cobertura del 100 % y usadas en producción. Los contratos de predicción se reemplazan en EPIC-6 (6.1).
* **Objetivo Técnico:** Establecer la columna vertebral de tipado, contratos inmutables (`extra="forbid"`, normalización UTC), reducer de estado por página y tubería de integración continua (CI) antes de acoplar servicios o infraestructura.
* **Alcance y Componentes Implementados:**
  * **Catálogo y Constantes (`constants.py`):** Definición de instituciones (`BBVA`, `NUBANK`, `SANTANDER`, `AZTECA`, `BANORTE`), modos de ingesta (`INCREMENTAL`, `BACKFILL` anual, `FULL_BACKFILL`), tópicos `ABSATopic`, parámetros del protocolo interno `batchexecute` (RPC `oCPfdb`, tamaño inicial de política `199`) y umbrales del EDA 2 a 60 palabras.
  * **Utilidades de Limpieza y Privacidad (`text_utils.py`):** Limpieza determinista de textos bancarios preservando emojis y códigos diagnósticos (`ref: 3702:65c5:9xhchi`), conteo de palabras y anonimización irreversible `hash_username_pii` SHA-256 con sal.
  * **Contratos de Datos y Sobres Versionados (`schemas.py`):**
    1. `RawReviewEvent` y `RawReviewEnvelope`: Evento crudo en tránsito con identidad determinista (`event_id`, `source_revision` derivado del contenido, nunca de `ingested_at`).
    2. `SanitizedReviewRecord` y `SanitizedReviewEnvelope`: Registro post-DLP con 0% de `usuario` o `imagen_usuario` en texto plano, listo para las 17 columnas de BigQuery *Trusted Data Source - TDS*.
    3. `IngestionWatermarkState` (v2), `IncrementalProgress`, `HistoricalPlan`, `ScanContext`, `ScanStreamState`, `PageManifest` y `ProcessingReceipt`: Separación estricta entre límites observados, progreso incremental comprometido, planes históricos con ancla $T_0$ fija y recibos de procesamiento por fase.
    4. `AnalyzedReviewPrediction`, `IncidentAlertMessage`, `HitlTriageAuditRecord` e `IngestionRunAudit`.
  * **Reducer Puro y Quality Gates (`ingestion_state.py`, `.github/workflows/ci.yaml`):** Transiciones verificables por página confirmada y validación automatizada con `Ruff`, `Pyrefly`, `Bandit` y `Pytest`.

---

---

### EPIC-2: Aprovisionamiento de Infraestructura Serverless y Seguridad en GCP (IaC)

* **Estado:** **Cerrada.** Features 2.1 a 2.10; desplegada en el stack `dev` (54 recursos, `pulumi preview` sin cambios). Los recursos de predicción se reemplazan en EPIC-6 (6.2).
* **Objetivo Técnico:** Codificar en **Pulumi (Python)** el despliegue reproducible, de mínimo privilegio y compatible con **GCP Free Tier** de las 5 capas de la solución.
* **Alcance y Componentes Implementados:**
  * **Seguridad e IAM (`kms_iam.py`):** 4 *Service Accounts* dedicadas (`voc-sa-ingestion`, `voc-sa-scheduler`, `voc-sa-sanitization`, `voc-sa-ml-backend`) con permisos acotados por recurso (`roles/storage.objectUser` a nivel bucket, `roles/run.jobsExecutorWithOverrides` sobre el Job histórico) y soporte condicional para llaves KMS/CMEK (`enable_cmek`).
  * **Privacidad por Diseño (`dlp.py`):** Plantillas regionales de inspección y desidentificación en **Cloud DLP** con 5 detectores NER nativos, 3 detectores REGEX bancarios mexicanos (`MX_CLABE_BANCARIA`, `MX_RFC_TAX_ID`, `BBVA_ACCOUNT_NUMBER`), reemplazo explícito por tokens entre corchetes (`[<INFO_TYPE>]`) y regla de exclusión parcial (`ExclusionRule`) para preservar códigos técnicos `ref: 3702`.
  * **Mensajería y Almacenamiento (`pubsub.py`, `storage_bq.py`):**
    * Tópicos y suscripciones Pull en Cloud Pub/Sub (`voc-raw-reviews-topic`, `voc-raw-reviews-dlq` con 5 intentos, `voc-incident-alerts-topic`).
    * Bucket `voc-datalake-{project_id}` con `IngestionStorageLayout` que aplica TTL de 7 días exclusivamente a `raw_staging/` y `temp_beam/`, preservando indefinidamente `state/watermarks/` y `state/ingestion/` manifiestos, ledgers y recibos.
    * Dataset `bbva_voc_tds` en **BigQuery** sin tablas de texto crudo, aprovisionando 4 tablas estrictas particionadas y clusterizadas: `sanitized_reviews_tds` (17 columnas, incluida `source_observed_at`), `delora_predictions` (15 columnas incluyendo `embedding_vector` `FLOAT REPEATED`), `ingestion_runs_log_v2` (20 columnas) y `hitl_triage_audit_log` 10 columnas.
  * **Cómputo Serverless y Orquestación (`cloud_run.py`, `cloud_scheduler.py`, `vertex_ai.py`):** Servicios *scale-to-zero* (`voc-ingestion-worker`, `voc-api-backend`), 2 Cloud Run Jobs privados (`voc-sanitization-job` y `voc-ingestion-history-job` para backfills largos fuera del ciclo HTTP), programación en Cloud Scheduler optimizada a 2 jobs en modo *Free Tier* (o 6 en modo normal) y recursos de Vertex AI condicionales (`enable_dedicated_vertex_endpoints`).

---

---

### EPIC-3: Ingesta Multibanco Reanudable desde Google Play (`batchexecute`)

* **Estado:** **Cerrada.** Features 3.1 a 3.5; desplegada y con el histórico de los 5 bancos recorrido hasta agotar el cursor.
* **Objetivo Técnico:** Construir el servicio y Job contenerizado en `services/ingestion-worker/` capaz de extraer reseñas públicas de Google Play Store mediante un cliente propio sobre el protocolo interno `batchexecute` (`oCPfdb`), con respaldo duradero por página, control de concurrencia CAS/lease y recuperación verificable.
* **Alcance y Componentes:**
  * **Adaptador de Protocolo (`playstore_protocol.py` — Implementado):** Serialización estructural de peticiones `batchexecute`, parser posicional validado contra respuestas reales de BBVA (`ocpfdb-2026-10-15.1`) y clasificación estricta de estados y errores (`PAGE_WITH_CURSOR`, `END_CANDIDATE`, `EMPTY_WITH_CURSOR`, `RateLimitedError`, `ProtocolError`).
  * **Repositorio de Estado y Auditoría (`watermark_store.py`, `audit.py` — Implementado):** Persistencia en GCS con precondiciones `if_generation_match` (CAS), lease por banco con *fencing epoch*, snapshots de planes/streams/manifiestos/ledgers y entrega durable de `IngestionRunAudit` hacia `ingestion_runs_log_v2`.
  * **Publicación Duradera por Página (`publisher.py` — Implementado):** Escritura condicional de capturas reproducibles `.jsonl.gz` en `raw_staging/`, registro de `PageManifest` pendiente y emisión de sobres `RawReviewEnvelope` a Pub/Sub verificando cada `future.result()` antes de avanzar el estado a `PUBLISHED`.
  * **Motor de Extracción, Políticas de Recuperación, API y Job Histórico (`extractor.py`, `main.py`, `job.py` — Features 3.4 y 3.5):** Ejecución de modos `INCREMENTAL`, `BACKFILL` (anual con $T_0$ fijo) y `FULL_BACKFILL` (extensión del mismo plan y replay de página ancla), escalera de recuperación de coste creciente, control de presupuestos y exposición de endpoints HTTP más CLI para `voc-ingestion-history-job`.

---

---

### EPIC-4: Sanitización PII (*Ethics by Design*), Persistencia Idempotente y Cobertura TDS

* **Estado:** **Cerrada.** Features 4.1 a 4.5; desplegada; el replay rápido cargó el histórico y la operación diaria corre sin intervención.
* **Objetivo Técnico:** Desarrollar el pipeline en **Apache Beam** (`services/sanitization-pipeline/`) ejecutable con `DirectRunner` dentro de `voc-sanitization-job` (`DataflowRunner` queda opt-in hasta aprovisionar Dataflow) que drena los sobres `RawReviewEnvelope`, desidentifica PII mediante **Cloud DLP + Regex de segunda barrera**, filtra el umbral de 2 a 60 palabras del EDA, actualiza `bbva_voc_tds.sanitized_reviews_tds` de forma idempotente y emite recibos `ProcessingReceipt` para cerrar la cobertura TDS por página.
* **Alcance y Componentes:**
  * **Transformación DLP Tabular y *Fail-Closed* (`dlp_transforms.py`):** Empaquetador dual ($\le 250$ filas y $\le 400\text{ KB}$) con *sidecar* posicional para no enviar IDs a DLP, protección de códigos diagnósticos `ref: 3702` mediante nonce, segunda barrera `LocalRegexFallbackSanitizer`, conteo exacto de tokens `[<INFO_TYPE>]` por fila (`pii_findings_count: int`) y política *fail-closed* en producción.
  * **Upsert Idempotente en BigQuery (`bq_writer.py`):** Carga de lotes sanitizados en tablas temporales con expiración de 1 hora dentro de `bbva_voc_tds` mediante `FILE_LOADS` (`load_table_from_json`) seguida de `MERGE` determinista hacia las 17 columnas de `sanitized_reviews_tds` sin usar *Streaming Inserts* y sin revertir revisiones más recientes.
  * **Ledger de Procesamiento y Leases de Ack (`processing_ledger.py`, `pipeline.py`):** Renovación periódica de `ack_deadline` (>600s), deduplicación preservando todos los `ack_ids` de redeliveries, gestión de cuarentena en GCS (acorde a los permisos IAM de `voc-sa-sanitization`), confirmación (`ack`) exclusiva tras persistencia en BigQuery + GCS, y cierre de páginas publicadas como `RESOLVED` o `GAPS_DETECTED` sin escribir en el estado de la ingesta.

---

### EPIC-5: Planteamiento Analítico y Experimentación del Core NLP

* **Estado:** **En curso** (fase 2). Estado por feature y siguientes pasos en [`epic_5.md`](epic_5.md); historia de los resultados en [`docs/analytics/`](../analytics/README.md).
* **Objetivo técnico:** decidir con evidencia el pipeline analítico sobre las 2 649 047 reseñas antes de construir el paquete desplegable: sentimiento real separado de las estrellas, temas recurrentes y su evolución, detección de incidentes y priorización.
* **Alcance:** planteamiento y elegibilidad (5.1), EDA (5.2), etiquetado oro y plata (5.3), competencia de modelos de sentimiento (5.4), tópicos e incidencias (5.5), calibración y HITL (5.6), escala y monitoreo (5.7), registro de decisión (5.8) e incidentes y versiones con la estrategia elegida (5.9).

---

### EPIC-6: Despliegue del Core Analítico (Contratos, Infraestructura e Inferencia)

* **Estado:** **Pendiente.** El registro de decisión de EPIC-5 (5.8) se aprobó el 2026-10-22; las features se detallan a partir de él al empezar.
* **Objetivo técnico:** llevar a producción la estrategia de 5.8 con un backfill único y un delta diario.
* **Alcance:** contratos de predicción v3 en `voc-common` (6.1), tablas de salida y de curaduría en Pulumi (6.2), servicio de inferencia batch con `MERGE` y alertas (6.3), y monitor de *drift* y ciclo de vida de modelos (6.4).

---

### EPIC-7: Exposición (FastAPI), Búsqueda Vectorial, Explicabilidad, Portal Web HITL y Gobernanza

* **Estado:** **Pendiente** (antes EPIC-6).
* **Objetivo técnico:** construir la capa de consumo (`services/api-backend/` y `web/hitl-portal/`): *Satisfaction Gap*, búsqueda semántica de causa raíz, explicabilidad local (atribución por oclusión), protocolo HITL, frontales de curaduría y artefactos normativos (*Data Card*, *Model Card*, matriz FMEA).
* **Alcance (reescrito el 2026-10-22, P8-12):** API (7.1), seguridad y roles (7.2), landing (7.3), reporte de hallazgos (7.4), cockpit diario (7.5), Explorador con búsqueda y XAI (7.6), HITL de sentimiento, aspectos y tópicos (7.7), alertas e incidentes (7.8), MLOps y AIOps (7.9), administración (7.10), documentos de gobernanza (7.11) y pruebas (7.12), con alcance por niveles para la presentación.
