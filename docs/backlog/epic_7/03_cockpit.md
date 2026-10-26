# Paso 3. Feature 7.5: Cockpit diario de KPIs

* **Estado (2026-10-26):** Implementado, probado, medido y desplegado en dev (imagen `bd705ed`). En revisión del autor: hay ajustes de datos, de diseño y una vista por versión nueva (ver "Revisión del autor tras el despliegue en dev").
* **Nivel:** imprescindible; la pestaña por versión, importante.
* **Depende de:** paso 2.
* **Objetivo:** el seguimiento diario de los cinco bancos, con solo agregados (rol lector): tarjetas con PPI, series diarias crudas con los temas del día, familias y marca `u` en nivel y en anomalía, tópicos vigentes, la matriz estrellas × texto, la comparación entre bancos y la pestaña por versión de la app.

## 1. Qué muestra y de dónde sale

| Bloque | Fuente | Método | Grano |
| :--- | :--- | :--- | :--- |
| Tarjetas por banco | `kpi_estimates` (`neg`, `gap_estrellas`, `estrellas_POS_texto_NEG`), última corrida | PPI con intervalo | Banco × mes |
| Serie diaria de sentimiento y *gap* | `review_predictions_current` | Crudo, rotulado como tal | Banco × día |
| Temas del día | `daily_topic_labels` | Crudo (participación del día y habitual de 28 días) | Banco × día |
| KPI mensuales | `kpi_estimates` (`ppi` y `raw`) | PPI con intervalo, con la cruda al lado | Banco × mes |
| Familias y marca `u` | Nivel: `review_aspects` con `review_predictions_current`; anomalía: `drift_metrics` (`family_<código>` y `flag_update_share`, z) | Crudo; z robusto del monitor | Banco × mes |
| Cambios de prompt | `review_aspects`: primera `labeled_at` de cada `prompt_version` | — | — |
| Tópicos vigentes | `topic_assignments` de la versión de `topic_model_current`, solo tópicos útiles, con su nombre curado | Crudo | Banco × mes × tópico |
| Matriz 3 × 3 | `kpi_estimates` (`estrellas_<A>_texto_<B>`) | PPI | Banco × mes |
| Comparación entre bancos | `kpi_estimates` del mes elegido | PPI con intervalo | Banco |
| Pestaña por versión | `review_predictions_current` + `review_aspects` | Crudo con IC de Wilson | Banco × versión |

**Lo que no se calcula aquí:** ningún PPI (lo calcula el monitor semanal en `kpi_estimates`) ni ningún umbral nuevo. El z de las familias es el mismo que usa el monitor de deriva, así que el cockpit y las alertas no se contradicen.

## 2. API (`sections/kpis/`)

Todas de rol lector y con `cache=True`. Los filtros comunes son `banks: list[str]` (por defecto los cinco), `date_from: date` y `date_to: date`.

| Método y ruta | Respuesta |
| :--- | :--- |
| `GET /api/v1/kpis/cards?period=YYYY-MM` | `list[BankCard]`: por banco, `neg`, `gap_estrellas` y `quejas_4_5` (celda `estrellas_POS_texto_NEG`) como `Estimate`, más el mismo mes del año anterior para la flecha de cambio, `model_version`, `gold_version` y alertas abiertas. Sin `period`, el último mes con PPI |
| `GET /api/v1/kpis/daily` | `list[DailyPoint]`: `bank_id`, `dia`, `filas`, `predichas`, `neg`, `neu`, `pos`, `no_predichas`, `gap_crudo`, `texto_peor`, `texto_mejor`, `neg_4_5` |
| `GET /api/v1/kpis/daily-topics?bank=…&day=…` | `DailyTopics`: `n_neg` y dos listas de hasta 5 (`familias`, `topicos`) con `codigo`, `nombre`, `filas`, `participacion`, `habitual`; más `aspects_prompt_version` y `topic_model_version` |
| `GET /api/v1/kpis/monthly?metrics=neg,gap_estrellas,texto_peor,texto_mejor` | `list[MonthlyKpi]`: `bank_id`, `period`, `metric`, `ppi: Estimate`, `raw: Estimate`, `model_version` |
| `GET /api/v1/kpis/families` | `FamiliesResponse`: `series: list[FamilyMonth]` (`bank_id`, `period`, `family` o `"u"`, `neg_count`, `share`, `z`, `threshold`, `alert`) y `prompt_changes: list[{prompt_version, first_labeled_at}]` |
| `GET /api/v1/kpis/topics` | `list[TopicMonth]`: `bank_id`, `period`, `topic_id`, `nombre`, `audience`, `families`, `filas`, `share`; con `topic_model_version` |
| `GET /api/v1/kpis/matrix?period=YYYY-MM` | `list[MatrixCell]`: `bank_id`, `stars_class`, `text_class`, `ppi: Estimate`, `raw: Estimate` |
| `GET /api/v1/kpis/versions?bank=…` | `list[VersionRow]`: `release` (o `OTRAS`), `first_seen`, `last_seen`, `filas`, `neg`, `neg_share`, `neg_ci_low`, `neg_ci_high` (Wilson 95 %), `u_share`, `families: dict[str, float]`. Más la cobertura (filas con versión reconocida) |

### 2.1 Consultas

* **Serie diaria** (la más cara; medir con `dry_run` en la verificación del paso 0):

