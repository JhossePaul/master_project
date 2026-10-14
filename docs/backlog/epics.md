# Mapa de Épicas del Proyecto (App Store Label Noise & Incident Analyzer)

Este documento define las **6 Épicas Técnicas** necesarias para construir y
desplegar el motor analítico de NLP en Google Cloud Platform (GCP), diseñado
para corregir el *Label Noise Bias (LNB)* (sesgo de *Obligatory 5-Star*),
recalibrar la satisfacción hacia el **True Net Satisfaction Score (TNSS)** y
automatizar el triaje del backlog de ingeniería bajo lineamientos de *Ethics by
Design* y *Human-In-The-Loop (HITL)*.

---

## Resumen de Épicas y Cronograma

| ID | Nombre de la Épica | Semanas | Directorios Principales Afectados | Archivo de Detalle |
| :--- | :--- | :---: | :--- | :--- |
| **EPIC-1** | Fundamentos del Monorepo, Contratos de Datos (`voc-common`) y Quality Gates | Sem 1 | `packages/voc-common/`, `.github/` | `epic_1.md` |
| **EPIC-2** | Aprovisionamiento de Infraestructura Serverless y Seguridad en GCP (IaC) | Sem 1 - 2 | `infra/` | `epic_2.md` |
| **EPIC-3** | Ingesta Paralela Multibanco desde Google Play Store | Sem 2 | `services/ingestion-worker/` | `epic_3.md` |
| **EPIC-4** | Pipeline de Sanitización PII (*Ethics by Design*) y Data Warehouse | Sem 3 - 4 | `services/sanitization-pipeline/` | `epic_4.md` |
| **EPIC-5** | Core Analítico NLP: Baseline RoBERTa, Arquitectura Dual LoRA (*Delora*) y ABSA | Sem 4 - 6 | `services/ml-delora/` | `epic_5.md` |
| **EPIC-6** | Exposición, Búsqueda Vectorial, Portal Web HITL y Gobernanza MLOps | Sem 7 - 8 | `services/api-backend/`, `web/hitl-portal/`, `docs/governance/` | `epic_6.md` |

---

## Descripción Detallada de las Épicas

### EPIC-1: Fundamentos del Monorepo, Contratos de Datos (`voc-common`) y Quality Gates

* **Objetivo Técnico:** Establecer la columna vertebral de tipado y validación
  del proyecto antes de escribir lógica de negocio o infraestructura. Configurar
  la tubería de integración continua (CI) que forzará la calidad del código.
* **Alcance y Componentes:**
  * Definición del catálogo de instituciones objetivo (`BBVA`, `NUBANK`, `SANTANDER`, `AZTECA`, `BANORTE`) y sus respectivos `app_id` de Google Play Store en `constants.py`.
  * Implementación de esquemas estrictos en **Pydantic v2** (`schemas.py`) que modelen el ciclo de vida completo del dato:
    1. `RawReviewEvent`: Dato extraído de Google Play Store (`id` hash, `texto`, `estrellas` 1-5, `votos_utilidad`, `version_app`, `fecha`, `bank_id`).
    2. `SanitizedReviewRecord`: Registro procesado tras la desidentificación de PII por Cloud DLP, listo para persistir en BigQuery (*Trusted Data Source*).
    3. `AnalyzedReviewPrediction`: Salida del motor analítico conteniendo el **TNSS** (polaridad real libre de ruido), bandera de sesgo *Obligatory 5-Star*, **Tópico ABSA**, puntaje de severidad ponderado por votos de utilidad, vector de *embeddings* y nivel de entropía para disparo del protocolo HITL.
    4. `IncidentAlertMessage`: Esquema de alerta crítica para enrutamiento por Pub/Sub.
  * Configuración de `.pre-commit-config.yaml` y GitHub Actions / Cloud Build ejecutando `Ruff`, `Pyrefly`, `Bandit` y `Pytest`.
* **Entregable Clave:** Paquete `voc-common` instalable en todo el workspace con 100% de cobertura en pruebas de validación de esquemas y pipelines de CI activos.

---

### EPIC-2: Aprovisionamiento de Infraestructura Serverless y Seguridad en GCP (IaC)

