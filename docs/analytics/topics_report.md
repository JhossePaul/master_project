# Tópicos de las reseñas negativas (EPIC-5, feature 5.5)

> **Estado (2026-10-22): cerrada.** Fases 0 a 4 hechas, incluida la vía B a escala; recomendación aprobada por el autor con el agregado de la curaduría HITL en EPIC-6 (sección 5 y [nota para 5.8](topics_decision_note.md)). Plan aprobado: [`topics_design.md`](topics_design.md). Métricas: [`topics_working_v0_metrics.json`](topics_working_v0_metrics.json), [`topics_pilot_v0_metrics.json`](topics_pilot_v0_metrics.json) y [`topics_phase2_v0_metrics.json`](topics_phase2_v0_metrics.json). Solo agregados; los términos de cada tópico quedan en `data/topics/` (fuera de git) hasta la revisión del autor, porque la sanitización no detecta nombres (FMEA F-01). Este reporte nombra algunos tópicos con etiquetas descriptivas genéricas ("actualizaciones", "interfaz"), no con sus términos. Índice: [`README.md`](README.md).

## 1. Fase 0: conjunto de trabajo

[`working_set.py`](../../experiments/analytics/src/voc_analytics/topics/working_set.py), [`versions.py`](../../experiments/analytics/src/voc_analytics/topics/versions.py).

* **Fuente:** las filas `NEG` de la plata `silver_v0` (`prompt_v3`), sin backfill de sentimiento (el backfill es de 5.7, 5.8 y EPIC-6). La plata está estratificada por banco × periodo y cada fila pesa 1 / π.
* **Tamaño:** 42 573 filas, 40 382 textos únicos, que representan 706 197 filas negativas elegibles (igual que el EDA). Mediana de 18 palabras; p10 de 6.
* **Versiones:** normalización por banco (sufijos de compilación de BANORTE, fecha en el 3.er componente de BBVA 11.x, `-minApiNN` de NUBANK; `BETA` y `UNKNOWN` nulas). Sin versión utilizable: del 9 % (SANTANDER) al 17 % (NUBANK) de las filas. Versiones con 50 negativas o más en la muestra: de 19 (AZTECA) a 58 (BBVA), así que el análisis por versión con la plata es grueso.
* **Cómputo local** (MacBook Pro M2, 8 GB, MPS): embeddings de los 40 382 textos en 47 s (MiniLM) y 119 s (RoBERTuito); BERTopic sobre ~17 000 textos en ~6 s por configuración con UMAP precalculado. Menos de 1.3 GB de RAM.

## 2. Fase 1: piloto en BBVA y NUBANK

[`pilot.py`](../../experiments/analytics/src/voc_analytics/topics/pilot.py). ~17 000 textos `NEG` únicos. UMAP 5d (15 vecinos, coseno) con 3 semillas; HDBSCAN `min_cluster_size` ∈ {25, 50, 100} × `min_samples` ∈ {5, 10, igual}; c-TF-IDF de unigramas y bigramas sin acentos, con las negaciones fuera de las stopwords. La alineación con familias usa los textos codificados en 5.2 (`aspects_v1` y `aspects_v2` provisional) ponderados por número de extracciones.

### 2.1 Embeddings: MiniLM sí, RoBERTuito base no

| Embedding, configuración | Tópicos | Ruido | NPMI | Pureza `v2` | NMI `v2` | ARI entre semillas |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| MiniLM, 25 / 5 | 117 | 40 % | 0.10 | 0.72 | 0.42 | 0.84 |
| **MiniLM, 50 / 10** | **55** | **37 %** | **0.12** | **0.62** | **0.38** | **0.71** |
| MiniLM, 100 / 5 | 27 | 28 % | 0.12 | 0.51 | 0.28 | 0.97 |
| MiniLM, 50 / igual; 100 / 10 o igual | 5–8 | 0–2 % | 0.11–0.13 | 0.37 | 0.07 | variable |
| RoBERTuito base, cualquiera | 2–5 | 0–1 % | 0.03–0.28 | 0.36 | 0.05–0.06 | ≈ 1 |

* **RoBERTuito base se descarta para agrupar:** colapsa en 2–5 grupos con cualquier configuración. Es un encoder de lenguaje enmascarado sin entrenamiento de similitud de oraciones; su NPMI alta refleja tópicos demasiado generales.
* **Varias configuraciones de MiniLM colapsan** en 5–8 tópicos gigantes (selección `eom` de HDBSCAN cerca de la raíz). Se descartan.
* **Elegida para la fase 2: MiniLM, 50 / 10** (escalada al número de textos). 100 / 5 es más estable entre semillas, pero colapsa a 8 y 4 tópicos en dos puntos del barrido de la sección 2.3; 50 / 10 no colapsa en ninguno.