```sql
SELECT bank_id, DATE(fecha) AS dia,
       COUNT(*) AS filas,
       COUNTIF(sentiment IN ('NEG', 'NEU', 'POS')) AS predichas,
       COUNTIF(sentiment = 'NEG') AS neg,
       COUNTIF(sentiment = 'NEU') AS neu,
       COUNTIF(sentiment = 'POS') AS pos,
       COUNTIF(sentiment = 'NO_PREDICTED') AS no_predichas,
       AVG(IF(sentiment IN ('NEG', 'NEU', 'POS'),
              estrellas - CASE sentiment WHEN 'NEG' THEN 1 WHEN 'NEU' THEN 3 ELSE 5 END,
              NULL)) AS gap_crudo,
       COUNTIF(texto_peor) AS texto_peor,
       COUNTIF(texto_mejor) AS texto_mejor,
       COUNTIF(sentiment = 'NEG' AND estrellas >= 4) AS neg_4_5
FROM `…review_predictions_current`
WHERE fecha BETWEEN @date_from AND @date_to AND bank_id IN UNNEST(@banks)
GROUP BY bank_id, dia
```

  El tipo de `fecha` (`DATE` o `TIMESTAMP`) sale de `ReviewPrediction`; el día es el día UTC. El *gap* crudo usa el mismo signo que `voc_nlp.ppi.targets`: positivo cuando las estrellas son mejores que el texto. **Si la consulta factura más de 1 GB** (la vista elige la última fila por reseña con una ventana, y eso puede impedir que el filtro por fecha pode particiones), se detiene y se propone al autor una tabla de agregados diarios que actualice el delta. Es un cambio de contrato.
* **Familias, nivel:** negativas de dos palabras o más (`sentiment = 'NEG' AND palabras >= 2`, la misma base que `daily_topic_labels`), unidas con la última fila de `review_aspects` por `id_resena` (`QUALIFY ROW_NUMBER() OVER (PARTITION BY id_resena ORDER BY labeled_at DESC) = 1`), con `UNNEST(families)` y conteo por banco × mes × familia, más `COUNTIF(flag_update)`.
* **Familias, anomalía:** `drift_metrics` con `metric` en `family_<código>` y `flag_update_share`, la última `computed_at` por (`bank_id`, `period`, `metric`), con `z`, `threshold` y `alert`. Antes de la política v2 esas series no tienen umbral: se muestran sin línea de umbral.
* **Tópicos:** `topic_assignments` de `topic_model_current`, con `curation_topics` (`curated_name`, `audience`, `families`) y `topic_catalog` (nombre por defecto); solo `audience` en producto o ingeniería.
* **Versiones:** la normalización de `release` es el port a SQL de `voc_analytics.topics.versions.normalize` (sin modificar el original), en `sections/kpis/versions.py`:
  * nulas: `UNKNOWN`, las que contienen `beta` (sin importar mayúsculas) y las que no empiezan con dígito;
  * base: quitar `-minApi<n>` y quedarse con el prefijo `[\d.]+` sin puntos al final;
  * BANORTE: los tres primeros componentes;
  * BBVA con tercer componente de 6 dígitos (una fecha): los dos primeros;
  * el resto, la base.

  Las versiones con menos de 50 reseñas con sentimiento en el banco se agrupan en `OTRAS`, como en los experimentos (el reporte de 5.9 cuenta reseñas, no negativas). El IC de Wilson se calcula en Python (`sections/kpis/stats.py`, con prueba contra valores conocidos). La prueba del port reproduce los ejemplos del docstring de `versions.py` (`7.0.9.45841` → `7.0.9`, `11.33.210429` → `11.33`, `9.38.75-minApi28` → `9.38.75`, `2.6.2 - BETA` → nula).

## 3. Pantalla (`src/sections/cockpit/`)

Dos pestañas: **Diario** (por defecto) y **Por versión**. La barra de filtros globales aplica a las dos.

### 3.1 Pestaña Diario, de arriba abajo

1. **Tarjetas por banco** (`KpiCard`): *gap* en estrellas (PPI, con intervalo y la flecha contra el mismo mes del año anterior), proporción de `NEG` (PPI), quejas con 4–5★ (PPI) y alertas abiertas. Insignia `PPI`, mes y procedencia.
2. **Serie diaria** (`TimeSeries`, dygraphs), con un selector entre proporción de `NEG` (por defecto), *gap* crudo y proporción de quejas con 4–5★; una línea por banco con su color y su trazo de respaldo. Insignia `crudo`. Debajo, la línea de procedencia (modelo vigente y fechas). Las anotaciones marcan los cambios de versión del modelo de sentimiento (`model_versions` promovidas).
   * **Al elegir un día** (clic), se abre un **panel lateral** con los temas del día del banco elegido (o una pestaña por banco si hay varios): las 5 familias y los 5 tópicos útiles, cada uno con su participación del día y la habitual, como barra doble (día en el color del banco, habitual en gris). Arriba del panel, el `Callout` "Describe lo que dicen las reseñas negativas de ese día; no es un diagnóstico ni la detección de un incidente". Es la forma visual recomendada (pregunta `K-01`).
   * **Al arrastrar un rango** se actualizan `desde` y `hasta` en la URL.