* **Objetivo Técnico:** Codificar en **Pulumi (Python)** el despliegue automatizado, reproducible y de mínimo privilegio de toda la arquitectura en Google Cloud Platform.
* **Alcance y Componentes:**
  * **Seguridad e IAM (`iam.py`):** Creación de *Service Accounts* dedicadas por capa (Ingesta, Dataflow/DLP, Vertex AI, Backend API) bajo el principio de mínimo privilegio y llaves KMS/CMEK para cifrado AES-256 en reposo.
  * **Mensajería (`pubsub.py`):** Tópicos y suscripciones de Cloud Pub/Sub para: (a) cola de ingesta de reseñas crudas (`voc-raw-reviews-topic`) con *Dead Letter Queue (DLQ)*, y (b) canal de alertas críticas de incidencias y *Model Drift* (`voc-incident-alerts-topic`).
  * **Almacenamiento (`storage_bq.py`):** Buckets en Cloud Storage (staging de Dataflow, artefactos de modelos y crudos) y Dataset/Tablas particionadas por fecha y clusterizadas por banco/versión en **BigQuery** generadas a partir de los esquemas de `voc-common`.
  * **Privacidad (`dlp.py`):** Plantillas de inspección (*Inspect Templates*) y desidentificación (*Deidentify Templates*) en **Cloud DLP** combinando detectores nativos (NER para nombres, teléfonos, correos) y expresiones regulares (REGEX) de dominio bancario mexicano (tarjetas de 16 dígitos, CLABE de 18 dígitos, números de cuenta/contrato, RFC/CURP).
  * **Cómputo y Orquestación (`cloud_run.py`, `cloud_scheduler.py`, `vertex_ai.py`):** Definición de Artifact Registry, servicios/jobs de Cloud Run, los 5 *cron jobs* paralelos en Cloud Scheduler (uno por banco) e índices de Vertex AI Vector Search.
* **Entregable Clave:** Ejecución limpia de `pulumi preview` y `pulumi up` que aprovisiona la infraestructura completa en GCP y exporta los identificadores de recursos para los servicios.

---

### EPIC-3: Ingesta Paralela Multibanco desde Google Play Store

* **Objetivo Técnico:** Construir el *worker* contenerizado en `services/ingestion-worker/` capaz de extraer diariamente las reseñas públicas de Google Play Store para BBVA México y sus 4 competidores, validarlas y publicarlas asíncronamente en Pub/Sub.
* **Alcance y Componentes:**
  * Cliente de extracción parametrizado por `BANK_KEY` y `APP_ID` con manejo de paginación, reintentos exponenciales (*exponential backoff*) y filtrado inicial (reseñas textuales válidas, control de duplicados mediante generación de `id` hash determinista).
  * Validación estricta en memoria mediante `RawReviewEvent` de `voc-common`.
  * Publicador asíncrono en lotes (*batching*) hacia **Cloud Pub/Sub** con inyección de metadatos en los atributos del mensaje.
  * Exposición de punto de entrada HTTP/Job compatible con invocaciones de **Cloud Scheduler** sobre **Cloud Run**.
* **Entregable Clave:** Imagen Docker del *worker* construida y probada unitariamente con mocks de Google Play y Pub/Sub, superando el 80% de cobertura.

---

### EPIC-4: Pipeline de Sanitización PII (*Ethics by Design*) y Data Warehouse

* **Objetivo Técnico:** Desarrollar el pipeline de procesamiento en **Apache Beam / Cloud Dataflow** (`services/sanitization-pipeline/`) que consume los mensajes de Pub/Sub, aplica desidentificación activa del 100% de PII mediante **Cloud DLP** antes de cualquier persistencia o vectorización, y escribe los datos curados en **BigQuery**.
* **Alcance y Componentes:**
  * Transformación `DoFn` en Apache Beam con agrupación en micro-lotes (*batching*) para optimizar cuotas y latencia en las llamadas a la API de `projects.content.deidentify` de Cloud DLP.
  * Enmascaramiento de entidades sensibles reemplazándolas por tokens semánticos (ej. `[NOMBRE_PII]`, `[CUENTA_BANCARIA]`, `[CLABE_PII]`, `[TELEFONO_PII]`) que preserven la estructura sintáctica de la oración para no degradar el modelo NLP posterior.
  * Limpieza de colas pesadas (filtro de longitud de 2 a 60 palabras según hallazgos del EDA y normalización básica de texto).
  * Escritura en tablas certificadas como *Trusted Data Source (TDS)* en BigQuery y manejo de errores hacia tabla de cuarentena.
