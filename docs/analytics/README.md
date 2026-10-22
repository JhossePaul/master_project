# Analítica de EPIC-5: la historia de los resultados

Esta carpeta reúne los reportes de la fase de planteamiento y experimentación de [EPIC-5](../backlog/epic_5.md). Cada reporte se escribió en su momento y conserva sus cifras como evidencia. Este índice los ordena como una historia y dice, para cada capítulo, qué conclusión sigue vigente.

* **Estado:** al 2026-10-20. El estado de cada feature y los siguientes pasos están en [`epic_5.md`](../backlog/epic_5.md).
* **Cómo leer un reporte:** al inicio, una nota **Estado** dice si es vigente, vigente en parte o histórico, y qué lo reemplazó. Las cifras de un reporte histórico no se corrigen: se citan con su fecha o se reemplazan por las del reporte que lo sustituye.
* **Código:** paquete `voc_analytics` en [`experiments/analytics/`](../../experiments/analytics/README.md), con los comandos de cada etapa en orden de ejecución.
* **Datos:** aquí solo hay agregados y ejemplos sintéticos. Las reseñas, las colas y las etiquetas individuales están en `experiments/analytics/data/`, fuera de git.

| # | Capítulo | Feature | Reportes | Estado |
| :---: | :--- | :---: | :--- | :--- |
| 1 | [Problema y corpus](#1-problema-y-corpus) | 5.1 | [`epic_5.md`](../backlog/epic_5.md) | Vigente |
| 2 | [EDA y elegibilidad](#2-eda-y-elegibilidad) | 5.1, 5.2 | [`eda_report`](eda_report.md), [`eda_temporal_report`](eda_temporal_report.md), [`eda_aspects_guideline`](eda_aspects_guideline.md), [`eligibility_rules`](eligibility_rules.md) | 5.2 cerrada (2026-10-21, guía `v2.1`); reglas en borrador |
| 3 | [Etiquetado: guía, pilotos, oro y plata](#3-etiquetado-guía-pilotos-oro-y-plata) | 5.3 | [`annotation_guideline`](annotation_guideline.md), [`labeling_pilot_v0`](labeling_pilot_v0.md), [`gold_v0_report`](gold_v0_report.md), [`gold_v0_r2_report`](gold_v0_r2_report.md), [`silver_v0_report`](silver_v0_report.md), [`gold_v1_design`](gold_v1_design.md), [`gold_v1_report`](gold_v1_report.md) | Cerrada (2026-10-20); oro `gold_v1` y plata `silver_v0` vigentes |
| 4 | [Competencia de modelos de sentimiento](#4-competencia-de-modelos-de-sentimiento) | 5.4 | [`sentiment_models_protocol`](sentiment_models_protocol.md), [`sentiment_models_v0_report`](sentiment_models_v0_report.md), [`gold_v1_report`](gold_v1_report.md) (sección 6) | Experimentación cerrada; M4 contra M9 se decide en 5.8 |
| 5 | [Tópicos e incidencias](#5-tópicos-e-incidencias) | 5.5 | [`topics_design`](topics_design.md), [`topics_report`](topics_report.md), [`topics_decision_note`](topics_decision_note.md) | Cerrado (2026-10-22): híbrido aprobado; `TOPIC_TOO_SHORT` k = 1 |
| 6 | [Siguientes pasos](#6-siguientes-pasos) | 5.3–5.8 | [`epic_5.md`](../backlog/epic_5.md#siguientes-pasos) | — |

---

## 1. Problema y corpus

El proyecto quiere medir el **sentimiento real del texto** de las reseñas de apps bancarias, separado de las estrellas, y usarlo para detectar y priorizar incidencias (preguntas Q1–Q4 de [`epic_5.md`](../backlog/epic_5.md)). La hipótesis central es que **las estrellas son una etiqueta ruidosa**: hay quejas escondidas en 4★ y 5★ (*Obligatory 5-Star*).

* **Corpus:** `bbva_voc_tds.sanitized_reviews_tds`, 2 649 047 reseñas de BBVA, NUBANK, SANTANDER, AZTECA y BANORTE (2011-04 a 2026-10). Snapshot local `tds_20261016T054714Z`. Ver la [*Data Card*](../governance/data_card.md).
* **Límites heredados de EPIC-1–4** ([cierre](../backlog/closure_epics_1_4.md)): `fecha` es la de la última edición; la sanitización es solo regex, así que puede quedar PII residual (FMEA F-01).
* **Presupuesto humano:** 1 000 etiquetas de base y hasta 2 000 con esfuerzo extra. El corpus completo solo se predice.

**Evidencia inicial (2026-10-16).** Consulta de longitudes por banco y año sobre el TDS, antes del EDA (palabras = tokens separados por espacios de `texto_limpio`):

| Banco | Filas | Textos únicos (cota) | 1 palabra | > 60 palabras | p99 por año | Máx. | Estrellas prom. | Antes de 2018 |
| :--- | ---: | ---: | ---: | ---: | :---: | ---: | ---: | ---: |
| BBVA | 787 875 | ≤ 65 % | 16.8 % | 2.4 % | 57–84 | 384 | 3.72 | 7.9 % |
| SANTANDER | 623 594 | ≤ 60 % | 18.2 % | 1.0 % | 52–87 | 625 | 4.03 | 0.9 % |
| AZTECA | 590 981 | ≤ 52 % | 21.9 % | 0.9 % | 50–88 | 655 | 4.40 | 0.2 % |
| BANORTE | 518 393 | ≤ 60 % | 17.5 % | 1.0 % | 51–87 | 297 | 4.25 | 2.6 % |
| NUBANK | 128 204 | ≤ 72 % | 14.7 % | 2.6 % | 30–100 | 114 | 4.21 | 0.0 % |
| **Total** | **2 649 047** | **≤ 1.60 M (60 %)** | **18.3 %** | **1.46 %** | **50–89** | **655** | | **3.1 %** |

Los textos únicos de esta tabla son una cota superior; el EDA midió 1 383 138 (52.2 %).

**Conclusión vigente:** un encoder de 512 tokens cubre el corpus, y el tope de 128 de 5.4 trunca menos del 0.1 % de las filas ([EDA](eda_report.md#51-longitud-en-tokens), sección 5.1); deduplicar ahorra cerca de la mitad de la inferencia; no hay una distribución estable en el tiempo, así que todo se estratifica por banco × periodo.

## 2. EDA y elegibilidad

| Reporte | Estado | Conclusión vigente |
| :--- | :--- | :--- |
| [EDA global](eda_report.md) | Vigente | **La longitud predice las estrellas** (1 palabra: 4.75★; más de 60: ~1.9★), así que cualquier filtro por longitud sesga los agregados. Pocos textos concentran el corpus ("excelente" es el 6.5 % de las filas) y la detección de idioma confunde el español informal. Hay picos de campañas de calificación y de incidentes (BBVA 2024–2025). |
| [Patrones temporales](eda_temporal_report.md) | Vigente (versión 2) | Sin ciclo trimestral; sprints de 1–2 semanas en NUBANK, BBVA y AZTECA. **La quincena sube el volumen de todas las estrellas, no las quejas.** Con la plata: en los días pico de SANTANDER y AZTECA las 5★ esconden más quejas, el patrón de incidencia que busca el proyecto. |
| [EDA, segunda pasada](eda_report.md#5-pendientes-cerrados-tokens-multi-aspecto-y-léxico) (sección 5) | Vigente | **Tokens:** el tope de 128 trunca menos del 0.1 %. **Multi-aspecto:** entre el 32 % (Gemini, cota inferior) y el 44 % (autor, κ 0.42) de las negativas nombra dos o más problemas, y la mitad de las de 20 palabras o más; las de 1 a 5 palabras casi nunca son multi-aspecto, pero sí nombran un problema concreto (4 % de las de una palabra, 48–50 % de las de 2 y 77–81 % de las de 3 a 5; provisional, sección 2.3 de [`topics_report`](topics_report.md), con `aspects_v2` sin validar). **Léxico:** 151 formas cubren el 95.3 % de las reseñas de una palabra con 99 % de exactitud; excluir solo las no cubiertas casi no sesga las estrellas. |
| [Guía de aspectos](eda_aspects_guideline.md) | `v2.1`, vigente y cerrada (copias congeladas: [`v1`](eda_aspects_guideline_v1.md) y [`v2`](eda_aspects_guideline_v2.md)) | Taxonomía de 11 códigos para las negativas; "sin problema concreto" es explícito (sin familias). `FQ` se fusionó en `UX`; `CO` incluye instalar y actualizar; `AC` incluye todo el token; `DV` se mantiene separado por decisión del autor, como excepción a la prevalencia mínima. Las marcas ortogonales `u` (actualización) y `s` (seguridad, incluye privacidad) sustituyen a la regla 3 de `v1`. La siguen el prompt `aspects_v2_1` y la app de validación. El κ 0.39 de `DS` es un dato de `v1`. |
| [Reglas de elegibilidad](eligibility_rules.md) | Borrador `v0.1` | Reglas deterministas por tarea con código de motivo; la fila excluida se conserva como `NOT_PREDICTED`. Corte de NUBANK en 2020-01-01. `TNSS_NOT_SPANISH` descartada. **Abierto:** `TNSS_SINGLE_WORD` (5.8) y `TOPIC_TOO_SHORT` (5.5). |

**Feature 5.2 cerrada (2026-10-21), con la [sección 5.2.1](eda_report.md#521-guía-de-aspectos-v2-y-v21-reapertura-para-55) de `eda_report.md` (guía de aspectos `v2.1`).** Se reabre si hay un snapshot nuevo.

Figuras: [`eda/figures/`](eda/figures/monthly_volume.png); métricas: [`eda/metrics.json`](eda/metrics.json), [`eda/temporal_metrics.json`](eda/temporal_metrics.json), [`eda/tokens_metrics.json`](eda/tokens_metrics.json), [`eda/aspects_v1_metrics.json`](eda/aspects_v1_metrics.json) y [`eda/lexicon_metrics.json`](eda/lexicon_metrics.json).

## 3. Etiquetado: guía, pilotos, oro y plata

La estrategia: **Gemini Flash** (Vertex AI, dentro de GCP) etiqueta una **plata** grande para entrenar, y un **oro** humano, anotado a ciegas, mide a Gemini, a las estrellas y a los modelos.

| Paso | Reporte | Estado | Conclusión |
| :---: | :--- | :--- | :--- |
| 3.1 | [Guía de anotación](annotation_guideline.md) | Vigente, `v2.2` | `NEG`/`NEU`/`POS` más `NO_EVALUABLE`. **Cualquier queja concreta es `NEG`**, aunque venga con elogios o sea menor (regla 2); desde `v2.2`, también las decisiones del banco que no se explican. Marcas `menciona_falla` y `nombre_persona`. |
| 3.2 | [Piloto de Gemini](labeling_pilot_v0.md) | Histórico | Se elige `gemini-3.6-flash` con razonamiento mínimo. La salida compacta baja el costo 58 %; el presupuesto deja de ser restricción y la restricción real es el tiempo humano. |
| 3.3 | [Oro, primera ronda](gold_v0_report.md) | Histórico | 450 ítems. **El anclaje es fuerte** (+7 puntos de acuerdo al ver la propuesta de Gemini): desde aquí todo se anota a ciegas. Nace la guía v1 (regla 2 amplia). |
| 3.4 | [Re-anotación a ciegas](gold_v0_r2_report.md) | Vigente en parte | Las 400 aleatorias, re-anotadas a ciegas con la guía v2, entran al oro. **Se elige `prompt_v3`** para la plata (99.8 % de estabilidad, $0.045 por 1 000 textos). |
| 3.5 | [Plata](silver_v0_report.md) | Vigente | 99 926 filas (70 284 textos únicos) por $3.37. Coincide con el oro: **73 % de las 3★ y 28.5 % de las 4★ son `NEG`**. |
| 3.6 | [Diseño de `gold_v1`](gold_v1_design.md) y [reporte](gold_v1_report.md) | Vigente | 1 350 ítems más (aleatorio estratificado y dirigido). **κ humano–Gemini 0.92** en 600 textos nuevos; ruido de las estrellas 12.5 % (EE 1.3); 0 nombres propios en 1 000 aleatorias. **Segundo anotador:** κ entre personas 0.81 (0.87 con 3 clases); Gemini coincide con cada anotador tanto o más que ellos entre sí. |

**Feature 5.3 cerrada (2026-10-20).** Se reabre si 5.5 usa `menciona_falla` (`prompt_v4`), si 5.6 o 5.8 necesitan más oro, o si se suman anotadores (guía `v2.3`).

**Versiones vigentes:** guía `v2.2`, `prompt_v3` con `gemini-3.6-flash`, plata `silver_v0`, oro `gold_v0_r2` + `gold_v1`.

**Oro vigente** (1 730 ítems):

| Partición | Ítems | Origen | Uso |
| :--- | ---: | :--- | :--- |
| *Dev* aleatorio | 799 (794 evaluables) | 199 de `gold_v0_r2` y 600 de `gold_v1` | Comparación de modelos, umbrales, calibración |
| *Dev* dirigido | 300 (297 evaluables) | `gold_v1` | Casos difíciles y `NEU`; nunca cifras poblacionales |
| *Test* | 601 | 201 de `gold_v0_r2` y 400 de `gold_v1` | **Una sola evaluación, en 5.8** |
| Calibración | 30 | `gold_v0_r2` | No se usa en métricas |

## 4. Competencia de modelos de sentimiento

El [protocolo](sentiment_models_protocol.md) fija los candidatos (M0–M9), las particiones y la regla de decisión: un modelo más caro reemplaza a uno más barato solo si su diferencia pareada en el oro *dev* excluye el 0.

| Paso | Reporte | Estado | Conclusión |
| :---: | :--- | :--- | :--- |
| 4.1 | [Primera ronda](sentiment_models_v0_report.md), secciones 1–8 | Vigente en parte | Fase A en el Mac, sin gasto. Los encoders sin ajuste (M2) no superan a las estrellas por el esquema de TASS; `TextBlob` no sirve para español. Se fija `texto_sanitizado`, un ejemplo por texto, sin pesos ni filtro de longitud. |
| 4.2 | [Escalera de ruido y M4](sentiment_models_v0_report.md), secciones 9–11 | Vigente en parte | Aprender de las estrellas (M3, M6, M7) no alcanza a destilar a Gemini (M1). Primer M4 en el Mac; se decide entrenar en Kaggle (FMEA F-13). |
| 4.3 | [Comparación con `gold_v1`](gold_v1_report.md), sección 6 | Vigente en parte | Con el *dev* ampliado, las cifras de 4.1 y 4.2 bajan por el anclaje. **M4 supera a M1** y queda cerca de Gemini (tabla). |
| 4.4 | [Kaggle: semillas de M4, M8 Delora y M5](sentiment_models_v0_report.md), secciones 12 a 14 | **Vigente** | M4 con 3 semillas por encoder: κ 0.917 y M4 − M1 significativo. M8 es significativamente peor que M4 y se descarta. M5 empata con M4 y calibra peor, así que también se descarta. El sesgo de `NEU` no se adopta (Δκ −0.001). Se verificaron errores del paper de Delora en las Eq. 5 y 6. |

**Cifras vigentes** (κ en el *dev* aleatorio, n = 794, IC 95 %):

| Modelo | κ | Diferencia pareada |
| :--- | :---: | :--- |
| M0 estrellas | 0.68 (0.65–0.72) | — |
| M1 TF-IDF + LR con la plata | 0.87 (0.84–0.90) | M1 − M0: +0.19 [0.14, 0.23] |
| M4 RoBERTuito ajustado con la plata (media de 3 semillas, rango) | 0.917 (0.912–0.922) | M4 − M1: entre +0.043 y +0.053, significativo en las 6 corridas (RoBERTuito y BETO) |
| M4 BETO (media de 3 semillas, rango) | 0.917 (0.912–0.923) | Empata con RoBERTuito; en el dirigido, 0.58 contra 0.63 |
| M8 Delora con RoBERTuito (media de 3 semillas, rango) | 0.866 (0.860–0.874) | M8 − M4: entre −0.039 y −0.052, significativo en las 3 semillas; descartado |
| M5 M4 RoBERTuito con *label smoothing* (ε = 0.1 y 0.2) | 0.913 | Empata con M4 y calibra peor (ECE 0.05 y 0.10 contra 0.035); descartado |
| M9 Gemini `prompt_v3` | 0.93 (0.91–0.96) | M9 − M4: +0.021 [−0.000, 0.043] |

**Conclusión vigente (experimentación cerrada, 2026-10-20):** la escalera M0–M9 está completa. M4 RoBERTuito es el mejor modelo propio: κ 0.917 con 3 semillas, 0.63 en el dirigido y sin costo por texto. Queda a +0.021 [−0.000, 0.043] de Gemini, una brecha de unos 5 `NEU` de 30 que el *dev* no puede resolver. M5 y M8 se descartan; el detector de M8 se conserva como candidato para la incongruencia. La elección entre M4 y M9 queda para 5.8, por costo (Gemini ~$72 el backfill), licencia (`pysentimiento` es no comercial) y el oro *test*, que sigue intacto. Con κ 0.81–0.87 entre personas, diferencias de ~0.02 entre los mejores modelos quedan por debajo del ruido entre anotadores ([`gold_v1`](gold_v1_report.md), sección 7).

## 5. Tópicos e incidencias

Feature 5.5, con hilo propio. [`topics_design`](topics_design.md) es el plan `v1` aprobado por el autor (alcance, enfoque, métricas, entregables, riesgos); [`topics_report`](topics_report.md) es el reporte, cerrado el 2026-10-22: cerró las fases 0 a 3 (la 3 sin llamadas nuevas a Gemini, sección 4); su lectura provisional apoya el híbrido. La vía B a escala está hecha (40 382 negativas de la plata codificadas con `aspects_v2_1`, $3.64, sección 4.5) y el autor decidió `TOPIC_TOO_SHORT` k = 1 (2026-10-22). Usa la [guía de aspectos](eda_aspects_guideline.md) `v2.1` y el prompt `aspects_v2_1`. [`topics_decision_note`](topics_decision_note.md) resume la recomendación para el registro de decisión (5.8). **Cerrado (2026-10-22): el autor aprobó el híbrido** (familias `v2.1` como núcleo, marca `u` como alerta, tópicos como capa de detalle curada) y pidió que los aplicativos de curaduría pasen al frontal de EPIC-6 con una base de curadurías. Las métricas están en la [tabla de abajo](#archivos-de-métricas).

---

## 6. Siguientes pasos

La lista ordenada, con dueño, dependencia y criterio de terminado, está en [`epic_5.md`, "Siguientes pasos"](../backlog/epic_5.md#siguientes-pasos). En resumen:

1. 5.4 cerrada: la elección entre M4 y M9 pasa a 5.8.
2. ~~Pendientes de 5.2: tokens, multi-aspecto y léxico para reseñas cortas~~: hechos (2026-10-20); 5.2 cerrada.
3. Tópicos e incidencias (5.5), calibración y HITL (5.6), escala y monitoreo (5.7).
4. Registro de decisión y evaluación única en el oro *test* (5.8).

---

## Qué cifra citar

| Medida | Cifra vigente | Fuente | Cifras anteriores (no citar sin fecha) |
| :--- | :--- | :--- | :--- |
| Estrellas distintas del texto (población, filas elegibles) | 12.5 % (EE 1.3) | [`gold_v1`](gold_v1_report.md), sección 2 | 10.4 % ([`gold_v0`](gold_v0_report.md)), 9.9 % ([`gold_v0_r2`](gold_v0_r2_report.md)), 10.9 % (plata, hereda a Gemini) |
| Incongruencia en los extremos | 5.7 % (EE 1.0) | [`gold_v1`](gold_v1_report.md), sección 2 | 4.2 %, 4.7 %, 5.0 % (plata) |
| κ estrellas contra oro | 0.68 | [`gold_v1`](gold_v1_report.md), sección 2 | 0.71, 0.73 |
| κ humano–Gemini (`prompt_v3`) | 0.92 (600 textos nuevos, a ciegas) | [`gold_v1`](gold_v1_report.md), sección 3 | 0.84–0.88 (primera ronda), 0.93 (cota superior) |
| Consistencia del anotador | κ 0.93 | [`gold_v1`](gold_v1_report.md), sección 1 | 0.83 (misma sesión), 0.93–0.94 (`gold_v0_r2`) |
| Acuerdo entre personas (autor y segundo anotador, 100 ítems a ciegas) | κ 0.81 [0.70, 0.91] con 4 clases; 0.87 con 3 | [`gold_v1`](gold_v1_report.md), sección 7 | — |
| Nombres propios tras la regex (F-01) | 0 de 1 000 aleatorias (cota 95 %: 0.3 %) | [`gold_v1`](gold_v1_report.md), sección 5 | — |
| Costo de la plata | $0.048 por 1 000 textos | [plata](silver_v0_report.md) | $0.124 (`prompt_v0`), $0.052 (`prompt_v1`) |
| Multi-aspecto de las negativas (filas `NEG` elegibles) | 32 % [30, 34] según Gemini (`aspects_v1`, cota inferior); 44 % [35, 54] según el autor en 100 textos; κ autor–Gemini 0.42 | [EDA](eda_report.md#52-proporción-multi-aspecto-de-las-negativas), sección 5.2 | κ 0.29 con `aspects_v0` |
| Cobertura del léxico en reseñas de una palabra | 95.3 % de las filas, 99 % de exactitud en el oro *dev* | [EDA](eda_report.md#53-léxico-determinista-para-reseñas-de-una-palabra), sección 5.3 | — |
| Filas truncadas con el tope de 128 tokens | 0.03 % con RoBERTuito, 0.07 % con BETO | [EDA](eda_report.md#51-longitud-en-tokens), sección 5.1 | — |
| κ de los modelos | tabla del capítulo 4 | [`gold_v1`](gold_v1_report.md), sección 6, y [competencia de modelos](sentiment_models_v0_report.md), secciones 12 a 14 (semillas) | M1 0.91 y M4 0.95 en el *dev* de 199 (inflados por el anclaje) |

## Archivos de métricas

Todos los escribe el paquete `voc_analytics`; solo contienen agregados.

| Archivo | Lo escribe | Reporte | Estado |
| :--- | :--- | :--- | :--- |
| [`eda/metrics.json`](eda/metrics.json) y `eda/figures/` | `eda.eda_global` | [EDA global](eda_report.md) | Vigente |
| [`eda/temporal_metrics.json`](eda/temporal_metrics.json) y `eda/figures/temporal_*` | `eda.eda_temporal` | [Patrones temporales](eda_temporal_report.md) | Vigente |
| [`eda/tokens_metrics.json`](eda/tokens_metrics.json) y `eda/figures/tokens_ccdf.png` | `eda.eda_tokens` | [EDA](eda_report.md), sección 5.1 | Vigente |
| [`eda/aspects_v2_metrics.json`](eda/aspects_v2_metrics.json) | `eda.eda_aspects_v2 analyze` | [EDA](eda_report.md), sección 5.2.1 | Histórico |
| [`eda/aspects_v2_1_metrics.json`](eda/aspects_v2_1_metrics.json) | `eda.eda_aspects_v2 analyze` | [EDA](eda_report.md), sección 5.2.1 | Vigente |
| [`eda/aspects_v1_metrics.json`](eda/aspects_v1_metrics.json) | `eda.eda_aspects analyze --prompt aspects_v1` | [EDA](eda_report.md), sección 5.2 | Histórico |
| [`eda/aspects_v0_metrics.json`](eda/aspects_v0_metrics.json) | `eda.eda_aspects analyze --prompt aspects_v0` | [EDA](eda_report.md), sección 5.2 | Histórico |
| [`eda/lexicon_metrics.json`](eda/lexicon_metrics.json) | `eda.eda_lexicon` | [EDA](eda_report.md), sección 5.3 | Vigente |
| [`gold_v0_metrics.json`](gold_v0_metrics.json) | `analysis.analyze_gold_v0` | [Oro, primera ronda](gold_v0_report.md) | Histórico |
| [`prompt_validation_prompt_v2.json`](prompt_validation_prompt_v2.json) | `analysis.validate_prompt` | [Oro, primera ronda](gold_v0_report.md), sección 3 | Histórico |
| [`gold_v0_r2_metrics.json`](gold_v0_r2_metrics.json) | `analysis.analyze_gold_v0_r2` | [Re-anotación](gold_v0_r2_report.md) | Vigente en parte |
| [`silver_v0_metrics.json`](silver_v0_metrics.json) | `analysis.analyze_silver` | [Plata](silver_v0_report.md) | Vigente |
| [`gold_v1_metrics.json`](gold_v1_metrics.json) | `analysis.analyze_gold_v1` | [`gold_v1`](gold_v1_report.md) | Vigente |
| [`gold_v1_a2_metrics.json`](gold_v1_a2_metrics.json) | `analysis.analyze_gold_v1_a2` | [`gold_v1`](gold_v1_report.md), sección 7 | Vigente |
| [`sentiment_models_metrics.json`](sentiment_models_metrics.json) | `sentiment.evaluate` (primera ronda) | [Primera ronda](sentiment_models_v0_report.md) | Histórico |
| [`sentiment_models_gold_v1_metrics.json`](sentiment_models_gold_v1_metrics.json) | `sentiment.evaluate` | [`gold_v1`](gold_v1_report.md), sección 6 | Vigente |
| [`topics_working_v0_metrics.json`](topics_working_v0_metrics.json) | `topics.working_set` | [Tópicos](topics_report.md) | Provisional |
| [`topics_pilot_v0_metrics.json`](topics_pilot_v0_metrics.json) | `topics.pilot` | [Tópicos](topics_report.md) | Provisional |
| [`topics_aspects_scale_v0_metrics.json`](topics_aspects_scale_v0_metrics.json) | `topics.aspects_scale` | [Tópicos](topics_report.md), sección 4.5 | Vigente |