### 2.2 El ruido está en las reseñas largas

Con 50 / 10, el ruido es del 34 % en las de 1–5 palabras y sube al 39 % en las de más de 40; con 100 / 5, del 10 % al 36 %. Tras quitar las de 2 palabras o menos, las de 41+ llegan a 41 %. `reduce_outliers` (c-TF-IDF, umbral 0.1) baja el ruido a 19–26 %. Es coherente con el multi-aspecto (5.2: 46–51 % en las de 20+ palabras): una reseña larga con varios problemas no cae en un solo grupo. **Siguiente paso: segmentar por cláusula u oración** (`topics_design.md` §4.1) antes de seguir afinando HDBSCAN.

### 2.3 `TOPIC_TOO_SHORT`: la premisa de 5.2 no se sostiene

Las negativas cortas **sí** nombran problemas concretos. Lo que casi nunca tienen es más de uno. Sobre las 1 500 extracciones de 5.2 (5 bancos):

| Palabras | n | Con problema concreto (`v1` / `v2`) | Multi-aspecto (`v1` / `v2`) |
| :--- | ---: | :--- | :--- |
| 1 | 28 | 4 % / 4 % | 0 % / 0 % |
| 2 | 50 | 50 % / 48 % | 0 % / 0 % |
| 3–5 | 146 | 81 % / 77 % | 3 % / 4 % |
| 6–10 | 265 | 91 % / 86 % | 13 % / 9 % |

"Las de 1 a 5 palabras casi nunca nombran un problema concreto" (EDA, `epic_5.md`, `eligibility_rules.md`) confunde "multi-aspecto 0–2 %" con "sin problema". "no abre" es corta y concreta.

Barrido en el piloto (MiniLM 50 / 10, re-ajustando sin las reseñas de k palabras o menos):

| k | Filas `NEG` excluidas | De ellas, con problema (`v2`) | Tópicos | Ruido | NPMI | Pureza `v2` |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 0 % | — | 55 | 37 % | 0.115 | 0.62 |
| 2 | 3 % | 20 % (n = 16) | 41 | 30 % | 0.129 | 0.56 |
| 3 | 5 % | 34 % (n = 30) | 51 | 37 % | 0.114 | 0.61 |
| 5 | 11 % | 57 % (n = 69) | 44 | 43 % | 0.129 | 0.63 |
| 6 | 14 % | 60 % (n = 89) | 52 | 40 % | 0.127 | 0.63 |
| 10 | 25 % | 74 % (n = 169) | 35 | 38 % | 0.117 | 0.61 |

* Excluir reseñas cortas **no mejora** la calidad de los tópicos (NPMI de 0.115 a 0.13 como máximo; la pureza no sube) y **pierde quejas concretas**: con k = 5 se va el 11 % de las negativas y más de la mitad de ellas nombra un problema.
* **Recomendación provisional: k = 1** (solo las de una palabra, que coinciden con `TNSS_SINGLE_WORD`), o k = 2 como máximo. *Confirmada con `v2.1` y decidida por el autor el 2026-10-22 (sección 4.3).* Se refuta la hipótesis k ≈ 5–6 del plan. Se confirma en la fase 2 con los 5 bancos; n es chico y `aspects_v2` es provisional.

## 3. Fase 2: unidad de análisis, lectura temporal y señal (5 bancos)

[`units.py`](../../experiments/analytics/src/voc_analytics/topics/units.py), [`dynamics.py`](../../experiments/analytics/src/voc_analytics/topics/dynamics.py). Los 40 382 textos `NEG` de la plata; MiniLM; HDBSCAN con `min_samples` 10. Referencia: `aspects_v2` provisional (27 % multi-aspecto en los textos codificados).

### 3.1 Ninguna unidad recupera el multi-aspecto

Tres unidades: la reseña completa (un tópico); cláusulas (`clauses_v0`: cortes por puntuación y conectores como "pero", "además", "aparte"; 63 040 segmentos, 1.56 por reseña), donde la reseña toma los tópicos de sus segmentos; y la distribución de tópicos de la reseña (`approximate_distribution`, tópicos con p ≥ umbral). Cada tópico se mapea a la familia mayoritaria de los textos codificados que lo contienen, con validación cruzada de 5 particiones.

