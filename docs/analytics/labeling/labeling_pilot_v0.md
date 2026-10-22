# Piloto de etiquetado con Gemini Flash (EPIC-5, feature 5.3)

> **Estado (2026-10-19): histórico.** Índice: [`README.md`](../README.md).
> * **Sigue vigente:** el modelo `gemini-3.6-flash` con razonamiento mínimo, la estructura de costo (la salida compacta) y el tope de $25 por corrida de plata.
> * **Reemplazado por:**
>   * prompt candidato `prompt_v1` → `prompt_v3`, elegido en la [re-anotación](gold_v0_r2_report.md), sección 5;
>   * acuerdo con humanos pendiente → medido en el [oro](gold_v0_report.md) y en [`gold_v1`](gold_v1_report.md) (κ 0.92);
>   * plan del oro (bloque dirigido de 600) → diseño de [`gold_v1`](gold_v1_report.md) (1 000 aleatorios y 300 dirigidos).

* **Corridas:** `20261018T050027Z` (`prompt_v0`, secciones 1–3) y `20261018T052510Z` (`prompt_v1`, sección 4). Muestra del snapshot `tds_20261016T054714Z` con `eligibility_rules_v0.1`.
* **Configuración:**
  * modelo `gemini-3.6-flash` en Vertex AI, región `global`, mismo proyecto GCP;
  * `prompt_v0` ([`prompt_v0.md`](../../../experiments/analytics/src/voc_analytics/labeling/prompts/prompt_v0.md)), condensado de `annotation_guideline_v0`;
  * temperatura 0, `thinking_level=minimal`, salida JSON con esquema (`i`, `s`, `f`, `d`);
  * 50 textos por petición, peticiones en línea (sin Batch API).
* **Código:**
  * [`sample_pilot.py`](../../../experiments/analytics/src/voc_analytics/sampling/sample_pilot.py) arma la muestra;
  * [`label_gemini.py`](../../../experiments/analytics/src/voc_analytics/labeling/label_gemini.py) etiqueta;
  * [`eligibility.py`](../../../experiments/analytics/src/voc_analytics/labeling/eligibility.py) implementa las reglas TNSS.
* **Datos:** la muestra, las etiquetas y la metadata de la corrida están en `experiments/analytics/data/labels/pilot_v0/`, fuera de git. Este reporte solo tiene agregados.
* **Pendiente:** el acuerdo con humanos se mide cuando exista la app de anotación.

## 1. Muestra

* **Diseño:**
  * 500 textos únicos (`texto_limpio`), estratificados por banco × estrellas (25 estratos de 20);
  * cuotas por longitud dentro de cada estrato: 1 palabra = 2, 2–5 = 6, 6–20 = 6, 21–60 = 4, más de 60 = 2;
  * semilla `20261017`.
* **Lo que no es:** **no es probabilística.** Sobrerrepresenta los textos largos y las estrellas 2–4. Sirve para medir tokens, costo y comportamiento del prompt. Las proporciones de abajo no estiman el corpus.
* **Lo que se envía:** a Gemini se envía `texto_sanitizado`, nunca las estrellas.
* **Modelos probados:**
  * En Vertex responden `gemini-2.5-flash`, `-2.5-flash-lite`, `-3-flash-preview` y `-3.5`, `-3.6` y `-3.7-flash`.
  * Se eligió **3.6 Flash** porque es el más reciente que acepta `thinking_level=minimal` con 0 tokens de razonamiento.
  * 3.7 Flash razona aun con `thinking_budget=0`, y esos tokens se cobran como salida.

## 2. Operación y costo

| Métrica | Valor |
| :--- | ---: |
| Peticiones / fallidas / reintentos | 10 / 0 / 0 |
| Textos etiquetados | 500 de 500 (ids completos en todos los lotes) |
| Latencia por petición | 4.5–6.7 s |
| Tokens de entrada | 21 856 (612 por petición son la instrucción) |
| Tokens de salida / razonamiento | 12 220 / 0 |
| Tokens en caché implícita | 0 |
| Costo | **$0.062** ($0.124 por 1 000 textos) |

