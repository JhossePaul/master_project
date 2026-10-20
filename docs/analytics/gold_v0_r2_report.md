# Re-anotación a ciegas del oro (EPIC-5, feature 5.3)

> **Estado (2026-10-19): vigente en parte.** Índice: [`README.md`](README.md).
> * **Sigue vigente:** `prompt_v3` como prompt de la plata, y estas 400 etiquetas como parte del oro (199 en *dev* y 201 en *test*).
> * **Reemplazado por** [`gold_v1`](gold_v1_report.md):
>   * "oro vigente = 400 aleatorias" → oro de 1 730 ítems (*dev* aleatorio 799, *dev* dirigido 300, *test* 601 y 30 de calibración);
>   * κ 0.93 como cota superior → 0.92 como mejor estimación del acuerdo humano–Gemini;
>   * ruido de las estrellas de 9.9 % → 12.5 % (EE 1.3).
> * **Sigue pendiente:** el segundo anotador (sección 5, punto 3), ahora como la cola `gold_v1_a2`.

* **Qué es:** el autor re-anotó los 430 ítems del oro con `annotation_guideline_v2`, todo a ciegas y en un orden nuevo.
  * Fue ~14 horas después de la primera ronda ([reporte](gold_v0_report.md)).
  * Tomó 23.7 minutos efectivos, con 2 correcciones.
* **Métricas:** [`gold_v0_r2_metrics.json`](gold_v0_r2_metrics.json), calculadas con [`analyze_gold_v0_r2.py`](../../experiments/analytics/src/voc_analytics/analysis/analyze_gold_v0_r2.py). Solo agregados.
* **Oro vigente:** desde ahora el **oro es la re-anotación**. Las 400 reseñas aleatorias quedan anotadas a ciegas con la guía v2; la primera ronda se conserva para medir consistencia y anclaje.

| Sección | Ítems | Origen en la primera ronda |
| :--- | ---: | :--- |
| `r2_ciego` | 201 | Aleatorio a ciegas |
| `r2_asistido` | 199 | Aleatorio asistido, ahora sin propuesta |
| `r2_calibracion` | 30 | Calibración |

## 1. Consistencia del anotador

| Ítems (modo en la primera ronda) | Acuerdo | κ |
| :--- | ---: | ---: |
| Aleatorio a ciegas | 97.5 % | 0.94 |
| Aleatorio asistido | 97.0 % | 0.93 |
| Calibración | 93.3 % | 0.80 |

* **Pocos cambios, y coherentes con la guía.**
  * En el bloque a ciegas cambiaron 5 de 201; dos de ellos son `POS` → `NEG`, la regla 2 amplia.
  * En el asistido cambiaron 6 de 199, todos desde `NEU`: 4 a `NEG` y 2 a `POS`.
* **Es una cota optimista:**
  * 14 horas no bastan para olvidar los textos (la guía pide días);
  * la consistencia incluye el efecto de recordar la decisión anterior.

## 2. Anclaje, visto en retrospectiva

| Textos que fueron asistidos (n = 199) | Acuerdo con `prompt_v1` |
| :--- | ---: |
| Primera ronda, viendo la propuesta | 99.5 % |
| Re-anotación a ciegas | 96.5 % |
| Para comparar: textos que siempre fueron a ciegas (n = 201) | 94.5 % |

* **Al quitar la propuesta, el acuerdo con Gemini baja 3 puntos.** Queda 2 puntos por encima del bloque que nunca vio propuesta.
* **El anclaje inmediato es real**, y un residuo pequeño persiste en la memoria, dentro del ruido con estos tamaños.
* La decisión de anotar todo a ciegas se mantiene.

## 3. Ruido de las estrellas, con el oro vigente (n = 400, todo a ciegas)