| Unidad (`min_cluster_size`) | Tópicos | Cobertura | F1 de familias | Multi-aspecto predicho | κ multi-aspecto |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Reseña completa (100) | 57 | 63 % | 0.36 | 0 % | 0.00 |
| Distribución, p ≥ 0.15 (100) | 57 | 64 % | 0.42 | 21 % | 0.10 |
| Distribución, p ≥ 0.30 (100) | 57 | 42 % | 0.28 | 2 % | 0.00 |
| **Cláusulas (100)** | **97** | **76 %** | **0.44** | **13 %** | **0.14** |
| Cláusulas (150) | 70 | 79 % | 0.42 | 14 % | 0.16 |

Con `min_cluster_size` 50 los resultados son parecidos (F1 0.38–0.43). Las cláusulas suben la cobertura y algo el F1, pero **ninguna unidad recupera el multi-aspecto** (κ ≤ 0.16 contra 27 % codificado). Los tópicos no supervisados no sustituyen a una clasificación multi-etiqueta por familias: es el argumento empírico para no usar solo tópicos dinámicos (`topics_design.md` §4.4). Limitaciones: el segmentador no corta en una "y" suelta, el mapeo da una sola familia por tópico y `aspects_v2` está sin validar.

Variante elegida para la lectura temporal: **cláusulas, 100**.

### 3.2 Lectura temporal e hipótesis

* **Persistencia** (197 trimestres × banco con 30 filas o más; un tópico está presente si supera el 1 %): 16 tópicos estables (en ≥ 50 % de los trimestres), 61 intermitentes y 20 raros.
* **H-T1 (token físico y wallet antes de 2018): no se confirma.** El único tópico de token es el "Súper Token" de SANTANDER (un token en la app), con 2–3 % de sus negativas en todas las etapas; en los demás bancos, ≤ 0.8 %. No aparece ningún tópico de wallet. Antes de 2018 la plata tiene pocas filas (174–942 por banco), así que la ausencia es débil.
* **H-T2 (crece la biometría y el alta digital desde 2019): solo en BBVA, y no crece de forma sostenida.** Los tópicos de reconocimiento facial, huella y datos biométricos pesan el 8.4 % de las negativas de BBVA en 2018–2020 y el 11.5 % en 2021–2023, y bajan al 3.0 % desde 2024; en los demás bancos, ≤ 1.2 % (salvo AZTECA antes de 2018, 3.1 % con 174 filas). El alta o registro digital pesa más en NUBANK (2.5 % en 2020, 0.7 % desde 2024).
* **H-T3 (NUBANK con tópicos propios; confusión con el portugués): se refuta.** Ningún tópico concentra el 80 % o más de su peso en NUBANK (3 en BBVA, 1 en SANTANDER), y ningún tópico tiene marcas de portugués, como anticipaba H8.

La identificación de tópicos por patrones en sus 3 primeros términos es gruesa; la revisión humana de la fase 4 la confirma o corrige.

### 3.3 Señal de incidentes por mes: detecta y explica, pero con muchas falsas alarmas

z robusto de la proporción mensual de cada tópico contra la mediana y la MAD de los 12 meses previos (6 como mínimo); alerta con z ≥ 3 y al menos 10 filas del tópico en el mes. Hay 632 meses × banco evaluables.

| Incidente | Tópicos en alerta | En el mes previo | z del volumen `NEG` (mes / previo) |
| :--- | ---: | ---: | :--- |
| BBVA 2024-07 | 1 (actualizaciones, z 7.4) | 2 (actualizaciones, lentitud) | 19.4 / 11.7 |
| BBVA 2025-10 | 3 (actualizaciones; interfaz; diseño, colores y adultos mayores) | 0 | 12.4 / 1.4 |
| BBVA 2025-11 | 2 (interfaz; diseño y colores) | 3 | 5.7 / 12.4 |

* **Detecta los tres incidentes**, y en 2024-07 avisa un mes antes; pero el volumen de negativas también los detecta y también avisa antes en 2024-07.
* **Lo que agrega es el qué:** 2024-07 es una actualización; 2025-10 es un rediseño, y separa diseño visual (colores, adultos mayores) de usabilidad (interfaz poco intuitiva), lo que respalda la separación `DV` / `UX` de la guía `v2`.
* **Falsas alarmas:** el 11 % de los demás meses × banco tiene al menos una alerta (68 de 629), y 76 meses tienen alerta de volumen. Sin una lista de incidentes etiquetados no se sabe cuántas son reales. Con la plata (mediana de 57 filas por banco y mes) la señal es ilustrativa; los umbrales operativos se calibran en 5.7.

