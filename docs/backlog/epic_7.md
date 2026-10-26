# EPIC-7: Portal de consumo, HITL y gobernanza (API y frontal web)

* **Estado (2026-10-25):** **Planificada; lista para ejecutar.** El detalle de cada feature (rutas, firmas, consultas, pantallas, pruebas y criterio de terminado) está en [`epic_7/`](epic_7/README.md), un archivo por paso **en orden de ejecución**. Lo que falta para empezar es la [feature 7.0](epic_7/00_preparacion.md); terminar EPIC-6 no es requisito.
* **Historia:**
  * reescrita el 2026-10-22 con el frontal que definió el autor para P8-12; la especificación anterior está en el [anexo B](epic_7/anexo_b_no_vigente.md) y no se implementa;
  * acotada el mismo día al acotar 5.9 a lo descriptivo: 7.8 pasa a alertas de deriva y el cockpit muestra el top 5 diario de temas;
  * planificada el 2026-10-25: feature 7.0, [guía visual](../design/visual_guide.md), [stack y arquitectura](../design/frontend_stack.md), [cuestionario de diseño](epic_7/design_questions.md) y la tesis al final con prioridad mínima.
* **Dependencias:**
  * [EPIC-6](epic_6.md): tablas de salida, políticas, curadurías, alertas y monitoreo, según el [esquema v3](../contracts/analytics_outputs_v3.md); todo cargado y validado en dev, con el delta y el monitor corriendo solos (6.6, cerrada el 2026-10-26);
  * EPIC-4: `sanitized_reviews_tds` e `ingestion_runs_log_v2`;
  * 5.9: el top 5 diario de temas (`daily_topic_labels`) y la vista por versión;
  * el [registro de decisión de 5.8](../analytics/decision_record.md), aprobado el 2026-10-22. Las decisiones que la condicionan son P8-6 (búsqueda), P8-8 (explicabilidad), P8-9 (*gap* en estrellas), P8-10 (estimaciones), P8-11 (HITL) y P8-12 (alcance), todas en el [registro de decisiones](epic_5.md#decisiones-pendientes).
* **Directorios:**
  * `services/api-backend/`: FastAPI, que también sirve el portal;
  * `web/portal/`: SPA en React, TypeScript y Vite;
  * `services/ml-inference/` (comando `serve` y servicio `voc-ml-online`, paso 6);
  * `infra/`, `docs/design/`, `docs/governance/` y `docs/thesis/` (paso 12).

---

## 🎯 Objetivo

Un portal privado que deje a los equipos de CX, producto y gestión de modelos:

* leer los hallazgos del análisis;
* seguir cada día el sentimiento, el *Satisfaction Gap* y los temas de queja de los cinco bancos;
* investigar reseñas y causas raíz;
* revisar casos HITL sin anclaje;
* atender las alertas de deriva del modelo;
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
* **Marca de Posgrados (decisión del autor, 2026-10-25):** verde `#00685E` y dorado `#BA9357`, sin el azul de Preparatoria ni el vino de Licenciatura; las gráficas tienen su propia paleta de datos ([guía visual](../design/visual_guide.md)).

<a id="mapa-del-portal"></a>

## 🗺️ Mapa del portal y alcance para la presentación (P8-12)

**Decisión del autor (2026-10-22):** el alcance se fija por niveles. Se construye primero lo imprescindible y se agrega lo demás según el tiempo disponible antes de la presentación. **Decisión del autor (2026-10-25):** la tesis (7.4) va al final del backlog con la prioridad más baja, para que los tokens se gasten primero en funcionalidad.

| Sección | Para qué | Rol mínimo | Feature | Nivel | Paso |
| :--- | :--- | :--- | :---: | :--- | :-: |
| Preparación | Bloqueantes y decisiones para empezar | — | 7.0 | Imprescindible | [0](epic_7/00_preparacion.md) |
| API, datos y despliegue | Endpoints por sección sobre el esquema v3 | — | 7.1 | Imprescindible (lo que pidan las demás) | [1](epic_7/01_api_y_acceso.md) |
| Seguridad y acceso | Portal privado con cuatro roles | — | 7.2 | Imprescindible | [1](epic_7/01_api_y_acceso.md) |
| Landing y navegación | Menú hacia las secciones, estado de los datos y enlace a gobernanza | Lector | 7.3 | Imprescindible | [2](epic_7/02_portal_base_y_landing.md) |
| Cockpit diario | KPIs, *gap* en estrellas, sentimiento y temas, con actualización diaria | Lector | 7.5 | Imprescindible; la pestaña por versión, importante | [3](epic_7/03_cockpit.md) |
| HITL de sentimiento | Cola con la guía vigente y el modo ciego | Revisor | 7.7 | Imprescindible | [4](epic_7/04_hitl_sentimiento.md) |
| Administración | Apetito de riesgo HITL, deriva por banco, historial y oro desde el HITL | Administrador | 7.10 | Imprescindible | [5](epic_7/05_administracion.md) |
| Explorador de reseñas | Tabla con *crossfilter*, búsqueda semántica y ficha con XAI | Analista | 7.6 | Importante | [6](epic_7/06_explorador.md) |
| Alertas de deriva | Bandeja de alertas de deriva por banco, con su flujo | Analista | 7.8 | Importante | [7](epic_7/07_alertas_deriva.md) |
| MLOps y AIOps | Calidad y deriva del modelo, registro de modelos, acciones y salud del pipeline | Analista (acciones: administrador) | 7.9 | Importante | [8](epic_7/08_mlops_aiops.md) |
| HITL de aspectos y tópicos | Codificación de familias y curaduría de tópicos | Revisor | 7.7 | Deseable | [9](epic_7/09_hitl_aspectos_topicos.md) |
| Gobernanza | Data Card, Model Card y FMEA | — (documentos) | 7.11 | Imprescindible (documentos); la página del portal, deseable | [10](epic_7/10_gobernanza.md) |
| Pruebas y *quality gates* | Cierre del portal funcional | — | 7.12 | Imprescindible | [11](epic_7/11_cierre_y_pruebas.md) |
| Reporte de la tesis | La tesis redactada, por capítulos, con gráficas generadas de los JSON de métricas | Lector | 7.4 | **Prioridad mínima** | [12](epic_7/12_reporte_tesis.md) |

**Si el tiempo no alcanza,** se recorta en este orden: la tesis, el HITL de aspectos y tópicos, la pestaña por versión y las partes de los pasos 6 a 8 que elija el autor.

---

## 🏗️ Arquitectura en una línea

Un servicio de Cloud Run (`voc-api-backend`) detrás de IAP sirve la API y el portal; los roles salen de un mapa cifrado en Pulumi; lo que necesita PyTorch (explicación bajo pedido y embedding de la consulta) corre en un servicio privado aparte (`voc-ml-online`); las acciones sobre el modelo lanzan los Jobs de EPIC-6. Detalle en [`frontend_stack.md`](../design/frontend_stack.md).

---

## ✅ Checklist de Aceptación de la Épica 7

* [ ] Portal privado con IAP y cuatro roles (lector, analista, revisor, administrador); ningún lector recibe texto de reseñas (7.2).
* [ ] Landing y cockpit diario con el *gap* en estrellas y sus intervalos (7.3 y 7.5).
* [ ] HITL de sentimiento con la cola visible, la guía vigente y el modo ciego para `monitor_sample`; sin XAI en la pantalla de revisión (7.7).
* [ ] Configuración de `risk_policy` y `drift_policy` versionada, con su curva y su ayuda, y usada por la siguiente corrida (7.10).
* [ ] Lo de nivel importante y deseable que entre en el tiempo: Explorador con XAI y búsqueda (7.6), alertas de deriva (7.8), MLOps y AIOps (7.9), pestaña por versión (7.5) y, de nivel deseable, HITL de aspectos y tópicos (7.7).
* [ ] Data Card, Model Card y FMEA actualizadas (7.11).
* [ ] *Quality gates* y `npm run build` sin errores (7.12).
* [ ] Reporte de la tesis versionado, con los bancos anonimizados (7.4, prioridad mínima).