3. **KPI mensuales con PPI:** puntos con barras de error (PPI) y una línea tenue con la proporción cruda del mismo mes, por banco, en una rejilla de gráficas pequeñas (una por banco, misma escala), para `gap_estrellas` y `neg`.
4. **Familias y marca `u`:** dos vistas del mismo dato, con un conmutador "Nivel | Anomalía":
   * nivel: barras apiladas por mes (volumen de negativas por familia), con líneas verticales en cada cambio de prompt y su `prompt_version`, y el aviso "las familias de cada tramo vienen del prompt con el que se etiquetaron";
   * anomalía: mapa de calor familia × mes con la escala divergente del z y el umbral (z ≥ 4) marcado con borde;
   * al pulsar una familia se escribe `?familia=<código>` en la URL: se resalta en las demás gráficas y viaja al Explorador.
5. **Tópicos vigentes:** los tópicos útiles ordenados por volumen del periodo, cada uno con su minigráfica de tendencia mensual, su audiencia y sus familias.
6. **Matriz estrellas × texto** del mes elegido (por defecto el último con PPI): 3 × 3 con la escala secuencial verde, el porcentaje con PPI y el intervalo en cada celda; las dos celdas de incongruencia extrema, con borde. Sirve de desglose del *gap*.
7. **Comparación entre bancos:** gráfica de puntos con intervalo (un renglón por banco) del mes elegido, para `gap_estrellas` y `neg`, ordenada por el estimado.

Cada bloque va en un `ChartFrame` con "Cómo leerla". Desde cualquier bloque, el analista tiene "Abrir en el Explorador", que lleva `bancos`, `desde`, `hasta`, `familia` y `sentimiento` (si están fijados) a `/explorador`.

### 3.2 Pestaña Por versión

* Selector de un banco (la vista compara versiones dentro de un banco: los esquemas de versión no son comparables entre bancos).
* Gráfica de puntos con IC de Wilson de la proporción de `NEG` por versión, en orden cronológico (`first_seen`), con la mediana del banco como línea de referencia; la marca `u` como segunda serie.
* Tabla con versión, fechas, filas, `NEG` con IC, `u` y las tres familias principales; las versiones de menos de 50 negativas van en `OTRAS`.
* `Callout`: "Descriptivo: no hay pruebas de cambio de nivel entre versiones". Y la cobertura: "el 90.9 % de las reseñas tiene versión reconocida", con el número que devuelva la API.

## 4. Pruebas

* **API:** cada repositorio con datos en memoria; `cards` toma la última corrida y cae al mes anterior si falta; `daily` agrupa por día UTC; el signo del *gap* crudo coincide con `voc_nlp.ppi.targets` en un caso a mano; la normalización de versiones reproduce los ejemplos de `versions.py`; Wilson contra valores de referencia; `OTRAS` con menos de 50 reseñas; todas las rutas en `SAMPLE_PARAMS` (centinela).
* **Portal:** las tarjetas muestran insignia e intervalo; elegir un día abre el panel con dos listas y el aviso; el *brush* cambia la URL; el conmutador de familias cambia de vista sin otra petición; "Abrir en el Explorador" arma la URL con los filtros; `axe` sin violaciones.

## Terminado cuando

* [x] Las tarjetas y las series se recalculan después de cada delta (la caché vence en 10 minutos) y cada cifra muestra su versión de modelo y si es cruda o PPI. (Todas las consultas usan `cache=True`; cada bloque lleva la insignia "Con revisión humana" o "Solo modelo" y su procedencia.)
* [x] La serie diaria de 12 meses de los cinco bancos carga en menos de 3 segundos con la caché vacía, y su consulta factura menos de 1 GB (anotar la cifra). (533.5 MB y 2.7 s con la caché vacía; ver "Avance".)
* [x] El panel del día muestra las dos listas con el aviso de descripción.
* [x] La pestaña por versión reproduce las medianas por banco del reporte de 5.9 (BBVA: 39.7 % `NEG` y 18.5 % `u`), con la diferencia explicada si el corte de datos cambió. (BBVA 39.7 % y 18.5 %; ver la tabla en "Avance".)
* [x] F-19 (lectura de un pico como incidente) queda calificada en la FMEA con los controles de esta pantalla (aviso, sin umbrales, participación habitual al lado). (Calificada el 2026-10-26; ver "Avance".)

## Decisiones al implementar

