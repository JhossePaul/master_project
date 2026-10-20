# Conjunto de oro, primera ronda (EPIC-5, feature 5.3)

> **Estado (2026-10-19): histórico.** Índice: [`README.md`](README.md).
> * **Sigue vigente:** la medición del anclaje (sección 1.4) y la decisión de anotar todo a ciegas; la elección de `gemini-3.6-flash`.
> * **Reemplazado por:**
>   * las etiquetas de esta ronda → la [re-anotación a ciegas](gold_v0_r2_report.md) con la guía v2, que a su vez forma parte del oro junto con [`gold_v1`](gold_v1_report.md);
>   * guía v1 y `prompt_v2` (secciones 3 y 4) → guía [`v2.2`](annotation_guideline.md) y `prompt_v3`;
>   * ruido de las estrellas de 10.4 % (n = 400) → 12.5 % (EE 1.3) con `gold_v1`;
>   * κ humano–Gemini de 0.84–0.88 → 0.92 en 600 textos nuevos a ciegas ([`gold_v1`](gold_v1_report.md), sección 3).

* **Fecha:** 2026-10-18.
* **Anotación:** un anotador (el autor) con `annotation_guideline_v0`.
* **Volumen:** 450 ítems en 39.8 minutos efectivos, con 13 correcciones.
* **Datos:** cola y anotaciones en `experiments/analytics/data/labels/gold_v0/`, fuera de git.
* **Métricas:** [`gold_v0_metrics.json`](gold_v0_metrics.json), calculadas con [`analyze_gold_v0.py`](../../experiments/analytics/src/voc_analytics/analysis/analyze_gold_v0.py).
* **Este reporte solo tiene agregados.**

| Bloque | Ítems | Modo | Uso |
| :--- | ---: | :--- | :--- |
| Calibración | 30 | A ciegas, con retroalimentación al guardar | Ajustar la guía; la mitad son textos donde las corridas de Gemini discrepan |
| Aleatorio | 201 | A ciegas | Acuerdo con Gemini sin anclaje; estimaciones poblacionales |
| Aleatorio | 199 | Asistido (propuesta de `prompt_v1`) | Estimaciones poblacionales; medición del anclaje |
| Re-anotación | 20 | A ciegas | Consistencia del anotador |

El bloque aleatorio es un muestreo aleatorio simple dentro de banco × periodo, con 80 reseñas por banco. Las proporciones poblacionales se ponderan por 1 / probabilidad de inclusión, y el error estándar (EE) es el del muestreo estratificado.

## 1. Hallazgos

### 1.1 Ruido de las estrellas (el objetivo central)

| Estimación poblacional (filas elegibles) | Bloque aleatorio (n = 400) | Solo a ciegas (n = 201) |
| :--- | ---: | ---: |
| Estrellas (1–2 NEG, 3 NEU, 4–5 POS) distintas del oro, textos evaluables | **10.4 %** (EE 1.7) | 9.8 % (EE 2.3) |
| Incongruencia en los extremos (1–2★ con oro POS, o 4–5★ con oro NEG) | **4.2 %** (EE 1.2) | 5.3 % (EE 1.9) |
| Oro `NEG` / `NEU` / `POS` / `NO_EVALUABLE` | 25.2 / 3.3 / 71.1 / 0.5 % | 28.9 / 1.8 / 68.3 / 0.9 % |
| Menciona falla | 21.9 % (EE 2.4) | — |

* **κ estrellas contra oro: 0.71** (n = 398 evaluables).
  * Las estrellas como clasificador (M0) aciertan el 88.7 % sin ponderar.
  * Es la línea base que cualquier modelo de 5.4 debe superar.
* **El ruido se concentra en 3★ y 4★.**
  * De 14 reseñas de 3★, el oro marca 10 como `NEG`.
  * De 42 de 4★, 10 son `NEG` y 7 `NEU`.
  * En 1★ y 5★ el acuerdo es de 97 % y 95 %.
