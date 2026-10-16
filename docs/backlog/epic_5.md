# EPIC-5: Planteamiento Analítico y Experimentación del Core NLP

* **Estado:** Pendiente. Reemplaza la especificación anterior, que fijaba modelo, dependencias, tópicos y esquema de salida antes de tener evidencia. Esa especificación se conserva como borrador condicionado en [`epic_5_deployment.md`](epic_5_deployment.md) y solo se reescribe tras el registro de decisión (feature 5.8).
* **Fases:** (1) planteamiento analítico viable → (2) experimentación para elegir la estrategia de producción → (3) despliegue de la estrategia elegida (`epic_5_deployment.md`).
* **Semanas Objetivo:** Semanas 4 - 6 (fases 1 y 2).
* **Dependencias:** EPIC-1 a EPIC-4 cerradas ([cierre](closure_epics_1_4.md)). Corpus: `bbva_voc_tds.sanitized_reviews_tds`, **2 649 047 reseñas** de BBVA, NUBANK, SANTANDER, AZTECA y BANORTE (2011-04 a 2026-10), con `source_observed_at`. Bibliografía: [`references.md`](../governance/references.md).
* **Directorios:**
  * `experiments/analytics/`: proyecto `uv` **independiente del workspace** (su propio `pyproject.toml` y `uv.lock`), para que las dependencias de experimentación (scikit-learn, sentence-transformers, torch, peft, cleanlab, BERTopic, polars/duckdb, cliente de Gemini) no entren al lock de producción. Scripts y notebooks reproducibles, con semillas fijas.
  * `docs/analytics/`: reportes de cada experimento, guía de anotación y el registro de decisión (`decision_record.md`).
  * `docs/governance/`: Data Card y Model Card se completan con los resultados.

---

## 🎯 Objetivo y principios

Diseñar, con evidencia, el pipeline analítico que responde a cuatro preguntas del caso de uso, y elegir la estrategia de producción **antes** de escribir el paquete desplegable:

| Pregunta | Salida candidata | Feature |
| :--- | :--- | :---: |
| Q1. ¿Cuál es el sentimiento real del texto, separado de las estrellas? | Polaridad por reseña, score continuo y brecha frente a las estrellas (*Satisfaction Gap*) | 5.4 |
| Q2. ¿Qué temas recurrentes hay en las quejas y cómo cambian en el tiempo? | Tópicos dinámicos sobre las reseñas negativas, por banco y periodo | 5.5 |
| Q3. ¿Cómo detectamos rápido un incidente nuevo? | Señal de aparición o crecimiento de un tópico por banco y versión | 5.5 |
| Q4. ¿Qué atender primero? | Priorización que combine severidad, volumen y votos de utilidad | 5.6 |

Principios:

* **Ningún modelo, dependencia, tópico ni esquema de salida es definitivo** hasta el registro de decisión (5.8). RoBERTuito, Delora y los 8 `ABSATopic` de `voc-common` son **hipótesis** a evaluar, no requisitos.
* **Las estrellas son una etiqueta ruidosa del sentimiento del texto**, no la verdad. El sentimiento real nunca recibe las estrellas como entrada.
* **Calidad y costo se miden juntos:** con 2.65 M de reseñas, la velocidad y el costo de inferencia son criterio de selección al mismo nivel que la métrica de calidad.
* **Toda cifra de la literatura o de conversaciones con LLM es una hipótesis** hasta medirla sobre este corpus (ver `references.md`, columna *Verif.*).
* **Etiquetado humano limitado:** 1 000 reseñas como base y hasta 2 000 con esfuerzo extra. Nunca se etiqueta el corpus completo; las 2.65 M solo se predicen.

---

## 📊 Evidencia inicial (2026-10-16)

Consulta de longitudes por banco y año sobre `sanitized_reviews_tds` (palabras = tokens separados por espacios de `texto_limpio`):

