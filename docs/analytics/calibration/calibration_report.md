# Reporte de 5.6: calibración, umbral HITL, PPI y priorización

> **Estado (2026-10-22): cerrado.** Feature 5.6 de [`epic_5.md`](../../backlog/epic_5.md); plan aprobado en [`calibration_design.md`](calibration_design.md). Calibración, umbral HITL y priorización decididos por el autor; PPI con Gemini y con M4 medidos. §3.5 se agregó en 5.8 (puntaje continuo de 1 a 5, P8-9). Solo agregados; el oro *test* no se usó. Índice: [`README.md`](../README.md).

## 1. Calibración (decidido)

* **Método adoptado:** *temperature scaling* con una T por semilla de M4 (decisión del autor, 2026-10-22). *Vector scaling* se descartó: no mejora a la temperatura y baja un poco la exactitud.
* **Resultado** (oro *dev* aleatorio, n = 794, ponderado por 1 / π, ECE calibrado medido fuera de partición): M4 está sobreconfiado (confianza media 0.995 y acierto 0.972). Con T ≈ 1.7, el ECE baja de 0.023–0.027 a 0.009–0.013 en RoBERTuito y de 0.024–0.026 a 0.005–0.006 en BETO, sin cambiar la exactitud. El IC de la diferencia excluye el 0 en 4 de las 6 corridas.
* **Transferencia:** en `holdout_nuevo` (contra la plata) el ECE también baja, de ~0.02 a ~0.009. En el *dev* dirigido baja de 0.15–0.20 a 0.10–0.14, pero sigue alto: en los casos difíciles la confianza vale menos.
* **Métricas:** [`calibration_v0_metrics.json`](calibration_v0_metrics.json); diagrama de fiabilidad en `figures/reliability_m4_robertuito_s1.png`.
* El ECE de 0.035 que reportó 5.4 no estaba ponderado; el de aquí sí.
* **Modelos con pesos (lote `m4_ppi`, 2026-10-22):** M4 RoBERTuito reentrenado con las semillas 1 a 3, ahora con los pesos guardados (`data/models/weights/`, 218 MB cada uno en fp16, fuera de git). Reproduce a 5.4: κ sin ponderar 0.915, 0.912 y 0.923 contra 0.917, 0.912 y 0.923. Su calibración da lo mismo: T de 1.68 a 1.75 y ECE de 0.023–0.026 a 0.009–0.013. **Estos son los modelos candidatos para 5.7 y 5.8**, porque son los únicos que se pueden desplegar.

## 2. Umbral HITL de sentimiento (decidido)

* **Señal:** probabilidad máxima calibrada de una semilla de RoBERTuito. La entropía y el margen dan el mismo AURC (0.0019–0.0024).
* **Cobertura por defecto: 90 %** (decisión del autor, 2026-10-22), como parámetro configurable. Con RoBERTuito s1: umbral 0.974; el error entre lo aceptado baja de 2.8 % a 0.4 % [0.03, 1.1]; el 86 % de los errores cae en revisión. Sobre el volumen reciente (3 493 textos únicos por semana) son ~350 revisiones por semana, unos 40–60 min.
* **Con los modelos con pesos** (`M4_robertuito_s*_ppi`) da lo mismo: al 90 %, riesgo 0.42 % [0.03, 1.1], umbral 0.973–0.974 y 86–87 % de los errores en revisión, en las tres semillas.
* **Revisar más del 10 % casi no mejora:** queda ~14 % de errores con mucha confianza.
* **Descartes** aceptados con la recomendación: el ensamble de 3 semillas (mismo AURC), BETO para el HITL (el doble de AURC), el disparador por impacto como señal de error (2–4 casos en el *dev*, error 0) y la marca `duda` de Gemini (0 de 199).
* **Límite:** en el *dev* dirigido el error sigue en 17–23 % aun revisando el 20 %.
* **Estado de la aplicación:** la curva y el parámetro se guardan versionados y el frontal los muestra (EPIC-6, 6.1 a 6.4; EPIC-7, 7.10).
* **Métricas:** [`selective_v0_metrics.json`](selective_v0_metrics.json); curva en `figures/risk_coverage_m4.png`.