### 3.4 Versiones: la plata no alcanza

La divergencia de Jensen-Shannon entre versiones consecutivas con 50 filas o más tiene una mediana de 0.17 (BANORTE) a 0.34 (AZTECA) y un p90 de 0.28 a 0.44. Con tan pocas filas por versión domina el ruido de muestreo y no se distinguen las regresiones. El análisis por versión necesita más filas que las de la plata: queda para 5.7.

## 4. Fase 3 sin Gemini: contraste con `aspects_v2_1`

`dynamics.py ab` y `pilot.py short --banks todos`. Referencia: la taxonomía `v2.1` validada por el autor (11 familias; `FQ` fusionada en `UX`; 24.7 % multi-aspecto), sobre las 1 500 extracciones de 5.2 (1 434 textos). Sin llamadas nuevas a Gemini.

### 4.1 La comparación de unidades no cambia con `v2.1`

Las cifras de la sección 3.1 se mantienen: cláusulas (100) con 76 % de cobertura, F1 de familias 0.43, multi-aspecto predicho 13 % contra 25 % codificado y κ 0.15; ninguna variante pasa de κ 0.17.

### 4.2 Tópicos (vía A) contra familias (vía B)

**Techo de la comparación:** las familias de referencia son etiquetas de Gemini, no del autor. El F1 de cada familia está acotado por el acuerdo autor–Gemini de esa familia (EDA §5.2.1): `FA`, la familia más frecuente, tiene κ 0.55; `LE`, 0.86. Además, con `v2.1` Gemini marca más multi-aspecto que el autor (30 % contra 23 % en la muestra), así que el 25 % de referencia es una cota superior y la brecha de los tópicos (13 % predicho) es algo menor que la que se ve.

F1 por familia con el mapeo tópico → familia cruzado (cláusulas, 100):

| Familia | Soporte | F1 | | Familia | Soporte | F1 |
| :--- | ---: | ---: | :--- | :--- | ---: | ---: |
| `LE` lentitud | 159 | 0.69 | | `CO` compatibilidad | 119 | 0.23 |
| `AC` acceso | 366 | 0.52 | | `AT` atención | 121 | 0.19 |
| `TR` transferencias | 206 | 0.50 | | `DV` diseño visual | 27 | 0.07 |
| `FA` falla general | 443 | 0.47 | | `DI` dinero y cargos | 40 | 0.00 |
| `PR` productos | 172 | 0.37 | | `OT` otro | 9 | 0.00 |
| `UX` usabilidad | 124 | 0.25 | | | | |

* **Los tópicos reproducen las familias operativas y concretas** (lentitud, acceso, transferencias, falla), con F1 de 0.47 a 0.69, y **no las relacionales o poco frecuentes** (atención, compatibilidad, diseño visual, dinero y cargos), con F1 ≤ 0.25. La reseña completa queda por debajo de las cláusulas en casi todas.
* **Pureza** (47 tópicos con 10 extracciones o más): 18 con pureza ≥ 0.7, 7 entre 0.5 y 0.7, y 22 por debajo de 0.5. Ninguna familia `DI`, `DV` u `OT` es la mayoritaria de algún tópico; 5 tópicos tienen mayoría "sin problema concreto".
* **Tópicos no alineados con una familia** (mayoría "sin problema" u `OT`, o pureza < 0.5): 24 tópicos, presentes en el 42 % de las filas `NEG` ponderadas. Son la reserva de "emergentes" del híbrido, pero en su mayoría son tópicos mezclados, no temas nuevos: separar unos de otros es trabajo de la revisión humana (fase 4).
* **`OT` no sirve como alarma de temas nuevos:** es el 0.6 % de las negativas y su κ autor–Gemini es 0 con `v2.1`. En el híbrido, la detección de lo nuevo le toca a la vía A (tópicos no alineados y su crecimiento), no a la prevalencia de `OT`.
* **Diseño visual:** `DV` es raro (1.8 %) y ningún tópico lo agrupa en general, pero en el incidente de BBVA 2025-10 aparece un tópico propio de diseño (sección 3.3). Las familias miden su nivel; los tópicos detectan su pico.

### 4.3 `TOPIC_TOO_SHORT`: k = 1 se confirma con `v2.1` y los 5 bancos

Proporción con problema concreto por largo (`v2.1`, 1 500 extracciones, IC de Wilson): 1 palabra, 4 % [1, 18]; 2 palabras, 46 % [33, 60]; 3 a 5, 77 % [70, 83]; 6 a 10, 86 % [81, 90]; 11 o más, 98 %.