| Banco | Filas | Textos únicos (cota) | 1 palabra | > 60 palabras | p99 por año | Máx. | Estrellas prom. | Antes de 2018 |
| :--- | ---: | ---: | ---: | ---: | :---: | ---: | ---: | ---: |
| BBVA | 787 875 | ≤ 65 % | 16.8 % | 2.4 % | 57–84 | 384 | 3.72 | 7.9 % |
| SANTANDER | 623 594 | ≤ 60 % | 18.2 % | 1.0 % | 52–87 | 625 | 4.03 | 0.9 % |
| AZTECA | 590 981 | ≤ 52 % | 21.9 % | 0.9 % | 50–88 | 655 | 4.40 | 0.2 % |
| BANORTE | 518 393 | ≤ 60 % | 17.5 % | 1.0 % | 51–87 | 297 | 4.25 | 2.6 % |
| NUBANK | 128 204 | ≤ 72 % | 14.7 % | 2.6 % | 30–100 | 114 | 4.21 | 0.0 % |
| **Total** | **2 649 047** | **≤ 1.60 M (60 %)** | **18.3 %** | **1.46 %** | **50–89** | **655** | | **3.1 %** |

Los textos únicos son la suma por banco y año: una **cota superior** del total deduplicado.

Implicaciones para el planteamiento:

* **Longitud:** el p99 por año está entre 50 y 89 palabras y solo 38 796 reseñas (1.46 %) superan 60. Un encoder de 512 tokens cubre prácticamente todo el corpus; el contexto largo no es un requisito. El rango 2–60 del EDA original ya **no filtra** en el TDS (EPIC-4 lo movió al análisis): su uso se decide en 5.2.
* **Textos de una palabra:** 484 829 (18.3 %; 21.9 % en AZTECA). Tienen sentimiento evaluable ("excelente", "pésima"), pero casi nunca un tema. La elegibilidad debe ser **por tarea** (sentimiento sí, tópico no), no un único filtro.
* **Deduplicación:** como mucho el 60 % de los textos es único, así que etiquetar y predecir sobre textos únicos ahorra al menos 40 % del costo. El EDA mide la cifra exacta (deduplicación global, no por año).
* **Deriva temporal evidente:** antes de 2018 las estrellas promedio rondan 2–3.5 y los textos son más largos. Desde 2019, AZTECA, BANORTE y SANTANDER suben a ~4.2–4.5 con medianas de 3–4 palabras, posible efecto de solicitudes de calificación dentro de la app. BBVA es el único que baja (3.2–3.7 en 2020 y 2024–2026). No se puede asumir una distribución estable ni una tasa de ruido única.
* **Concentración temporal:** el 97 % es de 2018 en adelante y el 31 % de 2024–2026. Muestreo y validación deben estratificar por periodo.
* **Límites heredados del cierre de EPIC-1–4:**
  * `fecha` es la de la **última edición** de la reseña, no la de creación.
  * La sanitización en producción es solo regex (Cloud DLP desactivado); queda PII residual posible (FMEA F-01/F-03).
  * Hay ~175 reseñas de NUBANK de 2015–2019, anteriores a su lanzamiento en México: decidir si se excluyen.
  * 8 textos vacíos.

---

## 📦 Features

### FEATURE 5.1: Planteamiento, Volumetría y Contrato Analítico

**Objetivo:** fijar qué se predice, sobre qué filas y con qué presupuesto, antes de experimentar.

1. **Definición de etiquetas de sentimiento** (guía de anotación, `docs/analytics/annotation_guideline.md`):
   * Clases candidatas: `NEG`, `NEU`, `POS`, con reglas explícitas para mezclas ("buena app pero no puedo transferir"), sarcasmo, quejas sobre el banco y no sobre la app, y textos sin opinión.
   * Decidir si existe una clase o marca `NO_EVALUABLE`, distinta de `NEU`.
   * Ejemplos por clase y por banco, revisados antes de etiquetar.
2. **Contrato de elegibilidad por tarea:** cada reseña recibe, por tarea (sentimiento, tópico), un estado `PREDICTABLE` o `NOT_PREDICTABLE` con motivo:

   | Motivo candidato | Criterio a definir en 5.2 |
   | :--- | :--- |
   | `EMPTY` | Texto vacío tras la limpieza |
   | `ONLY_TOKENS_OR_SYMBOLS` | Solo emojis, signos o tokens de sanitización (`[PERSON_NAME]`, …) |
   | `NOT_SPANISH` | Idioma distinto de español con confianza alta |
   | `TOO_SHORT_FOR_TOPIC` | Longitud insuficiente para asignar tema (umbral medido) |
   | `OUT_OF_SCOPE_PERIOD` | Por ejemplo, NUBANK anterior a su lanzamiento en México |

   Las reseñas no predecibles **se conservan y se reportan**; no se descartan.