## 3. Estimaciones poblacionales con PPI

### 3.1 Con Gemini (opción A, hecho)

PPI++ con 99 018 filas de la plata y los 794 ítems evaluables del oro *dev* aleatorio, en 19 celdas de banco × periodo ([`ppi_v0_gemini_metrics.json`](ppi_v0_gemini_metrics.json)).

| Medida (corpus) | PPI | Solo oro | Intervalo más estrecho en |
| :--- | :--- | :--- | ---: |
| Texto `NEG` | 27.4 % [26.6, 28.2] | 27.0 % [23.7, 30.2] | 76 % |
| Estrellas distintas del texto | 11.6 % [10.5, 12.6] | 12.1 % [9.7, 14.5] | 56 % |
| Incongruencia en los extremos | 4.7 % [4.1, 5.4] | 5.2 % [3.6, 6.9] | 63 % |

| Banco | Texto `NEG` | Estrellas distintas del texto | Incongruencia en los extremos |
| :--- | :--- | :--- | :--- |
| AZTECA | 16.4 % [14.7, 18.0] | 7.9 % [7.0, 8.9] | 3.2 % [1.6, 4.8] |
| BANORTE | 23.8 % [22.6, 25.0] | 11.6 % [10.4, 12.7] | 6.0 % [5.4, 6.5] |
| BBVA | 37.8 % [36.1, 39.6] | 13.9 % [10.8, 17.0] | 6.1 % [4.7, 7.4] |
| NUBANK | 22.1 % [19.9, 24.3] | 10.7 % [8.3, 13.2] | 3.6 % [2.3, 4.9] |
| SANTANDER | 28.6 % [26.9, 30.3] | 12.3 % [10.7, 13.8] | 3.8 % [2.6, 5.0] |

* Las cifras centrales coinciden con el oro solo, pero los intervalos son 2 a 4 veces más estrechos, y ya se pueden comparar bancos: AZTECA tiene menos incongruencia que BBVA.
* Donde menos ayuda es en 2023–2024 (reducción del 8 % al 50 %). En las celdas donde el oro no tiene ningún caso, λ = 0 y el estimador vuelve al del oro solo.

### 3.2 Con M4 (opción B1, hecho)

M4 se entrenó con la plata, así que no puede usarla como muestra sin etiqueta. Usa una muestra nueva del snapshot (`sampling.sample_ppi`: 99 789 filas y 69 534 textos, sin plata ni oro, con el diseño de la plata) y el lote `m4_ppi` de Kaggle (decisión del autor, 2026-10-22). Predictor: `M4_robertuito_s1_ppi`; en el oro, sus predicciones del *dev* ([`ppi_v0_m4_metrics.json`](ppi_v0_m4_metrics.json)).

| Medida (corpus) | PPI con Gemini | PPI con M4 | Solo oro | Más estrecho que el oro (Gemini / M4) |
| :--- | :--- | :--- | :--- | :---: |
| Texto `NEG` | 27.4 % [26.6, 28.2] | 26.3 % [25.4, 27.2] | 27.0 % [23.7, 30.2] | 76 % / 72 % |
| Estrellas distintas del texto | 11.6 % [10.5, 12.6] | 11.7 % [10.6, 12.8] | 12.1 % [9.7, 14.5] | 56 % / 53 % |
| Incongruencia en los extremos | 4.7 % [4.1, 5.4] | 4.8 % [4.2, 5.5] | 5.2 % [3.6, 6.9] | 63 % / 64 % |

