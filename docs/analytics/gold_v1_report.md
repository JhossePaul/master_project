# Oro, segunda ronda: `gold_v1` (EPIC-5, feature 5.3)

> **Estado (2026-10-19): vigente.** Es el oro actual y la sección 6 es la comparación de modelos vigente. Índice: [`README.md`](README.md).
> * **Segundo anotador (2026-10-20):** κ 0.81 entre personas (sección 7).
> * **F-01 (2026-10-20):** actualizada en la [matriz FMEA](../governance/ethical_fmea_matrix.md#f-01-nombres-propios-en-texto-libre) con 0 nombres en 1 300 anotadas; RPN 105 → 70, en monitoreo (sección 8).

* **Qué es:** 1 350 ítems anotados a ciegas por el autor con la guía `v2.1`, con el diseño de la opción B ([diseño](gold_v1_design.md)).

  | Bloque | Ítems | Uso |
  | :--- | ---: | :--- |
  | Aleatorio estratificado | 1 000 (600 *dev*, 400 *test*) | Cifras poblacionales y comparación de modelos |
  | Dirigido | 300 (*dev*) | Casos difíciles y `NEU`; sin cifras poblacionales |
  | Re-anotación | 50 | Consistencia del anotador |

* **Métricas:** [`gold_v1_metrics.json`](gold_v1_metrics.json), calculadas con [`analyze_gold_v1.py`](../../experiments/analytics/src/voc_analytics/analysis/analyze_gold_v1.py). Solo agregados.
* **El oro *test* no se comparó con ningún modelo**, ni con Gemini ni con las estrellas: queda para 5.8. De *test* solo se usan el tiempo, la consistencia y `nombre_persona`.
* **Tiempo:** 173.6 minutos efectivos (se estimaron ~124). La mediana es 3.8 s por ítem; la media truncada, 6.7 s en el aleatorio y 10.9 s en el dirigido. Los textos nuevos y difíciles cuestan más que en la primera ronda (4.4 s).

## 1. Calidad del etiquetado

| Medida | Valor |
| :--- | :--- |
| Consistencia en la re-anotación (n = 50) | 96 % de acuerdo, κ 0.93 (igual que en `gold_v0_r2`) |
| Ítems con `duda` | 2.5 % |
| Ítems con nota | 20; 10 preguntan si la falta de claridad del banco es una falla (sección 4) |

## 2. Población, con *dev* aleatorio (n = 600)

| Estimación poblacional (filas elegibles) | `gold_v1` | EE | `gold_v0_r2` (n = 400) |
| :--- | ---: | ---: | ---: |
| `NEG` / `NEU` / `POS` / `NO_EVALUABLE` | 28.2 / 2.9 / 68.0 / 0.9 % | 1.1 / 0.8 / 1.3 / 0.6 | 26.0 / 2.5 / 71.5 / 0.03 % |
| **Estrellas distintas del oro** (textos evaluables) | **12.5 %** | 1.3 | 9.9 % (EE 1.7) |
| Incongruencia en los extremos | 5.7 % | 1.0 | 4.7 % (EE 1.3) |
| κ estrellas contra oro | 0.68 (acuerdo 83 %) | — | 0.73 |

* **El ruido de las estrellas queda en 10–13 %.** La diferencia con la primera ronda (+2.6 puntos) está dentro de ~1.2 errores estándar combinados.
* **Sigue concentrado en 3★ y 4★:** de 49 reseñas de 3★, 38 son `NEG`; de 95 de 4★, 28 son `NEG`. Además, 11 de 291 reseñas de 5★ son `NEG`.

## 3. Gemini (`prompt_v3`) contra el oro

| Conjunto | n | Acuerdo | κ |
| :--- | ---: | ---: | ---: |
| ***Dev* aleatorio de `gold_v1`** | 600 | 95.7 % | **0.92** |
| *Dev* dirigido | 300 | 75.0 % | 0.60 |

* **κ 0.92 es la mejor estimación del acuerdo humano–Gemini.** Son textos nuevos, anotados a ciegas, con los que no se ajustó ni la guía ni el prompt. Cae entre la cifra conservadora de la primera ronda (0.84–0.88) y la cota superior de `gold_v0_r2` (0.93).
* **El punto débil de Gemini es `NEU`:** de 23 `NEU` del oro acierta 12, y manda 5 a `POS` y 4 a `NEG`. Además, 8 `NEG` del oro los llama `POS`.
* **El dirigido es difícil a propósito.** Ahí Gemini acierta el 75 %, y por criterio:

  | Criterio | n | Oro (`NEG` / `NEU` / `POS`) | Acuerdo Gemini | Acuerdo M1* | Acuerdo estrellas |
  | :--- | ---: | :---: | ---: | ---: | ---: |
  | `neu` | 60 | 12 / 41 / 7 | 68 % | 73 % | 32 % |
  | `cinco_neg` | 45 | 42 / 1 / 2 | 93 % | 89 % | 4 % |
  | `pico_3_4` | 45 | 30 / 0 / 15 | 91 % | 91 % | 33 % |
  | `desacuerdo` (M1 ≠ Gemini) | 75 | 43 / 12 / 19 | 65 % | 21 % | 53 % |
  | `incertidumbre_m1` | 75 | 28 / 21 / 24 | 69 % | 48 % | 52 % |

  \* M1 del momento de la selección (fuera de partición en entrenamiento). La comparación de modelos está en la sección 6.

  * **Las 5★ que Gemini llama `NEG` son quejas reales** en 42 de 45 casos: el ruido que las estrellas esconden existe también en los extremos.
  * **El criterio `neu` acierta 2 de cada 3**, y es lo que lleva *dev* de 7 a 105 `NEU` (7 de `gold_v0`, 23 del aleatorio y 75 del dirigido).
  * **Cuando M1 y Gemini discrepan, Gemini tiene razón 3 veces más seguido** (65 % contra 21 %).

## 4. `menciona_falla` y las quejas por falta de claridad del banco

| Conjunto | κ oro–Gemini | Oro sí, Gemini no | Oro no, Gemini sí | Tasa oro / Gemini |
| :--- | ---: | ---: | ---: | :---: |
| *Dev* aleatorio | 0.86 | 11 | 28 | 32.5 / 35.3 % |
| Dirigido | 0.59 | 30 | 30 | 41 / 41 % |

* **El κ de `menciona_falla` se mantiene** (0.84 en la primera ronda). En el aleatorio, el anotador marca **menos** fallas que Gemini, no más.
* **Caso fronterizo detectado al anotar:** quejas por decisiones del banco que parecen unilaterales si no se explican, como la ubicación obligatoria, los límites de monto o los rechazos sin motivo. Muchas vienen de la regulación.
  * El anotador las marcó como `NEG` y con falla cuando causan molestia.
  * Las 10 reseñas con nota sobre esto son 9 `NEG` y 1 `NEU`. El anotador marcó falla en 9; Gemini, en 5.
  * **El sentimiento no cambia:** la regla 2 ya cubre la queja concreta, y la regla 7 la que es sobre el banco. La ambigüedad es solo de `menciona_falla`.
* **Decisión (2026-10-19):** la regla queda en la [guía `v2.2`](annotation_guideline.md), regla 2. Codifica lo que el anotador ya hizo, así que ninguna etiqueta de `gold_v1` cambia. `prompt_v3` no la incluye y marca menos fallas en estos casos; un `prompt_v4` solo se justifica si `menciona_falla` entra a las métricas de 5.5.

## 5. Nombres propios (F-01, acción 1)

| Bloque | Con nombre | n | Tasa | Cota superior 95 % |
| :--- | ---: | ---: | ---: | ---: |
| Aleatorio | 0 | 1 000 | 0 % | 0.3 % (regla del tres) |
| Dirigido | 0 | 300 | 0 % | 1.0 % |

* El único caso marcado (`G0170`) fue un error de dedo: el anotador lo revisó, no tiene información personal y corrigió la marca en la app.
* **Lectura para F-01:** la tasa poblacional de nombres que la regex no detecta es menor que 0.3 %. El disparador de F-01 ("al menos un nombre en una muestra de ≥ 500") se definió para una muestra aleatoria, y en ella no hubo ninguno. En las 1 300 reseñas anotadas no apareció ningún nombre. La acción 1 de F-01 queda hecha y la [matriz FMEA](../governance/ethical_fmea_matrix.md#f-01-nombres-propios-en-texto-libre) ya la registra (RPN 105 → 70).

## 6. Comparación de modelos con *dev* ampliado

* **Métricas:** [`sentiment_models_gold_v1_metrics.json`](sentiment_models_gold_v1_metrics.json), con [`evaluate.py`](../../experiments/analytics/src/voc_analytics/sentiment/evaluate.py).
  * *Dev* aleatorio: 794 evaluables (199 de `gold_v0` y 595 de `gold_v1`), con 30 `NEU`.
  * *Dev* dirigido: 297 evaluables, con 75 `NEU`.
  * `sentiment_models_metrics.json` queda como registro de la primera ronda.
* **Se volvieron a predecir** M0–M3, M6, M7 y T0. Los TF-IDF se reentrenaron sin ninguna reseña del oro.
* **M4 (RoBERTuito ajustado con la plata) se reentrenó** en el Mac con la misma configuración que la primera corrida (MPS, lote 8 × 4, embeddings congelados, 2 épocas, una semilla; 46 min). El modelo anterior tenía 341 reseñas de `gold_v1` en su entrenamiento, así que no bastaba con predecir los ítems nuevos. Ahora se entrena con 60 287 textos, sin ninguna reseña de las colas del oro, y sobrescribe `M4_robertuito_mac`.

| Modelo | κ *dev* aleatorio (IC 95 %) | Macro-F1 | F1 `NEU` | Recall `NEG` | κ población | κ *dev* dirigido (IC 95 %) |
| :--- | :---: | ---: | ---: | ---: | ---: | :---: |
| M0 estrellas | 0.68 (0.65–0.72) | 0.62 | 0.16 | 66.3 % | 0.71 | 0.14 (0.08–0.20) |
| **M1 TF-IDF + LR** | **0.87 (0.84–0.90)** | 0.77 | 0.42 | 93.0 % | 0.89 | 0.46 (0.38–0.53) |
| M1 ponderado por filas | 0.88 (0.85–0.91) | 0.80 | 0.51 | 93.8 % | 0.91 | 0.43 (0.35–0.51) |
| M1 con `texto_limpio` | 0.88 (0.85–0.91) | 0.77 | 0.42 | 93.8 % | 0.90 | 0.43 (0.35–0.50) |
| M2 BETO | 0.60 (0.56–0.64) | 0.62 | 0.19 | 67.4 % | 0.59 | 0.35 (0.27–0.42) |
| M2 RoBERTuito | 0.53 (0.49–0.57) | 0.60 | 0.15 | 86.1 % | 0.49 | 0.42 (0.34–0.50) |
| M3 (TF-IDF con estrellas) | 0.71 (0.67–0.75) | 0.64 | 0.16 | 69.6 % | 0.74 | 0.09 (0.02–0.17) |
| M6 (corrección *forward*) | 0.83 (0.80–0.86) | 0.62 | 0.00 | 91.2 % | 0.84 | 0.14 (0.07–0.21) |
| M7 (*Confident Learning*) | 0.64 (0.60–0.68) | 0.61 | 0.10 | 70.3 % | 0.65 | 0.15 (0.08–0.23) |
| T0 `TextBlob` | 0.02 (0.01–0.03) | 0.08 | 0.07 | 4.8 % | 0.02 | 0.00 |
| **M4 RoBERTuito ajustado** | **0.91 (0.89–0.94)** | 0.82 | 0.51 | 96.0 % | 0.93 | **0.63 (0.56–0.70)** |
| **M9 Gemini** | **0.93 (0.91–0.96)** | **0.89** | **0.73** | **96.3 %** | **0.95** | **0.61 (0.53–0.68)** |

**Diferencias pareadas en κ (muestra):**

| Diferencia | *Dev* aleatorio | *Dev* dirigido | Lectura |
| :--- | :---: | :---: | :--- |
| M1 − M0 | +0.19 [0.14, 0.23] | — | M1 sigue superando a las estrellas |
| **M9 − M1** | **+0.064 [0.035, 0.095]** | **+0.15 [0.05, 0.26]** | **Gemini ya es significativamente mejor que M1** |
| **M4 − M1** | **+0.043 [0.020, 0.070]** | **+0.17 [0.09, 0.27]** | **El encoder ajustado supera a M1, y por mucho en los casos difíciles** |
| **M9 − M4** | **+0.021 [−0.000, 0.043]** | **−0.02 [−0.10, 0.05]** | **M4 cierra dos tercios de la brecha con Gemini; ya no se distinguen** |
| M6 − M1 | −0.039 [−0.070, −0.005] | −0.32 [−0.41, −0.21] | Aprender de las estrellas con corrección no alcanza a M1 |
| M1 ponderado por filas − M1 | +0.013 [0.001, 0.027] | −0.02 [−0.07, 0.02] | Borde: excluye el 0 por poco en el aleatorio y no en el dirigido |

### Lectura

1. **El oro grande separa lo que el chico no podía.** Con 199 ítems, M9 − M1 era +0.03 [−0.01, 0.08]; con 794 es +0.064 y excluye el 0. En el dirigido la brecha es de 0.15.
2. **El κ 0.91 de M1 en el *dev* original estaba inflado por el anclaje.** En las 199 de `gold_v0` M1 tiene κ 0.91; en las 595 nuevas, 0.86. Gemini se mantiene en 0.94 y 0.93, y las estrellas en 0.69 y 0.68. Es el residuo de anclaje que advirtió el [reporte de la re-anotación](gold_v0_r2_report.md): esos textos se anotaron primero viendo la propuesta de Gemini, de la que M1 aprende.
3. **`NEU` es donde más pierde M1:** F1 0.42 contra 0.73 de Gemini. En textos no vistos en el entrenamiento (466), M1 baja a κ 0.81 y Gemini queda en 0.90.
4. **La escalera de ruido (M3, M6, M7) no mejora a M1.** Entrenar con estrellas, incluso corrigiendo la transición, queda por debajo de destilar a Gemini.
5. **Ponderar por filas queda en el borde** (+0.013, IC [0.001, 0.027]), con el signo contrario en el dirigido. Según la regla 8 no basta para adoptarlo; se reporta como ablación.
6. **M4 cierra la mayor parte de la brecha con Gemini, pero no toda.**
   * En el *dev* aleatorio, M9 − M4 es +0.021 con IC [−0.000, 0.043]: el límite inferior roza el 0, así que no hay una diferencia significativa, pero tampoco hay evidencia de que M4 iguale a Gemini. Con pesos poblacionales, +0.017 [−0.007, 0.042].
   * En el dirigido, M4 queda por encima de Gemini (0.63 contra 0.61; −0.02 [−0.10, 0.05]). Gana en `neu` (κ 0.60 contra 0.24) y en `cinco_neg` (0.73 contra 0.00), y pierde en `desacuerdo` (0.34 contra 0.43).
   * M4 también tiene anclaje: κ 0.95 en las 199 de `gold_v0` y 0.90 en las 595 nuevas. El 0.95 de la primera ronda estaba inflado igual que el de M1.
   * Donde M4 sigue detrás de Gemini es en `NEU` del aleatorio (F1 0.51 contra 0.73; acierta 12 de 30) y en textos no vistos en el entrenamiento (κ 0.87 contra 0.90). Supera a M1 en ambos (0.42 y 0.81).
7. **Implicación para 5.4 y 5.8:**
   * M4 es el mejor candidato local: +0.043 sobre M1 y a 0.02 de Gemini, sin costo por texto. Es una sola semilla en el Mac; falta medir la varianza entre semillas (Kaggle) antes de elegirlo.
   * Gemini como clasificador directo cuesta ~$72 por el backfill de 1.6 M textos (a $0.045 por 1 000), así que la comparación de costo es real.

## 7. Acuerdo entre anotadores (`gold_v1_a2`)

* **Qué es:** una segunda persona, independiente del autor, anotó a ciegas 100 ítems del bloque aleatorio de `gold_v1` con la guía `v2.2`, la misma app y sin ver las etiquetas del autor ni las de Gemini.
  * Son 68 ítems de *dev* y 32 de *test*. El acuerdo entre personas no evalúa ningún modelo, así que usa los 100; Gemini y las estrellas solo se comparan en los 68 de *dev*.
  * Tardó 78 minutos efectivos (mediana 24.7 s por ítem; el autor, 3.0 s en los mismos ítems). Era su primera vez con la guía.
* **Métricas:** [`gold_v1_a2_metrics.json`](gold_v1_a2_metrics.json), con [`analyze_gold_v1_a2.py`](../../experiments/analytics/src/voc_analytics/analysis/analyze_gold_v1_a2.py). Solo agregados; el nombre del segundo anotador no se registra en `docs/`.

| Acuerdo autor – segundo anotador | n | Acuerdo | κ (IC 95 %) |
| :--- | ---: | ---: | :---: |
| **Sentimiento, 4 clases** (con `NO_EVALUABLE`) | 100 | 90 % | **0.81 (0.70–0.91)** |
| Sentimiento, 3 clases (ambos evaluables) | 94 | 93.6 % | 0.87 (0.75–0.96) |
| `menciona_falla` | 100 | 90 % | 0.75 |

| En los 68 de *dev* | κ contra el autor | κ contra el segundo anotador |
| :--- | ---: | ---: |
| Gemini (`prompt_v3`) | 0.91 | 0.88 |
| Estrellas (M0) | 0.67 | 0.76 |
| El otro anotador | 0.80 | 0.80 |

### Lectura

1. **El acuerdo entre personas es alto pero no perfecto:** κ 0.81 con 4 clases y 0.87 con 3. Es la cifra independiente que pedía el [reporte de la re-anotación](gold_v0_r2_report.md): sin calibración con Gemini ni anclaje.
2. **Gemini queda al nivel humano.** En *dev*, Gemini coincide con cada anotador (0.91 y 0.88) tanto o más que los anotadores entre sí (0.80). Con el segundo anotador coincide algo menos que con el autor, coherente con que la guía se ajustó con los desacuerdos del autor.
3. **La mayor fuente de desacuerdo es la regla 2.** De los 10 desacuerdos, 4 son `NEG` del autor contra `POS` del segundo anotador, en textos de 7 a 26 palabras. En 2 de ellos el segundo anotador sí marcó `menciona_falla` y aun así eligió `POS`: decidió por el tono general, no por la regla 2 amplia ("cualquier queja concreta ⇒ `NEG`"). Por eso las estrellas coinciden más con él (0.76) que con el autor (0.67).
4. **El otro tipo de desacuerdo es `NO_EVALUABLE` contra `NEU` o `NEG`** en textos de 1 a 3 palabras (4 casos). Es la frontera de la regla 1.
5. **Solo 1 de los 10 desacuerdos tenía `duda`** marcada por alguno de los dos: los anotadores no los percibían como difíciles.
6. **`nombre_persona`:** ninguno de los dos marcó nombres en estos 100 ítems.

### Implicaciones

* **Techo de medición.** Con κ ~0.8–0.87 entre personas, un modelo con κ 0.91–0.93 contra el oro del autor ya está al nivel del acuerdo humano. Las diferencias de 0.02 entre los mejores modelos (M4 y Gemini, sección 6) están por debajo del ruido entre anotadores. El oro mide la aplicación de la guía por un anotador, y así se declara en la tesis.
* **La regla 2 amplia es una decisión del proyecto, no una lectura natural.** Un anotador nuevo tiende a decidir por el tono. Si se suman anotadores, la guía necesita ejemplos de reseñas largas con elogio y una queja menor, y una calibración corta antes de anotar.
* **El sesgo hacia el autor es pequeño pero existe:** Gemini y M1 aprendieron su criterio. Se reporta el κ contra ambos anotadores donde haya doble etiqueta.

## 8. Decisiones y pendientes

1. **`gold_v1` entra al oro vigente.** Con él, Gemini supera a M1 y M4 queda a 0.02 de Gemini sin diferencia significativa (sección 6). *Dev* aleatorio pasa de 199 a 799 ítems (794 evaluables), *test* de 201 a 601, y *dev* dirigido suma 300. `data.py` los integra con `bloque_oro` y pesos combinados.
2. **Guía `v2.2` (adoptada):** la falta de claridad o comunicación del banco sobre una decisión que molesta al cliente cuenta como queja concreta de servicio. Es `NEG` y lleva `menciona_falla` = sí, aunque la medida venga de la regulación. Codifica lo que el anotador ya hizo; no cambia ninguna etiqueta.
3. **Segundo anotador (hecho):** κ 0.81 (4 clases) y 0.87 (3 clases) con el autor en 100 ítems. La diferencia entre los mejores modelos queda por debajo de ese ruido (sección 7).
4. **F-01 (hecho, 2026-10-20):** `G0170` fue un error de dedo (corregido). La [matriz FMEA](../governance/ethical_fmea_matrix.md#f-01-nombres-propios-en-texto-libre) registra 0 nombres en 1 300 reseñas: O 3 → 2 y RPN 105 → 70, y la fila pasa a monitoreo.
