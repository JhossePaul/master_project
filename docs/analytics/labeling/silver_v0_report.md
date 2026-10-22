# Conjunto de plata, primera versión (EPIC-5, feature 5.3)

> **Estado (2026-10-19): vigente.** `silver_v0` es la plata con la que se entrenan los modelos de 5.4. Índice: [`README.md`](../README.md).
> * **Cambio posterior:** 5.4 excluye del entrenamiento las reseñas de todas las colas del oro, incluida `gold_v1` ([competencia de modelos](../sentiment/sentiment_models_v0_report.md), al inicio). Las cifras de este reporte no cambian.

* **Corrida:** `20261019T011518Z`.
  * Modelo `gemini-3.6-flash` con `prompt_v3` (`annotation_guideline_v2`), en lotes de 100 y 8 peticiones en paralelo.
  * 70 284 textos únicos de 99 926 filas, sin lotes fallidos ni reintentos.
* **Costo:** **$3.37** ($0.048 por 1 000 textos), más $0.016 de la prueba de 300 textos.
* **Diseño:** ver [`sample_silver.py`](../../../experiments/analytics/src/voc_analytics/sampling/sample_silver.py).
  * 20 000 filas por banco, asignadas por raíz cuadrada dentro de banco × periodo × estrellas.
  * Holdout desde 2026-04-01 con reglas antifuga, que no tienen violaciones.
  * Contexto temporal por fila.
* **Métricas:** [`silver_v0_metrics.json`](silver_v0_metrics.json), calculadas con [`analyze_silver.py`](../../../experiments/analytics/src/voc_analytics/analysis/analyze_silver.py). Solo agregados; las etiquetas están en `experiments/analytics/data/labels/silver_v0/`, fuera de git.
* **Cómo leer las cifras:**
  * Las estimaciones poblacionales se ponderan por 1 / probabilidad de inclusión.
  * **Heredan el error de Gemini** (κ 0.84–0.93 contra el oro). Las cifras sin ese sesgo son las del oro, o las de PPI en 5.6.

| Partición | Filas |
| :--- | ---: |
| Entrenamiento | 90 883 |
| Holdout nuevo (evaluación de deriva) | 5 336 |
| Holdout visto (excluido) | 3 707 |

## 1. La plata coincide con el oro

| Estimación poblacional (filas elegibles) | Plata (n = 99 926) | Oro vigente (n = 400) |
| :--- | ---: | ---: |
| Estrellas (1–2 NEG, 3 NEU, 4–5 POS) distintas del texto | **10.9 %** | 9.9 % (EE 1.7) |
| Incongruencia en los extremos | **5.0 %** | 4.7 % (EE 1.3) |
| `NEG` / `NEU` / `POS` / `NO_EVALUABLE` | 26.9 / 1.8 / 70.9 / 0.4 % | 26.0 / 2.5 / 71.5 / 0.03 % |
| Menciona falla | 23.6 % | — |

Las dos fuentes son independientes en su muestreo y coinciden dentro del error del oro. Esto respalda usar la plata para entrenar (5.4) y como insumo de PPI.

### Sentimiento del texto por estrellas (ponderado)

| Estrellas | Filas | `NEG` | `NEU` | `POS` | Menciona falla |
| :---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 20 374 | 97.7 % | 0.9 % | 1.2 % | 82.3 % |
| 2 | 9 348 | 93.4 % | 2.3 % | 3.7 % | 83.3 % |
| 3 | 11 002 | **73.3 %** | 5.8 % | 20.2 % | 64.7 % |
| 4 | 15 936 | **28.5 %** | 3.7 % | 67.3 % | 26.5 % |
| 5 | 43 266 | 2.8 % | 1.5 % | 95.3 % | 3.0 % |

* **Lo que confirma:** el 3★ es mayoritariamente negativo, y más de una de cada cuatro reseñas de 4★ describe un problema. Lo mismo había encontrado el oro, ahora con 27 000 filas.
* **El ruido de las estrellas es asimétrico:** las calificaciones intermedias esconden quejas. Las de 1★ y 5★ casi siempre dicen lo que marcan.

### Incongruencia en los extremos por banco y periodo

* **Por banco:**
  * AZTECA 3.6 %
  * NUBANK 4.8 %
  * SANTANDER 4.7 %
  * BBVA 5.5 %
  * BANORTE 6.5 %
  * Con 20 000 filas por banco las diferencias ya son estables, pero conservan el sesgo de Gemini.
