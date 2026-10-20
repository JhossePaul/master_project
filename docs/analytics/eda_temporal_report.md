# Patrones temporales: trimestres, sprints y quincena (EPIC-5, feature 5.2)

> **Estado (2026-10-19): vigente** (versión 2, que reemplaza a la 1 descrita en el historial). La sección "Respuesta con la plata" ya incorpora el sentimiento del texto. Índice: [`README.md`](README.md).

* **Fecha:** 2026-10-18 (versión 2).
* **Snapshot:** `tds_20261016T054714Z`, periodo 2020-01-01 a 2026-10-13, con los cinco bancos presentes.
* **Código:** [`eda_temporal.py`](../../experiments/analytics/src/voc_analytics/eda/eda_temporal.py), con las definiciones compartidas en [`temporal_context.py`](../../experiments/analytics/src/voc_analytics/labeling/temporal_context.py).
* **Métricas:** [`temporal_metrics.json`](eda/temporal_metrics.json).
* **Pregunta:** ¿hay ciclos trimestrales, quincenales o de release que obliguen a cambiar el diseño muestral de la plata?

## Hipótesis del autor

| Código | Hipótesis |
| :--- | :--- |
| H-T1 | Los releases grandes de la banca tradicional siguen el calendario trimestral |
| H-T2 | Con scrum, parches y features incrementales salen cada ~2 semanas |
| H-T3 | Hay más incidencias en quincena ("BBVA se cae en quincena", porque se liberan cambios) |

**Confusor de H-T3:** en México la quincena es día de pago, con picos de transacciones. Una caída en quincena puede venir de la carga y no del despliegue.

## Método

* **Sin supuestos sobre las estrellas.**
  * La versión 1 de este reporte usaba la proporción de 1★ como indicador de incidencia. Eso supone que 1★ es negativo, que es justo el sesgo que el proyecto corrige.
  * Esta versión mide el **volumen total** y el **volumen de cada nivel de estrellas por separado**, cada uno relativo a su propia media. La mezcla de estrellas se reporta solo como descripción.
  * El sentimiento real de esas reseñas se medirá con la plata (`prompt_v3`), que trae estos atributos temporales por fila.
* **Calendario de releases desde `version_app`:**
  * la fecha de release es el día en que la versión acumula su 5.ª reseña;
  * se excluyen las versiones `BETA` y las de menos de 30 reseñas;
  * se quita el sufijo `-minApiNN`;
  * "feature" es la primera versión de cada `mayor.menor`.
* **Quincena** (*biweekly payday*): ±1 día alrededor de cada pago, es decir, los días 14–16 y el penúltimo día, el último y el día 1. Cubre el 19.7 % de los días. Las fechas pasan de UTC a la hora de Ciudad de México.
* **Día pico:** el volumen de la serie es al menos 3 veces su mediana móvil de 29 días, con al menos 20 reseñas. Se calcula para el total y para cada estrella.
* **Limitaciones:**
  * `fecha` es la última edición de la reseña;
  * la fecha de release se estima con retraso;
  * la definición de "feature" depende del esquema de versiones de cada banco;
  * hay pocos días pico por banco y serie (0–68).

## Hallazgos

### H-T2 (cadencia de sprint): se confirma de forma parcial

| Banco | Versiones (2020–2026) | Mediana entre versiones | P25–P75 | Intervalos de 11–17 días |
| :--- | ---: | ---: | :---: | ---: |
| NUBANK | 263 | **7 días** | 7–8 | 11 % |
| BBVA | 189 | **11 días** | 7–18 | 28 % |
| AZTECA | 187 | **12 días** | 8–16 | 37 % |
| SANTANDER | 96 | 23 días | 13–34 | 25 % |
| BANORTE | 62 | 36 días | 23–50 | 10 % |

* **BBVA y AZTECA** publican cada 1.5–2 semanas, compatible con sprints quincenales.
* **SANTANDER y BANORTE** tienen ciclos de 3–5 semanas.
* **NUBANK tiene un *release train* semanal:** 177 de 263 versiones salen en **jueves**. El jueves es también su día de más volumen (índice 1.30), y ese aumento viene de **4★ (1.30) y 5★ (1.37)**; el 1★ casi no cambia (1.07).
  * Es compatible con que la app pida calificar después de actualizar. Es una hipótesis: no hay datos de la app que lo confirmen.

### H-T1 (trimestres): no hay evidencia

* Los releases de feature se reparten igual entre los tres meses del trimestre, y casi ningún intervalo entre features cae en 80–100 días.
* El volumen por mes del trimestre no cambia de forma consistente en ninguna serie.

### H-T3 (quincena): sube la actividad en todas las estrellas

**Volumen en quincena contra el resto de los días** (razón de medias diarias; entre paréntesis, años de 7 con razón mayor que 1):

| Banco | Total | 1★ | 2★ | 3★ | 4★ | 5★ |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| BANORTE | 1.36 (7) | 1.22 (7) | 1.31 (7) | 1.33 (7) | 1.40 (7) | 1.38 (7) |
| SANTANDER | 1.24 (7) | **1.48** (7) | 1.37 (7) | 1.35 (7) | 1.23 (7) | 1.17 (7) |
| BBVA | 1.16 (7) | 1.16 (6) | 1.14 (6) | 1.15 (6) | 1.15 (7) | 1.17 (7) |
| AZTECA | 1.07 (7) | 1.10 (6) | 1.08 (6) | 1.10 (7) | 1.08 (7) | 1.07 (7) |
| NUBANK | 1.42 (5) | 1.12 (6) | 1.08 (4) | 1.24 (4) | 1.43 (6) | **1.50** (4) |

