# EDA global del TDS (EPIC-5, feature 5.2) — primera pasada

> **Estado (2026-10-19): vigente.** Los hallazgos H1–H10 y los conteos siguen valiendo para el snapshot `tds_20261016T054714Z`. Índice: [`README.md`](README.md).
> * **Resuelto después:** el proxy de incongruencia lo midieron el oro y la plata (estrellas distintas del texto en 10–13 %; ver [`gold_v1`](gold_v1_report.md), sección 2, y la [plata](silver_v0_report.md)); la limpieza por familia la cerró 5.4 (`texto_sanitizado`; [competencia de modelos](sentiment_models_v0_report.md), sección 2).
> * **Sigue pendiente:** longitud en tokens, proporción multi-aspecto, cobertura del léxico determinista y la *Data Card*.

* **Snapshot:** `tds_20261016T054714Z` (2 649 047 reseñas, 5 bancos, 2011-04-01 a 2026-10-14). Ver [`experiments/analytics/README.md`](../../experiments/analytics/README.md).
* **Reproducible:** [`eda_global.py`](../../experiments/analytics/src/voc_analytics/eda/eda_global.py) genera [`eda/metrics.json`](eda/metrics.json) y las figuras. Solo publica agregados y frases genéricas repetidas al menos 500 veces y de hasta 4 palabras.
* **Alcance de esta pasada:** volumen, duplicados, longitud, contenido, idioma, estrellas, votos, deriva temporal y parámetros de las reglas de elegibilidad (5.1).
* **Pendiente para 5.2:**
  * proxy de incongruencia estrellas–texto y estimación de reseñas multi-aspecto (requieren el piloto de etiquetado de 5.3);
  * longitud en tokens del tokenizador candidato;
  * evaluación de la limpieza por familia de modelos.

## 1. Hallazgos principales

| # | Hallazgo | Evidencia | Implicación |
| :---: | :--- | :--- | :--- |
| H1 | **La longitud predice las estrellas** | 1 palabra: 4.75★; 3: 4.60★; 11–20: 3.37★; 21–40: 2.53★; 41–60: 2.08★; > 60: ~1.9★ | Las quejas son largas y los elogios cortos. Toda exclusión por longitud sesga los agregados hacia lo negativo. |
| H2 | **Pocos textos concentran el corpus** | 1 383 138 textos únicos (52.2 %), 1 316 799 tras normalizar puntuación. Los 100 más frecuentes cubren 822 894 filas (31.1 %) y los 1 000 más frecuentes el 38.6 %. Solo "excelente" son 171 013 filas (6.5 %) | Predecir por texto único ahorra ~48 % del backfill. Un léxico sobre las frases más frecuentes cubriría casi un tercio de las filas sin modelo. |
| H3 | **Frases genéricas compartidas entre bancos** | 44 696 textos aparecen en más de un banco y cubren 1 297 135 filas (49 %) | No sirven para distinguir bancos; refuerzan H2. |
| H4 | **El corpus no tiene respuestas del banco (exclusión intencional)** | `texto_respuesta_sanitizado` y `fecha_respuesta` son nulos en el 100 % de las filas; `titulo` también | EPIC-3 excluye las respuestas desde la ingesta: no son el foco del análisis y a menudo citaban el nombre de usuario (PII). El modelo trabaja solo con el texto del usuario. |
| H5 | **Dos tipos de picos de volumen** | Campañas aparentes de calificación (muchas estrellas, textos cortos): SANTANDER 2018-12 (21 069; 4.39★; mediana 6 palabras), AZTECA 2019-05 (16 522; 4.65★; 3 palabras). Incidentes aparentes (pocas estrellas, textos largos): BBVA 2025-10 (18 493; 2.18★; 60.9 % de 1★; 12 palabras), BBVA 2025-11 (14 039; 60.7 % de 1★), BBVA 2024-07 (15 266; 34 % de 1★) | Material para probar hacia atrás la detección de incidentes (5.5). Las campañas inflan las estrellas y deben aislarse en los agregados. |
| H6 | **Deriva temporal fuerte** | Estrellas promedio de 1.9–3.5 antes de 2018 a 4.2–4.5 desde 2019, salvo BBVA (3.2–3.7 en 2020 y 2024–2026). Reseñas de ≤ 3 palabras con 5★: 30–50 % de cada año desde 2019 (AZTECA ~50 % en 2025–2026) | No hay una tasa de ruido única: muestreo, validación y métricas por banco × periodo. |
| H7 | **Los votos de utilidad son escasos y de cola larga** | Con al menos un voto: 2.2–4.6 % en los bancos tradicionales y 12.1 % en NUBANK. p99 de 1–11 votos; máximo de 2 370 a 6 321 | El ponderador por votos solo distingue a una fracción pequeña; conviene transformarlo (log, rango) y validarlo en 5.6. |
| H8 | **La detección de idioma no es fiable aquí** | lingua (ES/EN/PT, modo rápido) marca 48 176 filas como EN/PT. En una muestra revisada internamente, casi todas eran español informal con faltas ("exelente", "mui bien", "nu es god") | No usar un detector automático como regla de exclusión. El español no estándar es la norma y pesa en la elección del encoder. |
| H9 | **Poca PII residual y pocos códigos técnicos** | 15 filas con tokens de sanitización (coincide con `pii_findings_count`), 13 con códigos `ref:`, 119 487 con emojis | Los tokens y los códigos `ref:` no son señales de volumen para tópicos. |
| H10 | **Versión de la app desconocida en el 8.8 %** | 232 814 filas con `version_app = UNKNOWN` (5–31 % según banco y año) | Las alertas por versión no cubren esas filas; reportar cobertura. |

