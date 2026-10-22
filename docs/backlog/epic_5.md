# EPIC-5: Planteamiento Analítico y Experimentación del Core NLP

* **Estado (2026-10-22):** En curso, fase 2. Cerradas: el EDA (5.2, 2026-10-21, con la guía de aspectos `v2.1`), el etiquetado (5.3: oro de 1 730 ítems y plata `silver_v0`), la experimentación de modelos (5.4: M4 RoBERTuito, κ 0.917; M4 contra M9 se decide en 5.8) y los tópicos (5.5, 2026-10-22: híbrido aprobado por el autor y `TOPIC_TOO_SHORT` k = 1). Siguen 5.6–5.8. La curaduría HITL (sentimiento, aspectos y tópicos) y su base de datos pasan a EPIC-6 (feature 6.7). Ver [estado por feature](#-estado-por-feature) y [siguientes pasos](#siguientes-pasos).
* **Historia de los resultados:** [`docs/analytics/README.md`](../analytics/README.md) ordena los reportes como una historia y dice qué cifra está vigente. Este documento solo guarda el planteamiento, el estado y lo que falta; la cronología detallada está en los reportes.
* **Fases:** (1) planteamiento analítico viable → (2) experimentación para elegir la estrategia de producción → (3) despliegue de la estrategia elegida. La especificación anterior, que fijaba modelo, dependencias, tópicos y esquema de salida antes de tener evidencia, se conserva como borrador condicionado en [`epic_5_deployment.md`](epic_5_deployment.md) y solo se reescribe tras el registro de decisión (5.8).
* **Semanas Objetivo:** Semanas 4 - 6 (fases 1 y 2).
* **Dependencias:** EPIC-1 a EPIC-4 cerradas ([cierre](closure_epics_1_4.md)). Corpus: `bbva_voc_tds.sanitized_reviews_tds`, **2 649 047 reseñas** de BBVA, NUBANK, SANTANDER, AZTECA y BANORTE (2011-04 a 2026-10), con `source_observed_at`. Bibliografía: [`references.md`](../governance/references.md).
* **Directorios:**
  * `experiments/analytics/`: proyecto `uv` **independiente del workspace** (su propio `pyproject.toml` y `uv.lock`), para que las dependencias de experimentación no entren al lock de producción. El código es el paquete `voc_analytics` (`src/`), agrupado por etapa: `snapshot`, `eda`, `labeling`, `sampling`, `annotation`, `analysis`, `sentiment` y `topics`. Comandos en su [README](../../experiments/analytics/README.md).
  * `docs/analytics/`: reportes de cada experimento, guía de anotación, protocolo de 5.4 y, al final, el registro de decisión (`decision_record.md`).
  * `docs/governance/`: Data Card, Model Card y matriz FMEA se completan con los resultados.

---

## 🎯 Objetivo y principios

Diseñar, con evidencia, el pipeline analítico que responde a cuatro preguntas del caso de uso, y elegir la estrategia de producción **antes** de escribir el paquete desplegable:

| Pregunta | Salida candidata | Feature |
| :--- | :--- | :---: |
| Q1. ¿Cuál es el sentimiento real del texto, separado de las estrellas? | Polaridad por reseña, score continuo y brecha frente a las estrellas (*Satisfaction Gap*) | 5.4 |
| Q2. ¿Qué temas recurrentes hay en las quejas y cómo cambian en el tiempo? | Familias de aspectos `v2.1` (núcleo) y tópicos curados (detalle) sobre las reseñas negativas, por banco y periodo. **Resuelta en 5.5** | 5.5 |
| Q3. ¿Cómo detectamos rápido un incidente nuevo? | Marca `u` (problema atribuido a una actualización) y series por familia, por banco y mes; la prueba hacia atrás detecta 2 de 3 incidentes de BBVA. **Resuelta en 5.5** (umbrales en 5.7) | 5.5 |
| Q4. ¿Qué atender primero? | Priorización que combine severidad, volumen y votos de utilidad | 5.6 |

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
| 5.1 Planteamiento y elegibilidad | En curso: guía adoptada; reglas en borrador `v0.1`; `TOPIC_TOO_SHORT` decidido (k = 1, 5.5); falta `TNSS_SINGLE_WORD` (5.8) | [Reglas](../analytics/eligibility_rules.md), [guía](../analytics/annotation_guideline.md) |
| 5.2 EDA | **Cerrada (2026-10-21).** EDA global, patrones temporales, tokens, léxico para una palabra (95 % de cobertura) y guía de aspectos `v2.1` (reabierta para 5.5): 11 familias más las marcas `u` y `s`; `UX` pasó de κ 0.55 a 0.74 y `DV` queda separado; multi-aspecto del 24.7 % (32.1 % con `v1`). *Data Card* `v0.2` | [EDA](../analytics/eda_report.md), [temporal](../analytics/eda_temporal_report.md), [guía de aspectos `v2.1`](../analytics/eda_aspects_guideline.md) |
| 5.3 Etiquetado | **Cerrada (2026-10-20).** Oro (1 730 ítems) y plata vigentes; acuerdo entre personas medido (κ 0.81). 5.5 cerró sin usar `menciona_falla` (`prompt_v4` no se necesita). Se reabre si 5.6 o 5.8 necesitan más oro, o si se suman anotadores (guía `v2.3`) | [Capítulo 3](../analytics/README.md#3-etiquetado-guía-pilotos-oro-y-plata) |
| 5.4 Modelos de sentimiento | **Cerrada la experimentación (2026-10-20):** M0–M9 evaluados; M4 RoBERTuito es el mejor modelo propio; M4 contra M9 se decide en 5.8 | [Protocolo](../analytics/sentiment_models_protocol.md), [capítulo 4](../analytics/README.md#4-competencia-de-modelos-de-sentimiento) |
| 5.5 Tópicos y ABSA | **Cerrada (2026-10-22).** Recomendación aprobada por el autor, con el agregado de llevar la curaduría HITL (sentimiento, aspectos y tópicos) y su base de datos a EPIC-6. Híbrido: familias `aspects_v2_1` y la marca `u` como núcleo de medición y alerta (la marca `u` detecta 2 de 3 incidentes con 4 % de falsas alarmas; `DV` y `UX` avisaron del rediseño de BBVA un mes antes), y tópicos por cláusulas como capa de detalle curada para producto e ingeniería. Los tópicos no encontraron temas fuera de la taxonomía; cerca de un tercio de su peso es ruido. `TOPIC_TOO_SHORT` con k = 1 (decidido). Costo: ~$0.60 al mes de Gemini y ~30–60 min de curaduría por trimestre | [Plan](../analytics/topics_design.md), [reporte](../analytics/topics_report.md), [nota para 5.8](../analytics/topics_decision_note.md) |
| 5.6 Calibración, HITL y priorización | Sin iniciar | — |
| 5.7 Escala, ciclo de vida y monitoreo | Sin iniciar | — |
| 5.8 Registro de decisión | Sin iniciar | — |

### FEATURE 5.1: Planteamiento, Volumetría y Contrato Analítico

**Objetivo:** fijar qué se predice, sobre qué filas y con qué presupuesto, antes de experimentar.

* **Etiquetas de sentimiento:** decidido. `NEG`/`NEU`/`POS` más la marca `NO_EVALUABLE`, con `menciona_falla`, `duda` y `nombre_persona`; cualquier queja concreta es `NEG`. Ver la [guía `v2.2`](../analytics/annotation_guideline.md).
* **Reglas deterministas de elegibilidad** ([`eligibility_rules_v0.1`](../analytics/eligibility_rules.md), borrador):
  * se evalúan por fila antes de la inferencia, sin modelos ni aleatoriedad; gana la primera que coincide;
  * la fila excluida queda `NOT_PREDICTED` con su código, se conserva y se reporta por banco × periodo × motivo;
  * la inferencia corre una vez por texto único elegible y se propaga a sus filas;
  * `TOPIC_NOT_NEGATIVE` usa el TNSS **predicho**, nunca las estrellas, así que el backfill de tópicos es posterior al de TNSS;
  * el EDA puede añadir reglas, cada una con código, criterio, conteo y justificación.
* **Decisiones vigentes:** corte de NUBANK en 2020-01-01 (`TNSS_TIME_OUTLIER`, 175 filas); `TNSS_NOT_SPANISH` descartada.
* **Abierto:**
  * `TNSS_SINGLE_WORD` (484 829 filas, 18.3 %): excluir y reportar cobertura, o asignar por léxico como `RULE_BASED`. El sesgo de excluirlas es de −0.10 a −0.21 estrellas por banco, y los modelos aciertan ~96 % en una palabra. **Evidencia del léxico (5.2):** 151 formas cubren el 95.3 % de esas filas con 99 % de exactitud en el oro *dev*, y excluir solo las no cubiertas deja un sesgo de −0.001 a −0.007. Decide 5.8.
  * Umbral de `TOPIC_TOO_SHORT`: **Decisión del autor (2026-10-22): k = 1.** Del análisis de tópicos y familias se excluyen solo las negativas de una palabra ([`topics_report.md`](../analytics/topics_report.md#43-topic_too_short-k--1-se-confirma-con-v21-y-los-5-bancos), sección 4.3). **Corregido (2026-10-21):** el dato de 5.2 decía que las negativas de 1 a 5 palabras casi nunca nombran un problema concreto, y no se sostiene. Según 5.5, nombran un problema concreto el 4 % [1, 18] de las negativas de una palabra, el 46 % [33, 60] de las de 2 y el 77 % [70, 83] de las de 3 a 5; lo que casi nunca son es multi-aspecto (0–4 %) ([`topics_report.md`](../analytics/topics_report.md#43-topic_too_short-k--1-se-confirma-con-v21-y-los-5-bancos), sección 4.3; confirmadas con `aspects_v2_1` y los 5 bancos).
* **Envolvente de volumetría y costo:** backfill único sobre ≤ 1.60 M textos únicos (1 383 138 medidos) y delta diario de cientos de reseñas. Cualquier estrategia que no quepa queda descartada aunque gane en calidad. Costos medidos hasta ahora en la [sección de cómputo](#-cómputo-y-presupuesto).
* **Borrador de las salidas de producción** (se cierra en 5.8): predicción por reseña versionada por modelo y corrida; tópicos por periodo; catálogo de tópicos con su ciclo de vida; estado de elegibilidad; registro de corridas. El esquema de 15 columnas de `delora_predictions` (EPIC-2) se revisa con esta evidencia.

### FEATURE 5.2: EDA Global y Pipeline de Limpieza

> **Cerrada de nuevo (2026-10-21) con la guía de aspectos `v2.1`** ([EDA, sección 5.2.1](../analytics/eda_report.md#521-guía-de-aspectos-v2-y-v21-reapertura-para-55)): taxonomía final de 11 familias con las marcas `u` y `s`; `UX` κ 0.74; `DV` separado como excepción por prevalencia (1.8 %); multi-aspecto 24.7 %. Se reabrió el 2026-10-20: lo pidió 5.5 ([plan de tópicos](../analytics/topics_design.md), sección 6) y lo aprobó el autor. El resto sigue cerrado: EDA global, patrones temporales y los pendientes de tokens, multi-aspecto y léxico ([sección 5 del EDA](../analytics/eda_report.md#5-pendientes-cerrados-tokens-multi-aspecto-y-léxico)); *Data Card* `v0.2`.
>
> **Alcance de la reapertura:**
> * **Guía:** [`v2.1`](../analytics/eda_aspects_guideline.md) (empezó como `v2-draft`). `DS` se parte en `DV` (diseño visual), `UX` (usabilidad y recorrido) y `FQ` (funciones quitadas o cambiadas). La regla 3 pasa a la marca `u` (problema atribuido a una actualización), que no cuenta para el multi-aspecto. A pedido del autor se agrega la marca de seguridad `s` (hackeo, fraude con la app, desconfianza, biometría como seguridad), también ortogonal. `v1` queda congelada en [`eda_aspects_guideline_v1.md`](../analytics/eda_aspects_guideline_v1.md).
> * **Proceso:**
>   1. calibración del autor en dos rondas, de 30 y 20 textos;
>   2. muestra de 300 (150 enriquecidos con casos de diseño y 150 aleatorios), codificada a ciegas por el autor y por Gemini (`aspects_v2`);
>   3. recodificación intra-autor de 50 textos tras una semana o más;
>   4. Gemini sobre las 1 500 extracciones representativas.
> * **Regla de decisión** (guía, sección 6, fijada antes de codificar): `DV` y `UX` quedan separados si cada uno tiene κ intra-autor ≥ 0.70, κ autor–Gemini ≥ 0.60, confusión entre ellos < 20 % de sus desacuerdos y prevalencia ≥ 2 %. Si no, se fusionan en `DU`. `FQ` sigue el mismo criterio contra `UX` y `FA`, y si falla se fusiona con `UX`.
> * **Avance (2026-10-20):**
>   * hechos: la guía `v2-draft`, el prompt [`aspects_v2`](../../experiments/analytics/src/voc_analytics/eda/prompts/aspects_v2.md), [`eda_aspects_v2.py`](../../experiments/analytics/src/voc_analytics/eda/eda_aspects_v2.py) y la app [`aspects_v2_app.py`](../../experiments/analytics/src/voc_analytics/eda/aspects_v2_app.py);
>   * colas de calibración (30) y de muestra (300) exportadas;
>   * **calibración, ronda 1:** 30 textos, acuerdo exacto autor–Gemini del 33 %. Se ajustaron las fronteras `AC`/`FA`, `PR` (incluye consultas de cuenta), `CO` (permisos), `UX` (no es frustración) y `FQ` (va sola), y se agregó la marca `s`;
>   * **calibración, ronda 2:** 20 textos (14 de diseño y 6 de seguridad), acuerdo exacto del 40 %; κ de `u` 0.70 y de `s` 0.61. Se aclararon cinco fronteras: funciones que no existen van a su dominio, `FQ` exige que el texto diga que se quitó, "diseño" no implica `DV`, los trámites de la cuenta van a `PR` y `s` es solo para quejas;
>   * **`OT` deja de ser caja de sastre** (decisión del autor): publicidad, notificaciones, idioma y actualización forzosa pasan a `UX`; espacio y batería a `CO`; cajeros a `TR`; puntos a `PR`. `OT` queda como "sin familia" y su prevalencia es la alarma de un tema nuevo;
>   * **calibración, ronda 3:** 30 textos (16 de diseño, 8 de lo que antes era `OT` y 6 de seguridad); acuerdo exacto del 46.7 %; κ de `u` 0.83, de `s` 0.78 y de `FQ` 1.0. El autor decidió que `UX` no incluye la fricción de una operación del dominio y que `s` incluye la privacidad;
>   * **guía `v2` congelada (2026-10-20);**
>   * Gemini (`aspects_v2`) ya codificó la muestra de 300 y las 1 500 extracciones ($0.17 en total);
>   * **muestra codificada por el autor con `v2` (2026-10-21):** acuerdo exacto con Gemini del 54 %; κ de `DV` 0.81, de `UX` 0.55, de `u` 0.66 y de `s` 0.71. La regla fusionaría `DV` y `UX` por el κ de `UX`. El autor mantiene `DV` separado como desviación explícita: la confusión entre ellas es del 3 % y el κ bajo de `UX` viene de su frontera con `CO`, `AC` y `PR`. `FQ` se fusiona con `UX` por prevalencia (0.8 %);
>   * **guía `v2.1`, taxonomía final:** `FQ` dentro de `UX`, instalación y actualización en `CO`, token y códigos en `AC`, y casillas agrupadas en orden de decisión. Gemini ya codificó con `aspects_v2_1` la muestra y las extracciones ($0.16);
>   * **recodificación con `v2.1` (2026-10-21):** los 300, 17 horas o más después. `UX` subió de κ 0.55 a 0.74 sin fusionarse con `DV`; `CO` de 0.61 a 0.77; `PR` de 0.52 a 0.62. Estabilidad intra-autor en los códigos sin cambio: `DV` 0.97, `LE` 0.88, `DI` 0.85, `AT` 0.71, `u` 0.83, `s` 0.93. El autor mantiene `DV` separado como excepción a la prevalencia mínima;
>   * **límite:** la marca `s` tiene muy pocos positivos y su κ autor–Gemini (0.56) no es concluyente.
> * **Entregable para 5.5 (entregado):** la guía `v2.1` vigente, las etiquetas `aspects_v2_1` con su esquema de columnas, y `aspects_v2_metrics.json` y `aspects_v2_1_metrics.json`.
>
> **Se vuelve a reabrir si hay un snapshot nuevo del TDS.**

**Objetivo:** describir los 15 años y 5 bancos y decidir la limpieza y la elegibilidad.

* **Hecho:** [EDA global](../analytics/eda_report.md) (2026-10-16), [patrones temporales](../analytics/eda_temporal_report.md) (2026-10-18) y [segunda pasada](../analytics/eda_report.md#5-pendientes-cerrados-tokens-multi-aspecto-y-léxico) (2026-10-20). Conclusiones en el [capítulo 2](../analytics/README.md#2-eda-y-elegibilidad).
* **Decisiones vigentes:**
  * sin filtro de longitud: la longitud predice las estrellas y filtrar sesga los agregados;
  * deduplicar por texto único antes de etiquetar y predecir;
  * la plata no necesita estratos de quincena, día de la semana ni trimestre; los atributos temporales se guardan por fila;
  * las ventanas de deriva de 5.7 siguen la cadencia de cada banco (semanal en NUBANK, 2–5 semanas en el resto);
  * el tope de 128 tokens de 5.4 se mantiene: trunca menos del 0.1 % de las filas (RoBERTuito 0.03 %, BETO 0.07 %).
* **Evidencia para otras features:**
  * **5.5, multi-aspecto (`v1`, superada por `v2.1`: 24.7 % [22.6, 26.8], ver 5.2.1):** según Gemini (`aspects_v1`), el 32 % [30, 34] de las filas `NEG` tiene dos o más problemas, y el 51 % de las de 20 palabras o más. El autor, a ciegas en 100 textos, marca 44 % [35, 54] (κ 0.42), así que el 32 % es una cota inferior. Un tercio o más de las quejas mezcla problemas: conviene un esquema de varios aspectos por reseña;
  * **5.5, `TOPIC_TOO_SHORT`:** decidido k = 1 (decisión del autor, 2026-10-22). Las negativas cortas casi nunca son multi-aspecto, pero **sí** nombran problemas concretos. Lo decía al revés y lo corrigió 5.5 el 2026-10-21: nombran un problema concreto el 4 % [1, 18] de las negativas de una palabra, el 46 % [33, 60] de las de 2 y el 77 % [70, 83] de las de 3 a 5; lo que casi nunca son es multi-aspecto (0–4 %) ([`topics_report.md`](../analytics/topics_report.md#43-topic_too_short-k--1-se-confirma-con-v21-y-los-5-bancos), sección 4.3; confirmadas con `aspects_v2_1` y los 5 bancos);
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
  * **Oro vigente** (`gold_v0_r2` + `gold_v1`, 1 730 ítems): *dev* aleatorio 799, *dev* dirigido 300, *test* 601 y 30 de calibración. Solo el bloque aleatorio da cifras poblacionales; el *test* se evalúa una sola vez, en 5.8. Diseño en [`gold_v1_design.md`](../analytics/gold_v1_design.md).
  * **Plata vigente:** `silver_v0`, 99 926 filas y 70 284 textos únicos por $3.37, con holdout temporal desde 2026-04-01.
  * **Herramienta del oro:** app Streamlit local (`voc_analytics.annotation`), solo en `localhost`; guarda en CSV fuera de git y registra el tiempo por reseña.
  * `prompt_v4` solo se justificaba si `menciona_falla` entraba a las métricas de 5.5; 5.5 cerró sin usarla, así que no se necesita.
* **Segundo anotador (2026-10-20):** 100 ítems a ciegas de `gold_v1`, con la guía `v2.2`. κ entre personas 0.81 [0.70, 0.91] con 4 clases y 0.87 con 3; Gemini coincide con cada anotador (0.91 y 0.88 en *dev*) tanto o más que ellos entre sí. El desacuerdo principal es la regla 2 amplia: el segundo anotador decide por el tono. Ver el [reporte](../analytics/gold_v1_report.md), sección 7.
* **F-01 (hecho, 2026-10-20):** la [matriz FMEA](../governance/ethical_fmea_matrix.md#f-01-nombres-propios-en-texto-libre) registra la tasa medida de nombres propios, 0 en 1 300 anotadas. RPN 105 → 70; la fila pasa a monitoreo.

### FEATURE 5.4: Competencia de Modelos de Sentimiento con Etiquetas Ruidosas

**Objetivo:** elegir el modelo de Q1 por evidencia, con el mismo protocolo para todos.

* **Candidatos y protocolo:** escalera M0–M9, particiones, métricas y regla de decisión en [`sentiment_models_protocol.md`](../analytics/sentiment_models_protocol.md). M8 (Delora) es el más caro y el menos validado: se time-boxea y solo se adopta si supera claramente a los métodos baratos.
* **Hecho:** fase A en el Mac (M0, M1, M2, T0, M9), escalera de ruido con TF-IDF (M3, M6, M7), M4 con RoBERTuito y BETO (3 semillas cada uno) M8 Delora (búsqueda del detector y 3 semillas), M5 (*label smoothing* sobre M4, 2 valores de ε y 3 semillas) en Kaggle y un sesgo de `NEU` sobre M4, evaluados con el *dev* ampliado. Detalle en las secciones 12 a 14 del [reporte](../analytics/sentiment_models_v0_report.md). Ver el [capítulo 4](../analytics/README.md#4-competencia-de-modelos-de-sentimiento).
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

* **Estado (2026-10-22):** **cerrada.** Recomendación aprobada por el autor; agregado: los flujos de curaduría y una base de datos de curadurías para el reentrenamiento pasan al frontal HITL de EPIC-6 ([requisitos y borrador del modelo de datos](../analytics/topics_decision_note.md#agregado-del-autor-2026-10-22-curaduría-hitl-en-epic-6)). [Plan aprobado](../analytics/topics_design.md), [reporte](../analytics/topics_report.md) (fases 0 a 4) y [nota para el registro de decisión](../analytics/topics_decision_note.md). Todo en local sobre la plata, sin backfill de sentimiento; la vía B a escala costó $3.64.

* **Descubrimiento (hecho):** sobre las reseñas negativas elegibles para tópico, agrupar embeddings por periodo (estilo BERTopic: embeddings → reducción de dimensión → HDBSCAN → términos representativos por c-TF-IDF y nombre propuesto por un LLM).
* **Lectura temporal (hecha, [reporte](../analytics/topics_report.md) §3.2):** qué tópicos son estables, cuáles aparecen tras una versión concreta y cuáles desaparecen, por banco.
* **Validación humana (hecha, fase 4, [reporte](../analytics/topics_report.md) §4.7):** revisión de los tópicos principales (coherencia, utilidad para producto) y contraste con la taxonomía hipotética de 8 `ABSATopic`.
* **Opciones (decidido: híbrido, 2026-10-22):**

  | Opción | Ventaja | Riesgo |
  | :--- | :--- | :--- |
  | Taxonomía fija (ABSA ligero) | Estable, comparable en el tiempo, simple de reportar | No ve incidentes nuevos; envejece |
  | Tópicos dinámicos | Detecta temas nuevos sin reentrenar | Nombres e identidad cambian entre corridas; requiere curaduría |
  | **Híbrido: núcleo estable + "emergentes" (elegido)** | Comparabilidad y detección de lo nuevo | Más complejidad operativa |

* **Detección de incidentes (Q3, hecha: la marca `u` detecta 2 de 3 incidentes de BBVA con 4 % de falsas alarmas; `DV` y `UX` avisaron del rediseño un mes antes; [reporte](../analytics/topics_report.md) §3.3 y §4.4):** proponer una señal (aparición o crecimiento anómalo de un tópico por banco y versión) y probarla hacia atrás con los picos que ya mostró el EDA (BBVA 2024-07, 2025-10 y 2025-11) y con los días pico de SANTANDER y AZTECA donde las 5★ esconden quejas.
* **Insumos de 5.2** ([EDA](../analytics/eda_report.md#52-proporción-multi-aspecto-de-las-negativas), sección 5.2): entre el 32 % (Gemini, cota inferior) y el 44 % (autor) de las negativas es multi-aspecto, y la mitad de las de 20 palabras o más, lo que favorece tópicos por cláusula o ABSA multi-etiqueta sobre un tópico por reseña. ~~Las negativas de 1 a 5 palabras casi nunca nombran un problema~~ **Corregido en 5.5 (2026-10-21; confirmado con `v2.1` y los 5 bancos):** casi nunca son multi-aspecto, pero sí nombran un problema concreto: el 4 % [1, 18] de las de una palabra, el 46 % [33, 60] de las de 2 y el 77 % [70, 83] de las de 3 a 5. Excluirlas no mejora los tópicos: `TOPIC_TOO_SHORT` con k = 1 (decisión del autor, 2026-10-22; antes, recomendación de 5.5) ([reporte](../analytics/topics_report.md#43-topic_too_short-k--1-se-confirma-con-v21-y-los-5-bancos)). Con la guía `v2.1`, las familias más frecuentes son falla general (29.5 %), acceso (24.4 %), transferencias (13.7 %), productos (11.5 %) y lentitud (10.6 %), y el multi-aspecto es 24.7 %. Para codificar aspectos con Gemini está la [guía de aspectos `v2.1`](../analytics/eda_aspects_guideline.md) (validada por el autor; prompt `aspects_v2_1`), que reemplaza `DS` (κ 0.39 en `v1`) por `DV` y `UX` (κ 0.74 cada una), pasa la instalación y la actualización a `CO` y el token a `AC`, y agrega las marcas `u` (actualización, κ 0.70) y `s` (seguridad, no concluyente).
* **Entregable:** recomendación con su costo de operación (frecuencia de re-clustering, curaduría humana, estabilidad de identificadores de tópico). **Aprobada (2026-10-22):** [reporte, sección 5](../analytics/topics_report.md#5-recomendación-aprobada-por-el-autor-2026-10-22) y [nota para 5.8](../analytics/topics_decision_note.md). Queda para 5.7: los umbrales de la señal, el análisis por versión, el emparejamiento de tópicos entre reajustes y el monitoreo de `OT`; para 5.8: el modelo de sentimiento del que dependen las familias.

### FEATURE 5.6: Calibración, Incertidumbre, HITL y Priorización

* **Calibración:** *temperature scaling* (Guo et al., 2017) sobre el oro *dev*, antes de cualquier uso de probabilidades o entropía. En el *dev* de 199, M1 tenía ECE 0.02 y M4 0.017 sin calibrar; se re-mide con el *dev* ampliado.
* **Umbral de revisión humana:** elegido por la curva cobertura–riesgo en el oro *dev*, no fijado a priori en 0.65.
* **Estimaciones poblacionales:** PPI con la plata y el oro aleatorio para la incongruencia por banco y periodo con intervalos válidos.
* **Priorización (Q4):** las fórmulas de `tnss_numeric_calibrated` y `priority_weight_score` de la especificación anterior son hipótesis. Se evalúan contra un criterio observable (por ejemplo, ordenar incidentes conocidos) antes de adoptarlas. Los votos de utilidad son escasos y de cola larga (EDA, H7): conviene transformarlos.

### FEATURE 5.7: Escala, Ciclo de Vida y Monitoreo

* **Benchmark de escala:** tiempo y costo del backfill sobre los textos únicos y del delta diario para los finalistas (Kaggle T4 y Cloud Run CPU), aplicando deduplicación, orden por longitud y adaptadores fusionados.
* **Ciclo de vida de artefactos:** registro de versiones (GCS versionado o Vertex Model Registry), Model Card por versión, regla de promoción y rollback, y política de **re-scoring** al cambiar de modelo (todo el histórico o solo lo nuevo).
* **Monitoreo (sin y con etiquetas):**

  | Nivel | Qué se mide | ¿Requiere etiquetas? |
  | :--- | :--- | :---: |
  | Entrada | Longitud, idioma, vocabulario nuevo, `version_app`, proporción de no predecibles | No |
  | Predicción | Proporción de `NEG` por banco y versión; confianza media | No |
  | Concepto | Desempeño sobre una muestra humana periódica pequeña | Sí |
  | Tópicos | Aparición y crecimiento de tópicos; esperado, no un fallo | No |

### FEATURE 5.8: Registro de Decisión

`docs/analytics/decision_record.md`, con la evidencia de 5.2–5.7. Fija:

* modelo de sentimiento, encoder y método de ruido (o su ausencia), con métricas del oro *test* e intervalos;
* estrategia de tópicos y detección de incidentes;
* reglas de limpieza y elegibilidad, incluida `TNSS_SINGLE_WORD`;
* esquema de las tablas de salida y migración desde `delora_predictions`;
* umbral HITL y priorización;
* plan de backfill, operación diaria, ciclo de vida y monitoreo;
* límites y riesgos para la Model Card y la FMEA.

Al aprobarlo se reescribe `epic_5_deployment.md` (fase 3) con las dependencias, tablas y pruebas que correspondan.

---

<a id="siguientes-pasos"></a>

## 🧭 Siguientes pasos

En orden. Cada paso sale de un pendiente de los reportes o del alcance de su feature.

| # | Paso | Dueña | Depende de | Terminado cuando |
| :---: | :--- | :---: | :--- | :--- |
| 1 | **Hecho (2026-10-20).** Regenerar el paquete de Kaggle tras la consolidación en `voc_analytics`, subirlo y correr el lote `humo` | 5.4 | — | `kaggle_push dataset --update` hecho y `humo` instala, ve la GPU y escribe salidas de M4 y Delora |
| 2 | **Hecho (2026-10-20):** κ *dev* 0.917 con RoBERTuito y con BETO (media de 3 semillas); M4 − M1 significativo en las 6 corridas; RoBERTuito gana en el dirigido (0.63 contra 0.58). Ver el [reporte](../analytics/sentiment_models_v0_report.md), sección 12. **Semillas de M4:** RoBERTuito y BETO, 3 semillas cada uno (lote `m4`) | 5.4 | 1 | Predicciones evaluadas con `evaluate` en el *dev* aleatorio y el dirigido; reporte con la varianza entre semillas y las diferencias pareadas contra M1 y M9 |
| 3 | **Evaluado y descartado con motivo (2026-10-20):** κ 0.913 con ε = 0.1 y 0.2; empata con M4 y calibra peor (ECE 0.05 y 0.10 contra 0.035). Ver el [reporte](../analytics/sentiment_models_v0_report.md), sección 14. **M5:** *label smoothing* sobre M4 RoBERTuito, dirigido a la brecha de `NEU` contra Gemini | 5.4 | 2 | Evaluado con el mismo protocolo, o descartado con motivo |
| 4 | **Evaluado y descartado con motivo (2026-10-20):** κ *dev* 0.866, M8 − M4 entre −0.04 y −0.05, significativo en las 3 semillas; el detector queda como candidato para la incongruencia. Ver el [reporte](../analytics/sentiment_models_v0_report.md), sección 13. **M8 Delora:** búsqueda del detector (`delora_grid`, elegida por F1 de detección fuera de muestra contra la plata) y Delora completo con 3 semillas | 5.4 | 1; se compara contra 2 y 3 | Evaluado o descartado con motivo, dentro de su *time-box* |
| 5 | ~~Actualizar F-01 (y la nota de F-13) en la matriz FMEA con la tasa medida~~ **Hecho (2026-10-20):** 0 nombres en 1 300 anotadas; O 3 → 2 y RPN 105 → 70 | Documentación y gobierno | — | Estado de F-01 y su calificación actualizados con la evidencia de [`gold_v1`](../analytics/gold_v1_report.md), sección 5 |
| 6 | ~~Calificar F-12~~ **Hecho (2026-10-20):** sesión presencial en el Mac del autor, sin copia, con acuerdo verbal; RPN 25 | Documentación y gobierno | Decisión del autor | Fila F-12 calificada en la matriz FMEA |
| 7 | ~~Segundo anotador de `gold_v1`~~ **Hecho (2026-10-20):** κ entre personas 0.81 [0.70, 0.91] con 4 clases y 0.87 con 3; Gemini coincide con cada anotador (0.91 y 0.88) tanto o más que ellos entre sí (0.80). Ver [`gold_v1`](../analytics/gold_v1_report.md), sección 7 | 5.3 | 6 y una persona disponible | Acuerdo entre personas (κ) reportado con su IC y comparado con el acuerdo humano–Gemini |
| 8 | ~~Actualizar la *Data Card* con el oro `gold_v1`~~ **Hecho (2026-10-20):** la sección de etiquetas cita el oro vigente y el acuerdo entre personas | Documentación y gobierno | — | La sección de etiquetas cita el oro vigente y el [índice de la historia](../analytics/README.md#qué-cifra-citar) |
| 9 | ~~Pendientes de 5.2: tokens, multi-aspecto y léxico para reseñas cortas~~ **Hecho (2026-10-20):** el tope de 128 tokens trunca menos del 0.1 %; multi-aspecto del 32 % (Gemini) al 44 % (autor, κ 0.42); el léxico cubre el 95.3 % de las reseñas de una palabra con 99 % de exactitud. Ver el [EDA](../analytics/eda_report.md#5-pendientes-cerrados-tokens-multi-aspecto-y-léxico), sección 5, y la *Data Card* `v0.2` | 5.2 | 2 para los tokenizadores | Agregados en el reporte del EDA |
| 10 | ~~**5.5 Tópicos:** piloto de tópicos, umbral de `TOPIC_TOO_SHORT` y señal de incidentes~~ **Hecho (2026-10-22):** híbrido aprobado (familias `v2.1` y marca `u` como núcleo, tópicos como capa curada), `TOPIC_TOO_SHORT` k = 1 y señal probada hacia atrás; la curaduría HITL pasa a EPIC-6 (6.7) | 5.5 (hilo propio) | Un TNSS predicho para las negativas; 9 (hecho) | [Nota de decisión](../analytics/topics_decision_note.md) |
| 11 | **5.6:** calibración, umbral HITL por cobertura–riesgo, PPI y priorización | 5.6 (al arrancar) | Modelo finalista (2–4) | Umbral y calibración elegidos en el oro *dev* |
| 12 | **5.7:** benchmark de escala de los finalistas, ciclo de vida y plan de monitoreo | 5.7 (al arrancar) | Finalistas (2–4) | Tiempo y costo del backfill y del delta medidos; propuesta de ciclo de vida y monitoreo. Heredado de 5.5: umbrales de la señal, análisis por versión, emparejamiento de tópicos entre reajustes y monitoreo de `OT` |
| 13 | **5.8:** registro de decisión, evaluación única en el oro *test*, decisión de `TNSS_SINGLE_WORD` y aprobación de las reglas | 5.8 (al arrancar) | 2–12 | `decision_record.md` aprobado y `epic_5_deployment.md` reescrito. Heredado de 5.5: registrar la estrategia híbrida ([nota](../analytics/topics_decision_note.md)) y la elección M4/M9, de la que dependen las familias |

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
* [x] Decisión sobre ABSA, tópicos dinámicos o híbrido, con una señal de incidentes probada hacia atrás (5.5). *Híbrido aprobado por el autor (2026-10-22): familias `v2.1` y marca `u` como núcleo y alerta, tópicos como capa de detalle curada; señal probada con los 3 incidentes de BBVA ([reporte](../analytics/topics_report.md), sección 5).*
* [ ] Calibración y umbral HITL elegidos por cobertura–riesgo (5.6).
* [ ] Benchmark de escala, propuesta de ciclo de vida y plan de monitoreo (5.7).
* [ ] Registro de decisión aprobado y `epic_5_deployment.md` reescrito a partir de él (5.8).
* [x] Experimentos reproducibles en `experiments/analytics/` (proyecto `uv` propio, semillas fijas), sin dependencias de experimentación en el `uv.lock` de producción.
