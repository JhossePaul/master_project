# Oro, segunda ronda: diseño de `gold_v1` (EPIC-5, feature 5.3)

> **Estado (2026-10-19): vigente; la cola se armó y se anotó.** Resultados en el [reporte de `gold_v1`](gold_v1_report.md). Índice: [`README.md`](../README.md).
> Este diseño estaba en [`epic_5.md`](../../backlog/epic_5.md), feature 5.3, punto 3, y se movió aquí sin cambiar cifras. Los pasos de "Después de anotar" ya se hicieron ([reporte](gold_v1_report.md), secciones 6 y 7).

**Motivo (2026-10-19):** sustituye al *active learning* puro. La primera ronda de 5.4 mostró que el oro chico ya no separa a los buenos modelos: *dev* tiene 199 ítems, el IC de κ mide ±0.06, hay 7 `NEU` y M9 − M1 = +0.03 [−0.01, 0.08].

* **Código:** [`sampling/sample_gold_v1.py`](../../../experiments/analytics/src/voc_analytics/sampling/sample_gold_v1.py).
  * `plan` no gasta ni arma cola; deja los agregados en `data/labels/gold_v1/plan.json` (fuera de git).
  * `queue --option X` arma la cola y corre Gemini sobre el bloque aleatorio (~$0.05).
* **Bloque aleatorio estratificado:** el único válido para cifras poblacionales y el único que entra a *test*.
  * Marco: 2 625 143 filas elegibles, sin las reseñas de `gold_v0` ni las filas `holdout_visto` de la plata.
  * 57 estratos banco × periodo (los de `gold_v0`) × estrellas (1–2, 3–4, 5).
  * Asignación igual por banco y proporcional a la raíz cuadrada del estrato dentro del banco, con mínimo 2 por estrato. Se registra π.
  * Sobremuestrea 3–4★, donde están el ruido y los `NEU` (24 % de la muestra, ~15 % de la población). Efecto de diseño de Kish: 1.4.
  * Dentro de cada estrato, una fracción fija va a *dev* y el resto a *test*.
  * Gemini (`prompt_v3`) etiqueta al armar la cola, así que M9 queda fijado antes de anotar.
* **Bloque dirigido:** solo para *dev* y análisis; nunca para *test* ni para cifras poblacionales.
  * Sale de la plata (`entrenamiento` y `holdout_nuevo`), que ya tiene Gemini. Un texto por clave, sin claves del oro ni del bloque aleatorio.
  * Criterios, en orden de selección y sin repetir textos:

    | Criterio | Definición | Textos candidatos | Reparto |
    | :--- | :--- | ---: | ---: |
    | `neu` | Gemini o M1 dicen `NEU` | 2 461 | 20 % |
    | `cinco_neg` | 5★ y Gemini `NEG` | 1 288 | 15 % |
    | `pico_3_4` | 3–4★ en día pico de volumen (`dia_pico_total`) | 1 386 | 15 % |
    | `desacuerdo` | M1 distinto de Gemini | 4 058 | 25 % |
    | `incertidumbre_m1` | 5 % de menor margen de M1 (p₁ − p₂) | 3 419 | 25 % |

  * En los textos de entrenamiento, M1 da probabilidades **fuera de partición** (la misma CV de 5 particiones de `sentiment/models/baselines.py`), para no subestimar la incertidumbre por memorización. En `holdout_nuevo` usa el modelo completo.
  * El desacuerdo con las estrellas ya lo cubren `cinco_neg` y `pico_3_4`. Cada ítem guarda todas las marcas que cumple.
  * Se reporta aparte (*dev* dirigido). Sirve para las diferencias pareadas en los casos difíciles y para `NEU`, no para el κ poblacional.
* **Segundo anotador:** 100 ítems del bloque aleatorio, proporcionales por estrato y a ciegas, en `gold_v1_a2` con la misma app y la misma guía. Mide el acuerdo entre personas sin la contaminación por Gemini que describe el [reporte de la re-anotación](gold_v0_r2_report.md).
* **Re-anotación:** 5 % del bloque aleatorio, al final de la cola.
* **Reglas de la cola:**
  * todo a ciegas;
  * el aleatorio y el dirigido se mezclan en orden aleatorio, y la app ya no muestra el bloque (salvo en la calibración), para que el anotador no sepa qué ítems son difíciles;
  * la cola solo lleva el texto; el diseño (estrato, π, partición, criterio, Gemini, M1) va aparte en `design.parquet`.
