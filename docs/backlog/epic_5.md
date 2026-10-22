# EPIC-5: Planteamiento Analítico y Experimentación del Core NLP

* **Estado (2026-10-22):** En curso, fase 2. Cerradas: el EDA (5.2, 2026-10-21, con la guía de aspectos `v2.1`), el etiquetado (5.3: oro de 1 730 ítems y plata `silver_v0`), la experimentación de modelos (5.4: M4 RoBERTuito, κ 0.917; M4 contra M9 se decide en 5.8) y los tópicos (5.5, 2026-10-22: híbrido aprobado por el autor y `TOPIC_TOO_SHORT` k = 1). 5.6 cerrada (2026-10-22: calibración, HITL al 90 %, PPI y priorización). 5.7 cerrada (2026-10-22: benchmark en Cloud Run, ciclo de vida, monitoreo y costos medidos). 5.8 con el borrador del registro de decisión ([`decision_record.md`](../analytics/decision_record.md)) y 5 decisiones pendientes. Sigue 5.9 (incidentes y versiones con la estrategia elegida), después de 5.8. Ver el [registro de decisiones](#decisiones-pendientes). Los frontales de curaduría HITL (sentimiento, aspectos y tópicos) pasan a EPIC-7 (7.7) y su base de datos a EPIC-6 (6.2). Ver [estado por feature](#-estado-por-feature) y [siguientes pasos](#siguientes-pasos).
* **Historia de los resultados:** [`docs/analytics/README.md`](../analytics/README.md) ordena los reportes como una historia y dice qué cifra está vigente. Este documento solo guarda el planteamiento, el estado y lo que falta; la cronología detallada está en los reportes.
* **Fases:** (1) planteamiento analítico viable → (2) experimentación para elegir la estrategia de producción → (3) despliegue de la estrategia elegida. Desde la reorganización del backlog (2026-10-22), la fase 3 es [EPIC-6](epic_6.md), que conserva la especificación anterior como anexo no vigente y se detalla tras el registro de decisión (5.8).
* **Semanas Objetivo:** Semanas 4 - 6 (fases 1 y 2).
* **Dependencias:** EPIC-1 a EPIC-4 cerradas ([cierre](epics.md#cierre-de-las-épicas-1-a-4)). Corpus: `bbva_voc_tds.sanitized_reviews_tds`, **2 649 047 reseñas** de BBVA, NUBANK, SANTANDER, AZTECA y BANORTE (2011-04 a 2026-10), con `source_observed_at`. Bibliografía: [`references.md`](../governance/references.md).
* **Directorios:**
  * `experiments/analytics/`: proyecto `uv` **independiente del workspace** (su propio `pyproject.toml` y `uv.lock`), para que las dependencias de experimentación no entren al lock de producción. El código es el paquete `voc_analytics` (`src/`), agrupado por etapa: `snapshot`, `eda`, `labeling`, `sampling`, `annotation`, `analysis`, `sentiment`, `topics`, `calibration` (5.6) y `scale` (5.7). Comandos en su [README](../../experiments/analytics/README.md).
  * `docs/analytics/`: reportes por etapa, con las mismas carpetas que el paquete (`eda/`, `labeling/`, `sentiment/`, `topics/`, `calibration/`, `scale/`) y el registro de decisión de 5.8 ([`decision_record.md`](../analytics/decision_record.md), en borrador).
  * `docs/contracts/`: el [borrador de esquemas de salida v3](../contracts/analytics_outputs_v3_draft.md) (P8-5, P8-11).
  * `docs/governance/`: Data Card, Model Card y matriz FMEA se completan con los resultados.

---

## 🎯 Objetivo y principios

Diseñar, con evidencia, el pipeline analítico que responde a cuatro preguntas del caso de uso, y elegir la estrategia de producción **antes** de escribir el paquete desplegable:

| Pregunta | Salida candidata | Feature |
| :--- | :--- | :---: |
| Q1. ¿Cuál es el sentimiento real del texto, separado de las estrellas? | Polaridad por reseña (M4 o M9, P8-1) y brecha frente a las estrellas (*Satisfaction Gap* simétrico, P8-9). Medido en 5.6: el texto es más negativo que las estrellas en el 10.5 % de las reseñas y más positivo en el 0.9 % | 5.4, 5.6 |
| Q2. ¿Qué temas recurrentes hay en las quejas y cómo cambian en el tiempo? | Familias de aspectos `v2.1` (núcleo) y tópicos curados (detalle) sobre las reseñas negativas, por banco y periodo. **Resuelta en 5.5** | 5.5 |
| Q3. ¿Cómo detectamos rápido un incidente nuevo? | Marca `u` (problema atribuido a una actualización) y series por familia, por banco y mes; la prueba hacia atrás detecta 2 de 3 incidentes de BBVA. **Resuelta en 5.5** (umbrales en 5.9) | 5.5 |
| Q4. ¿Qué atender primero? | Volumen de negativas por familia y marca `u`, en nivel y en anomalía; los votos solo como contexto. **Resuelta en 5.6** | 5.6 |

Principios:

* **Ningún modelo, dependencia, tópico ni esquema de salida es definitivo** hasta el registro de decisión (5.8). RoBERTuito, Delora y los 8 `ABSATopic` de `voc-common` son **hipótesis** a evaluar, no requisitos. *5.5 reemplazó los 8 `ABSATopic` por las 11 familias `v2.1` (multi-etiqueta, con las marcas `u` y `s`) y los tópicos como capa aparte; Delora se descartó en 5.4.*
* **Las estrellas son una etiqueta ruidosa del sentimiento del texto**, no la verdad. El sentimiento real nunca recibe las estrellas como entrada.
* **Calidad y costo se miden juntos:** con 2.65 M de reseñas, la velocidad y el costo de inferencia son criterio de selección al mismo nivel que la métrica de calidad.
* **Toda cifra de la literatura o de conversaciones con LLM es una hipótesis** hasta medirla sobre este corpus (ver `references.md`, columna *Verif.*).
* **Etiquetado humano limitado:** 1 000 reseñas como base y hasta 2 000 con esfuerzo extra. Nunca se etiqueta el corpus completo; las 2.65 M solo se predicen.

La evidencia inicial sobre el corpus (longitudes, duplicados y deriva por banco y año, 2026-10-16) está en el [capítulo 1 de la historia](../analytics/README.md#1-problema-y-corpus).

---

## 📦 Estado por feature

| Feature | Estado | Reportes |
| :--- | :--- | :--- |
| 5.1 Planteamiento y elegibilidad | Decidido (2026-10-22): `TNSS_SINGLE_WORD` por léxico (P8-3) y reglas `v1` aprobadas (P8-4); falta publicar `eligibility_rules.md` como `v1` con sus conteos | [Reglas](../analytics/eda/eligibility_rules.md), [guía](../analytics/labeling/annotation_guideline.md) |
| 5.2 EDA | **Cerrada (2026-10-21).** EDA global, patrones temporales, tokens, léxico para una palabra (95 % de cobertura) y guía de aspectos `v2.1` (reabierta para 5.5): 11 familias más las marcas `u` y `s`; `UX` pasó de κ 0.55 a 0.74 y `DV` queda separado; multi-aspecto del 24.7 % (32.1 % con `v1`). *Data Card* `v0.2` | [EDA](../analytics/eda/eda_report.md), [temporal](../analytics/eda/eda_temporal_report.md), [guía de aspectos `v2.1`](../analytics/eda/eda_aspects_guideline.md) |
| 5.3 Etiquetado | **Cerrada (2026-10-20).** Oro (1 730 ítems) y plata vigentes; acuerdo entre personas medido (κ 0.81). 5.5 cerró sin usar `menciona_falla` (`prompt_v4` no se necesita). Se reabre si 5.6 o 5.8 necesitan más oro, o si se suman anotadores (guía `v2.3`) | [Capítulo 3](../analytics/README.md#3-etiquetado-guía-pilotos-oro-y-plata) |
| 5.4 Modelos de sentimiento | **Cerrada la experimentación (2026-10-20):** M0–M9 evaluados; M4 RoBERTuito es el mejor modelo propio; M4 contra M9 se decide en 5.8 | [Protocolo](../analytics/sentiment/sentiment_models_protocol.md), [capítulo 4](../analytics/README.md#4-competencia-de-modelos-de-sentimiento) |
| 5.5 Tópicos y ABSA | **Cerrada (2026-10-22).** Recomendación aprobada por el autor, con el agregado de llevar los frontales de curaduría HITL (sentimiento, aspectos y tópicos) a EPIC-7 y su base de datos a EPIC-6. Híbrido: familias `aspects_v2_1` y la marca `u` como núcleo de medición y alerta (la marca `u` detecta 2 de 3 incidentes con 4 % de falsas alarmas; `DV` y `UX` avisaron del rediseño de BBVA un mes antes), y tópicos por cláusulas como capa de detalle curada para producto e ingeniería. Los tópicos no encontraron temas fuera de la taxonomía; cerca de un tercio de su peso es ruido. `TOPIC_TOO_SHORT` con k = 1 (decidido). Costo: ~$0.60 al mes de Gemini y ~30–60 min de curaduría por trimestre | [Plan](../analytics/topics/topics_design.md), [reporte](../analytics/topics/topics_report.md), [nota para 5.8](../analytics/topics/topics_decision_note.md) |
| 5.6 Calibración, HITL y priorización | **Cerrada (2026-10-22).** *temperature scaling* adoptado; umbral HITL al 90 % de cobertura (parámetro configurable); PPI con Gemini y con M4 hecho; M4 reentrenado con pesos guardados (lote `m4_ppi`); priorización por volumen de negativas por familia y marca `u`, sin fórmula anterior ni votos (decisión del autor) | [Plan](../analytics/calibration/calibration_design.md), [reporte](../analytics/calibration/calibration_report.md) |
| 5.7 Escala, ciclo de vida y monitoreo | **Cerrada (2026-10-22).** Benchmark en el Mac y en Cloud Run, línea base de deriva, costos de Gemini, búsqueda vectorial, Vertex Model Registry y explicabilidad medidos; P7-1 a P7-4 y P7-6 a P7-11 decididas (HITL global en `risk_policy`, alertas de deriva por banco en `drift_policy`, reentrenamiento de M4 y revalidación de las familias) | [Plan](../analytics/scale/scale_design.md), [reporte de 5.7](../analytics/scale/scale_report.md) |
| 5.8 Registro de decisión | **En curso (2026-10-22):** borrador del registro listo; decididas P8-1 (criterio), P8-2, P8-3, P8-4, P8-6, P8-7, P8-8, P8-10 y P8-11 (dirección). Faltan la evaluación en el oro *test*, P8-9 y P8-12; P8-5 y P8-11 aprobadas con la condición de cubrir el frontal | [`decision_record.md`](../analytics/decision_record.md), [esquemas](../contracts/analytics_outputs_v3_draft.md) |
| 5.9 Incidentes y versiones con la estrategia elegida | Sin iniciar; depende de 5.8 y de [P9-1 y P9-2](#decisiones-pendientes) | — |

### FEATURE 5.1: Planteamiento, Volumetría y Contrato Analítico

**Objetivo:** fijar qué se predice, sobre qué filas y con qué presupuesto, antes de experimentar.

* **Etiquetas de sentimiento:** decidido. `NEG`/`NEU`/`POS` más la marca `NO_EVALUABLE`, con `menciona_falla`, `duda` y `nombre_persona`; cualquier queja concreta es `NEG`. Ver la [guía `v2.2`](../analytics/labeling/annotation_guideline.md).
* **Reglas deterministas de elegibilidad** ([`eligibility_rules_v0.1`](../analytics/eda/eligibility_rules.md), borrador):
  * se evalúan por fila antes de la inferencia, sin modelos ni aleatoriedad; gana la primera que coincide;
  * la fila excluida queda `NOT_PREDICTED` con su código, se conserva y se reporta por banco × periodo × motivo;
  * la inferencia corre una vez por texto único elegible y se propaga a sus filas;
  * `TOPIC_NOT_NEGATIVE` usa el TNSS **predicho**, nunca las estrellas, así que el backfill de tópicos es posterior al de TNSS;
  * el EDA puede añadir reglas, cada una con código, criterio, conteo y justificación.
* **Decisiones vigentes:** corte de NUBANK en 2020-01-01 (`TNSS_TIME_OUTLIER`, 175 filas); `TNSS_NOT_SPANISH` descartada; `TOPIC_TOO_SHORT` con k = 1 (decisión del autor, 2026-10-22): del análisis de tópicos y familias se excluyen solo las negativas de una palabra ([`topics_report.md`](../analytics/topics/topics_report.md#43-topic_too_short-k--1-se-confirma-con-v21-y-los-5-bancos), sección 4.3).
* **`TNSS_SINGLE_WORD` (decisión del autor, 2026-10-22, P8-3):** las 484 829 filas de una palabra (18.3 %) se asignan con el léxico determinista (`RULE_BASED`; 151 formas cubren el 95.3 % con 99 % de exactitud en el oro *dev*) y se excluyen las no cubiertas, con un sesgo de −0.001 a −0.007 estrellas. Excluirlas todas habría sesgado de −0.10 a −0.21 estrellas por banco. Las reglas `v1` quedan aprobadas (P8-4); falta publicarlas con sus conteos.
* **Envolvente de volumetría y costo:** backfill único sobre ≤ 1.60 M textos únicos (1 383 138 medidos) y delta diario de cientos de reseñas. Cualquier estrategia que no quepa queda descartada aunque gane en calidad. Costos medidos hasta ahora en la [sección de cómputo](#-cómputo-y-presupuesto).
* **Salidas de producción:** el [borrador de esquemas v3](../contracts/analytics_outputs_v3_draft.md) reemplaza a `delora_predictions` y `hitl_triage_audit_log` (las dos están vacías). Se decide en 5.8 (P8-5, P8-11).

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
  * **5.8, `TNSS_SINGLE_WORD`:** 151 formas cubren el 95.3 % de las reseñas de una palabra, con 99 % de exactitud en el oro *dev*; excluir solo las no cubiertas deja un sesgo de −0.001 a −0.007 estrellas.
* **Resuelto en otras features:**
  * proxy de incongruencia estrellas–texto: lo midieron el oro y la plata (5.3);
  * limpieza por familia de modelos: `texto_sanitizado` sin `limpiar_texto_bancario` (5.4).

### FEATURE 5.3: Estrategia de Etiquetado (Oro y Plata)

> **Cerrada (2026-10-20).** Oro vigente de 1 730 ítems, plata `silver_v0`, guía `v2.2`, segundo anotador (κ 0.81) y F-01 en monitoreo. Se reabre solo si:
> 1. ~~5.5 usa `menciona_falla` en sus métricas (`prompt_v4`)~~: descartada, 5.5 cerró (2026-10-22) sin usarla;
> 2. 5.6 o 5.8 necesitan más oro (por ejemplo, para calibrar umbrales);
> 3. se suman anotadores (guía `v2.3` con ejemplos largos de elogio con una queja menor).

**Objetivo:** obtener etiquetas limpias suficientes para entrenar y, sobre todo, para evaluar sin sesgo, con 1 000–2 000 etiquetas humanas.

* **Hecho:** guía de anotación, piloto de Gemini, oro en dos rondas más una re-anotación a ciegas, y plata v0. Historia y cifras vigentes en el [capítulo 3](../analytics/README.md#3-etiquetado-guía-pilotos-oro-y-plata).
* **Decisiones vigentes:**
  * **Gemini Flash vía Vertex AI en el proyecto:** los datos no salen de GCP y se paga con créditos. La API se habilita con el flag `enable_vertex_ai_api`; **no** se usa `enable_dedicated_vertex_endpoints`.
  * **Etiquetador:** `gemini-3.6-flash` con `prompt_v3` (guía `v2`): κ 0.92 contra el oro en 600 textos nuevos, $0.045–0.048 por 1 000 textos. Se versionan el prompt, el modelo exacto y la fecha. Las etiquetas de plata nunca se usan como verdad para reportar KPIs.
  * **Todo el oro se anota a ciegas,** tras medir un anclaje de +7 puntos en modo asistido.
  * **Oro vigente** (`gold_v0_r2` + `gold_v1`, 1 730 ítems): *dev* aleatorio 799, *dev* dirigido 300, *test* 601 y 30 de calibración. Solo el bloque aleatorio da cifras poblacionales; el *test* se evalúa una sola vez, en 5.8. Diseño en [`gold_v1_design.md`](../analytics/labeling/gold_v1_design.md).
  * **Plata vigente:** `silver_v0`, 99 926 filas y 70 284 textos únicos por $3.37, con holdout temporal desde 2026-04-01.
  * **Herramienta del oro:** app Streamlit local (`voc_analytics.annotation`), solo en `localhost`; guarda en CSV fuera de git y registra el tiempo por reseña.
  * `prompt_v4` solo se justificaba si `menciona_falla` entraba a las métricas de 5.5; 5.5 cerró sin usarla, así que no se necesita.
* **Segundo anotador (2026-10-20):** 100 ítems a ciegas de `gold_v1`, con la guía `v2.2`. κ entre personas 0.81 [0.70, 0.91] con 4 clases y 0.87 con 3; Gemini coincide con cada anotador (0.91 y 0.88 en *dev*) tanto o más que ellos entre sí. El desacuerdo principal es la regla 2 amplia: el segundo anotador decide por el tono. Ver el [reporte](../analytics/labeling/gold_v1_report.md), sección 7.
* **F-01 (hecho, 2026-10-20):** la [matriz FMEA](../governance/ethical_fmea_matrix.md#f-01-nombres-propios-en-texto-libre) registra la tasa medida de nombres propios, 0 en 1 300 anotadas. RPN 105 → 70; la fila pasa a monitoreo.

### FEATURE 5.4: Competencia de Modelos de Sentimiento con Etiquetas Ruidosas

**Objetivo:** elegir el modelo de Q1 por evidencia, con el mismo protocolo para todos.

* **Candidatos y protocolo:** escalera M0–M9, particiones, métricas y regla de decisión en [`sentiment_models_protocol.md`](../analytics/sentiment/sentiment_models_protocol.md). M8 (Delora) es el más caro y el menos validado: se time-boxea y solo se adopta si supera claramente a los métodos baratos.
* **Hecho:** fase A en el Mac (M0, M1, M2, T0, M9), escalera de ruido con TF-IDF (M3, M6, M7), M4 con RoBERTuito y BETO (3 semillas cada uno) M8 Delora (búsqueda del detector y 3 semillas), M5 (*label smoothing* sobre M4, 2 valores de ε y 3 semillas) en Kaggle y un sesgo de `NEU` sobre M4, evaluados con el *dev* ampliado. Detalle en las secciones 12 a 14 del [reporte](../analytics/sentiment/sentiment_models_v0_report.md). Ver el [capítulo 4](../analytics/README.md#4-competencia-de-modelos-de-sentimiento).
* **Decisiones vigentes:**
  * entrada `texto_sanitizado`, un ejemplo por texto único, sin pesos ni filtro de longitud; las métricas se desglosan por longitud;
  * se excluyen del entrenamiento las reseñas de todas las colas del oro;
  * descartados con motivo: T0 y M2 sin ajustar (dominio), M3, M6 y M7 (estrellas como etiqueta) **M8 Delora** (−0.04 a −0.05 de κ contra M4 en las tres semillas, más caro; su detector queda como candidato para la incongruencia) y **M5** (empata con M4 y calibra peor);
  * M4 RoBERTuito es el mejor modelo propio: empata con BETO en el aleatorio y gana en el dirigido;
  * entrenamiento con GPU en Kaggle, sin el oro *test* (riesgo F-13 aceptado por el autor); nada de GPU en GCP sin su aprobación.
* **Resultado vigente** (κ *dev* aleatorio, n = 794; M4 y M8, media de 3 semillas): M0 0.68, M1 0.87, M8 0.87, M4 0.92, M9 0.93. M4 − M1 entre +0.043 y +0.053, significativo en las seis corridas; M9 − M4 = +0.021 [−0.000, 0.043], concentrado en `NEU` (F1 0.73 contra 0.55).
* **Cerrado (2026-10-20):** escalera M0–M9 completa. Un sesgo de `NEU` sobre M4, elegido con la plata de `holdout_nuevo`, no mejora en el oro (Δκ medio −0.001) y no se adopta. **M4 RoBERTuito queda como el mejor modelo propio**; la elección entre M4 y M9 se hace en 5.8, por costo, licencia (`pysentimiento` es no comercial) y el oro *test*.

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
* **Entregable:** recomendación con su costo de operación (frecuencia de re-clustering, curaduría humana, estabilidad de identificadores de tópico). **Aprobada (2026-10-22):** [reporte, sección 5](../analytics/topics/topics_report.md#5-recomendación-aprobada-por-el-autor-2026-10-22) y [nota para 5.8](../analytics/topics/topics_decision_note.md). Pasaron a 5.9 los umbrales de la señal y el análisis por versión; a 5.7, el emparejamiento de tópicos entre reajustes y el monitoreo de `OT` (P7-8); a 5.8, el modelo de sentimiento del que dependen las familias (P8-1).

### FEATURE 5.6: Calibración, Incertidumbre, HITL y Priorización

> **Cerrada (2026-10-22).** [Plan](../analytics/calibration/calibration_design.md) y [reporte](../analytics/calibration/calibration_report.md). Todo se hizo con el oro *dev* (el *test* sigue intacto), la plata y una muestra nueva sin etiqueta; código en `voc_analytics.calibration`.

**Objetivo:** dejar calibradas las probabilidades, fijar la revisión humana, estimar proporciones poblacionales con intervalos válidos y decidir cómo se prioriza (Q4).

* **Calibración (decisión del autor):** *temperature scaling* con una T por semilla de M4 (≈ 1.7). M4 está sobreconfiado (confianza 0.995 y acierto 0.972); el ECE baja de ~0.025 a ~0.01 sin cambiar la exactitud. *Vector scaling* se descartó.
* **Umbral HITL de sentimiento (decisión del autor):** probabilidad máxima calibrada, **90 % de cobertura por defecto** como parámetro configurable. Se revisa el ~10 % menos seguro (~350 textos únicos por semana, 40–60 min) y el error entre lo aceptado baja de 2.8 % a 0.4 %. Revisar más del 10 % casi no mejora. Es un costo de operación del escenario de producción, no una carga semanal del autor; para la tesis basta una validación única. La curva y el parámetro son estado de la aplicación (EPIC-6, 6.1 a 6.4; EPIC-7, 7.7.2).
* **Descartes:** el ensamble de 3 semillas, BETO para el HITL, el disparador por impacto (4–5★, `NEG` y votos ≥ 5) como señal de error y la marca `duda` de Gemini (0 de 199).
* **PPI** (decisión del autor: medir con Gemini y con M4): los intervalos poblacionales son 2 a 4 veces más estrechos que con el oro solo, con cualquiera de los dos predictores (estrellas distintas del texto: 11.6 % [10.5, 12.6] con Gemini y 11.7 % [10.6, 12.8] con M4). Para M4 se usó una muestra nueva del snapshot (`ppi_v0`, 69 534 textos sin plata ni oro), porque M4 se entrenó con la plata.
* **Modelos con pesos:** el lote `m4_ppi` de Kaggle reentrenó M4 RoBERTuito con las semillas 1 a 3 y **guardó los pesos** (218 MB cada uno en fp16, `data/models/weights/`, fuera de git). Reproducen a 5.4 (κ 0.912–0.923) y son los candidatos desplegables.
* **Priorización, Q4 (decisión del autor):** volumen de negativas por familia y marca `u`, en nivel y en anomalía. La fórmula anterior (`priority_weight_score`) ordena los incidentes igual que contar negativas, y los votos empeoran el orden (se acumulan con el tiempo), así que salen del contrato; los votos se muestran como contexto.
* **Límite:** en los casos difíciles (*dev* dirigido) el error sigue en 17–23 % aun revisando el 20 %.
* **Pasa a otras features:** D1 (cuándo la deriva o un tema nuevo suben la revisión) a 5.7 ([P7-6](#decisiones-pendientes)); la fila de la FMEA sobre la priorización errónea y la validación única de la cola HITL, al autor.

### FEATURE 5.7: Escala, Ciclo de Vida y Monitoreo

> **Cerrada (2026-10-22).** [Plan](../analytics/scale/scale_design.md) (E1: medir en Cloud Run; E2: medir int8; E3: periodo de referencia por banco, no fecha común) y [reporte de 5.7](../analytics/scale/scale_report.md). Código en `voc_analytics.scale`. Todos los recursos temporales en GCP se borraron.

**Objetivo:** medir el tiempo y el costo de operar el pipeline y fijar cómo se versionan, promueven y vigilan los modelos.

* **Benchmark de inferencia (P7-1, P7-2; reporte §1):** M4 en Cloud Run con 1 vCPU, ordenado por longitud, hace 22.6 textos/s en fp32 y 27.2 en int8; con 2 vCPU en int8, 88. Ordenar por longitud acelera ~4×. int8 no pierde calidad (κ 0.918 contra 0.912). La memoria pico es de 1.2–1.4 GB, así que 1 GiB no alcanza. El backfill tardaría ~17 h en 1 vCPU y ~9 min en la T4 de Kaggle; el delta diario, ~25 s.
* **Decisiones del autor:** backfill y *re-scoring* completo en Kaggle con un pipeline desde GCP, asumiendo y declarando el riesgo de subir el corpus (P7-1, P7-4); delta diario en Cloud Run con 1 vCPU y 2 GiB (P7-2); Vertex Model Registry, con alias para promover y regresar (P7-3; reporte §6); subidas automáticas de la revisión HITL solo para el banco que alertó (P7-6); muestra humana de monitoreo y re-ajuste trimestral de tópicos como parámetros de la política de riesgo global (P7-7, P7-8); umbrales de deriva por banco en `drift_policy` (P7-9); reentrenamiento de M4 si el κ trimestral cae debajo de 0.89 y revalidación de las familias al cambiar Gemini (P7-10, P7-11; reporte §8).
* **Línea base de deriva (E3; reporte §2):** las tasas de alerta son mucho más altas en los años de arranque de cada banco. Con la regla propuesta (12 meses seguidos con al menos 200 filas) cada banco entra al monitor en su propio mes: BBVA 2016-04, AZTECA 2018-09, BANORTE 2018-10, SANTANDER 2019-04 y NUBANK 2021-12. Con z ≥ 4, cada serie alerta de 0 a 1.4 meses al año por banco (tabla por banco en el reporte). Estos umbrales son la plantilla de la **`drift_policy` de cada banco** (P7-9); la política HITL (`risk_policy`) es global.
* **Costos medidos para 5.8:** familias con Gemini, $0.091 por 1 000 textos (~$72 el llenado histórico; reporte §3); explicabilidad precalculada para el HITL, ~9 min de CPU por semana (§4); `VECTOR_SEARCH` en BigQuery, 4.26 GB por búsqueda sobre todo el corpus y ~0.5 GB con una ventana de 12 meses en una tabla particionada (§5 y §5.1).
* **Propuesta de ciclo de vida y monitoreo:** reporte §7 (candidato, registro, promoción, rollback y política HITL; umbrales del monitor por nivel).
* **Heredado de 5.5 y 5.6:** el emparejamiento de tópicos entre reajustes y el monitoreo de `OT` quedan en P7-8; los umbrales de la señal de incidentes y el análisis por versión pasaron a 5.9.

### FEATURE 5.8: Registro de Decisión

[`decision_record.md`](../analytics/decision_record.md) (**borrador, 2026-10-22**), con la evidencia de 5.2–5.7. Junta por tema lo decidido, lo pendiente y su evidencia, y termina con la lista de lo que falta para aprobarlo. Fija:

* modelo de sentimiento, encoder y método de ruido (o su ausencia), con métricas del oro *test* e intervalos;
* estrategia de tópicos y detección de incidentes;
* reglas de limpieza y elegibilidad, incluida `TNSS_SINGLE_WORD`;
* esquema de las tablas de salida y migración desde `delora_predictions`;
* umbral HITL y priorización (decididos en 5.6);
* *Satisfaction Gap*, búsqueda semántica y explicabilidad;
* plan de backfill, operación diaria, ciclo de vida y monitoreo;
* límites y riesgos para la Model Card y la FMEA.

**Antes de montar la infraestructura hay que tomar varias decisiones.** EPIC-6 (contratos, tablas, Jobs) y EPIC-7 (API y portal) se especificaron antes de la evidencia, y varias de sus piezas chocan con lo que decidió EPIC-5: el modelo, la licencia, el encoder de la búsqueda, la definición del *Satisfaction Gap*, la explicabilidad y quién etiqueta las familias en producción. Ninguna de las dos épicas empieza hasta que el [registro de decisiones](#decisiones-pendientes) tenga resueltas las de 5.8 (P8-1 a P8-12) y estén cerradas o aceptadas las [incompatibilidades](#incompatibilidades-entre-el-diseño-de-epic-6-y-epic-7-y-la-evidencia). Al aprobarse el registro se detalla [EPIC-6](epic_6.md) con las dependencias, tablas y pruebas que correspondan.

### FEATURE 5.9: Incidentes y versiones con la estrategia elegida

> **Sin iniciar; depende de 5.8 (decisión del autor, 2026-10-22).** Estos análisis cambian según el predictor que se elija en 5.8: sentimiento con M4 o con Gemini (P8-1) y familias con Gemini o con un clasificador propio (P8-7). Hacerlos antes obligaría a predecir el corpus o muestras grandes con un modelo que la decisión podría descartar. Por eso van después del registro de decisión y usan solo la estrategia elegida.

**Objetivo:** validar la señal de incidentes fuera de BBVA y medir el efecto de cada versión de la app, con datos suficientes y el predictor de producción.

1. **Meses candidatos a incidente en los 5 bancos, para validación del autor.** Hoy solo hay 3 incidentes etiquetados, todos de BBVA; en 5.5, el 11 % de los demás meses × banco tuvo alguna alerta y no se sabe cuántas son reales.
   * Entregable: por banco, los meses con más alerta (volumen de negativas, marca `u` y familias, en nivel y en anomalía), con la familia dominante, el tamaño de la muestra y su IC.
   * El autor marca cuáles fueron incidentes reales. Con esa lista se fijan los umbrales de la señal (P9-1) y se mide la precisión fuera de BBVA.
2. **Análisis por versión con más filas.** En 5.5 la plata no alcanzó para comparar versiones (JSD dominada por el ruido de muestreo).
   * Primero con la plata + `ppi_v0` (~200 000 filas), predichas con el modelo elegido. Si no alcanza, con las predicciones del backfill de EPIC-6 (6.3), sin hacer un backfill aparte.
   * Entregable: por banco y versión normalizada, la proporción de `NEG` y de la marca `u` con IC, el efecto de los días desde la versión en el sentimiento (no solo en la marca `u`), y qué versiones se separan de su línea base.
   * Límite: hoy las familias y la marca `u` solo existen para las negativas de la plata (40 382); extenderlas a `ppi_v0` depende de P8-7 (con Gemini, ~$3.6 y autorización del autor).
* **Consume:** 5.8 (predictor, familias, reglas). **Alimenta:** EPIC-6, 6.4 (umbrales del monitor y de las alertas). Las features 6.1 a 6.3 no dependen de 5.9 y pueden empezar al cerrar 5.8.

<a id="decisiones-pendientes"></a>

## 🗂️ Registro de decisiones pendientes

Seguimiento de lo que falta decidir para cerrar 5.7, 5.8 y 5.9 y empezar EPIC-6 y EPIC-7. Cada decisión es del autor; la columna "Propuesta" es la recomendación con la evidencia que hay hoy, o la decisión cuando ya se tomó. El [`decision_record.md`](../analytics/decision_record.md) junta todo por tema. Actualizado: 2026-10-22.

**Resumen:**

| Bloque | Decididas | Pendientes |
| :--- | :--- | :--- |
| 5.7 | P7-1 a P7-4 y P7-6 a P7-11 | Ninguna (cerrada) |
| 5.8 | P8-1 (criterio), P8-2, P8-3, P8-4, P8-5 y P8-11 (condicionadas al frontal), P8-6, P8-7, P8-8, P8-10 | Evaluación en el oro *test* (P8-1), P8-9, P8-12 |
| 5.9 | P9-1 (criterio) | P9-2 |

### Para cerrar 5.7

| ID | Decisión | Opciones | Evidencia hoy | Propuesta | Bloquea |
| :--- | :--- | :--- | :--- | :--- | :--- |
| P7-1 | Entorno del backfill | Kaggle T4; Cloud Run CPU; GPU Spot en GCP | T4: ~9 min, pero sube **todo** el corpus a Kaggle (F-13 cubre el entrenamiento, no el corpus completo). Cloud Run: ~17 h con 1 vCPU y ~4.4 h con 2 vCPU en int8 ([reporte de 5.7](../analytics/scale/scale_report.md), §1). GPU en GCP: requiere pasar la cuenta a pago | **Decidido por el autor (2026-10-22):** si 5.8 elige M4, backfill en Kaggle (prioridad: tiempo de ejecución), con un **pipeline desde GCP** que exporte de BigQuery, lance el kernel con la API de Kaggle y cargue las predicciones de vuelta; se asume el riesgo de subir el corpus completo y se declara en la FMEA con la tasa de PII medida. En producción todo quedaría en GCP. El delta diario sigue en Cloud Run | 6.2, 6.3 |
| P7-2 | Recursos del delta diario | 1 o 2 vCPU; 1 o 2 GiB | Memoria pico de 1.2–1.4 GB en Cloud Run; ~500 textos únicos por día | **Decidido por el autor (2026-10-22):** Job de 1 vCPU y 2 GiB para el delta diario (memoria pico 1.2–1.4 GB; ~25 s por 500 textos) | 6.2 |
| P7-3 | Registro de artefactos | GCS versionado; Vertex Model Registry | Pesos en fp16 + tokenizador + T + curva HITL por versión | **Decidido por el autor (2026-10-22):** Vertex Model Registry (versiones y alias; promoción en 3 s); se declara un contenedor de *serving* mínimo aunque no se despliegue | 6.2, 6.4 |
| P7-4 | Promoción, rollback y *re-scoring* | Re-predecir todo el histórico o solo lo nuevo al cambiar de modelo | El backfill en CPU tomaría horas; las series históricas se rompen si se mezclan modelos | **Decidido por el autor (2026-10-22):** re-predecir todo el histórico en Kaggle al promover un modelo, con `model_version` por predicción y las predicciones anteriores conservadas para auditoría | 6.3, 6.4 |
| P7-6 | D1: cuándo la deriva o un tema nuevo suben la revisión HITL | Automático, sugerido al revisor o manual | Curva de cobertura y riesgo por versión (5.6) | **Decidido por el autor (2026-10-22):** automático, aplicado solo al banco que alertó: cada subida queda en `hitl_boosts` con las reglas de la `risk_policy` global (cobertura, duración y tope semanal) y vuelve a la base al terminar | 6.4, 7.7.2 |
| P7-7 | Monitoreo de concepto | Tamaño y frecuencia de la muestra humana periódica | Única fuente con etiquetas; cuesta tiempo humano | **Decidido por el autor (2026-10-22):** muestra humana periódica como parámetro configurable (tamaño y frecuencia): el revisor y el dueño de negocio fijan el apetito de riesgo, como la cobertura HITL | 6.4 |
| P7-8 | Re-ajuste de tópicos | Frecuencia, emparejamiento de identificadores y vigilancia de `OT` | 5.5: curaduría de ~30–60 min por trimestre | **Decidido por el autor (2026-10-22):** re-ajuste trimestral con emparejamiento por centroides, con la frecuencia como parámetro configurable del mismo apetito de riesgo | 6.4, 7.7.1 |
| P7-9 | Umbrales del monitor de deriva y regla de entrada por banco | z o PSI por serie; periodo de referencia | Línea base histórica ([reporte de 5.7](../analytics/scale/scale_report.md), §2): con z ≥ 4 alertan el 2.3–6.9 % de los meses; por banco, de 0 a 1.4 meses al año en cada serie; PSI ≥ 0.25, el 2.0 %; los años de arranque alertan mucho más | **Decidido por el autor (2026-10-22):** los umbrales de deriva no son apetito de riesgo sino la configuración del detector, y van **por banco** en una tabla propia (`drift_policy`), creada desde una plantilla: z ≥ 4 en las series de entrada y de `NEG`, PSI ≥ 0.25 en la longitud, entrada con 12 meses seguidos de al menos 200 filas. La política HITL (`risk_policy`) queda **global**, como la evidencia de 5.6; una alerta sube la revisión solo del banco que alertó (`hitl_boosts`) | 6.4 |
| P7-10 | Desempeño de M4 y reentrenamiento | Umbral de κ en la muestra humana trimestral; señales baratas | [reporte de 5.7](../analytics/scale/scale_report.md), §8.1 y §8.2: con 300 revisiones por trimestre, el κ de un M4 sin cambios cae en [0.89, 0.97]; tasa de corrección esperada en la cola 24.9 %; acuerdo M4–Gemini 96.9 % | **Decidido por el autor (2026-10-22):** reentrenar si el κ trimestral de M4 (300 revisiones `monitor_sample`) queda debajo de 0.89; avisos, sin disparar solos: tasa de corrección de 4 semanas > 28 % y acuerdo M4–Gemini de 4 semanas < 94 % (500 textos por semana, ~$0.02). Valores en la `risk_policy` global | 6.4 |
| P7-11 | Calidad de las familias de Gemini | Revalidar al cambiar de modelo o de prompt | [reporte de 5.7](../analytics/scale/scale_report.md), §8.3: κ autor–Gemini por familia y acuerdo exacto 58.3 % [52.7, 64.0] en las 300 reseñas de `muestra_v21` | **Decidido por el autor (2026-10-22):** al cambiar el modelo o el prompt de Gemini, repetir las 300 reseñas de `muestra_v21` (~$0.03) y aceptar el cambio solo si el acuerdo exacto es ≥ 53 % y ninguna familia con prevalencia ≥ 5 % queda debajo del límite inferior de su IC | 6.3, 6.4 |

### Para 5.8 y antes de EPIC-6 y EPIC-7

| ID | Decisión | Opciones | Evidencia hoy | Propuesta | Bloquea |
| :--- | :--- | :--- | :--- | :--- | :--- |
| P8-1 | Modelo de sentimiento | M4 RoBERTuito (`_ppi`, con pesos); M9 Gemini | κ 0.917 contra 0.93 (M9 − M4 = +0.021 [−0.000, 0.043]); M4 sin costo por texto y calibrado; M9 ~$72 el backfill, sin probabilidades ni señal HITL útil | **Decidido por el autor (2026-10-22):** se decide con datos: el oro *test* (una sola vez), el costo y la licencia | 6.1–6.3, 7.1, 7.2 |
| P8-2 | Licencia del modelo | Aceptar la licencia no comercial de `pysentimiento` (tesis); reentrenar desde un checkpoint base sin esa restricción; M9 | Los dos M4 parten de checkpoints de `pysentimiento` (RoBERTuito y BETO), con licencia solo para investigación | **Decidido por el autor (2026-10-22):** RoBERTuito para la tesis; el límite para uso comercial se declara en la FMEA y en la Model Card | P8-1, 7.5 |
| P8-3 | `TNSS_SINGLE_WORD` | Excluir y reportar cobertura; asignar por léxico (`RULE_BASED`) | El léxico cubre el 95.3 % con 99 % de exactitud; excluir solo lo no cubierto deja un sesgo de −0.001 a −0.007 | **Decidido por el autor (2026-10-22):** léxico determinista para las cubiertas y excluir el resto | 6.1, 6.3 |
| P8-4 | Aprobar las reglas de elegibilidad | `v0.1` (borrador) a `v1` | Corte de NUBANK, `TNSS_NOT_SPANISH` descartada, `TOPIC_TOO_SHORT` k = 1 | **Decidido por el autor (2026-10-22):** aprobar `v1` con `TNSS_SINGLE_WORD` (léxico, P8-3) y `TOPIC_TOO_SHORT` k = 1; no se contradicen: la primera es del sentimiento y la segunda de tópicos y familias | 6.1, 6.3 |
| P8-5 | Esquema de salida y migración | Columnas de las tablas que reemplazan `delora_predictions` | Borrador de 5.1; 5.6 quitó `priority_weight_score` y `tnss_numeric_calibrated` | **Decidido por el autor (2026-10-22), con una condición:** se aprueba el [esquema v3](../contracts/analytics_outputs_v3_draft.md) con sus cambios: `eligibility_code` explícito (`ELEGIBLE`), `sentiment` con `NO_PREDICTED`, nulos solo para ausencia, `review_predictions` por reseña con inferencia por texto único en el backfill. Condición: que cubra las necesidades del frontal de EPIC-7 (se revisa con P8-12) | 6.1, 6.2, 7.1 |
| P8-6 | Búsqueda semántica | Encoder MiniLM (384), otro encoder, o sacarla del alcance | Delora descartado; los tópicos ya usan MiniLM; la infraestructura de EPIC-2 declara 768 dimensiones; experimento en BigQuery | **Decidido por el autor (2026-10-22):** BigQuery `VECTOR_SEARCH` sobre una tabla de embeddings (MiniLM, 384) particionada por mes, con una ventana de meses configurable (12 por defecto): ~2 000 búsquedas al mes en el free tier; sin Vertex Vector Search ([reporte de 5.7](../analytics/scale/scale_report.md), §5.1) | 6.2, 7.1, 7.3, 7.4 |
| P8-7 | Familias en producción | Gemini (`aspects_v2_1`) sobre todas las negativas; clasificador propio entrenado con esas etiquetas | Gemini κ 0.55–0.86 contra el autor según la familia; ~$0.03 al día en el delta | **Medido (2026-10-22, [reporte de 5.7](../analytics/scale/scale_report.md), §3):** $3.60 por 39 635 negativas ($0.091 por 1 000); llenado histórico estimado en ~$72. Decidido por el autor: llenado histórico en GCP | 6.1, 6.3 |
| P8-8 | Explicabilidad | Oclusión por token con el modelo elegido; explicación por familias y términos de tópico; sacarla del alcance | La meta de < 150 ms en 1 vCPU no es realista; precalculada, cuesta ~0.5 s por texto | **Decidido por el autor (2026-10-22):** explicabilidad por oclusión precalculada solo para la cola HITL (~0.5 s por texto en Cloud Run, ~9 min de CPU por semana) | 7.2, 7.3 |
| P8-9 | Definición del *Satisfaction Gap* | Diferencia entre estrellas y `tnss_numeric_calibrated` (descartado en 5.6); proporción de `NEG` contra la de estrellas 1–2; estrellas distintas del texto | PPI ya da estas proporciones con intervalos por banco | **Avance (2026-10-22):** el autor objetó medir una sola dirección. Medido con PPI ([reporte de 5.6](../analytics/calibration/calibration_report.md), §3.3): texto más negativo que las estrellas 10.5 %, más positivo 0.9 %, brecha neta −0.14 [−0.16, −0.13]. Propuesta: reportar la matriz 3 × 3 y la brecha neta con intervalo | 7.1, 7.4, 7.6 |
| P8-10 | Estimaciones del portal | Proporciones crudas sobre las predicciones o corregidas por PPI | PPI necesita el oro aleatorio; las proporciones crudas tienen el sesgo del modelo | **Decidido por el autor (2026-10-22):** crudas para las series diarias y PPI para los KPI por banco y periodo | 7.1, 7.4 |
| P8-11 | Registro de las revisiones de sentimiento | Ampliar `hitl_triage_audit_log` o crear `curation_sentiment` | La bitácora actual guarda un `ABSATopic`, que ya no existe | **Decidido por el autor (2026-10-22), con una condición:** tablas nuevas para el HITL (`hitl_items`, `hitl_events`, `hitl_reviews` con comentario sanitizado) y se elimina `hitl_triage_audit_log`; la muestra de monitoreo es `hitl_items.reason` y puede entrar al oro por versiones (`gold_versions`). Misma condición que P8-5 | 6.1, 6.2, 7.2 |
| P8-12 | Alcance de EPIC-7 para la presentación | Todas las features o un subconjunto | Tiempo disponible antes de la presentación | Decidir al cerrar 5.8, con la lista de features que entran a la demo; al hacerlo, comprobar que el esquema aprobado (P8-5, P8-11) cubre todas las pantallas | 7.1–7.7 |

### Para 5.9

| ID | Decisión | Opciones | Evidencia hoy | Propuesta | Bloquea |
| :--- | :--- | :--- | :--- | :--- | :--- |
| P9-1 | Umbrales de la señal de incidentes | z, línea base, mínimo de filas por mes | 5.5: la marca `u` detecta 2 de 3 incidentes con 4 % de falsas alarmas; solo 3 incidentes etiquetados, todos de BBVA | **Decidido por el autor (2026-10-22):** fijarlos con datos: la lista de meses candidatos de los 5 bancos que valide el autor (tarea 1 de 5.9) | 6.4 |
| P9-2 | Datos para el análisis por versión | Plata + `ppi_v0`; predicciones del backfill de EPIC-6 | 5.5: con la plata sola domina el ruido | Empezar con la plata + `ppi_v0`; pasar al backfill solo si no alcanza | 5.9 |

### Incompatibilidades entre el diseño de EPIC-6 y EPIC-7 y la evidencia

Piezas del texto original de EPIC-1, EPIC-2 y EPIC-7 que chocan con lo decidido en EPIC-5. Las "resueltas" ya tienen decisión y solo falta reescribir la especificación; las "pendientes" dependen de una decisión del registro.

| Pieza (dónde) | Choca con | Estado |
| :--- | :--- | :--- |
| `AnalyzedReviewPrediction` con `sentimiento_roberta` y docstring "DeLoRA" (EPIC-1) | Delora descartado (5.4) | Pendiente de P8-1 |
| `ABSATopic` único por reseña (EPIC-1; EPIC-7 7.1, 7.2, 7.4, 7.6) | Familias multi-etiqueta `v2.1` y marcas `u` y `s` (5.5) | Resuelta en 5.5; se reescribe en 6.1 |
| `MIN_REVIEW_WORDS`/`MAX_REVIEW_WORDS = (2, 60)` (EPIC-1; EPIC-7 7.2 "de 2 a 60 palabras") | Sin filtro de longitud (5.2); elegibilidad por reglas | Resuelta; falta P8-3 y P8-4 |
| `priority_weight_score`, `tnss_numeric_calibrated` y `prediction_entropy` (EPIC-1; EPIC-7 7.1, 7.2) | Priorización por volumen y marca `u`; HITL por probabilidad máxima calibrada (5.6) | Resuelta en 5.6; se reescribe en 6.1 |
| `delora_predictions` de 15 columnas agrupada por `topico` (EPIC-2) | Esquema versionado por modelo, calibración y política HITL | Resuelta con P8-5 (condicionada al frontal): se elimina; se reescribe en 6.1 y 6.2 |
| `embedding_vector` de 768 dimensiones e índice de Vertex de 768 (EPIC-2; EPIC-7 7.1, 7.3, 7.6) | Delora descartado; MiniLM de 384 en tópicos | Resuelta con P8-6: MiniLM de 384 en BigQuery, tabla particionada por mes; se retira el índice de Vertex. Se reescribe en 6.2 y 7.1 |
| `hitl_entropy_threshold = 0.65` en `Settings` (EPIC-1; EPIC-7 objetivo y 7.5) | 90 % de cobertura como política versionada (5.6) | Resuelta en 5.6; se reescribe en 6.1 y 7.5 |
| `hitl_triage_audit_log` con `original_topic`/`validated_topic` (EPIC-2; EPIC-7 7.2) | Curadurías de sentimiento, aspectos y tópicos (5.5) | Resuelta con P8-11: se elimina; falta revisar el esquema de las tablas nuevas |
| *Satisfaction Gap* como estrellas menos TNSS continuo, prueba con gap −1.11 (EPIC-7 7.1, 7.6) | `tnss_numeric_calibrated` descartado (5.6) | Pendiente de P8-9 |
| Explicador de < 150 ms en 1 vCPU y 1 GiB (EPIC-7 7.2) | Velocidad medida de M4 en CPU | Resuelta con P8-8: oclusión precalculada para la cola HITL; se reescribe en 7.2 |
| Model Card con Delora, paridad dialectal sintética y umbral 0.65 (EPIC-7 7.5) | 5.4 y 5.6 | Resuelta; se reescribe al cerrar 5.8 |
| FMEA: "Label Noise mitigado por Dual LoRA" y "priorización mitigada por entropía ≥ 0.65" (EPIC-7 7.5) | M4 ajustado con la plata; HITL por cobertura | Resuelta; la fila nueva de priorización la califica el autor |
| *Concept drift* con JSD de 8 tópicos y umbrales PSI 0.25 / JSD 0.20 (anexo de EPIC-6, A.7) | Familias y marca `u` (5.5); línea base de 5.7 | Pendiente de P7-9 (deriva) y P9-1 (señal de incidentes) |
| Backfill "dentro de GCP" contra la medición en Kaggle | Principio de que los datos no salen de GCP | Resuelta con P7-1: backfill en Kaggle con riesgo aceptado y declarado en la FMEA; en producción, todo en GCP |
| IAM de Vertex AI para el modelo de producción (EPIC-6 6.2) | Las familias usan Gemini en GCP (P8-7) y el registro es Vertex (P7-3) | Resuelta: `voc-sa-ml-backend` necesita Vertex AI para Gemini y el registro; M9 solo cambia el volumen |

---


<a id="siguientes-pasos"></a>

## 🧭 Siguientes pasos

En orden. Cada paso sale de un pendiente de los reportes o del alcance de su feature. Los pasos 1 a 10 están hechos (2026-10-20 a 2026-10-22): paquete de Kaggle y lote `humo`, semillas de M4, M5 y M8 descartados con motivo, F-01 y F-12 en la FMEA, segundo anotador, *Data Card* con `gold_v1`, pendientes de 5.2 y tópicos (5.5). Su detalle está en los reportes de cada feature y en la historia de git.

| # | Paso | Dueña | Depende de | Terminado cuando |
| :---: | :--- | :---: | :--- | :--- |
| 11 | ~~**5.6:** calibración, umbral HITL, PPI y priorización~~ **Hecho (2026-10-22):** ver el [reporte](../analytics/calibration/calibration_report.md) | 5.6 | — | — |
| 12 | ~~**5.7:** benchmark en Cloud Run, ciclo de vida, monitoreo y costos~~ **Hecho (2026-10-22):** ver el [reporte de 5.7](../analytics/scale/scale_report.md) | 5.7 | — | — |
| 13 | **5.8:** decidir lo pendiente del [`decision_record.md`](../analytics/decision_record.md), evaluar una sola vez en el oro *test*, publicar las reglas `v1` y redactar los límites para la Model Card y la FMEA | 5.8 | 12 | `decision_record.md` aprobado, incompatibilidades resueltas o aceptadas y EPIC-6 detallada |
| 14 | **5.9:** meses candidatos a incidente en los 5 bancos (validados por el autor) y análisis por versión, con la estrategia elegida en 5.8 | 5.9 (al arrancar) | 13 | Lista de incidentes validada; umbrales de la señal (P9-1); efecto por versión con IC |

---

## 💻 Cómputo y presupuesto

| Tarea | Dónde | Costo |
| :--- | :--- | :--- |
| EDA, deduplicación, muestreo y modelos lineales | Mac M2 8 GB (polars/duckdb, CPU) | $0 |
| Etiquetas de plata y M9 | Vertex AI, `gemini-3.6-flash` | Medido: plata v0 $3.37 por 70 284 textos; Gemini sobre el backfill completo ~$72 (precio introductorio hasta el 2026-12-31) |
| Codificación de aspectos (5.2) | Vertex AI, `gemini-3.6-flash` | Medido: $0.17 por dos rondas de 1 434 textos negativos (`aspects_v0` y `aspects_v1`); $0.17 y $0.16 en `aspects_v2` y `aspects_v2_1` (guía `v2.1`); $3.64 por las 40 382 negativas de la plata en 5.5 (vía B a escala) |
| Ajuste de encoders y semillas | Kaggle (~30 h/semana de GPU, no garantizadas); el Mac solo para validar el pipeline (M4 en 46–48 min, una semilla). Medido en la T4: M4 y M5 ~6 min por corrida; M8 ~1 h por semilla | $0 |
| GPU dentro de GCP (opcional) | Pasar la cuenta de prueba a pago conserva los créditos y permite pedir cuota de GPU Spot (L4/T4) | Centavos por hora; requiere aprobación del autor |
| Backfill de 2.65 M (1.38 M textos únicos) | Kaggle T4 con pipeline desde GCP (P7-1) | Medido: ~9 min de GPU ($0); en Cloud Run serían ~17 h con 1 vCPU |
| Delta diario | Cloud Run Job de 1 vCPU y 2 GiB (P7-2; free tier: 180 000 vCPU-s/mes) | Medido: ~25 s por 500 textos ($0) |
| Familias con Gemini (P8-7) | Vertex AI, `gemini-3.6-flash` | Medido: $3.60 por 39 635 negativas de `ppi_v0` ($0.091 por 1 000); llenado histórico ~$72 |
| Búsqueda semántica (P8-6) | BigQuery `VECTOR_SEARCH` | Medido: 4.26 GB por búsqueda sobre todo el corpus; ~0.5 GB con ventana de 12 meses (free tier: 1 TiB al mes) |
| Benchmarks de 5.7 | Cloud Run, Cloud Build, BigQuery y Vertex | Recursos temporales, borrados al terminar |

Crédito disponible: ~$5 000 MXN. La restricción del etiquetado es el tiempo humano, no el gasto. Las cifras de throughput, costo y duplicados de la literatura o de conversaciones con otros LLM no se usan para decidir hasta medirlas.

---

## ⚠️ Riesgos y limitaciones a declarar

* **Delora no está validado** en encoders de ~110 M ni con estrellas como etiqueta (`references.md`, §10). Su adopción depende de que supere a métodos baratos.
* **El ruido de las estrellas depende de la instancia y del periodo** (NoisyAG-News, 2024): los resultados con ruido sintético no transfieren.
* **Las etiquetas de plata heredan sesgos de Gemini** (sarcasmo, jerga bancaria mexicana, `NEU`); solo el oro sirve para reportar.
* **El oro es el criterio de un anotador**, el autor, que además escribió la guía y la calibró en parte con Gemini. Un segundo anotador coincide con él con κ 0.81 (0.87 con 3 clases), sobre todo por la regla 2 amplia, que un anotador nuevo tiende a decidir por el tono. Por eso las diferencias de ~0.02 entre los mejores modelos (κ 0.91–0.93) quedan por debajo del ruido entre personas.
* **Licencia:** los modelos de `pysentimiento` son solo para uso no comercial e investigación. Decisión del autor (P8-2): se aceptan para la tesis y se declara en la Model Card y la FMEA que limitan un uso comercial.
* **Corpus en Kaggle (P7-1):** el backfill sube el corpus completo de textos sanitizados a un dataset privado de Kaggle; riesgo aceptado por el autor, por declarar en la FMEA.
* **Casos difíciles:** en el *dev* dirigido el error de M4 sigue en 17–23 % aun revisando el 20 % (5.6).
* **`fecha` es de última edición:** el análisis temporal mide cuándo se escribió la versión vigente, no la original.
* **Puede haber PII residual** por la sanitización solo con regex: no publicar ejemplos del corpus sin revisión.
* **Los tópicos dinámicos requieren curaduría humana continua;** sin ella pierden identidad entre corridas.
* **Los aspectos son etiquetas de Gemini, no una medición:** con `v2.1` el multi-aspecto es 24.7 % y el κ con el autor va de 0.55 a 0.86 según el código (`UX` 0.74; `u` 0.70; `s` no concluyente); entre corridas de Gemini, `DV` 0.58 y `OT` 0.22. Con `v1` Gemini marcaba 32 % contra 44 % del autor (κ 0.42). Hay un único anotador humano y solo 3 incidentes conocidos para la prueba hacia atrás, así que la señal es ilustrativa.

---

## ✅ Checklist de Aceptación de la Épica 5 (fases 1 y 2)

* [ ] Guía de anotación, reglas deterministas de elegibilidad por tarea (con códigos, precedencia y versión) y envolvente de costo aprobados (5.1). *Avance: guía `v2.2` adoptada; reglas `v1` aprobadas por el autor (P8-3, P8-4) y falta publicarlas; costos de etiquetado, inferencia y familias medidos.*
* [ ] Reporte de cobertura por banco × periodo × motivo, y decisión sobre `TNSS_SINGLE_WORD` (excluir o léxico determinista) con su sesgo medido (5.2, 5.8). *Avance: sesgo medido (−0.10 a −0.21 estrellas por banco); conteos por regla en el EDA; el léxico determinista cubre el 95.3 % con 99 % de exactitud y deja un sesgo de −0.001 a −0.007 (5.2). Decidido: léxico para las cubiertas y exclusión del resto (P8-3); falta el reporte de cobertura con las reglas `v1`.*
* [x] EDA global de los 5 bancos y 15 años, con reglas de limpieza versionadas y Data Card actualizada (5.2). *EDA global, temporal y segunda pasada hechos; limpieza decidida en 5.4; Data Card `v0.2` con el EDA completo, el oro, la plata y los aspectos.*
* [x] Conjunto de plata con prompt, modelo y costo versionados; conjunto de oro con bloque aleatorio documentado y medición de anclaje (5.3).
* [x] Al menos M0–M7 evaluados con el mismo protocolo; M8 y M9 evaluados o descartados con motivo (5.4). *M4 RoBERTuito es el mejor modelo propio; M5 y M8 descartados con motivo; M4 contra M9 se decide en 5.8.*
* [x] Decisión sobre ABSA, tópicos dinámicos o híbrido, con una señal de incidentes probada hacia atrás (5.5). *Híbrido aprobado por el autor (2026-10-22): familias `v2.1` y marca `u` como núcleo y alerta, tópicos como capa de detalle curada; señal probada con los 3 incidentes de BBVA ([reporte](../analytics/topics/topics_report.md), sección 5).*
* [x] Calibración y umbral HITL elegidos por cobertura–riesgo (5.6). *Temperature scaling (T ≈ 1.7) y 90 % de cobertura por defecto como parámetro configurable; PPI y priorización decididos ([reporte](../analytics/calibration/calibration_report.md)).*
* [x] Benchmark de escala, propuesta de ciclo de vida y plan de monitoreo (5.7). *Benchmark en Cloud Run, ciclo de vida y monitoreo ([reporte de 5.7](../analytics/scale/scale_report.md), §1 y §7); P7-1 a P7-4 y P7-6 a P7-11 decididas.*
* [ ] Registro de decisión ([`decision_record.md`](../analytics/decision_record.md)) aprobado, con P8-1 a P8-12 decididas, y [EPIC-6](epic_6.md) detallada a partir de él (5.8). *Avance: borrador listo; faltan el oro test, P8-9 y P8-12; P8-5 y P8-11 aprobadas con condición.*
* [ ] Lista de incidentes de los 5 bancos validada por el autor, umbrales de la señal y efecto por versión, con la estrategia elegida (5.9).
* [x] Experimentos reproducibles en `experiments/analytics/` (proyecto `uv` propio, semillas fijas), sin dependencias de experimentación en el `uv.lock` de producción.