* **Un repositorio por sección.** `sections/kpis/` sigue el patrón de la landing: `Protocol`, repositorio de BigQuery, repositorio en memoria y datos de muestra para `PORTAL_DATA=fixtures`. Las consultas agregan en SQL y el servicio arma las respuestas; `versions.py` (port de `normalize`) y `stats.py` (Wilson) son Python puro con su prueba.
* **Una ruta más que la tabla de la sección 2:** `GET /api/v1/kpis/model-changes` (versiones del modelo con `promoted_at`), que alimenta las anotaciones de la serie diaria. Sale de `model_versions` (la última fila de cada versión con `promoted_at`).
* **Tarjetas.** El mes objetivo es `period` o el último mes con PPI de `neg`; cada banco toma su último mes con PPI hasta ese mes (un banco sin PPI sale con `period: null`). `previous_year` solo existe si el banco tiene PPI de `neg` en el mismo mes del año anterior.
* **Serie diaria.** El rango se compara con `fecha` sin envolverla en `DATE()` (`fecha >= TIMESTAMP(@date_from) AND fecha < TIMESTAMP(DATE_ADD(@date_to, INTERVAL 1 DAY))`) para no estorbar la poda de particiones. Sin fechas, los últimos 90 días; más de 800 días da 422.
* **Base de las familias.** Nivel y participación usan las negativas de dos palabras o más con etiqueta de aspectos (la misma base que `daily_topic_labels`); la marca `u` es la parte de esas negativas con `flag_update`. En la pestaña por versión se sigue el reporte de 5.9: `neg_share` es negativas entre reseñas con sentimiento; `u_share` y las familias son la proporción entre las negativas de dos palabras o más con etiqueta de aspectos; `OTRAS` (menos de 50 reseñas) no entra en las medianas.
* **Tópicos.** Solo `curation_topics` de la versión vigente con audiencia producto o ingeniería (siempre traen nombre curado, así que `topic_catalog` no hace falta como respaldo del nombre). `share` es reseñas del tópico entre las negativas del mes.
* **Familias y tópicos no usan el rango global:** traen todo el historial de los bancos filtrados (las gráficas mensuales son de largo plazo); solo la serie diaria y los enlaces al Explorador usan `desde` y `hasta`.
* **Matriz.** La respuesta de `matrix` trae `period` en cada celda (se pide un banco a la vez desde la pantalla).
* **Pantalla.** Se conserva dygraphs para la serie diaria: el clic y el *brush* funcionan (el rango se escribe en la URL con `zoomCallback`, solo cuando la persona acerca; con `drawCallback` cada redibujo reescribía `desde` y `hasta`). Si más adelante se complica, queda abierta la opción de pasarla a D3. El resto de las gráficas son SVG con las primitivas de `charts/`.
* **Estado en la URL:** `vista` (`version`), `dia`, `familia`, `banco` (banco del detalle y de la vista por versión) y `mes` (matriz y comparación), además de los filtros globales.
* **Colores de las familias:** once tonos de la paleta de `tokens.css` (verdes, dorados y neutros); la marca `u` usa `--color-sent-neg`.

## Avance

* **API (2026-10-26):** `GET /api/v1/kpis/{cards,daily,daily-topics,monthly,families,topics,matrix,versions,model-changes}` (todas de rol lector, en `ROUTE_ROLES` y en `SAMPLE_PARAMS` del centinela), `openapi.json` y `schema.d.ts` regenerados. 35 pruebas nuevas en `test_kpis.py` (último mes con respaldo, año anterior, día UTC, signo del *gap* contra `voc_nlp.ppi.targets`, ejemplos de `versions.py`, Wilson, `OTRAS`, cobertura, SQL con un lector falso). `pytest services/api-backend` (153 pasan, 40 omitidas de BigQuery), `ruff`, `pyrefly` y `bandit` en verde.
* **Portal (2026-10-26):** `/cockpit` con las pestañas Diario y Por versión y los siete bloques de la sección 3.1; 16 pruebas nuevas (insignia e intervalo, panel del día, *brush*, conmutador sin otra petición, URL del Explorador, matriz, versión y `axe` en las dos pestañas). `npm run check`, `npm test` (82) y `npm run build` pasan; el cockpit es un trozo perezoso de 64 KB comprimido.
* **Vista previa local** (`PORTAL_DATA=fixtures`): se revisaron las tarjetas, la serie, el panel del día, las gráficas mensuales, familias, tópicos, matriz y comparación.
* **Bytes de cada consulta en dev** (`dry_run`, 2026-10-26): `kpi_estimates` 2.1 MB, alertas 0.0 MB, `drift_metrics` 0.5 MB, versiones del modelo 0.0 MB, aspectos por prompt 15.5 MB, serie diaria 533.5 MB (igual con 90 días que con 365: la vista de predicciones vigentes no deja podar particiones, pero queda por debajo del 1 GB, así que no hace falta la tabla de agregados), temas del día 640.9 MB, familias en nivel 570.1 MB, tópicos 595.2 MB, versiones 619.4 MB y 622.1 MB. Ninguna pasa del tope de 2 GB de la API. Con la caché vacía: serie diaria de 12 meses 2.7 s, familias 2.9 s, tópicos 4.7 s y temas de un día 4.2 s (la caché de 10 minutos absorbe las repeticiones).
* **Comparación con el reporte de 5.9** (medianas por banco entre versiones, `OTRAS` aparte; datos de dev al 2026-10-26):

| Banco | `NEG` (reporte) | `NEG` (API) | `u` (reporte) | `u` (API) | Versiones (reporte / API) |
| :--- | ---: | ---: | ---: | ---: | ---: |
| AZTECA | 15.2 % | 15.3 % | 9.7 % | 9.7 % | 225 / 225 |
| BANORTE | 19.1 % | 19.1 % | 7.4 % | 7.2 % | 30 / 30 |
| BBVA | 39.7 % | 39.7 % | 18.5 % | 18.5 % | 259 / 259 |
| NUBANK | 28.7 % | 28.7 % | 5.8 % | 5.8 % | 252 / 253 |
| SANTANDER | 28.6 % | 28.6 % | 7.7 % | 7.7 % | 176 / 176 |

  La cobertura de versión reconocida es 90.8 % (BBVA) frente al 90.9 % global del reporte. Las diferencias de una décima son del corte de datos (el reporte es del 2026-10-23). La primera comparación salió con 18.3 % de `u` en BBVA porque la base eran todas las negativas; con la base del reporte (dos palabras o más con etiqueta) coincide. Dos errores que la comparación y el `dry_run` destaparon: `OTRAS` se calculaba con negativas en vez de reseñas y la consulta de familias en nivel no compilaba en BigQuery (alias repetido).
