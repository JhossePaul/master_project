# Reporte de 5.7: escala, ciclo de vida y monitoreo

> **Estado (2026-10-22): cerrado.** Decididos por el autor: P7-9 (umbrales de deriva por banco en `drift_policy`; política HITL global en `risk_policy`, sección 7) y P7-10 y P7-11 (reentrenamiento de M4 y revalidación de las familias, sección 8). Feature 5.7 de [`epic_5.md`](../../backlog/epic_5.md); plan en [`scale_design.md`](scale_design.md). Hecho: benchmark en el Mac y en Cloud Run (E1, E2), línea base histórica de deriva (E3), costo real de las familias con Gemini (P8-7), costo de la explicabilidad (P8-8), búsqueda vectorial en BigQuery (P8-6) y Vertex Model Registry (P7-3). Todos los recursos temporales en GCP se borraron. Después del cierre, en 5.8, se corrió el primer backfill de M4 en Kaggle (sección 9). Solo agregados. Índice: [`README.md`](../README.md).

## 1. Benchmark de inferencia de M4 (P7-1, P7-2)

M4 RoBERTuito (`M4_robertuito_s1_ppi`) en CPU, sobre 2 000 textos de `ppi_v0` ([`benchmark.py`](../../../experiments/analytics/src/voc_analytics/scale/benchmark.py)). Cada configuración corrió en su propio proceso. En Cloud Run, Jobs temporales con la imagen de prueba, borrados al terminar junto con la imagen.

| Entorno | Hilos | fp32 sin ordenar | fp32 ordenado por longitud | int8 ordenado | Memoria pico |
| :--- | :---: | ---: | ---: | ---: | ---: |
| Mac M2 (ARM) | 1 | 37 t/s | 143 t/s | 15 t/s | 1.1–1.5 GB |
| Mac M2 (ARM) | 4 | 51 t/s | 199 t/s | 80 t/s | 1.5–1.7 GB |
| Cloud Run, 1 vCPU, 2 GiB | 1 | 5.5 t/s | 22.6 t/s | 27.2 t/s | 1.2–1.4 GB |
| Cloud Run, 2 vCPU, 4 GiB | 1 | 6.5 t/s | 27.0 t/s | 55.0 t/s | 1.2–1.4 GB |
| Cloud Run, 2 vCPU, 4 GiB | 2 | 11.2 t/s | 46.0 t/s | 88.4 t/s | 1.2–1.4 GB |

* **Ordenar por longitud acelera ~4× en todos los entornos:** los lotes de textos de largo parecido casi no tienen relleno.
* **Cloud Run es ~6.5× más lento que el Mac** con 1 hilo.
* **int8 no pierde calidad** (κ 0.918 contra 0.912 en el oro *dev*; 99.75 % de acuerdo con fp32) y en x86 rinde: con 2 vCPU casi duplica a fp32. En ARM es más lento, porque el motor `qnnpack` no está optimizado para esto.
* **Memoria:** 1.2–1.4 GB de pico, así que **1 GiB no alcanza** (los Jobs actuales del proyecto usan 1 GiB).

| Trabajo | Kaggle T4 | Cloud Run, 1 vCPU, fp32 | Cloud Run, 2 vCPU, int8 |
| :--- | :--- | :--- | :--- |
| Backfill (1 383 138 textos únicos) | ~9 min | ~17 h | ~4.4 h |
| Delta diario (~500 textos únicos) | — | ~25 s | ~6 s |
| Re-scoring completo (P7-4) | ~9 min | ~17 h | ~4.4 h |

**Decisiones del autor y consecuencia:** el backfill y el *re-scoring* van en Kaggle con un pipeline desde GCP (P7-1, P7-4), y el delta diario en Cloud Run. Propuesta para P7-2: un Job de 1 vCPU y 2 GiB, en fp32 o int8.

## 2. Línea base histórica del monitor de deriva (E3, P7-6)

Series mensuales por banco con el snapshot completo, cada mes contra sus 12 previos ([`drift_baseline.py`](../../../experiments/analytics/src/voc_analytics/scale/drift_baseline.py), [métricas](drift_baseline_v0_metrics.json)). Un banco × mes entra con al menos 200 filas (30 en las muestras de predicción).