* **Por banco**, la incongruencia en los extremos va de 3.2 % (AZTECA) a 5.4 % (BBVA). Con 80 reseñas por banco los EE (2–3 puntos) **no permiten distinguir bancos**.
* **Por periodo** parece más alta antes de 2020 (8.1 %, EE 3.5) que en 2025–2026 (1.6 %, EE 1.2). Es un indicio que coincide con la deriva del EDA (H6), no una conclusión. Afinarlo requiere el oro dirigido o la plata.

### 1.2 Acuerdo con Gemini (bloque a ciegas, n = 201)

| Prompt | Acuerdo | κ sentimiento | κ menciona falla |
| :--- | ---: | ---: | ---: |
| `prompt_v0` (JSON) | 93.0 % | **0.85** | 0.82 |
| `prompt_v1` (compacto) | 92.5 % | **0.84** | 0.86 |

* **Gemini 3.6 Flash supera el umbral habitual de acuerdo "casi perfecto"** (κ > 0.8). Además, κ humano–Gemini (0.84) es del mismo orden que la consistencia del propio anotador (0.83).
  * **Decisión 1 confirmada:** se mantiene `gemini-3.6-flash`.
* **Errores de Gemini contra el oro:** en v1, 7 de los 15 desacuerdos son `POS` humano y `NEU` Gemini, en textos favorables cortos o tibios. Hay solo 1 `NEG` humano marcado `POS`.
* **En la población aleatoria v0 y v1 empatan**, porque los casos fronterizos son pocos.

### 1.3 Casos fronterizos (calibración)

| | Acuerdo con el humano | κ |
| :--- | ---: | ---: |
| `prompt_v0` | 80.0 % | 0.53 |
| `prompt_v1` | 53.3 % | 0.26 |
| Textos donde v0 y v1 discrepan (10) | **v0 coincide en 9**, v1 en 1 | |

* El κ es bajo por diseño: la calibración se eligió entre los casos donde las corridas de Gemini discrepan.
* **El patrón es claro.** Las notas del anotador aplican la regla 2 en su lectura amplia, como hace v0: la lentitud ocasional o una molestia concreta hacen la reseña `NEG` aunque haya elogios.
  * `prompt_v1` relaja esa regla al cambiar el formato de salida, y en estos casos falla.
  * Para la detección de incidencias, el foco del proyecto, la lectura amplia es la útil.
* **Inconsistencia del anotador:**
  * Un caso de "todo muy bien, el único detalle es que es pesada" quedó `NEU` con falla.
  * La palabra suelta "complicado" quedó `NO_EVALUABLE`; Gemini la marca `NEG`.
  * Ambos van a la guía v1.

### 1.4 Anclaje

| Modo | Acuerdo con `prompt_v1` | κ | Mediana de tiempo por reseña |
| :--- | ---: | ---: | ---: |
| A ciegas | 92.5 % | 0.84 | 2.4 s |
| Asistido | **99.5 %** | 0.99 | **1.3 s** |
| Asistido contra `prompt_v0` (nunca mostrado) | 98.0 % | 0.95 | |

* **El anclaje es fuerte.** Al ver la propuesta, el acuerdo sube 7 puntos y el tiempo se reduce a la mitad.
  * En textos de más de 20 palabras la mediana baja de 11.6 s a 5.3 s.
  * Los dos bloques son mitades aleatorias de los mismos estratos, así que la diferencia no se explica por los textos.
* **Consecuencias:**
  * Las etiquetas asistidas **no sirven para evaluar a Gemini** ni a modelos entrenados con su plata: heredan su sesgo.
  * Para métricas de modelos y para PPI se usa solo el bloque a ciegas.
  * Las estimaciones poblacionales del bloque completo coinciden con las de solo a ciegas dentro del EE, pero el reporte final usa las de solo a ciegas.
  * **El bloque dirigido de la segunda ronda se anota a ciegas.** El modo asistido se reserva para tareas donde la velocidad importe más que la independencia.

### 1.5 Consistencia del anotador

* Re-anotación de 20 ítems: **95 % de acuerdo, κ 0.83**. Un solo cambio.
* **Limitación:** se hizo en la misma sesión, minutos después, no días después como pide la guía. Es una cota optimista.
* La marca `duda` se usó en el 0.35 % de las reseñas: el anotador tampoco la usa. Igual que con Gemini, no sirve como señal de incertidumbre.

