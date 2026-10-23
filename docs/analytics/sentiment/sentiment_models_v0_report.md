# Competencia de sentimiento (EPIC-5, feature 5.4)

> **Estado (2026-10-20).** Índice: [`README.md`](../README.md). El reporte es cronológico: las secciones 1 a 10 son la primera ronda y su *dev* de 199 ítems; desde la sección 11, las corridas en Kaggle contra el *dev* de `gold_v1`.
>
> **Resultado vigente** (κ en el *dev* aleatorio de `gold_v1`, n = 794; media de 3 semillas en los encoders ajustados):
>
> | Modelo | κ | F1 `NEU` | κ dirigido (n = 297) | Estado |
> | :--- | :---: | :---: | :---: | :--- |
> | M0 estrellas | 0.68 | — | 0.14 | Referencia |
> | M1 TF-IDF + LR | 0.87 | 0.42 | 0.46 | Referencia barata y respaldo |
> | M3, M6, M7 (estrellas como etiqueta) | 0.64–0.83 | — | 0.09–0.15 | Descartados (sección 9) |
> | M2 y T0 sin ajuste | 0.02–0.61 | — | — | Descartados (sección 1) |
> | **M4 RoBERTuito** | **0.917** | 0.55 | **0.63** | **Mejor modelo propio** (sección 12) |
> | M4 BETO | 0.917 | 0.56 | 0.58 | Empata en el aleatorio; pierde en el dirigido |
> | M8 Delora | 0.866 | 0.28 | 0.40 | Descartado: peor que M4 y más caro (sección 13) |
> | M5 M4 + *label smoothing* (ε = 0.1) | 0.913 | 0.55 | 0.63 | Descartado: empata con M4 y calibra peor (sección 14) |
> | M9 Gemini (techo) | 0.933 | 0.73 | 0.61 | Techo externo |
>
> * **M4 − M1** está entre +0.043 y +0.053 de κ, significativo en las seis corridas. **M9 − M4** es +0.021 [−0.000, 0.043], y la brecha está casi toda en `NEU`.
> * **Superado:** las cifras de κ sobre el *dev* de 199 (secciones 1, 4, 9 y 10), infladas por el anclaje, y las implicaciones de la sección 8, que ponían a M1 como referencia a vencer.
> * **Sigue vigente:** la decisión de limpieza y ponderación (sección 2), la lectura por longitud (sección 3), las cifras de costo (secciones 6, 10 y 12) y la conclusión de la escalera de ruido.
> * **Escalera completa:** M0–M9 evaluados. Un sesgo de `NEU` sobre M4, elegido con la plata, tampoco mejora en el oro (sección 14). La experimentación de 5.4 se cierra con M4 RoBERTuito; la elección entre M4 y M9 queda para 5.8.
> * **Oro *test* (5.8, 2026-10-22, sección 15):** evaluado una sola vez. M4 κ 0.929 (3 semillas, 0.925–0.932) contra M9 0.943; M9 − M4 entre +0.010 y +0.017, con todos los IC conteniendo el 0, y sin diferencia en `NEG`. **P8-1: M4 RoBERTuito.**
> * **Después (5.6, 2026-10-22):** M4 RoBERTuito se reentrenó con las semillas 1 a 3 guardando los pesos (`M4_robertuito_s*_ppi`); reproduce estas cifras (κ 0.912–0.923 sin ponderar). Ver el [reporte de 5.6](../calibration/calibration_report.md). La elección M4/M9 y la licencia son P8-1 y P8-2 del [registro de decisiones](../../backlog/epic_5.md#decisiones-pendientes).

* **Qué es:** la fase A del [plan de 5.4](sentiment_models_protocol.md): líneas base y encoders sin ajuste, todo en el Mac y sin gasto.
  * M0: estrellas.
  * M1: TF-IDF + regresión logística entrenada con la plata.
  * M2: RoBERTuito y BETO de `pysentimiento`, sin ajuste.
  * T0: `TextBlob`, la referencia del EDA preliminar.
  * M9: Gemini con `prompt_v3`, como techo.
  * **Agregado el 2026-10-19 (sección 9):** la escalera de ruido con TF-IDF, M3, M6 y M7, entrenados con estrellas. **Ninguna selección de modelo se hace con estos resultados** hasta la segunda ronda del oro (`gold_v1`, 5.3).
  * **Reentrenamiento (2026-10-19):** 341 reseñas de la cola de `gold_v1` (y 2 de la del segundo anotador) estaban en la plata de entrenamiento. Desde entonces se excluyen las reseñas de **todas** las colas del oro (63 415 textos de entrenamiento, antes 63 720), y se reentrenaron todos los modelos TF-IDF con validación cruzada desde cero.
    * El oro *dev* (`gold_v0`) no estaba afectado.
    * La validación cruzada eligió ahora `class_weight="balanced"` (macro-F1 0.819 contra 0.817 sin balancear); M1 conserva κ 0.91 en *dev*.
    * Cambian dentro del ruido las ablaciones (sección 2, actualizada) y M7 (sección 9). Las cifras de calibración y velocidad de la sección 6 son de la primera corrida.
* **Métricas:** [`sentiment_models_metrics.json`](sentiment_models_metrics.json) para la primera ronda y [`sentiment_models_gold_v1_metrics.json`](sentiment_models_gold_v1_metrics.json) para el *dev* de `gold_v1` (secciones 12 en adelante); solo agregados.
  * Código en [`voc_analytics.sentiment`](../../../experiments/analytics/src/voc_analytics/sentiment/): `models/baselines.py`, `models/pretrained.py`, `models/noisy.py`, `models/finetune.py` (M4 y M5), `models/delora.py` (M8), `kaggle/` y `evaluate.py`.
  * Las predicciones quedan fuera de git.
* **Datos:**
  * Entrenamiento: 63 720 textos únicos de la plata (`entrenamiento`), sin `NA` ni reseñas del oro.
  * Evaluación: oro *dev* (199 evaluables: 45 `NEG`, 7 `NEU`, 147 `POS`) y 5 305 filas de `holdout_nuevo`.
  * **El oro *test* no se tocó** hasta su evaluación única en 5.8 (sección 15).
* **Cómo leer las cifras:**
  * "Muestra" es la muestra sin ponderar (comparable con los κ de 5.3); "población" pondera por 1/π.
  * IC 95 % por bootstrap estratificado (2 000 réplicas en *dev*, 500 en holdout).
  * Con 7 `NEU` en *dev*, el F1 de `NEU`, y con él el macro-F1, es muy variable. **κ es la métrica más estable.**

## 1. Resultados en el oro *dev*

| Modelo | κ (IC 95 %) | Macro-F1 (IC 95 %) | Exactitud | Recall `NEG` | Precisión `NEG` | κ población |
| :--- | :---: | :---: | ---: | ---: | ---: | ---: |
| M0 estrellas | 0.69 (0.58–0.78) | 0.58 (0.54–0.61) | 88.4 % | 66.7 % | 100 % | 0.70 |
| **M1 TF-IDF + LR** | **0.91 (0.85–0.97)** | **0.82 (0.65–0.92)** | **96.5 %** | **97.8 %** | 95.7 % | **0.93** |
| M2 BETO | 0.58 (0.49–0.67) | 0.64 (0.58–0.70) | 77.9 % | 73.3 % | 94.3 % | 0.59 |
| M2 RoBERTuito | 0.47 (0.38–0.55) | 0.61 (0.56–0.66) | 67.8 % | 86.7 % | 97.5 % | 0.50 |
| T0 `TextBlob` | 0.01 (−0.01–0.03) | 0.07 (0.04–0.12) | 7.0 % | 4.4 % | 100 % | 0.02 |
| M9 Gemini (techo) | 0.94 (0.88–0.99) | 0.89 (0.77–0.97) | 97.5 % | 97.8 % | 97.8 % | 0.95 |

**Diferencias pareadas en κ (muestra):**

| Diferencia | Valor | IC 95 % | Lectura |
| :--- | ---: | :---: | :--- |
| M1 − M0 | +0.22 | [0.13, 0.33] | **M1 supera a las estrellas** |
| M9 − M1 | +0.03 | [−0.01, 0.08] | Gemini no es significativamente mejor que M1 |
| M2 BETO − M0 | −0.11 | [−0.25, 0.02] | Sin ajuste, no supera a las estrellas |

### Lectura

1. **M1 casi alcanza a su maestro.** Un clasificador lineal de 6.8 MB, entrenado con las etiquetas de Gemini, logra κ 0.91 contra el oro humano; Gemini logra 0.94 y la diferencia no es significativa con n = 199. Supera a las estrellas por 0.22 de κ. Sobre todo, recupera las quejas: recall de `NEG` 97.8 % contra 66.7 %.
2. **Los encoders sin ajuste quedan por debajo de las estrellas.** El problema no es la polaridad, sino el esquema:
   * RoBERTuito manda a `NEU` 57 de las 147 reseñas `POS`, casi todas elogios breves. En textos de una palabra acierta el 26 %.
   * En textos de 11–30 palabras, en cambio, RoBERTuito llega a κ 0.82 y BETO a 0.78.
   * Ambos se entrenaron con TASS (tuits), donde una mezcla de elogio y queja es `NEU`, mientras que la guía v2 la marca `NEG`.
   * Esto **motiva M4**: ajustar el encoder con la plata para alinearlo con la guía.
3. **`TextBlob` no sirve para español.** Su léxico es en inglés: asigna polaridad 0 a casi todo el corpus y lo clasifica `NEU` (κ 0.01). El gráfico de incongruencia con `TextBlob` del EDA preliminar medía, en realidad, la ausencia de cobertura del léxico, no el sentimiento. El de RoBERTuito sí tenía señal, pero sobreestimaba `NEU` por el desajuste de esquema descrito arriba.

## 2. Limpieza del texto y ponderación (ablaciones)

| Variante | κ *dev* | Macro-F1 *dev* | κ holdout (población) | Predicciones distintas de la base (*dev* / holdout) |
| :--- | ---: | ---: | ---: | :---: |
| M1 (`texto_sanitizado`, un ejemplo por texto) | 0.91 | 0.82 | 0.89 | — |
| M1 con `texto_limpio` | 0.92 | 0.82 | 0.89 | 1 / 89 |
| M1 ponderado por filas | 0.91 | 0.82 | 0.88 | 0 / 75 |
| M1 ponderado por diseño (Σ 1/π) | 0.89 | 0.79 | 0.88 | 2 / 150 |
| RoBERTuito con `texto_limpio` | 0.47 | 0.61 | 0.75 | 0 / 2 |
| BETO con `texto_limpio` | 0.58 | 0.65 | 0.61 | 4 / 128 |

* **`limpiar_texto_bancario` no aporta de forma distinguible en ninguna familia.** Las variantes difieren en un puñado de predicciones (en M1, 1 de 199 en *dev*).
  * En la primera corrida, M1 con `texto_limpio` quedaba por debajo en macro-F1. Tras el reentrenamiento queda +0.01 de κ por encima (IC 95 % [0.00, 0.04]). El signo cambia con un solo ítem: es ruido.
  * TF-IDF ya pasa a minúsculas.
  * RoBERTuito es *uncased* y `pysentimiento` ya normaliza repeticiones y emojis.
* **Decisión:** **`texto_sanitizado` queda como entrada** de 5.4. Se cierra la evaluación de limpieza por familia que dejó pendiente 5.2, para estas dos familias; se repite si entra un encoder *cased* ajustado.
* **Ponderar tampoco aporta.** Se mantiene un ejemplo por texto único, sin pesos.

## 3. Longitud y texto repetido

Exactitud en el oro *dev* por longitud en palabras (`texto_limpio`):

| Palabras | n | M0 | M1 | M2 BETO | M2 RoBERTuito | M9 |
| :---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 27 | 92.6 % | 96.3 % | 74.1 % | 25.9 % | 96.3 % |
| 2–3 | 61 | 98.4 % | 98.4 % | 88.5 % | 62.3 % | 100 % |
| 4–10 | 53 | 90.6 % | 96.2 % | 66.0 % | 75.5 % | 98.1 % |
| 11–30 | 37 | 73.0 % | 94.6 % | 86.5 % | 89.2 % | 97.3 % |
| 31+ | 21 | 76.2 % | 95.2 % | 66.7 % | 81.0 % | 90.5 % |
| 2–60 (filtro del EDA preliminar) | 172 | 87.8 % | 96.5 % | 78.5 % | 74.4 % | 97.7 % |

* **Las estrellas fallan en los textos largos** (73–76 % de exactitud desde 11 palabras): ahí están las quejas con 3★ y 4★. M1 se mantiene en 95 % en todas las longitudes.
* **Las reseñas de una palabra son fáciles** para M0, M1 y Gemini (~93–96 %). Para `TNSS_SINGLE_WORD` (5.8), esto indica que excluirlas no evita error de clasificación. Su único efecto sería el sesgo en los agregados que ya midió el EDA.
* **El filtro de 2 a 60 palabras no cambia el orden** de los modelos. No se aplica.
* **Memorización:** el 48 % de *dev* (95 textos, casi todos breves) aparece literalmente en el entrenamiento. En los 104 textos no vistos, M1 conserva κ 0.89 y 94.2 % de exactitud, contra 0.93 y 96.2 % de Gemini: **M1 generaliza, no solo memoriza.**

## 4. Detección de incongruencia

En las 23 reseñas de *dev* donde las estrellas difieren del oro:

| M0 | M1 | M2 BETO | M2 RoBERTuito | T0 | M9 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0 % | **82.6 %** | 69.6 % | 69.6 % | 34.8 %* | 91.3 % |

\* `TextBlob` clasifica `NEU` 190 de los 199 textos de *dev*. Sus 8 aciertos aquí son 7 reseñas `NEU` con 4–5★ y una sola queja detectada.

M1 encuentra 4 de cada 5 quejas o elogios que las estrellas esconden. Es el caso de uso central (Q1).

## 5. Deriva temporal: `holdout_nuevo` contra la plata

| Modelo | κ población (IC 95 %) | Exactitud población |
| :--- | :---: | ---: |
| M0 | 0.67 (0.66–0.69) | 82.0 % |
| **M1** | **0.89 (0.88–0.90)** | **94.3 %** |
| M2 RoBERTuito | 0.75 (0.73–0.77) | 85.7 % |
| M2 BETO | 0.61 (0.59–0.63) | 76.5 % |
| T0 `TextBlob` | 0.01 | 5.3 % |

* **Sin deriva visible en M1:** κ 0.89 en textos nuevos desde 2026-04-01, igual que en *dev*. Se mide contra Gemini, no contra humanos.
* **Brecha por banco (M1, κ población):** AZTECA 0.93, SANTANDER 0.91, BANORTE 0.88, NUBANK 0.84, BBVA 0.83. M0 va de 0.52 (BANORTE) a 0.72 (AZTECA): M1 reduce la brecha entre bancos de 0.20 a 0.10.
* `holdout_nuevo` casi no tiene textos de una palabra (10 filas): por diseño excluye los textos ya vistos, y los elogios breves casi siempre se vieron antes.

## 6. Calibración y costo

| Modelo | ECE *dev* | Equipo | Textos por segundo | Ajuste | Tamaño | Parámetros |
| :--- | ---: | :--- | ---: | ---: | ---: | ---: |
| M1 | 0.023 | Mac M2, CPU (1 proceso) | 9 100 | 20 s | 6.8 MB | — |
| M2 RoBERTuito | 0.092 | Mac M2, MPS | 110 | — | — | 109 M |
| M2 BETO | 0.202 | Mac M2, MPS | 111 | — | — | 110 M |
| T0 `TextBlob` | — | Mac M2, CPU | 13 000 | — | — | — |
| M9 Gemini | — | Vertex AI | — | — | — | $0.045 por 1 000 textos |

* **A ritmo de M1, el backfill de ≤ 1.60 M textos únicos tarda ~3 minutos en CPU**, y cabe sin problema en el free tier de Cloud Run. Los encoders sin ajuste tardarían ~4 horas en el Mac.
* **M1 ya está bien calibrado** (ECE 0.02) sin *temperature scaling*.
* El equipo medido tiene **8 GB** de memoria, no 16 GB como decía la tabla de cómputo.

## 7. Límites

* ***Dev* es chico:** 199 ítems y 7 `NEU`. Los IC de macro-F1 se traslapan entre casi todos los modelos buenos; κ discrimina mejor.
* **M1 aprende el criterio de Gemini, incluidos sus sesgos.** Su techo práctico es el acuerdo Gemini–oro. El oro *dev* se anotó a ciegas en la segunda ronda, pero en la primera esos textos fueron asistidos con la propuesta de Gemini: un residuo de anclaje (≤ 2 puntos, [reporte](../labeling/gold_v0_r2_report.md)) favorece a los modelos entrenados con la plata. El oro *test*, siempre a ciegas, no tiene ese sesgo.
* **El C elegido para M1 (16) quedó en el borde de la cuadrícula** (macro-F1 de validación cruzada 0.821 con palabras + caracteres; 0.802 solo con palabras). Ampliar a C ≥ 64 es barato y queda pendiente.
* **Licencia:** los modelos de `pysentimiento` son solo para uso no comercial e investigación, y heredan la licencia de TASS.

## 8. Implicaciones para el resto de 5.4

1. **M1 es la referencia a vencer**, no M0. Cualquier encoder ajustado (M3–M7) debe superar κ 0.91 en *dev* con diferencia pareada que excluya el 0, y justificar su costo: 80 veces más lento en MPS.
2. **M4 (encoder ajustado con la plata) es el siguiente paso con más sentido.** M2 muestra que la polaridad de los encoders es buena en textos largos y que el problema es el esquema de TASS.
3. **M3 (estrellas como etiqueta)** sirve para medir cuánto ruido aprende un modelo. Con M1 ya disponible, se puede hacer barato: TF-IDF entrenado con estrellas antes de ajustar encoders.
4. **`texto_sanitizado`, un ejemplo por texto y sin filtro de longitud** quedan como protocolo para todos los modelos.

## 9. Escalera de ruido con TF-IDF: M3, M6 y M7 (2026-10-19)

**Diseño:** los tres modelos aprenden de las **estrellas**, no de la plata, con la misma representación e hiperparámetros que M1. Así la diferencia con M1 mide el efecto de la etiqueta, no el del modelo.

* Se entrenan sobre pares (texto único, estrellas) ponderados por sus filas, lo que equivale a entrenar por reseña: 65 164 pares y 90 396 filas.
* **M3:** etiqueta ingenua (1–2 `NEG`, 3 `NEU`, 4–5 `POS`).
* **M6:** corrección *forward* (Patrini et al., 2017) con una matriz T de 3 × 5, P(estrellas | sentimiento). T se estima con la plata en las mismas filas de entrenamiento: son **15 números agregados**, y ninguna etiqueta individual de la plata entra al ajuste.
* **M7:** *Confident Learning* (`cleanlab`, poda por tasa de ruido) sobre probabilidades fuera de partición, y reentrenamiento sin los pares marcados.
* La cuadrícula de M1 se amplió a C = 64: la validación cruzada baja (0.816 contra 0.821), así que **C = 16 era el óptimo** y M1 no cambia.

| Modelo | Aprende de | κ *dev* (IC 95 %) | Recall `NEG` | Precisión `NEG` | Acierto donde las estrellas fallan (n = 23) | κ holdout (población) |
| :--- | :--- | :---: | ---: | ---: | ---: | :---: |
| M0 | estrellas, regla fija | 0.69 (0.58–0.78) | 66.7 % | 100 % | 0 % | 0.67 |
| M3 | estrellas | 0.73 (0.64–0.82) | 71.1 % | 88.9 % | 34.8 % | 0.63 |
| M7 | estrellas, con poda de cleanlab | 0.62 (0.53–0.72) | 68.9 % | 93.9 % | 30.4 % | 0.66 |
| **M6** | estrellas + T de 3 × 5 | **0.82 (0.74–0.90)** | **95.6 %** | 82.7 % | **65.2 %** | **0.83** |
| M1 | plata (por texto) | 0.91 (0.85–0.97) | 97.8 % | 95.7 % | 82.6 % | 0.89 |

**Diferencias pareadas en κ (*dev*, muestra):**

| Diferencia | Valor | IC 95 % |
| :--- | ---: | :---: |
| M6 − M3 | +0.09 | [0.01, 0.18] |
| M7 − M3 | −0.11 | [−0.19, −0.02] |
| M1 − M6 | +0.09 | [0.04, 0.16] |
| M3 − M0 | +0.04 | [−0.05, 0.14] |

### Lectura

1. **Aprender de las estrellas apenas supera a las estrellas.** M3 generaliza un poco (κ 0.73 contra 0.69, sin diferencia significativa) y recupera el 35 % de los casos donde las estrellas mienten, pero hereda el ruido: confunde las quejas con 3★ y 4★.
2. **La corrección *forward* recupera la mayor parte de la brecha con una matriz de 15 números.** M6 sube el recall de `NEG` a 95.6 % y supera a M3 con diferencia significativa.
   * Su costo es la clase `NEU`: no la predice nunca, porque la fila `NEU` de T es casi plana (0.10–0.27 en cada nivel de estrellas) y el modelo no puede distinguirla.
   * Implicación: **conocer la estructura del ruido vale casi tanto como tener etiquetas limpias por instancia**. Una muestra pequeña etiquetada para estimar T bastaría para la mayor parte de la ganancia.
3. **cleanlab no aporta y es inestable.** En la primera corrida empató con M3 (κ 0.73). Tras el reentrenamiento, con 0.5 % menos de textos, cae a 0.62, significativamente por debajo de M3.
   * Ahora marca 14 947 pares (18 852 filas). Solo el 48 % de esas filas es ruido real según la plata; el resto (9 809) son ejemplos sin ruido, como 4 889 `NEG` con 1–2★ y 4 660 `POS` con 4–5★.
   * No corrige la etiqueta, solo la descarta. Las quejas con 3★ son tan frecuentes (73 % de las 3★ son `NEG`) que la poda no las ve como anomalías.
4. **M1 sigue arriba con diferencia significativa.** Las etiquetas por instancia de la plata ganan a la mejor corrección del ruido de las estrellas. Lo mismo se ve por banco en el holdout: M6 va de 0.72 (BANORTE) a 0.88 (SANTANDER) y M1 de 0.83 (BBVA) a 0.92 (AZTECA).

**Calibración (ECE *dev*):** M3 0.035, M6 0.036, M7 0.113.

**Costo:** M3 se ajusta en 45 s, M7 en 3.4 min (5 particiones más el reentrenamiento) y M6 en 12 min (L-BFGS en torch, CPU). La inferencia de los tres es la de M1 (~9 000 textos/s).

**Límites:** *dev* es el mismo de la sección 1 (n = 199, 7 `NEU`). La conclusión sobre `NEU` en M6 es estructural, no de potencia: la fila de T es plana con 2 500 filas de plata.

## 10. M4 RoBERTuito ajustado con la plata, validación en el Mac (2026-10-19)

**Qué es:** RoBERTuito (`pysentimiento/robertuito-sentiment-analysis`) con **todos** los pesos ajustados con la plata, un ejemplo por texto.

* Configuración: 2 épocas, AdamW con lr 2e−5, lote efectivo 32 (8 × 4 por la memoria del Mac) y embeddings congelados.
* La mejor época se elige con un 5 % de validación sobre la plata, agrupada por `clave`.
* Es una **validación del pipeline** con una sola semilla. Se entrenó antes de excluir las colas de `gold_v1`, lo que no afecta a *dev*. La corrida comparable, con varias semillas, se hará en Kaggle (sección 11).

| Métrica (*dev*, n = 199) | M4 RoBERTuito | M1 | M9 Gemini |
| :--- | :---: | :---: | :---: |
| κ (IC 95 %) | **0.95 (0.90–0.99)** | 0.91 (0.85–0.97) | 0.94 (0.88–0.99) |
| Macro-F1 | **0.91** | 0.82 | 0.89 |
| F1 de `NEU` (n = 7) | 0.75 | 0.50 | 0.71 |
| Recall / precisión de `NEG` | 97.8 % / 100 % | 97.8 % / 95.7 % | 97.8 % / 97.8 % |
| Acierto donde las estrellas fallan (n = 23) | **95.7 %** | 82.6 % | 91.3 % |
| Exactitud en textos no vistos (n = 104) | 97.1 % | 94.2 % | 96.2 % |
| κ holdout contra la plata (población) | 0.95 | 0.89 | — |
| ECE | 0.017 | 0.026 | — |

* **M4 − M1 en κ: +0.04, IC 95 % [−0.01, 0.09].** No es significativo con n = 199, pero es la primera vez que un modelo iguala o supera puntualmente a Gemini en todas las métricas.
* **Por banco (holdout):** de 0.92 (BBVA y NUBANK) a 0.97 (AZTECA), contra 0.83–0.92 de M1. La brecha entre bancos baja a 0.05.
* **Costo en el Mac:** 48 min de ajuste a 42 textos/s en MPS. La inferencia va a 483 textos/s, así que el backfill de ≤ 1.60 M textos únicos tardaría ~55 min en el Mac, contra ~3 min de M1 en CPU.
* **Límites:** una semilla, sin selección; el residuo de anclaje de *dev* favorece a los modelos entrenados con la plata (sección 7). Sin `gold_v1` no se puede afirmar que M4 supere a M1.

## 11. Plan para Kaggle (decisión del autor, 2026-10-19)

* **Motivo:** el Mac de 8 GB limita el lote a 8 y Delora corre a 9 pares/s; en el Mac no hay margen para semillas ni para buscar hiperparámetros.
* **Datos:** el autor decidió entrenar en Kaggle sin restricciones de volumen ni de PII (FMEA, F-13, riesgo aceptado).
  * El paquete (`kaggle/export_bundle.py`, 9.3 MB) lleva la plata sin `holdout_visto`, el oro *dev* y los ids del oro para excluirlos.
  * **El oro *test* no sale**, por método: se evalúa una sola vez en 5.8.
* **Flujo** (`kaggle/kaggle_push.py`): dataset y kernels privados con GPU. Las predicciones se descargan y `evaluate.py` corre en el Mac con el mismo protocolo.
* **Lotes:**
  1. `humo`: instalación, GPU y salidas (M4 y Delora con 2 000 textos).
  2. `m4`: RoBERTuito y BETO, 3 semillas cada uno; lote 32, fp16.
  3. `delora_grid`: detector solo, con 20 000 pares y 4 épocas: h1 y h2 en {(0.5, 0.5), (1, 1), (2, 2), (1, 2), (2, 1)} con rango 16, y rango 8 y 32 con (1, 1). Se elige por F1 de detección **fuera de muestra contra la plata**, no con el oro.
  4. Delora completo con la mejor configuración: detector con todos los pares, épocas del paper (8 con 2 de *warm-up*) y 3 semillas.

## 12. Kaggle: M4 con semillas y búsqueda del detector de Delora (2026-10-20)

Corridas en una T4 (lote 32, fp16, sin congelar embeddings). Evaluación en el Mac contra el *dev* aleatorio de `gold_v1` (n = 794 evaluables) y el dirigido (n = 297), con el protocolo de `evaluate.py`. Métricas completas en `sentiment_models_gold_v1_metrics.json`.

### M4: RoBERTuito y BETO, 3 semillas

| *dev* aleatorio (media de 3 semillas, rango) | M4 RoBERTuito | M4 BETO | M1 | M9 Gemini |
| :--- | :---: | :---: | :---: | :---: |
| κ | **0.917** (0.912–0.922) | **0.917** (0.912–0.923) | 0.869 | 0.933 |
| Macro-F1 | 0.831 (0.821–0.839) | 0.833 (0.823–0.846) | 0.771 | 0.892 |
| F1 de `NEU` | 0.553 (0.522–0.583) | 0.561 (0.533–0.596) | 0.415 | 0.731 |
| κ en el dirigido | **0.630** (0.625–0.638) | 0.578 (0.569–0.587) | 0.457 | 0.607 |
| ECE (muestra) | 0.035 | 0.032 | 0.031 | — |

* **M4 − M1 en κ es significativo en las seis corridas:** entre +0.043 y +0.053, y todos los IC 95 % excluyen el cero (el más bajo, [0.016, 0.070]).
* **Reproducibilidad:** la corrida del Mac (`M4_robertuito_mac`, κ 0.912) cae dentro del rango de semillas de Kaggle; ninguna semilla difiere de ella en más de 0.010 de κ.
* **RoBERTuito y BETO empatan en el aleatorio.** RoBERTuito es mejor en el dirigido (+0.05 de κ, rangos disjuntos), que concentra los casos difíciles; por eso Delora se corre con RoBERTuito.
* **Brecha con Gemini:** M9 − M4 en κ es +0.021 [−0.000, 0.043], en el límite de la significancia. Está concentrada en `NEU` (0.73 contra 0.55). En el dirigido, M4 RoBERTuito queda por encima de Gemini (0.63 contra 0.61).
* **Costo:** ~6 min de ajuste por corrida en la T4, contra 48 min en el Mac.

### Búsqueda del detector de Delora

Detector solo, 20 000 pares, 4 épocas con 1 de *warm-up*. Se elige por F1 contra la plata **fuera de muestra** (44 854 pares no usados para entrenar); el oro *dev* se informa pero no decide.

| h1, h2, rango | F1 plata fuera de muestra | Precisión | Recall | F1 oro *dev* |
| :--- | :---: | :---: | :---: | :---: |
| 0.5, 0.5, 16 | 0.822 | 0.926 | 0.740 | 0.642 |
| 1, 1, 16 | 0.827 | 0.929 | 0.745 | 0.668 |
| 2, 2, 16 | 0.835 | 0.930 | 0.758 | 0.681 |
| **1, 2, 16** | **0.842** | 0.933 | **0.768** | **0.704** |
| 2, 1, 16 | 0.814 | 0.931 | 0.722 | 0.653 |
| 1, 1, 8 | 0.802 | 0.923 | 0.710 | 0.607 |
| 1, 1, 32 | 0.809 | 0.935 | 0.713 | 0.637 |

* **Gana h1 = 1, h2 = 2, rango 16.** Un h2 más alto (la LoRA ruidosa se congela antes) sube el recall sin perder precisión. El rango 16 supera a 8 y a 32.
* El oro *dev* ordena igual las dos mejores configuraciones, lo que sugiere que la plata fuera de muestra es un criterio de selección razonable.
* El detector marca como ruidosas ~19 % de las estrellas; la plata discrepa de las estrellas en el 23.6 %.

### Errores del paper en las Eq. 5 y 6

Verificado contra el HTML de arXiv (2510.10208). La implementación sigue el criterio de la Eq. 3 (limpia si CE_c < CE_n) y no la notación literal:

* **Eq. 5:** escribe p_c = e^{CE_c} / (e^{CE_c} + e^{CE_n}) = σ(CE_c − CE_n), que da más probabilidad de limpia cuanto **peor** ajusta la LoRA limpia. Contradice la Eq. 3 y la frase del propio paper ("p_c > 0.5" equivale a la Eq. 3). Se usa p_c = σ(CE_n − CE_c).
* **Eq. 6:** L_Detector = (1/N_p) Σ ℓ_nll(p_c, y) + ℓ_nll(1 − p_c, y^n). Tiene tres problemas:
  1. arrastra el signo de la Eq. 5, así que minimizarla tal cual entrenaría al detector al revés;
  2. aplica una NLL multiclase a una probabilidad escalar con una etiqueta de clase;
  3. no indica que el segundo p_c se evalúa en la etiqueta volteada y^n; con el mismo p_c(x, y) en los dos términos, la pérdida es degenerada.
* **Lo que se implementa es la BCE estándar que el paper pretende:** −log p_c(x, y) − log(1 − p_c(x, y^n)), promediada sobre los positivos D_p, cuyos negativos son esos mismos positivos con la etiqueta volteada.
* **Evidencia de que el signo es el correcto:** el detector alcanza 0.93 de precisión contra la plata fuera de muestra; con el signo invertido quedaría por debajo del azar.
* **Siguiente:** lote `delora` con esa configuración, el detector con todos los pares, 8 épocas con 2 de *warm-up* y 3 semillas.

## 13. M8 Delora completo (2026-10-20)

Lote `delora` en Kaggle: RoBERTuito, h1 = 1, h2 = 2, rango 16, detector con los 64 854 pares, 8 épocas con 2 de *warm-up*, clasificador de 2 épocas, 3 semillas. Mismo protocolo de evaluación que la sección 12.

| *dev* aleatorio (media de 3 semillas, rango) | M8 (limpias + RCE) | M8 solo limpias | M4 RoBERTuito | M1 |
| :--- | :---: | :---: | :---: | :---: |
| κ | 0.866 (0.860–0.874) | 0.819 (0.805–0.841) | **0.917** (0.912–0.922) | 0.869 |
| Macro-F1 | 0.724 (0.704–0.750) | 0.641 (0.613–0.693) | **0.831** | 0.771 |
| F1 de `NEU` | 0.28 (0.22–0.35) | 0.07 (0.00–0.21) | **0.55** | 0.42 |
| Recall de `NEG` | 0.91 | 0.86 | **0.96** | — |
| κ en el dirigido | 0.40 (0.38–0.43) | 0.31 (0.25–0.40) | **0.63** | 0.46 |
| ECE (muestra) | 0.053 | 0.072 | 0.035 | 0.031 |

* **M8 − M4 en κ es negativo y significativo en las tres semillas:** entre −0.039 y −0.052 (el IC menos desfavorable, [−0.063, −0.015]). Contra M1 empata: entre −0.010 y +0.004, con todos los IC conteniendo el 0.
* **El detector es inestable entre semillas:** F1 contra la plata de entrenamiento de 0.76 a 0.86 y contra el oro *dev* de 0.58 a 0.72. La semilla con mejor detector (s3) da el mejor clasificador en las dos variantes.
* **Por qué pierde:** la etapa 2 entrena el subconjunto limpio con **las estrellas** como etiqueta. Con estrellas, `NEU` solo sale de las reseñas de 3 estrellas, que no equivalen a texto neutro, así que el modelo aprende poco neutro: `solo_limpias` llega a F1 de `NEU` = 0. El re-etiquetado con la plata y la RCE recuperan una parte, pero menos que entrenar con la plata en todo (M4).
* **El diseño de Delora supone que la etiqueta observada es la mejor disponible** y que el LLM solo se usa como apoyo. Aquí ocurre lo contrario: la plata (κ 0.93 contra el oro) es mucho mejor que las estrellas (κ 0.68), y M4 la aprovecha directamente.
* **Costo:** ~1 h por semilla en la T4 (detector ~45 min, dos clasificadores ~6 min cada uno), contra ~6 min de M4.

### Decisión

* **M8 se descarta como modelo de Q1** por la regla del protocolo: es más caro que M4 y significativamente peor, con las tres semillas. El *time-box* se cierra.
* **El detector se conserva como subproducto candidato** para la detección de incongruencia estrellas-texto (precisión 0.79–0.87 contra el oro *dev*). Su inestabilidad entre semillas obliga a promediar o ensamblar semillas si se adopta; se evalúa en la feature que use incongruencia, no en 5.4.
* **Sigue:** M5 (*label smoothing* sobre M4 RoBERTuito), dirigido a la brecha de `NEU` contra Gemini.

## 14. M5: M4 RoBERTuito con *label smoothing* (2026-10-20)

Lote `m5` en Kaggle: la receta de M4 (sección 12) con entropía cruzada suavizada, ε ∈ {0.1, 0.2} y 3 semillas por valor. **ε se elige por el macro-F1 medio en la validación sobre la plata**, declarado antes de mirar el oro: ε = 0.1 (0.905) contra ε = 0.2 (0.904). M4 obtiene 0.906 en esa misma validación.

| *dev* aleatorio (media de 3 semillas, rango) | M5 ε = 0.1 | M5 ε = 0.2 | M4 RoBERTuito | M9 Gemini |
| :--- | :---: | :---: | :---: | :---: |
| κ | 0.913 (0.912–0.915) | 0.913 (0.912–0.915) | **0.917** (0.912–0.922) | 0.933 |
| Macro-F1 | 0.828 (0.819–0.840) | 0.828 (0.819–0.839) | 0.831 (0.821–0.839) | 0.892 |
| F1 de `NEU` | 0.55 (0.52–0.58) | 0.55 (0.52–0.58) | 0.55 (0.52–0.58) | 0.73 |
| κ en el dirigido | 0.631 (0.630–0.631) | 0.631 (0.627–0.637) | 0.630 (0.625–0.638) | 0.607 |
| ECE (muestra) | 0.052 | 0.103 | **0.035** | — |

* **M5 empata con M4 en todas las métricas de clasificación.** La diferencia con M4 (Mac) en κ va de −0.000 a +0.002, con todos los IC conteniendo el 0. En las semillas 1 y 2, el F1 de `NEU` coincide exactamente con el de M4 de la misma semilla (0.52 y 0.58); en la 3 queda en 0.54, contra 0.55 de M4.
* **La calibración empeora**, como se espera del suavizado: el modelo queda subconfiado (ECE 0.05 con ε = 0.1 y 0.10 con ε = 0.2, contra 0.035 de M4).
* **Lectura:** el *label smoothing* protege contra ruido uniforme en la etiqueta. La brecha de `NEU` contra Gemini no se comporta así: M4 ya reproduce a su maestro en `NEG` y `POS`, y lo que falla es aprender una clase minoritaria de frontera. Es un problema de desbalance y de umbral, no de ruido simétrico.

### Decisión

* **M5 se descarta**: no mejora a M4 y empeora la calibración, con el mismo costo. La regla del protocolo no permite reemplazar a M4.
* **M4 RoBERTuito queda como el mejor modelo propio** para Q1, a +0.021 [−0.000, 0.043] de κ de Gemini.
* **Candidato barato:** un ajuste del sesgo de `NEU` en M4, sin reentrenar (abajo).

### Sesgo de `NEU` sobre M4 (2026-10-20)

`models/threshold.py` suma un sesgo b al log-probabilidad de `NEU` de cada semilla de M4 RoBERTuito y renormaliza. **b se elige por macro-F1 contra la plata de `holdout_nuevo`** (5 304 textos nunca vistos en el ajuste, 140 `NEU`), con una cuadrícula de −1 a 4 en pasos de 0.05. Se usa `holdout_nuevo` y no la validación del 5 % porque M4 no guarda pesos ni esas probabilidades. El oro no interviene.

| Semilla | b elegido | Macro-F1 holdout (plata, dentro de muestra) | Δκ *dev* | Δ macro-F1 *dev* | F1 `NEU` *dev* |
| :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | +0.95 | 0.836 → 0.846 | +0.003 | +0.017 | 0.52 → 0.57 |
| 2 | +2.10 | 0.839 → 0.856 | −0.005 | −0.010 | 0.58 → 0.56 |
| 3 | +1.90 | 0.843 → 0.854 | −0.002 | +0.012 | 0.55 → 0.59 |
| **Media** | — | — | **−0.001** | **+0.006** | **0.55 → 0.57** |

* **No hay ganancia medible.** κ medio queda en 0.916 (0.917 sin sesgo) y el dirigido en 0.632 (0.630). El signo del cambio en *dev* depende de la semilla, y la calibración no cambia (ECE 0.034).
* **El óptimo es plano:** b varía de +0.95 a +2.10 entre semillas con mejoras parecidas en la plata. La plata premia predecir más `NEU`; el oro no lo confirma.
* **La brecha de `NEU` contra Gemini son unos 5 ítems de 30.** M4 acierta 14–15 `NEU` del oro y Gemini 19; la mayoría de los errores de M4 van a `POS` (10–11 contra 7). Con 30 `NEU` en *dev*, una diferencia de ese tamaño no se resuelve; el oro *test* (5.8) es la próxima medición.
* **Para Q1 la brecha importa poco:** en `NEG`, M4 y Gemini empatan (recall 0.96 contra 0.96, precisión 0.96–0.97 contra 0.97).
* **Decisión:** el sesgo no se adopta, porque agrega un parámetro sin mejora en el oro. **La experimentación de 5.4 se cierra con M4 RoBERTuito** como el mejor modelo propio. La elección entre M4 y M9 queda para 5.8, por costo, licencia y el oro *test*.

## 15. Evaluación única en el oro *test* (5.8, 2026-10-22)

Protocolo y regla de decisión aprobados por el autor antes de mirar el *test* ([registro de decisión, tema 1](../decision_record.md#1-modelo-de-sentimiento-p8-1-p8-2)). Código: `sentiment/evaluate_test.py`; métricas: [`sentiment_models_test_metrics.json`](sentiment_models_test_metrics.json). Las predicciones del *test* no se guardan.

* **Datos:** 594 ítems evaluables de 601 (200 de `gold_v0_r2` y 394 de `gold_v1`; 7 `NA` del humano excluidos). Todos del bloque aleatorio, anotados a ciegas: 212 `NEG`, 22 `NEU` y 360 `POS`.
* **M4:** los pesos `M4_robertuito_s{1,2,3}_ppi` en el Mac (CPU, fp32) con la T de 5.6. Control previo: en el *dev* aleatorio, las tres semillas reproducen las clases de Kaggle al 100 % (diferencia máxima de probabilidad 0.004).
* **M9:** la etiqueta de `prompt_v3` ya guardada; cubre los 594 ítems, sin `NA`.

| *Test* (n = 594, muestra) | M4 `s1` | M4 `s2` | M4 `s3` | M4 media | M9 Gemini |
| :--- | :---: | :---: | :---: | :---: | :---: |
| κ (IC 95 %) | 0.929 (0.901–0.955) | 0.925 (0.896–0.951) | 0.932 (0.905–0.956) | **0.929** | **0.943** (0.917–0.966) |
| κ población | 0.927 | 0.922 | 0.933 | 0.927 | 0.942 |
| Macro-F1 | 0.859 | 0.857 | 0.872 | 0.863 | 0.893 |
| F1 `NEG` / `NEU` / `POS` | 0.970 / 0.629 / 0.978 | 0.967 / 0.629 / 0.977 | 0.972 / 0.667 / 0.978 | — | 0.979 / 0.718 / 0.981 |
| Recall / precisión `NEG` | 0.976 / 0.963 | 0.972 / 0.963 | 0.976 / 0.967 | 0.975 / 0.964 | 0.981 / 0.977 |
| ECE sin calibrar → calibrado | 0.029 → 0.014 | 0.029 → 0.015 | 0.029 → 0.011 | — | — |

**M9 − M4, pareado (muestra):**

| Métrica | `s1` | `s2` | `s3` |
| :--- | :---: | :---: | :---: |
| κ | +0.014 [−0.010, 0.037] | +0.017 [−0.007, 0.041] | +0.010 [−0.013, 0.032] |
| κ población | +0.015 [−0.015, 0.044] | +0.020 [−0.010, 0.050] | +0.009 [−0.017, 0.033] |
| Recall `NEG` | +0.005 [−0.014, 0.024] | +0.009 [−0.014, 0.031] | +0.005 [−0.014, 0.024] |
| Precisión `NEG` | +0.014 [−0.005, 0.036] | +0.014 [−0.005, 0.037] | +0.009 [−0.009, 0.031] |
| F1 `NEU` (22 ítems) | +0.089 [−0.060, 0.261] | +0.089 [−0.060, 0.261] | +0.051 [−0.087, 0.212] |

### Lectura

1. **El *test* confirma el *dev* y no muestra optimismo.** M4 sube de 0.917 a 0.929 y M9 de 0.933 a 0.943. La brecha baja de +0.021 a +0.014 de media, y en ninguna semilla ni en ningún peso el IC excluye el 0. El residuo de anclaje del *dev* (sección 7) no infló a M4.
2. **En `NEG`, lo que importa para Q1, no hay diferencia significativa.** M9 queda medio punto arriba en recall y un punto en precisión, con todos los IC conteniendo el 0.
3. **La ventaja de M9 sigue concentrada en `NEU`**, con 22 ítems: unos 2 aciertos más, y un IC de −0.06 a +0.26 en F1.
4. **La calibración se transfiere:** la T elegida en *dev* reduce el ECE del *test* a la mitad (0.029 → 0.011–0.015).

### Decisión (P8-1)

**M4 RoBERTuito**, aplicando la regla aprobada: el IC de M9 − M4 en κ incluye el 0 en las tres semillas, y M4 no pierde en `NEG`. Coincide con el criterio del autor de que la carga de la prueba está en M9, por sus gastos fijos y su dependencia de un servicio externo. El *test* queda consumido y no se vuelve a usar para elegir modelos.