**Tasa de alerta por umbral** (proporción de banco × mes evaluables):

| Serie | Evaluables | z ≥ 3 | z ≥ 4 | z ≥ 5 |
| :--- | ---: | ---: | ---: | ---: |
| Palabras medias | 522 | 11.3 % | 6.9 % | 4.2 % |
| Textos de una palabra | 522 | 9.8 % | 5.4 % | 3.1 % |
| Textos de más de 60 palabras | 522 | 8.8 % | 5.0 % | 3.1 % |
| No predecibles | 522 | 4.8 % | 2.3 % | 1.2 % |
| Vocabulario fuera del entrenamiento | 522 | 6.9 % | 3.3 % | 1.7 % |
| `NEG` de Gemini (plata) | 487 | 9.7 % | 6.6 % | 3.5 % |
| `NEG` de M4 (`ppi_v0`) | 484 | 10.7 % | 6.6 % | 4.6 % |
| PSI de la distribución de palabras | 561 | — | PSI ≥ 0.1: 10.9 % | PSI ≥ 0.25: 2.0 % |

**El periodo de referencia lo marca el volumen de cada banco, no una fecha común** (respuesta a E3):

* las tasas de alerta son mucho más altas en los años de arranque: con z ≥ 4 en `NEG`, 38 % de los meses en 2017 y 24 % en 2019, contra 2–8 % desde 2020;
* cada banco se estabiliza en un año distinto: BBVA y BANORTE desde 2018 (más de ~3 500 filas por mes); SANTANDER y AZTECA desde 2019 (SANTANDER salta en 2018, con coeficiente de variación 2.9); NUBANK nunca se estabiliza (coeficiente de variación de 0.5 a 1.0), porque crece todo el tiempo;
* **propuesta:** que cada banco entre al monitor cuando tenga 12 meses seguidos con al menos 200 filas (regla, no fecha). Con esa regla, los meses de entrada son: AZTECA 2018-09, BANORTE 2018-10, BBVA 2016-04, NUBANK 2021-12, SANTANDER 2019-04. La entrada no coincide con la estabilidad del volumen (BBVA entra en 2016, aunque su volumen se estabiliza en 2018): la regla solo exige filas suficientes, y el z ya se ajusta a la variabilidad de cada banco.

**Meses de alerta por año, por banco y umbral** (desde el mes de entrada de cada banco; a pedido del autor, para ver si conviene un umbral por banco):

| Serie | Umbral | AZTECA | BANORTE | BBVA | NUBANK | SANTANDER |
| :--- | :---: | ---: | ---: | ---: | ---: | ---: |
| Palabras medias | z ≥ 3 | 1.1 | 1.8 | 1.6 | 0.6 | 1.5 |
| Palabras medias | z ≥ 4 | 0.6 | 1.1 | 1.0 | 0.4 | 1.1 |
| Palabras medias | z ≥ 5 | 0.4 | 0.8 | 0.5 | 0.2 | 0.8 |
| Textos de una palabra | z ≥ 3 | 1.2 | 1.1 | 1.5 | 0.2 | 1.1 |
| Textos de una palabra | z ≥ 4 | 0.7 | 0.8 | 0.9 | 0.0 | 0.5 |
| Textos de una palabra | z ≥ 5 | 0.2 | 0.4 | 0.7 | 0.0 | 0.4 |
| Más de 60 palabras | z ≥ 3 | 0.6 | 1.9 | 1.3 | 0.8 | 0.7 |
| Más de 60 palabras | z ≥ 4 | 0.1 | 1.4 | 0.8 | 0.4 | 0.4 |
| Más de 60 palabras | z ≥ 5 | 0.1 | 0.9 | 0.5 | 0.2 | 0.3 |
| No predecibles | z ≥ 3 | 0.2 | 0.5 | 1.0 | 0.2 | 0.3 |
| No predecibles | z ≥ 4 | 0.0 | 0.2 | 0.4 | 0.0 | 0.1 |
| No predecibles | z ≥ 5 | 0.0 | 0.0 | 0.1 | 0.0 | 0.0 |
| Vocabulario fuera del entrenamiento | z ≥ 3 | 0.6 | 0.8 | 1.6 | 0.0 | 0.3 |
| Vocabulario fuera del entrenamiento | z ≥ 4 | 0.5 | 0.1 | 0.8 | 0.0 | 0.0 |
| Vocabulario fuera del entrenamiento | z ≥ 5 | 0.2 | 0.0 | 0.6 | 0.0 | 0.0 |
| `NEG` (M4) | z ≥ 3 | 1.0 | 1.4 | 2.0 | 1.5 | 0.8 |
| `NEG` (M4) | z ≥ 4 | 0.8 | 0.8 | 1.1 | 0.6 | 0.8 |
| `NEG` (M4) | z ≥ 5 | 0.6 | 0.4 | 0.7 | 0.4 | 0.7 |
| `NEG` (Gemini) | z ≥ 3 | 1.3 | 1.0 | 1.4 | 0.8 | 1.3 |
| `NEG` (Gemini) | z ≥ 4 | 0.8 | 0.8 | 1.1 | 0.6 | 0.7 |
| `NEG` (Gemini) | z ≥ 5 | 0.1 | 0.8 | 0.7 | 0.0 | 0.4 |
| PSI de longitud | PSI ≥ 0.1 | 1.0 | 1.0 | 2.0 | 1.3 | 0.3 |
| PSI de longitud | PSI ≥ 0.25 | 0.1 | 0.4 | 0.3 | 0.4 | 0.0 |