* **Precio:** $0.75 de entrada y $3.75 de salida por 1M de tokens, introductorio de Vertex AI hasta el 2026-12-31. Desde 2027 el estándar es $1.50 / $7.50.
* **Descuento de Batch API:** no está confirmado para este modelo; verificar en la página oficial antes de usarlo.
* **La salida es el 74 % del costo:** ~24 tokens por texto, casi todo nombres de campo y llaves JSON.

### Proyección

Se usan 0.299 tokens por carácter de texto y 24.4 de salida por texto, medidos en el piloto, más 612 tokens de instrucción por cada lote de 50.

| Alcance | Textos únicos | Costo en línea, precio introductorio | Precio 2027 |
| :--- | ---: | ---: | ---: |
| Plata de 50 000 textos | 50 000 | ~$6 | ~$12 |
| Plata de 100 000 textos | 100 000 | ~$12 | ~$24 |
| Todo el corpus elegible (M9 como clasificador directo) | 1 380 725 | ~$168 | ~$336 |
| Corpus elegible sin una palabra | 1 371 076 | ~$167 | ~$334 |

* **Las reseñas de una palabra no afectan el costo.** Son el 18 % de las filas pero solo 9 649 textos únicos (0.7 %), porque se repiten muchísimo. La decisión sobre `TNSS_SINGLE_WORD` en 5.8 es solo metodológica.
* **El conjunto de plata (decenas de miles) cabe holgado en los créditos.** El corpus completo con Gemini (M9) es viable pero caro frente a un modelo propio, y se compara así en 5.4.

## 3. Comportamiento de las etiquetas

### Etiqueta de Gemini por estrellas (filas = 100 textos cada una)

| Estrellas | NEG | NEU | POS | NA |
| :---: | ---: | ---: | ---: | ---: |
| 1 | 91 | 5 | 3 | 1 |
| 2 | 81 | 7 | 4 | 8 |
| 3 | 64 | 19 | 15 | 2 |
| 4 | 37 | 17 | 45 | 1 |
| 5 | 8 | 1 | 89 | 2 |

### Por longitud

| Palabras | Textos | NEG | NEU | POS | NA | `f` (falla) | `d` (duda) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 50 | 9 | 7 | 24 | 10 | 4 % | 6 % |
| 2–5 | 150 | 70 | 20 | 57 | 3 | 35 % | 5 % |
| 6–20 | 150 | 91 | 14 | 44 | 1 | 54 % | 1 % |
| 21–60 | 100 | 73 | 7 | 20 | 0 | 68 % | 3 % |
| >60 | 50 | 38 | 1 | 11 | 0 | 82 % | 0 % |

### Lectura

1. **Las estrellas y el texto coinciden en los extremos**, con 91 % NEG en 1★ y 89 % POS en 5★. El ruido se concentra en 3★ y sobre todo en **4★: 37 % NEG**.
   * Incongruencia en la muestra (1–2★ con POS o 4–5★ con NEG): 6–16 % por banco y 15–18 % en textos de más de 20 palabras.
   * No estima el corpus: la tasa poblacional sale del bloque aleatorio del oro.
2. **La regla 2 ("falla concreta ⇒ NEG") se aplica de forma agresiva.**
   * Ejemplos sintéticos del patrón: "excelente, solo que a veces tarda" o "es un poco lenta".
   * Gemini etiqueta `NEG` lo que la guía ejemplifica como `NEU` ("regular, a veces se tarda").
   * La guía dice "lentitud que **impide** el uso", pero no separa la molestia menor de la falla que bloquea. Es la ambigüedad principal a resolver en la calibración (guía v1).
3. **`NA` (2.8 %) es sensato:** ruido de teclado, alfabetos mezclados, palabras sueltas sin valoración. Hay casos dudosos:
   * una queja con faltas severas ("no entra" mal escrito) quedó `NA`;
   * algunas palabras sueltas neutras quedaron `NA` y no `NEU`.
4. **`d` (duda) casi nunca se activa** (3 %), ni siquiera en los casos fronterizos del punto 2. No sirve como señal de incertidumbre para el muestreo dirigido del oro. Alternativas a probar:
   * probabilidades de token (`response_logprobs`), si el modelo las expone;
   * desacuerdo entre dos prompts o modelos (por ejemplo, 3.6 Flash contra 2.5 Flash-Lite);
   * desacuerdo con un clasificador clásico (M1).
