# Paso 3. Feature 7.5: Cockpit diario de KPIs

* **Estado (2026-10-26):** Implementado y probado con datos sintéticos; faltan las verificaciones contra BigQuery de dev (ver "Terminado cuando").
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

  Las versiones con menos de 50 negativas en el banco se agrupan en `OTRAS`, como en los experimentos. El IC de Wilson se calcula en Python (`sections/kpis/stats.py`, con prueba contra valores conocidos). La prueba del port reproduce los ejemplos del docstring de `versions.py` (`7.0.9.45841` → `7.0.9`, `11.33.210429` → `11.33`, `9.38.75-minApi28` → `9.38.75`, `2.6.2 - BETA` → nula).

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

* **API:** cada repositorio con datos en memoria; `cards` toma la última corrida y cae al mes anterior si falta; `daily` agrupa por día UTC; el signo del *gap* crudo coincide con `voc_nlp.ppi.targets` en un caso a mano; la normalización de versiones reproduce los ejemplos de `versions.py`; Wilson contra valores de referencia; `OTRAS` con menos de 50 negativas; todas las rutas en `SAMPLE_PARAMS` (centinela).
* **Portal:** las tarjetas muestran insignia e intervalo; elegir un día abre el panel con dos listas y el aviso; el *brush* cambia la URL; el conmutador de familias cambia de vista sin otra petición; "Abrir en el Explorador" arma la URL con los filtros; `axe` sin violaciones.

## Terminado cuando

* [x] Las tarjetas y las series se recalculan después de cada delta (la caché vence en 10 minutos) y cada cifra muestra su versión de modelo y si es cruda o PPI. (Todas las consultas usan `cache=True`; cada bloque lleva la insignia "Con revisión humana" o "Solo modelo" y su procedencia.)
* [ ] La serie diaria de 12 meses de los cinco bancos carga en menos de 3 segundos con la caché vacía, y su consulta factura menos de 1 GB (anotar la cifra).
* [x] El panel del día muestra las dos listas con el aviso de descripción.
* [ ] La pestaña por versión reproduce las medianas por banco del reporte de 5.9 (BBVA: 39.7 % `NEG` y 18.5 % `u`), con la diferencia explicada si el corte de datos cambió.
* [ ] F-19 (lectura de un pico como incidente) queda calificada en la FMEA con los controles de esta pantalla (aviso, sin umbrales, participación habitual al lado); se anota en el paso 10.

## Decisiones al implementar

* **Un repositorio por sección.** `sections/kpis/` sigue el patrón de la landing: `Protocol`, repositorio de BigQuery, repositorio en memoria y datos de muestra para `PORTAL_DATA=fixtures`. Las consultas agregan en SQL y el servicio arma las respuestas; `versions.py` (port de `normalize`) y `stats.py` (Wilson) son Python puro con su prueba.
* **Una ruta más que la tabla de la sección 2:** `GET /api/v1/kpis/model-changes` (versiones del modelo con `promoted_at`), que alimenta las anotaciones de la serie diaria. Sale de `model_versions` (la última fila de cada versión con `promoted_at`).
* **Tarjetas.** El mes objetivo es `period` o el último mes con PPI de `neg`; cada banco toma su último mes con PPI hasta ese mes (un banco sin PPI sale con `period: null`). `previous_year` solo existe si el banco tiene PPI de `neg` en el mismo mes del año anterior.
* **Serie diaria.** El rango se compara con `fecha` sin envolverla en `DATE()` (`fecha >= TIMESTAMP(@date_from) AND fecha < TIMESTAMP(DATE_ADD(@date_to, INTERVAL 1 DAY))`) para no estorbar la poda de particiones. Sin fechas, los últimos 90 días; más de 800 días da 422.
* **Base de las familias.** Nivel y participación usan las negativas de dos palabras o más con etiqueta de aspectos (la misma base que `daily_topic_labels`); la marca `u` es la parte de esas negativas con `flag_update`. En la pestaña por versión, `neg_share` es negativas entre predichas y `u_share` es la marca `u` entre las negativas de la versión (definición propia: el reporte de 5.9 es la referencia a comparar).
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
* **Pendiente (necesita BigQuery de dev):** medir con `dry_run` la serie diaria de 12 meses (debe facturar menos de 1 GB y cargar en menos de 3 s con la caché vacía; si no, se propone la tabla de agregados diarios), comparar las medianas de BBVA con el reporte de 5.9 (39.7 % `NEG` y 18.5 % `u`) y anotar F-19 en la FMEA en el paso 10.