* **El umbral es global, pero la escala es de cada banco:** el z se mide contra la mediana y la variabilidad del propio banco, así que el mismo umbral da tasas parecidas en los cinco. Con z ≥ 4, cada serie alerta entre 0 y 1.4 meses al año por banco.
* **Diferencias que sí aparecen:** NUBANK alerta menos (pocos meses evaluables y crecimiento constante); BANORTE alerta más en textos de más de 60 palabras (1.4 al año con z ≥ 4); BBVA alerta más en vocabulario nuevo y no predecibles, coherente con sus rediseños.
* **Las series no son independientes:** un mismo mes puede alertar en varias (en el rediseño de BBVA de 2025-10 alertaron la proporción de `NEG`, las reseñas de una palabra y el vocabulario). Por eso los meses con alguna alerta son menos que la suma de la tabla.

**En los incidentes de BBVA** (informativo; los umbrales de la señal de incidentes son de 5.9): la proporción de `NEG` sube a z de 3.1 a 6.1 con Gemini y de 3.6 a 4.3 con M4; en el rediseño de 2025-10, las reseñas de una palabra caen (z −6.9) y el vocabulario fuera del entrenamiento sube (z 5.4). La deriva de entrada también avisa de un cambio de producto.

## 3. Costo de las familias con Gemini (P8-7)

Las 39 635 negativas únicas de `ppi_v0` (M4), con `aspects_v2_1`, el mismo modelo y lotes de 5.5 ([`aspects_ppi.py`](../../../experiments/analytics/src/voc_analytics/scale/aspects_ppi.py), [métricas](aspects_cost_v0_metrics.json)):

* **Costo real:** $3.60 por 39 635 textos, **$0.091 por 1 000** (62 tokens de entrada y 11 de salida por texto); 2 lotes fallidos se reintentaron.
* **Proyección al corpus:** el 57 % de los textos únicos de la muestra son `NEG`, ~788 000 en el corpus: **~$72** con el precio introductorio vigente hasta el 2026-12-31. Es casi lo mismo que el backfill de sentimiento con M9.
* Las etiquetas quedan en `data/scale/aspects_ppi_v0/` para el análisis por versión de 5.9.

## 4. Costo de la explicabilidad en la cola HITL (P8-8)

Atribución por oclusión (una pasada por palabra) sobre 200 textos del 10 % de menor confianza de `ppi_v0`, que simulan la cola HITL ([`explain_cost.py`](../../../experiments/analytics/src/voc_analytics/scale/explain_cost.py), [métricas](explain_cost_v0_metrics.json)):