3. **Envolvente de volumetría y costo:**
   * Backfill único sobre ≤ 1.60 M textos únicos y delta diario de cientos de reseñas.
   * Presupuesto máximo por fase: etiquetado con Gemini, cómputo de experimentos, backfill y operación diaria.
   * Cualquier estrategia que no quepa en la envolvente queda descartada, aunque gane en calidad.
4. **Borrador de las salidas de producción** (se cierra en 5.8):
   * predicción por reseña, versionada por modelo y corrida;
   * asignación de tópicos por periodo;
   * catálogo de tópicos con su ciclo de vida;
   * estado de elegibilidad;
   * registro de corridas.

   El esquema de 15 columnas de `delora_predictions` (EPIC-2) se revisa con esta evidencia.

### FEATURE 5.2: EDA Global y Pipeline de Limpieza

**Objetivo:** describir los 15 años y 5 bancos (no solo la muestra de 5 000 reseñas del último mes de BBVA) y decidir la limpieza y la elegibilidad.

* **Corpus local:** exportar `sanitized_reviews_tds` a Parquet (una sola lectura de BigQuery dentro del free tier) y analizarlo localmente con polars/duckdb.
* **Volumen y duplicados:** textos únicos globales, duplicados exactos y casi exactos (normalización de mayúsculas, espacios y repeticiones), y textos repetidos entre bancos.
* **Distribuciones por banco × año × `version_app`:**
  * longitud en palabras y tokens del tokenizador candidato;
  * estrellas y votos de utilidad;
  * idioma, emojis y tokens de sanitización;
  * códigos `ref:`.
* **Proxy de incongruencia:** en una muestra, comparar estrellas contra el sentimiento estimado (Gemini o un modelo sin ajuste) por banco y periodo, para dimensionar el ruido real. Esto reemplaza la cifra no verificada del 28.3 % (`references.md`, C4).
* **Multi-aspecto:** estimar qué fracción de reseñas negativas menciona más de un tema; esto informa la decisión ABSA vs tópicos (5.5).
* **Pipeline de limpieza:** evaluar `limpiar_texto_bancario` (minúsculas, URLs, repeticiones) frente al texto sanitizado sin limpiar, por cada familia de modelos (los transformers pueden preferir texto menos procesado). Decidir cómo tratar emojis, tokens de sanitización y códigos `ref:`.
* **Entregables:**
  * reporte `docs/analytics/eda_report.md`;
  * reglas de limpieza y elegibilidad versionadas;
  * Data Card actualizada.

### FEATURE 5.3: Estrategia de Etiquetado (Oro y Plata)

**Objetivo:** obtener etiquetas limpias suficientes para entrenar y, sobre todo, para evaluar sin sesgo, con 1 000–2 000 etiquetas humanas.

1. **Conjunto de plata (Gemini Flash):**
   * Muestra estratificada por banco × estrellas × periodo de **decenas de miles de textos únicos** (tamaño fijado por el presupuesto de 5.1), sobremuestreando 4 y 5 estrellas.
   * Eficiencia obligatoria:
     * deduplicar antes de enviar;
     * 50–100 reseñas por solicitud con una sola instrucción corta;
     * salida estructurada mínima (índice, etiqueta enum, confianza);
     * razonamiento (*thinking*) apagado o mínimo;
     * temperatura 0;
     * Batch API cuando la espera sea aceptable.
   * Antes de la corrida completa, un piloto de ~500 textos mide tokens reales, costo y acuerdo con humanos. Se fija un tope de gasto.
   * Versionar el prompt, el modelo exacto y la fecha. Las etiquetas de plata nunca se usan como verdad para reportar KPIs.
