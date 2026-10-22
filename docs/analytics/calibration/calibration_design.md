# Plan de 5.6: calibración, umbral HITL, PPI y priorización

> **Estado (2026-10-22): aprobado en términos generales por el autor**, que pide ser consultado antes de cada decisión o descarte. **Avance:** *temperature scaling* con una T por semilla **adoptado** para M4 y *vector scaling* **descartado** (decisión del autor, 2026-10-22; `calibration_v0_metrics.json`). Curva de cobertura y riesgo medida (`selective_v0_metrics.json`) y umbral HITL de sentimiento decidido (sección 3.1). PPI con Gemini (opción A) medido (`ppi_v0_gemini_metrics.json`); opción B1 hecha (sección 4.1; `ppi_v0_m4_metrics.json`) con el lote `m4_ppi`, que guardó los pesos. Priorización decidida por el autor (volumen de negativas por familia y marca `u`, sin fórmula anterior ni votos). **5.6 cerrada (2026-10-22).** Resultados en [`calibration_report.md`](calibration_report.md). Feature 5.6 de [`epic_5.md`](../../backlog/epic_5.md). Todo se hace con lo que ya existe: predicciones guardadas, oro *dev* y plata. No hay etiquetado humano nuevo ni GPU, salvo que se elija la opción B de la sección 4. El oro *test* (601 ítems) **no se usa**: queda para 5.8. Índice: [`README.md`](../README.md).

## 1. Insumos que ya existen

| Insumo | Dónde | Qué tiene |
| :--- | :--- | :--- |
| Predicciones de M4 RoBERTuito y BETO, 3 semillas cada uno | `data/models/preds/M4_*__dev.parquet` y `__holdout.parquet` | `p_NEG`, `p_NEU`, `p_POS` sobre los 1 091 ítems *dev* (799 aleatorios y 292 dirigidos) y los 5 304 textos de `holdout_nuevo` |
| Predicciones de M1, M5 y M8 | La misma carpeta | Las mismas columnas, como comparación |
| M9 Gemini (`prompt_v3`) | `data/labels/silver_v0/labels_prompt_v3.parquet` y las etiquetas de Gemini del oro | Etiqueta y marca `duda`, **sin probabilidades** |
| Oro *dev* | `sentiment.data.gold()` | Etiqueta humana, estrato, `prob_inclusion` y peso de diseño |
| Plata `silver_v0` | `data/labels/silver_v0/` | 99 926 filas (70 284 textos) estratificadas por banco × periodo, con `prob_inclusion`; los votos de utilidad se unen desde el snapshot |
| Familias `aspects_v2_1` y marca `u` | `data/topics/aspects_scale_v0/` | 40 382 negativas de la plata (5.5) |
| ECE con 10 bins | `sentiment.metrics.ece` | Ya se usa en 5.4 (M4: 0.035) |

## 2. Calibración

* **Método:** *temperature scaling* (Guo et al., 2017), con un parámetro por modelo y semilla. Como comparación se prueba *vector scaling* (un sesgo por clase), que podría corregir el exceso de `NEU`.
* **Sin optimismo:** el *dev* aleatorio también se usó para elegir modelos, así que la temperatura se ajusta con validación cruzada de 5 particiones estratificadas dentro de los 794 evaluables. Se reporta el ECE fuera de partición. La temperatura final se ajusta con todo el *dev*.
* **Métricas:**
  * ECE ponderado por el peso de diseño y ECE por clase;
  * *log loss* y Brier;
  * diagrama de fiabilidad;
  * los mismos cálculos en el *dev* dirigido (292) y en `holdout_nuevo` contra la plata, como prueba de deriva.
* **Semillas:** se calibra cada semilla y se reporta el rango. La alternativa es promediar las probabilidades de las 3 semillas en un ensamble, pero triplica el costo de inferencia (decisión D3).
* **Terminado cuando:** ECE fuera de partición con IC por *bootstrap*, para M4 sin calibrar y calibrado, y una temperatura fija lista para producción.

## 3. Umbral HITL por cobertura y riesgo