* **Entregable Clave:** Pipeline de Apache Beam ejecutable tanto en `DirectRunner` (para pruebas unitarias/locales) como en `DataflowRunner` en GCP, garantizando 0% de fuga de PII en pruebas sintéticas con datos bancarios.

---

### EPIC-5: Core Analítico NLP: Baseline RoBERTa, Arquitectura Dual LoRA (*Delora*) y ABSA

* **Objetivo Técnico:** Implementar el motor de Aprendizaje Automático en `services/ml-delora/` sobre **PyTorch** y **Vertex AI** para desacoplar el ruido de etiquetado (*Label Noise Bias*), calcular el **TNSS**, clasificar tópicos de fallos (**ABSA**) y generar *embeddings* semánticos.
* **Alcance y Componentes:**
  * **Baseline NLP:** Implementación del evaluador base con RoBERTa en español para cuantificar la brecha entre estrellas otorgadas y polaridad textual.
  * **Arquitectura Dual LoRA (*Delora*):** Implementación en PyTorch/HuggingFace PEFT de los dos adaptadores de bajo rango sobre el modelo fundacional: una rama limpia (*Clean Adapter*) para aprender la polaridad real del texto (**TNSS**) y una rama de ruido (*Noisy Adapter*) condicionada a las estrellas (1-5) para absorber y aislar el patrón *Obligatory 5-Star*.
  * **Pipeline ABSA y Severidad:** Clasificador por aspectos (biometría, transferencias SPEI, crashes post-release, bloqueo de cuenta, etc.) y fórmula de priorización ponderada por `votos_utilidad` y `version_app`.
  * **Inferencia, Embeddings y Alertamiento:** Generación de vectores para **Vertex AI Vector Search**, escritura de predicciones en BigQuery y emisión automática de alertas vía Pub/Sub cuando se detecten picos de fallos críticos respaldados por alta tracción comunitaria (votos de utilidad) o alta entropía.
* **Entregable Clave:** Scripts de entrenamiento, evaluación (métricas de *Negative Recall*, eficacia de desacoplamiento y paridad dialectal en español mexicano) y contenedor de inferencia desplegable en Vertex AI Endpoints.

---

### EPIC-6: Exposición, Búsqueda Vectorial, Portal Web HITL y Gobernanza MLOps

* **Objetivo Técnico:** Construir la capa de consumo e interpretabilidad (`services/api-backend/` y `web/hitl-portal/`) para que Product Owners y Program Managers ejecuten el protocolo **Human-In-The-Loop (HITL)**, junto con el monitoreo de *Drift* y la documentación normativa de BBVA.
* **Alcance y Componentes:**
  * **Backend FastAPI (`services/api-backend/`):** Endpoints RESTful para:
    * Consulta del *Satisfaction Gap* (Rating Oficial vs. TNSS) por versión de app y comparativa frente a competidores (Nubank, Santander, Azteca, Banorte).
    * Búsqueda semántica de causa raíz conectada a **Vertex AI Vector Search**.
    * Servicio de explicabilidad local (**SHAP / LIME**) que devuelve mapas de atribución de tokens sobre reseñas individuales.
    * Gestión de la cola de triaje HITL (aprobar, reclasificar o escalar incidencias de alta entropía al backlog de ingeniería).
  * **Frontend React SPA (`web/hitl-portal/`):** Dashboard interactivo con visualización de series de tiempo de *Concept Drift* entre versiones, explorador vectorial de quejas, visor de atribuciones SHAP/LIME y bandeja de validación humana HITL.
  * **MLOps y Gobernanza (`drift_monitor.py` y `docs/governance/`):** Configuración de **Vertex AI Model Monitoring** para detección de *Data Drift* y *Concept Drift* (con disparo de *Fallback Plan* vía Pub/Sub), y redacción completa de la **Data Card**, **Model Card** y **Matriz Ethical FMEA**.
* **Entregable Clave:** API en FastAPI y SPA en React contenerizadas y desplegadas en Cloud Run, monitoreo activo de *Drift* y artefactos de gobernanza listos para auditoría de QA y Compliance.