Barrido con los 5 bancos (MiniLM, `min_cluster_size` 100, `min_samples` 10, re-ajustando sin las reseñas de k palabras o menos):

| k | Filas `NEG` excluidas | De ellas, con problema | Tópicos | Ruido | NPMI | Pureza `v2.1` |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 0 % | — | 57 | 37 % | 0.121 | 0.65 |
| 2 | 5 % | 31 % (n = 47) | 59 | 36 % | 0.127 | 0.64 |
| 3 | 7 % | 41 % (n = 85) | 53 | 37 % | 0.112 | 0.62 |
| 5 | 14 % | 61 % (n = 186) | 48 | 39 % | 0.125 | 0.62 |
| 6 | 18 % | 66 % (n = 240) | 45 | 38 % | 0.122 | 0.59 |
| 10 | 31 % | 75 % (n = 446) | 38 | 43 % | 0.115 | 0.60 |

Excluir reseñas cortas no mejora la coherencia ni la pureza, y pierde quejas concretas.

Volumen en el corpus (filas `NEG` elegibles estimadas con la plata ponderada, ~706 000; ~636 000 nombran un problema concreto):

| k | Negativas excluidas | Quejas concretas perdidas |
| ---: | :--- | :--- |
| 1 | 11 600 (1.6 %) | ~400 (0.1 %); en el peor caso del IC, ~2 100 (0.3 %) |
| 2 | 33 000 (4.7 %) | ~10 200 (1.6 %) |
| 3 | 52 900 (7.5 %) | ~21 800 (3.4 %) |
| 5 | 101 900 (14.4 %) | ~62 300 (9.8 %) |

**Decisión del autor (2026-10-22): `TOPIC_TOO_SHORT` con k = 1.** Quedan fuera del análisis de tópicos y familias solo las negativas de una palabra ("mala", "pésima", "horrible"), que se solapan con `TNSS_SINGLE_WORD`; siguen contando en los agregados de sentimiento. La regla la registra Datos y EDA en `eligibility_rules.md`.

### 4.4 H-T4: la marca `u` sube tras cada versión y en los incidentes (se confirma)

Proporción de negativas con la marca `u` (problema atribuido a una actualización; κ autor–Gemini 0.70) según los días desde la última versión de su banco:

| Días desde la versión | n | `u` | IC 95 % |
| :--- | ---: | ---: | :--- |
| 0–3 | 343 | 13 % | 10–17 |
| 4–7 | 317 | 21 % | 17–26 |
| 8–14 | 334 | 22 % | 18–27 |
| 15–30 | 327 | 13 % | 10–18 |
| 31 o más | 179 | 7 % | 4–12 |

* La marca sube entre los días 4 y 14 y baja después: es compatible con la adopción gradual de cada versión, que tarda unos días.
* **En los meses de incidente de BBVA, el 61 % [50, 72] de las negativas tiene la marca `u`, contra el 14 % [12, 16] del resto.** Es la señal por familia más fuerte que tenemos para Q3, y viene de la vía B.

### 4.5 Vía B a escala: las 40 382 negativas de la plata codificadas

[`aspects_scale.py`](../../experiments/analytics/src/voc_analytics/topics/aspects_scale.py) → [`topics_aspects_scale_v0_metrics.json`](topics_aspects_scale_v0_metrics.json). Aprobada por el autor el 2026-10-22. Gemini (`gemini-3.6-flash`, Vertex AI dentro de GCP) con el prompt `aspects_v2_1` de 5.2, sin cambios.

* **Corrida:** 404 lotes de 100 textos. Tres lotes fallaron porque Gemini omitió líneas y se completaron con `--solo-faltantes`. **Costo real: $3.64**, incluidos los intentos fallidos (estimado: $3.80).
* **Proporciones poblacionales** (filas `NEG` ponderadas por 1 / π, ~706 000): multi-aspecto 24.7 % (igual que 5.2), sin problema concreto 9.5 %, marca `u` 17.0 %. Familias: `FA` 27.2 %, `AC` 26.5 %, `TR` 13.6 %, `PR` 12.1 %, `LE` 10.1 %, `CO` 8.6 %, `AT` 8.4 %, `UX` 7.9 %, `DI` 2.7 %, `DV` 1.3 %, `OT` 0.7 %. Todas cerca de las cifras de 5.2.
* **Reproducibilidad de Gemini:** en los 1 434 textos que 5.2 ya había codificado con el mismo prompt (temperatura 0, otros lotes), el conjunto de familias coincide exactamente en el 70 %. κ por código: 0.71–0.89 en `AC`, `FA`, `TR`, `PR`, `LE`, `UX`, `AT`, `CO` y `DI`; **0.58 en `DV`** y **0.22 en `OT`**; 0.88 en la marca `u`. Las series de `DV` y `OT` tienen, además del desacuerdo con el autor, ruido entre corridas de Gemini: se leen con cautela.