* **Señal de incertidumbre:** se comparan la probabilidad máxima calibrada, la entropía normalizada y el margen entre las dos primeras clases. Se elige la que dé mejor AURC (área bajo la curva de riesgo y cobertura).
* **Curva:** para cada umbral, la cobertura es la proporción que se acepta sin revisión y el riesgo es el error ponderado entre lo aceptado. Se calcula en el *dev* aleatorio con IC por *bootstrap*, y también por longitud y por banco.
* **Disparador por impacto:** se mide cuántas reseñas agrega la regla de 4–5★ con `NEG` y votos ≥ 5, que viene de la especificación anterior, y si esas reseñas tienen más error que el resto.
* **Elección del umbral:** según tu restricción (decisión D1), ya sea por la capacidad de revisión humana por semana sobre el delta diario o por un error máximo entre lo aceptado. La curva muestra el precio de cada opción.
* **M9:** no da probabilidades. Su única señal es la marca `duda`, de la que se mide cuánto riesgo atrapa con qué cobertura. Si 5.8 elige M9, eso marca el límite de su HITL.
* **Terminado cuando:** está la curva, hay un umbral elegido con su cobertura y riesgo esperados, y está el volumen semanal estimado para la cola HITL de EPIC-7.

### 3.1 Decisión del autor (2026-10-22)

* **Cobertura por defecto: 90 %.** Se revisa el ~10 % menos seguro: unos 350 textos únicos por semana sobre el volumen reciente (3 493 por semana), con un error de 0.4 % entre lo aceptado, igual en las tres semillas de RoBERTuito. El 95 % (unos 175 por semana) queda como alternativa de menor costo.
* **Es un parámetro configurable, no un compromiso de horas del autor.** La revisión semanal es un costo de operación del escenario de producción, y la hace el equipo de CX o de producto en EPIC-7. Para la tesis basta medir y justificar el umbral, más una validación única con la cola de una semana antes de la presentación.
* **La curva y el parámetro son parte del estado de la aplicación:** se guardan versionados y el frontal HITL los muestra junto con su costo estimado (EPIC-6, 6.1 a 6.4; EPIC-7, 7.7).
* **Señal:** probabilidad máxima calibrada (la entropía y el margen dan el mismo AURC), con una semilla de RoBERTuito.
* **Descartes, propuestos con la recomendación y aceptados con ella:**
  * el ensamble de 3 semillas, que no mejora el AURC;
  * BETO para el HITL, cuyo AURC es el doble;
  * el disparador por impacto (4–5★, `NEG` y votos ≥ 5) como señal de error: solo lo cumplen 2–4 reseñas del *dev* y su error es 0; se reconsidera como criterio de prioridad en la sección 5;
  * la marca `duda` de Gemini, que marcó 0 de 199 reseñas *dev*; si 5.8 elige M9, su HITL necesita otra señal (por ejemplo, desacuerdo entre dos corridas).
* **Límite para 5.8 y la FMEA:** en el *dev* dirigido el error sigue entre 17 % y 23 % aun revisando el 20 %; la confianza ayuda poco en `NEU` y en elogios con quejas.

## 4. Estimaciones poblacionales con PPI

* **Objetivo:** estimar con intervalos válidos la incongruencia entre estrellas y texto (12.5 % en el oro) y la proporción de `NEG` por banco y periodo, con más precisión que el oro solo.
* **Método:** *prediction-powered inference* (Angelopoulos et al., 2023), con estratos y pesos de diseño:
  * la plata da la media de las predicciones sobre muchos textos;
  * el oro aleatorio *dev* (799) corrige el sesgo del predictor;
  * se compara con el estimador solo-oro, que es la base actual;
  * cuando un estrato tiene pocos ítems de oro, se agrupa por banco o por periodo y se reporta qué se agrupó.
* **Predictor** (decisión D2):
  * **A. Gemini sobre la plata (recomendado):** no cuesta nada porque ya existe, y es el mejor predictor (κ 0.93);
  * **B. M4 sobre la plata:** requiere inferir unos 70 000 textos en Kaggle (minutos en la T4) y mide el predictor que tal vez se despliegue.
* **Terminado cuando:** hay una tabla por banco × periodo con el estimador PPI y el solo-oro, sus IC y la reducción del ancho del intervalo.

### 4.1 Opción B: M4 no puede predecir la plata con la que se entrenó (2026-10-22)

PPI exige que el predictor sea independiente de las dos muestras. M4 se ajustó con los textos de `entrenamiento` de la plata, así que sus predicciones sobre esos textos reproducen a Gemini mejor que sobre textos nuevos, y el estimador quedaría sesgado. Los pesos de M4 no se guardaron, así que cualquier opción reentrena en Kaggle (~6 min por semilla en la T4):