5. **`f` (falla) crece con la longitud** (4 % → 82 %), como se esperaba. Hay inconsistencias aisladas: una queja de tarjeta no entregada con `f = false`.

## 4. Segundo piloto: salida compacta (`prompt_v1`)

* **Corridas:** `20261018T052510Z` y su repetición `20261018T052534Z`, sobre las mismas 500 muestras.
* **Qué cambia:** `prompt_v1` ([`prompt_v1.md`](../../../experiments/analytics/src/voc_analytics/labeling/prompts/prompt_v1.md)) tiene **las mismas reglas** que v0. Solo cambia la salida y el lote:
  * texto plano, una línea `i etiqueta f` por texto;
  * sin `d`, que no aportaba señal;
  * sin esquema JSON (el esquema también se cobra como entrada);
  * lotes de 100.

| Métrica | `prompt_v0` | `prompt_v1` |
| :--- | ---: | ---: |
| Peticiones / fallidas | 10 / 0 | 5 / 0 |
| Tokens de entrada | 21 856 | 17 481 |
| Tokens de salida por texto | 24.4 | 6.9 |
| Latencia por petición | 4.5–6.7 s | 3.2–3.9 s |
| Costo por 1 000 textos | $0.124 | **$0.052** (−58 %) |

### Concordancia

| Comparación | Acuerdo en sentimiento | κ sentimiento | κ falla |
| :--- | ---: | ---: | ---: |
| v0 contra v1 | 90.0 % | 0.83 | 0.85 |
| v1 contra su repetición (misma configuración) | 95.2 % | 0.92 | 0.92 |

* **Temperatura 0 no es determinista:** repetir la misma corrida cambia la etiqueta en ~5 % de los textos. Ese es el piso de ruido propio de la plata y se reporta así en 5.8.
* **v1 es menos agresivo con la regla 2.**
  * De los 50 cambios, 23 son `NEG` → `NEU` y 11 `NEG` → `POS`.
  * En 4★ los `NEG` bajan de 37 a 20 y los `NEU` suben de 17 a 30.
  * El formato de salida cambia la etiqueta en los casos fronterizos (molestias menores). Cuál versión acierta lo decide el oro.

### Proyección con `prompt_v1`

Se usan 0.272 tokens por carácter, 6.9 de salida por texto y 628 de instrucción por lote de 100.

| Alcance | Precio introductorio | Precio 2027 |
| :--- | ---: | ---: |
| Plata de 50 000 textos | ~$2.5 | ~$5 |
| Plata de 100 000 textos | ~$5 | ~$10 |
| Corpus elegible completo (1.38 M únicos, M9) | ~$69 | ~$137 |

**Presupuesto disponible:** ~$5 000 MXN de crédito tras la ingesta histórica, del orden de $250–$280 USD. La plata cuesta una fracción mínima, e incluso Gemini sobre todo el corpus (M9) cabe. El presupuesto deja de ser restricción del etiquetado; la restricción real es el tiempo humano del oro.

## 5. Decisiones y siguientes pasos

* **Modelo (decidido 2026-10-18):** se mantiene `gemini-3.6-flash` con razonamiento mínimo. Solo se cambia si el κ humano–Gemini del bloque a ciegas resulta bajo.
* **Prompt de producción candidato:** `prompt_v1`, por costo. El oro lleva propuestas de v1, y el bloque a ciegas permite comparar v0 y v1 contra el humano antes de fijarlo.
* **Oro, primera ronda** ([`sample_gold_v0.py`](../../../experiments/analytics/src/voc_analytics/sampling/sample_gold_v0.py)), en este orden:
  1. 30 de calibración del piloto, la mitad donde las corridas de Gemini discrepan;
  2. 400 aleatorias, muestreo aleatorio simple en banco × periodo (80 por banco), con probabilidad de inclusión; 201 a ciegas y 199 asistidas;
  3. 20 de re-anotación.
* **Oro, después:** el bloque dirigido (600) se arma cuando exista la plata.
* **Pendiente:** resolver en la calibración la ambigüedad de "molestia menor contra falla" (regla 2) y publicar `annotation_guideline_v1` si cambia alguna regla.
* **Tope de gasto:** $25 USD por corrida de plata, registrado en `run_<run>.json`. Conviene además una alerta de presupuesto en la cuenta de facturación.