* esos textos tienen una mediana de 14 palabras (p90: 35), más largos que el corpus;
* en Cloud Run (1 vCPU, estimado con la razón medida Mac/Cloud Run de 6.5): **0.5 s por texto** (p90: 2.9 s);
* con ~350 textos por semana: **~9 min de CPU a la semana**, ~2 300 vCPU-s al mes, dentro del free tier (180 000).

**Lectura:** el costo de cómputo es despreciable si se precalcula en el Job de inferencia para los casos que entran a la cola y se guarda en `hitl_items.explanation`. No necesita un servicio aparte ni la meta de 150 ms. El costo real es de desarrollo: la pantalla del portal y sus pruebas.

## 5. Búsqueda semántica con `VECTOR_SEARCH` de BigQuery (P8-6)

Dataset temporal en `us-central1`, borrado al terminar ([`vector_search.py`](../../../experiments/analytics/src/voc_analytics/scale/vector_search.py), [métricas](vector_search_v0_metrics.json)). 5 consultas por configuración, `top_k` 20, coseno, con el vector de consulta como parámetro (como lo mandaría la API).

| Tabla | Filas | Tamaño | Sin índice | Con índice IVF |
| :--- | ---: | ---: | :--- | :--- |
| Sintética, del tamaño del corpus (384 dimensiones) | 1 383 138 | 4.26 GB | 8.9 s; 4.26 GB facturados | 6.6 s; 4.26 GB facturados (índice listo en 6 min) |
| Real: negativas de la plata (MiniLM) | 40 382 | 0.12 GB | 4.7 s; 0.12 GB | — |

* **Es viable, pero no es instantánea:** 5–9 s por búsqueda, no "sub-segundo" como suponía EPIC-7. Sirve para una exploración de causa raíz, no para un autocompletado.
* **El índice baja la latencia pero no la factura:** cada búsqueda cobra el tamaño de la columna de embeddings. Con 1 TB gratis al mes, alcanzan ~230 búsquedas sobre todo el corpus; más allá, centavos por búsqueda (por confirmar con el precio vigente).
* **Para abaratarla:** ver la sección 5.1; la única palanca que funciona bien es la partición por mes.
* **Los vecinos tienen sentido:** el 43 % comparte la familia principal del texto buscado, contra el 14 % de los pares al azar.
* **Primer intento descartado:** sacar el vector de consulta con una subconsulta sobre la misma tabla la escanea completa en cada búsqueda (con índice facturaba 8.6 GB). La API debe mandar el vector como parámetro.
* **Vertex Vector Search no se probó:** exige un índice desplegado siempre encendido, con costo fijo mensual (EPIC-2 lo estimaba en ~$150 al mes, sin verificar). Para el volumen de una tesis, BigQuery basta.

### 5.1 ¿Filtrar antes de buscar baja lo facturado? (2026-10-22)

A pedido del autor, que dudó de que ~230 búsquedas al mes cupieran en el free tier ([`vector_filter.py`](../../../experiments/analytics/src/voc_analytics/scale/vector_filter.py), [métricas](vector_filter_v0_metrics.json)). Tabla sintética del tamaño del corpus con banco, marca de negativa y mes; dos copias, una sin organizar y otra **particionada por mes y agrupada por banco y negativa**. 3 búsquedas por variante, sin índice. El dataset se borró al terminar.

| Variante | Sin organizar | Particionada y agrupada | Búsquedas por TiB (particionada) |
| :--- | ---: | ---: | ---: |
| Todo el corpus | 4.26 GB | 4.26 GB | 258 |
| Solo BBVA (30 % de las filas) | 4.27 GB | 3.75 GB | 294 |
| Solo negativas (57 %) | 4.26 GB | 4.24 GB | 260 |
| BBVA y negativas | 4.27 GB | 3.75 GB | 293 |
| Últimos 12 meses | 4.27 GB | **0.49 GB** | **2 248** |
| Tabla física aparte con solo negativas | — | 2.43 GB | 452 |