* **Los dos predictores dan estimaciones compatibles** y reducen el ancho casi lo mismo. Gemini es un poco más preciso en `NEG` (κ 0.93 contra 0.92), como se esperaba.
* **Las diferencias por banco están dentro de los intervalos,** salvo en la incongruencia de los extremos en AZTECA, NUBANK y SANTANDER, donde M4 da ~1 punto más (por ejemplo, AZTECA 3.9 % [3.4, 4.5] contra 3.2 % [1.6, 4.8]). Las dos estimaciones usan muestras sin etiqueta distintas, así que parte de la diferencia es de muestreo.
* **Para 5.8:** PPI no obliga a elegir M9. Con M4 los intervalos poblacionales son casi tan estrechos como con Gemini, sin costo por texto.

### 3.3 *Satisfaction Gap* simétrico (P8-9, 2026-10-22)

A pedido del autor, que objetó medir solo las quejas escondidas, PPI estima también la dirección contraria y la matriz completa (mismas muestras y predictores que 3.1 y 3.2).

| Medida (corpus) | Gemini | M4 | Solo oro |
| :--- | :--- | :--- | :--- |
| Texto más negativo que las estrellas | 10.5 % [9.4, 11.5] | 10.5 % [9.4, 11.7] | 11.0 % [8.7, 13.4] |
| Texto más positivo que las estrellas | 0.9 % [0.7, 1.1] | 0.8 % [0.5, 1.1] | 1.0 % [0.4, 1.7] |
| Brecha neta ordinal (−2 a +2) | −0.142 [−0.158, −0.126] | −0.138 [−0.154, −0.122] | −0.150 [−0.187, −0.112] |

Matriz estrellas × texto (Gemini, proporción del corpus; filas = estrellas, columnas = texto):

| | Texto `NEG` | Texto `NEU` | Texto `POS` |
| :--- | ---: | ---: | ---: |
| 1–2★ | 18.8 % | 0.2 % | 0.04 % |
| 3★ | 3.2 % | 0.3 % | 0.3 % |
| 4–5★ | 4.5 % | 1.3 % | 69.1 % |

* **Medir en las dos direcciones no cambia la conclusión:** la discordancia es casi toda hacia lo negativo (10.5 % contra 0.9 %). Las reseñas de 1–2★ con texto positivo existen, pero son el 0.04 % del corpus.
* **Por banco,** la brecha neta va de −0.08 (AZTECA) a −0.17 (BBVA y BANORTE). NUBANK tiene la mayor proporción de texto más positivo que sus estrellas (2.1 %).
* Propuesta para P8-9: reportar la matriz y la brecha neta con su intervalo, en lugar de una sola dirección.

### 3.5 Puntaje continuo de 1 a 5 (TNSS original) (P8-9, 5.8, 2026-10-22)

A pedido del autor en 5.8, se mide la métrica original del TNSS, que 5.6 no había evaluado (§3.3 solo midió el *gap* por clases). Se usa el mismo PPI++ con M4 calibrado (`ppi_v0`, 99 789 filas, y el oro *dev* aleatorio, 794). Código: `calibration/tnss_score.py`; métricas: [`tnss_score_v0_metrics.json`](tnss_score_v0_metrics.json).

* **Variantes:**
  * `score_clase`: `NEG` = 1, `NEU` = 3, `POS` = 5, con la clase predicha.
  * `score_esperado`: 1·p(`NEG`) + 3·p(`NEU`) + 5·p(`POS`), con la probabilidad calibrada. Es la fórmula de `tnss_numeric_calibrated` de EPIC-6. Su objetivo humano es el mismo que el de `score_clase`; solo cambia el predictor.
  * `score_original`: 1 + 4·p(`POS`), la propuesta inicial.
* ***Gap*:** estrellas menos el puntaje del texto, por reseña y promediado.