2. **Conjunto de oro (humano, 1 000 base / 2 000 con esfuerzo extra):**
   * **~40 % aleatorio estratificado** por banco × estrellas × periodo × longitud, con probabilidades de inclusión registradas. Es el único bloque válido para estimar métricas poblacionales e intervalos (*Prediction-Powered Inference*, Angelopoulos et al., 2023).
   * **~60 % dirigido:**
     * desacuerdos entre estrellas y Gemini (el sesgo de interés);
     * baja confianza de Gemini o desacuerdo entre Gemini y un modelo clásico;
     * cobertura de grupos de embeddings: temas raros, modismos, textos largos, solo tokens, códigos `ref:`.
   * **Anclaje:** el anotador ve la propuesta de Gemini. Una submuestra de **150–200 reseñas se etiqueta a ciegas** para medir el acuerdo con y sin ver la propuesta.
   * **Uso:** el oro se divide en *dev* (selección de hiperparámetros y umbrales) y *test* (reporte final, intocable hasta 5.8). Nunca entra al entrenamiento salvo, opcionalmente, una porción pequeña declarada como ancla limpia para Delora.
3. **Segunda ronda (*active learning*):** si el presupuesto humano llega a 2 000, las ~1 000 adicionales se eligen por incertidumbre del mejor modelo de la primera ronda.
4. **Métricas del etiquetado:**
   * acuerdo humano–Gemini (κ de Cohen);
   * acuerdo humano a ciegas vs con propuesta;
   * tasa de incongruencia estrellas–oro por banco y periodo.

### FEATURE 5.4: Competencia de Modelos de Sentimiento con Etiquetas Ruidosas

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

### FEATURE 5.5: Descubrimiento de Tópicos y Decisión sobre ABSA

**Objetivo:** decidir con evidencia si se necesita una taxonomía fija (ABSA), tópicos dinámicos o un híbrido, para Q2 y Q3.

* **Descubrimiento:** sobre las reseñas negativas elegibles para tópico, agrupar embeddings por periodo (estilo BERTopic: embeddings → reducción de dimensión → HDBSCAN → términos representativos por c-TF-IDF y nombre propuesto por un LLM).
* **Lectura temporal:** qué tópicos son estables, cuáles aparecen tras una versión concreta y cuáles desaparecen, por banco.
* **Validación humana:** revisión de los tópicos principales (coherencia, utilidad para producto) y contraste con la taxonomía hipotética de 8 `ABSATopic`.
* **Opciones a decidir:**

  | Opción | Ventaja | Riesgo |
  | :--- | :--- | :--- |
  | Taxonomía fija (ABSA ligero) | Estable, comparable en el tiempo, simple de reportar | No ve incidentes nuevos; envejece |
  | Tópicos dinámicos | Detecta temas nuevos sin reentrenar | Nombres e identidad cambian entre corridas; requiere curaduría |
  | Híbrido: núcleo estable + "emergentes" | Comparabilidad y detección de lo nuevo | Más complejidad operativa |

* **Detección de incidentes (Q3):** proponer una señal (aparición o crecimiento anómalo de un tópico por banco y versión) y probarla hacia atrás con los picos por versión que ya mostró el EDA.
* **Entregable:** recomendación con su costo de operación (frecuencia de re-clustering, curaduría humana, estabilidad de identificadores de tópico).

### FEATURE 5.6: Calibración, Incertidumbre, HITL y Priorización

* **Calibración:** *temperature scaling* (Guo et al., 2017) sobre el oro *dev*, antes de cualquier uso de probabilidades o entropía.
* **Umbral de revisión humana:** elegido por la curva cobertura–riesgo en el oro *dev* (qué fracción se envía a revisión frente al error que se evita), no fijado a priori en 0.65.
* **Priorización (Q4):** las fórmulas de `tnss_numeric_calibrated` y `priority_weight_score` de la especificación anterior son hipótesis. Se evalúan contra un criterio observable (por ejemplo, ordenar incidentes conocidos) antes de adoptarlas.

### FEATURE 5.7: Escala, Ciclo de Vida y Monitoreo

* **Benchmark de escala:** tiempo y costo del backfill sobre los textos únicos y del delta diario para los finalistas, aplicando deduplicación, orden por longitud y adaptadores fusionados.
* **Ciclo de vida de artefactos:** proponer el registro de versiones (GCS versionado o Vertex Model Registry), la Model Card por versión, la regla de promoción y rollback, y la política de **re-scoring** al cambiar de modelo (todo el histórico o solo lo nuevo).
* **Monitoreo (sin y con etiquetas):**

  | Nivel | Qué se mide | ¿Requiere etiquetas? |
  | :--- | :--- | :---: |
  | Entrada | Longitud, idioma, vocabulario nuevo, `version_app`, proporción de no predecibles | No |
  | Predicción | Proporción de `NEG` por banco y versión; confianza media | No |
  | Concepto | Desempeño sobre una muestra humana periódica pequeña | Sí |
  | Tópicos | Aparición y crecimiento de tópicos; esperado, no un fallo | No |