| Estimación poblacional (filas elegibles) | Valor | EE |
| :--- | ---: | ---: |
| **Estrellas (1–2 NEG, 3 NEU, 4–5 POS) distintas del oro**, textos evaluables | **9.9 %** | 1.7 |
| Incongruencia en los extremos (1–2★ con POS, o 4–5★ con NEG) | 4.7 % | 1.3 |
| Oro `NEG` / `NEU` / `POS` / `NO_EVALUABLE` | 26.0 / 2.5 / 71.5 / 0.03 % | 2.5 / 0.9 / 2.6 / — |
| κ estrellas contra oro (M0) | 0.73 (acuerdo 89.2 %) | — |

* **Las cifras son estables** frente a la primera ronda (10.4 % y 4.2 %).
* **El ruido sigue concentrado en 3★ y 4★:**
  * de 14 reseñas de 3★, 11 son `NEG` en el oro;
  * de 42 de 4★, 13 son `NEG`.
* **Por banco** la incongruencia va de 3.2 % (AZTECA) a 7.0 % (NUBANK). **Por periodo**, de 2.9 % (2020–2022) a 8.1 % (hasta 2019). Los EE de 2–3.5 puntos no permiten afirmar diferencias.

## 4. Prompts contra el oro vigente

| Prompt | κ aleatorio (n = 400) | Acuerdo | κ falla | κ calibración (n = 30) | Estabilidad entre corridas | Costo por 1 000 textos |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `prompt_v0` (JSON) | 0.91 | 96.3 % | 0.84 | 0.66 | — | $0.124 |
| `prompt_v1` | 0.90 | 95.5 % | 0.84 | 0.25 | 95.2 %* | $0.052 |
| `prompt_v2` (guía v1) | 0.91 | 96.0 % | 0.84 | 0.70 | 98.4 % | $0.045 |
| **`prompt_v3` (guía v2)** | **0.93** | **97.0 %** | 0.84 | 0.70 | **99.8 %** | **$0.045** |

\* Medida en el piloto, sobre otros textos.

* **Diferencias con bootstrap pareado** (2 000 réplicas):
  * κ(v3) − κ(v0) = +0.017, IC 95 % [−0.012, 0.049];
  * κ(v3) − κ(v2) = +0.022, IC 95 % [−0.012, 0.058].
  * **Ningún prompt es significativamente mejor** con n = 400.
* **Se elige `prompt_v3` para la plata.** Tiene el mejor κ puntual, la mayor estabilidad (casi determinista), el costo más bajo y está alineado con la guía vigente.
* **Errores de v3 contra el oro (12 de 400), repartidos:**
  * 3 `POS` → `NEG`;
  * 3 `POS` → `NEU`;
  * 3 `NEU` → `POS`;
  * 2 `NEG` → `NEU`;
  * 1 `NEG` → `POS`.
* **`menciona_falla`:** κ ≈ 0.84 para todos los prompts.

### Cuánto creerle al κ

* **El oro vigente no es del todo independiente de Gemini:**
  * el anotador vio sus etiquetas en la calibración y en el modo asistido;
  * la guía v2 se ajustó con los desacuerdos contra `prompt_v2`.
* Por eso **κ = 0.93 es una cota superior** del acuerdo con un anotador independiente. La cifra conservadora es la de la primera ronda a ciegas: 0.84–0.88.
* **Para la tesis se reportan ambas.** Lo que se necesita para la plata es que Gemini supere con holgura a las estrellas, y lo hace: κ 0.88–0.93 contra 0.73.

## 5. Decisiones

1. **Oro vigente:** la re-anotación (400 aleatorias y 30 de calibración, guía v2, a ciegas). Es el que usan 5.4 y 5.6.
2. **Prompt de la plata:** `prompt_v3` con `gemini-3.6-flash`.
3. **Pendiente para la tesis:** un segundo anotador independiente sobre una submuestra a ciegas (por ejemplo, 100 reseñas). Mediría el acuerdo entre personas sin la contaminación descrita arriba.
