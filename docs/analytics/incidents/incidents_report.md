# Reporte de 5.9: temas por día y versiones (descriptivo)

* **Estado (2026-10-22):** acotada a lo descriptivo por decisión del autor (§3). Hechos: la preparación (§0) y la comparación de ventanas como hallazgo exploratorio (§1). Hecho también el backfill de familias y tópicos (§2). Hechos también el top 5 diario de temas (§4) y los embeddings por texto para EPIC-6 (§2.3). Hecha también la vista por versión (§5) y la validación única de la cola HITL (§6). **5.9 cerrada (2026-10-23).** Plan en [`epic_5.md`, feature 5.9](../../backlog/epic_5.md#feature-59-temas-por-día-y-versiones-descriptivo).
* **Código:** [`voc_analytics.incidents`](../../../experiments/analytics/src/voc_analytics/incidents/). Las filas y las series quedan en `data/incidents/`, fuera de git; aquí solo van agregados.
* **Estrategia usada:** sentimiento con `M4_robertuito_s1_ppi` (P8-1), del backfill de 5.8; familias `aspects_v2_1` de Gemini (P8-7); reglas `eligibility_rules_v1`.

## 0. Preparación (tarea 0)

Código: [`incidents/prepare.py`](../../../experiments/analytics/src/voc_analytics/incidents/prepare.py); métricas: [`prepare_v0_metrics.json`](prepare_v0_metrics.json).

### 0.1 Unión con el backfill

* Snapshot `tds_20261016T054714Z`: 2 649 047 filas y 1 427 640 textos únicos.
* Solo 99 textos (99 filas) no tienen predicción en el backfill: la reseña cambió o desapareció entre el snapshot y la exportación del 2026-10-20. Se tratan como sin sentimiento.
* Con `eligibility_rules_v1`, cada fila queda así:

  | Banco | `NEG` | `NEU` | `POS` | Excluida |
  | :--- | ---: | ---: | ---: | ---: |
  | AZTECA | 16.0 % | 1.7 % | 80.4 % | 1.9 % |
  | BANORTE | 23.6 % | 1.4 % | 73.5 % | 1.5 % |
  | BBVA | 37.4 % | 1.6 % | 59.5 % | 1.5 % |
  | NUBANK | 24.2 % | 2.9 % | 71.4 % | 1.5 % |
  | SANTANDER | 27.4 % | 1.7 % | 69.4 % | 1.5 % |
  | **Total** | **26.9 %** | **1.7 %** | **69.8 %** | **1.6 %** |

* Son proporciones crudas por fila, como las series del monitor (P8-10); no son el KPI con PPI.
* **Negativas para familias** (`NEG` con dos palabras o más): 703 353 filas y **659 416 textos únicos**. El registro estimaba ~788 000 (P8-7); con el corpus medido, el backfill completo de familias costaría **~$60** ($0.091 por 1 000).

### 0.2 Familias y marca `u`: las dos muestras son comparables

* Se juntan las negativas con familias de la plata (`NEG` de Gemini) y de `ppi_v0` (`NEG` de M4), y se conservan solo las que también son negativas para familias con M4 `s1`:
  * plata: 41 594 de 42 573 filas (se pierden 979, que Gemini marcó `NEG` y M4 no); quedan 615 negativas de M4 sin familias;
  * `ppi_v0`: 41 145 de 41 843 filas; 3 negativas de M4 sin familias.
* Prevalencias ponderadas por 1 / π: la marca `u` es 17.4 % en la plata y 16.8 % en `ppi_v0`; ninguna familia difiere más de 2 puntos (`AC` 27.1 % contra 25.3 %). Por eso se juntan en una sola estimación por banco y mes.
* Juntas suman 82 739 filas, el **11.8 % de las negativas para familias**.

### 0.3 Series por banco y mes

* Los meses de entrada al monitor (regla de P7-9) coinciden con los de 5.7: BBVA 2016-04, AZTECA 2018-09, BANORTE 2018-10, SANTANDER 2019-04 y NUBANK 2021-12. Octubre de 2026 está incompleto y no se evalúa.
* Desde su mes de entrada, la muestra de la marca `u` por mes queda así:

  | Banco | Meses | Negativas en la muestra por mes (mediana) | Meses con ≥ 30 | Ancho del IC 95 % de `u` (mediana) |
  | :--- | ---: | ---: | ---: | ---: |
  | AZTECA | 97 | 114 | 94 | 11.8 pts |
  | BANORTE | 96 | 136 | 96 | 10.4 pts |
  | BBVA | 126 | 124 | 124 | 13.1 pts |
  | NUBANK | 58 | 192 | 57 | 7.1 pts |
  | SANTANDER | 90 | 141 | 90 | 8.2 pts |

* Con una prevalencia de `u` cercana al 17 %, un IC de 8 a 13 puntos solo distingue saltos grandes (del orden del doble). Para el volumen y la proporción de `NEG` no hay ese problema: salen del corpus completo.
* Meses con z robusto ≥ 4 (referencia de P7-9), por banco: en el volumen de `NEG`, de 3 (BANORTE) a 14 (BBVA); en la proporción de `NEG`, de 2 (NUBANK) a 10 (BBVA). El volumen alerta más porque sigue la tendencia del número de reseñas; la tarea 1 compara las dos series con la lista validada.

### 0.4 Evidencia para P9-3

* Con las muestras, la marca `u` y las familias por mes tienen IC de 7 a 13 puntos.
* El backfill completo de familias (~659 000 textos, ~$60, Gemini en Vertex AI dentro de GCP, cubierto por F-10) multiplica por ~8 las negativas con familias de cada mes y su resultado se reutiliza en 6.3. El autor lo autorizó (§2).

## 1. Ventana de la señal de incidentes (P9-1)

Código: [`incidents/signal.py`](../../../experiments/analytics/src/voc_analytics/incidents/signal.py); métricas: [`signal_v0_metrics.json`](signal_v0_metrics.json).

### 1.1 Lista externa del autor

* El autor reunió 107 incidentes confirmados por medios de México: BBVA 38, Santander 20, Banorte 19, NUBANK 17 y Azteca 13. Está en `data/incidents/external_v0.csv`, fuera de git; el JSON guarda su SHA-256.
* **No es exhaustiva** (falta revisar redes sociales), así que solo mide el **recall**. Una alerta que no está en la lista puede ser un incidente real; la precisión sale de la validación de los candidatos (tarea 1).
* Se evalúan 101: 5 son anteriores al mes de entrada de su banco y 1 es posterior al snapshot.
* **Sesgo de la lista:** los medios reportan sobre todo caídas de uno o dos días. Los problemas sostenidos (un rediseño, un bug gradual, un SPEI lento durante semanas) están casi ausentes.
* **Fechas imprecisas** (señalado por el autor):
  * la fecha del medio es la de publicación del reporte, no necesariamente la del incidente;
  * la fecha de la reseña es la de su última edición (límite 8 de la Model Card), y en los fallos de largo plazo, como el de una versión, las quejas se reparten durante semanas.
  * Por eso la §1.4 separa la tolerancia de la fecha del tamaño de la ventana.

### 1.2 Método

* **Señal:** suma de negativas de M4 `s1` en los `w` días que terminan en `t`, contra max(12, ⌈28 / w⌉) ventanas previas del mismo largo, sin traslape; z robusto (mediana y MAD). También el mes calendario, con el z de 12 meses de la tarea 0.
* **Detección:** un incidente del día `d` cuenta si hay una alerta en `[d, d + w]`.
* **Costo: porcentaje de días marcados**, la probabilidad de que un día cualquiera quede marcado con la misma regla. Se descartaron los episodios por año como medida de costo: con ventanas largas las alertas se juntan en pocos episodios de semanas y el presupuesto nunca limita, lo que hacía parecer mejores las ventanas de 10 a 30 días.
* **Umbral por banco**, como `drift_policy`: el menor z cuyo porcentaje de días marcados no pasa el presupuesto.

### 1.3 Resultado: la ventana de 1 día capta más incidentes

Recall sobre los 101 incidentes, al mismo costo:

| Ventana | ≤ 5 % de días marcados | ≤ 10 % | ≤ 20 % |
| :--- | ---: | ---: | ---: |
| **1 día** | **40.6 %** | **54.5 %** | **65.3 %** |
| 2 días | 36.6 % | 48.5 % | 57.4 % |
| 3 días | 32.7 % | 42.6 % | 54.5 % |
| 4 días | 29.7 % | 36.6 % | 52.5 % |
| 5 días | 19.8 % | 39.6 % | 49.5 % |
| 7 días | 16.8 % | 30.7 % | 41.6 % |
| 14 días | 10.9 % | 19.8 % | 33.7 % |
| 30 días | 6.9 % | 14.9 % | 29.7 % |
| Mes calendario | 6.9 % | 15.8 % | 27.7 % |

* El orden se repite en los cinco bancos, también en NUBANK, que tiene poco volumen (mediana de 13 negativas por día).
* Con el 10 % de días marcados, la ventana de 1 día usa un z de 2.75 a 3.25 según el banco y da de 10 a 13 episodios por año y banco. Con el 5 %, z de 3.75 a 5.75 y unos 6 episodios por año.
* La ventana larga capta problemas que la diaria no ve. Por ejemplo, el SPEI lento de NUBANK en octubre de 2023 no destaca el día del reporte (z −0.3), pero el mes completo da z 19.9. Esta lista no permite medir su recall: su valor se juzga con la validación del autor y con el antecedente de 5.5 (`DV` y `UX` avisaron del rediseño de BBVA un mes antes).

### 1.4 Sensibilidad a la imprecisión de las fechas

Un incidente cuenta si alguna ventana que termina en `[d − T, d + T + w − 1]` alerta, y el porcentaje de días marcados usa la misma zona. Recall con el 10 % de días marcados:

| Ventana | ±0 días | ±1 | ±3 | ±7 |
| :--- | ---: | ---: | ---: | ---: |
| **1 día** | **55.4 %** | **52.5 %** | **39.6 %** | **33.7 %** |
| 2 días | 49.5 % | 46.5 % | 37.6 % | 30.7 % |
| 3 días | 43.6 % | 39.6 % | 38.6 % | 31.7 % |
| 7 días | 30.7 % | 29.7 % | 25.7 % | 20.8 % |
| 14 días | 21.8 % | 19.8 % | 17.8 % | 16.8 % |
| 30 días | 14.9 % | 14.9 % | 14.9 % | 13.9 % |

* **La ventana de 1 día gana con cualquier tolerancia.** El recall baja al ampliar `T` porque una zona más ancha también marca más días al azar y obliga a subir el umbral.
* **Dónde cae el pico:** en 60 incidentes con un pico de z ≥ 4 entre `d − 7` y `d + 7`, el pico cae el día del reporte en 34 y al día siguiente en 8 (70 %); antes del reporte en 11 y de 2 a 7 días después en 9. En las caídas, la gente se queja el mismo día y los medios publican rápido.
* **Lo que no cubre:** los fallos de largo plazo de una versión. Esos los atienden la ventana larga y el análisis por versión (tarea 2), con los días desde el *release*.

### 1.5 Decisión del autor (2026-10-22), sujeta al backfill de familias y tópicos (P9-3)

> **Superada el mismo día (§3):** la detección de incidentes quedó fuera del alcance, así que esta decisión no se aplica. Se conserva como resultado exploratorio.

* **Señal principal:** ventana de 1 día, con umbral por banco. Los días de alerta seguidos forman un episodio.
* **Señal complementaria:** una ventana larga para problemas sostenidos. Falta elegir entre 30 días móviles y mes calendario; rinden parecido con la lista (14.9 % y 15.8 % con el 10 % de días marcados).
* **Costo:** porcentaje de días marcados, no episodios por año.
* **Pendiente:**
  * el presupuesto de días marcados (5, 10 o 20 %), que se fija con la validación de los candidatos;
  * controlar en la línea base el efecto de la quincena y del fin de semana;
  * repetir la comparación con la marca `u` y las familias cuando exista el backfill de familias y tópicos (P9-3).
* Las series diarias de las ventanas de 1 y 30 días quedan en `data/incidents/daily_v0.parquet` para armar los candidatos.

## 2. Backfill de familias y tópicos (P9-3)

Decisión del autor (2026-10-22): etiquetar todas las negativas, porque el dashboard necesita los temas por día y el llenado histórico (P8-7) hará falta de todos modos. Los artefactos se conservan por `text_key` en `data/backfill/20261022/`, fuera de git, para cargarlos en EPIC-6 (6.3).

### 2.1 Familias con Gemini

Código: [`incidents/backfill_aspects.py`](../../../experiments/analytics/src/voc_analytics/incidents/backfill_aspects.py); métricas: [`backfill_aspects_v0_metrics.json`](backfill_aspects_v0_metrics.json).

* **Textos:** las 659 416 negativas únicas del snapshot (`NEG` de M4 `s1` con dos palabras o más). Los textos que entraron después del snapshot quedan para el delta de EPIC-6.
* **Etiquetado:** mismo prompt (`aspects_v2_1`), modelo y lotes de 100 que 5.5 y 5.7, en Vertex AI dentro del proyecto (F-10). Se etiquetan también los ~80 000 textos que ya tenían etiqueta, para que el backfill salga de una sola corrida y para medir la reproducibilidad entre corridas.
* **Corrida:** 12 workers, ~1 h. 659 316 de 659 416 textos etiquetados; 47 lotes fallaron y se reintentaron. Un lote (100 textos, 0.015 %) falla siempre: Gemini omite un texto y, con temperatura 0, el error se repite. Queda pendiente para el delta de EPIC-6, con lotes más chicos.
* **Costo:** **$60.61**, $0.092 por 1 000 textos, igual a lo estimado en 5.7 (P8-7).
* **Prevalencias por texto único:**
  * marca `u` 17.7 % y `s` 2.7 %; sin familia 6.4 %; dos o más familias 27.3 %;
  * acceso (`AC`) 28.0 %, falla general (`FA`) 27.4 %, transferencias (`TR`) 14.4 %, productos (`PR`) 13.0 %, lentitud (`LE`) 9.7 %, usabilidad (`UX`) 9.2 %, compatibilidad, instalación y actualización (`CO`) 9.0 %, atención (`AT`) 9.0 %, dinero y cargos (`DI`) 2.9 %, diseño visual (`DV`) 1.5 % y sin familia (`OT`) 1.1 %.
  * Coinciden con las muestras de la tarea 0 (marca `u` 17.4 % y 16.8 %).
* **Reproducibilidad entre corridas** (mismo prompt y modelo, los textos ya etiquetados en 5.5 y 5.7):

  | Muestra | Textos | Acuerdo exacto de familias | Acuerdo en `u` | Acuerdo por familia |
  | :--- | ---: | ---: | ---: | :--- |
  | Plata (5.5) | 39 913 | 68.4 % | 96.6 % | de 90.2 % (`FA`) a 99.5 % (`DV`) |
  | `ppi_v0` (5.7) | 39 485 | 68.7 % | 96.4 % | de 90.1 % (`FA`) a 99.5 % (`DV`) |

  * Una de cada tres negativas cambia su conjunto exacto de familias entre corridas, casi siempre en una familia. `FA` y `AC` son las menos estables.
  * Para las etiquetas por día importa la proporción agregada, que es estable; la etiqueta de una reseña individual no es reproducible al 100 %, como ya mostró 5.5 (§4.5).

### 2.2 Tópicos con el modelo de 5.5 congelado

Código: [`incidents/backfill_topics.py`](../../../experiments/analytics/src/voc_analytics/incidents/backfill_topics.py); métricas: [`backfill_topics_v0_metrics.json`](backfill_topics_v0_metrics.json).

* **Cláusulas:** `clauses_v0`, como en 5.5: 1 035 052 segmentos, 1.57 por texto.
* **Embeddings:** MiniLM multilingüe en el Mac (14 min en MPS); el texto no sale del equipo (F-11).
* **Modelo:** se reajustó el de 5.5 (cláusulas, `min_cluster_size` 100, `min_samples` 10, UMAP con semilla 0) sobre los mismos 63 040 segmentos de la plata. **Reproduce el 100 % de los conjuntos de tópicos de las 40 382 negativas de 5.5**, así que los identificadores y la curación del autor (fase 4) siguen valiendo. Se guardó congelado (UMAP y BERTopic) para asignar sin cambiar identificadores (P7-8).
* **Asignación:** `transform` de UMAP y `approximate_predict` de HDBSCAN en 3 min. El 72.9 % de los textos tiene al menos un tópico (76 % en la plata de 5.5) y el 36.2 % de las cláusulas queda como ruido.
* **Provisional:** el descubrimiento de tópicos por ventana (por ejemplo, `topics_over_time` de BERTopic) queda como trabajo futuro con la detección de incidentes.

### 2.3 Embeddings por texto para la búsqueda semántica (P8-6)

Código: [`incidents/backfill_embeddings.py`](../../../experiments/analytics/src/voc_analytics/incidents/backfill_embeddings.py); métricas: [`backfill_embeddings_v0_metrics.json`](backfill_embeddings_v0_metrics.json).

* **Decisión del autor (2026-10-22):** calcularlos ahora para cargarlos en `text_embeddings` de EPIC-6, aunque no los use 5.9.
* **Textos:** los 1 429 675 textos únicos del export del backfill de M4, positivos incluidos, con su `text_key`.
* **Modelo:** MiniLM multilingüe de 384 dimensiones, tope de 128 tokens, el mismo de los tópicos y del experimento de `VECTOR_SEARCH` de 5.7. En el Mac (F-11): el texto no sale del equipo.
* **Resultado:** 1 429 675 textos × 384 dimensiones en 23 min en MPS (~1 040 textos/s); 2.2 GB en float32 (`emb_minilm.npy`, en el orden de `keys.parquet`). Comprobación: re-embeber tres textos al azar en CPU da coseno 1.0 con lo guardado.
* **Para EPIC-6:** `text_embeddings` se arma con estas filas por `text_key` y se replica por banco × mes al cargar (P8-6, tabla particionada por mes).

## 3. Alcance acotado a lo descriptivo (decisión del autor, 2026-10-22)

* **Qué cambia:** la detección de incidentes (series de tiempo, anomalías, umbrales y su validación, y el cruce con redes sociales) tiene metodología propia y supera el alcance de una tesis centrada en el sentimiento real del texto. Queda como trabajo futuro, con §1 como antecedente.
* **Qué queda en 5.9:**
  * el backfill de familias y tópicos (§2);
  * el **top 5 diario de temas** (P9-4, §4), para el *hover* del cockpit (7.5), de modo que el lector relacione temas con sentimiento;
  * la vista por versión, opcional y descriptiva (P9-2);
  * la validación única de la cola HITL, heredada de 5.6.
* **Consecuencias:** la Model Card (límite 7) declara que no hay detección de incidentes; F-19 pasa a cubrir la lectura de un pico como incidente confirmado; P9-1 queda fuera del alcance.

## 4. Top 5 diario de temas (P9-4)

Código: [`incidents/daily_topics.py`](../../../experiments/analytics/src/voc_analytics/incidents/daily_topics.py); métricas: [`daily_topics_v0_metrics.json`](daily_topics_v0_metrics.json).

* **Decisión del autor (2026-10-22):** algo sencillo, un top 5 diario, sin más trabajo metodológico sobre los tópicos.
* **Definición:** por banco y día, entre las reseñas negativas para familias del día:
  * las 5 **familias** `aspects_v2_1` con más reseñas, con el nombre de la guía `v2.1`;
  * los 5 **tópicos útiles** con más reseñas, con el nombre que les dio el autor. Son los 19 que juzgó útiles en 5.5: 11 de producto y 8 de ingeniería (coherencia ≥ 3). Los genéricos y el ruido no se muestran;
  * su **participación**: reseñas del día con ese tema entre las negativas del día. No suman 100 %, porque una reseña puede tener varios temas;
  * su **participación habitual** (agregada por decisión del autor, 2026-10-22): la del mismo tema en los 28 días previos del banco, sin el día. Es un dato al lado, sin umbral ni marca. Ejemplo: en la caída de BBVA del 2021-09-12, falla general (`FA`) tuvo el 75.2 % de las negativas, contra el 23.0 % habitual.
* **Para qué:** acompañar la serie diaria del cockpit (7.5), para que el lector relacione temas con sentimiento. Van las dos listas, familias y tópicos: las familias explican los días de caída (ese día ningún tópico útil pasó del 4 %) y los tópicos dan detalle en los días normales. La forma visual (*hover*, panel lateral u otra) se decide en 7.5. Es una descripción, no un diagnóstico ni una alerta (F-19).
* **Resultado:**
  * 19 343 días × banco con negativas; mediana de negativas por día de 10 (NUBANK) a 43 (BBVA);
  * el 41.2 % de las negativas tiene al menos un tópico útil, así que en muchos días el top de tópicos tiene menos de 5;
  * la familia en primer lugar es acceso (`AC`) en el 46.9 % de los días, falla general (`FA`) en el 22.4 % y lentitud (`LE`) en el 9.0 %; en BANORTE la más frecuente en primer lugar es `LE`.
* **Salida:** `data/incidents/daily_topics_v0.parquet` (fuera de git; los nombres de tópicos son del autor). En producción es la vista `daily_topic_labels` del [esquema v3](../../contracts/analytics_outputs_v3.md), que calcula 6.3.

## 5. Vista por versión de la app (P9-2)

Código: [`incidents/versions.py`](../../../experiments/analytics/src/voc_analytics/incidents/versions.py); métricas: [`versions_v0_metrics.json`](versions_v0_metrics.json).

* **Decisión del autor (2026-10-22):** mostrarla en el dashboard, porque los datos ya existen. Es descriptiva: sin pruebas de cambio de nivel.
* **Definición:** por banco y versión normalizada (`release`, `topics/versions.py`), la proporción cruda de `NEG` con IC de Wilson, la marca `u` y las 11 familias entre las negativas de la versión. Las versiones con menos de 50 reseñas se agrupan en `OTRAS`.
* **Cobertura:** el 90.9 % de las 2 607 016 reseñas con sentimiento tiene versión válida (el resto es `UNKNOWN` o beta).

| Banco | Versiones | Reseñas por versión (mediana) | `NEG` (mediana) | Marca `u` (mediana) |
| :--- | ---: | ---: | ---: | ---: |
| AZTECA | 225 | 1 866 | 15.2 % | 9.7 % |
| BANORTE | 30 | 10 659 | 19.1 % | 7.4 % |
| BBVA | 259 | 1 671 | 39.7 % | 18.5 % |
| NUBANK | 252 | 234 | 28.7 % | 5.8 % |
| SANTANDER | 176 | 2 011 | 28.6 % | 7.7 % |

* **Coherencia con lo conocido:** entre las versiones con 500 reseñas o más, las de mayor proporción de `NEG` coinciden con episodios conocidos. Es una observación descriptiva, no una prueba:
  * BBVA 25.100.15 (desde 2025-10-19): 87.8 % `NEG` y marca `u` en el 74.5 % de las negativas, el rediseño de octubre de 2025 que ya vio 5.5;
  * NUBANK 9.5.66 (desde 2023-10-05): 77.7 % `NEG`, el mes del SPEI lento que solo vio la ventana larga (§1.3);
  * NUBANK 9.33.46 (desde 2025-08-28): 62.1 % `NEG`, junto a la intermitencia del 2025-08-24 de la lista del autor.
* **Salida:** `data/incidents/versions_v0.parquet` (fuera de git). En producción la calcula el cockpit desde `version_app` de `review_predictions` y `review_aspects` (EPIC-7, 7.5).

## 6. Validación única de la cola HITL (heredada de 5.6)

Código: [`incidents/hitl_validation.py`](../../../experiments/analytics/src/voc_analytics/incidents/hitl_validation.py).

* **Por qué:** el umbral HITL (90 % de cobertura) se eligió con el oro *dev*. 5.6 dejó pendiente probarlo una vez con una semana real, para comprobar la carga de revisión y la tasa de corrección fuera del oro.
* **Decisiones del autor (2026-10-22):** se hace, en **modo ciego** (la app no muestra la predicción, para evitar el anclaje de +7 puntos medido en 5.3), con la **última semana completa** del snapshot.
* **Cola (lista):**
  * semana del 2026-10-05 al 2026-10-11: 2 839 textos únicos con sentimiento por modelo; se excluyen 3 que ya están en el oro;
  * `M4_robertuito_s1_ppi` con T = 1.68 y el umbral que da el 90 % de cobertura en el oro *dev* aleatorio: probabilidad máxima calibrada < 0.974 (en el *dev*, error en revisión 25.0 % y riesgo aceptado 0.42 %). Es el umbral que usaría producción;
  * **cola de 387 textos**: la cobertura real de la semana es **86.4 %**, no 90 %. La semana real tiene más casos dudosos que el *dev*, así que con el mismo umbral la cola crece de ~350 a 387;
  * por predicción: 172 `NEG`, 67 `NEU` y 148 `POS`; por banco, de 56 (NUBANK) a 104 (BBVA).
* **Cómo se revisa:** en la app local, con la misma guía `v2.2` del oro:

  ```
  GOLD_DIR=hitl_v0 uv run streamlit run src/voc_analytics/annotation/app.py
  ```

  La cola y las anotaciones quedan en `data/labels/hitl_v0/`, fuera de git.
* **Qué se mide al terminar** (`hitl_validation summary`): la tasa de corrección de la cola con su IC (5.7 esperaba 24.9 %; el aviso de P7-10 salta en 28 %), por clase predicha, y el tiempo real por reseña contra los 40–60 min estimados.
* **Resultado** (revisión del autor, 2026-10-23; métricas: [`hitl_validation_v0_metrics.json`](hitl_validation_v0_metrics.json)):
  * **tasa de corrección: 18.3 % [14.6, 22.6]** en 356 reseñas evaluables. Es menor que el 24.9 % esperado del *dev* (fuera del IC) y queda lejos del aviso de P7-10 (28 %);
  * **no evaluables:** 31 (8.0 % de la cola). La cola concentra los textos ininteligibles o sin relación, como se esperaba;
  * **por clase predicha:**

    | Predicción de M4 | Revisadas | Corregidas | Hacia |
    | :--- | ---: | ---: | :--- |
    | `NEG` | 166 | 9 (5.4 %) | 5 `NEU`, 4 `POS` |
    | `NEU` | 53 | 11 (20.8 %) | 9 `NEG`, 2 `POS` |
    | `POS` | 137 | 45 (32.8 %) | 30 `NEG`, 15 `NEU` |

    El error se concentra en lo predicho `POS` que en realidad es una queja: elogios con un problema (regla 2 de la guía), la debilidad conocida de 5.6. Lo predicho `NEG` casi no se corrige;
  * **por banco:** de 11.7 % (BANORTE, 9 de 77) a 25.0 % (SANTANDER, 20 de 80);
  * **tiempo:** mediana de 7.1 s por reseña y p90 de 30 s; **~80 min activos** para la cola (más 16 correcciones propias). Se excluyen 7 registros de más de 120 s, que son pausas (107 min). El plan de 5.6 estimaba 40–60 min para ~350 textos: la cola real fue más grande y más lenta.
* **Qué significa:**
  * el umbral del *dev* funciona en una semana real: la cola atrapa sobre todo los casos dudosos, y la revisión corrige uno de cada cinco;
  * la cobertura real (86.4 %) quedó debajo del 90 % objetivo, así que la carga semanal es ~10 % mayor que la estimada. EPIC-6 recalcula el umbral con cada modelo (6.4);
  * con una tasa base real de ~18 %, el aviso de P7-10 en 28 % queda holgado. Revisar ese umbral con la operación real es una propuesta para EPIC-6, no una decisión.
* **Límites:** una sola semana y un solo revisor (el autor, que escribió la guía); la tasa de corrección mide desacuerdo con M4, no error contra un oro de dos anotadores.