* **F-19 calificada (2026-10-26, decisión del autor):** S 1, O 1, D 1 (RPN 1), con los controles de esta pantalla; es un hallazgo de la investigación y el producto no está en producción. Quedó escrita en la [FMEA](../../governance/ethical_fmea_matrix.md); el paso 10 solo la confirma.

## Revisión del autor tras el despliegue en dev (2026-10-26)

El autor revisó el cockpit en dev con datos reales. Esta sección guarda los comentarios, lo que se encontró al investigarlos y el plan. Nada de esto está implementado todavía.

### Hallazgos al investigar

* **Anomalías vacías: error propio.** `drift_metrics` sí trae z en todas las filas de familias (hasta |z| = 34), pero guarda `period` como fecha (`2026-09-01`) y la unión con el nivel de familias usa `2026-09`: nunca coincide y todas las celdas salen grises. Además tiene 125 meses (desde 2016-05) y ninguna fila con umbral (la política v2 aún no está en esas series), así que no habrá bordes de alerta.
* **Los botones 30 días, 90 días, 12 meses y Todo sí funcionan** (probado en local: cambian la URL y las fechas). Lo que no se nota es que solo la serie diaria usa el rango, y que los botones no muestran cuál está activo.
* **Las gráficas mensuales sí existen** ("Reseñas negativas por mes" y "Brecha en estrellas por mes", debajo de la serie diaria), pero se dibujan con todo el historial (BBVA desde 2011-04, los demás desde 2020), con meses de 2 reseñas y rangos enormes, y no se leen.
* **Tópicos "sin familia": las familias se perdieron al cargar la curaduría** (análisis completo abajo).
* **Versiones:** BBVA tiene 259 versiones; el eje de categorías con todas es ilegible. Se rediseña.

### Comentarios y decisiones

| # | Comentario del autor | Decisión |
| :--- | :--- | :--- |
| 1 | Encabezados fijos en todas las tablas de datos | Sí: `sticky` en el encabezado de la tabla de `ChartFrame` y de la tabla por versión |
| 2 | Promedio móvil y su convivencia con el panel del día | Un selector "Suavizado: sin / 7 / 14 / 28 días" (por defecto 7), una línea por banco (cinco, no veinte), promedio ponderado de ventana que termina en cada día (suma de negativas entre suma de predichas). El dato diario crudo queda como línea tenue solo con uno o dos bancos. Se calcula en el frontal; dygraphs se conserva. El clic sigue eligiendo **un día** y el panel dice "Temas del día X (no del promedio)": `daily_topic_labels` guarda solo el top 5 de cada día, así que no se puede sumar una ventana sin una consulta nueva (unos 600 MB), que queda como opción futura. La leyenda de hover de dygraphs (que se encima con el eje Y) pasa a una franja propia con fondo |
| 3 | Familias: gráfico demasiado grande, etiqueta del prompt cortada, `u` no es familia, etiquetas ocupan dos renglones | Altura fija; leyenda vertical a la derecha que también filtra; el nombre del prompt con espacio propio; `u` sale de las etiquetas y se muestra aparte como la marca "habla de una actualización", con su propia mini-gráfica |
| 4 | Anomalías no se entiende | Arreglar el cruce de periodos, limitar a los últimos 24 meses con celdas grandes, leyenda del z (escala "z robusto"; sin umbral no hay borde ni se promete alerta) |
| 5 | Tópicos sin familia; audiencia a la izquierda | Es un error de carga (ver abajo), no de curación. La audiencia (ingeniería / producto) pasa junto al nombre del tópico; el gráfico y las familias quedan del otro lado |
| 6 | Vista por versión ilegible | Rediseño (ver abajo) |
| 7 | Barra de filtros poco clara y sin movimiento; que sea fija | "2 de 5 bancos seleccionados"; estado activo en los atajos; nota de qué bloques usan el rango; las gráficas mensuales tienen su propio selector (12, 24 meses o todo; 24 por defecto) y ocultan los meses con muy pocas reseñas; la barra queda fija al hacer scroll |
| 8 | ¿Mes contra mes, año contra mes, acumulado? | Selector en las tarjetas: "vs. mes anterior" y "vs. año anterior" (hoy solo hay el segundo). Mes contra mes es más ruidoso (cada punto trae su intervalo). El acumulado del año no se hace |
| 9 | Títulos de sección como parte del header | Una sola franja fija: filtros a la izquierda y, a la derecha, la sección que está a la vista con un menú para saltar a otra (IntersectionObserver); se quitan los títulos grandes del cuerpo (los de cada gráfica se quedan). Evita apilar tres franjas fijas (encabezado, filtros y secciones) |

### Vista por versión (rediseño)

* Un banco siempre filtrado (el primero por defecto); los filtros de banco van **debajo** del aviso "Descriptivo", no encima del título.
* Barras apiladas por día (como el análisis preliminar), coloreadas por versión: las 8 principales del rango y el resto agrupado; los despliegues se leen como cambios de color.
* Filtro de sentimiento (todas, negativas, neutras, positivas) y rango de 90 días por defecto.
* Ruta de API nueva (conteos por día, versión y sentimiento, para un banco y un rango); la tabla con IC de Wilson y las medianas quedan debajo, con la mediana visible y no escondida detrás de los puntos.

