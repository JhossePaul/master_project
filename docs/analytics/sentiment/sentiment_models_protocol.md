# Competencia de sentimiento: candidatos y protocolo (EPIC-5, feature 5.4)

> **Estado (2026-10-19): vigente.** Es el protocolo con el que se evalúan todos los modelos. Estaba en [`epic_5.md`](../../backlog/epic_5.md), feature 5.4, y se movió aquí sin cambios de fondo; las particiones del punto 4 ya incluyen `gold_v1`. Desde 2026-10-19 salen del entrenamiento las reseñas de **todas** las colas del oro, no solo las 430 de `gold_v0` que menciona el punto 3. Resultados: [primera ronda](sentiment_models_v0_report.md) y [comparación con `gold_v1`](../labeling/gold_v1_report.md), sección 6. Índice: [`README.md`](../README.md).

**Objetivo:** elegir el modelo de Q1 por evidencia, con el mismo protocolo para todos.

**Candidatos (escalera de complejidad):**

| ID | Estrategia | Fuente |
| :---: | :--- | :--- |
| M0 | Estrellas → polaridad (1–2 NEG, 3 NEU, 4–5 POS) | Referencia trivial: mide cuánto ruido hay |
| M1 | TF-IDF + regresión logística / SVM | Molla et al. (2026): los clásicos compiten con pocos datos |
| M2 | Encoder de sentimiento sin ajuste (p. ej., `pysentimiento/robertuito-sentiment-analysis`) | Pérez et al. (2022) |
| M3 | Encoder ajustado con estrellas como etiqueta | Referencia ingenua: aprende el ruido |
| M4 | Encoder ajustado con etiquetas de plata | Destilación del LLM |
| M5 | M3 o M4 con *label smoothing* | Gao et al. (2024) |
| M6 | Corrección *forward* con matriz de transición estrellas → sentimiento | Patrini et al. (2017); Sukhbaatar et al. (2015) |
| M7 | *Confident Learning* (`cleanlab`) para filtrar o re-ponderar y reentrenar | Northcutt et al. (2021) |
| M8 | Delora adaptado: detector de dos LoRA (Eq. 3) y clasificador en etapa 2 | Yuan, Chen y Zhang (2025) |
| M9 | Gemini Flash como clasificador directo | Costo por millón medido en 5.3 |

* **Encoders a evaluar** (la disponibilidad y licencia de cada checkpoint se verifican antes de usarlo):
  * `robertuito` (preentrenado con tuits);
  * RoBERTa-BNE / BETO (español general);
  * mDeBERTa-v3 (multilingüe).
* El rango de LoRA es un hiperparámetro (Steele, 2026), no se fija en 8.
* **M8 es el más caro y el menos validado:** el paper solo evalúa Llama-3.1-8B y requiere h₁, h₂ y un conjunto limpio. Se time-boxea y se compara contra M5–M7. Si no supera claramente a los métodos baratos, no se adopta. Los otros dos "DeLoRA / Dual LoRA" (Bini et al.; Xu et al.) **no tratan ruido** y no son candidatos (`references.md`, C3).
* **Protocolo:**
  * validación cruzada sobre la plata, estratificada por banco y periodo;
  * selección en el oro *dev*;
  * reporte final una sola vez sobre el oro *test*, con intervalos de confianza por *bootstrap* y estimaciones poblacionales por PPI.
* **Métricas de calidad:**
  * macro-F1;
  * **Negative Recall** y precisión de `NEG`;
  * detección de incongruencia (sobre el oro: el modelo acierta cuando estrellas y texto no coinciden);
  * calibración (ECE);
  * brecha de desempeño entre bancos y entre periodos (la paridad por banco y periodo sustituye a la "paridad dialectal" del caso de uso, que no tiene un corpus de modismos etiquetado; `references.md`, C6).