* **Sin particionar, filtrar no ahorra nada:** BigQuery lee la columna de embeddings completa y filtra después.
* **El agrupamiento casi no ayuda** (−12 % con un banco que es el 30 % de las filas): con particiones mensuales chicas, los bloques agrupados no se pueden descartar bien.
* **La partición por mes sí ahorra:** solo se leen los meses pedidos. Con los últimos 12 meses, ~2 200 búsquedas por TiB en la tabla sintética, donde los meses pesan igual; en el corpus real los últimos 12 meses (desde 2025-10) son el 12.7 % de las filas, así que serían ~2 000 búsquedas al mes.
* **Una tabla aparte de negativas** reduce a la mitad, pero es más lenta (16 s) y duplica el almacenamiento.
* **Consecuencia para el esquema:** `text_embeddings` (una fila por texto único, sin fecha) no se puede particionar. Para filtrar por periodo, el embedding tiene que vivir en una tabla con mes: por ejemplo, una fila por texto × banco × mes, particionada por mes. La duplicación es pequeña (un texto repetido en varios meses se guarda una vez por mes).

**Decisión del autor (2026-10-22), P8-6:** BigQuery con la tabla de embeddings particionada por mes, y la búsqueda acotada por defecto a una ventana de meses configurable (por ejemplo, 12). Así el free tier cubre ~2 000 búsquedas al mes. Buscar en todo el histórico sigue siendo posible, pero cuesta ~4.3 GB.

## 6. Vertex Model Registry (P7-3)

Registro de dos versiones de M4 (semillas 1 y 2) como un mismo modelo, promoción por alias y lectura desde el alias; todo se borró al terminar.

| Paso | Resultado |
| :--- | :--- |
| Subir los pesos a GCS (439 MB desde el Mac) | 1 306 s: lo limita la subida de la red doméstica; en producción los escribiría Kaggle o un Job |
| Registrar con el contenedor prediseñado de PyTorch | **Falla:** exige un `model.mar` (TorchServe) en la carpeta del modelo |
| Registrar con un contenedor propio declarado (no se despliega) | Funciona: ~160 s por versión |
| Segunda versión del mismo modelo (`--parent-model`) | Funciona; cada versión guarda su `artifactUri`, alias y etiquetas |
| Promover: mover el alias `produccion` a la versión 2 | 3 s (API `mergeVersionAliases`; `gcloud` no lo expone) |
| Resolver `modelo@produccion` y cargar los pesos desde su URI | Funciona (descarga de 218 MB en 171 s desde el Mac) |

**Ventajas sobre GCS versionado:** versiones y alias nativos (promoción y rollback con un cambio de alias), etiquetas y metadatos consultables, consola y trazabilidad, y el camino abierto a Vertex Batch Prediction o Endpoints si algún día se usan.

**Desventajas:** obliga a declarar un contenedor de *serving* aunque no se despliegue (el prediseñado pide un `.mar`; la salida práctica es una imagen propia mínima), la promoción por alias no está en `gcloud` (API REST o SDK), y cada registro tarda ~2–3 min. El costo del registro no se pudo confirmar en la página de precios durante el experimento; no hubo cargos visibles más allá del almacenamiento en GCS.

**Lectura:** no es "exageradamente más complicado" que GCS versionado. El costo extra es una imagen mínima de *serving* (o reutilizar la del Job de inferencia de EPIC-6) y un paso de promoción por API.


## 7. Propuesta de ciclo de vida y monitoreo (P7-3 a P7-9)

Con las decisiones del autor del 2026-10-22, esto es lo que EPIC-6 (6.2 a 6.4) implementa.

**Ciclo de vida de un modelo:**

1. **Candidato:** se ajusta en Kaggle (lote como `m4_ppi`) y guarda pesos fp16, tokenizador y predicciones del oro *dev*.
2. **Registro:** se sube a Vertex Model Registry como versión nueva, con alias `candidato`, la T de calibración, la curva HITL y las métricas en el oro *dev* como metadatos (`model_versions`).
3. **Promoción:** con la regla de 5.4 (diferencia pareada en el oro *dev* que excluye el 0, o empate a menor costo). Se mueve el alias `produccion` y se re-predice todo el histórico en Kaggle (P7-4), con `model_version` en cada predicción; las predicciones anteriores se conservan.
4. **Rollback:** se mueve el alias a la versión anterior; sus predicciones siguen en la tabla, así que no hace falta re-predecir.
5. **Política HITL:** al promover, se recalcula la curva de cobertura y riesgo y se propone el umbral equivalente a la cobertura vigente, como versión nueva de `risk_policy`.