## 2. Limitaciones

* **Un solo anotador**, que además es el autor de la guía. No hay acuerdo entre anotadores independientes.
* **n = 400 aleatorio:** alcanza para el nivel global (EE de 1–2 puntos), no para comparar bancos o periodos.
* **El tiempo por reseña** incluye la lectura desde que la app muestra el texto. Una pausa con la app abierta lo infla, pero ninguna mediana se ve afectada.

## 3. Guía v1 y `prompt_v2` (2026-10-18)

* **Qué cambia:**
  * Se aplicó [`annotation_guideline_v1`](annotation_guideline.md) con la regla 2 amplia: cualquier queja concreta es `NEG`, aunque sea menor u ocasional. Las palabras sueltas con valencia son evaluables.
  * [`prompt_v2`](../../experiments/analytics/src/voc_analytics/labeling/prompts/prompt_v2.md) usa la salida compacta de v1 con esas reglas y ejemplos sintéticos nuevos.
* **Validación:** dos corridas sobre la calibración y el bloque aleatorio (430 textos, $0.045 por 1 000), con métricas en [`prompt_validation_prompt_v2.json`](prompt_validation_prompt_v2.json).

| Prompt | κ a ciegas (n = 201) | Acuerdo a ciegas | κ calibración (n = 30) | Fronterizos v0≠v1 que acierta (de 10) |
| :--- | ---: | ---: | ---: | ---: |
| `prompt_v0` | 0.85 | 93.0 % | 0.53 | 9 |
| `prompt_v1` | 0.84 | 92.5 % | 0.26 | 1 |
| **`prompt_v2`** | **0.88** | **94.5 %** | 0.57 | 7 |

* **Estabilidad de v2:** 98.4 % de acuerdo entre dos corridas idénticas (κ 0.97).
* **`menciona_falla`:** κ 0.83 a ciegas.
* **v2 es el mejor en el bloque a ciegas**, pero con n = 201 la ventaja sobre v0 (3 puntos de κ) no es significativa.
* **La calibración no es una prueba independiente:** la guía v1 se derivó de esos 30 textos.
* **Desacuerdos que quedan:**
  * **Fronterizos (3):** la etiqueta humana contradice la guía v1, porque se anotó con v0 (una molestia menor quedó `NEU`), o v2 se equivoca con ironía o con una palabra suelta.
  * **A ciegas (11):**
    * 4 son `POS` humano y `NEG` v2. Al menos 3 traen una queja menor ("el único problema es…") que con la guía v1 es `NEG`: **el oro de la primera ronda se anotó con v0 y no es del todo consistente con v1.**
    * 3 son `POS` humano y `NEU` v2 en "bien" u "ok". Es una laguna de la guía (¿un aprobatorio tibio es `POS`?).
    * Los demás son casos aislados.

## 4. Decisiones

1. **Modelo:** `gemini-3.6-flash`, confirmado (κ a ciegas 0.84–0.88 según el prompt).
2. **Guía vigente:** `annotation_guideline_v1`. La app registra la versión en cada anotación.
3. **Prompt de producción:** `prompt_v2`. Iguala o supera a los anteriores en el bloque a ciegas y conserva el costo de v1.
4. **Segunda ronda del oro a ciegas**, incluido el bloque dirigido.

## 5. Siguientes pasos propuestos

1. **Re-anotación del bloque a ciegas con la guía v1** (201 ítems, sin propuesta), al menos un día después. Sirve para tres cosas a la vez:
   * migrar el oro a v1;
   * medir la consistencia del anotador en el plazo que pide la guía;
   * recalcular el κ de `prompt_v2` contra un oro coherente con sus reglas.
2. **Decidir "bien" / "ok"** (¿`POS`?) antes de la re-anotación; si cambia, se publica `annotation_guideline_v2`.
3. **Plata con `prompt_v2`** sobre una muestra estratificada para la competencia de modelos (5.4). Por ejemplo, 100 000 textos únicos por ~$5.