### 4.6 Series y señal por familia, y tópicos contra familias a escala

`dynamics.py families`, con las 40 382 negativas de la vía B. La marca `u` cuenta como una serie más. `DV` y `OT` se leen con cautela (sección 4.5).

**Proporción de cada familia en las negativas, por año** (todos los bancos, ponderada):

| Familia | 2013 | 2015 | 2017 | 2019 | 2021 | 2023 | 2024 | 2025 | 2026 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `AC` acceso | 36 % | 58 % | 44 % | 25 % | 27 % | 25 % | 26 % | 17 % | 19 % |
| `FA` falla general | 23 % | 15 % | 24 % | 29 % | 30 % | 21 % | 30 % | 25 % | 31 % |
| `LE` lentitud | 1 % | 1 % | 4 % | 8 % | 8 % | 9 % | 10 % | 17 % | 17 % |
| `CO` compatibilidad | 19 % | 9 % | 12 % | 6 % | 16 % | 9 % | 5 % | 4 % | 6 % |
| `UX` usabilidad | 7 % | 4 % | 3 % | 9 % | 6 % | 7 % | 7 % | 16 % | 10 % |
| `DI` dinero y cargos | 0 % | 0 % | 1 % | 2 % | 2 % | 4 % | 4 % | 3 % | 5 % |
| marca `u` | 30 % | 12 % | 18 % | 18 % | 14 % | 10 % | 19 % | 30 % | 14 % |

El acceso pierde peso (de 36–58 % antes de 2018 a 17–19 % en 2025–2026), mientras la lentitud y los cargos ganan. 2025 concentra los picos de usabilidad y de quejas atribuidas a una actualización, por el rediseño de BBVA. Antes de 2018 la plata tiene pocas filas por año.

**Señal de incidentes** (el mismo z ≥ 3 contra los 12 meses previos, con al menos 10 filas, que en los tópicos):

| Series | Incidentes detectados (de 3) | Con aviso el mes previo | Meses × banco con alerta fuera de incidentes |
| :--- | ---: | ---: | ---: |
| 97 tópicos | 3 | 2 | 11 % |
| 11 familias + `u` | 3 | 3 | 22 % |
| Solo la marca `u` | 2 | 2 | 4 % |

* **Las familias explican cada incidente y avisan antes.** En BBVA 2024-07, `u` (41 % de las negativas, contra una base de 10 %), ya en alerta en 2024-06. En BBVA 2025-10, `UX` (34 % contra 4 %), `DV` (14 % contra 1 %) y `u`. **En 2025-09, un mes antes del pico, `DV` (z 11.5) y `UX` (z 6.1) ya estaban en alerta**, cuando el volumen de negativas (z 1.4) y los tópicos no lo estaban: es el único aviso previo que no da el volumen.
* **Costo:** con 12 series más densas, las familias alertan en el 22 % de los meses fuera de incidentes; `FA`, `u` y `CO` son las que más alertan. La marca `u` sola tiene la mejor precisión (4 %) pero no ve el rediseño de 2025-11.
* Sin una lista de incidentes etiquetados no se sabe cuántas de esas alertas son reales; los umbrales se calibran en 5.7.

**Tópicos contra familias en los 40 382 textos** (ponderados por 1 / π, mapeo cruzado): F1 `LE` 0.74, `AC` 0.54, `TR` 0.48, `FA` 0.45, `PR` 0.44, `DV` 0.29, `UX` 0.27, `CO` 0.22, `AT` 0.21, `DI` 0 y `OT` 0. De 96 tópicos con 100 textos o más, 25 tienen pureza ≥ 0.7, 27 entre 0.5 y 0.7, y 44 por debajo de 0.5. 46 tópicos no se alinean con ninguna familia y pesan el 41 % de las negativas: confirma, con 28 veces más textos, lo que se vio con las 1 500 extracciones (sección 4.2).

### 4.7 Revisión del autor (fase 4)

El autor revisó 35 tópicos el 2026-10-22: los 20 de más peso, que suman el 57 % de las negativas, y 15 no alineados. Para cada uno anotó un nombre, la coherencia de 1 a 5, si es útil para producto, las familias correctas y si es un tema nuevo. Las fichas tienen términos y ejemplos de reseñas, así que quedan fuera de git (`data/topics/phase4_v0/`). Aquí van solo los nombres que eligió el autor y los agregados.

