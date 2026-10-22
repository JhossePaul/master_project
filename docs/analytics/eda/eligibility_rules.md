# Reglas deterministas de elegibilidad para el backfill

> **Estado (2026-10-20): vigente como borrador** `eligibility_rules_v0.1`; se aprueba en 5.8. Índice: [`README.md`](../README.md).
> * **Sigue abierto:** `TNSS_SINGLE_WORD` (excluir o léxico `RULE_BASED`, 5.8) y el umbral de `TOPIC_TOO_SHORT` (5.5).
> * **Dato posterior para `TNSS_SINGLE_WORD`:** las reseñas de una palabra son fáciles para los modelos (~96 % de exactitud; [competencia de modelos](../sentiment/sentiment_models_v0_report.md), sección 3), así que excluirlas no evita error de clasificación; su único efecto es el sesgo en los agregados.
> * **Léxico medido (2026-10-20, [EDA](eda_report.md#53-léxico-determinista-para-reseñas-de-una-palabra), sección 5.3):** 151 formas normalizadas, con su etiqueta tomada de la plata, cubren el 95.3 % de las reseñas de una palabra elegibles, con 99 % de exactitud en el oro *dev*. Excluir solo las no cubiertas deja un sesgo de −0.001 a −0.007 estrellas por banco.
> * **`TOPIC_TOO_SHORT`:** **Decisión del autor (2026-10-22): k = 1.** Del análisis de tópicos y familias se excluyen solo las negativas de una palabra; criterio en [`topics_report.md`](../topics/topics_report.md#43-topic_too_short-k--1-se-confirma-con-v21-y-los-5-bancos), sección 4.3.
> * **Dato de 5.2 ([EDA](eda_report.md#52-proporción-multi-aspecto-de-las-negativas), sección 5.2):** solo el 2 % de las negativas de 2 a 5 palabras es multi-aspecto. **Corregido (2026-10-21):** decía también que las de 1 a 5 palabras casi nunca nombran un problema concreto, y no se sostiene. Según 5.5, nombran un problema concreto el 4 % [1, 18] de las negativas de una palabra, el 46 % [33, 60] de las de 2 y el 77 % [70, 83] de las de 3 a 5; lo que casi nunca son es multi-aspecto (0–4 %) ([`topics_report.md`](../topics/topics_report.md#43-topic_too_short-k--1-se-confirma-con-v21-y-los-5-bancos), sección 4.3; confirmadas con `aspects_v2_1` y los 5 bancos).

* **Versión:** `eligibility_rules_v0.1` (borrador; se aprueba en 5.8).
* **Fuente:** [`epic_5.md`](../../backlog/epic_5.md), feature 5.1. Los parámetros salen del [EDA](eda_report.md) sobre `tds_20261016T054714Z`.
* **Gobierno:** el proyecto es un trabajo académico independiente de los bancos; no hay un dueño de negocio que valide los parámetros. Cada parámetro es una **decisión metodológica del autor**, documentada con su criterio y con un análisis de sensibilidad cuando la alternativa razonable cambia los conteos.
* **Contrato:**
  * Se evalúan antes de la inferencia, por fila, sin modelos ni aleatoriedad.
  * Gana la primera regla que coincide, en el orden de cada tabla.
  * Una fila excluida queda `NOT_PREDICTED` con el código de la regla. Se conserva y se reporta por banco × periodo × motivo.
  * La inferencia corre una vez por texto único elegible y el resultado se propaga a sus filas.
* **Definiciones:** `palabras` = tokens separados por espacios de `texto_limpio`. *Contenido* = letras o dígitos que quedan tras quitar emojis y tokens de sanitización (sin distinguir mayúsculas).

## Tarea TNSS

| Orden | Código | Criterio | Parámetro | Filas (snapshot) | Estado |
| :---: | :--- | :--- | :--- | ---: | :--- |
| 1 | `TNSS_EMPTY` | `palabras = 0` | — | 8 | Propuesta |
| 2 | `TNSS_NO_TEXT_CONTENT` | Sin contenido alfanumérico tras quitar emojis y tokens | — | 19 586 | Propuesta |
| 3 | `TNSS_TIME_OUTLIER` | `fecha < app_valid_from[bank_id]` | NUBANK: `2020-01-01`; otros bancos: sin corte | 175 | **Decidida** (ver criterio abajo) |
| 4 | `TNSS_SINGLE_WORD` | `palabras = 1` | — | 484 829 | **Decisión pendiente en 5.8:** excluir o asignar por léxico (`RULE_BASED`). Sesgo medido: −0.10 a −0.21 estrellas por banco; con el léxico (95.3 % de cobertura, 99 % de exactitud) baja a −0.001 a −0.007 |
| — | `TNSS_NOT_SPANISH` | — | — | — | **Descartada:** el detector confunde el español informal con EN/PT (EDA, H8) |

**Criterio de `TNSS_TIME_OUTLIER` para NUBANK.** Antes de 2020 llegan entre 1 y 15 reseñas por mes (175 en total entre 2015-08 y 2019-12). A partir de 2020 el volumen crece de forma sostenida, coherente con la operación de la app en México. Se elige el corte mínimo que aísla ese tramo anómalo. Sensibilidad: con corte en 2020-09-01 (primer mes con al menos 100 reseñas) se excluirían 542 filas, el 0.4 % de NUBANK y el 0.02 % del corpus. El resultado se reporta con ambos cortes en 5.8 si cambia alguna conclusión. Los demás bancos no tienen corte: sus primeros años son reseñas legítimas de baja adopción.

## Tarea de tópicos

| Orden | Código | Criterio | Parámetro | Estado |
| :---: | :--- | :--- | :--- | :--- |
| 1 | `TOPIC_TNSS_NOT_PREDICTED` | La fila no tiene TNSS | — | Propuesta |
| 2 | `TOPIC_NOT_NEGATIVE` | El TNSS **predicho** no es negativo (nunca las estrellas) | Clase o umbral de probabilidad negativa (5.6) | Propuesta |
| 3 | `TOPIC_TOO_SHORT` | `palabras <= k` | **k = 1** (decisión del autor, 2026-10-22): solo se excluyen las negativas de una palabra. Antes de la regla 2, `k = 2` excluye 36 % de las filas y `k = 3` el 45 %. Entre las negativas, las cortas casi nunca son multi-aspecto, pero sí nombran problemas concretos: el 4 % [1, 18] de las de una palabra, el 46 % [33, 60] de las de 2 y el 77 % [70, 83] de las de 3 a 5. Criterio: excluir más no mejora los tópicos y pierde quejas concretas ([`topics_report.md`](../topics/topics_report.md#43-topic_too_short-k--1-se-confirma-con-v21-y-los-5-bancos), sección 4.3; confirmadas con `aspects_v2_1` y los 5 bancos) | Decidida (2026-10-22) |

## Candidatas a evaluar en el resto de 5.2

| Código tentativo | Idea | Evidencia que falta |
| :--- | :--- | :--- |
| `AGG_RATING_CAMPAIGN` | Marcar (no excluir) los meses con picos de reseñas cortas y de 5★ para aislarlos en los agregados | Criterio de pico: razón contra la mediana mensual, longitud y estrellas (EDA, H5) |
| `TOPIC_GENERIC_PHRASE` | Excluir de tópicos las frases genéricas muy repetidas (por ejemplo, "muy bien") | Lista y umbral de frecuencia; probablemente ya cubiertas por las reglas 2 y 3 |

## Historial

| Versión | Fecha | Cambio |
| :--- | :--- | :--- |
| `v0` | 2026-10-16 | Borrador inicial con conteos del snapshot `20261016T054714Z` |
| `v0.1` | 2026-10-17 | Parámetros como decisiones metodológicas del autor (sin dueño de negocio); corte de NUBANK fijado en 2020-01-01 con sensibilidad a 2020-09-01 |