1. **La quincena aumenta el volumen de *todos* los niveles de estrellas**, y de forma consistente año con año en los bancos tradicionales. Es un efecto de actividad: más uso de la app trae más reseñas de todo tipo.
2. **La mezcla de estrellas cambia distinto según el banco:**
   * **BBVA y AZTECA:** la quincena es igual en todas las estrellas y la mezcla no cambia (BBVA: 28.2 % de 1★ en quincena y en el resto).
   * **SANTANDER:** suben más las estrellas bajas, y el 1★ pasa de 16.4 % a 19.5 %.
   * **NUBANK:** suben más las altas. El 5★ pasa de 72.1 % a 76.4 % y el 1★ baja de 15.2 % a 12.0 %. El efecto es irregular entre años (4 de 7) y concentrado en el día 1 y del 13 al 17 ([figura](eda/figures/temporal_day_of_month.png)). Es compatible con campañas o peticiones de calificación ligadas al depósito, no con incidencias.
   * Como advierte el autor, **nada de esto dice si esas reseñas son negativas**: un 5★ de quincena puede describir una falla.
3. **Los días pico se concentran en quincena en todas las series** (los cinco bancos juntos, 19.7 % esperado):

   | Serie | Días pico | En quincena | p binomial |
   | :--- | ---: | ---: | ---: |
   | Total | 119 | 29 % | 0.012 |
   | 1★ | 158 | 37 % | < 0.001 |
   | 2★ | 84 | 32 % | 0.005 |
   | 3★ | 115 | 33 % | < 0.001 |
   | 4★ | 95 | 33 % | 0.002 |
   | 5★ | 107 | 25 % | 0.094 |

   Los picos de estrellas bajas y medias se concentran más que los de 5★. Sin la plata no se puede afirmar que sean incidencias.
4. **BBVA y BANORTE publican menos versiones en quincena** (12 % y 10 % contra 19.7 % esperado). Es compatible con una ventana de congelamiento alrededor del día de pago. AZTECA, SANTANDER y NUBANK publican en su proporción.

### Volumen alrededor de los releases

| Banco | Total, días 0–3 contra la semana previa | Series que más suben |
| :--- | ---: | :--- |
| BANORTE | 1.24 | Todas (2★ 1.48, 3★ 1.34, 1★ 1.33) |
| SANTANDER | 1.12 | 1★ 1.31 |
| BBVA | 1.11 | Todas por igual (1.07–1.13) |
| AZTECA | 1.04 | 1★ 1.20, 2★ 1.25 |
| NUBANK | 1.05 | 4★ 1.10 |

* **Días pico tras un release** (días 0–3, que son el 11 % de los días): solo se concentran los picos de **4★** (22 %, p = 0.001), de **5★** (19 %, p = 0.013) y del total (17 %, p = 0.037). Los de 1★ no (9 %).
* **Lectura:**
  * un release mueve sobre todo reseñas de estrellas altas, quizá por la petición de calificación al actualizar;
  * las estrellas bajas suben en algunos bancos (BANORTE, SANTANDER, AZTECA) sin formar picos;
  * "BBVA se cae en quincena porque se liberan cambios" no encuentra apoyo: BBVA publica menos en quincena y su volumen tras un release sube parejo en todas las estrellas.

## Implicaciones para el muestreo de la plata

* **No hace falta un estrato de quincena, día de la semana ni trimestre.**
  * El muestreo es aleatorio dentro de banco × año × estrellas: cada día entra en proporción a su volumen, en cada nivel de estrellas.
  * Los efectos de quincena y release, que mueven a todas las estrellas, quedan representados.
* **Atributos guardados por fila** en `rows.parquet` (no son estratos):
  * `dia_mes` y `quincena`;
  * `dias_desde_version` y `dias_desde_feature`;
  * `dia_pico_total` (pico de volumen total) y `dia_pico_estrella` (pico del mismo nivel de estrellas que la reseña).
  * Con la plata se podrá medir el **sentimiento del texto** según el contexto temporal: por ejemplo, si los 5★ de quincena de NUBANK o los de los jueves esconden quejas.
* **Monitoreo (5.7):** las ventanas de deriva deben respetar la cadencia de cada banco (semanal en NUBANK, 2–5 semanas en el resto).

## Respuesta con la plata

Con el sentimiento del texto y dentro de cada banco × estrellas ([reporte de la plata](silver_v0_report.md)):

* **Quincena:** las 5★ de quincena no son más negativas.
* **Días pico:** en SANTANDER y AZTECA las 5★ y las 3★ esconden más quejas, un patrón de incidencia.
* **NUBANK:** en sus días pico y sus jueves las 5★ son más positivas que el resto.

## Historial

| Versión | Cambio |
| :--- | :--- |
| 1 | Proporción de 1★ como resultado y ventana fija de quincena (días 14–16 y 30–2) |
| 2 | Volumen total y por estrella sin supuestos sobre su sentido; ventana de quincena de ±1 día alrededor del 15 y del último día del mes; picos por serie; atributos neutrales en la plata |