* **Por periodo:** estable entre 4.7 % y 5.3 % desde 2019. Hay dos excepciones:
  * 2018 tiene 6.7 % y `≤2017` 5.8 %;
  * en BANORTE se llega a 8.1 % en 2018 y en el holdout.

## 2. Contexto temporal: ¿las estrellas esconden quejas en quincena o en incidencias?

Pregunta del autor, que surgió en el análisis temporal ([reporte](../eda/eda_temporal_report.md)): ¿hay más reseñas de 5★ con texto negativo en quincena, o semanalmente en NUBANK?

**Método:**
* Se compara la proporción de `NEG` del texto **dentro de cada banco × nivel de estrellas**: con la marca contra sin ella. Así la mezcla de estrellas no confunde el resultado.
* Prueba z de dos proporciones, con 25 pruebas por marca. A p < 0.05 se esperan ~1.25 falsos positivos por marca.

| Contexto | Pruebas con p < 0.05 | Dirección | 5★: `NEG` con marca contra sin marca |
| :--- | ---: | :--- | :--- |
| Quincena | 5 de 25 | Todas suben, entre 1 y 5 puntos (1★, 3★ y 4★) | Sin diferencia en ningún banco; NUBANK 2.9 % contra 3.7 % (p = 0.09) |
| Día pico de volumen total | 7 de 25 | 5 suben, 2 bajan | **SANTANDER 4.6 % contra 2.1 % (p < 0.001)**; **AZTECA 12.5 % contra 1.8 %** (n = 32); **NUBANK 1.9 % contra 4.3 %** (n = 2 954, p < 0.001) |
| Día pico del mismo nivel de estrellas | 7 de 25 | 5 suben, 2 bajan | Igual patrón: SANTANDER y AZTECA suben, NUBANK baja |
| Días 0–3 tras un release | 3 de 25 | Mixta | Sin diferencia |
| Jueves (NUBANK) | 1 de 5 | Baja | **2.5 % contra 3.7 % (p = 0.015)** |

### Lectura

1. **En quincena las 5★ no esconden más quejas.** El aumento de volumen de quincena (análisis temporal) trae texto con el mismo sentimiento que el resto del mes. Hay subidas pequeñas de `NEG` en algunas celdas de 1★, 3★ y 4★ (1–5 puntos), pocas y apenas por encima de lo esperado por azar.
2. **En los días pico de SANTANDER y AZTECA, las 5★ sí esconden quejas.** Su `NEG` se duplica o más, y el 3★ también se vuelve más negativo (AZTECA 91 % contra 58 %, BBVA 95 % contra 81 %, SANTANDER 81 % contra 72 %).
   * Es el patrón de una **incidencia**: gente que se queja sin bajar la calificación.
   * Es justo el caso que el proyecto busca: las estrellas lo ocultan y el texto lo revela.
3. **En NUBANK pasa lo contrario.** Sus días pico y sus jueves (el día de su release semanal) traen 5★ *más* positivas que el resto. Es compatible con peticiones de calificación tras actualizar o con campañas: volumen positivo genuino, no incidencias.
4. **Después de un release** el sentimiento no cambia de forma consistente en ninguna estrella.

**Limitaciones:**
* las etiquetas son de Gemini, no humanas;
* 25 pruebas por marca sin corrección por comparaciones múltiples: los efectos con n chico (AZTECA 5★, n = 32) son indicios;
* los días pico usan una mediana centrada, que incluye días futuros.

## 3. Implicaciones

* **Plata lista para 5.4:** 90 883 filas de entrenamiento y 5 336 de holdout nuevo, con etiquetas a nivel de texto que se propagan a las filas.
* **Tópicos (5.5):** los días pico de SANTANDER y AZTECA son buenos candidatos para validar que los tópicos de quejas detectan incidencias reales, incluidas las de 5★.
* **Oro dirigido (segunda ronda):** conviene incluir 3★ y 4★ en días pico, y 5★ con `NEG` de Gemini, donde la plata y las estrellas más discrepan. Se anota a ciegas.
* **PPI (5.6):** la plata de 100 000 filas y el oro de 400 permiten estimar la incongruencia por banco con intervalos válidos, corrigiendo el sesgo de Gemini.
