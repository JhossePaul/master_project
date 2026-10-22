# Registro de decisión de EPIC-5 (5.8)

> **Estado (2026-10-22): borrador para que el autor tome las decisiones de 5.8.** Junta, por tema, lo que ya decidió el autor en 5.1–5.7, lo que falta decidir y la evidencia de cada punto. Cuando todas las filas estén decididas y el oro *test* se haya evaluado, este documento se aprueba, se detalla [EPIC-6](../backlog/epic_6.md) y arranca 5.9. El seguimiento de cada decisión está en el [registro de decisiones de `epic_5.md`](../backlog/epic_5.md#decisiones-pendientes). Índice: [`README.md`](README.md).

## Resumen

| Tema | Estado | IDs |
| :--- | :--- | :--- |
| 1. Modelo de sentimiento | **Pendiente:** falta la evaluación única en el oro *test*; licencia decidida | P8-1, P8-2 |
| 2. Limpieza y elegibilidad | Decidido | P8-3, P8-4 |
| 3. Tópicos, familias e incidentes | Decidido; los umbrales de la señal pasan a 5.9 | 5.5, P8-7, P9-1 |
| 4. Calibración, HITL y priorización | Decidido | 5.6, P7-6 a P7-8 |
| 5. *Satisfaction Gap* y estimaciones | **Pendiente:** definición del *gap*; estimaciones decididas | P8-9, P8-10 |
| 6. Esquema de salida, HITL y migración | Decidido, con la condición de cubrir el frontal de EPIC-7 | P8-5, P8-11 |
| 7. Búsqueda semántica y explicabilidad | Decidido | P8-6, P8-8 |
| 8. Backfill, operación diaria y ciclo de vida | Decidido | P7-1 a P7-4 |
| 9. Monitoreo de deriva, del modelo y de las familias | Decidido | P7-9 a P7-11 |
| 10. Alcance de EPIC-7 para la presentación | **Pendiente:** depende de lo anterior | P8-12 |
| 11. Límites y riesgos para la Model Card y la FMEA | Por redactar al aprobar | — |

## 1. Modelo de sentimiento (P8-1, P8-2)

| Candidato | κ *dev* aleatorio (n = 794) | κ *dev* dirigido (n = 297) | Costo del backfill | Costo del delta | Probabilidades y HITL | Licencia |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **M4 RoBERTuito** (`M4_robertuito_s*_ppi`, con pesos) | 0.917 (3 semillas, 0.912–0.922) | 0.63 | ~9 min de T4 en Kaggle ($0) | ~25 s de CPU al día ($0) | Sí: calibrado (T ≈ 1.7), curva HITL | No comercial (`pysentimiento`) |
| **M9 Gemini** (`prompt_v3`) | 0.93 (0.91–0.96) | — | ~$72 | ~$0.02 al día (500 textos × $0.048 por 1 000) | No: solo etiqueta; la marca `duda` no sirve como señal HITL | Términos de Vertex AI |
| Diferencia M9 − M4 | +0.021 [−0.000, 0.043] | | | | | |

* **Decidido:** se decide con datos: el oro *test* (601 ítems, **una sola evaluación**), el costo y la licencia (P8-1). Para la tesis se acepta RoBERTuito y su licencia no comercial se declara en la Model Card y en la FMEA (P8-2).
* **Falta (acción, no decisión):** evaluar M4 (las 3 semillas `_ppi`, calibradas) y M9 en el oro *test* con el protocolo de 5.4 y reportar κ, F1 por clase y la diferencia pareada con IC. Hoy la brecha de M9 es de ~5 `NEU` de 30 y está por debajo del ruido entre personas (κ 0.81–0.87).
* **Regla propuesta para decidir** (la de 5.4): M9 reemplaza a M4 solo si su diferencia pareada en el *test* excluye el 0 **y** compensa costo, falta de probabilidades y dependencia de un servicio externo. Si no, M4.
* Evidencia: [competencia de modelos](sentiment/sentiment_models_v0_report.md), [calibración](calibration/calibration_report.md), [protocolo](sentiment/sentiment_models_protocol.md).

## 2. Limpieza y elegibilidad (P8-3, P8-4)

* **Decidido:** reglas `eligibility_rules_v1`: corte de NUBANK en 2020-01-01, `TNSS_NOT_SPANISH` descartada, `TNSS_SINGLE_WORD` resuelta con el léxico determinista (151 formas, 95.3 % de cobertura, 99 % de exactitud; las no cubiertas se excluyen, con un sesgo de −0.001 a −0.007 estrellas) y `TOPIC_TOO_SHORT` con k = 1 para tópicos y familias. Sin filtro de longitud; inferencia por texto único.
* **Falta (acción):** publicar `eligibility_rules.md` como `v1` con los conteos por banco × periodo × motivo.
* Evidencia: [reglas](eda/eligibility_rules.md), [EDA §5.3](eda/eda_report.md#53-léxico-determinista-para-reseñas-de-una-palabra), [tópicos §4.3](topics/topics_report.md#43-topic_too_short-k--1-se-confirma-con-v21-y-los-5-bancos).

## 3. Tópicos, familias e incidentes (5.5, P8-7, P9-1)

* **Decidido (5.5):** híbrido: las 11 familias `aspects_v2_1` y las marcas `u` y `s` como núcleo de medición y alerta; los tópicos (BERTopic por cláusulas, MiniLM, HDBSCAN) como capa de detalle curada.
* **Decidido (P8-7):** las familias se etiquetan con Gemini dentro de GCP. Costo medido: $0.091 por 1 000 textos; llenado histórico de ~788 000 negativas únicas, **~$72**.
* **A 5.9:** los umbrales de la señal de incidentes se fijan con la lista de meses candidatos de los 5 bancos que valide el autor (P9-1).
* Evidencia: [reporte de tópicos](topics/topics_report.md), [nota para 5.8](topics/topics_decision_note.md), [costo de las familias](scale/scale_report.md#3-costo-de-las-familias-con-gemini-p8-7).

## 4. Calibración, HITL y priorización (5.6, P7-6 a P7-8)

* **Decidido:** *temperature scaling* por semilla; HITL por probabilidad máxima calibrada con **90 % de cobertura por defecto** (~350 textos por semana, error entre lo aceptado de 0.4 %); priorización por volumen de negativas por familia y marca `u`, en nivel y en anomalía, sin `priority_weight_score` ni votos como peso.
* **Decidido (apetito de riesgo, global):** la cobertura, la muestra humana de monitoreo (P7-7), la frecuencia de re-ajuste de tópicos (P7-8) y los umbrales son **parámetros configurables** de una política versionada; el revisor y el dueño de negocio fijan el riesgo. Las subidas por deriva son automáticas y solo para el banco que alertó (P7-6, `hitl_boosts`), con tope semanal y vuelta a la base.
* Evidencia: [reporte de 5.6](calibration/calibration_report.md).

## 5. *Satisfaction Gap* y estimaciones (P8-9, P8-10)

* **Decidido (P8-10):** proporciones crudas para las series diarias y PPI para los KPI por banco y periodo.
* **Pendiente (P8-9):** cómo se reporta el *gap*. El autor objetó medir una sola dirección. Medido con PPI:

  | Medida (corpus) | Gemini | M4 |
  | :--- | :--- | :--- |
  | Texto más negativo que las estrellas | 10.5 % [9.4, 11.5] | 10.5 % [9.4, 11.7] |
  | Texto más positivo que las estrellas | 0.9 % [0.7, 1.1] | 0.8 % [0.5, 1.1] |
  | Brecha neta ordinal (−2 a +2) | −0.142 [−0.158, −0.126] | −0.138 [−0.154, −0.122] |

  **Propuesta:** reportar la matriz 3 × 3 estrellas × texto y la brecha neta, con su intervalo, por banco y periodo. `tnss_numeric_calibrated` no se evaluó en 5.6; si el autor quiere un puntaje continuo de 1 a 5, se reabre y se evalúa.
* Evidencia: [reporte de 5.6, §3.3](calibration/calibration_report.md#33-satisfaction-gap-simétrico-p8-9-2026-10-22).

## 6. Esquema de salida, HITL y migración (P8-5, P8-11)

* **Decidido (P8-11):** tablas nuevas para el HITL y se elimina `hitl_triage_audit_log`.
* **Decidido (P8-5, 2026-10-22), con una condición:** se aprueba el [esquema v3](../contracts/analytics_outputs_v3_draft.md) con los cambios del autor: `eligibility_code` explícito (`ELEGIBLE` o el código; nulo solo si no se evaluó), `sentiment` con `NO_PREDICTED`, probabilidades nulas solo cuando no hay modelo, y `review_predictions` por reseña con inferencia por texto único en el backfill. La muestra de monitoreo (`hitl_items.reason`) puede entrar al oro por versiones (`gold_versions`) y el revisor puede dejar un comentario sanitizado. **Condición:** que cubra todas las necesidades del frontal de EPIC-7, que se revisa con P8-12.
* La migración no mueve datos: `delora_predictions` y `hitl_triage_audit_log` están vacías.

## 7. Búsqueda semántica y explicabilidad (P8-6, P8-8)

* **Decidido (P8-6):** BigQuery `VECTOR_SEARCH` sobre embeddings MiniLM (384) en una tabla particionada por mes, con ventana configurable de 12 meses: ~2 000 búsquedas al mes en el free tier (cada búsqueda sobre todo el corpus factura 4.26 GB). Sin Vertex Vector Search.
* **Decidido (P8-8):** explicabilidad por oclusión precalculada solo para la cola HITL: ~0.5 s por texto en Cloud Run, ~9 min de CPU por semana.
* Evidencia: [reporte de 5.7, §4, §5 y §5.1](scale/scale_report.md).

## 8. Backfill, operación diaria y ciclo de vida (P7-1 a P7-4)

| Pieza | Decisión | Medido |
| :--- | :--- | :--- |
| Backfill y *re-scoring* | Kaggle T4, con un pipeline desde GCP (exporta de BigQuery, lanza el kernel, carga con `MERGE`); se re-predice todo el histórico al promover un modelo | ~9 min de GPU; ~17 h en Cloud Run con 1 vCPU |
| Delta diario | Cloud Run Job de 1 vCPU y 2 GiB, ordenado por longitud | ~25 s por 500 textos; memoria pico 1.2–1.4 GB |
| Familias del delta | Gemini en GCP | ~$0.03 al día (~285 negativas × $0.091 por 1 000) |
| Registro de modelos | Vertex Model Registry, con alias para promover y regresar | Registro ~160 s por versión; promoción en 3 s |
| Versión de modelo | Pesos fp16 + tokenizador + T + curva HITL + métricas en el oro *dev* | 218 MB por semilla |

* **Riesgo aceptado (P7-1):** se sube el corpus completo de textos sanitizados a un dataset privado de Kaggle. Se declara en la FMEA con la tasa de PII medida (0 nombres en 1 000 aleatorias, F-01). En producción todo quedaría en GCP.
* Evidencia: [reporte de 5.7, §1 y §6](scale/scale_report.md).

## 9. Monitoreo de deriva, del modelo y de las familias (P7-9 a P7-11)

* **Decidido (2026-10-22):** los umbrales de deriva son la configuración del detector, no apetito de riesgo, y van **por banco** en `drift_policy`, creada desde una plantilla: z ≥ 4 (contra los 12 meses previos) en las series de entrada y de proporción de `NEG`, PSI ≥ 0.25 en la distribución de longitud, y entrada al monitor con 12 meses seguidos de al menos 200 filas (BBVA 2016-04, AZTECA 2018-09, BANORTE 2018-10, SANTANDER 2019-04, NUBANK 2021-12). Con esa plantilla, cada serie alerta de 0 a 1.4 meses al año por banco ([tabla por banco](scale/scale_report.md#2-línea-base-histórica-del-monitor-de-deriva-e3-p7-6)).
* **Separado del HITL:** la política HITL (`risk_policy`) es global; una alerta sube la revisión solo del banco que alertó, con las reglas globales (`hitl_boosts`).

* **Desempeño de M4 (P7-10, decidido):** reentrenar si el κ en la muestra humana trimestral (300 revisiones) queda debajo de 0.89, el percentil 5 de un M4 sin cambios; avisos semanales sin disparo: tasa de corrección de la cola HITL > 28 % y acuerdo M4–Gemini < 94 % (4 semanas). Costo: ~3 min de revisión por semana y ~$0.02 de Gemini.
* **Familias de Gemini (P7-11, decidido):** al cambiar el modelo o el prompt, repetir las 300 reseñas de `muestra_v21` (~$0.03) y aceptar solo con acuerdo exacto ≥ 53 % y sin familias de prevalencia ≥ 5 % bajo el límite inferior de su IC ([reporte de 5.7, §8](scale/scale_report.md#8-desempeño-de-m4-y-calidad-de-las-familias-p7-10-p7-11)).

## 10. Alcance de EPIC-7 para la presentación (P8-12)

* **Pendiente:** qué features de EPIC-7 entran a la demo. Depende del tiempo disponible y de los temas 1, 5 y 6.

## 11. Límites y riesgos para la Model Card y la FMEA

Por redactar al aprobar el registro. Lista de partida:

* licencia no comercial de los checkpoints de `pysentimiento` (P8-2);
* corpus completo en un dataset privado de Kaggle (P7-1); hoy F-13 solo cubre el entrenamiento;
* error de 17–23 % en los casos difíciles (*dev* dirigido) aun revisando el 20 % (5.6);
* el oro es de un solo anotador principal (κ 0.81–0.87 con un segundo anotador);
* las familias son etiquetas de Gemini, con κ de 0.55 a 0.86 contra el autor según la familia;
* la señal de incidentes se probó solo con 3 incidentes de un banco (hasta 5.9);
* `fecha` es la de la última edición de la reseña;
* PII residual posible por la sanitización solo con regex (F-01: 0 nombres en 1 000 aleatorias).

## Para aprobar este registro

1. Evaluar M4 y M9 en el oro *test* (una sola vez) y decidir P8-1.
2. Decidir P8-9 (*Satisfaction Gap*) y P8-12 (alcance de EPIC-7).
3. Comprobar que el esquema aprobado cubre el frontal de EPIC-7 al definir P8-12.
4. Publicar `eligibility_rules_v1` y redactar la sección 11 en la Model Card y la FMEA.
5. Resolver o aceptar las [incompatibilidades](../backlog/epic_5.md#incompatibilidades-entre-el-diseño-de-epic-6-y-epic-7-y-la-evidencia) que siguen pendientes.