* **B1. Muestra nueva del snapshot (recomendada):** ~70 000 filas estratificadas como la plata, sin reseñas de la plata ni del oro, con π conocido. Se reentrena M4 (3 semillas) y se predice esa muestra. GPU: ~0.5 h. Sirve además para medir el *throughput* de inferencia de 5.7.
* **Decisión del autor (2026-10-22): B1, y guardar los pesos.** La corrida `voc-sentimiento-m4` de 5.4 no los guardó: su salida solo tiene código, logs y predicciones (verificado en Kaggle). Hecho:
  * `sampling.sample_ppi`: 99 789 filas y 69 534 textos únicos, 20 000 por banco con el diseño de la plata, sin ninguna reseña de la plata ni del oro;
  * `finetune --ppi --save-weights` predice esa muestra y guarda el modelo en fp16 (218 MB por semilla, probado en local con recarga);
  * lote `m4_ppi`: M4 RoBERTuito con las semillas 1 a 3 y sufijo `_ppi`, para no pisar las predicciones de 5.4 con las que se calibró. Al volver, se recalcula la T y la curva HITL con estos modelos, que son los que tienen pesos.
* **B2. Validación cruzada sobre la plata:** 5 modelos por semilla, cada uno predice la parte que no vio (*cross-prediction*). GPU: ~1.5–2 h. Compara A y B sobre la misma muestra, pero cuesta unas 5 veces más.

## 5. Priorización (Q4)

* **Candidatas:**
  * la fórmula `priority_weight_score` de la especificación anterior: p(`NEG`), incongruencia y log de los votos;
  * variantes que agregan la marca `u` y la proporción de familias, y transforman los votos (los votos son escasos y de cola larga; EDA, H7).
* **Criterio observable:** ordenar celdas de banco × mes, y de versión cuando se pueda, y ver si los 3 incidentes conocidos de BBVA (2024-07, 2025-10 y 2025-11) quedan arriba. Se mide el rango de cada incidente y la precisión en los primeros k. Se repite con los días pico de SANTANDER y AZTECA donde las 5★ esconden quejas (EDA temporal).
* **Límite:** con 3 incidentes la prueba es ilustrativa, como la señal de 5.5. Se reporta así y no se ajustan pesos finos con esto.
* **Terminado cuando:** hay una fórmula recomendada, o la conclusión de que basta ordenar por volumen de `NEG` con la marca `u`, y la comparación contra las alternativas.

## 6. Entregables y código

* **Código** en `voc_analytics/calibration/` (área nueva, 5.6): `calibrate.py`, `selective.py`, `ppi.py` y `priority.py`. Reutiliza `sentiment.data` y `sentiment.metrics` sin modificarlos.
* **Métricas** en `docs/analytics/calibration/calibration_v0_metrics.json`, solo agregados.
* **Reporte** `calibration_report.md` y una nota para 5.8.
* **Actualizaciones:** `epic_5.md` (5.6), `analytics/README.md`, la fila de 5.6 en el mapa de áreas de `CLAUDE.md` y la FMEA si cambia el riesgo de "priorización errónea en predicciones inciertas".
* **Esfuerzo estimado:** ~1 día de cómputo y escritura en el Mac, más el tiempo de tus decisiones.

## 7. Decisiones del autor (2026-10-22)

| # | Decisión | Respuesta del autor | Consecuencia en el plan |
| :---: | :--- | :--- | :--- |
| D1 | Restricción del umbral HITL | Depende de sobre qué se hace HITL (sentimiento o tópicos), de la deriva y de los tópicos nuevos | Pendiente de cerrar. Propuesta: 5.6 fija la curva y un umbral base para el sentimiento; la curaduría de tópicos sigue siendo la revisión trimestral de 5.5; 5.7 define cuándo la deriva o un tema nuevo suben temporalmente el volumen de revisión |
| D2 | Predictor para PPI | Medir con los dos (Gemini y M4) para 5.8 | Se infiere M4 sobre la plata en Kaggle (opción B) además de la A |
| D3 | Semillas de M4 | El costo en Kaggle se puede asumir (quedan 25.5 h de GPU y 20 h de TPU) | Se mide también el ensamble de 3 semillas. Nota: el costo que triplica el ensamble es el de la inferencia en producción (backfill y delta en Cloud Run), no el de Kaggle, así que esa parte se decide en 5.7 y 5.8 |