Distribución de estrellas por banco (% de filas):

| Banco | 1★ | 2★ | 3★ | 4★ | 5★ |
| :--- | ---: | ---: | ---: | ---: | ---: |
| AZTECA | 9.5 | 2.0 | 3.4 | 9.7 | 75.5 |
| BANORTE | 11.5 | 2.6 | 4.6 | 12.0 | 69.3 |
| BBVA | 24.2 | 4.6 | 4.9 | 8.1 | 58.3 |
| NUBANK | 14.4 | 3.0 | 3.6 | 5.8 | 73.2 |
| SANTANDER | 15.9 | 3.6 | 5.2 | 12.0 | 63.3 |

![Reseñas por mes y banco](eda/figures/monthly_volume.png)

![Estrellas promedio por año](eda/figures/yearly_stars.png)

![Reseñas de una sola palabra por año](eda/figures/yearly_single_word.png)

Las tablas de cada figura están en `eda/metrics.json` (`yearly`, `stars_by_bank` y los conteos mensuales que produce el script).

## 2. Parámetros para las reglas de elegibilidad (5.1)

Conteos sobre las 2 649 047 filas, sin aplicar todavía la precedencia. La propuesta versionada está en [`eligibility_rules.md`](eligibility_rules.md).

| Regla | Filas | % | Observación |
| :--- | ---: | ---: | :--- |
| `TNSS_EMPTY` | 8 | 0.0003 | Vacíos tras la limpieza |
| `TNSS_NO_TEXT_CONTENT` | 19 586 | 0.74 | Sin letras ni dígitos tras quitar emojis y tokens; casi todo son emojis sueltos ("👍" son 6 266) |
| `TNSS_TIME_OUTLIER` (NUBANK) | 175 | 0.007 | Anteriores a 2020-01-01. Con corte en 2020-09-01 (primer mes con ≥ 100 reseñas) serían 542 |
| `TNSS_SINGLE_WORD` | 484 829 | 18.3 | Promedio de 4.75★ |
| `TNSS_NOT_SPANISH` | — | — | **Se propone descartarla** (H8) |
| `TOPIC_TOO_SHORT` con máximo de 1 / 2 / 3 / 4 / 5 palabras | 484 837 / 955 728 / 1 182 736 / 1 365 543 / 1 501 901 | 18 / 36 / 45 / 52 / 57 | Antes de aplicar `TOPIC_NOT_NEGATIVE`. El umbral se fija con el piloto de tópicos |

**Sesgo de excluir las reseñas de una palabra** (estrellas promedio, como sustituto del TNSS hasta tener un modelo):

| Banco | Todas | Sin una palabra | Solo una palabra | Cambio |
| :--- | ---: | ---: | ---: | ---: |
| AZTECA | 4.397 | 4.293 | 4.766 | −0.10 |
| BANORTE | 4.250 | 4.139 | 4.773 | −0.11 |
| BBVA | 3.716 | 3.504 | 4.773 | −0.21 |
| NUBANK | 4.205 | 4.093 | 4.861 | −0.11 |
| SANTANDER | 4.032 | 3.895 | 4.651 | −0.14 |

Excluirlas baja entre 0.10 y 0.21 estrellas el promedio de cada banco. Además, el efecto varía por banco, así que también cambia la comparación entre ellos. Esto apoya que 5.8 evalúe la alternativa del léxico determinista (H2: unas pocas formas como "excelente", "bueno" o "pésima" cubren gran parte de ese 18.3 %).

## 3. Frases genéricas más frecuentes

Solo frases repetidas al menos 500 veces y de hasta 4 palabras (sin riesgo de identificación). Ejemplos:

| Texto | Filas |
| :--- | ---: |
| excelente | 171 013 |
| muy bien | 28 382 |
| muy buena app | 21 266 |
| bueno | 10 607 |
| 👍 | 6 266 |
| fácil de usar | 3 891 |
| buenas | 2 479 |
| la mejor | 2 235 |
| pésima | 1 324 |
| ecxelente | 1 264 |

Las variantes ortográficas ("ecxelente", "exelente") confirman que la normalización y el encoder deben tolerar español informal.

## 4. Siguientes pasos de 5.2

1. ~~Fecha de corte de NUBANK~~: fijada en 2020-01-01 como decisión metodológica, con sensibilidad a 2020-09-01 (`eligibility_rules_v0.1`).
2. ~~Origen de la falta de respuestas (H4)~~: exclusión intencional en EPIC-3.
3. Medir la longitud en tokens con los tokenizadores candidatos de 5.4.
4. Con el piloto de etiquetado de 5.3:
   * proxy de incongruencia por banco × periodo;
   * proporción multi-aspecto;
   * cobertura del léxico determinista para reseñas cortas.
5. Completar la *Data Card* con composición, procesos y límites (H4, H6, H8 y los del cierre de EPIC-1–4).
