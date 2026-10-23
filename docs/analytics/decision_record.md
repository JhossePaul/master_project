# Registro de decisión de EPIC-5 (5.8)

> **Estado (2026-10-22): aprobado; 5.8 cerrada.** Junta, por tema, lo que decidió el autor en 5.1–5.8 y la evidencia de cada punto. Las doce decisiones P8 están tomadas, el oro *test* se evaluó una sola vez, las reglas `eligibility_rules_v1` están publicadas, los límites están en la [Model Card](../governance/model_card.md) y la [FMEA](../governance/ethical_fmea_matrix.md), y las incompatibilidades están resueltas (la señal de incidentes pasa a 5.9). Sigue detallar [EPIC-6](../backlog/epic_6.md) a partir de este registro y, en paralelo, 5.9. El seguimiento de cada decisión está en el [registro de decisiones de `epic_5.md`](../backlog/epic_5.md#decisiones-pendientes). Índice: [`README.md`](README.md).

## Resumen

| Tema | Estado | IDs |
| :--- | :--- | :--- |
| 1. Modelo de sentimiento | Decidido: M4 RoBERTuito, tras la evaluación única en el oro *test* | P8-1, P8-2 |
| 2. Limpieza y elegibilidad | Decidido | P8-3, P8-4 |
| 3. Tópicos, familias e incidentes | Decidido; los umbrales de la señal pasan a 5.9 | 5.5, P8-7, P9-1 |
| 4. Calibración, HITL y priorización | Decidido | 5.6, P7-6 a P7-8 |
| 5. *Satisfaction Gap* y estimaciones | Decidido: *gap* en estrellas con PPI | P8-9, P8-10 |
| 6. Esquema de salida, HITL y migración | Decidido; cubre el frontal de EPIC-7 (revisado el 2026-10-22) | P8-5, P8-11 |
| 7. Búsqueda semántica y explicabilidad | Decidido | P8-6, P8-8 |
| 8. Backfill, operación diaria y ciclo de vida | Decidido | P7-1 a P7-4 |
| 9. Monitoreo de deriva, del modelo y de las familias | Decidido | P7-9 a P7-11 |
| 10. Alcance de EPIC-7 para la presentación | Decidido: por niveles | P8-12 |
| 11. Límites y riesgos para la Model Card y la FMEA | Redactado: Model Card 0.1 y FMEA F-16 a F-20 | — |

## 1. Modelo de sentimiento (P8-1, P8-2)

| Candidato | κ *dev* aleatorio (n = 794) | κ *test* (n = 594) | κ *dev* dirigido (n = 297) | Costo del backfill | Costo del delta | Probabilidades y HITL | Licencia |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **M4 RoBERTuito** (`M4_robertuito_s*_ppi`, con pesos) | 0.917 (3 semillas, 0.912–0.922) | 0.929 (0.925–0.932) | 0.63 | ~9 min de T4 en Kaggle ($0) | ~25 s de CPU al día ($0) | Sí: calibrado (T ≈ 1.7), curva HITL | No comercial (`pysentimiento`) |
| **M9 Gemini** (`prompt_v3`) | 0.93 (0.91–0.96) | 0.943 (0.917–0.966) | — | ~$72 | ~$0.02 al día (500 textos × $0.048 por 1 000) | No: solo etiqueta; la marca `duda` no sirve como señal HITL | Términos de Vertex AI |
| Diferencia M9 − M4 | +0.021 [−0.000, 0.043] | +0.010 a +0.017; todos los IC contienen el 0 | | | | | |

* **Decidido:** se decide con datos: el oro *test* (601 ítems, **una sola evaluación**), el costo y la licencia (P8-1). Para la tesis se acepta RoBERTuito y su licencia no comercial se declara en la Model Card y en la FMEA (P8-2).
* **Protocolo de la evaluación en el *test*** (aprobado por el autor el 2026-10-22, antes de mirar el *test*):
  1. **M4:** el *test* se predice en el Mac con los pesos `M4_robertuito_s{1,2,3}_ppi` y la T de cada semilla. El *temperature scaling* no cambia la clase predicha, así que solo afecta al ECE. Se reporta la media de las 3 semillas y, aparte, `s1`, la semilla del monitoreo de 5.7.
  2. **M9:** se usa la etiqueta de `prompt_v3` que ya está en la plata para esos ítems. Si falta alguno, se reporta y no se rellena sin consultar al autor.
  3. **Métricas** (las de 5.4, `evaluate.py`): κ de la muestra y de la población, F1 por clase, recall y precisión de `NEG`, ECE de M4 y la diferencia pareada M9 − M4 con *bootstrap* estratificado (2 000 réplicas). Corre una sola vez y solo se guardan agregados.
* **Regla de decisión** (aprobada por el autor el 2026-10-22):
  * **M4** si el IC de M9 − M4 en κ incluye el 0, o si M9 gana solo en `NEU` sin diferencia significativa en `NEG`.
  * **M9** solo si la diferencia en κ es significativa **y** M4 pierde en recall o precisión de `NEG`.
  * Si no hay un ganador claro, el autor decide con los números.
  * **Criterio del autor:** la carga de la prueba está en M9. Elegirlo implica gastos fijos (backfill y cada texto nuevo) y depender de un servicio externo, así que la razón para tomarlo tiene que ser fuerte.
* **Resultado (2026-10-22, [reporte de 5.4, sección 15](sentiment/sentiment_models_v0_report.md#15-evaluación-única-en-el-oro-test-58-2026-10-22)):** en el *test* (594 evaluables) M4 logra κ 0.929 (media de 3 semillas) y M9 0.943. M9 − M4 va de +0.010 a +0.017 y todos los IC 95 % contienen el 0, también ponderados. En `NEG` no hay diferencia significativa (recall 0.975 contra 0.981, precisión 0.964 contra 0.977), y la ventaja de M9 está en `NEU` (22 ítems). La T de 5.6 baja el ECE del *test* de 0.029 a 0.011–0.015.
* **Decidido (P8-1, aplicación de la regla aprobada): M4 RoBERTuito** (`M4_robertuito_s*_ppi`). El *test* queda consumido.
* Evidencia: [competencia de modelos](sentiment/sentiment_models_v0_report.md), [calibración](calibration/calibration_report.md), [protocolo](sentiment/sentiment_models_protocol.md).

## 2. Limpieza y elegibilidad (P8-3, P8-4)

* **Decidido:** reglas `eligibility_rules_v1`: corte de NUBANK en 2020-01-01, `TNSS_NOT_SPANISH` descartada, `TNSS_SINGLE_WORD` resuelta con el léxico determinista (151 formas, 95.3 % de cobertura, 99 % de exactitud; las no cubiertas se excluyen, con un sesgo de −0.001 a −0.007 estrellas) y `TOPIC_TOO_SHORT` con k = 1 para tópicos y familias. Sin filtro de longitud; inferencia por texto único.
* **Hecho (2026-10-22):** [`eligibility_rules.md`](eda/eligibility_rules.md) publicada como `v1`, con conteos por banco × periodo × motivo ([`eligibility_v1_counts.json`](eda/eligibility_v1_counts.json)). Sentimiento: 81.7 % por M4, 16.7 % por léxico y 1.6 % excluido. Familias y tópicos: 26.6 % de las filas (negativas de dos palabras o más).
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
* **Decidido por el autor (2026-10-22):** el KPI es el ***gap* en estrellas**: el promedio de estrellas menos el puntaje del texto (`NEG` = 1, `NEU` = 3, `POS` = 5), estimado con PPI y con intervalo por banco y periodo. La matriz 3 × 3 y las dos direcciones van como desglose. Quedan fuera el α y 1 + 4·p(`POS`). Por reseña se muestra la clase con sus probabilidades, no un puntaje continuo (P8-9).
* **Evidencia de P8-9:** el autor objetó medir una sola dirección. Medido con PPI:

  | Medida (corpus) | Gemini | M4 |
  | :--- | :--- | :--- |
  | Texto más negativo que las estrellas | 10.5 % [9.4, 11.5] | 10.5 % [9.4, 11.7] |
  | Texto más positivo que las estrellas | 0.9 % [0.7, 1.1] | 0.8 % [0.5, 1.1] |
  | Brecha neta ordinal (−2 a +2) | −0.142 [−0.158, −0.126] | −0.138 [−0.154, −0.122] |

  **Puntaje continuo de 1 a 5, medido en 5.8** ([reporte de 5.6, §3.5](calibration/calibration_report.md#35-puntaje-continuo-de-1-a-5-tnss-original-p8-9-58-2026-10-22)): estrellas 4.09 y puntaje del texto 3.88, con un *gap* de +0.21 [0.17, 0.24] en el corpus. Por banco va de +0.10 (AZTECA) a +0.27 (BBVA). La versión con probabilidades (1·p(`NEG`) + 3·p(`NEU`) + 5·p(`POS`)) da el mismo agregado que la de clases y es peor por reseña (error medio 0.107 contra 0.075). 1 + 4·p(`POS`) cuenta `NEU` como queja e infla el *gap* a +0.28. El α de la propuesta original solo escala el *gap* y no se puede estimar sin una calificación verdadera de 1 a 5. La escala 1/3/5 agrega un artefacto de −0.04 por las reseñas concordantes (4★ con `POS` cuentan −1).
* Evidencia: [reporte de 5.6, §3.3](calibration/calibration_report.md#33-satisfaction-gap-simétrico-p8-9-2026-10-22).

## 6. Esquema de salida, HITL y migración (P8-5, P8-11)

* **Decidido (P8-11):** tablas nuevas para el HITL y se elimina `hitl_triage_audit_log`.
* **Decidido (P8-5, 2026-10-22), con una condición, ya cumplida:** se aprueba el [esquema v3](../contracts/analytics_outputs_v3_draft.md) con los cambios del autor: `eligibility_code` explícito (`ELEGIBLE` o el código; nulo solo si no se evaluó), `sentiment` con `NO_PREDICTED`, probabilidades nulas solo cuando no hay modelo, y `review_predictions` por reseña con inferencia por texto único en el backfill. La muestra de monitoreo (`hitl_items.reason`) puede entrar al oro por versiones (`gold_versions`) y el revisor puede dejar un comentario sanitizado. **Condición:** que cubra todas las necesidades del frontal de EPIC-7, que se revisa con P8-12.
* La migración no mueve datos: `delora_predictions` y `hitl_triage_audit_log` están vacías.

## 7. Búsqueda semántica y explicabilidad (P8-6, P8-8)

* **Decidido (P8-6):** BigQuery `VECTOR_SEARCH` sobre embeddings MiniLM (384) en una tabla particionada por mes, con ventana configurable de 12 meses: ~2 000 búsquedas al mes en el free tier (cada búsqueda sobre todo el corpus factura 4.26 GB). Sin Vertex Vector Search.
* **Decidido (P8-8), revisado al definir el frontal (2026-10-22):** explicabilidad por oclusión, precalculada para los casos del HITL (~0.5 s por texto en Cloud Run, ~9 min de CPU por semana) y bajo pedido para las demás reseñas (servicio aparte de 2 GiB). Se muestra solo en la ficha del Explorador (EPIC-7, 7.6) y **nunca en la pantalla HITL**, para no anclar al revisor; por la misma razón, la muestra de monitoreo y todo caso que pueda entrar al oro se revisan a ciegas, sin la predicción.
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

* **Decidido por el autor (2026-10-22):** el frontal de [EPIC-7](../backlog/epic_7.md), reescrito con las secciones que definió el autor, y el alcance por niveles:
  * **Imprescindible:** API y seguridad con tres roles (IAP), landing, reporte de hallazgos versionado, cockpit diario, HITL de sentimiento con modo ciego, administración de `risk_policy` y `drift_policy`, documentos de gobernanza y pruebas.
  * **Importante:** Explorador de reseñas (tabla con *crossfilter*, búsqueda semántica y ficha con XAI), alertas e incidentes, MLOps y AIOps.
  * **Deseable:** HITL de aspectos y tópicos, pestaña por versión de la app (depende de 5.9) y página de gobernanza.
* **Esquema:** revisado pantalla por pantalla ([sección 6](../contracts/analytics_outputs_v3_draft.md#6-cobertura-del-frontal-de-epic-7)); con los agregados de esa revisión, la condición de P8-5 queda cumplida.

## 11. Límites y riesgos para la Model Card y la FMEA

**Redactado (2026-10-22):** los límites están en la sección 5 de la [Model Card](../governance/model_card.md), que se escribió en 5.8. Los riesgos tienen su fila en la [FMEA](../governance/ethical_fmea_matrix.md): F-01, F-13 a F-15 y las nuevas F-16 (licencia), F-17 (priorización con predicciones inciertas), F-18 (familias de Gemini), F-19 (umbrales de incidentes) y F-20 (sesgo del anotador), por calificar. La calificación del *Label Noise Bias* quedó confirmada con el oro *test* (M4 pierde 5 de 212 quejas; RPN 60). Lista de partida:

* licencia no comercial de los checkpoints de `pysentimiento` (P8-2);
* corpus completo en un dataset privado de Kaggle (P7-1), cubierto por F-14;
* error de 17–23 % en los casos difíciles (*dev* dirigido) aun revisando el 20 % (5.6);
* el oro es de un solo anotador principal (κ 0.81–0.87 con un segundo anotador);
* las familias son etiquetas de Gemini, con κ de 0.55 a 0.86 contra el autor según la familia;
* la señal de incidentes se probó solo con 3 incidentes de un banco (hasta 5.9);
* `fecha` es la de la última edición de la reseña;
* PII residual posible por la sanitización solo con regex (F-01: 0 nombres en 1 000 aleatorias).

## Para aprobar este registro

1. ~~Evaluar M4 y M9 en el oro *test* y decidir P8-1~~: hecho, M4 (2026-10-22).
2. ~~Decidir P8-9 y P8-12~~: *gap* en estrellas y alcance por niveles (2026-10-22).
3. ~~Comprobar que el esquema cubre el frontal de EPIC-7~~: hecho (2026-10-22).
4. ~~Publicar `eligibility_rules_v1` y redactar la sección 11 en la Model Card y la FMEA~~: hecho (2026-10-22).
5. ~~Resolver o aceptar las [incompatibilidades](../backlog/epic_5.md#incompatibilidades-entre-el-diseño-de-epic-6-y-epic-7-y-la-evidencia)~~: resueltas (2026-10-22); los umbrales de la señal de incidentes pasan a 5.9 (P9-1).

**Registro aprobado y 5.8 cerrada (2026-10-22).**