* **Nombre propio (F-01, acción 1):** la app agrega el campo `nombre_persona` (guía `v2.1`). La tasa se estima con el bloque aleatorio; con ≥ 600 ítems cumple la muestra de ≥ 500 del disparador de F-01.
* **Tamaño:**

  | Opción | Aleatorio (*dev* / *test*) | Dirigido | *Dev* aleatorio | *Test* | IC κ *dev* | IC κ *test* | `NEU` esperados en *dev* | Minutos del autor | Oro total |
  | :---: | :---: | ---: | ---: | ---: | :---: | :---: | ---: | ---: | ---: |
  | A | 600 (300 / 300) | 200 | 499 | 501 | ±0.042 | ±0.039 | ~45 | ~76 | 1 230 |
  | **B** | 1 000 (600 / 400) | 300 | 799 | 601 | ±0.034 | ±0.037 | ~69 | ~124 | 1 730 |
  | C | 1 200 (720 / 480) | 370 | 919 | 681 | ±0.029 | ±0.034 | ~80 | ~148 | 2 000 |

  * **Supuestos:**
    * El tiempo por longitud es el del bloque a ciegas de la primera ronda: 2.3 s en 1–3 palabras, 3.1 s en 4–10, 7.9 s en 11–30 y 13.2 s en 31+ (media 4.4 s). No se usa el de la re-anotación (3.3 s) porque los textos son nuevos. Los minutos incluyen la re-anotación.
    * El IC de κ (M1, semiamplitud al 95 %) sale de remuestrear el *dev* actual a cada tamaño (1 000 réplicas). Supone la mezcla de clases del *dev* actual.
    * `NEU` en el aleatorio: tasa de Gemini por grupo de estrellas en la plata, escalada por 2.5 / 1.86 (oro contra Gemini). En el dirigido: precisión de Gemini `NEU` en *dev* (5 de 7). Es la cifra más incierta.
    * El segundo anotador tarda ~8 minutos al ritmo del autor; una persona nueva, probablemente 2–3 veces más.
  * **Lectura:**
    * **≥ 30 `NEU` en *dev*:** las tres opciones llegan, casi solo por el bloque dirigido. Con solo el aleatorio (~2.8 % de `NEU`) harían falta ~800 ítems más en *dev*.
    * **IC de κ de ±0.03–0.04:** A apenas llega a ±0.04, B queda en ±0.034 (*dev*) y ±0.037 (*test*), y C llega a ±0.03.
    * **M9 contra M1:** el IC pareado de la diferencia (+0.026 hoy) mide ±0.049 con 199 ítems, ~±0.025 con 800 y ~±0.022 con 1 000. Ni C garantiza separarlos si la diferencia real es de ese tamaño. Para eso está el bloque dirigido; si aun así no se separan, la regla 8 del [protocolo de 5.4](../sentiment/sentiment_models_protocol.md) favorece al más barato.
    * **Se recomienda B:** cumple los dos objetivos con ~2 horas en 2–3 sesiones y deja el oro en 1 730, dentro del rango de 1 000–2 000. C cuesta 25 minutos más por 0.005 de IC.
* **Después de anotar** (pendiente):
  * `data.py`: `gold()` lee `gold_v1` con su partición y su π. Las cifras poblacionales combinan las dos muestras aleatorias, cada una con su diseño, ponderadas por su tamaño efectivo.
  * `gold_ids()` incluye `gold_v1`, y los textos del dirigido salen del entrenamiento por clave. M1 se reentrena sin ellos antes de comparar (20 s).
  * *Test* sigue intocable hasta 5.8.
* **Cola armada con la opción B (2026-10-19):** 1 350 ítems en `data/labels/gold_v1/` (fuera de git), sin duplicados y ninguno en `gold_v0` ni en `holdout_visto`.
  * 1 000 aleatorios (600 *dev*, 400 *test*), 300 dirigidos y 50 de re-anotación.
  * Gemini (`prompt_v3`, corrida `20261019T041916Z`) etiquetó los 1 000 aleatorios por $0.043.
  * El segundo anotador tiene 100 ítems en `gold_v1_a2/`: 68 de *dev* y 32 de *test*, porque se eligen por estrato sin mirar la partición.
  * Se anota con `GOLD_DIR=gold_v1 uv run streamlit run src/voc_analytics/annotation/app.py`, y el segundo anotador con `GOLD_DIR=gold_v1_a2` y su propio nombre.
