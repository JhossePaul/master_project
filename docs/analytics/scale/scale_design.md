# Plan de 5.7: escala, ciclo de vida y monitoreo

> **Estado (2026-10-22): aprobado por el autor; ejecutado** (resultados en [`scale_report.md`](scale_report.md)). E1: medir en Cloud Run. E2: medir int8. E3: reabierta (sección 6). Feature 5.7 de [`epic_5.md`](../../backlog/epic_5.md). Cierra las decisiones P7-1 a P7-4 y P7-6 a P7-8 del [registro](../../backlog/epic_5.md#decisiones-pendientes). Lo que depende del predictor elegido (incidentes y versiones) está en 5.9. Nada se despliega en GCP sin aprobación del autor. Índice: [`README.md`](../README.md).

## 1. Lo que ya existe

| Insumo | Dónde | Qué da |
| :--- | :--- | :--- |
| M4 RoBERTuito con pesos, 3 semillas | `data/models/weights/M4_robertuito_s*_ppi/` | Modelo desplegable (218 MB en fp16) con su T de calibración (5.6) |
| Velocidad medida | [Reporte de 5.6](../calibration/calibration_report.md), §3.3 | ~2 500 textos/s en la T4; 39–53 en CPU (Mac M2, sin ordenar por longitud) |
| Corpus | Snapshot `tds_20261016T054714Z` | 2 649 047 filas, 1 383 138 textos únicos, mediana de 24 caracteres |
| Volumen reciente | `selective_v0_metrics.json` | ~3 493 textos únicos por semana (~500 al día) |
| Costo de Gemini por texto | Corrida de familias de 5.5 | $3.64 por 40 382 negativas (~$0.09 por 1 000) |
| Límites de Cloud Run en la infraestructura | `infra/modules/cloud_run.py` | Los Jobs actuales usan 1 vCPU y 1 GiB |

## 2. Benchmark de escala (P7-1 y P7-2)

* **Proxy de Cloud Run en local (sin GCP):** M4 en CPU con 1 y 2 hilos, fp32, sobre muestras de 5 000 textos de `ppi_v0`, con y sin orden por longitud, midiendo textos/s, memoria pico (RSS) y tiempo de carga del modelo. Si el daemon de Docker está activo, la misma prueba en un contenedor con `--cpus=1 --memory=2g`, que se parece más a Cloud Run.
* **Variantes baratas:** cuantización dinámica int8 de las capas lineales (PyTorch) y la diferencia de κ que provoca en el oro *dev*. **[decide el autor]** si una variante con menor κ es aceptable.
* **Proyección:** tiempo y costo del backfill (1.38 M textos) y del delta diario, en CPU de Cloud Run (free tier: 180 000 vCPU-s al mes) y en la T4. El backfill en Kaggle saca el corpus de GCP: la decisión es tuya (P7-1).
* **Medición real en Cloud Run (opcional, con aprobación):** construir la imagen con Cloud Build y correr un Job de prueba con 5 000 textos. Toca `infra/` y gasta créditos; solo si la proyección local deja dudas.
* **Familias con Gemini** (insumo de P8-7): estimar el costo de etiquetar las negativas del corpus con `aspects_v2_1` a partir de la corrida de 5.5 (~$0.09 por 1 000 textos), sin llamadas nuevas.

## 3. Ciclo de vida de artefactos (P7-3 y P7-4)

Propuesta escrita, sin código de producción (eso es EPIC-6):

* **Qué es una versión de modelo:** pesos fp16 + tokenizador + T + curva HITL + métricas en el oro *dev* + hash del paquete de entrenamiento; un manifiesto JSON por versión.
* **Registro:** GCS versionado frente a Vertex Model Registry, con costo y complejidad.
* **Promoción y rollback:** la regla de 5.4 (un modelo nuevo reemplaza al vigente solo si su diferencia pareada en el oro *dev* excluye el 0 o empata y es más barato), el recálculo de la curva HITL (6.4) y el *rollback* a la versión anterior.
* **Re-scoring:** histórico completo contra solo lo nuevo, con el costo medido en la sección 2.

## 4. Plan de monitoreo (P7-6 a P7-8)

* **Qué se "calibra" aquí:** no es la calibración de probabilidades de 5.6 (la T de M4). Son los **umbrales de alerta** del monitor de deriva: con qué valor de PSI o de z se avisa. Se fijan por la tasa de falsas alarmas que tendrían en el histórico. No tiene relación con el benchmark de la sección 2.
* **Entrada y predicción, sin etiquetas:** con el snapshot, calcular hacia atrás las series mensuales por banco de longitud, vocabulario nuevo, proporción de no predecibles y proporción de `NEG` (con la plata y `ppi_v0`), y su PSI o z robusto contra una línea base de 12 meses. Con eso se propone un umbral por su tasa de falsas alarmas histórica. Es la parte del monitor que no depende de la lista de incidentes (5.9).
* **D1 (P7-6):** propuesta de cómo una alerta de deriva sugiere una nueva versión de la política HITL, que una persona aprueba en el portal.
* **Concepto (P7-7):** tamaño de la muestra humana periódica para detectar una caída de κ de, por ejemplo, 0.05, con el IC del oro actual.
* **Tópicos (P7-8):** frecuencia del re-ajuste, emparejamiento de identificadores por similitud de centroides (se prueba entre dos ajustes de 5.5) y vigilancia de `OT`.

## 5. Entregables y código

* **Código** en `voc_analytics/scale/` (área nueva, 5.7): `benchmark.py` (sección 2) y `drift_baseline.py` (sección 4). Reutiliza `sentiment` y `calibration` sin modificarlos.
* **Métricas** en `docs/analytics/scale/`, solo agregados; reporte `scale_report.md` con la propuesta de ciclo de vida y monitoreo.
* **Esfuerzo estimado:** ~1 día en el Mac, sin GPU ni Gemini; la medición real en Cloud Run, si se aprueba, ~1 h más.

## 6. Decisiones del autor antes de empezar

| # | Decisión | Opciones | Recomendación |
| :---: | :--- | :--- | :--- |
| E1 | ¿Se mide en Cloud Run real o basta el proxy local? | Proxy local; proxy local y luego Cloud Run | Proxy local primero; Cloud Run solo si la proyección deja dudas |
| E2 | ¿Se prueba la cuantización int8? | Sí; no | Sí: puede duplicar la velocidad en CPU; su efecto en κ se mide y tú decides |
| E3 | ¿Con qué periodo se fijan los umbrales del monitor de deriva? | Un corte fijo; reglas por banco | **Reabierta por el autor (2026-10-22):** no hay razón para un corte fijo. Se usa todo el histórico con un mínimo de filas por mes por banco, y se reporta la tasa de alerta y la estabilidad del volumen por banco y por año; el periodo de referencia se elige con esos datos |