### FEATURE 5.8: Registro de Decisión

`docs/analytics/decision_record.md`, con la evidencia de 5.2–5.7. Fija:

* modelo de sentimiento, encoder y método de ruido (o su ausencia), con métricas del oro *test* e intervalos;
* estrategia de tópicos y detección de incidentes;
* reglas de limpieza y elegibilidad;
* esquema de las tablas de salida y migración desde `delora_predictions`;
* umbral HITL y priorización;
* plan de backfill, operación diaria, ciclo de vida y monitoreo;
* límites y riesgos para la Model Card y la FMEA.

Al aprobarlo se reescribe `epic_5_deployment.md` (fase 3) con las dependencias, tablas y pruebas que correspondan.

---

## 💻 Cómputo y presupuesto

| Tarea | Dónde | Costo esperado |
| :--- | :--- | :--- |
| EDA, deduplicación, muestreo y prototipos | Mac M2 16 GB (polars/duckdb, PyTorch MPS) | $0 |
| Etiquetas de plata y M9 | Vertex AI Gemini Flash (Batch API si aplica) | Unos dólares para decenas de miles de textos; se mide en el piloto |
| Ajuste de encoders y validación cruzada | Kaggle (~30 h/semana de GPU, no garantizadas) o Mac M2 | $0 |
| GPU dentro de GCP (opcional) | Pasar la cuenta de prueba a pago conserva los créditos y permite pedir cuota de GPU Spot (L4/T4) | Centavos por hora; la cuota puede tardar días |
| Backfill de 2.65 M | El entorno más barato que cumpla el benchmark de 5.7 | Se mide |
| Delta diario | Cloud Run Job en CPU (free tier: 180 000 vCPU-s/mes) | ~$0 si el modelo es ligero |

Las cifras de throughput, costo y duplicados de la literatura o de conversaciones con otros LLM no se usan para decidir hasta medirlas.

---

## ⚠️ Riesgos y limitaciones a declarar

* **Delora no está validado** en encoders de ~110 M ni con estrellas como etiqueta (`references.md`, §10). Su adopción depende de que supere a métodos baratos.
* **El ruido de las estrellas depende de la instancia y del periodo** (NoisyAG-News, 2024): los resultados con ruido sintético no transfieren.
* **Las etiquetas de plata heredan sesgos de Gemini** (sarcasmo, jerga bancaria mexicana); solo el oro sirve para reportar.
* **`fecha` es de última edición:** el análisis temporal mide cuándo se escribió la versión vigente, no la original.
* **Puede haber PII residual** por la sanitización solo con regex: no publicar ejemplos del corpus sin revisión.
* **Los tópicos dinámicos requieren curaduría humana continua;** sin ella pierden identidad entre corridas.

---

## ✅ Checklist de Aceptación de la Épica 5 (fases 1 y 2)

* [ ] Guía de anotación, contrato de elegibilidad por tarea y envolvente de costo aprobados (5.1).
* [ ] EDA global de los 5 bancos y 15 años, con reglas de limpieza versionadas y Data Card actualizada (5.2).
* [ ] Conjunto de plata con prompt, modelo y costo versionados; conjunto de oro con bloque aleatorio documentado y medición de anclaje (5.3).
* [ ] Al menos M0–M7 evaluados con el mismo protocolo; M8 y M9 evaluados o descartados con motivo (5.4).
* [ ] Decisión sobre ABSA, tópicos dinámicos o híbrido, con una señal de incidentes probada hacia atrás (5.5).
* [ ] Calibración y umbral HITL elegidos por cobertura–riesgo (5.6).
* [ ] Benchmark de escala, propuesta de ciclo de vida y plan de monitoreo (5.7).
* [ ] Registro de decisión aprobado y `epic_5_deployment.md` reescrito a partir de él (5.8).
* [ ] Experimentos reproducibles en `experiments/analytics/` (proyecto `uv` propio, semillas fijas), sin dependencias de experimentación en el `uv.lock` de producción.
