# EPIC-7: Portal de consumo, HITL y gobernanza (API y frontal web)

* **Estado (2026-10-22):** Pendiente. **Reescrita el 2026-10-22** con el frontal que definió el autor para P8-12. Era EPIC-6 hasta la reorganización del backlog. La especificación anterior, escrita antes de la evidencia de EPIC-5 (Delora, 768 dimensiones, umbral de entropía 0.65, `ABSATopic`), se conserva en el [anexo B](#anexo-b-especificación-anterior-no-vigente) y no se implementa donde contradice esta versión.
* **Antes de empezar:**
  * aprobar el [registro de decisión de 5.8](../analytics/decision_record.md);
  * tener en operación las tablas y la inferencia de [EPIC-6](epic_6.md).
  * Las decisiones que la condicionan son P8-6 (búsqueda), P8-8 (explicabilidad), P8-9 (*gap* en estrellas), P8-10 (estimaciones), P8-11 (HITL) y P8-12 (alcance), todas en el [registro de decisiones](epic_5.md#decisiones-pendientes).
* **Semanas Objetivo:** tras EPIC-6.
* **Dependencias:**
  * [EPIC-6](epic_6.md): tablas de salida, políticas, curadurías, alertas y monitoreo, según el [esquema v3](../contracts/analytics_outputs_v3_draft.md);
  * EPIC-4: `sanitized_reviews_tds` e `ingestion_runs_log_v2`;
  * EPIC-2: `voc-api-backend` y las cuentas de servicio;
  * 5.9: la lista de incidentes y el análisis por versión.
* **Directorios (provisionales):** `services/api-backend/` (FastAPI), `web/hitl-portal/` (SPA en React, TypeScript y Vite, con la paleta institucional del EDA: azul `#002D72`, verde `#215347`, vino `#7A1A37` y dorado `#B9975B`) y `docs/governance/`.

---

## 🎯 Objetivo

Un portal privado que deje a los equipos de CX, producto y gestión de modelos:
* leer los hallazgos del análisis;
* seguir cada día el sentimiento, el *Satisfaction Gap* y los temas de queja de los cinco bancos;
* investigar reseñas y causas raíz;
* revisar casos HITL sin anclaje;
* atender alertas;
* vigilar el modelo y el pipeline;
* ajustar el apetito de riesgo y la deriva con información a la vista.

La épica no decide modelos ni umbrales: muestra y configura los que fijaron EPIC-5 y EPIC-6.

## 🧭 Principios del frontal

* **Separar agregados de texto.** El reporte y el cockpit muestran solo agregados. Las reseñas se leen en el Explorador y en el HITL, que tienen acceso restringido (7.2).
* **Sin anclaje en la revisión (decisión del autor, 2026-10-22):**
  * la pantalla HITL nunca muestra la explicación (XAI);
  * la muestra de monitoreo (`monitor_sample`) y todo caso que pueda entrar al oro se revisan **a ciegas**, sin la predicción del modelo.
  * Respaldo: en 5.3, anotar viendo la propuesta de Gemini dejó un residuo de anclaje de hasta 2 puntos ([reporte](../analytics/labeling/gold_v0_r2_report.md)).
* **Cada número con su procedencia:** versión de modelo, de política y de guía; intervalo cuando la cifra es una estimación poblacional (PPI, P8-10); aviso cuando es una proporción cruda.
* **Configurar es crear una versión:** ningún cambio de política edita la anterior. Cada cambio registra quién lo hizo (como hash) y por qué.

<a id="mapa-del-portal"></a>

## 🗺️ Mapa del portal y alcance para la presentación (P8-12)

**Decisión del autor (2026-10-22):** el alcance se fija por niveles. Se construye primero lo imprescindible y se agrega lo demás según el tiempo disponible antes de la presentación.

| Sección | Para qué | Rol mínimo | Feature | Nivel |
| :--- | :--- | :--- | :---: | :--- |
| API, datos y despliegue | Endpoints por sección sobre el esquema v3 | — | 7.1 | Imprescindible (lo que pidan las demás) |
| Seguridad y acceso | Portal privado con tres roles | — | 7.2 | Imprescindible |
| Landing y navegación | Menú hacia las secciones, estado de los datos y enlace a gobernanza | Lector | 7.3 | Imprescindible |
| Reporte de hallazgos | Resultados del análisis por secciones, con submenú | Lector | 7.4 | Imprescindible |
| Cockpit diario | KPIs, *gap* en estrellas, sentimiento y temas, con actualización diaria | Lector | 7.5 | Imprescindible; la pestaña por versión, deseable (depende de 5.9) |
| Explorador de reseñas | Tabla con *crossfilter*, búsqueda semántica y ficha con XAI | Analista | 7.6 | Importante |
| HITL | Colas de sentimiento, aspectos y tópicos, con la guía vigente | Revisor | 7.7 | Sentimiento, imprescindible; aspectos y tópicos, deseable |
| Alertas e incidentes | Bandeja de alertas por banco, con su flujo | Analista | 7.8 | Importante |
| MLOps y AIOps | Calidad y deriva del modelo, registro de modelos y salud del pipeline | Analista | 7.9 | Importante |
| Administración | Apetito de riesgo HITL, deriva por banco, historial y oro desde el HITL | Administrador | 7.10 | Imprescindible |
| Gobernanza | Data Card, Model Card y FMEA | — (documentos) | 7.11 | Imprescindible (documentos); la página del portal, deseable |
| Pruebas y *quality gates* | | — | 7.12 | Imprescindible |

---

## 📦 Features

Cada feature se detalla (archivos, firmas y pruebas) al empezar la épica.

### FEATURE 7.1: API, acceso a datos y despliegue

**Objetivo:** el backend FastAPI (`services/api-backend/`) que sirve a todas las secciones con consultas parametrizadas a BigQuery sobre el esquema v3.

* **Una ruta por sección:**
  * `/api/v1/report`
  * `/api/v1/kpis`
  * `/api/v1/reviews` (Explorador y búsqueda)
  * `/api/v1/explanations`
  * `/api/v1/hitl`
  * `/api/v1/alerts`
  * `/api/v1/mlops`
  * `/api/v1/admin`
  * Cada ruta valida el rol (7.2).
* **Costo:** toda consulta de reseñas filtra por la partición de mes (ventana configurable, 12 meses por defecto, como P8-6). El *crossfilter* del Explorador consulta agregados precalculados y pide filas solo al abrir la tabla.
* **Explicaciones bajo pedido (P8-8):** se calculan en un servicio aparte con M4 y 2 GiB, porque M4 no cabe en 1 GiB (5.7) y la API sigue con 1 GiB. Se guardan en `review_explanations` para no repetirlas.
* **Contenedor:** imagen multi-stage sin root, como en EPIC-6.
* **Terminado cuando:** cada pantalla de nivel imprescindible tiene sus rutas con pruebas sin red; ninguna respuesta de rol lector contiene texto de reseñas.

### FEATURE 7.2: Seguridad y acceso

**Objetivo:** el portal es privado y cada rol ve solo lo que necesita.

* **Autenticación:** Identity-Aware Proxy (IAP) delante de Cloud Run, con grupos de Google. No se construye autenticación propia.
* **Roles:**
  * **Lector:** landing, reporte y cockpit; solo agregados.
  * **Analista:** además, Explorador, alertas y MLOps y AIOps; lee texto sanitizado.
  * **Revisor:** las colas HITL que tenga asignadas; lee texto sanitizado.
  * **Administrador:** configuración y versiones del oro.
  * Un usuario puede tener varios roles.
* **Configuración:**
  * cada cambio de `risk_policy` o `drift_policy` exige un motivo y queda versionado;
  * los cambios grandes de cobertura (por ejemplo, más de 5 puntos) piden confirmación explícita en pantalla;
  * queda abierto evaluar un segundo visto bueno.
* **Sin descarga de texto:** la exportación es solo de agregados. Los accesos quedan en Cloud Audit Logs (API y *data access* de BigQuery).
* **FMEA:**
  * el Explorador amplía quién lee reseñas, más allá de los revisores HITL: fila F-15 de la [matriz](../governance/ethical_fmea_matrix.md), con F-01 (nombres que la regex no detecta) como riesgo base;
  * el comentario del revisor ya está considerado en el esquema.
* **Terminado cuando:** un usuario sin rol no ve nada; un lector no puede pedir texto ni por la API; cada cambio de configuración aparece en el historial (7.10).

### FEATURE 7.3: Landing, navegación y gobernanza

* **Landing:**
  * menú hacia todas las secciones que permita el rol;
  * frescura de los datos: última ingesta (`ingestion_runs_log_v2`) y última inferencia (`inference_runs`);
  * alertas abiertas (7.8);
  * una línea por KPI principal.
* **Navegación común:** filtros globales de banco y periodo que se conservan entre secciones, glosario y ayuda contextual en cada métrica.
* **Página de gobernanza** (deseable): Data Card, Model Card y FMEA de 7.11, con los límites declarados (licencia no comercial de `pysentimiento`, tasa de nombres de F-01, el riesgo del corpus en Kaggle de F-14).

### FEATURE 7.4: Reporte de hallazgos

**Objetivo:** el informe de los resultados del análisis (EPIC-5), con un submenú por sección. Es una **foto versionada**: se publica por versión (fecha y commit) a partir de los reportes y JSON de `docs/analytics/`, y no cambia con la operación diaria.

* **Secciones propuestas** (siguen la [historia de los resultados](../analytics/README.md)):
  1. datos y EDA;
  2. etiquetado (oro y plata);
  3. competencia de modelos y evaluación en el oro *test*;
  4. calibración y HITL;
  5. estimaciones con PPI y *Satisfaction Gap* por banco;
  6. familias, tópicos e incidentes;
  7. escala y monitoreo;
  8. decisiones y límites.
* Cada gráfica trae "cómo leerla" e intervalo cuando corresponde. Solo agregados y ejemplos sintéticos, como `docs/`.
* **Terminado cuando:** el reporte publica la versión vigente de `docs/analytics/` y cada cifra enlaza a su JSON de métricas.

### FEATURE 7.5: Cockpit diario de KPIs

**Objetivo:** el seguimiento diario de los cinco bancos. Se actualiza con el delta diario de EPIC-6.

* **Tarjetas:**
  * *Satisfaction Gap* en estrellas por banco (P8-9: estrellas menos el puntaje 1/3/5 del texto) con su intervalo PPI;
  * proporción de `NEG` y su tendencia;
  * quejas con 4–5★;
  * alertas abiertas.
* **Gráficas interactivas:**
  * serie diaria de sentimiento y de *gap* por banco (proporciones crudas, P8-10, rotuladas como tales);
  * KPIs por banco y periodo con PPI e intervalo;
  * volumen de negativas por familia y marca `u`, en nivel y en anomalía (priorización de 5.6);
  * tópicos vigentes con su tendencia;
  * matriz 3 × 3 estrellas × texto como desglose del *gap*;
  * comparación entre bancos.
* **Pestaña por versión de la app** (deseable, depende de 5.9): negativas por `version_app` y familias que cambian tras un *release*.
* **Interacción:** las gráficas se filtran entre sí (*crossfilter*) por banco, periodo, familia y sentimiento. Desde cualquier gráfica, un analista puede abrir el Explorador con el mismo filtro.
* **Terminado cuando:** las tarjetas y las series se recalculan con cada delta; cada cifra muestra su versión de modelo y si es cruda o PPI.

### FEATURE 7.6: Explorador de reseñas (tabla, búsqueda semántica y XAI)

**Objetivo:** investigar reseñas y causas raíz. Es la única sección, aparte del HITL, que muestra texto (rol analista).

* **Tabla interactiva:** reseñas sanitizadas con banco, fecha, versión, estrellas, sentimiento y probabilidades, familias, marcas `u` y `s`, tópico y si pasó por HITL. Se filtra con las gráficas de la sección (*crossfilter*) y con los filtros que llegan del cockpit.
* **Búsqueda semántica (P8-6):** `VECTOR_SEARCH` de BigQuery sobre `text_embeddings` (MiniLM, 384), acotada a la ventana de meses configurable. Los resultados se cargan en la tabla.
* **Ficha de la reseña:**
  * texto, predicción, probabilidades calibradas, familias y tópico;
  * **la explicación por oclusión** (XAI, P8-8), con las palabras que empujan hacia `NEG` en vino y hacia `POS` en verde;
  * la explicación viene precalculada para los casos que pasaron por HITL; para el resto se calcula bajo pedido.
  * La XAI **vive aquí y no en el HITL**, para no anclar al revisor (decisión del autor, 2026-10-22).
* **Límite de la explicación:** la atribución dice qué palabras movieron la predicción del modelo, no la causa técnica del fallo.
* **Terminado cuando:** la tabla responde a los filtros dentro del costo de la ventana; la búsqueda devuelve vecinos con su distancia; la ficha muestra la explicación con su versión de modelo.

### FEATURE 7.7: HITL de sentimiento, aspectos y tópicos

**Objetivo:** los equivalentes de los prototipos de Streamlit de EPIC-5, con la cola visible de inmediato.

| Prototipo (EPIC-5) | Cola en el portal | Nivel |
| :--- | :--- | :--- |
| `annotation/app.py` (5.3): sentimiento, `menciona_falla` y duda | Sentimiento | Imprescindible |
| `eda/aspects_app.py` y `eda/aspects_v2_app.py` (5.2): familias `v2.1` y marcas `u` y `s` | Aspectos | Deseable |
| Fichas y CSV de `data/topics/phase4_v0/` (5.5): revisión trimestral | Tópicos | Deseable |

* **Entrada:** la lista de casos pendientes del revisor se ve al entrar, con un submenú por tipo de HITL. Muestra el avance (pendientes de la semana, hechos y tiempo medio por caso).
* **Guía vigente a la vista:**
  * la versión de la guía de cada tarea (`guidelines`) se muestra junto al caso;
  * cada revisión guarda la versión con la que se hizo.
* **Modo ciego y asistido (`display_mode`):**
  * `monitor_sample`, la doble revisión y todo caso que pueda entrar al oro van **a ciegas**, sin la predicción;
  * la cola por baja confianza puede ir asistida, mostrando la predicción, para ser más rápida;
  * el modo se guarda en cada revisión;
  * la XAI nunca se muestra en esta pantalla.
* **Opciones de respuesta:** etiqueta, marcas (`menciona_falla`, `duda`, `no_evaluable`, `nombre_persona`), saltar, comentario sanitizado y ticket opcional.
* **Doble revisión:** una muestra de casos va a dos revisores (`reason = 'agreement_sample'`), para medir el acuerdo entre personas.
* **Terminado cuando:** cada cola reproduce el flujo de su prototipo, escribe en `hitl_reviews` (o en las curadurías de tópicos de EPIC-6) con su modo y su guía, y la muestra de monitoreo nunca muestra la predicción.

### FEATURE 7.8: Alertas e incidentes

**Objetivo:** atender las alertas de negocio. Son distintas de las de MLOps: aquí se pregunta si el banco tiene un problema, no si el modelo se degradó.

* **Bandeja de `incident_alerts` por banco:** picos de negativas por familia, marca `u` y deriva de la `drift_policy` del banco. Cada alerta muestra su serie, su umbral, la subida HITL que disparó (`hitl_boosts`) y un enlace al Explorador con el filtro de la alerta.
* **Flujo:**
  * cada alerta pasa por `open`, `confirmed` o `dismissed`;
  * cada transición queda en `incident_alert_events`, con quién (como hash), cuándo, nota y ticket;
  * las confirmadas forman la lista de incidentes que usa 5.9 (P9-1) para fijar los umbrales.
* **Terminado cuando:** una alerta nueva aparece en la bandeja y en la landing, y su confirmación queda auditada.

### FEATURE 7.9: MLOps y AIOps

**Objetivo:** vigilar el modelo, las familias y el pipeline (lo que mide 6.4).

* **Modelo:**
  * κ trimestral de M4 en `monitor_sample` contra el piso de reentrenamiento;
  * tasa de corrección de la cola HITL y acuerdo M4–Gemini contra sus avisos (P7-10);
  * curva de cobertura y riesgo vigente.
  * Todo sale de `model_quality` y `hitl_coverage_curves`.
* **Familias:** las revalidaciones de P7-11, con acuerdo exacto e IC por familia.
* **Deriva de entrada y de predicción:** `drift_metrics` por banco y mes, con z o PSI contra el umbral de la `drift_policy` del banco.
* **Registro de modelos:** versión promovida, candidatos, promociones y *rollbacks* (`model_versions`), y *re-scorings* (P7-4).
* **Salud del pipeline (AIOps):**
  * corridas de ingesta e inferencia (estado, duración, filas, costo);
  * frescura de los datos;
  * proporción de reseñas no predecibles por motivo de elegibilidad.
* **Terminado cuando:** cada señal de 6.4 tiene su gráfica con el umbral vigente y el estado (`ok`, `warning`, `retrain`).

### FEATURE 7.10: Administración y configuración

**Objetivo:** ajustar el apetito de riesgo y la deriva como decisiones informadas. Reemplaza a la tarea B.7.2 del anexo.

* **Apetito de riesgo HITL (`risk_policy`, global):**
  * la curva de cobertura y riesgo del modelo vigente (`hitl_coverage_curves`), con el punto vigente marcado;
  * para cada cobertura: error esperado entre lo aceptado, errores atrapados, revisiones por semana y minutos estimados con el tiempo medido (`seconds_spent`);
  * la cobertura objetivo (90 % por defecto, 5.6);
  * los parámetros de reacción a la deriva, de monitoreo y de reentrenamiento (P7-6, P7-7, P7-10 y P7-11).
  * Muestra también las subidas activas por banco (`hitl_boosts`).
* **Deriva por banco (`drift_policy`):** umbrales por serie y regla de entrada, con la tasa histórica de alerta que daría cada umbral (5.7) y la diferencia contra la plantilla.
* **Ayuda en cada parámetro:** qué significa, qué decisión de EPIC-5 lo fijó y qué pasa si se sube o se baja, con la gráfica o la tabla que lo respalda.
* **Historial:** todas las versiones de cada política, con quién (como hash), cuándo y motivo. Se puede comparar una versión con otra.
* **Oro desde el HITL (`gold_versions`):** crear una versión del oro a partir de las revisiones a ciegas de `monitor_sample` y ver sus ítems, para el reentrenamiento.
* **Rutas:** `GET /api/v1/admin/risk-policy`, `GET /api/v1/admin/coverage-curve`, `POST /api/v1/admin/risk-policy` y sus equivalentes para `drift_policy`.
* **Terminado cuando:** un cambio crea una versión nueva y auditada; la siguiente corrida de inferencia usa la política nueva.

### FEATURE 7.11: Artefactos de gobernanza (`docs/governance/`)

* **Data Card:** origen, TDS, sanitización (regex local, sin Cloud DLP por defecto, F-01), reglas de elegibilidad `v1`, sin filtro de longitud.
* **Model Card:**
  * M4 RoBERTuito ajustado con la plata, calibrado con T;
  * métricas en el oro *test* (P8-1);
  * HITL por cobertura;
  * límites: licencia no comercial y la brecha de `NEU` frente a Gemini.
* **FMEA:** filas vigentes, incluidas F-13 a F-15.
* La lista de límites sale del tema 11 del [registro de decisión](../analytics/decision_record.md).
* **Terminado cuando:** los tres documentos reflejan lo decidido en EPIC-5 y no queda texto de la especificación anterior (Delora, 0.65, paridad dialectal sintética).

### FEATURE 7.12: Pruebas y *quality gates*

* **Pruebas de la API sin red** (`TestClient` y *mocks* de BigQuery):
  * roles y ausencia de texto para el lector;
  * cálculo del *gap* en estrellas e intervalos;
  * filtros del Explorador y de la búsqueda;
  * modo ciego del HITL (la predicción no viaja en `monitor_sample`);
  * versionado de políticas;
  * hash del revisor.
* **Portal:** `npm run build` sin errores de TypeScript.
* **Monorepo:** `ruff`, `pyrefly`, `bandit` y `pytest` con cobertura ≥ 85 %.

---

## ✅ Checklist de Aceptación de la Épica 7

* [ ] Portal privado con IAP y tres roles; ningún lector recibe texto de reseñas (7.2).
* [ ] Landing, reporte versionado y cockpit diario con el *gap* en estrellas y sus intervalos (7.3 a 7.5).
* [ ] HITL de sentimiento con la cola visible, la guía vigente y el modo ciego para `monitor_sample`; sin XAI en la pantalla de revisión (7.7).
* [ ] Configuración de `risk_policy` y `drift_policy` versionada, con su curva y su ayuda, y usada por la siguiente corrida (7.10).
* [ ] Lo de nivel importante y deseable que entre en el tiempo: Explorador con XAI y búsqueda (7.6), alertas (7.8), MLOps y AIOps (7.9), HITL de aspectos y tópicos (7.7) y pestaña por versión (7.5).
* [ ] Data Card, Model Card y FMEA actualizadas (7.11).
* [ ] *Quality gates* y `npm run build` sin errores (7.12).

---

## Anexo B: especificación anterior (no vigente)

> Es la versión de esta épica anterior a la reescritura del 2026-10-22, escrita antes de la evidencia de EPIC-5. Se conserva por trazabilidad. Sus features se renombraron de 7.1–7.7 a B.1–B.7 para no confundirlas con las vigentes. **No se implementa** lo que contradiga lo anterior: Delora y `tnss_numeric_calibrated`, los 8 `ABSATopic`, la búsqueda de 768 dimensiones, el explicador de < 150 ms dentro del HITL, el umbral de entropía 0.65, el ranking por `priority_weight_score` y `hitl_triage_audit_log`.

### B.0: Objetivo y límites de la garantía

Construir la capa de consumo analítico, explicabilidad e intervención humana (**HITL**) que permite a los equipos de *Client Solutions*, *Customer Experience (CX)*, *Program Managers* y *Product Owners* explorar la brecha de satisfacción real (**Satisfaction Gap**: Rating Oficial vs. **TNSS**), buscar causas raíz semánticamente mediante *embeddings* de 768 dimensiones, inspeccionar mapas de atribución de tokens (**SHAP / LIME**), auditar y reclasificar predicciones de alta entropía hacia el backlog de ingeniería, mostrar las alertas de *drift* que emite EPIC-6, y entregar la documentación normativa alineada a los estándares de BBVA *Norma Data Governance* y *Norma de Gobierno de Modelos de Analítica Avanzada*.

* **Límite de Explicabilidad Local:** Los valores de atribución por token (SHAP/LIME/oclusión de perturbación) explican qué palabras o tokens DLP (`ref: 3702`, `[MX_CLABE_BANCARIA]`, `"pantalla azul"`) empujaron la predicción local del modelo hacia `NEG` o hacia un `ABSATopic` específico, pero no constituyen prueba de causalidad técnica en el código fuente móvil el cual debe correlacionarse con telemetría APM en sistemas de ingeniería.
* **Agencia Humana (HITL):** Ninguna predicción con `requires_hitl = True` (`prediction_entropy >= 0.65` o sesgo *Obligatory 5-Star* de alto impacto) modifica automáticamente prioridades definitivas sin registrar un `HitlTriageAuditRecord` firmado por un revisor humano autenticado (almacenando únicamente `reviewer_email_hash` SHA-256 para cumplir con minimización de PII).


### B.0b: Alineación con contratos e infraestructura (EPIC-1 a EPIC-6)

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


### B.0c: Decisiones heredadas de 5.5 y 5.6 (2026-10-22)

El autor aprobó la recomendación híbrida de 5.5 ([nota de decisión](../analytics/topics/topics_decision_note.md)) y las decisiones de 5.6 ([reporte](../analytics/calibration/calibration_report.md)). Donde el texto original de esta épica la contradice, se conserva para trazabilidad y rige lo siguiente:

| Texto original de EPIC-7 | Decisión heredada de 5.5 | Se fija en |
| :--- | :--- | :--- |
| Taxonomía de los 8 `ABSATopic` (ranking de backlog, `predicted_topic`, `validated_topic`, filtros) | Núcleo: las 11 familias multi-etiqueta de `aspects_v2_1` más las marcas `u` y `s`; una reseña puede tener varias familias. Los tópicos de BERTopic son una capa de detalle aparte, con versión y curada. | 7.1 a 7.4 al implementarlas; contratos de `voc_common` en EPIC-6 (6.1) |
| `embedding_vector` de 768 dimensiones del modelo Delora (búsqueda semántica) | 5.4 descartó Delora (M8); los tópicos usan MiniLM (384 dimensiones). La búsqueda semántica debe decidir su encoder. | 5.8 (P8-6); columna en EPIC-6 (6.2) |
| *Concept drift* con JSD de la distribución de los 8 tópicos por versión | Proporción de las familias y de la marca `u`, que se adelantó a los incidentes de BBVA. | Umbrales en 5.7; monitor en EPIC-6 (6.4) |
| Umbral HITL `prediction_entropy >= 0.65` fijado a priori | Decidido en 5.6: probabilidad máxima calibrada con 90 % de cobertura por defecto, configurable desde el portal (B.7.2). | 5.6 (decidido) |
| *Satisfaction Gap* como estrellas menos `tnss_numeric_calibrated` (7.1, 7.4, 7.6) | `tnss_numeric_calibrated` se descartó en 5.6; PPI ya da proporciones con intervalo por banco. | 5.8 (P8-9, P8-10) |
| Explicador de < 150 ms en 1 vCPU (7.2) | M4 hace 39–53 textos/s en CPU, y la oclusión necesita una pasada por token. | 5.8 (P8-8) |
| Ranking del backlog por `SUM(priority_weight_score)` y `SUM(votos_utilidad)` (7.1) | Decidido en 5.6: volumen de negativas por familia y marca `u`, en nivel y en anomalía; los votos se muestran como contexto, no como peso. | 5.6 (decidido) |



### B.1: Configuración del Paquete `api-backend` y Servicio Analítico/Vectorial en BigQuery (`bq_vector_and_analytics.py`)

**Objetivo:** Configurar el microservicio FastAPI dentro del workspace de `uv` e implementar las consultas parametrizadas a BigQuery para KPIs ejecutivos (*Satisfaction Gap*, evolución por versión y comparación competitiva frente a Nubank, Santander, Azteca y Banorte) y búsqueda semántica de causa raíz.

#### Tarea B.1.1: Configurar `services/api-backend/pyproject.toml`

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

#### Tarea B.1.2: Implementar Consultas de KPIs y Búsqueda Semántica en `bq_vector_and_analytics.py`

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


### B.2: Motor de Explicabilidad Local (SHAP / LIME Token Attribution) y Servicio HITL (`explainability.py`, `hitl_service.py`)

**Objetivo:** Dotar a los analistas de CX y Product Owners de mapas de atribución de palabras sobre cualquier reseña individual y gestionar la bandeja de validación humana HITL con persistencia auditada en `bbva_voc_tds.hitl_triage_audit_log`.

#### Tarea B.2.1: Implementar `LocalTokenAttributionExplainer` en `explainability.py`

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

#### Tarea B.2.2: Implementar `HitlTriageService` en `hitl_service.py`

1. **`list_pending_hitl_reviews(self, bank_id: BankKey | None = None, limit: int = 50) -> list[HitlQueueItem]`**:

* Consulta en BigQuery las reseñas donde `p.requires_hitl = TRUE` que aún **no** tengan un registro en `hitl_triage_audit_log`, ordenadas por `p.priority_weight_score DESC, p.prediction_entropy DESC`.

1. **`submit_human_validation(self, request: HitlDecisionRequest) -> HitlTriageAuditRecord`**:

* Recibe la decisión del usuario humano (`id_resena`, `bank_id`, `validated_tnss: SentimentLabel`, `validated_topic: ABSATopic`, `reviewer_email: str`, `backlog_jira_ticket: str | None`).
* Aplica inmediatamente `hash_username_pii(request.reviewer_email, settings.user_hash_salt)` de `voc-common` para obtener `reviewer_email_hash` (jamás guarda el email en texto plano en BigQuery).

* Construye y valida `HitlTriageAuditRecord` (EPIC-1 Feature 1.3.5) y lo persiste en `bbva_voc_tds.hitl_triage_audit_log`.


### B.3: Rutas RESTful en FastAPI y Contenedor Docker (`routes.py`, `main.py`, `Dockerfile`)

**Objetivo:** Exponer la API de alto rendimiento con validación estricta Pydantic, CORS configurado para la SPA en React y empaquetado Docker seguro.

#### Tarea B.3.1: Implementar Endpoints en `routes.py` y `main.py`

Exponer bajo el prefijo `/api/v1`:

1. `GET /health`: Estado de salud del servicio `api-backend`.
2. `GET /api/v1/analytics/satisfaction-gap`: Devuelve `SatisfactionGapReport` (filtrable por `bank_id` y `days_window`).

3. `GET /api/v1/analytics/version-drift`: Devuelve la evolución temporal de quejas por `version_app`.

4. `GET /api/v1/analytics/backlog-ranking`: Devuelve el ranking de tópicos `ABSATopic` ponderado por severidad y votos de utilidad.

5. `POST /api/v1/search/semantic`: Recibe una consulta en lenguaje natural (`query_text: str`, `bank_id`, `topico`, `top_k`), genera su vector de 768 dimensiones y retorna los `SemanticSearchHit` más cercanos.

6. `GET /api/v1/reviews/{bank_id}/{id_resena}/explanation`: Devuelve `ReviewExplanationResponse` con el mapa de atribución de tokens SHAP/LIME.

7. `GET /api/v1/hitl/queue`: Lista las reseñas pendientes de validación humana (`requires_hitl = True`).

8. `POST /api/v1/hitl/validate`: Registra la decisión humana y devuelve el `HitlTriageAuditRecord` confirmado.

#### Tarea B.3.2: Implementar `services/api-backend/Dockerfile`

Construir `Dockerfile` multi-stage con `ghcr.io/astral-sh/uv:python3.11-bookworm-slim`, usuario no-root `appuser`, instalando `voc-common` y `api-backend` desde `uv.lock`, exponiendo el puerto `8080` con `uvicorn api_backend.main:app --host 0.0.0.0 --port 8080`.


### B.4: Portal Interactivo React SPA para Triaje HITL (`web/hitl-portal/`)

**Objetivo:** Desarrollar la Single Page Application (React + TypeScript + Vite) utilizando la paleta institucional definida en el notebook del EDA (`Azul: #002D72`, `Verde: #215347`, `Vino: #7A1A37`, `Dorado: #B9975B`) para que los stakeholders naveguen por las incidencias y ejecuten el protocolo HITL.

#### Tarea B.4.1: Implementar los 3 Módulos Visuales en `web/hitl-portal/src/`

1. **`SatisfactionGapDashboard.tsx`:**

* Tarjetas ejecutivas mostrando el Rating Oficial Inercial vs. **TNSS Recalibrado**, el *Satisfaction Gap*, el porcentaje de *Obligatory 5-Star* detectado, la comparativa frente a `NUBANK`, `SANTANDER`, `AZTECA` y `BANORTE`, y el gráfico apilado de quejas por `version_app`.

1. **`VectorRootCauseExplorer.tsx`:**

* Buscador semántico donde el Product Owner escribe una hipótesis de fallo (ej. *"bloqueo por antivirus o accesibilidad código 3702"*), visualiza las reseñas semánticamente más cercanas con sus votos de utilidad y, al hacer clic en una reseña, despliega el **Mapa de Calor de Atribución SHAP/LIME** resaltando en color Vino (`#7A1A37`) los tokens que impulsan la polaridad negativa y en Verde (`#215347`) los positivos.

1. **`HitlTriageQueue.tsx`:**

* Bandeja interactiva que muestra las reseñas con `requires_hitl = True` (alta entropía o alto impacto), permitiendo al revisor confirmar o reclasificar el `tnss_score` (`NEG`/`NEU`/`POS`) y el `ABSATopic`, vincular opcionalmente un ID de ticket de Jira/Backlog y enviar la validación hacia `POST /api/v1/hitl/validate`.


### B.5: Artefactos Normativos de Gobernanza (`docs/governance/`)

**Objetivo:** Redactar los 3 documentos normativos obligatorios para la auditoría de *Data Governance*, *QA Responsible* y *Compliance* de BBVA.

#### Tarea B.5.1: Redactar los 3 Artefactos de Gobernanza en `docs/governance/`

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


### B.6: Suite de Pruebas Unitarias de API, Explicabilidad y HITL (`tests/`)

**Objetivo:** Certificar con `pytest` y `fastapi.testclient.TestClient` (sin requerir conexión a GCP en CI) todos los endpoints del backend, el motor de atribución de tokens y la bitácora HITL. Las pruebas del monitor de *drift* están en EPIC-6.

#### Tarea B.6.1: Implementar `test_api_routes.py` y `test_explainability_and_hitl.py`

Escribir pruebas deterministas que validen:

1. **`test_satisfaction_gap_and_competitor_benchmark_endpoint`**:

* Verificar que `GET /api/v1/analytics/satisfaction-gap` calcule correctamente el diferencial negativo entre el rating oficial (ej. `4.68`) y el TNSS recalibrado (ej. `3.57`, gap `-1.11`) y devuelva la comparativa de los 5 bancos de `BankKey`.

1. **`test_semantic_vector_search_validation_and_ranking`**:

* Comprobar que `POST /api/v1/search/semantic` valide dimensiones (`768`), filtre por `bank_id` y `ABSATopic`, y ordene los resultados por similitud coseno descendente.

1. **`test_token_attribution_explainer_identifies_incident_keywords`**:

* Pasar la reseña `"pésima actualización se traba la pantalla azul y marca error ref: 3702:65c5:9xhchi"` a `LocalTokenAttributionExplainer`. Verificar que los tokens `"pésima"`, `"traba"` y `"ref: 3702:65c5:9xhchi"` reciban los pesos de atribución más altos con dirección `"TOWARDS_NEG_INCIDENT"`.

1. **`test_hitl_validation_hashes_reviewer_email_and_creates_audit_record`**:

* Enviar una decisión humana a `POST /api/v1/hitl/validate` con `reviewer_email="claudia.martinez@bbva.com"`. Comprobar que el `HitlTriageAuditRecord` insertado en `hitl_triage_audit_log` contenga un `reviewer_email_hash` SHA-256 de 64 caracteres, nunca el email en texto plano, y que refleje el cambio de tópico/TNSS validado.


### B.7: Frontales de Curaduría HITL (agregado del autor, 2026-10-22)

**Decisión del autor:** todos los aplicativos de curaduría desarrollados en EPIC-5 (sentimiento y tópicos) pertenecen también al frontal de EPIC-7. La base de datos que guarda las curadurías para el reentrenamiento se diseña en [EPIC-6](epic_6.md) (feature 6.2). Insumo: sección final de la [nota de decisión](../analytics/topics/topics_decision_note.md).

#### Tarea B.7.1: Frontales de curaduría en `web/hitl-portal/`

| Prototipo actual (local, EPIC-5) | Pantalla en el portal |
| :--- | :--- |
| `annotation/app.py` (Streamlit, 5.3): etiqueta de sentimiento, `menciona_falla`, duda | Cola de sentimiento (`HitlTriageQueue`) |
| `eda/aspects_app.py` y `eda/aspects_v2_app.py` (Streamlit, 5.2): familias `v2.1`, marcas `u` y `s` | Codificación de aspectos (nueva) |
| Fichas y CSV de `data/topics/phase4_v0/` (5.5) | Curaduría de tópicos en la revisión trimestral de la fase 4 (nueva) |

* Criterio de terminado: cada pantalla reproduce el flujo del prototipo, escribe en la base de curadurías de EPIC-6 (6.2) y muestra solo texto sanitizado.

#### Tarea B.7.2: Configuración de la política HITL (agregado del autor, 2026-10-22)

La cobertura de la revisión humana es una decisión informada, no un número fijo. La pantalla de la cola HITL muestra:

* la curva de cobertura y riesgo del modelo vigente (`hitl_coverage_curves` de EPIC-6), con el punto de la política vigente marcado;
* para cada cobertura: el error esperado entre lo aceptado, los errores que caen en revisión, las revisiones por semana y los minutos estimados, con el volumen y el tiempo por revisión medidos;
* el parámetro configurable de la **política HITL global** (cobertura objetivo; 90 % por defecto, decidido en 5.6), con las subidas temporales activas por banco (`hitl_boosts`);
* aparte, la **configuración de alertas de deriva de cada banco** (`drift_policy`: umbrales por serie y regla de entrada), con la tasa histórica de alerta que daría cada umbral.

Cambiar un parámetro **crea una versión nueva** de `risk_policy` (global) o de la `drift_policy` del banco (solo inserción, con revisor como hash y motivo) y nunca edita la anterior. La API expone `GET /api/v1/hitl/policy`, `GET /api/v1/hitl/coverage-curve` y `POST /api/v1/hitl/policy`.

* Criterio de terminado: la curva se ve con el punto vigente; el cambio de parámetro queda versionado y auditado; la siguiente corrida de inferencia usa la política nueva.


### Checklist anterior (no vigente)

* [ ] `api-backend` expone los endpoints de KPIs (*Satisfaction Gap*), series de tiempo por versión, búsqueda vectorial de 768 dimensiones, explicabilidad SHAP/LIME y cola de validación HITL.

* [ ] Las decisiones humanas del protocolo HITL se registran de forma inmutable en `bbva_voc_tds.hitl_triage_audit_log` usando `HitlTriageAuditRecord` con el correo del revisor hasheado con SHA-256.

* [ ] El portal muestra las alertas de *drift* de EPIC-6 (6.4).

* [ ] Los 3 artefactos de gobernanza (`data_card.md`, `model_card.md` y `ethical_fmea_matrix.md`) están redactados y completos en `docs/governance/`.

* [ ] El portal web en `web/hitl-portal/` compila sin errores de TypeScript (`npm run build`).
* [ ] Todos los *Quality Gates* del monorepo (`uv run ruff check .`, `uv run ruff format --check .`, `uv run pyrefly check`, `uv run bandit -c pyproject.toml -r .` y `uv run pytest --cov-fail-under=85`) pasan con **0 errores**.

* [ ] Los frontales de curaduría de sentimiento, aspectos y tópicos están en el portal y escriben en la base de curadurías para el reentrenamiento (7.7).
* [ ] La cola HITL muestra la curva de cobertura y riesgo con su costo estimado y permite cambiar la cobertura, que queda versionada (B.7.2).