* **"Útil para producto" significa negocio y definición de producto,** no ingeniería (aclaración del autor). Por eso los tópicos se agrupan en tres audiencias: **producto** (útil = sí), **ingeniería** (coherencia ≥ 3 y útil = no; son fallas técnicas) y **sin valor** (coherencia ≤ 2).

| Audiencia | Principales (20) | Peso en las negativas | No alineados (15) | Peso |
| :--- | ---: | ---: | ---: | ---: |
| Producto | 7 | 22.8 % | 4 | 3.8 % |
| Ingeniería | 7 | 18.8 % | 1 | 0.7 % |
| Sin valor | 6 | 15.6 % | 10 | 8.7 % |

* **Producto:** tarjetas y préstamos (6.6 %), conectividad, autenticación y permisos del celular (4.5 %), movimientos no reconocidos y saldos no reflejados (3.5 %), transferencias (3.5 %), contraseña (2.0 %), biometría (1.4 %), acceso y gestión de cuentas (1.3 %); entre los no alineados: procesos tardados, consulta de movimientos, notificaciones (coherencia 5) y errores por actualización e instalación.
* **Ingeniería:** lentitud (6.3 %, coherencia 5), inconformidad con las actualizaciones (5.5 %), desinstalar y reinstalar (dos tópicos, 3.1 %), fallas prolongadas, no abre, errores al abrir y rechazo a la nueva versión.
* **Sin valor:** quejas genéricas ("no deja, nada": el tópico de más peso, 6.8 %), amenazas de cambiar de banco, menciones de estrellas, comparativas entre bancos, insultos, enojo y peticiones de ayuda. Varios agrupan **estilo o retórica, no problemas**, por ejemplo el patrón "reconocer lo bueno, castigar lo malo" (4 tópicos) y "antes funcionaba".
* **Ningún tópico es un tema nuevo** (0 de 35): todo lo que los tópicos encuentran cabe en las 11 familias de `v2.1`. Los tópicos útiles son **más finos que una familia** (contraseña, biometría y permisos del celular dentro de `AC`; notificaciones; reinstalación), y el autor les asigna varias familias a la vez.
* **Familias:** en los 19 tópicos útiles, la familia mayoritaria de Gemini está entre las que anota el autor en 17 (13 de 14 principales y 4 de 5 no alineados).
* **Los no alineados son casi todos ruido** (10 de 15 sin valor): confirma que "no alineado" significa "mezcla" y no "emergente" (sección 4.2).
* **Hipótesis:** el autor confirma los 6 tópicos de H-T1 y H-T2 (Súper Token, 4 de biometría, registro). Cinco de esas fichas faltaban en el material y se agregaron después en `revision_hipotesis.md`, así que esa confirmación se basó en los términos.

## 5. Recomendación (aprobada por el autor, 2026-10-22)

**Híbrido con roles separados: las familias miden y alertan, y los tópicos detallan.** Aprobada por el autor el 2026-10-22, con el agregado de la curaduría HITL en EPIC-6 (sección 6). Nota para el registro de decisión de 5.8: [`topics_decision_note.md`](topics_decision_note.md).

### 5.1 Qué se recomienda y por qué

| Componente | Rol | Evidencia |
| :--- | :--- | :--- |
| **Familias `aspects_v2_1`** (Gemini, multi-etiqueta, 11 familias) | Núcleo: métricas por banco × periodo, comparables en el tiempo | Recuperan el multi-aspecto (24.7 %), que ningún esquema de tópicos recupera (κ ≤ 0.17; §3.1 y §4.1). κ con el autor de 0.55 a 0.86 por familia (EDA §5.2.1) |
| **Marca `u`** (problema atribuido a una actualización) | Alerta principal de regresión por versión | Sube a los 4–14 días de una versión (H-T4) y llega al 61 % de las negativas en los incidentes, contra el 14 %. Como serie mensual, detecta 2 de 3 incidentes con el 4 % de meses en falsa alarma (§4.4 y §4.6) |
| **Familias como series de alerta** (`UX`, `DV`, `FA`…) | Alerta complementaria que explica el incidente | 3 de 3 incidentes, y el único aviso previo que no da el volumen: `DV` y `UX` en BBVA 2025-09, un mes antes del rediseño. Su costo es un 22 % de meses en falsa alarma (§4.6) |
| **Tópicos** (BERTopic por cláusulas, MiniLM) | Capa de detalle curada: qué hay dentro de cada familia, para producto y para ingeniería | 19 de 35 tópicos útiles según el autor (11 de producto, 8 de ingeniería), más finos que una familia (contraseña, biometría, permisos del celular, notificaciones, reinstalación) (§4.7) |