| Corpus (PPI, IC 95 %) | Puntaje | *Gap* (estrellas − puntaje) |
| :--- | :---: | :---: |
| Estrellas | 4.09 [4.08, 4.10] | — |
| `score_clase` | 3.88 [3.84, 3.91] | +0.21 [0.17, 0.24] |
| `score_esperado` | 3.88 [3.85, 3.91] | +0.21 [0.18, 0.24] |
| `score_original` | 3.81 [3.77, 3.86] | +0.28 [0.23, 0.32] |
| Brecha neta ordinal (§3.3, −2 a +2) | — | −0.14 [−0.15, −0.12] |

| Banco | Estrellas | `score_esperado` | *Gap* | Brecha neta ordinal |
| :--- | :---: | :---: | :---: | :---: |
| AZTECA | 4.42 | 4.32 | +0.10 [0.05, 0.14] | −0.09 [−0.12, −0.06] |
| NUBANK | 4.32 | 4.08 | +0.22 [0.14, 0.31] | −0.12 [−0.16, −0.08] |
| SANTANDER | 4.05 | 3.83 | +0.22 [0.17, 0.27] | −0.16 [−0.18, −0.13] |
| BANORTE | 4.27 | 4.04 | +0.24 [0.19, 0.29] | −0.16 [−0.19, −0.14] |
| BBVA | 3.72 | 3.47 | +0.27 [0.19, 0.34] | −0.15 [−0.19, −0.11] |

* **Usar probabilidades no cambia el agregado.** `score_esperado` y `score_clase` estiman lo mismo (3.88) y el intervalo apenas se estrecha (0.064 contra 0.071). Con probabilidades calibradas, el promedio del puntaje continuo equivale a 1·P(`NEG`) + 3·P(`NEU`) + 5·P(`POS`) en la población.
* **Por reseña, el puntaje continuo es peor.** En el oro *dev*, el error absoluto medio contra el puntaje humano es 0.107 con `score_esperado` y 0.075 con la clase. Solo el 1.9 % de las reseñas cae en la zona ambigua (de 2 a 4): las probabilidades de M4 son casi siempre extremas.
* **1 + 4·p(`POS`) trata `NEU` como queja** (vale 1, igual que `NEG`), y eso infla el *gap* de +0.21 a +0.28. No hay criterio para preferirlo.
* **α no se puede estimar y solo escala.** Con R = α·S + (1 − α)·T, el *gap* estrellas − R es (1 − α) veces el de T. Ajustar α requeriría una calificación "verdadera" de 1 a 5 que el oro no tiene, porque se anotó en 3 clases.
* **La escala 1/3/5 agrega un artefacto chico** (descomposición con M4 en `ppi_v0`). De un *gap* de +0.19, las reseñas discordantes aportan +0.23 y las concordantes −0.04: las 4★ con texto `POS` (6.6 % del corpus) cuentan −1 cada una, y las 2★ con `NEG` (2.9 %), +1. Las quejas con 4–5★ aportan +0.17 y las 3★ con `NEG`, +0.06. La brecha ordinal no tiene este artefacto, porque compara clases y no puntajes.
* **La hipótesis original no se confirma en los datos.** La tabla de partida suponía +0.8 para BBVA y +0.2 para Nu. El *gap* medido es +0.27 para BBVA y +0.22 para NUBANK, con intervalos traslapados. Solo AZTECA se separa del resto, con el *gap* más bajo. Los dos *gaps* ordenan igual al banco extremo (AZTECA) y difieren entre los demás dentro del ruido.

### 3.4 Insumo medido para 5.7

En la T4 de Kaggle, M4 RoBERTuito infiere **~2 500 textos por segundo** (5 304 textos de `holdout_nuevo` en 2.1 s, igual en las tres semillas). A ese ritmo, los 1 383 138 textos únicos del corpus tomarían ~9 minutos de GPU, sin contar la carga de datos. El ajuste tomó ~6 minutos por semilla. En **CPU** (Mac M2, fp32, 2 000 textos de `ppi_v0` en orden aleatorio, sin ordenar por longitud): **39 textos/s con 1 hilo y 53 con 4**. Con ~500 textos únicos nuevos al día (3 493 por semana), el delta diario toma ~10–15 s de CPU, así que cabe en Cloud Run sin GPU. El backfill completo en CPU tomaría ~7–10 h; en la T4, ~9 min. Es una medición indicativa: falta repetirla en Cloud Run (5.7) y probar el orden por longitud, que reduce el relleno.