* **Métricas de costo:**
  * reseñas por segundo y costo por millón en Mac M2 (MPS), Kaggle T4 y Cloud Run CPU;
  * tamaño del artefacto;
  * memoria.

**Plan experimental (2026-10-19):** concreta el protocolo de arriba con la plata v0 y el oro vigente. El código está en [`voc_analytics.sentiment`](../../../experiments/analytics/src/voc_analytics/sentiment/):
* `data.py` y `metrics.py`, comunes a todos los modelos;
* un script por familia en `models/`, que solo guarda predicciones (`baselines.py`, `pretrained.py`, `noisy.py`, `finetune.py`, `delora.py`);
* `evaluate.py`, que calcula todas las métricas con el mismo protocolo.

1. **Alcance y orden.** La escalera se recorre de lo barato a lo caro, y cada peldaño se compara contra el mejor anterior:
   * **Fase A, Mac y $0 (primera ronda):**
     * M0 y M1;
     * M2 con los dos encoders de `pysentimiento` en español: RoBERTuito (`pysentimiento/robertuito-sentiment-analysis`) y BETO (`finiteautomata/beto-sentiment-analysis`). BERTweet es su analizador en **inglés** y no se evalúa sobre español;
     * **T0, el léxico de `TextBlob` del EDA preliminar** ([`experiments/project_viability/`](../../../experiments/project_viability/README.md)), por continuidad y con su misma receta: polaridad sobre el texto sin limpiar, umbral ±0.1. Su léxico es en inglés;
     * M9 (Gemini, `prompt_v3`), ya medido en 5.3 (κ 0.93 contra el oro), se recalcula con las mismas métricas y particiones como techo.
   * **Licencias:** los modelos de `pysentimiento` son solo para uso no comercial e investigación, y heredan la licencia de TASS. Sirven para la tesis; para producción (5.8) cuentan como restricción.
   * **Fase B, ajuste de encoders:** M3–M7 sobre el encoder que mejor salga de M2 y uno de español general. Primero en el Mac (MPS); Kaggle si no cabe. **Nada de GPU en GCP sin aprobación del autor.**
   * **Fase C:** M8, con *time-box*, solo si M5–M7 dejan margen.
2. **Texto de entrada y limpieza** (la evaluación de la limpieza por familia que dejó pendiente 5.2):
   * **Entrada por defecto:** `texto_sanitizado`, el mismo campo que vieron Gemini y el anotador. Los tokens de sanitización se dejan tal cual; cada encoder aplica su propio preprocesamiento (`pysentimiento` convierte emojis a texto).
   * **Ablación:** M1 y cada M2 también corren sobre `texto_limpio` (`limpiar_texto_bancario`: minúsculas, sin URLs ni menciones, repeticiones recortadas), que era la entrada del EDA preliminar. Se adopta la limpieza solo si gana en el oro *dev* con la regla del punto 8.
   * **Sin filtro de longitud:** el rango de 2 a 60 palabras del EDA preliminar no se aplica, porque la longitud predice las estrellas (EDA, H1) y filtrar sesga los agregados. Las reseñas de una palabra siguen en la plata y en el oro mientras `TNSS_SINGLE_WORD` esté pendiente. En su lugar, **las métricas se desglosan por longitud** (1, 2–3, 4–10, 11–30 y 31+ palabras) y en el subconjunto de 2–60 del preliminar. Eso informa la decisión de 5.8: si los modelos aciertan casi siempre en una palabra, excluirlas no ahorra error; si fallan, el léxico `RULE_BASED` gana sentido.
