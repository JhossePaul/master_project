# Reglas deterministas de elegibilidad para el backfill

> **Estado (2026-10-22): aprobada como `eligibility_rules_v1`** (P8-3 y P8-4 del [registro de decisiones](../../backlog/epic_5.md#decisiones-pendientes)). Índice: [`README.md`](../README.md).
> * **Cambios frente a `v0.1`:** `TNSS_SINGLE_WORD` resuelta con el léxico determinista (P8-3), `TOPIC_TOO_SHORT` con k = 1 (5.5) y conteos por banco × periodo × motivo ([`eligibility_v1_counts.json`](eligibility_v1_counts.json)).
> * **Código:** `labeling.eligibility.with_tnss_rule_v1` (reglas) y `eda.eligibility_counts` (conteos). `with_tnss_rule` sigue siendo `v0.1`, porque con ella se construyeron las muestras de EPIC-5 y sus consumidores deben reproducirlas.
> * **Evidencia de las decisiones:**
>   * `TNSS_SINGLE_WORD`: las reseñas de una palabra son fáciles para los modelos (~96 % de exactitud; [competencia de modelos](../sentiment/sentiment_models_v0_report.md), sección 3), así que excluirlas no evita error de clasificación, y excluirlas todas sesga los agregados entre −0.10 y −0.21 estrellas por banco. El léxico ([EDA](eda_report.md#53-léxico-determinista-para-reseñas-de-una-palabra), sección 5.3) cubre el 95.3 % con 99 % de exactitud en el oro *dev*, y excluir solo lo no cubierto deja un sesgo de −0.001 a −0.007 estrellas.
>   * `TOPIC_TOO_SHORT` con k = 1: las negativas cortas casi nunca son multi-aspecto (0–4 %), pero sí nombran problemas concretos: el 4 % [1, 18] de las de una palabra, el 46 % [33, 60] de las de 2 y el 77 % [70, 83] de las de 3 a 5 ([`topics_report.md`](../topics/topics_report.md#43-topic_too_short-k--1-se-confirma-con-v21-y-los-5-bancos), sección 4.3).

* **Versión:** `eligibility_rules_v1` (aprobada en 5.8, 2026-10-22).
* **Fuente:** [`epic_5.md`](../../backlog/epic_5.md), feature 5.1. Los parámetros salen del [EDA](eda_report.md) y los conteos se calcularon sobre el snapshot `tds_20261016T054714Z` (2 649 047 filas).
* **Gobierno:** el proyecto es un trabajo académico independiente de los bancos; no hay un dueño de negocio que valide los parámetros. Cada parámetro es una **decisión metodológica del autor**, documentada con su criterio y con un análisis de sensibilidad cuando la alternativa razonable cambia los conteos.
* **Contrato:**
  * Se evalúan antes de la inferencia, por fila, sin modelos ni aleatoriedad.
  * Gana la primera regla que coincide, en el orden de cada tabla.
  * Una fila excluida queda `NO_PREDICTED` con el código de la regla en `eligibility_code` (esquema v3). Se conserva y se reporta por banco × periodo × motivo.
  * Una fila elegible queda `ELEGIBLE`, con `label_source = MODEL` (M4) o `RULE_BASED` (léxico).
  * La inferencia corre una vez por texto único elegible y el resultado se propaga a sus filas.
* **Definiciones:** `palabras` = tokens separados por espacios de `texto_limpio`. *Contenido* = letras o dígitos que quedan tras quitar emojis y tokens de sanitización (sin distinguir mayúsculas).

## Tarea TNSS

| Orden | Código | Criterio | Parámetro | Filas | % | Estado |
| :---: | :--- | :--- | :--- | ---: | ---: | :--- |
| 1 | `TNSS_EMPTY` | `palabras = 0` | — | 8 | 0.00 % | Aprobada |
| 2 | `TNSS_NO_TEXT_CONTENT` | Sin contenido alfanumérico tras quitar emojis y tokens | — | 19 586 | 0.74 % | Aprobada |
| 3 | `TNSS_TIME_OUTLIER` | `fecha < app_valid_from[bank_id]` | NUBANK: `2020-01-01`; otros bancos: sin corte | 174 | 0.01 % | Aprobada (ver criterio abajo) |
| 4 | `TNSS_SINGLE_WORD` | `palabras = 1` y la forma normalizada no tiene etiqueta de sentimiento en el léxico `lexicon_v1` (no está, o su etiqueta es `NA`) | Léxico de 151 formas (22 `NEG`, 7 `NEU`, 117 `POS`, 5 `NA`): soporte ≥ 3 filas de plata y pureza ≥ 0.9 | 22 164 | 0.84 % | Aprobada (P8-3) |
| — | Elegible por léxico (`RULE_BASED`) | `palabras = 1` y forma con etiqueta en el léxico | La etiqueta del léxico | 443 469 | 16.74 % | Aprobada (P8-3) |
| — | Elegible por modelo (`MODEL`) | El resto | M4 (`M4_robertuito_s1_ppi`) | 2 163 646 | 81.68 % | — |
| — | `TNSS_NOT_SPANISH` | — | — | — | — | **Descartada:** el detector confunde el español informal con EN/PT (EDA, H8) |

* **Léxico congelado:** `data/eda/lexicon_v1.parquet` (fuera de git; SHA-256 en el JSON de conteos). Las formas salen de reseñas, así que no se publican; EPIC-6 lo empaqueta con el servicio de inferencia (6.3).
* `TNSS_TIME_OUTLIER` cuenta 174 filas y no 175 como en `v0.1`, porque una de las 175 reseñas de NUBANK anteriores a 2020 no tiene contenido alfanumérico y cae antes en `TNSS_NO_TEXT_CONTENT` (gana la primera regla que coincide).

**Por banco** (filas del snapshot):

| Banco | Filas | Modelo | Léxico | `TNSS_SINGLE_WORD` | `TNSS_NO_TEXT_CONTENT` | `TNSS_TIME_OUTLIER` | `TNSS_EMPTY` | Excluidas |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| AZTECA | 590 981 | 461 226 | 118 637 | 5 613 | 5 503 | 0 | 2 | 1.9 % |
| BANORTE | 518 393 | 427 526 | 83 330 | 3 914 | 3 622 | 0 | 1 | 1.5 % |
| BBVA | 787 875 | 655 689 | 120 158 | 6 922 | 5 101 | 0 | 5 | 1.5 % |
| NUBANK | 128 204 | 109 239 | 17 047 | 953 | 791 | 174 | 0 | 1.5 % |
| SANTANDER | 623 594 | 509 966 | 104 297 | 4 762 | 4 569 | 0 | 0 | 1.5 % |

El desglose por banco × periodo × motivo está en [`eligibility_v1_counts.json`](eligibility_v1_counts.json).

**Criterio de `TNSS_TIME_OUTLIER` para NUBANK.** Antes de 2020 llegan entre 1 y 15 reseñas por mes (175 en total entre 2015-08 y 2019-12). A partir de 2020 el volumen crece de forma sostenida, coherente con la operación de la app en México. Se elige el corte mínimo que aísla ese tramo anómalo. Sensibilidad: con corte en 2020-09-01 (primer mes con al menos 100 reseñas) se excluirían 542 filas, el 0.4 % de NUBANK y el 0.02 % del corpus. El resultado se reporta con ambos cortes en 5.8 si cambia alguna conclusión. Los demás bancos no tienen corte: sus primeros años son reseñas legítimas de baja adopción.

## Tarea de tópicos y familias

Se evalúa sobre las filas con TNSS. `TOPIC_NOT_NEGATIVE` usa el sentimiento **predicho** (léxico o M4 `s1` del backfill de 5.8), nunca las estrellas.

| Orden | Código | Criterio | Parámetro | Filas | % | Estado |
| :---: | :--- | :--- | :--- | ---: | ---: | :--- |
| 1 | `TOPIC_TNSS_NOT_PREDICTED` | La fila no tiene TNSS | — | 41 932 | 1.58 % | Aprobada |
| 2 | `TOPIC_NOT_NEGATIVE` | El TNSS predicho no es `NEG` | Clase predicha (argmax; la T no la cambia) | 1 893 282 | 71.47 % | Aprobada |
| 3 | `TOPIC_TOO_SHORT` | `palabras <= k` | **k = 1** (decisión del autor, 2026-10-22): solo las negativas de una palabra. Antes de la regla 2, `k = 2` excluiría el 36 % de las filas y `k = 3` el 45 %. Criterio: excluir más no mejora los tópicos y pierde quejas concretas | 10 381 | 0.39 % | Aprobada |
| — | Elegible para tópicos y familias | Negativas de 2 palabras o más | — | 703 353 | 26.55 % | — |

* 99 filas (0.004 %) no tienen predicción en el backfill: su `texto_sanitizado` cambió entre el snapshot y la exportación del backfill (re-sanitización). En producción se predicen en el delta.
* **Por banco, elegibles para tópicos:** AZTECA 93 004, BANORTE 120 675, BBVA 292 190, NUBANK 30 849 y SANTANDER 166 635.

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
| `v1` | 2026-10-22 | Aprobada en 5.8: `TNSS_SINGLE_WORD` con el léxico `lexicon_v1` (P8-3), `TOPIC_TOO_SHORT` con k = 1, conteos por banco × periodo × motivo con el sentimiento de M4 `s1` |
