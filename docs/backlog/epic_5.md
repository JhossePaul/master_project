# EPIC-5: Planteamiento Analítico y Experimentación del Core NLP

* **Estado (2026-10-22):** En curso, fase 2. Cerradas 5.1 a 5.8. El [registro de decisión](../analytics/decision_record.md) está aprobado: M4 RoBERTuito (`M4_robertuito_s1_ppi`) en producción, *gap* en estrellas con PPI (P8-9) y frontal de EPIC-7 por niveles (P8-12). El primer backfill de M4 está hecho. Falta 5.9 (incidentes y versiones con la estrategia elegida). Los frontales de curaduría HITL (sentimiento, aspectos y tópicos) pasan a EPIC-7 (7.7) y su base de datos a EPIC-6 (6.2). Ver [estado por feature](#-estado-por-feature), el [registro de decisiones](#decisiones-pendientes) y los [siguientes pasos](#siguientes-pasos).
* **Historia de los resultados:** [`docs/analytics/README.md`](../analytics/README.md) ordena los reportes como una historia y dice qué cifra está vigente. Este documento solo guarda el planteamiento, el estado y lo que falta; la cronología detallada está en los reportes.
* **Fases:** (1) planteamiento analítico viable → (2) experimentación para elegir la estrategia de producción → (3) despliegue de la estrategia elegida. Desde la reorganización del backlog (2026-10-22), la fase 3 es [EPIC-6](epic_6.md), que conserva la especificación anterior como anexo no vigente. Con el registro de decisión aprobado, detallarla es su primera tarea; solo 6.4 espera a 5.9.
* **Dependencias:** EPIC-1 a EPIC-4 cerradas ([cierre](epics.md#cierre-de-las-épicas-1-a-4)). Corpus: `bbva_voc_tds.sanitized_reviews_tds`, **2 649 047 reseñas** en el snapshot del EDA (`tds_20261016T054714Z`) de BBVA, NUBANK, SANTANDER, AZTECA y BANORTE (2011-04 a 2026-10), con `source_observed_at`. El backfill de M4 cubrió 2 653 238 filas y 1 429 675 textos únicos (TDS al 2026-10-20). Bibliografía: [`references.md`](../governance/references.md).
* **Directorios:**
  * `experiments/analytics/`: proyecto `uv` **independiente del workspace** (su propio `pyproject.toml` y `uv.lock`), para que las dependencias de experimentación no entren al lock de producción. El código es el paquete `voc_analytics` (`src/`), agrupado por etapa: `snapshot`, `eda`, `labeling`, `sampling`, `annotation`, `analysis`, `sentiment`, `topics`, `calibration` (5.6) y `scale` (5.7). Comandos en su [README](../../experiments/analytics/README.md).
  * `docs/analytics/`: reportes por etapa, con las mismas carpetas que el paquete (`eda/`, `labeling/`, `sentiment/`, `topics/`, `calibration/`, `scale/`) y el registro de decisión de 5.8 ([`decision_record.md`](../analytics/decision_record.md), aprobado).
  * `docs/contracts/`: el [esquema de salida v3](../contracts/analytics_outputs_v3_draft.md), aprobado en 5.8 (P8-5, P8-11).
  * `docs/governance/`: [Data Card](../governance/data_card.md) `v0.2`, [Model Card](../governance/model_card.md) 0.1 y [matriz FMEA](../governance/ethical_fmea_matrix.md) (filas F-10 a F-20 de EPIC-5).

---

## 🎯 Objetivo y principios

Diseñar, con evidencia, el pipeline analítico que responde a cuatro preguntas del caso de uso, y elegir la estrategia de producción **antes** de escribir el paquete desplegable:

| Pregunta | Salida candidata | Feature |
| :--- | :--- | :---: |
| Q1. ¿Cuál es el sentimiento real del texto, separado de las estrellas? | Polaridad por reseña con M4 RoBERTuito (P8-1) y *gap* en estrellas: promedio de estrellas menos el puntaje del texto, con PPI (P8-9), +0.21 [0.17, 0.24]. Desglose medido en 5.6: el texto es más negativo que las estrellas en el 10.5 % de las reseñas y más positivo en el 0.9 %. **Resuelta en 5.8** | 5.4, 5.6, 5.8 |
| Q2. ¿Qué temas recurrentes hay en las quejas y cómo cambian en el tiempo? | Familias de aspectos `v2.1` (núcleo) y tópicos curados (detalle) sobre las reseñas negativas, por banco y periodo. **Resuelta en 5.5** | 5.5 |
| Q3. ¿Cómo detectamos rápido un incidente nuevo? | Marca `u` (problema atribuido a una actualización) y series por familia, por banco y mes; la prueba hacia atrás detecta 2 de 3 incidentes de BBVA. **Resuelta en 5.5** (umbrales en 5.9) | 5.5 |
| Q4. ¿Qué atender primero? | Volumen de negativas por familia y marca `u`, en nivel y en anomalía; los votos solo como contexto. **Resuelta en 5.6** | 5.6 |

Principios:

* **Ningún modelo, dependencia, tópico ni esquema de salida era definitivo** hasta el registro de decisión (5.8). Se cumplió: lo vigente está en el [registro](../analytics/decision_record.md). RoBERTuito, Delora y los 8 `ABSATopic` de `voc-common` eran hipótesis: Delora se descartó en 5.4, 5.5 reemplazó los 8 `ABSATopic` por las 11 familias `v2.1` (multi-etiqueta, con las marcas `u` y `s`) y los tópicos como capa aparte, y 5.8 eligió M4 RoBERTuito.
* **Las estrellas son una etiqueta ruidosa del sentimiento del texto**, no la verdad. El sentimiento real nunca recibe las estrellas como entrada.
* **Calidad y costo se miden juntos:** con 2.65 M de reseñas, la velocidad y el costo de inferencia son criterio de selección al mismo nivel que la métrica de calidad.
* **Toda cifra de la literatura o de conversaciones con LLM es una hipótesis** hasta medirla sobre este corpus (ver `references.md`, columna *Verif.*).
* **Etiquetado humano limitado:** 1 000 reseñas como base y hasta 2 000 con esfuerzo extra. Nunca se etiqueta el corpus completo; las 2.65 M solo se predicen.

La evidencia inicial sobre el corpus (longitudes, duplicados y deriva por banco y año, 2026-10-16) está en el [capítulo 1 de la historia](../analytics/README.md#1-problema-y-corpus).

---

## 📦 Estado por feature

| Feature | Estado | Reportes |
| :--- | :--- | :--- |
| 5.1 Planteamiento y elegibilidad | **Cerrada (2026-10-22).** `TNSS_SINGLE_WORD` por léxico (P8-3) y `eligibility_rules_v1` publicada con sus conteos (P8-4): sentimiento 81.7 % por M4, 16.7 % por léxico y 1.6 % excluido; familias y tópicos sobre el 26.6 % de las filas | [Reglas](../analytics/eda/eligibility_rules.md), [conteos](../analytics/eda/eligibility_v1_counts.json), [guía](../analytics/labeling/annotation_guideline.md) |
| 5.2 EDA | **Cerrada (2026-10-21).** EDA global, patrones temporales, tokens, léxico para una palabra (95 % de cobertura) y guía de aspectos `v2.1` (reabierta para 5.5): 11 familias más las marcas `u` y `s`; `UX` pasó de κ 0.55 a 0.74 y `DV` queda separado; multi-aspecto del 24.7 % (32.1 % con `v1`). *Data Card* `v0.2` | [EDA](../analytics/eda/eda_report.md), [temporal](../analytics/eda/eda_temporal_report.md), [guía de aspectos `v2.1`](../analytics/eda/eda_aspects_guideline.md) |
| 5.3 Etiquetado | **Cerrada (2026-10-20).** Oro (1 730 ítems) y plata vigentes; acuerdo entre personas medido (κ 0.81). 5.5 cerró sin usar `menciona_falla` (`prompt_v4` no se necesita). 5.6 y 5.8 cerraron sin pedir más oro y el *test* quedó consumido en 5.8. Se reabre solo si se suman anotadores (guía `v2.3`) | [Capítulo 3](../analytics/README.md#3-etiquetado-guía-pilotos-oro-y-plata) |
| 5.4 Modelos de sentimiento | **Cerrada (2026-10-20):** M0–M9 evaluados; M4 RoBERTuito es el mejor modelo propio y 5.8 lo eligió frente a M9 con el oro *test* (κ 0.929 contra 0.943, sin diferencia significativa) | [Protocolo](../analytics/sentiment/sentiment_models_protocol.md), [capítulo 4](../analytics/README.md#4-competencia-de-modelos-de-sentimiento) |
| 5.5 Tópicos y ABSA | **Cerrada (2026-10-22).** Recomendación aprobada por el autor, con el agregado de llevar los frontales de curaduría HITL (sentimiento, aspectos y tópicos) a EPIC-7 y su base de datos a EPIC-6. Híbrido: familias `aspects_v2_1` y la marca `u` como núcleo de medición y alerta (la marca `u` detecta 2 de 3 incidentes con 4 % de falsas alarmas; `DV` y `UX` avisaron del rediseño de BBVA un mes antes), y tópicos por cláusulas como capa de detalle curada para producto e ingeniería. Los tópicos no encontraron temas fuera de la taxonomía; cerca de un tercio de su peso es ruido. `TOPIC_TOO_SHORT` con k = 1 (decidido). Costo: ~$0.60 al mes de Gemini y ~30–60 min de curaduría por trimestre | [Plan](../analytics/topics/topics_design.md), [reporte](../analytics/topics/topics_report.md), [nota para 5.8](../analytics/topics/topics_decision_note.md) |
| 5.6 Calibración, HITL y priorización | **Cerrada (2026-10-22).** *temperature scaling* adoptado; umbral HITL al 90 % de cobertura (parámetro configurable); PPI con Gemini y con M4 hecho; M4 reentrenado con pesos guardados (lote `m4_ppi`); priorización por volumen de negativas por familia y marca `u`, sin fórmula anterior ni votos (decisión del autor) | [Plan](../analytics/calibration/calibration_design.md), [reporte](../analytics/calibration/calibration_report.md) |
| 5.7 Escala, ciclo de vida y monitoreo | **Cerrada (2026-10-22).** Benchmark en el Mac y en Cloud Run, línea base de deriva, costos de Gemini, búsqueda vectorial, Vertex Model Registry y explicabilidad medidos; P7-1 a P7-4 y P7-6 a P7-11 decididas (HITL global en `risk_policy`, alertas de deriva por banco en `drift_policy`, reentrenamiento de M4 y revalidación de las familias) | [Plan](../analytics/scale/scale_design.md), [reporte de 5.7](../analytics/scale/scale_report.md) |
| 5.8 Registro de decisión | **Cerrada (2026-10-22):** P8-1 a P8-12 decididas (M4 RoBERTuito tras el oro *test*, *gap* en estrellas, frontal de EPIC-7 por niveles); `eligibility_rules_v1` publicada con sus conteos; Model Card 0.1 y FMEA F-14 a F-20; incompatibilidades resueltas. Primer backfill de M4 hecho (`s1` en producción) | [`decision_record.md`](../analytics/decision_record.md), [esquemas](../contracts/analytics_outputs_v3_draft.md) |
| 5.9 Incidentes y versiones con la estrategia elegida | Lista para empezar (5.8 cerrada). P9-1 (criterio) y P9-2 decididas; P9-3 pendiente ([registro](#decisiones-pendientes)). Incluye la validación única de la cola HITL de 5.6 | — |

### FEATURE 5.1: Planteamiento, Volumetría y Contrato Analítico

**Objetivo:** fijar qué se predice, sobre qué filas y con qué presupuesto, antes de experimentar.

* **Etiquetas de sentimiento:** decidido. `NEG`/`NEU`/`POS` más la marca `NO_EVALUABLE`, con `menciona_falla`, `duda` y `nombre_persona`; cualquier queja concreta es `NEG`. Ver la [guía `v2.2`](../analytics/labeling/annotation_guideline.md).
* **Reglas deterministas de elegibilidad** ([`eligibility_rules_v1`](../analytics/eda/eligibility_rules.md), publicada el 2026-10-22 con sus conteos por banco × periodo × motivo):
  * se evalúan por fila antes de la inferencia, sin modelos ni aleatoriedad; gana la primera que coincide;
  * la fila excluida queda `NOT_PREDICTED` con su código, se conserva y se reporta por banco × periodo × motivo;
  * la inferencia corre una vez por texto único elegible y se propaga a sus filas;
  * `TOPIC_NOT_NEGATIVE` usa el TNSS **predicho**, nunca las estrellas, así que el backfill de tópicos es posterior al de TNSS;
  * el EDA puede añadir reglas, cada una con código, criterio, conteo y justificación.
* **Decisiones vigentes:** corte de NUBANK en 2020-01-01 (`TNSS_TIME_OUTLIER`, 175 filas); `TNSS_NOT_SPANISH` descartada; `TOPIC_TOO_SHORT` con k = 1 (decisión del autor, 2026-10-22): del análisis de tópicos y familias se excluyen solo las negativas de una palabra ([`topics_report.md`](../analytics/topics/topics_report.md#43-topic_too_short-k--1-se-confirma-con-v21-y-los-5-bancos), sección 4.3).
* **`TNSS_SINGLE_WORD` (decisión del autor, 2026-10-22, P8-3):** las 484 829 filas de una palabra (18.3 %) se asignan con el léxico determinista (`RULE_BASED`; 151 formas cubren el 95.3 % con 99 % de exactitud en el oro *dev*) y se excluyen las no cubiertas, con un sesgo de −0.001 a −0.007 estrellas. Excluirlas todas habría sesgado de −0.10 a −0.21 estrellas por banco. Las reglas `v1` se aprobaron (P8-4) y se publicaron con sus conteos (2026-10-22).
* **Envolvente de volumetría y costo:** backfill único sobre ≤ 1.60 M textos únicos (1 383 138 en el snapshot del EDA; 1 429 675 en el backfill de M4, con el TDS al 2026-10-20) y delta diario de cientos de reseñas. Cualquier estrategia que no quepa queda descartada aunque gane en calidad. Costos medidos hasta ahora en la [sección de cómputo](#-cómputo-y-presupuesto).
* **Salidas de producción:** el [esquema v3](../contracts/analytics_outputs_v3_draft.md) reemplaza a `delora_predictions` y `hitl_triage_audit_log` (las dos están vacías). Decidido en 5.8 (P8-5, P8-11), con la cobertura del frontal de EPIC-7 revisada.

### FEATURE 5.2: EDA Global y Pipeline de Limpieza

> **Cerrada de nuevo (2026-10-21) con la guía de aspectos `v2.1`** ([EDA, sección 5.2.1](../analytics/eda/eda_report.md#521-guía-de-aspectos-v2-y-v21-reapertura-para-55)): taxonomía final de 11 familias con las marcas `u` y `s`; `UX` κ 0.74; `DV` separado como excepción por prevalencia (1.8 %); multi-aspecto 24.7 %. Se reabrió el 2026-10-20: lo pidió 5.5 ([plan de tópicos](../analytics/topics/topics_design.md), sección 6) y lo aprobó el autor. El resto sigue cerrado: EDA global, patrones temporales y los pendientes de tokens, multi-aspecto y léxico ([sección 5 del EDA](../analytics/eda/eda_report.md#5-pendientes-cerrados-tokens-multi-aspecto-y-léxico)); *Data Card* `v0.2`.
>
> **Reapertura (2026-10-20 a 2026-10-21), en resumen:** `DS` se partió en `DV`, `UX` y `FQ`; la regla 3 pasó a la marca `u` y se agregó la marca de seguridad `s`; `OT` dejó de ser caja de sastre. Tras tres rondas de calibración y una muestra de 300 codificada a ciegas por el autor y por Gemini, la `v2.1` fusionó `FQ` en `UX` (prevalencia 0.8 %) y mantuvo `DV` separado como excepción explícita del autor. Proceso, regla de decisión y cifras: [EDA, sección 5.2.1](../analytics/eda/eda_report.md#521-guía-de-aspectos-v2-y-v21-reapertura-para-55), y registro de rondas en la [guía](../analytics/eda/eda_aspects_guideline.md), sección 7. Límite: la marca `s` tiene muy pocos positivos y su κ autor–Gemini (0.56) no es concluyente.
>
> **Entregado a 5.5:** la guía `v2.1`, las etiquetas `aspects_v2_1` con su esquema de columnas, y `aspects_v2_metrics.json` y `aspects_v2_1_metrics.json`.
>
> **Se vuelve a reabrir si hay un snapshot nuevo del TDS.**

**Objetivo:** describir los 15 años y 5 bancos y decidir la limpieza y la elegibilidad.

* **Hecho:** [EDA global](../analytics/eda/eda_report.md) (2026-10-16), [patrones temporales](../analytics/eda/eda_temporal_report.md) (2026-10-18) y [segunda pasada](../analytics/eda/eda_report.md#5-pendientes-cerrados-tokens-multi-aspecto-y-léxico) (2026-10-20). Conclusiones en el [capítulo 2](../analytics/README.md#2-eda-y-elegibilidad).
* **Decisiones vigentes:**
  * sin filtro de longitud: la longitud predice las estrellas y filtrar sesga los agregados;
  * deduplicar por texto único antes de etiquetar y predecir;
  * la plata no necesita estratos de quincena, día de la semana ni trimestre; los atributos temporales se guardan por fila;
  * las ventanas de deriva de 5.7 siguen la cadencia de cada banco (semanal en NUBANK, 2–5 semanas en el resto);
  * el tope de 128 tokens de 5.4 se mantiene: trunca menos del 0.1 % de las filas (RoBERTuito 0.03 %, BETO 0.07 %).
* **Evidencia para otras features:**
  * **5.5, multi-aspecto (`v1`, superada por `v2.1`: 24.7 % [22.6, 26.8], ver 5.2.1):** según Gemini (`aspects_v1`), el 32 % [30, 34] de las filas `NEG` tiene dos o más problemas, y el 51 % de las de 20 palabras o más. El autor, a ciegas en 100 textos, marca 44 % [35, 54] (κ 0.42), así que el 32 % es una cota inferior. Un tercio o más de las quejas mezcla problemas: conviene un esquema de varios aspectos por reseña;
  * **5.5, `TOPIC_TOO_SHORT`:** decidido k = 1 (ver 5.1). Las negativas cortas casi nunca son multi-aspecto, pero sí nombran problemas concretos (corregido por 5.5 el 2026-10-21; [`topics_report.md`](../analytics/topics/topics_report.md#43-topic_too_short-k--1-se-confirma-con-v21-y-los-5-bancos), sección 4.3);
  * **5.8, `TNSS_SINGLE_WORD` (decidido, P8-3):** 151 formas cubren el 95.3 % de las reseñas de una palabra, con 99 % de exactitud en el oro *dev*; excluir solo las no cubiertas deja un sesgo de −0.001 a −0.007 estrellas.
* **Resuelto en otras features:**
  * proxy de incongruencia estrellas–texto: lo midieron el oro y la plata (5.3);
  * limpieza por familia de modelos: `texto_sanitizado` sin `limpiar_texto_bancario` (5.4).

### FEATURE 5.3: Estrategia de Etiquetado (Oro y Plata)

> **Cerrada (2026-10-20).** Oro vigente de 1 730 ítems, plata `silver_v0`, guía `v2.2`, segundo anotador (κ 0.81) y F-01 en monitoreo. Se reabre solo si:
> 1. ~~5.5 usa `menciona_falla` en sus métricas (`prompt_v4`)~~: descartada, 5.5 cerró (2026-10-22) sin usarla;
> 2. ~~5.6 o 5.8 necesitan más oro~~: descartada, cerraron sin pedirlo y el *test* quedó consumido en 5.8;
> 3. se suman anotadores (guía `v2.3` con ejemplos largos de elogio con una queja menor).

**Objetivo:** obtener etiquetas limpias suficientes para entrenar y, sobre todo, para evaluar sin sesgo, con 1 000–2 000 etiquetas humanas.

* **Hecho:** guía de anotación, piloto de Gemini, oro en dos rondas más una re-anotación a ciegas, y plata v0. Historia y cifras vigentes en el [capítulo 3](../analytics/README.md#3-etiquetado-guía-pilotos-oro-y-plata).
* **Decisiones vigentes:**
  * **Gemini Flash vía Vertex AI en el proyecto:** los datos no salen de GCP y se paga con créditos. La API se habilita con el flag `enable_vertex_ai_api`; **no** se usa `enable_dedicated_vertex_endpoints`.
  * **Etiquetador:** `gemini-3.6-flash` con `prompt_v3` (guía `v2`): κ 0.92 contra el oro en 600 textos nuevos, $0.045–0.048 por 1 000 textos. Se versionan el prompt, el modelo exacto y la fecha. Las etiquetas de plata nunca se usan como verdad para reportar KPIs.
  * **Todo el oro se anota a ciegas,** tras medir un anclaje de +7 puntos en modo asistido.
  * **Oro vigente** (`gold_v0_r2` + `gold_v1`, 1 730 ítems): *dev* aleatorio 799, *dev* dirigido 300, *test* 601 y 30 de calibración. Solo el bloque aleatorio da cifras poblacionales; el *test* se evaluó una sola vez, en 5.8, y quedó consumido. Diseño en [`gold_v1_design.md`](../analytics/labeling/gold_v1_design.md).
  * **Plata vigente:** `silver_v0`, 99 926 filas y 70 284 textos únicos por $3.37, con holdout temporal desde 2026-04-01.
  * **Herramienta del oro:** app Streamlit local (`voc_analytics.annotation`), solo en `localhost`; guarda en CSV fuera de git y registra el tiempo por reseña.
  * `prompt_v4` solo se justificaba si `menciona_falla` entraba a las métricas de 5.5; 5.5 cerró sin usarla, así que no se necesita.
* **Segundo anotador (2026-10-20):** 100 ítems a ciegas de `gold_v1`, con la guía `v2.2`. κ entre personas 0.81 [0.70, 0.91] con 4 clases y 0.87 con 3; Gemini coincide con cada anotador (0.91 y 0.88 en *dev*) tanto o más que ellos entre sí. El desacuerdo principal es la regla 2 amplia: el segundo anotador decide por el tono. Ver el [reporte](../analytics/labeling/gold_v1_report.md), sección 7.
* **F-01 (hecho, 2026-10-20):** la [matriz FMEA](../governance/ethical_fmea_matrix.md#f-01-nombres-propios-en-texto-libre) registra la tasa medida de nombres propios, 0 en 1 300 anotadas. RPN 105 → 70; la fila pasa a monitoreo.

### FEATURE 5.4: Competencia de Modelos de Sentimiento con Etiquetas Ruidosas

**Objetivo:** elegir el modelo de Q1 por evidencia, con el mismo protocolo para todos.

* **Candidatos y protocolo:** escalera M0–M9, particiones, métricas y regla de decisión en [`sentiment_models_protocol.md`](../analytics/sentiment/sentiment_models_protocol.md). M8 (Delora), el más caro y el menos validado, se time-boxeó y se descartó (ver abajo).
* **Hecho:** fase A en el Mac (M0, M1, M2, T0, M9), escalera de ruido con TF-IDF (M3, M6, M7), M4 con RoBERTuito y BETO (3 semillas cada uno), M8 Delora (búsqueda del detector y 3 semillas), M5 (*label smoothing* sobre M4, 2 valores de ε y 3 semillas) en Kaggle y un sesgo de `NEU` sobre M4, evaluados con el *dev* ampliado. Detalle en las secciones 12 a 14 del [reporte](../analytics/sentiment/sentiment_models_v0_report.md). Ver el [capítulo 4](../analytics/README.md#4-competencia-de-modelos-de-sentimiento).
* **Decisiones vigentes:**
  * entrada `texto_sanitizado`, un ejemplo por texto único, sin pesos ni filtro de longitud; las métricas se desglosan por longitud;
  * se excluyen del entrenamiento las reseñas de todas las colas del oro;
  * descartados con motivo: T0 y M2 sin ajustar (dominio), M3, M6 y M7 (estrellas como etiqueta), **M8 Delora** (−0.04 a −0.05 de κ contra M4 en las tres semillas, más caro; su detector queda como candidato para la incongruencia) y **M5** (empata con M4 y calibra peor);
  * M4 RoBERTuito es el mejor modelo propio: empata con BETO en el aleatorio y gana en el dirigido;
  * entrenamiento con GPU en Kaggle, sin el oro *test* (riesgo F-13 aceptado por el autor); nada de GPU en GCP sin su aprobación.
* **Resultado vigente** (κ *dev* aleatorio, n = 794; M4 y M8, media de 3 semillas): M0 0.68, M1 0.87, M8 0.87, M4 0.92, M9 0.93. M4 − M1 entre +0.043 y +0.053, significativo en las seis corridas; M9 − M4 = +0.021 [−0.000, 0.043], concentrado en `NEU` (F1 0.73 contra 0.55).
* **Cerrado (2026-10-20):** escalera M0–M9 completa. Un sesgo de `NEU` sobre M4, elegido con la plata de `holdout_nuevo`, no mejora en el oro (Δκ medio −0.001) y no se adopta. **M4 RoBERTuito queda como el mejor modelo propio**; la elección entre M4 y M9 se hizo en 5.8 (ver abajo).
* **Resultado en el oro *test* (5.8, 2026-10-22):** M4 κ 0.929 (media de 3 semillas) contra M9 0.943 en 594 evaluables; M9 − M4 de +0.010 a +0.017, con todos los IC conteniendo el 0, y sin diferencia en `NEG` (recall 0.975 contra 0.981). Con la regla aprobada antes de evaluar, **se eligió M4 RoBERTuito** (P8-1) y `s1` va a producción. Ver la [sección 15 del reporte](../analytics/sentiment/sentiment_models_v0_report.md#15-evaluación-única-en-el-oro-test-58-2026-10-22).

### FEATURE 5.5: Descubrimiento de Tópicos y Decisión sobre ABSA

**Objetivo:** decidir con evidencia si se necesita una taxonomía fija (ABSA), tópicos dinámicos o un híbrido, para Q2 y Q3.

* **Estado (2026-10-22):** **cerrada.** Recomendación aprobada por el autor; agregado: los flujos de curaduría pasan al frontal HITL de EPIC-7 (7.7) y la base de datos de curadurías para el reentrenamiento a EPIC-6 (6.2) ([requisitos y borrador del modelo de datos](../analytics/topics/topics_decision_note.md#agregado-del-autor-2026-10-22-curaduría-hitl-en-epic-6-y-epic-7)). [Plan aprobado](../analytics/topics/topics_design.md), [reporte](../analytics/topics/topics_report.md) (fases 0 a 4) y [nota para el registro de decisión](../analytics/topics/topics_decision_note.md). Todo en local sobre la plata, sin backfill de sentimiento; la vía B a escala costó $3.64.

* **Descubrimiento (hecho):** sobre las reseñas negativas elegibles para tópico, agrupar embeddings por periodo (estilo BERTopic: embeddings → reducción de dimensión → HDBSCAN → términos representativos por c-TF-IDF y nombre propuesto por un LLM).
* **Lectura temporal (hecha, [reporte](../analytics/topics/topics_report.md) §3.2):** qué tópicos son estables, cuáles aparecen tras una versión concreta y cuáles desaparecen, por banco.
* **Validación humana (hecha, fase 4, [reporte](../analytics/topics/topics_report.md) §4.7):** revisión de los tópicos principales (coherencia, utilidad para producto) y contraste con la taxonomía hipotética de 8 `ABSATopic`.
* **Opciones (decidido: híbrido, 2026-10-22):**

  | Opción | Ventaja | Riesgo |
  | :--- | :--- | :--- |
  | Taxonomía fija (ABSA ligero) | Estable, comparable en el tiempo, simple de reportar | No ve incidentes nuevos; envejece |
  | Tópicos dinámicos | Detecta temas nuevos sin reentrenar | Nombres e identidad cambian entre corridas; requiere curaduría |
  | **Híbrido: núcleo estable + "emergentes" (elegido)** | Comparabilidad y detección de lo nuevo | Más complejidad operativa |

* **Detección de incidentes (Q3, hecha: la marca `u` detecta 2 de 3 incidentes de BBVA con 4 % de falsas alarmas; `DV` y `UX` avisaron del rediseño un mes antes; [reporte](../analytics/topics/topics_report.md) §3.3 y §4.4):** proponer una señal (aparición o crecimiento anómalo de un tópico por banco y versión) y probarla hacia atrás con los picos que ya mostró el EDA (BBVA 2024-07, 2025-10 y 2025-11) y con los días pico de SANTANDER y AZTECA donde las 5★ esconden quejas.
* **Insumos de 5.2** ([EDA](../analytics/eda/eda_report.md#52-proporción-multi-aspecto-de-las-negativas), sección 5.2): entre el 32 % (Gemini, cota inferior) y el 44 % (autor) de las negativas es multi-aspecto, y la mitad de las de 20 palabras o más, lo que favorece tópicos por cláusula o ABSA multi-etiqueta sobre un tópico por reseña. Las negativas cortas casi nunca son multi-aspecto, pero sí nombran un problema concreto; `TOPIC_TOO_SHORT` con k = 1 (ver 5.1). Con la guía `v2.1`, las familias más frecuentes son falla general (29.5 %), acceso (24.4 %), transferencias (13.7 %), productos (11.5 %) y lentitud (10.6 %), y el multi-aspecto es 24.7 %. Para codificar aspectos con Gemini está la [guía de aspectos `v2.1`](../analytics/eda/eda_aspects_guideline.md) (validada por el autor; prompt `aspects_v2_1`), que reemplaza `DS` (κ 0.39 en `v1`) por `DV` y `UX` (κ 0.74 cada una), pasa la instalación y la actualización a `CO` y el token a `AC`, y agrega las marcas `u` (actualización, κ 0.70) y `s` (seguridad, no concluyente).
* **Entregable:** recomendación con su costo de operación (frecuencia de re-clustering, curaduría humana, estabilidad de identificadores de tópico). **Aprobada (2026-10-22):** [reporte, sección 5](../analytics/topics/topics_report.md#5-recomendación-aprobada-por-el-autor-2026-10-22) y [nota para 5.8](../analytics/topics/topics_decision_note.md). Pasaron a 5.9 los umbrales de la señal y el análisis por versión; a 5.7, el emparejamiento de tópicos entre reajustes y el monitoreo de `OT` (P7-8); a 5.8, el modelo de sentimiento del que dependen las familias (P8-1, resuelto: M4).

### FEATURE 5.6: Calibración, Incertidumbre, HITL y Priorización

> **Cerrada (2026-10-22).** [Plan](../analytics/calibration/calibration_design.md) y [reporte](../analytics/calibration/calibration_report.md). Todo se hizo con el oro *dev* (el *test* sigue intacto), la plata y una muestra nueva sin etiqueta; código en `voc_analytics.calibration`.

**Objetivo:** dejar calibradas las probabilidades, fijar la revisión humana, estimar proporciones poblacionales con intervalos válidos y decidir cómo se prioriza (Q4).

* **Calibración (decisión del autor):** *temperature scaling* con una T por semilla de M4 (≈ 1.7). M4 está sobreconfiado (confianza 0.995 y acierto 0.972); el ECE baja de ~0.025 a ~0.01 sin cambiar la exactitud. *Vector scaling* se descartó.
* **Umbral HITL de sentimiento (decisión del autor):** probabilidad máxima calibrada, **90 % de cobertura por defecto** como parámetro configurable. Se revisa el ~10 % menos seguro (~350 textos únicos por semana, 40–60 min) y el error entre lo aceptado baja de 2.8 % a 0.4 %. Revisar más del 10 % casi no mejora. Es un costo de operación del escenario de producción, no una carga semanal del autor; para la tesis basta una validación única. La curva y el parámetro son estado de la aplicación (EPIC-6, 6.1 a 6.4; EPIC-7, 7.10).
* **Descartes:** el ensamble de 3 semillas, BETO para el HITL, el disparador por impacto (4–5★, `NEG` y votos ≥ 5) como señal de error y la marca `duda` de Gemini (0 de 199).
* **PPI** (decisión del autor: medir con Gemini y con M4): los intervalos poblacionales son 2 a 4 veces más estrechos que con el oro solo, con cualquiera de los dos predictores (estrellas distintas del texto: 11.6 % [10.5, 12.6] con Gemini y 11.7 % [10.6, 12.8] con M4). Para M4 se usó una muestra nueva del snapshot (`ppi_v0`, 69 534 textos sin plata ni oro), porque M4 se entrenó con la plata.
* **Modelos con pesos:** el lote `m4_ppi` de Kaggle reentrenó M4 RoBERTuito con las semillas 1 a 3 y **guardó los pesos** (218 MB cada uno en fp16, `data/models/weights/`, fuera de git). Reproducen a 5.4 (κ 0.912–0.923) y son los candidatos desplegables.
* **Priorización, Q4 (decisión del autor):** volumen de negativas por familia y marca `u`, en nivel y en anomalía. La fórmula anterior (`priority_weight_score`) ordena los incidentes igual que contar negativas, y los votos empeoran el orden (se acumulan con el tiempo), así que salen del contrato; los votos se muestran como contexto.
* **Límite:** en los casos difíciles (*dev* dirigido) el error sigue en 17–23 % aun revisando el 20 %.
* **Pasa a otras features:** D1 (cuándo la deriva o un tema nuevo suben la revisión) a 5.7 ([P7-6](#decisiones-pendientes), decidido); la priorización errónea quedó en la FMEA como F-17 (por calificar), y la validación única de la cola HITL pasa a 5.9.

### FEATURE 5.7: Escala, Ciclo de Vida y Monitoreo

> **Cerrada (2026-10-22).** [Plan](../analytics/scale/scale_design.md) (E1: medir en Cloud Run; E2: medir int8; E3: periodo de referencia por banco, no fecha común) y [reporte de 5.7](../analytics/scale/scale_report.md). Código en `voc_analytics.scale`. Todos los recursos temporales en GCP se borraron.

**Objetivo:** medir el tiempo y el costo de operar el pipeline y fijar cómo se versionan, promueven y vigilan los modelos.

* **Benchmark de inferencia (P7-1, P7-2; reporte §1):** M4 en Cloud Run con 1 vCPU, ordenado por longitud, hace 22.6 textos/s en fp32 y 27.2 en int8; con 2 vCPU en int8, 88. Ordenar por longitud acelera ~4×. int8 no pierde calidad (κ 0.918 contra 0.912). La memoria pico es de 1.2–1.4 GB, así que 1 GiB no alcanza. El backfill tardaría ~17 h en 1 vCPU y ~9 min en la T4 de Kaggle; el delta diario, ~25 s.
* **Decisiones del autor:** backfill y *re-scoring* completo en Kaggle con un pipeline desde GCP, asumiendo y declarando el riesgo de subir el corpus (P7-1, P7-4); delta diario en Cloud Run con 1 vCPU y 2 GiB (P7-2); Vertex Model Registry, con alias para promover y regresar (P7-3; reporte §6); subidas automáticas de la revisión HITL solo para el banco que alertó (P7-6); muestra humana de monitoreo y re-ajuste trimestral de tópicos como parámetros de la política de riesgo global (P7-7, P7-8); umbrales de deriva por banco en `drift_policy` (P7-9); reentrenamiento de M4 si el κ trimestral cae debajo de 0.89 y revalidación de las familias al cambiar Gemini (P7-10, P7-11; reporte §8).
* **Línea base de deriva (E3; reporte §2):** las tasas de alerta son mucho más altas en los años de arranque de cada banco. Con la regla propuesta (12 meses seguidos con al menos 200 filas) cada banco entra al monitor en su propio mes: BBVA 2016-04, AZTECA 2018-09, BANORTE 2018-10, SANTANDER 2019-04 y NUBANK 2021-12. Con z ≥ 4, cada serie alerta de 0 a 1.4 meses al año por banco (tabla por banco en el reporte). Estos umbrales son la plantilla de la **`drift_policy` de cada banco** (P7-9); la política HITL (`risk_policy`) es global.
* **Costos medidos para 5.8:** familias con Gemini, $0.091 por 1 000 textos (~$72 el llenado histórico; reporte §3); explicabilidad precalculada para el HITL, ~9 min de CPU por semana (§4); `VECTOR_SEARCH` en BigQuery, 4.26 GB por búsqueda sobre todo el corpus y ~0.5 GB con una ventana de 12 meses en una tabla particionada (§5 y §5.1).
* **Propuesta de ciclo de vida y monitoreo:** reporte §7 (candidato, registro, promoción, rollback y política HITL; umbrales del monitor por nivel).
* **Backfill de M4 (P7-1, hecho en 5.8; [reporte §9](../analytics/scale/scale_report.md#9-backfill-de-m4-en-kaggle-p7-1-58-2026-10-22)):** 1 429 675 textos únicos con las 3 semillas, 346–357 s de T4 por semilla y 27 min de preparación. `s1` va a producción y las predicciones quedan en local para 5.9.
* **Heredado de 5.5 y 5.6:** el emparejamiento de tópicos entre reajustes y el monitoreo de `OT` quedan en P7-8; los umbrales de la señal de incidentes y el análisis por versión pasaron a 5.9.

### FEATURE 5.8: Registro de Decisión

> **Cerrada (2026-10-22).** [`decision_record.md`](../analytics/decision_record.md) aprobado, con la evidencia de 5.2–5.7 y P8-1 a P8-12 decididas.

**Objetivo:** fijar la estrategia de producción con la evidencia de 5.2–5.7 antes de EPIC-6 y EPIC-7.

* **Modelo de sentimiento (P8-1, P8-2):** evaluación única en el oro *test*, con protocolo y regla aprobados antes de mirarlo. Ganó M4 RoBERTuito (κ 0.929 contra 0.943 de M9, sin diferencia significativa). La licencia no comercial se acepta para la tesis.
* **Elegibilidad (P8-3, P8-4):** [`eligibility_rules_v1`](../analytics/eda/eligibility_rules.md) publicada con sus conteos.
* ***Satisfaction Gap* y estimaciones (P8-9, P8-10):** *gap* en estrellas con PPI, +0.21 [0.17, 0.24]; series crudas y KPI con PPI.
* **Frontal y esquema (P8-12, P8-5, P8-11):** EPIC-7 reescrita con el alcance por niveles; el [esquema v3](../contracts/analytics_outputs_v3_draft.md) se revisó pantalla por pantalla.
* **Búsqueda, explicabilidad y familias (P8-6 a P8-8):** MiniLM en BigQuery `VECTOR_SEARCH`, oclusión fuera de la pantalla HITL y familias con Gemini en GCP.
* **Gobierno:** [Model Card](../governance/model_card.md) 0.1 y filas F-14 a F-20 de la [FMEA](../governance/ethical_fmea_matrix.md) (F-15 a F-20 por calificar).
* **Backfill de M4 (P7-1):** hecho; `M4_robertuito_s1_ppi` va a producción y la carga a BigQuery es de EPIC-6 (6.2, 6.3) ([reporte de 5.7, §9](../analytics/scale/scale_report.md#9-backfill-de-m4-en-kaggle-p7-1-58-2026-10-22)).
* **Incompatibilidades:** todas resueltas ([tabla](#incompatibilidades-entre-el-diseño-de-epic-6-y-epic-7-y-la-evidencia)).
* **Sigue:** EPIC-6 y EPIC-7 pueden empezar; solo 6.4 y la pestaña por versión (7.5) esperan a 5.9.

### FEATURE 5.9: Incidentes y versiones con la estrategia elegida

> **Lista para empezar (5.8 cerrada el 2026-10-22).** Usa solo la estrategia elegida: sentimiento con M4 `s1` (P8-1) y familias con Gemini `aspects_v2_1` (P8-7). Va después de 5.8 para no predecir con un modelo que la decisión podía descartar.

**Objetivo:** validar la señal de incidentes fuera de BBVA y medir el efecto de cada versión de la app, con datos suficientes y el predictor de producción.

**Datos disponibles (en local, fuera de git):**

* sentimiento de M4 `s1` para todo el corpus: `data/backfill/20261022/preds/` (1 429 675 textos únicos, que se unen a las filas por `text_key`);
* familias y marca `u` en dos muestras: las 40 382 negativas de la plata (`NEG` de Gemini, 5.5) y las 39 635 de `ppi_v0` (`NEG` de M4, [reporte de 5.7, §3](../analytics/scale/scale_report.md#3-costo-de-las-familias-con-gemini-p8-7)). Juntas son ~10 % de las ~788 000 negativas únicas.

Tareas:

0. **Preparación.** Unir el snapshot con `preds_s1`, medir la cobertura y aplicar `eligibility_rules_v1`. Series crudas, como el monitor (P8-10). Revisar que las negativas de las dos muestras sean comparables (Gemini en la plata, M4 en `ppi_v0`).
1. **Meses candidatos a incidente en los 5 bancos (P9-1).** Hoy solo hay 3 incidentes etiquetados, todos de BBVA; en 5.5, el 11 % de los demás meses × banco tuvo alguna alerta y no se sabe cuántas son reales.
   * Señal: volumen y proporción de `NEG` con el corpus completo; marca `u` y familias con la cobertura que fije P9-3; en nivel y en anomalía (z contra los 12 meses previos, con la entrada al monitor de P7-9).
   * Entregable: por banco, los meses con más alerta, con la familia dominante, el tamaño de la muestra y su IC.
   * El autor marca cuáles fueron incidentes reales. Con esa lista se fijan los umbrales (P9-1), se mide la precisión fuera de BBVA (dejando fuera un banco a la vez) y se califica F-19.
   * **Sesgo de selección:** los candidatos salen de la misma señal, así que no muestran lo que la señal omite. El autor investiga por su cuenta los incidentes conocidos de los 5 bancos en fuentes externas, y con esa lista se estima el recall.
2. **Análisis por versión (P9-2).** En 5.5 la plata no alcanzó para comparar versiones (JSD dominada por el ruido de muestreo).
   * Sentimiento con el backfill de M4 (corpus completo); familias y marca `u` con la cobertura de P9-3.
   * Entregable: por banco y versión normalizada (`topics/versions.py`), la proporción de `NEG` y de la marca `u` con IC, el efecto de los días desde la versión en el sentimiento (no solo en la marca `u`) y qué versiones se separan de su línea base, con corrección por comparaciones múltiples.
3. **Validación única de la cola HITL (heredada de 5.6).** El autor revisa una vez la cola de una semana del backfill con el umbral del 90 %, antes de la presentación ([plan de 5.6](../analytics/calibration/calibration_design.md)).

* **Consume:** 5.8 (predictor, familias, reglas). **Alimenta:** EPIC-6, 6.4 (umbrales del monitor y de las alertas); EPIC-7, pestaña por versión (7.5); Model Card (límite 7) y FMEA (F-19). Las features 6.1 a 6.3 no dependen de 5.9 y pueden empezar ya.

<a id="decisiones-pendientes"></a>

## 🗂️ Registro de decisiones

Seguimiento de las decisiones del autor de 5.7 a 5.9. La columna "Bloquea" dice qué feature depende de cada una. El [`decision_record.md`](../analytics/decision_record.md) junta todo por tema, con su evidencia. Actualizado: 2026-10-22.

**Resumen:**

| Bloque | Decididas | Pendientes |
| :--- | :--- | :--- |
| 5.7 | P7-1 a P7-4 y P7-6 a P7-11 | Ninguna (cerrada) |
| 5.8 | P8-1 a P8-12 (P8-5 y P8-11 con la condición del frontal cumplida) | Ninguna (cerrada) |
| 5.9 | P9-1 (criterio) y P9-2 | P9-3 |

### Decididas (5.7 y 5.8)

Historia compacta. Las opciones y la evidencia de cada una están en el [registro de decisión](../analytics/decision_record.md) y en los reportes de 5.6 y 5.7.

| ID | Decisión | Resultado (2026-10-22) | Bloquea |
| :--- | :--- | :--- | :--- |
| P7-1 | Entorno del backfill | Kaggle T4 con un pipeline desde GCP; riesgo de subir el corpus aceptado (F-14). Primer backfill hecho: `s1` en producción ([reporte de 5.7, §9](../analytics/scale/scale_report.md#9-backfill-de-m4-en-kaggle-p7-1-58-2026-10-22)) | 6.2, 6.3 |
| P7-2 | Recursos del delta diario | Cloud Run Job de 1 vCPU y 2 GiB (~25 s por 500 textos) | 6.2 |
| P7-3 | Registro de artefactos | Vertex Model Registry, con alias para promover y regresar | 6.2, 6.4 |
| P7-4 | Promoción, rollback y *re-scoring* | Re-predecir todo el histórico en Kaggle al promover; `model_version` por predicción y las anteriores conservadas | 6.3, 6.4 |
| P7-6 | Subida de la revisión HITL por deriva o tema nuevo | Automática, solo para el banco que alertó (`hitl_boosts`), con las reglas de la `risk_policy` global | 6.4, 7.10 |
| P7-7 | Monitoreo de concepto | Muestra humana periódica; tamaño y frecuencia configurables en la `risk_policy` | 6.4 |
| P7-8 | Re-ajuste de tópicos | Trimestral, con emparejamiento por centroides; frecuencia configurable | 6.4, 7.7.1 |
| P7-9 | Umbrales del monitor de deriva | Por banco en `drift_policy`, desde una plantilla: z ≥ 4, PSI ≥ 0.25 en la longitud y entrada con 12 meses seguidos de ≥ 200 filas | 6.4 |
| P7-10 | Desempeño de M4 | Reentrenar si el κ trimestral (300 revisiones) baja de 0.89; avisos: corrección > 28 % y acuerdo M4–Gemini < 94 % | 6.4 |
| P7-11 | Calidad de las familias de Gemini | Al cambiar modelo o prompt, repetir `muestra_v21` y aceptar con acuerdo exacto ≥ 53 % | 6.3, 6.4 |
| P8-1 | Modelo de sentimiento | **M4 RoBERTuito**, con la regla aprobada antes del *test*: κ 0.929 contra 0.943 de M9; M9 − M4 de +0.010 a +0.017, con todos los IC conteniendo el 0, y sin diferencia en `NEG` | 6.1–6.3, 7.1, 7.2 |
| P8-2 | Licencia del modelo | RoBERTuito para la tesis; el límite comercial va en la Model Card y en la FMEA (F-16) | P8-1, 7.5 |
| P8-3 | `TNSS_SINGLE_WORD` | Léxico determinista para las cubiertas (95.3 %) y exclusión del resto | 6.1, 6.3 |
| P8-4 | Reglas de elegibilidad | `eligibility_rules_v1` publicada con sus conteos | 6.1, 6.3 |
| P8-5 | Esquema de salida y migración | [Esquema v3](../contracts/analytics_outputs_v3_draft.md) aprobado; cubre el frontal de EPIC-7, revisado pantalla por pantalla | 6.1, 6.2, 7.1 |
| P8-6 | Búsqueda semántica | MiniLM (384) en BigQuery `VECTOR_SEARCH`, tabla particionada por mes, ventana de 12 meses por defecto | 6.2, 7.1, 7.3, 7.4 |
| P8-7 | Familias en producción | Gemini `aspects_v2_1` en GCP; llenado histórico ~$72 | 6.1, 6.3 |
| P8-8 | Explicabilidad | Oclusión precalculada para la cola HITL y bajo pedido; solo en la ficha del Explorador (7.6), nunca en el HITL | 7.1, 7.6 |
| P8-9 | *Satisfaction Gap* | *Gap* en estrellas: promedio de estrellas menos el puntaje del texto (`NEG` = 1, `NEU` = 3, `POS` = 5), con PPI; +0.21 [0.17, 0.24] | 7.1, 7.4, 7.6 |
| P8-10 | Estimaciones del portal | Crudas en las series diarias; PPI en los KPI por banco y periodo | 7.1, 7.4 |
| P8-11 | Registro de las revisiones | Tablas `hitl_items`, `hitl_events` y `hitl_reviews`; se elimina `hitl_triage_audit_log` | 6.1, 6.2, 7.2 |
| P8-12 | Alcance de EPIC-7 | Por niveles: imprescindible, importante y deseable ([mapa del portal](epic_7.md#mapa-del-portal)) | 7.1–7.12 |

### Para 5.9

| ID | Decisión | Opciones | Evidencia hoy | Propuesta | Bloquea |
| :--- | :--- | :--- | :--- | :--- | :--- |
| P9-1 | Umbrales de la señal de incidentes | z, línea base, mínimo de filas por mes | 5.5: la marca `u` detecta 2 de 3 incidentes con 4 % de falsas alarmas; solo 3 incidentes etiquetados, todos de BBVA | **Decidido por el autor (2026-10-22):** fijarlos con datos: la lista de meses candidatos de los 5 bancos que valide el autor (tarea 1 de 5.9), más su lista de incidentes de fuentes externas para estimar el recall | 6.4 |
| P9-2 | Datos para el análisis por versión | Plata + `ppi_v0`; backfill de M4 | 5.5: con la plata sola domina el ruido; el backfill de M4 ya está en local (5.8) | **Decidido por el autor (2026-10-22):** sentimiento con el backfill de M4 y familias con la cobertura de P9-3. Queda abierta la opción de un backfill de familias y tópicos si P9-3 lo pide | 5.9, 7.5 |
| P9-3 | Cobertura de familias y marca `u` para la señal | Muestras actuales (~80 000 negativas, $0); muestra estratificada por banco y mes (~$10); backfill completo de familias (~$72, Gemini en GCP, reutilizable en 6.3) y, si hace falta, de tópicos | ~10 % de las ~788 000 negativas únicas tiene familias | **Para empezar (autor, 2026-10-22):** las muestras actuales. Se considera el backfill completo, que de todos modos hará falta en producción (P8-7); se decide con los IC de la marca `u` por mes, y el gasto requiere la autorización del autor | 5.9, 6.3 |

### Incompatibilidades entre el diseño de EPIC-6 y EPIC-7 y la evidencia

Piezas del texto original de EPIC-1, EPIC-2 y EPIC-7 que chocaban con lo decidido en EPIC-5. **Todas resueltas (2026-10-22);** la columna "Estado" dice dónde se reescribe cada una.

| Pieza (dónde) | Choca con | Estado |
| :--- | :--- | :--- |
| `AnalyzedReviewPrediction` con `sentimiento_roberta` y docstring "DeLoRA" (EPIC-1) | Delora descartado (5.4) | Resuelta con P8-1 (M4 RoBERTuito, 2026-10-22); se reescribe en 6.1 |
| `ABSATopic` único por reseña (EPIC-1; EPIC-7 anexo B.1, B.2, B.4, B.6) | Familias multi-etiqueta `v2.1` y marcas `u` y `s` (5.5) | Resuelta en 5.5; se reescribe en 6.1 |
| `MIN_REVIEW_WORDS`/`MAX_REVIEW_WORDS = (2, 60)` (EPIC-1; EPIC-7 anexo B.2 "de 2 a 60 palabras") | Sin filtro de longitud (5.2); elegibilidad por reglas | Resuelta con P8-3 y P8-4: `eligibility_rules_v1` publicada con sus conteos (2026-10-22); se reescribe en 6.1 |
| `priority_weight_score`, `tnss_numeric_calibrated` y `prediction_entropy` (EPIC-1; EPIC-7 anexo B.1, B.2) | Priorización por volumen y marca `u`; HITL por probabilidad máxima calibrada (5.6) | Resuelta en 5.6; se reescribe en 6.1 |
| `delora_predictions` de 15 columnas agrupada por `topico` (EPIC-2) | Esquema versionado por modelo, calibración y política HITL | Resuelta con P8-5 (la condición del frontal se cumplió el 2026-10-22): se elimina; se reescribe en 6.1 y 6.2 |
| `embedding_vector` de 768 dimensiones e índice de Vertex de 768 (EPIC-2; EPIC-7 anexo B.1, B.3, B.6) | Delora descartado; MiniLM de 384 en tópicos | Resuelta con P8-6: MiniLM de 384 en BigQuery, tabla particionada por mes; se retira el índice de Vertex. Se reescribe en 6.2 y 7.1 |
| `hitl_entropy_threshold = 0.65` en `Settings` (EPIC-1; EPIC-7 objetivo y anexo B.5) | 90 % de cobertura como política versionada (5.6) | Resuelta en 5.6; se reescribe en 6.1 y 7.10 |
| `hitl_triage_audit_log` con `original_topic`/`validated_topic` (EPIC-2; EPIC-7 anexo B.2) | Curadurías de sentimiento, aspectos y tópicos (5.5) | Resuelta con P8-11: se elimina; las tablas nuevas se revisaron contra el frontal (2026-10-22) |
| *Satisfaction Gap* como estrellas menos TNSS continuo, prueba con gap −1.11 (EPIC-7 anexo B.1, B.6) | `tnss_numeric_calibrated` descartado (5.6); P8-9 decide estrellas menos el puntaje 1/3/5 por clase, con PPI (*gap* positivo, ~+0.21) | Resuelta en 5.8 (P8-9); ya reescrita en EPIC-7 (7.5) |
| Explicador de < 150 ms en 1 vCPU y 1 GiB (EPIC-7 anexo B.2) | Velocidad medida de M4 en CPU | Resuelta con P8-8: oclusión precalculada para la cola HITL y bajo pedido, mostrada solo en el Explorador (7.6) |
| Model Card con Delora, paridad dialectal sintética y umbral 0.65 (EPIC-7 anexo B.5) | 5.4 y 5.6 | Resuelta: [Model Card](../governance/model_card.md) 0.1 escrita en 5.8 (2026-10-22) |
| FMEA: "Label Noise mitigado por Dual LoRA" y "priorización mitigada por entropía ≥ 0.65" (EPIC-7 anexo B.5) | M4 ajustado con la plata; HITL por cobertura | Resuelta: filas F-17 (priorización con predicciones inciertas) y *Label Noise Bias* confirmada con el oro *test* (2026-10-22); F-17 queda por calificar |
| *Concept drift* con JSD de 8 tópicos y umbrales PSI 0.25 / JSD 0.20 (anexo de EPIC-6, A.7) | Familias y marca `u` (5.5); línea base de 5.7 | Resuelta para la deriva con P7-9 (`drift_policy` por banco, 5.7); los umbrales de la señal de incidentes pasan a 5.9 (P9-1) y no bloquean el cierre de 5.8 |
| Backfill "dentro de GCP" contra la medición en Kaggle | Principio de que los datos no salen de GCP | Resuelta con P7-1: backfill en Kaggle con riesgo aceptado y declarado en la FMEA; en producción, todo en GCP |
| IAM de Vertex AI para el modelo de producción (EPIC-6 6.2) | Las familias usan Gemini en GCP (P8-7) y el registro es Vertex (P7-3) | Resuelta: `voc-sa-ml-backend` necesita Vertex AI para Gemini y el registro; M9 solo cambia el volumen |

---


<a id="siguientes-pasos"></a>

## 🧭 Siguientes pasos

En orden. Los pasos 1 a 13 están hechos (2026-10-20 a 2026-10-22), de 5.2 a 5.8; su detalle está en los reportes de cada feature y en la historia de git.

| # | Paso | Dueña | Depende de | Terminado cuando |
| :---: | :--- | :---: | :--- | :--- |
| 14 | **5.9, preparación:** unir el snapshot con el backfill de M4, aplicar `eligibility_rules_v1` y armar las series por banco y mes | 5.9 | — | Cobertura medida y series listas |
| 15 | **5.9, meses candidatos (P9-1):** señal en los 5 bancos, lista para el autor, umbrales y precisión fuera de BBVA | 5.9 | 14; lista externa del autor; P9-3 | Lista validada, umbrales fijados y F-19 calificada |
| 16 | **5.9, análisis por versión (P9-2):** proporción de `NEG` y de la marca `u` por versión, con IC | 5.9 | 14; P9-3 | Efecto por versión con IC |
| 17 | **5.9, validación única de la cola HITL** (heredada de 5.6) | 5.9 | 14 | Cola de una semana revisada por el autor |
| 18 | **EPIC-6:** detallar las features a partir del registro (sesión paralela) | EPIC-6 | — | [`epic_6.md`](epic_6.md) detallada; 6.4 a la espera de 5.9 |
| 19 | **Cierre de EPIC-5** | EPIC-5 | 15–17 | Criterios de cierre del checklist |

---

## 💻 Cómputo y presupuesto

| Tarea | Dónde | Costo |
| :--- | :--- | :--- |
| EDA, deduplicación, muestreo y modelos lineales | Mac M2 8 GB (polars/duckdb, CPU) | $0 |
| Etiquetas de plata y M9 (5.3, 5.4) | Vertex AI, `gemini-3.6-flash` | Medido: plata v0 $3.37 por 70 284 textos. M9 no se eligió (P8-1) |
| Codificación de aspectos (5.2) | Vertex AI, `gemini-3.6-flash` | Medido: $0.17 por dos rondas de 1 434 textos negativos (`aspects_v0` y `aspects_v1`); $0.17 y $0.16 en `aspects_v2` y `aspects_v2_1` (guía `v2.1`); $3.64 por las 40 382 negativas de la plata en 5.5 (vía B a escala) |
| Ajuste de encoders y semillas | Kaggle (~30 h/semana de GPU, no garantizadas); el Mac solo para validar el pipeline (M4 en 46–48 min, una semilla). Medido en la T4: M4 y M5 ~6 min por corrida; M8 ~1 h por semilla | $0 |
| Backfill de M4 (2.65 M filas, 1 429 675 textos únicos) | Kaggle T4 con pipeline desde GCP (P7-1) | Medido (5.8): 346–357 s de GPU por semilla más 27 min de preparación ($0); en Cloud Run serían ~17 h con 1 vCPU |
| Delta diario | Cloud Run Job de 1 vCPU y 2 GiB (P7-2; free tier: 180 000 vCPU-s/mes) | Medido: ~25 s por 500 textos ($0) |
| Familias con Gemini (P8-7) | Vertex AI, `gemini-3.6-flash` | Medido: $3.60 por 39 635 negativas de `ppi_v0` ($0.091 por 1 000); llenado histórico ~$72 (precio introductorio hasta el 2026-12-31) |
| Búsqueda semántica (P8-6) | BigQuery `VECTOR_SEARCH` | Medido: 4.26 GB por búsqueda sobre todo el corpus; ~0.5 GB con ventana de 12 meses (free tier: 1 TiB al mes) |
| Benchmarks de 5.7 | Cloud Run, Cloud Build, BigQuery y Vertex | Recursos temporales, borrados al terminar |
| Incidentes y versiones (5.9) | Mac (polars, CPU) con el backfill de M4; Vertex AI si P9-3 elige el backfill de familias | $0 con las muestras; ~$72 el backfill de familias (requiere autorización del autor) |

Crédito disponible: ~$5 000 MXN. La restricción del etiquetado es el tiempo humano, no el gasto. Las cifras de throughput, costo y duplicados de la literatura o de conversaciones con otros LLM no se usan para decidir hasta medirlas.

---

## ⚠️ Riesgos y limitaciones a declarar

Los límites del modelo están en la [Model Card](../governance/model_card.md), sección 5: licencia, `NEU`, casos difíciles, criterio de Gemini, anotador único, familias de Gemini, señal de incidentes, `fecha` de última edición, PII residual, corpus fuera de GCP, paridad dialectal y representatividad. Cada riesgo tiene su fila en la [FMEA](../governance/ethical_fmea_matrix.md) (F-01 y F-10 a F-20). Aquí quedan solo los del proceso de EPIC-5:

* **El ruido de las estrellas depende de la instancia y del periodo** (NoisyAG-News, 2024): los resultados con ruido sintético no transfieren.
* **Las etiquetas de plata heredan sesgos de Gemini** (sarcasmo, jerga bancaria mexicana, `NEU`); solo el oro sirve para reportar.
* **Los tópicos dinámicos requieren curaduría humana continua;** sin ella pierden identidad entre corridas (P7-8).
* **La señal de incidentes es ilustrativa hasta 5.9:** se probó con 3 incidentes de un solo banco (F-19).
* **El corpus sigue en Kaggle hasta cerrar EPIC-5** (F-14): el dataset `voc-backfill-corpus` se conserva por si hace falta otra corrida y se borra al cerrar la épica.

---

## ✅ Checklist de Aceptación de la Épica 5 (fases 1 y 2)

* [x] Guía de anotación, reglas deterministas de elegibilidad por tarea (con códigos, precedencia y versión) y envolvente de costo aprobados (5.1). *Guía `v2.2`; [`eligibility_rules_v1`](../analytics/eda/eligibility_rules.md) aprobada (P8-3, P8-4) y publicada con sus conteos (2026-10-22); costos de etiquetado, inferencia y familias medidos.*
* [x] Reporte de cobertura por banco × periodo × motivo, y decisión sobre `TNSS_SINGLE_WORD` (excluir o léxico determinista) con su sesgo medido (5.2, 5.8). *Excluirlas todas sesga de −0.10 a −0.21 estrellas por banco; el léxico (95.3 % de cobertura, 99 % de exactitud) con exclusión del resto deja de −0.001 a −0.007 (P8-3). Cobertura con las reglas `v1` en [`eligibility_v1_counts.json`](../analytics/eda/eligibility_v1_counts.json).*
* [x] EDA global de los 5 bancos y 15 años, con reglas de limpieza versionadas y Data Card actualizada (5.2). *EDA global, temporal y segunda pasada hechos; limpieza decidida en 5.4; Data Card `v0.2` con el EDA completo, el oro, la plata y los aspectos.*
* [x] Conjunto de plata con prompt, modelo y costo versionados; conjunto de oro con bloque aleatorio documentado y medición de anclaje (5.3).
* [x] Al menos M0–M7 evaluados con el mismo protocolo; M8 y M9 evaluados o descartados con motivo (5.4). *M4 RoBERTuito es el mejor modelo propio; M5 y M8 descartados con motivo; 5.8 eligió M4 frente a M9 con el oro *test*.*
* [x] Decisión sobre ABSA, tópicos dinámicos o híbrido, con una señal de incidentes probada hacia atrás (5.5). *Híbrido aprobado por el autor (2026-10-22): familias `v2.1` y marca `u` como núcleo y alerta, tópicos como capa de detalle curada; señal probada con los 3 incidentes de BBVA ([reporte](../analytics/topics/topics_report.md), sección 5).*
* [x] Calibración y umbral HITL elegidos por cobertura–riesgo (5.6). *Temperature scaling (T ≈ 1.7) y 90 % de cobertura por defecto como parámetro configurable; PPI y priorización decididos ([reporte](../analytics/calibration/calibration_report.md)).*
* [x] Benchmark de escala, propuesta de ciclo de vida y plan de monitoreo (5.7). *Benchmark en Cloud Run, ciclo de vida y monitoreo ([reporte de 5.7](../analytics/scale/scale_report.md), §1 y §7); P7-1 a P7-4 y P7-6 a P7-11 decididas.*
* [x] Registro de decisión ([`decision_record.md`](../analytics/decision_record.md)) aprobado, con P8-1 a P8-12 decididas (5.8, 2026-10-22). Detallar [EPIC-6](epic_6.md) a partir de él es la primera tarea de EPIC-6.
* [ ] Lista de incidentes de los 5 bancos validada por el autor, umbrales de la señal y efecto por versión, con la estrategia elegida, y validación única de la cola HITL (5.9).
* [x] Experimentos reproducibles en `experiments/analytics/` (proyecto `uv` propio, semillas fijas), sin dependencias de experimentación en el `uv.lock` de producción.
* [ ] Cierre de EPIC-5 (por confirmar con el autor): dataset `voc-backfill-corpus` borrado de Kaggle (F-14); destino del snapshot local decidido (F-11); filas F-15 a F-20 de la FMEA calificadas o asignadas a EPIC-6 y EPIC-7.