**Lo que no se recomienda:**
* **Solo tópicos dinámicos:** no recuperan el multi-aspecto, sus nombres e identidades requieren curaduría, y en este corpus no encontraron ningún tema fuera de la taxonomía.
* **Solo la taxonomía:** perdería la granularidad que pide el autor para producto e ingeniería, y la única vía para detectar algo realmente nuevo, porque `OT` no sirve como alarma (κ 0).

**Matiz explícito:** **los tópicos no demostraron descubrir temas fuera de la taxonomía en este corpus** (0 de 35 en la revisión del autor). Su valor demostrado es la granularidad dentro de cada familia y servir a dos audiencias. Su costo es la curaduría: cerca de un tercio del peso de los tópicos principales es ruido o retórica (genéricas, insultos, estrellas, "reconocer lo bueno, castigar lo malo"). La detección de lo nuevo queda como hipótesis por vigilar, no como capacidad probada.

### 5.2 Costo de operación (estimado con la plata y lo medido en 5.5)

| Rubro | Estimación | Base |
| :--- | :--- | :--- |
| Volumen nuevo | ~6 700 negativas al mes (mediana 2025–2026; hasta ~18 800 en un mes de incidente), ~6 400 textos únicos | Plata ponderada |
| Gemini, familias y `u` | **~$0.09 por 1 000 textos** → ~$0.60 al mes (~$1.70 en un mes pico), ~$7–8 al año | Vía B a escala: $3.64 por 40 382 textos, incluidos los reintentos |
| Gemini, histórico (si 5.7 decide reprocesar) | ~$60 por ~670 000 textos negativos únicos | Misma tarifa |
| Embeddings y asignación de tópicos | Segundos al mes (MiniLM, 860 textos/s en CPU/MPS local) | Fases 0 y 2 |
| **Reagrupamiento** | **Trimestral**: re-ajustar BERTopic sobre una muestra estratificada (~40 000 textos, 1–2 min) y asignar el resto con `transform` entre reajustes | Fases 1 y 2 |
| **Curaduría humana** | ~45 min la primera vez para 20 tópicos; luego ~30–60 min por trimestre para revisar los tópicos nuevos o cambiados y descartar el ruido (~1/3) | Revisión del autor (§4.7) |
| **Estabilidad de identificadores** | Entre reajustes, el modelo se congela y los identificadores no cambian. En cada reajuste, los tópicos se emparejan con los anteriores por similitud de centroides y el curador confirma. El emparejamiento no está validado: el ARI entre semillas varió de 0.40 a 0.97 según la configuración (§2.1) | Pendiente para 5.7 |

Las familias no tienen problema de identidad: son fijas. Su riesgo es el cambio de prompt o de modelo de Gemini, que exige re-medir κ y la reproducibilidad entre corridas (hoy 0.71–0.89; `DV` 0.58 y `OT` 0.22; §4.5).

### 5.3 Qué queda para 5.6–5.8

* **5.6:** si las alertas se priorizan, `priority_weight_score` y los votos de utilidad se evalúan contra los incidentes conocidos; la calibración de probabilidades no aplica a Gemini.
* **5.7:**
  * calibrar los umbrales de la señal (z, línea base, mínimo de filas) con más filas por mes que la plata y con una lista de incidentes etiquetados;
  * el análisis por versión, que con la plata no alcanza (§3.4);
  * validar el emparejamiento de tópicos entre reajustes;
  * el *backfill* (sentimiento y familias) y el monitoreo de la prevalencia de `OT` y de los tópicos no alineados.
* **5.8:** registrar la estrategia (esta recomendación); el modelo de sentimiento que define qué reseñas son negativas en producción (M4 o M9), del que dependen las familias; y `TOPIC_TOO_SHORT` con k = 1 (decidido).

## 6. Pendiente

* **Agregado del autor al aprobar:** los flujos de curaduría (sentimiento, aspectos y tópicos) pasan al frontal HITL de EPIC-6, con una base de datos de curadurías para el reentrenamiento; requisitos y borrador del modelo de datos en la [nota para 5.8](topics_decision_note.md#agregado-del-autor-2026-10-22-curaduría-hitl-en-epic-6).
* Confirmar las hipótesis H-T1 y H-T2 con las fichas de `revision_hipotesis.md`, si el autor lo considera necesario.