### Alcance de la corrección de la curaduría

**Causa.** `curation_rows` (`services/ml-inference/src/ml_inference/load_local.py`) separa `familia_correcta` por comas, pero `experiments/analytics/data/topics/phase4_v0/revision_topicos.csv` las separa con `|` (`PR | UX | TR | u`). Al quitar los espacios queda `PR|UX|TR|u`, que no es una de las 11 familias, y se descarta. Como `familia_correcta` no viene vacía, tampoco se usa `familia_mayoritaria` como respaldo.

**Qué datos están mal.** Solo `curation_topics.families` de `topics_v1`: 35 filas (35 tópicos, un solo `curator_hash`, cargadas el 2026-10-25 09:25:51 por la corrida `backfill-20261022-20261025T092551`). Las familias están vacías en todas, salvo dos tópicos cuya lista tenía un solo código (15 y 17, `FA`). De los 35, 11 son de producto, 8 de ingeniería y 16 sin valor; los 19 útiles tienen al menos una familia válida en el CSV.

**Qué no está mal** (verificado contra el CSV y BigQuery): `audience` (11 + 8 + 16, coincide con la regla), nombres curados, coherencia, tema nuevo, `topic_assignments`, `topic_catalog`, `topic_model_current` y `daily_topic_labels` (esas vistas solo leen nombre y audiencia, no familias). El comando `seed` no toca la curaduría (carga versiones y políticas), así que no hace falta correrlo.

**Por qué no basta volver a correr `load-local`.**

* Corre los siete pasos (artefactos, elegibilidad leyendo el TDS, predicciones, familias, embeddings, tópicos, oro) y registra tres corridas nuevas en `inference_runs`: mucho más de lo que hay que corregir.
* El escritor (`StagingMergeWriter`) solo inserta las claves que no existen, y la clave de la curaduría (`topic_model_version`, `topic_id`, `curator_hash`) no incluye `curated_at`: una recarga con el mismo curador no actualiza ninguna fila.

**Corrección propuesta.**

1. **Código** (`ml-inference`, área Inferencia): `curation_rows` separa por `|` y por coma, descarta lo que no es una de las 11 familias (`u` y `s` son marcas; `SIN` y `FQ` no son familias; `MEZCLA` deja la lista vacía y no usa el respaldo) y solo usa `familia_mayoritaria` si no queda ninguna y no es `MEZCLA`. Prueba con los renglones reales del CSV (`PR | UX | TR | u`, `u | SIN | AC | LE | FA`, `MEZCLA`).
2. **Carga acotada:** un subcomando `load-curation` que solo escribe `curation_topics`, con la clave ampliada con `curated_at`. La tabla es de historial (la vista toma la última fila por tópico, y el HITL de tópicos del paso 9 también inserta filas nuevas), así que se agregan 35 filas nuevas con `curated_at` actual y las viejas se conservan como historial. No toca ninguna otra tabla ni registra corridas de inferencia.
3. **Verificación:** consulta de `curation_topics` por `audience` y `ARRAY_LENGTH(families)`; la API `GET /api/v1/kpis/topics` devuelve familias; las vistas no cambian.
4. **Frontal** (cockpit): sin cambio de datos. Las familias de cada tópico se muestran con nombre (primeras tres y "+n"), "sin familia" solo cuando de verdad no hay, y la audiencia pasa junto al nombre. La familia fijada con `?familia=` atenúa los tópicos que no la tienen (ya funciona; hoy atenúa todos).
5. **Documentación:** nota en el contrato (`families` de la curaduría se carga de `familia_correcta`, en el orden de importancia que dio el curador) y en el backlog del paso.

**Decisiones del autor (2026-10-26):**

* `SIN` se descarta. `FQ` (un solo caso, tópico 38: `UX | CO | TR | FQ | u`) tampoco es una de las 11 familias y no hay forma de saber qué quiso escribir el curador (probablemente `FA`, vecina de `Q` en el teclado), así que se descarta; si es `FA`, se corrige en el CSV y se vuelve a correr `load-curation`.
* Se corrige el flujo original de `load-local` (no solo el comando nuevo) y se elimina la curaduría anterior, que era un error de carga y no una decisión del curador. Autorizadas la escritura de las 35 filas y la limpieza de la tabla.
* El cambio vive en `services/ml-inference/` (área Inferencia): se hizo en esta misma sesión, con su prueba, sin tocar nada más de ese servicio.

**Hecho (2026-10-26):**

* `curation_families` (nueva, con sus pruebas con renglones reales del CSV) y `curation_rows` la usan; `Loader.curation` escribe con `curated_at` en la clave, y `load-local` y `python -m ml_inference load-curation` comparten ese método. `pytest services/ml-inference` (cobertura 98 %), `ruff`, `pyrefly` y `bandit` en verde.
* Respaldo de las 35 filas viejas en JSON (copia local de la sesión, fuera de git), `load-curation` en dev (35 filas nuevas, `curated_at` 2026-10-26 15:45:10) y `DELETE` de las 35 viejas (`curated_at` 2026-10-25 09:25:51). Verificado: 19 tópicos útiles con familias (producto 3.1 de promedio, ingeniería 2.9) y los 16 sin valor vacíos; `topic_model_current` sigue en `topics_v1`; `GET /api/v1/kpis/topics` devuelve las familias.

### Plan por pasadas