**Monitoreo** (tabla `drift_metrics`, alertas en `incident_alerts`):

| Nivel | Series | Umbral (plantilla, P7-9) | Tasa histórica de alerta |
| :--- | :--- | :--- | :--- |
| Entrada | Palabras medias, textos de una palabra, de más de 60, no predecibles, vocabulario fuera del entrenamiento | z ≥ 4 contra los 12 meses previos | 2.3–6.9 % de los meses |
| Entrada | Distribución de longitud | PSI ≥ 0.25 | 2.0 % |
| Predicción | Proporción de `NEG` por banco | z ≥ 4 | 6.6 % |
| Familias y marca `u` | Proporción por banco y mes | La fija 5.9 (P9-1), en la `drift_policy` de cada banco | — |
| Concepto | Muestra humana periódica (P7-7) | Parámetro de la política | — |
| Tópicos | Re-ajuste trimestral con emparejamiento por centroides (P7-8) | Parámetro de la política | — |

* **Regla de entrada por banco (propuesta, E3):** un banco entra al monitor cuando tiene 12 meses seguidos con al menos 200 filas; no hay una fecha común.
* **Configuración por banco (decisión del autor, P7-9):** estos umbrales son la plantilla de la `drift_policy` de cada banco, que es una tabla aparte del apetito de riesgo HITL (`risk_policy`, global).
* **Subida automática de la revisión (P7-6):** una alerta de deriva de un banco crea una subida en `hitl_boosts`, solo para ese banco, con la cobertura, la duración y el tope de la `risk_policy` global; al terminar vuelve la cobertura base.

## 8. Desempeño de M4 y calidad de las familias (P7-10, P7-11)

**Umbrales aprobados por el autor (2026-10-22): los de 8.1 a 8.3 tal como se proponen en el registro (P7-10, P7-11).** Pedido del autor: vigilar también si el modelo empeora y cuándo reentrenar, y la calidad de las familias de Gemini, con mecanismos que ya existen y costo mínimo ([`model_monitor.py`](../../../experiments/analytics/src/voc_analytics/scale/model_monitor.py), [métricas](model_monitor_v0_metrics.json)). Ninguna medición llamó a un servicio.

### 8.1 κ de M4 en la muestra humana trimestral (señal principal de reentrenamiento)

Muestras aleatorias simuladas desde el oro *dev* aleatorio (remuestreo proporcional al peso de diseño); `M4_robertuito_s1_ppi`, κ poblacional en el *dev* 0.933.

| Revisiones por trimestre | IC 95 % del κ si el modelo no cambió | Percentil 5 |
| ---: | :--- | ---: |
| 100 | [0.85, 1.00] | 0.86 |
| 200 | [0.88, 0.98] | 0.89 |
| 300 | [0.89, 0.97] | 0.89 |
| 500 | [0.90, 0.96] | 0.90 |

* Con 100 revisiones el ruido (±0.08) tapa una caída de 0.05; **con 300 por trimestre** (±0.04) ya se distingue. Son ~23 por semana (~3 min a la semana con 8 s por revisión): la muestra `monitor_sample` de P7-7, dentro del HITL.

### 8.2 Señales baratas entre trimestres (avisan, no disparan solas)

| Señal | Línea base | Variación esperada | Costo |
| :--- | :--- | :--- | :--- |
| Tasa de corrección en la cola HITL (90 % de cobertura) | 24.9 % de los casos revisados son errores de M4 | ±2.3 puntos por semana (350 revisiones); límite 99 % en 4 semanas: 27.9 % | $0: ya es el HITL |
| Acuerdo M4–Gemini en `holdout_nuevo`, por mes | 96.9 % (rango mensual 95.3–98.6 %) | Con 500 textos por semana, ±0.8 puntos | ~$0.02 por semana (Gemini sobre 500 textos) |

* El acuerdo M4–Gemini bajó de 98.6 % (2026-04) a 95.3–96.1 % (2026-09 y 2026-10): es justo lo que esta señal quiere ver, y por ahora está dentro del rango.

### 8.3 Familias de Gemini: referencia para validar un cambio de modelo