3. **Duplicados y ponderación:**
   * **Un ejemplo por texto único** (`text_id`, la unidad del etiquetado). Los duplicados no agregan información de etiqueta, solo inclinan el prior hacia los elogios breves.
   * **Las 430 reseñas del oro salen del entrenamiento**, en cualquier bloque. Su texto puede seguir entrando por otras filas iguales ("excelente"): es la repetición natural del corpus, y por eso las métricas se desglosan en texto visto y no visto en entrenamiento.
   * **Ablaciones, no selección:** ponderar por filas de entrenamiento y por peso de diseño (Σ 1/π). Se adoptan solo si la diferencia pareada en el oro *dev* excluye el 0.
   * **M3 y M6** usan las estrellas de las filas de entrenamiento. Un texto con varias filas puede tener estrellas distintas; se entrena por fila o con etiqueta suave, y se documenta la elección.
4. **Particiones:**

   | Conjunto | Tamaño | Uso |
   | :--- | ---: | :--- |
   | Plata `entrenamiento` | 63 720 textos (90 396 filas), sin `NA` ni reseñas del oro | Entrenamiento. Hiperparámetros por validación cruzada de 5 particiones, agrupada por `clave` y estratificada por banco × periodo × clase |
   | Plata `holdout_nuevo` | 5 305 filas evaluables | Deriva temporal contra Gemini, ponderada por 1/π, y brecha por banco |
   | Oro *dev* aleatorio | 799: 199 de `gold_v0` (asistidas en la primera ronda, re-anotadas a ciegas) y 600 de `gold_v1` (desde 2026-10-19) | Comparación entre modelos y variantes, umbrales y calibración (5.6) |
   | Oro *dev* dirigido | 300 de `gold_v1`, sin π | Comparación en casos difíciles y `NEU`; nunca para cifras poblacionales |
   | Oro *test* | 601: 201 de `gold_v0` (siempre a ciegas) y 400 de `gold_v1` | **Una sola evaluación, en 5.8** |
   | Plata `holdout_visto` y calibración del oro (30) | — | No se usan para métricas |

   La primera ronda ya partió cada estrato banco × periodo a la mitad entre ciego y asistido, así que *dev* y *test* son muestras estratificadas y la partición estaba fijada antes de cualquier modelo. *Test* es el bloque más limpio: nunca vio una propuesta de Gemini.
5. **Métricas sobre el oro** (`metrics.py`), solo con textos evaluables y 3 clases:
   * **Principales:** macro-F1 y κ de Cohen. Se reportan sin ponderar (la muestra, comparable con los κ de 5.3) y ponderadas por 1/π (estimación poblacional).
   * **IC 95 %** por bootstrap estratificado por estrato (2 000 réplicas), y **diferencias pareadas** contra M0 y contra el mejor peldaño anterior.
   * **Secundarias:** precisión y recall de `NEG`, F1 por clase, exactitud en las filas donde las estrellas difieren del oro (detección de incongruencia), métricas por longitud y en texto visto y no visto, ECE.
   * **Límite de potencia:** el *dev* original tenía 7 `NEU`, así que el F1 de `NEU`, y con él el macro-F1, tenía mucha varianza. Con `gold_v1`, el *dev* aleatorio tiene 30 y el dirigido 75. κ y el F1 por clase se leen junto al macro-F1.
   * **Techo:** un modelo entrenado con la plata no puede medirse por encima del acuerdo de Gemini con el oro (κ 0.93 como cota superior).
6. **Brecha por banco y periodo:** el oro tiene ~40 reseñas por banco en *dev*, demasiado pocas. La brecha se mide en `holdout_nuevo` contra Gemini, ponderada, y se declara que hereda su sesgo.
7. **Costo y latencia:** segundos de ajuste, textos por segundo y memoria en el Mac M2 (8 GB medidos, CPU; MPS para encoders), tamaño del artefacto y costo por millón de textos. Kaggle T4 y Cloud Run CPU se miden solo para los finalistas (5.7).
8. **Regla de decisión:** un modelo más caro reemplaza a uno más barato solo si su diferencia pareada en κ o macro-F1 sobre el oro *dev* excluye el 0, o si iguala y el costo lo permite. El reporte final usa el oro *test* una vez, con PPI para las cifras poblacionales.