1. **Corrección de datos de la curaduría** (arriba): hecha el 2026-10-26.
2. **Primera pasada del cockpit (hecha el 2026-10-26, falta desplegar):** cruce de periodos de las anomalías (API, con prueba), anomalía con ventana de 24 meses y leyenda, familias (altura fija, leyenda vertical, `u` aparte, prompt visible), tópicos (audiencia junto al nombre, familias con nombre), encabezados de tabla fijos, barra de filtros (texto, estado activo, nota del rango, fija), franja con la sección a la vista, selector de ventana en las gráficas mensuales y ocultar meses con pocas reseñas, selector de comparación en las tarjetas.
3. **Segunda pasada (hecha el 2026-10-26, falta desplegar):** suavizado y franja de leyenda de la serie diaria, y la vista por versión nueva (ruta de API, barras apiladas, filtro de sentimiento).

### Terminado cuando (revisión)

* [x] `curation_topics.families` trae las familias del CSV para los 19 tópicos útiles de `topics_v1` (hecho el 2026-10-26). [x] El cockpit las muestra con nombre y "sin familia" solo aparece donde corresponde.
* [x] La anomalía de familias muestra z por familia y mes (24 meses) y se entiende sin leer el código. (Revisado en local con datos de dev.)
* [x] Las tablas de datos tienen el encabezado fijo; la barra de filtros y la sección a la vista quedan fijas al hacer scroll.
* [x] La serie diaria tiene suavizado de 7, 14 y 28 días, sin romper el panel del día, y su leyenda no tapa el eje.
* [x] La vista por versión muestra un banco, barras por día coloreadas por versión y filtro de sentimiento.

### Primera pasada del frontal (2026-10-26)

* **API:** `drift_metrics` se lee con `period` como `YYYY-MM` (`SUBSTR(CAST(period AS STRING), 1, 7)`) y el servicio lo normaliza también, así que el z ya se une con el nivel de familias; `BankCard` trae `previous_month` además de `previous_year` (`month_before`, con prueba que cruza el año). `openapi.json` y `schema.d.ts` regenerados.
* **Barra de filtros fija** (`sticky`, debajo del encabezado): "N de 5 bancos seleccionados", atajos con estado activo y, a la derecha, el menú "Sección: …" que sigue el scroll y salta a cada sección (`SectionNav`). Se quitaron los títulos grandes del cuerpo (quedan como encabezados ocultos para lectores de pantalla). La serie diaria aclara que el rango aplica solo a ella.
* **Tarjetas:** selector "Mismo mes del año anterior / Mes anterior".
* **Gráficas mensuales:** selector 12 / 24 meses o todo (24 por defecto) y se ocultan los meses con menos de 100 reseñas.
* **Familias:** últimos 24 meses, altura fija (260 px) con el texto a tamaño natural, leyenda vertical a la derecha que resalta la familia (con las negativas del último mes), etiqueta del prompt a la vista, y la marca `u` como "Habla de una actualización" en su propia gráfica (en la anomalía, en una fila aparte). La anomalía usa celdas de al menos 24 px, una leyenda del z y una nota de que esas series aún no tienen umbral.
* **Tópicos:** la audiencia (Producto / Ingeniería) va junto al nombre; las familias salen con nombre (tres y "+n") y "sin familia asociada" solo si no hay.
* **Tablas:** el encabezado de `Table` es fijo (`sticky`), también en "Ver datos" y en la tabla por versión.
* **Pruebas:** 92 en el portal (10 nuevas: barra, atajo activo, menú de secciones y su seguimiento del scroll, comparación con el mes anterior, tópicos con y sin familias, z de la anomalía, meses ocultos, `shiftMonths`, encabezados fijos) y 154 en la API; `check`, `tsc` y `build` en verde. Revisado en local con datos de dev. **Queda para la segunda pasada:** suavizado y leyenda de la serie diaria, vista por versión nueva y, opcional, la ventana de temas.

### Segunda pasada del frontal (2026-10-26)

* **Suavizado de la serie diaria** (solo frontal, `smoothing.ts`): selector "Sin suavizar / 7 / 14 / 28 días" (7 por defecto), una línea por banco. Cada punto es el promedio ponderado de la ventana que termina en ese día (suma de negativas entre suma de predichas; el *gap* pesa por reseñas predichas), no el promedio de las proporciones diarias. La consulta pide siempre 27 días de más al inicio del rango para que el primer día ya tenga su ventana completa; con uno o dos bancos se dibuja el dato diario como línea de fondo. La leyenda y los valores al pasar el cursor van en una franja propia sobre la gráfica (`labelsDiv`), ya no encima del eje. El clic sigue eligiendo un día y el panel aclara "no del promedio de N días".
* **Ruta nueva `GET /api/v1/kpis/versions/daily`** (`bank`, `date_from`, `date_to`, `sentiment` = `ALL` / `NEG` / `NEU` / `POS`): reseñas por día y versión de un banco. Se normaliza la versión (`versions.py`), las 8 versiones con más reseñas del rango salen con nombre y el resto (más las reseñas sin versión reconocida) en `OTRAS`; las versiones vienen en orden cronológico con su primer día. Mide 544 MB y 2.2 s con la caché vacía en dev (BBVA, 90 días). En la sentinela y con sus pruebas.
* **Pestaña Por versión rediseñada:** el aviso "Descriptivo" y la cobertura van primero; debajo, el selector de banco (uno siempre elegido) y el filtro de sentimiento; barras apiladas por día coloreadas por versión (los cambios de color son los despliegues, con líneas punteadas en la primera aparición de cada versión) y una leyenda con "desde" y reseñas. Debajo, la tabla de las versiones activas en el rango (con IC de Wilson, marca `u` y familias principales, encabezado fijo) y la mediana del banco escrita en el texto. El rango es el de la barra de filtros (90 días por defecto). Se quitó la gráfica de puntos por versión.
* **Pruebas:** 106 en el portal (14 nuevas: ponderación del promedio, ventana, 27 días de más, línea de fondo, leyenda, panel del día, aviso antes de los filtros, leyenda y tabla, filtro de sentimiento y de banco que vuelven a pedir los datos, `axe`) y 157 en la API; `check`, `tsc`, `build`, `ruff`, `pyrefly` y `bandit` en verde. Revisado en local con datos de dev.
* **Pendiente:** la ventana de temas de varios días (necesitaría una consulta nueva de unos 600 MB) y el SVG oficial del logotipo.

