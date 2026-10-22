# EPIC-5: Planteamiento Analítico y Experimentación del Core NLP

* **Estado (2026-10-22):** En curso, fase 2. Cerradas: el EDA (5.2, 2026-10-21, con la guía de aspectos `v2.1`), el etiquetado (5.3: oro de 1 730 ítems y plata `silver_v0`), la experimentación de modelos (5.4: M4 RoBERTuito, κ 0.917; M4 contra M9 se decide en 5.8) y los tópicos (5.5, 2026-10-22: híbrido aprobado por el autor y `TOPIC_TOO_SHORT` k = 1). 5.6 cerrada (2026-10-22: calibración, HITL al 90 %, PPI y priorización). Siguen 5.7 y 5.8, que dependen de las decisiones del [registro](#decisiones-pendientes). Los frontales de curaduría HITL (sentimiento, aspectos y tópicos) pasan a EPIC-7 (7.7) y su base de datos a EPIC-6 (6.2). Ver [estado por feature](#-estado-por-feature) y [siguientes pasos](#siguientes-pasos).
* **Historia de los resultados:** [`docs/analytics/README.md`](../analytics/README.md) ordena los reportes como una historia y dice qué cifra está vigente. Este documento solo guarda el planteamiento, el estado y lo que falta; la cronología detallada está en los reportes.
* **Fases:** (1) planteamiento analítico viable → (2) experimentación para elegir la estrategia de producción → (3) despliegue de la estrategia elegida. Desde la reorganización del backlog (2026-10-22), la fase 3 es [EPIC-6](epic_6.md), que conserva la especificación anterior como anexo no vigente y se detalla tras el registro de decisión (5.8).
* **Semanas Objetivo:** Semanas 4 - 6 (fases 1 y 2).
* **Dependencias:** EPIC-1 a EPIC-4 cerradas ([cierre](epics.md#cierre-de-las-épicas-1-a-4)). Corpus: `bbva_voc_tds.sanitized_reviews_tds`, **2 649 047 reseñas** de BBVA, NUBANK, SANTANDER, AZTECA y BANORTE (2011-04 a 2026-10), con `source_observed_at`. Bibliografía: [`references.md`](../governance/references.md).
* **Directorios:**
  * `experiments/analytics/`: proyecto `uv` **independiente del workspace** (su propio `pyproject.toml` y `uv.lock`), para que las dependencias de experimentación no entren al lock de producción. El código es el paquete `voc_analytics` (`src/`), agrupado por etapa: `snapshot`, `eda`, `labeling`, `sampling`, `annotation`, `analysis`, `sentiment` y `topics`. Comandos en su [README](../../experiments/analytics/README.md).
  * `docs/analytics/`: reportes por etapa, con las mismas carpetas que el paquete (`eda/`, `labeling/`, `sentiment/`, `topics/`) y, al final, el registro de decisión (`decision_record.md`).
  * `docs/governance/`: Data Card, Model Card y matriz FMEA se completan con los resultados.

---

## 🎯 Objetivo y principios

Diseñar, con evidencia, el pipeline analítico que responde a cuatro preguntas del caso de uso, y elegir la estrategia de producción **antes** de escribir el paquete desplegable:

| Pregunta | Salida candidata | Feature |
| :--- | :--- | :---: |
| Q1. ¿Cuál es el sentimiento real del texto, separado de las estrellas? | Polaridad por reseña, score continuo y brecha frente a las estrellas (*Satisfaction Gap*) | 5.4 |
| Q2. ¿Qué temas recurrentes hay en las quejas y cómo cambian en el tiempo? | Familias de aspectos `v2.1` (núcleo) y tópicos curados (detalle) sobre las reseñas negativas, por banco y periodo. **Resuelta en 5.5** | 5.5 |
| Q3. ¿Cómo detectamos rápido un incidente nuevo? | Marca `u` (problema atribuido a una actualización) y series por familia, por banco y mes; la prueba hacia atrás detecta 2 de 3 incidentes de BBVA. **Resuelta en 5.5** (umbrales en 5.7) | 5.5 |
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
| 5.1 Planteamiento y elegibilidad | En curso: guía adoptada; reglas en borrador `v0.1`; `TOPIC_TOO_SHORT` decidido (k = 1, 5.5); falta `TNSS_SINGLE_WORD` (5.8) | [Reglas](../analytics/eda/eligibility_rules.md), [guía](../analytics/labeling/annotation_guideline.md) |
| 5.2 EDA | **Cerrada (2026-10-21).** EDA global, patrones temporales, tokens, léxico para una palabra (95 % de cobertura) y guía de aspectos `v2.1` (reabierta para 5.5): 11 familias más las marcas `u` y `s`; `UX` pasó de κ 0.55 a 0.74 y `DV` queda separado; multi-aspecto del 24.7 % (32.1 % con `v1`). *Data Card* `v0.2` | [EDA](../analytics/eda/eda_report.md), [temporal](../analytics/eda/eda_temporal_report.md), [guía de aspectos `v2.1`](../analytics/eda/eda_aspects_guideline.md) |
| 5.3 Etiquetado | **Cerrada (2026-10-20).** Oro (1 730 ítems) y plata vigentes; acuerdo entre personas medido (κ 0.81). 5.5 cerró sin usar `menciona_falla` (`prompt_v4` no se necesita). Se reabre si 5.6 o 5.8 necesitan más oro, o si se suman anotadores (guía `v2.3`) | [Capítulo 3](../analytics/README.md#3-etiquetado-guía-pilotos-oro-y-plata) |
| 5.4 Modelos de sentimiento | **Cerrada la experimentación (2026-10-20):** M0–M9 evaluados; M4 RoBERTuito es el mejor modelo propio; M4 contra M9 se decide en 5.8 | [Protocolo](../analytics/sentiment/sentiment_models_protocol.md), [capítulo 4](../analytics/README.md#4-competencia-de-modelos-de-sentimiento) |
| 5.5 Tópicos y ABSA | **Cerrada (2026-10-22).** Recomendación aprobada por el autor, con el agregado de llevar los frontales de curaduría HITL (sentimiento, aspectos y tópicos) a EPIC-7 y su base de datos a EPIC-6. Híbrido: familias `aspects_v2_1` y la marca `u` como núcleo de medición y alerta (la marca `u` detecta 2 de 3 incidentes con 4 % de falsas alarmas; `DV` y `UX` avisaron del rediseño de BBVA un mes antes), y tópicos por cláusulas como capa de detalle curada para producto e ingeniería. Los tópicos no encontraron temas fuera de la taxonomía; cerca de un tercio de su peso es ruido. `TOPIC_TOO_SHORT` con k = 1 (decidido). Costo: ~$0.60 al mes de Gemini y ~30–60 min de curaduría por trimestre | [Plan](../analytics/topics/topics_design.md), [reporte](../analytics/topics/topics_report.md), [nota para 5.8](../analytics/topics/topics_decision_note.md) |
| 5.6 Calibración, HITL y priorización | **Cerrada (2026-10-22).** *temperature scaling* adoptado; umbral HITL al 90 % de cobertura (parámetro configurable); PPI con Gemini y con M4 hecho; M4 reentrenado con pesos guardados (lote `m4_ppi`); priorización por volumen de negativas por familia y marca `u`, sin fórmula anterior ni votos (decisión del autor) | [Plan](../analytics/calibration/calibration_design.md), [reporte](../analytics/calibration/calibration_report.md) |
| 5.7 Escala, ciclo de vida y monitoreo | Sin iniciar, con avances de 5.6 (velocidad de M4 en T4 y CPU, pesos guardados); faltan [P7-1 a P7-8](#decisiones-pendientes) | [Reporte de 5.6](../analytics/calibration/calibration_report.md), §3.3 |
| 5.8 Registro de decisión | Sin iniciar; faltan [P8-1 a P8-12](#decisiones-pendientes) y las incompatibilidades con EPIC-6 y EPIC-7 | — |

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
* **Abierto:** `TNSS_SINGLE_WORD` (484 829 filas, 18.3 %): excluir y reportar cobertura, o asignar por léxico como `RULE_BASED`. El sesgo de excluirlas es de −0.10 a −0.21 estrellas por banco, y los modelos aciertan ~96 % en una palabra. **Evidencia del léxico (5.2):** 151 formas cubren el 95.3 % de esas filas con 99 % de exactitud en el oro *dev*, y excluir solo las no cubiertas deja un sesgo de −0.001 a −0.007. Decide 5.8.
* **Envolvente de volumetría y costo:** backfill único sobre ≤ 1.60 M textos únicos (1 383 138 medidos) y delta diario de cientos de reseñas. Cualquier estrategia que no quepa queda descartada aunque gane en calidad. Costos medidos hasta ahora en la [sección de cómputo](#-cómputo-y-presupuesto).
* **Borrador de las salidas de producción** (se cierra en 5.8): predicción por reseña versionada por modelo y corrida; tópicos por periodo; catálogo de tópicos con su ciclo de vida; estado de elegibilidad; registro de corridas. El esquema de 15 columnas de `delora_predictions` (EPIC-2) se revisa con esta evidencia.

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
* **Entregable:** recomendación con su costo de operación (frecuencia de re-clustering, curaduría humana, estabilidad de identificadores de tópico). **Aprobada (2026-10-22):** [reporte, sección 5](../analytics/topics/topics_report.md#5-recomendación-aprobada-por-el-autor-2026-10-22) y [nota para 5.8](../analytics/topics/topics_decision_note.md). Queda para 5.7: los umbrales de la señal, el análisis por versión, el emparejamiento de tópicos entre reajustes y el monitoreo de `OT`; para 5.8: el modelo de sentimiento del que dependen las familias.

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

> **Sin iniciar formalmente, con avances (2026-10-22)** que dejó 5.6. Las decisiones que faltan para cerrarla están en el [registro de decisiones](#decisiones-pendientes) (P7-1 a P7-8).

* **Benchmark de escala:** tiempo y costo del backfill sobre los textos únicos y del delta diario para los finalistas (Kaggle T4 y Cloud Run CPU), aplicando deduplicación, orden por longitud y adaptadores fusionados.
  * **Medido en 5.6 (indicativo):** M4 RoBERTuito infiere ~2 500 textos/s en la T4 (los 1 383 138 textos únicos en ~9 min de GPU) y 39–53 textos/s en CPU (Mac M2, fp32, sin ordenar por longitud): el backfill tomaría ~7–10 h en CPU y el delta diario (~500 textos únicos) ~10–15 s. El ajuste tomó ~6 min por semilla en la T4.
  * **Falta:** repetir la medición en Cloud Run (1 y 2 vCPU, memoria pico), probar el orden por longitud, y medir el costo de las familias `aspects_v2_1` con Gemini sobre las negativas del corpus (5.5 midió $3.64 por 40 382 negativas).
* **Ciclo de vida de artefactos:** registro de versiones (GCS versionado o Vertex Model Registry), Model Card por versión, regla de promoción y rollback, y política de **re-scoring** al cambiar de modelo (todo el histórico o solo lo nuevo).
  * **Ya existe:** pesos de 3 semillas en fp16 con su tokenizador, una T por semilla y el procedimiento para recalcular la curva HITL al promover un modelo (`calibration.selective`, EPIC-6 6.4).
* **Monitoreo (sin y con etiquetas):**

  | Nivel | Qué se mide | ¿Requiere etiquetas? |
  | :--- | :--- | :---: |
  | Entrada | Longitud, idioma, vocabulario nuevo, `version_app`, proporción de no predecibles | No |
  | Predicción | Proporción de `NEG` por banco y versión; confianza media | No |
  | Concepto | Desempeño sobre una muestra humana periódica pequeña | Sí |
  | Tópicos | Aparición y crecimiento de tópicos; esperado, no un fallo | No |

* **Heredado de 5.5:** umbrales de la señal de incidentes, análisis por versión, emparejamiento de tópicos entre reajustes y monitoreo de `OT`. **De 5.6:** D1 y la ventana de deriva por cadencia de cada banco (5.2).

### FEATURE 5.8: Registro de Decisión

`docs/analytics/decision_record.md`, con la evidencia de 5.2–5.7. Fija:

* modelo de sentimiento, encoder y método de ruido (o su ausencia), con métricas del oro *test* e intervalos;
* estrategia de tópicos y detección de incidentes;
* reglas de limpieza y elegibilidad, incluida `TNSS_SINGLE_WORD`;
* esquema de las tablas de salida y migración desde `delora_predictions`;
* umbral HITL y priorización (decididos en 5.6);
* plan de backfill, operación diaria, ciclo de vida y monitoreo;
* límites y riesgos para la Model Card y la FMEA.

**Antes de montar la infraestructura hay que tomar varias decisiones.** EPIC-6 (contratos, tablas, Jobs) y EPIC-7 (API y portal) se especificaron antes de la evidencia, y varias de sus piezas chocan con lo que decidió EPIC-5: el modelo, la licencia, el encoder de la búsqueda, la definición del *Satisfaction Gap*, la explicabilidad y quién etiqueta las familias en producción. Ninguna de las dos épicas empieza hasta que el [registro de decisiones](#decisiones-pendientes) tenga resueltas las de 5.8 (P8-1 a P8-12) y estén cerradas o aceptadas las [incompatibilidades](#incompatibilidades-entre-el-diseño-de-epic-6-y-epic-7-y-la-evidencia). Al aprobarse el registro se detalla [EPIC-6](epic_6.md) con las dependencias, tablas y pruebas que correspondan.

<a id="decisiones-pendientes"></a>

## 🗂️ Registro de decisiones pendientes

Seguimiento de lo que falta decidir para cerrar 5.7 y 5.8 y empezar EPIC-6 y EPIC-7. Cada decisión es del autor; la columna "Propuesta" es la recomendación con la evidencia que hay hoy, no una decisión. Al decidirse, la fila se marca y pasa al reporte de su feature o a `decision_record.md`. Actualizado: 2026-10-22.

### Para cerrar 5.7

| ID | Decisión | Opciones | Evidencia hoy | Propuesta | Bloquea |
| :--- | :--- | :--- | :--- | :--- | :--- |
| P7-1 | Entorno del backfill | Kaggle T4; Cloud Run CPU; GPU Spot en GCP | T4: ~9 min, pero sube **todo** el corpus a Kaggle (F-13 cubre el entrenamiento, no el corpus completo). CPU: ~7–10 h estimadas. GPU en GCP: requiere pasar la cuenta a pago | Cloud Run Job en CPU, por tramos y con el orden por longitud: el corpus no sale de GCP y el costo cabe en el free tier; medirlo antes de decidir | 6.2, 6.3 |
| P7-2 | Recursos del delta diario | 1 o 2 vCPU; 1 o 2 GiB | Modelo de 218 MB en fp16 (~435 MB en fp32); ~500 textos únicos por día | Cloud Run Job de 1 vCPU y 2 GiB; medir la memoria pico | 6.2 |
| P7-3 | Registro de artefactos | GCS versionado; Vertex Model Registry | Pesos en fp16 + tokenizador + T + curva HITL por versión | GCS versionado (sin costo fijo), con un manifiesto por versión | 6.2, 6.4 |
| P7-4 | Promoción, rollback y *re-scoring* | Re-predecir todo el histórico o solo lo nuevo al cambiar de modelo | El backfill en CPU tomaría horas; las series históricas se rompen si se mezclan modelos | Promover solo si mejora en el oro *dev* con la regla de 5.4; *re-scoring* completo al promover, versionado por `model_version` | 6.3, 6.4 |
| P7-5 | Umbrales de la señal de incidentes | z, línea base, mínimo de filas por mes | 5.5: la marca `u` detecta 2 de 3 incidentes con 4 % de falsas alarmas; solo 3 incidentes etiquetados | Fijar con más filas por mes (el backfill) y documentar que es ilustrativo; armar una lista de incidentes conocidos | 6.4 |
| P7-6 | D1: cuándo la deriva o un tema nuevo suben la revisión HITL | Automático, sugerido al revisor o manual | Curva de cobertura y riesgo por versión (5.6) | Que el monitor sugiera una nueva versión de la política HITL y que una persona la apruebe en el portal | 6.4, 7.7.2 |
| P7-7 | Monitoreo de concepto | Tamaño y frecuencia de la muestra humana periódica | Única fuente con etiquetas; cuesta tiempo humano | Para la tesis, la validación única de la cola HITL; en producción, ~100 reseñas aleatorias por trimestre | 6.4 |
| P7-8 | Re-ajuste de tópicos | Frecuencia, emparejamiento de identificadores y vigilancia de `OT` | 5.5: curaduría de ~30–60 min por trimestre | Trimestral, con emparejamiento por similitud de centroides | 6.4, 7.7.1 |

### Para 5.8 y antes de EPIC-6 y EPIC-7

| ID | Decisión | Opciones | Evidencia hoy | Propuesta | Bloquea |
| :--- | :--- | :--- | :--- | :--- | :--- |
| P8-1 | Modelo de sentimiento | M4 RoBERTuito (`_ppi`, con pesos); M9 Gemini | κ 0.917 contra 0.93 (M9 − M4 = +0.021 [−0.000, 0.043]); M4 sin costo por texto y calibrado; M9 ~$72 el backfill, sin probabilidades ni señal HITL útil | Se decide con el oro *test* (una sola vez) y con P8-2 | 6.1–6.3, 7.1, 7.2 |
| P8-2 | Licencia del modelo | Aceptar la licencia no comercial de `pysentimiento` (tesis); reentrenar desde un checkpoint base sin esa restricción; M9 | Los dos M4 parten de checkpoints de `pysentimiento` (RoBERTuito y BETO), con licencia solo para investigación | Aceptarla para la tesis y declararla en la Model Card como límite de un uso comercial | P8-1, 7.5 |
| P8-3 | `TNSS_SINGLE_WORD` | Excluir y reportar cobertura; asignar por léxico (`RULE_BASED`) | El léxico cubre el 95.3 % con 99 % de exactitud; excluir solo lo no cubierto deja un sesgo de −0.001 a −0.007 | Léxico determinista para las cubiertas y excluir el resto | 6.1, 6.3 |
| P8-4 | Aprobar las reglas de elegibilidad | `v0.1` (borrador) a `v1` | Corte de NUBANK, `TNSS_NOT_SPANISH` descartada, `TOPIC_TOO_SHORT` k = 1 | Aprobar `v1` junto con P8-3 | 6.1, 6.3 |
| P8-5 | Esquema de salida y migración | Columnas de las tablas que reemplazan `delora_predictions` | Borrador de 5.1; 5.6 quitó `priority_weight_score` y `tnss_numeric_calibrated` | Predicción por texto único y por fila, con `model_version`, `calibration_version` y `hitl_policy_version`; la tabla vieja se retira (está vacía) | 6.1, 6.2, 7.1 |
| P8-6 | Búsqueda semántica | Encoder MiniLM (384), otro encoder, o sacarla del alcance | Delora descartado; los tópicos ya usan MiniLM; la infraestructura de EPIC-2 declara 768 dimensiones | MiniLM de 384 en BigQuery (`VECTOR_SEARCH`), sin Vertex Vector Search | 6.2, 7.1, 7.3, 7.4 |
| P8-7 | Familias en producción | Gemini (`aspects_v2_1`) sobre todas las negativas; clasificador propio entrenado con esas etiquetas | Gemini κ 0.55–0.86 contra el autor según la familia; ~$0.60 al mes en el delta; el backfill de las negativas no está medido | Gemini dentro de GCP, como en 5.5, con costo del backfill medido en 5.7 | 6.1, 6.3 |
| P8-8 | Explicabilidad | Oclusión por token con el modelo elegido; explicación por familias y términos de tópico; sacarla del alcance | La meta de < 150 ms en 1 vCPU no es realista: M4 hace 39–53 textos/s en CPU, y una explicación por oclusión necesita una pasada por token | Oclusión asíncrona o precalculada para la cola HITL, sin la meta de 150 ms | 7.2, 7.3 |
| P8-9 | Definición del *Satisfaction Gap* | Diferencia entre estrellas y `tnss_numeric_calibrated` (descartado en 5.6); proporción de `NEG` contra la de estrellas 1–2; estrellas distintas del texto | PPI ya da estas proporciones con intervalos por banco | Reportar las proporciones de PPI (`NEG` por texto contra `NEG` por estrellas, y estrellas distintas del texto) con su intervalo | 7.1, 7.4, 7.6 |
| P8-10 | Estimaciones del portal | Proporciones crudas sobre las predicciones o corregidas por PPI | PPI necesita el oro aleatorio; las proporciones crudas tienen el sesgo del modelo | Crudas para las series diarias y PPI para los KPI por banco y periodo | 7.1, 7.4 |
| P8-11 | Registro de las revisiones de sentimiento | Ampliar `hitl_triage_audit_log` o crear `curation_sentiment` | La bitácora actual guarda un `ABSATopic`, que ya no existe | Crear `curation_sentiment` y dejar la bitácora vieja sin uso | 6.1, 6.2, 7.2 |
| P8-12 | Alcance de EPIC-7 para la presentación | Todas las features o un subconjunto | Tiempo disponible antes de la presentación | Decidir al cerrar 5.8, con la lista de features que entran a la demo | 7.1–7.7 |

### Incompatibilidades entre el diseño de EPIC-6 y EPIC-7 y la evidencia

Piezas del texto original de EPIC-1, EPIC-2 y EPIC-7 que chocan con lo decidido en EPIC-5. Las "resueltas" ya tienen decisión y solo falta reescribir la especificación; las "pendientes" dependen de una decisión del registro.

| Pieza (dónde) | Choca con | Estado |
| :--- | :--- | :--- |
| `AnalyzedReviewPrediction` con `sentimiento_roberta` y docstring "DeLoRA" (EPIC-1) | Delora descartado (5.4) | Pendiente de P8-1 |
| `ABSATopic` único por reseña (EPIC-1; EPIC-7 7.1, 7.2, 7.4, 7.6) | Familias multi-etiqueta `v2.1` y marcas `u` y `s` (5.5) | Resuelta en 5.5; se reescribe en 6.1 |
| `MIN_REVIEW_WORDS`/`MAX_REVIEW_WORDS = (2, 60)` (EPIC-1; EPIC-7 7.2 "de 2 a 60 palabras") | Sin filtro de longitud (5.2); elegibilidad por reglas | Resuelta; falta P8-3 y P8-4 |
| `priority_weight_score`, `tnss_numeric_calibrated` y `prediction_entropy` (EPIC-1; EPIC-7 7.1, 7.2) | Priorización por volumen y marca `u`; HITL por probabilidad máxima calibrada (5.6) | Resuelta en 5.6; se reescribe en 6.1 |
| `delora_predictions` de 15 columnas agrupada por `topico` (EPIC-2) | Esquema versionado por modelo, calibración y política HITL | Pendiente de P8-5 |
| `embedding_vector` de 768 dimensiones e índice de Vertex de 768 (EPIC-2; EPIC-7 7.1, 7.3, 7.6) | Delora descartado; MiniLM de 384 en tópicos | Pendiente de P8-6 |
| `hitl_entropy_threshold = 0.65` en `Settings` (EPIC-1; EPIC-7 objetivo y 7.5) | 90 % de cobertura como política versionada (5.6) | Resuelta en 5.6; se reescribe en 6.1 y 7.5 |
| `hitl_triage_audit_log` con `original_topic`/`validated_topic` (EPIC-2; EPIC-7 7.2) | Curadurías de sentimiento, aspectos y tópicos (5.5) | Pendiente de P8-11 |
| *Satisfaction Gap* como estrellas menos TNSS continuo, prueba con gap −1.11 (EPIC-7 7.1, 7.6) | `tnss_numeric_calibrated` descartado (5.6) | Pendiente de P8-9 |
| Explicador de < 150 ms en 1 vCPU y 1 GiB (EPIC-7 7.2) | Velocidad medida de M4 en CPU | Pendiente de P8-8 |
| Model Card con Delora, paridad dialectal sintética y umbral 0.65 (EPIC-7 7.5) | 5.4 y 5.6 | Resuelta; se reescribe al cerrar 5.8 |
| FMEA: "Label Noise mitigado por Dual LoRA" y "priorización mitigada por entropía ≥ 0.65" (EPIC-7 7.5) | M4 ajustado con la plata; HITL por cobertura | Resuelta; la fila nueva de priorización la califica el autor |
| *Concept drift* con JSD de 8 tópicos y umbrales PSI 0.25 / JSD 0.20 (anexo de EPIC-6, A.7) | Familias y marca `u` (5.5) | Pendiente de P7-5 |
| Backfill "dentro de GCP" contra la medición en Kaggle | Principio de que los datos no salen de GCP | Pendiente de P7-1 |
| IAM de Vertex AI para el modelo de producción (EPIC-6 6.2) | Depende de si se usa M9 o solo las familias con Gemini | Pendiente de P8-1 y P8-7 |

---


<a id="siguientes-pasos"></a>

## 🧭 Siguientes pasos

En orden. Cada paso sale de un pendiente de los reportes o del alcance de su feature. Los pasos 1 a 10 están hechos (2026-10-20 a 2026-10-22): paquete de Kaggle y lote `humo`, semillas de M4, M5 y M8 descartados con motivo, F-01 y F-12 en la FMEA, segundo anotador, *Data Card* con `gold_v1`, pendientes de 5.2 y tópicos (5.5). Su detalle está en los reportes de cada feature y en la historia de git.

| # | Paso | Dueña | Depende de | Terminado cuando |
| :---: | :--- | :---: | :--- | :--- |
| 11 | ~~**5.6:** calibración, umbral HITL, PPI y priorización~~ **Hecho (2026-10-22):** ver el [reporte](../analytics/calibration/calibration_report.md) | 5.6 | — | — |
| 12 | **5.7:** benchmark de escala en Cloud Run, ciclo de vida y plan de monitoreo | 5.7 (al arrancar) | 5.6 (hecho) | Decisiones P7-1 a P7-8 del [registro](#decisiones-pendientes) tomadas; tiempo y costo del backfill y del delta medidos en Cloud Run; propuesta de ciclo de vida y monitoreo |
| 13 | **5.8:** registro de decisión, evaluación única en el oro *test* y aprobación de las reglas | 5.8 (al arrancar) | 12 | Decisiones P8-1 a P8-12 tomadas, incompatibilidades resueltas o aceptadas, `decision_record.md` aprobado y EPIC-6 detallada |

---

## 💻 Cómputo y presupuesto

| Tarea | Dónde | Costo |
| :--- | :--- | :--- |
| EDA, deduplicación, muestreo y modelos lineales | Mac M2 8 GB (polars/duckdb, CPU) | $0 |
| Etiquetas de plata y M9 | Vertex AI, `gemini-3.6-flash` | Medido: plata v0 $3.37 por 70 284 textos; Gemini sobre el backfill completo ~$72 (precio introductorio hasta el 2026-12-31) |
| Codificación de aspectos (5.2) | Vertex AI, `gemini-3.6-flash` | Medido: $0.17 por dos rondas de 1 434 textos negativos (`aspects_v0` y `aspects_v1`); $0.17 y $0.16 en `aspects_v2` y `aspects_v2_1` (guía `v2.1`); $3.64 por las 40 382 negativas de la plata en 5.5 (vía B a escala) |
| Ajuste de encoders y semillas | Kaggle (~30 h/semana de GPU, no garantizadas); el Mac solo para validar el pipeline (M4 en 46–48 min, una semilla). Medido en la T4: M4 y M5 ~6 min por corrida; M8 ~1 h por semilla | $0 |
| GPU dentro de GCP (opcional) | Pasar la cuenta de prueba a pago conserva los créditos y permite pedir cuota de GPU Spot (L4/T4) | Centavos por hora; requiere aprobación del autor |
| Backfill de 2.65 M | El entorno más barato que cumpla el benchmark de 5.7 | Se mide |
| Delta diario | Cloud Run Job en CPU (free tier: 180 000 vCPU-s/mes) | ~$0 si el modelo es ligero |

Crédito disponible: ~$5 000 MXN. La restricción del etiquetado es el tiempo humano, no el gasto. Las cifras de throughput, costo y duplicados de la literatura o de conversaciones con otros LLM no se usan para decidir hasta medirlas.

---

## ⚠️ Riesgos y limitaciones a declarar

* **Delora no está validado** en encoders de ~110 M ni con estrellas como etiqueta (`references.md`, §10). Su adopción depende de que supere a métodos baratos.
* **El ruido de las estrellas depende de la instancia y del periodo** (NoisyAG-News, 2024): los resultados con ruido sintético no transfieren.
* **Las etiquetas de plata heredan sesgos de Gemini** (sarcasmo, jerga bancaria mexicana, `NEU`); solo el oro sirve para reportar.
* **El oro es el criterio de un anotador**, el autor, que además escribió la guía y la calibró en parte con Gemini. Un segundo anotador coincide con él con κ 0.81 (0.87 con 3 clases), sobre todo por la regla 2 amplia, que un anotador nuevo tiende a decidir por el tono. Por eso las diferencias de ~0.02 entre los mejores modelos (κ 0.91–0.93) quedan por debajo del ruido entre personas.
* **Licencia:** los modelos de `pysentimiento` son solo para uso no comercial e investigación; para producción (5.8) son una restricción.
* **`fecha` es de última edición:** el análisis temporal mide cuándo se escribió la versión vigente, no la original.
* **Puede haber PII residual** por la sanitización solo con regex: no publicar ejemplos del corpus sin revisión.
* **Los tópicos dinámicos requieren curaduría humana continua;** sin ella pierden identidad entre corridas.
* **Los aspectos son etiquetas de Gemini, no una medición:** con `v2.1` el multi-aspecto es 24.7 % y el κ con el autor va de 0.55 a 0.86 según el código (`UX` 0.74; `u` 0.70; `s` no concluyente); entre corridas de Gemini, `DV` 0.58 y `OT` 0.22. Con `v1` Gemini marcaba 32 % contra 44 % del autor (κ 0.42). Hay un único anotador humano y solo 3 incidentes conocidos para la prueba hacia atrás, así que la señal es ilustrativa.

---

## ✅ Checklist de Aceptación de la Épica 5 (fases 1 y 2)

* [ ] Guía de anotación, reglas deterministas de elegibilidad por tarea (con códigos, precedencia y versión) y envolvente de costo aprobados (5.1). *Avance: guía `v2.2` adoptada; reglas en borrador `v0.1`; costos de etiquetado medidos; `TOPIC_TOO_SHORT` decidido (k = 1).*
* [ ] Reporte de cobertura por banco × periodo × motivo, y decisión sobre `TNSS_SINGLE_WORD` (excluir o léxico determinista) con su sesgo medido (5.2, 5.8). *Avance: sesgo medido (−0.10 a −0.21 estrellas por banco); conteos por regla en el EDA; el léxico determinista cubre el 95.3 % con 99 % de exactitud y deja un sesgo de −0.001 a −0.007 (5.2). Falta la decisión (5.8).*
* [x] EDA global de los 5 bancos y 15 años, con reglas de limpieza versionadas y Data Card actualizada (5.2). *EDA global, temporal y segunda pasada hechos; limpieza decidida en 5.4; Data Card `v0.2` con el EDA completo, el oro, la plata y los aspectos.*
* [x] Conjunto de plata con prompt, modelo y costo versionados; conjunto de oro con bloque aleatorio documentado y medición de anclaje (5.3).
* [x] Al menos M0–M7 evaluados con el mismo protocolo; M8 y M9 evaluados o descartados con motivo (5.4). *M4 RoBERTuito es el mejor modelo propio; M5 y M8 descartados con motivo; M4 contra M9 se decide en 5.8.*
* [x] Decisión sobre ABSA, tópicos dinámicos o híbrido, con una señal de incidentes probada hacia atrás (5.5). *Híbrido aprobado por el autor (2026-10-22): familias `v2.1` y marca `u` como núcleo y alerta, tópicos como capa de detalle curada; señal probada con los 3 incidentes de BBVA ([reporte](../analytics/topics/topics_report.md), sección 5).*
* [x] Calibración y umbral HITL elegidos por cobertura–riesgo (5.6). *Temperature scaling (T ≈ 1.7) y 90 % de cobertura por defecto como parámetro configurable; PPI y priorización decididos ([reporte](../analytics/calibration/calibration_report.md)).*
* [ ] Benchmark de escala, propuesta de ciclo de vida y plan de monitoreo (5.7). *Avance: velocidad de M4 medida en la T4 y en CPU; pesos guardados (5.6). Faltan P7-1 a P7-8.*
* [ ] Registro de decisión aprobado, con P8-1 a P8-12 decididas, y [EPIC-6](epic_6.md) detallada a partir de él (5.8).
* [x] Experimentos reproducibles en `experiments/analytics/` (proyecto `uv` propio, semillas fijas), sin dependencias de experimentación en el `uv.lock` de producción.