κ autor–Gemini por familia en las 300 reseñas codificadas por el autor en 5.2 (`muestra_v21`), con IC por *bootstrap*:

| Familia | κ | IC 95 % | Prevalencia |
| :--- | ---: | :--- | ---: |
| AC | 0.70 | [0.60, 0.79] | 23 % |
| FA | 0.55 | [0.44, 0.66] | 17 % |
| UX | 0.74 | [0.62, 0.84] | 15 % |
| TR | 0.68 | [0.54, 0.80] | 13 % |
| PR | 0.62 | [0.47, 0.74] | 13 % |
| CO | 0.77 | [0.64, 0.87] | 13 % |
| LE | 0.86 | [0.74, 0.95] | 10 % |
| DV | 0.74 | [0.52, 0.89] | 7 % |
| AT | 0.68 | [0.48, 0.83] | 6 % |
| DI | 0.62 | [0.24, 0.87] | 2 % |
| OT | 0.00 | — | 0.3 % |

* Acuerdo exacto del conjunto de familias: 58.3 % [52.7, 64.0].
* Las familias de baja prevalencia (DI, OT) tienen intervalos demasiado anchos para juzgar un cambio; solo se vigilan las que tienen 5 % o más.
* Repetir el prompt sobre estas 300 reseñas cuesta ~$0.03.

## 9. Backfill de M4 en Kaggle (P7-1, 5.8, 2026-10-22)

Primer backfill con el pipeline que decidió el autor en P7-1. El riesgo de subir el corpus está aceptado en la FMEA (F-14). Código: [`scale/backfill.py`](../../../experiments/analytics/src/voc_analytics/scale/backfill.py); métricas: [`backfill_v0_metrics.json`](backfill_v0_metrics.json).

* **Pipeline:**
  1. `export`: `EXPORT DATA` de los textos únicos de `sanitized_reviews_tds` a `gs://voc-datalake-<proyecto>/backfill/20261022/` y descarga. Facturó 0.15 GB.
  2. `dataset`: dataset privado `voc-backfill-corpus` con los textos y los pesos de las 3 semillas `_ppi`.
  3. `kernel`: kernel privado `voc-backfill-m4` en la T4.
  4. `pull` y `check`: descarga y validación.
* **Qué viaja:** solo `texto_sanitizado`, su clave `text_key` (SHA-256 del texto, igual en BigQuery y en Python) y su número de filas.
* **Corrida:**
  * 1 429 675 textos únicos, que cubren las 2 653 238 filas del TDS, con reseñas hasta el 2026-10-20.
  * Las 3 semillas, sin textos faltantes, a ~4 000 textos/s: 346–357 s de GPU por semilla.
  * La preparación (`preprocess_tweet` y tokenización, en la CPU de Kaggle) tomó 27 min. En el Mac la misma preparación proyecta ~2 min, así que conviene paralelizarla o hacerla antes de subir.
* **Control:** sobre los 69 528 textos de `ppi_v0` que se pueden emparejar, las clases coinciden con las de 5.6 en el 99.99–100 % (diferencia máxima de probabilidad 0.012, fp16 en otra GPU).
* **Acuerdo entre semillas en el corpus:** 99.1 % por par, 98.6 % entre las tres.
* **Distribución por texto único** (`s1`): 46.3 % `NEG`, 1.9 % `NEU`, 51.8 % `POS`. Es por texto, no por reseña: los elogios breves se repiten mucho, así que por fila la proporción de `POS` es mayor.
* **Decisiones del autor (2026-10-22):**
  * **`M4_robertuito_s1_ppi` va a producción** (la semilla del monitoreo de 5.7; las tres son equivalentes en el oro *test*).
  * La carga a `review_predictions` (esquema v3, con la T de `s1` y las reglas de elegibilidad) se hace en EPIC-6 (6.2 y 6.3). Mientras tanto, las predicciones se conservan en local (`data/backfill/20261022/`, fuera de git) para 5.9.
  * El dataset del corpus en Kaggle se conserva hasta cerrar EPIC-5, por si hacen falta más corridas (por ejemplo, el backfill de tópicos), y se borra al cerrarla.