## Segunda revisión del autor y rediseño en tres vistas (2026-10-26)

Tras ver la primera y la segunda pasada en dev, el autor pidió más ajustes y una reorganización. Decisiones:

### Reorganización

* El grupo del sidebar pasa a llamarse **Dashboard** y el cockpit se divide en tres vistas, cada una con su ruta y su entrada en el sidebar (`/cockpit` se conserva para la primera, porque la landing y el Explorador ya apuntan a ella):
  * **Cockpit** (`/cockpit`): la tabla de comparación (con mancuerna) y la matriz estrellas × texto.
  * **Evolución** (`/evolucion`): serie diaria (dygraphs, suavizado y panel de temas del día), mensual con PPI y por versión.
  * **Tópicos** (`/topicos`): familias y tópicos.
* "Inicio" sigue en su grupo. El título "Cockpit" sale del cuerpo de la pantalla (queda solo en el sidebar; se conserva un `h1` oculto para lectores de pantalla). Se descarta poner el título en el encabezado.
* Se quita el menú "Sección:" de la barra de filtros (con dos o tres bloques por vista ya no hace falta). La barra de filtros sigue fija.
* El sidebar queda **fijo** al hacer scroll.
* La navegación del sidebar conserva solo los parámetros globales (`bancos`, `desde`, `hasta`) y `kpi`; `dia`, `familia`, `banco` y `mes` son de cada vista.

### Cambios por bloque

* **KPI global (`?kpi=`):** botones "Reseñas negativas / Brecha en estrellas / Quejas con 4–5★" en la tabla, la serie diaria y el mensual, ligados a un solo estado (cada bloque muestra sus botones). `GET /api/v1/kpis/monthly` admite además `estrellas_POS_texto_NEG` (los datos ya están en `kpi_estimates`).
* **Tabla en vez de tarjetas** (solo en Cockpit; la landing conserva las suyas): bancos en filas, un KPI a la vez con columnas referencia `[lo, hi]`, actual `[lo, hi]`, diferencia (sin intervalo propio), una **mancuerna** (referencia → actual, con bigotes de cada intervalo, escala compartida por KPI) y alertas abiertas. Botones "vs. mes anterior / vs. año anterior", el texto "Comparando vs ago 2026" debajo y "Con revisión humana" como subtítulo de la tabla. Sin colores de bueno o malo, solo flecha. Se quita el bloque "Comparación entre bancos".
* **Mensual con PPI** (se conserva, con sus intervalos): un solo bloque con botones por KPI en lugar de dos bloques apilados.
* **Serie diaria:** leyenda propia en una sola línea (los valores al pasar el cursor siguen en la franja de dygraphs); el panel de temas sigue siendo de un solo día. El suavizado se queda como está.
* **Tópicos:** filtro de bancos con casillas (por defecto los del filtro global) y matriz **3 × 2** con paginador (‹ ›, "1–6 de 19", flechas del teclado), ordenada por volumen; cada panel es un tópico con una línea por banco (parte de las negativas por mes). La familia resaltada atenúa los paneles que no la tienen.
* **Versiones:** tooltip del día (fecha, total y detalle por versión, con la columna resaltada) y gráfica a todo el ancho.
* **Textos:** "Habla de una actualización (u)" y "Marca u" pasan a "Relacionada con una actualización" en toda la interfaz (el nombre técnico queda en el glosario).

### Errores propios que se corrigen

* `useChartSize` mide el contenedor solo al montar; las gráficas que aparecen después de que llegan los datos se quedaban con el ancho de respaldo (la de versiones a 640 px). Se corrige el hook.
* El mapa de calor de anomalías medía 8 px más que su contenedor y mostraba un scroll horizontal.

### Descartado

* Título del cockpit en el encabezado (redundante con el sidebar fijo).
* Niveles de agregación (día, semana, mes) en las gráficas mensuales: el PPI solo existe por mes y la diaria ya cubre el dato crudo.
* Fusionar la serie diaria con la mensual: primero se ve si estos cambios mejoran la lectura.
* Intervalo propio de la diferencia entre dos estimaciones.

### Plan

1. Correcciones y división en tres vistas (rutas, sidebar, parámetros).
2. Cockpit: KPI global, tabla y mancuerna.
3. Evolución: mensual con botones por KPI.
4. Tópicos: filtro de bancos y matriz con paginador.