## 4. Priorización (Q4) (decidido)

Se compararon 7 puntuaciones por banco × mes sobre la plata (mediana de 126 filas por mes en BBVA), en nivel y en anomalía (z robusto contra los 12 meses previos), por su rango de los 3 incidentes de BBVA entre 58 meses desde 2022-01 ([`priority_v0_metrics.json`](priority_v0_metrics.json)).

| Puntuación | Rango de 2024-07, 2025-10 y 2025-11 (nivel) | Precisión en 3 (nivel) | Rango (anomalía) |
| :--- | :--- | :---: | :--- |
| Volumen de `NEG` | 3, 1, 2 | 1.0 | 1, 2, 5 |
| Proporción de `NEG` | 3, 1, 2 | 1.0 | 2, 1, 4 |
| Fórmula anterior (`NEG`, 4–5★ y votos) | 3, 1, 2 | 1.0 | 1, 2, 4 |
| `NEG` × votos | 17, 1, 2 | 0.67 | 19, 1, 3 |
| Volumen de la marca `u` | 3, 1, 2 | 1.0 | 1, 4, 6 |
| Proporción de `u` | 5, 1, 2 | 0.67 | 1, 6, 8 |
| Fórmula anterior × (1 + `u`) | 3, 1, 2 | 1.0 | 1, 2, 4 |

* **La fórmula anterior no agrega nada sobre contar negativas:** ordena los meses igual que el volumen de `NEG`.
* **Los votos empeoran el orden:** se acumulan con el tiempo y castigan los meses recientes (2024-07 cae al lugar 17).
* **La anomalía avisa mejor del incidente de actualización** (2024-07 primero), y la proporción de `u` es la que lo aísla; el nivel ordena mejor los meses del rediseño.
* **Dentro de cada mes** (criterio B), la causa esperada sale arriba: en 2024-07 la marca `u` es la primera; en 2025-10 y 2025-11, `u` y luego `UX` (y `DV` en 2025-10, en cuarto lugar). La fórmula anterior y el volumen dan el mismo orden.
* **Límite:** 3 incidentes de un solo banco; ilustrativo, como la señal de 5.5.

**Decisión del autor (2026-10-22):** se prioriza con el volumen de negativas por familia y la marca `u`, en nivel y en anomalía (z robusto contra los 12 meses previos). La fórmula anterior y los votos no entran como peso; los votos se muestran como contexto. `priority_weight_score` y `tnss_numeric_calibrated` salen del contrato de EPIC-6 (6.1).

## 5. Lo que queda para otras features

| # | Pendiente | Quién | Nota |
| :---: | :--- | :--- | :--- |
| 1 | D1: cómo la deriva o un tema nuevo suben la revisión HITL | 5.7 | P7-6 del [registro de decisiones](../../backlog/epic_5.md#decisiones-pendientes) |
| 2 | Fila de la FMEA sobre "priorización errónea en predicciones inciertas" con la cifra del *dev* dirigido (17–23 % de error revisando el 20 %) | Autor (gobierno) | No se agregó: es una calificación de riesgo |
| 3 | Validación única de la cola HITL de una semana antes de la presentación | Autor | 20–60 min, una vez |

**Para 5.8:** los candidatos desplegables son `M4_robertuito_s{1,2,3}_ppi` (con pesos), calibrados con su T. PPI funciona con M4 casi tan bien como con Gemini, así que no es un argumento para elegir M9. Las decisiones que dejan abiertas estos resultados (entorno del backfill, licencia, *Satisfaction Gap*, explicabilidad) están en el [registro de decisiones](../../backlog/epic_5.md#decisiones-pendientes).

