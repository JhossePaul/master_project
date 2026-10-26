# EPIC-6: Despliegue del Core Analítico (Contratos, Infraestructura e Inferencia)

* **Estado (2026-10-25):** 6.1 a 6.5 **cerradas**: el código, la infraestructura y las pruebas están terminados. Queda abierta solo **6.6, carga y validación en dev**. La épica se cierra al terminar 6.6; no depende de EPIC-7.
* **Dependencias:** [EPIC-5](epic_5.md) cerrada, con el [registro de decisión](../analytics/decision_record.md) aprobado, y EPIC-1 a EPIC-4 cerradas ([estado](epics.md#cierre-de-las-épicas-1-a-4)).
* **La consume:** [EPIC-7](epic_7.md), que lee las tablas y vistas, escribe en las de curaduría y HITL y lanza los Jobs con argumentos. Lo que EPIC-7 construye por su cuenta está en su [feature 7.0](epic_7/00_preparacion.md).
* **Directorios:**
  * `packages/voc-common/`: contratos v3 (modelos Pydantic, enums, `bq_schema`);
  * `packages/voc-nlp/`: lógica pura portada de EPIC-5 sin cambiar el criterio;
  * `services/ml-inference/`: la imagen de inferencia, monitoreo, ciclo de vida, reentrenamiento y backfills;
  * `infra/`: tablas, vistas, Jobs, IAM y avisos.
* **Pendientes que no bloquean:** la dependencia de archivos locales de la carga y otras deudas quedan en [EPIC-8](epic_8.md).

---

## 🎯 Objetivo

Llevar a producción lo que decidió EPIC-5: cargar los backfills de 5.8 y 5.9, correr un delta diario, guardar salidas versionadas en BigQuery, vigilar deriva y calidad por banco, mantener las tablas de curaduría y HITL, y reentrenar y re-predecir sin repetir la experimentación en local. Esta épica no decide modelos ni umbrales; implementa los de EPIC-5.

---

## 🔁 Comandos

Todos con la imagen `ml-inference` (`python -m ml_inference <comando>`) y la cuenta `voc-sa-ml-backend`. Las corridas largas escriben su inicio y su cierre en `inference_runs`; la vista `inference_runs_current` da el estado de cada una.

| Comando | Dónde corre | Cuándo | Qué hace | Costo |
| :--- | :--- | :--- | :--- | :--- |
| `seed` | Local (autor) | Una vez | Versiones iniciales desde los JSON de `docs/analytics/`: `robertuito_sentiment_v1` promovido (T 1.6811), su curva, `risk_policy` v1 (con `retrain_trigger = manual` y `topic_refit_trigger = scheduled`), `drift_policy` por banco y guías | $0 |
| `load-local` | Local (autor) | Una vez | Desde `experiments/analytics/data/`: sube pesos, modelo de tópicos y MiniLM a `ml_artifacts/`, y carga sentimiento, familias, embeddings, tópicos `topics_v1`, vectores de cláusulas, curaduría y `gold_labels` | $0 |
| `upload-gold-ids` | Local (autor) | Una vez | Ids y `text_key` de todas las colas del oro (*dev* y *test*), sin texto ni etiquetas, a `archive/epic5/labels/silver_v0/gold_ids.parquet`; el entrenamiento los excluye | $0 |
| `build-vocab` | Local o Job (`voc-ml-monitor --args=build-vocab`) | Una vez por modelo | `training_vocab.txt` de `robertuito_sentiment_v1`, para la serie de vocabulario | $0 |
| `delta` | Job `voc-ml-inference-delta` | Diario | Elegibilidad → RoBERTuito → familias (Gemini solo para textos sin familias) → MiniLM y tópicos de lo que llegó por la ingesta, con los vectores de cláusulas en `segment_embeddings` → casos HITL `low_confidence` → lanza el backfill de tópicos si hace falta | ~$0.03 al día |
| `monitor` | Job `voc-ml-monitor` | Lunes | Deriva por banco (serie por serie), muestras, calidad, KPI con PPI; con `retrain_trigger = auto` lanza el reentrenamiento (uno por trimestre) | ~$0.02 a la semana |
| `drift-rates` | Job `voc-ml-monitor` | A mano | Tasas de alerta contra las de 5.7 (código 1 si alguna queda fuera) | $0 |
| `topics-refit` | Job `voc-ml-topics-refit` | Día 2 de cada trimestre, o `--force` | Re-ajusta BERTopic y empareja con la versión anterior; con `topic_refit_trigger = manual` solo con `--force` | $0 |
| `topics-backfill` | Job `voc-ml-topics-backfill` | Lo lanza el delta | Re-asigna el histórico a la versión vigente sobre `segment_embeddings`, sin Kaggle | ~$0.02 |
| `aspects-backfill` | Job `voc-ml-aspects-backfill` | A mano | Sin `--approve` estima; con `--approve --max-usd <tope>` re-etiqueta con el prompt vigente hasta el tope | ~$60 el histórico completo |
| `train` | Job `voc-ml-training` + kernel de Kaggle | A mano o desde el monitor | Reentrena desde el modelo base, calibra, publica y registra un candidato; en `auto` lanza el *re-scoring*. Acepta `--actor-hash` y `--reason` | ~$1 de plata reciente (tope $2) |
| `rescore` | Job `voc-ml-rescoring` + kernel de Kaggle | Por candidato | Predice el corpus con el candidato, carga, verifica y guarda la regla de promoción en `promotion_checks`. Acepta `--actor-hash` y `--reason` | $0 |
| `promote` | Job `voc-ml-promote` o local | A mano | Regla de promoción (`--force` para saltarla), curva, alias de Vertex (registra la versión si falta) y `risk_policy` siguiente; a una versión ya promovida es el *rollback* | $0 |
| `register`, `curve`, `risk-policy` | Local | A mano | Registrar un candidato hecho fuera; recalcular la curva; cambiar la cobertura objetivo | $0 |

**Ciclo de un modelo nuevo:** `train` (registra) → `rescore` → `promote`. Promover antes del *re-scoring* dejaría el cockpit vacío.

**Avisos:** `DriftAlertMessage` en `voc-incident-alerts-topic` y `ModelQualityMessage` en `voc-model-quality-topic`, sin texto ni PII; Cloud Monitoring manda un correo con los comandos de respaldo.

**Configuración que cambia con el tiempo** (variables de entorno de los Jobs, sin tocar código): `GEMINI_PRICE_IN` y `GEMINI_PRICE_OUT` (el precio introductorio vence el 2026-12-31 y de él dependen los topes de costo), `GOLD_VERSION`, `RECENT_SILVER_TEXTS`, `RECENT_SILVER_MONTHS` y `RECENT_SILVER_MAX_USD`.

---

## 🔒 Restricciones de despliegue vigentes

* Inferencia batch incremental sobre BigQuery en Cloud Run Jobs de CPU; sin endpoints de Vertex.
* Escritura por tabla temporal y `MERGE` de solo inserción, sin *Streaming Inserts*; toda corrida se repite sin duplicar filas.
* Una inferencia por texto único elegible (`text_key`), propagada a sus filas; la fila excluida queda `NO_PREDICTED` con su código.
* Los tópicos dependen del sentimiento (`TOPIC_NOT_NEGATIVE`): primero sentimiento, luego familias y tópicos.
* Mensajes de Pub/Sub validados con un contrato de `voc-common`, sin texto ni PII.
* El texto solo sale de GCP a Kaggle, y solo en el *re-scoring* (ids de tokens, no texto) y en el entrenamiento de 6.5 (FMEA F-13 y F-14). Gemini corre en Vertex AI dentro del proyecto (F-10).
* Ningún backfill pagado sin aprobación del autor.
* Imagen multi-stage sin root; pruebas deterministas sin red ni descargas.

## 🧱 Decisiones de diseño de EPIC-6 (autor, 2026-10-23)

Solo las vigentes. D5 se retiró (la reemplazó D13) y D8 también (la reemplazó D35). Las del 2026-10-24 se tomaron al implementar 6.3 a 6.5; la columna dice lo implementado.

| # | Tema | Decisión |
| :---: | :--- | :--- |
| D1 | Dónde vive el código | `voc-common` solo contratos; `voc-nlp` la lógica pura; `ml-inference` una imagen con varios comandos. Se borró `services/ml-delora/` |
| D2 | Léxico `lexicon_v1` | Versionado en git dentro de `voc-nlp` (151 formas con su etiqueta agregada y su SHA-256); excepción aprobada a la regla de datos |
| D3 | Alertas | Todas en el monitor (6.4); el delta solo predice y escribe |
| D4 | Precisión del delta | RoBERTuito en fp32 en 1 vCPU; los pesos fp16 del registro se cargan en fp32; sin int8 |
| D6 | Histórico de familias, tópicos y embeddings | Hecho en 5.9 ([reporte, §2](../analytics/incidents/incidents_report.md#2-backfill-de-familias-y-tópicos-p9-3)); 6.3 solo lo carga |
| D7 | Piezas sin dueño | El delta crea los casos `low_confidence` y su oclusión; el monitor, `monitor_sample`, `agreement_sample` y `kpi_estimates` con PPI sobre el oro *dev* (más `gold_hitl` cuando exista) |
| D9 | Delta | Un Job con pasos en serie y un modelo cargado a la vez; 4 GiB (con 2 GiB el primer delta en dev se quedó sin memoria al embeber y asignar tópicos, 2026-10-25) |
| D10 | Oro en producción | `gold_labels` en BigQuery, cargado una vez desde local: oro *dev* aleatorio y las 300 reseñas de `aspects_gold_v2_1` |
| D11 | Nombres | Sin la jerga de EPIC-5 en código ni en BigQuery (`robertuito_sentiment_v1`, `topics_v1`, `clause_segmenter_v1`, `aspects_gold_v2_1`); la carga traduce los nombres locales |
| D12 | Apetito de riesgo sin evidencia | Tope semanal, subida por deriva y doble revisión de `risk_policy` nulos en v1 (sin tope, sin subida, sin doble revisión) hasta que el dueño de negocio los fije en 7.10. Los grupos se configuran completos o no se configuran |
| D13 | *Re-scoring* | Job `voc-ml-rescoring` que hace todo desde GCP: exporta, sube un dataset privado de Kaggle por corrida (ids de tokens y pesos), corre el kernel de GPU, carga con `MERGE`, verifica y borra el dataset. Token en Secret Manager (`voc-kaggle-token`), solo para `voc-sa-ml-backend`. **Precede a la promoción** (D18) |
| D14 | Reentrenamiento | Feature 6.5 |
| D15 | Avisos | Por correo con Cloud Monitoring sobre los dos tópicos; el correo se guarda cifrado en el stack, no en git |
| D16 | Carga del backfill | `load-local` corre en el Mac del autor y lee del TDS en memoria solo lo que pide la elegibilidad (F-11); lo demás viaja sin texto, con `text_key` |
| D17 | Oro y curva | `gold_labels` lleva `weight` (1/π) y `id_resena` nulo en el oro de aspectos; se exporta sin texto con `voc_analytics.labeling.export_gold_v3`. `CoveragePoint` acepta el IC nulo en cobertura 1.0 |
| D18 | Orden del ciclo de modelo (2026-10-24) | `register` → `rescore` → `promote`. `promote` se niega si el candidato no tiene filas en el oro *dev* |
| D19 | Regla de promoción (2026-10-24) | Diferencia pareada candidato − vigente en κ y macro-F1 ponderados por 1/π en el oro *dev*, *bootstrap* estratificado por banco × periodo (2 000 réplicas). Se promueve si es mejor o empata; si un IC queda bajo 0, solo con `--force`. `promote` inserta la `risk_policy` siguiente con el umbral de la cobertura vigente en la curva nueva |
| D20 | KPI con PPI (2026-10-24) | La corrección se estima con todo el oro *dev* del banco y se aplica a cada mes (el oro tiene ~36 reseñas por banco y periodo). Supone sesgo estable; lo vigilan el κ trimestral y la deriva |
| D21 | Re-ajuste de tópicos (2026-10-24) | Job `voc-ml-topics-refit` (2 vCPU, 4 GiB) trimestral, con los parámetros de `topics_v1` y una muestra de hasta 40 000 negativas de 12 meses con cuota por banco. Sin Gemini: los nombres los pone el curador |
| D22 | Emparejamiento y activación de tópicos (2026-10-24) | Cada tópico nuevo va con el anterior de centroide más parecido, sin umbral. La versión se activa (`topic_model_current`) cuando todos sus pares tienen decisión en `curation_topics` |
| D23 | Deriva sin alertas históricas (2026-10-24) | Solo el último mes cerrado abre alerta, publica y crea subida; los meses anteriores quedan en `drift_metrics` con su marca, para medir tasas |
| D24 | Vocabulario fuera del entrenamiento (2026-10-24) | Artefacto `training_vocab.txt` junto a los pesos de cada versión, armado en GCP desde la plata archivada; sin él, la serie se omite con un aviso |
| D25 | Disparo del reentrenamiento (2026-10-24) | Configurable en `risk_policy` (`retrain_trigger`: `auto` o `manual`; `manual` en v1), versionado con quién y motivo y editable en 7.10. En `auto`, el `monitor` lanza el Job de reentrenamiento al escribir `retrain`; en `manual`, MLOps (7.9) muestra un botón que solo se habilita con `retrain` vigente y sin otro reentrenamiento en curso. El texto del correo de avisos lleva el comando del Job como respaldo. Auto saca texto a Kaggle sin aprobación por corrida (F-13): pasar a `auto` es esa aprobación. Auto llega como mucho al *re-scoring* del candidato; la promoción siempre es humana |
| D26 | Botón de promoción (2026-10-24) | MLOps (7.9) promueve un candidato con un botón, que se habilita cuando su *re-scoring* está verificado. Antes de confirmar muestra el resultado de la regla de promoción (diferencias de κ y macro-F1 con su IC) y la curva nueva; si la regla no pasa, pide confirmación explícita y motivo (el `--force` de la CLI). El mismo panel hace el *rollback* a una versión que ya estuvo promovida. Ejecuta el comando `promote` en un Job; el actor y el motivo quedan en `model_versions` (`promoted_by_hash`, `reason`, con la marca de forzada o de *rollback*) |
| D27 | Punto de partida del reentrenamiento (2026-10-24) | La receta de 5.4 desde el modelo base (`pysentimiento/robertuito-sentiment-analysis`), no desde el modelo vigente: cada versión sale solo de la receta y de un conjunto con hash, y un error de una versión no se hereda a la siguiente. Una semilla por reentrenamiento (en 5.4 las tres quedaron dentro de 0.01 de κ) |
| D28 | Conjunto de entrenamiento (2026-10-24) | La partición `entrenamiento` de la plata de 5.3 (63 720 textos, sin `NA`) más las revisiones de sentimiento del HITL de `low_confidence` y `drift_boost` (primera ronda, sin `no_evaluable`); la revisión reemplaza a la plata del mismo texto. Se excluyen `monitor_sample` y `agreement_sample` (miden el κ y alimentan el oro de PPI) y todo texto del oro *dev* y *test* |
| D29 | Gemini solo etiqueta lo que nunca etiquetó (2026-10-24) | El delta manda a Gemini solo los textos `NEG` sin ninguna fila en `review_aspects`, con cualquier prompt. Un cambio de prompt no re-etiqueta el histórico: las familias quedan con el prompt con el que se etiquetaron, y la serie mezcla prompts. Es un hueco aceptado por presupuesto (un backfill cuesta ~$60, unos $1 200 MXN, en un proyecto académico); en producción se re-etiquetaría. RoBERTuito, MiniLM y los tópicos, que no cuestan, solo procesan lo que llega por la ingesta diaria; sus históricos se rehacen con el *re-scoring* y el backfill de tópicos |
| D30 | Embeddings de cláusulas (2026-10-24) | Tabla `segment_embeddings` en BigQuery (vector de MiniLM por `text_key` × `segment_index`, agrupada por `text_key`), calculada una sola vez y extendida por el delta. Leer todos los vectores cuesta ~$0.02 por corrida y guardarlos ~$0.06 al mes. La re-asignación del histórico de tópicos corre en Cloud Run sobre ellos, sin Kaggle: el texto no sale de GCP |
| D31 | Plata reciente en cada reentrenamiento (2026-10-24) | Prendida por defecto: cada reentrenamiento sortea 20 000 textos de los meses posteriores a la plata de 5.3, los etiqueta con Gemini con el prompt de la plata y los suma al conjunto. Es lo que más acerca el modelo a los datos recientes, porque las revisiones humanas son pocas y son los casos difíciles. Cuesta ~$1 (~$0.048 por 1 000 textos) y lleva un tope de $2 por corrida en lugar de `--approve`, así que también corre en modo `auto`. Ventana de 12 meses (`RECENT_SILVER_MONTHS`), nunca antes del 2026-04-01; `RECENT_SILVER_TEXTS=0` la apaga |
| D32 | Disparo del backfill de tópicos (2026-10-24; ajustado 2026-10-25) | Lo lanza el delta mientras queden negativas sin asignar a la versión vigente y no haya un backfill de esa versión en curso (fila `running` de `inference_runs` más nueva que el tiempo máximo del Job); mientras tanto, el delta asigna tópicos solo a lo que llegó por la ingesta diaria. Un backfill fallido se relanza al día siguiente |
| D33 | Calibración y curva de cada candidato (2026-10-24) | Un modelo recién entrenado exagera su seguridad; se corrige con un solo número (la temperatura) ajustado contra las reseñas que etiquetaron personas (el oro *dev*), como se hizo con el modelo vigente. Con la confianza corregida se calcula la curva de cobertura y riesgo: para cada porcentaje de reseñas que se aceptan sin revisión, cuántos errores quedan. El corte que se usa no es fijo: sale de la cobertura objetivo de la `risk_policy` (90 % por defecto, parámetro del apetito de riesgo que se cambia en 7.10). Los dos se calculan antes de `register` con el mismo oro *dev*; el error estimado sale un poco optimista, igual que en el modelo vigente, así que se comparan en las mismas condiciones. Además se guardan el κ, el ECE y el AURC del oro *dev* en `model_versions`, y el ECE y el diagrama de confiabilidad antes y después de la temperatura en `training_manifest.json`, junto a los pesos. MLOps (7.9) los muestra para decidir la promoción |
| D34 | Un switch de reentrenamiento por modelo (2026-10-24) | **Sentimiento:** `retrain_trigger` (`auto` o `manual`, `manual` en v1). En `auto`, cuando el κ trimestral cae bajo su piso, se entrena un candidato y se vuelve a predecir el histórico con él, pero no se pone en uso: eso lo decide una persona con el botón de promoción. Como mucho uno por trimestre. **Tópicos:** `topic_refit_trigger` (`scheduled` o `manual`, `scheduled` en v1). EPIC-5 no dejó evidencia para un umbral: `OT` no sirve como alarma (es el 0.6 % de las negativas y su κ autor–Gemini es 0) y que los tópicos no alineados detecten temas nuevos quedó como hipótesis. Por eso el re-ajuste sigue por calendario (`topic_refit_frequency`) o con el botón de MLOps, y una versión nueva solo se usa cuando el curador revisa sus tópicos. El monitor guarda como contexto, sin umbral, la proporción de cláusulas sin tópico (ruido; 36.2 % en el histórico de 5.9) y la de negativas cuyos tópicos no tienen familia en la curaduría (no alineados), para fijar un umbral cuando haya trimestres de datos. **Familias y marca `u`:** llevan umbral desde el 2026-10-25 (D35) |
| D35 | Familias y marca `u` con umbral (2026-10-25) | Las 11 familias y `u` pasan de contexto a series con z ≥ 4 en la política de deriva v2 (`drift_policy_template_v2` y `drift_policy_v2_<banco>`), como el resto; los tópicos siguen como contexto sin umbral. Criterio: sin la lista de incidentes no se puede calibrar la sensibilidad (5.9 sacó la detección de incidentes del alcance), así que conviene acumular el historial de `drift_alerts` para calibrarla después; con `drift_boost` nulo (D12) una alerta solo publica y manda correo, y la política es versionada y editable en 7.10. Tasas del primer monitor (|z| ≥ 4 o PSI ≥ 0.25): familias, media de 0.58 meses al año y máximo de 2.32 (NUBANK–DV); `u`, media de 1.03 y máximo de 1.89 (SANTANDER); suman unos 37 meses-alerta al año a los ~19 de las 35 series anteriores. Aplica desde el primer mes cerrado después de la política: el monitor no recalcula los pares (mes, serie) ya guardados, así que el historial queda sin marcas. `drift-rates` no tiene referencia de 5.7 para estas series y las compara con el techo de 1.4 más la tolerancia de 0.5, así que NUBANK–DV (2.32) saldrá fuera. La sensibilidad (z ≥ 3 daría ~1.6 veces las tasas de 5.7) se revisa con un trimestre de historial |

### Parámetros que fija el dueño de negocio (EPIC-7, 7.10)

No son huecos de diseño: no hay evidencia en EPIC-5 para ellos ([registro de decisión](../analytics/decision_record.md), sección 4), así que la `risk_policy` v1 los deja nulos (D12).

| Parámetro | Nulo en v1 significa | Referencia |
| :--- | :--- | :--- |
| `hitl_weekly_cap` | Sin tope | La semana real de 5.9 dio 387 casos con el umbral del 90 % |
| `drift_boost_coverage`, `drift_boost_days`, `drift_boost_weekly_cap` | La alerta se registra y se publica, sin subida | La curva da el costo de cada cobertura |
| `human_agreement_sample_size`, `human_agreement_frequency` | Sin doble revisión entre personas | — |

---

## 📦 Features

### Cerradas

| Feature | Entregó |
| :--- | :--- |
| 6.1 Contratos v3 | Enums y modelos por tabla en `voc-common`, `text_key`, `bq_schema` y el [contrato v3](../contracts/analytics_outputs_v3.md) |
| 6.2 Infraestructura | 28 tablas y 10 vistas en `bbva_voc_tds`, IAM de mínimo privilegio, tópico y correo de avisos, secreto de Kaggle; lo de EPIC-2 retirado |
| 6.3 Inferencia batch | Ports de EPIC-5 en `voc-nlp`; `delta`, `seed`, `load-local`, `register`; imagen multi-stage sin root y `tools/deploy_images.py` |
| 6.4 Monitoreo y ciclo de vida | Deriva, calidad, KPI con PPI, muestras HITL, `promote` con regla y *rollback*, `rescore` en Kaggle, `topics-refit`, `build-vocab`, `drift-rates` |
| 6.5 Reentrenamiento y backfills | `train` con la receta de 5.4 desde el modelo base, calibración y registro con hash; `topics-backfill` sobre `segment_embeddings`; `aspects-backfill` con tope; Gemini solo para textos sin familias; `promotion_checks`; switches `retrain_trigger` y `topic_refit_trigger`; `inference_runs` con inicio, versión de tópicos, actor y motivo |

Puertas de calidad al cerrar (2026-10-25, con `uv sync --all-packages` como CI): `ruff`, `pyrefly` (0 errores) y `bandit` sin hallazgos; `pytest` con 128 pruebas de `infra/`, 344 de `voc-common`, 139 de `voc-nlp`, 198 de `ml-inference`, 196 de ingesta, 130 de sanitización y 50 de `tools`.

### FEATURE 6.6: Carga y validación en dev

**Objetivo:** pasar de "infraestructura aplicada y tablas vacías" a "todo cargado, validado y corriendo en dev", con evidencia de cada paso. No depende de EPIC-7.

**Antes de empezar (máquina del autor):** `gcloud auth application-default login`; `uv sync --all-packages`; desde la raíz del repo, `export GCP_PROJECT_ID=<proyecto> GCS_RAW_DATALAKE_BUCKET=voc-datalake-<proyecto>`. Los comandos locales leen `experiments/analytics/data/` con rutas relativas a la raíz.

**El orden importa:** la imagen se fija (paso 8) después de sembrar y cargar. Con la imagen fijada los Schedulers disparan el delta cada día y el monitor los lunes: sobre tablas vacías, el delta falla sin modelo promovido, o predice y paga Gemini por negativas que `load-local` aún no carga.

| # | Paso | Comando | Lee → escribe | Validación |
| :-: | :--- | :--- | :--- | :--- |
| 1 | Infraestructura al día | `pulumi up` en `infra/` | Agrega la vista `inference_runs_current` y las columnas nuevas de `inference_runs` (`topic_model_version`, `actor_hash`, `reason`, `ended_at` nulo) y de `model_versions` (`reason`) | `pulumi preview` sin cambios |
| 2 | Oro exportado | `uv run python -m voc_analytics.labeling.export_gold_v3` (en `experiments/analytics`) | Etiquetas locales → `data/handoff/gold_labels_v1.parquet` (sin texto) | El archivo existe (ya existe desde el 2026-10-24) |
| 3 | Siembra | `uv run python -m ml_inference seed --actor-hash <sha256> --reason "<motivo>"` | JSON de `docs/analytics/` → `model_versions`, `hitl_coverage_curves`, `risk_policy`, `drift_policy_template`, `drift_policy`, `guidelines` | `model_versions` con `robertuito_sentiment_v1` `promoted`; 5 filas en `drift_policy`; 1 en `risk_policy_current` |
| 4 | Carga del histórico | `uv run python -m ml_inference load-local --actor-hash <sha256> --work <carpeta>` | Archivos locales de 5.8 y 5.9 → `ml_artifacts/` y las tablas de predicciones, familias, embeddings, tópicos, `segment_embeddings`, curaduría y `gold_labels` | ~2 653 238 filas en `review_predictions`; 659 316 `text_key` en `review_aspects`; 1 429 675 en `text_embeddings`; 1 035 052 en `segment_embeddings`; `topic_model_current` = `topics_v1`; `gold_labels` con el *dev* y `aspects_gold_v2_1` |
| 5 | Vocabulario | `uv run python -m ml_inference build-vocab` | Plata archivada en GCS → `ml_artifacts/sentiment/robertuito_sentiment_v1/training_vocab.txt` | El objeto existe; el log da palabras y SHA-256 |
| 6 | Insumos del reentrenamiento | `uv run python -m ml_inference upload-gold-ids`; `hf download pysentimiento/robertuito-sentiment-analysis --local-dir <dir>` y `gcloud storage cp -r <dir>/* gs://<bucket>/ml_artifacts/sentiment/base/`; `gcloud storage ls gs://<bucket>/archive/epic5/labels/silver_v0/` | Colas del oro → `gold_ids.parquet`; modelo base → `ml_artifacts/sentiment/base/` | `gold_ids.parquet`, `config.json` y los pesos del modelo base existen; la plata archivada tiene `texts.parquet`, `rows.parquet` y `labels_prompt_v3.parquet` |
| 7 | Secreto de Kaggle | `gcloud secrets versions add voc-kaggle-token --data-file=<archivo>` | Token → Secret Manager | `gcloud secrets versions list voc-kaggle-token` |
| 8 | Imagen fijada | Mezclar en `main`, esperar el CD y `uv run python tools/deploy_images.py --project <proyecto> --apply`; commitear `infra/Pulumi.dev.yaml` | Crea los ocho Jobs de ML, sus Schedulers y el permiso de ejecución con argumentos | `gcloud run jobs list` muestra los ocho; `pulumi preview` sin cambios |
| 9 | Primer delta | `gcloud run jobs execute voc-ml-inference-delta --wait` | TDS nuevo → predicciones, familias, tópicos y casos HITL | `inference_runs_current`: `delta` `succeeded`, con `peak_memory_mib` dentro de 4 GiB y `cost_usd`; si quedaron negativas sin tópico, un `topic_backfill` lanzado y luego `succeeded` |
| 10 | Temas diarios | Consulta a `daily_topic_labels` | — | Coincide con `data/incidents/daily_topics_v0.parquet` de 5.9 en una muestra de días × banco |
| 11 | Primer monitor | `gcloud run jobs execute voc-ml-monitor --wait` | → `drift_metrics` (histórico sin alertas viejas, con vocabulario y series de tópicos), `model_quality`, `kpi_estimates`, `hitl_items` de `monitor_sample` | Meses por banco en `drift_metrics`; filas en `model_quality` y `kpi_estimates` |
| 12 | Tasas de alerta | `gcloud run jobs execute voc-ml-monitor --args=drift-rates --wait` | `drift_metrics` | Sale con código 0 (tasas de 5.7); con las de familias y `u` el autor decide si llevan umbral y lo anota en D34 |
| 13 | Avisos | Publicar un mensaje de prueba en `voc-model-quality-topic` | — | Llega el correo |
| 14 | Ciclo de modelo | `gcloud run jobs execute voc-ml-training --args=train,--actor-hash=<sha256>,--reason=<motivo> --wait`, luego `rescore --model-version=<candidato>` | Plata, revisiones y plata reciente → Kaggle (solo ids) → candidato en `model_versions`, curva, `promotion_checks` | `inference_runs_current`: `training` y `rescoring` `succeeded`; el candidato con `training_data_hash`, `ece_dev` y `aurc_dev`; una fila en `promotion_checks`. Promover es decisión del autor. Requiere aprobar ~$1 de Gemini (tope $2) |
| 15 | Backfill de familias, solo estimación | `gcloud run jobs execute voc-ml-aspects-backfill --args=aspects-backfill --wait` | — | El log da textos pendientes del prompt vigente y costo estimado; no llama a Gemini |

**Avance (validaciones anotadas):**

* Paso 1 (2026-10-25): las columnas nuevas de `model_versions` e `inference_runs` están en BigQuery; `pulumi preview` sin cambios (103 recursos sin modificar).
* Paso 2 (2026-10-25): `data/handoff/gold_labels_v1.parquet` existe.
* Paso 3 (2026-10-25): `seed` escribió 1 fila en `model_versions`, 1 en `hitl_coverage_curves`, 1 en `risk_policy`, 1 en `drift_policy_template`, 5 en `drift_policy` y 2 en `guidelines`. `robertuito_sentiment_v1` quedó `promoted` (T 1.6811) y `risk_policy_current` da `risk_policy_v1` (cobertura 0.9, `retrain_trigger = manual`, `topic_refit_trigger = scheduled`). El primer intento falló: `INSERT ROW` empareja por posición y `model_versions`, `inference_runs`, `risk_policy` y `gold_labels` tienen sus columnas nuevas al final. El `MERGE` de `StagingMergeWriter` ahora lista las columnas por nombre.
* Paso 4 (2026-10-25): `load-local` terminó. Dos fallos previos, ambos de código y corregidos: el `MERGE` por posición del paso 3 y un escape `$${tds}` en la consulta al TDS. Quedaron `review_predictions` 2 654 106 filas (1 429 622 `text_key`; el backlog esperaba ~2 653 238 filas), `review_aspects` 703 369 filas (659 286 `text_key`; esperados 659 316), `text_embeddings` 1 826 977 filas (1 429 616 `text_key`; esperados 1 429 675), `segment_embeddings` 1 035 052 (exacto), `topic_assignments` 1 079 153, `topic_model_current` = `topics_v1` (97 tópicos), `curation_topics` 35 y `gold_labels` `gold_epic5_v1` con 794 del *dev* y 300 de `aspects_gold_v2_1`. La diferencia se explica por el corte del backfill (2026-10-22) frente al TDS actual (2 655 053 reseñas, hasta el 2026-10-23): 947 reseñas del TDS, de los días 20 a 23, no tienen predicción, y las decenas de `text_key` de familias y embeddings van por el mismo lado. El primer delta las toma como pendientes (`LEFT JOIN` con `review_predictions`, sin ventana de fechas).
* Paso 5 (2026-10-25): `build-vocab` dio 44 997 palabras, SHA-256 `756358892fa9c61b6def9f06f3271561da4d0d6933540f52017c3a5ca1c70d64`.
* Paso 6 (2026-10-25): `upload-gold-ids` subió 1 730 reseñas a `gold_ids.parquet`; el modelo base está en `ml_artifacts/sentiment/base/` (`config.json`, `model.safetensors` y el tokenizador); la plata archivada tiene `texts.parquet`, `rows.parquet` y `labels_prompt_v3.parquet`.
* Paso 7 (2026-10-25): `voc-kaggle-token` tiene la versión 1 activa (creada el 2026-10-24), con un token de una sola cadena (`KGAT_…`, 37 caracteres, sin JSON ni salto de línea), que es el formato de `KAGGLE_API_TOKEN`. Falta probar la autenticación, que se hace en el paso 14.
* Paso 8 (2026-10-25): PR 11 mezclado en `main` con merge commit (`b4d5758`); el CD terminó en verde. `deploy_images.py --apply` creó 17 recursos (los ocho Jobs de ML, seis permisos y tres Schedulers: delta diario 09:30, monitor lunes 10:30 y re-ajuste de tópicos el día 2 de enero, abril, julio y octubre, hora de CDMX) y actualizó las imágenes de ingesta y sanitización. `gcloud run jobs list` muestra los ocho Jobs de ML; `pulumi preview` da 120 recursos sin cambios.
* Paso 9 (2026-10-25): el primer delta falló por dos causas. (1) El `MERGE` por nombre de la corrección anterior no citaba las columnas y `at` es palabra reservada (`Unexpected keyword AT` en `hitl_events`): el delta escribió las predicciones y los casos HITL sin sus eventos. (2) El reintento etiquetó 1 503 textos con Gemini y murió por memoria con 2 GiB. El Scheduler de las 09:30 repitió el patrón con 677 reseñas. Se corrigieron el `MERGE` (columnas entre comillas) y la memoria del Job (4 GiB, D9), se repararon a mano los 197 casos HITL sin evento (`queued`, con el `created_at` del caso) y se repitió el delta: `succeeded`, 0 reseñas pendientes, pico 1 357 MiB, 0 reseñas sin predicción y 0 negativas sin familias. El delta lanzó el `topics-backfill` (959 negativas sin tópico): `succeeded` en 4 min 12 s, pico 1 913 MiB. Quedan 2 negativas sin tópico porque el segmentador no les sacó cláusulas. El costo de Gemini de las corridas fallidas no quedó en `inference_runs` (`cost_usd` 0): estimado ~$0.07 por 1 503 textos.
* Paso 10 (2026-10-25): `daily_topic_labels` contra `daily_topics_v0.parquet` de 5.9: 160 002 filas comparables (día × banco × tipo × rango) y 99.47 % idénticas (853 con alguna diferencia). En las antiguas, `n_neg` en BigQuery es 1 menos que en 5.9 (428 filas, siempre −1, repartidas por meses), coherente con las ~30 negativas menos del TDS actual (paso 4); no se verificó reseña por reseña. BigQuery llega al 2026-10-24 y 5.9 al 2026-10-14.
* Paso 11 (2026-10-25): `voc-ml-monitor` terminó en `succeeded` en 3 min 19 s. `drift_metrics` quedó con 9 702 filas (0 alertas, 0 subidas, por D23), `kpi_estimates` con 19 136 (186 meses) y `model_quality` con 2 (`gemini_agreement` y `families_validation`, ambas `ok`); `monitor_sample` creó 300 casos (`hitl_items` pasó de 197 a 497). El κ trimestral de 2026Q3 aún no se calcula: tiene 0 de 300 revisiones. El monitor no escribe en `inference_runs`, así que su pico de memoria no está registrado.
* Paso 12 (2026-10-25): `drift-rates` sale con código 0: las 35 series con umbral (7 series × 5 bancos) quedan dentro de la tolerancia de 5.7. Series de contexto, calculadas aparte con |z| ≥ 4 o PSI ≥ 0.25 (el comando no las reporta): familias, 55 pares banco × familia, media 0.58 meses al año y máximo 2.32 (NUBANK–DV; NUBANK–FA llega a 1.47); la marca `u` (`flag_update_share`), máximo 1.89 (SANTANDER); tópicos, máximo 0.63. Dos pares de familias y uno de `flag_update_share` pasan el techo de 1.4 de las series con umbral. El autor decidió ponerles z ≥ 4 (D35); la política v2 se sembró el mismo día.
* Paso 13 (2026-10-25): el monitor no publicó avisos porque no hubo alertas. Se publicó un mensaje de prueba válido (`gemini_agreement`, `warning`, versión `PRUEBA_SIN_EFECTO`) en `voc-model-quality-topic` y se retiró de la suscripción; las dos políticas de alerta están activas. El correo llegó: una alerta a las 10:45 y su recuperación a las 10:50 (CDMX), porque Cloud Monitoring cierra el incidente cuando deja de haber publicaciones.
* Paso 15 (2026-10-25): `voc-ml-aspects-backfill` sin `--approve` terminó en `succeeded` en 1 min 17 s: `0 textos sin familias de aspects_v2_1, costo estimado $0.00`. No llamó a Gemini ni escribió en `inference_runs` (0 filas `aspect_backfill`). Coincide con BigQuery: los 660 919 textos de `review_aspects` ya llevan el prompt vigente. El backfill solo re-etiqueta cuando cambia el prompt (D29), así que no hay nada que cobrar hoy; hacerlo completo con un prompt nuevo costaría ~$60.61.
* Paso 14 (2026-10-25), intentos fallidos: (1) el primer `train` murió a los 90 segundos al importar `kaggle`, porque el usuario sin root no tiene directorio de inicio (`KAGGLE_CONFIG_DIR=/tmp/kaggle` en la imagen y comprobación en el smoke test); (2) el segundo armó el conjunto (83 169 ejemplos: 63 237 de la plata y 19 932 recientes, $0.9127 de Gemini, que sí se cobraron y quedaron en `inference_runs`) y falló al subir el dataset. Con el CLI de Kaggle y un dataset de prueba se midieron dos causas: Kaggle contesta 403 a la consulta de estado durante ~2 segundos tras crear el dataset (y el Job consultaba de inmediato), y `dir_mode="skip"` descartaba la subcarpeta `base/` con el modelo base (el dataset quedó solo con `train.parquet` y `dev.parquet`). Ahora el estado 403 o 404 cuenta como pendiente, el dataset conserva sus subcarpetas (`zip`) y no se suben los pesos duplicados del modelo base (`tf_model.h5` y `pytorch_model.bin`, ~870 MB). El adaptador también lanza el error que Kaggle devuelve en la respuesta de `dataset_create_new`, y `kaggle-check` prueba todo sin gastar. Cada reintento de `train` vuelve a pagar ~$0.91, porque sortea otros textos recientes.

**Terminado cuando:**

* [ ] los pasos 1 a 13 y 15 tienen su validación anotada aquí (fecha y cifra);
* [ ] el paso 14 corrió o el autor decidió posponer el primer reentrenamiento real, con su motivo;
* [ ] el delta y el monitor programados corrieron una vez solos sin error.

---

## ✅ Checklist de Aceptación de la Épica 6

* [x] Contratos v3 en `voc-common`, con `bq_schema` y su contrato en `docs/contracts/` (6.1).
* [x] Tablas y vistas v3, IAM y avisos aprovisionados con Pulumi; lo de EPIC-2 retirado (6.2).
* [x] Inferencia, monitoreo, ciclo de vida, reentrenamiento y backfills implementados y probados sin red (6.3 a 6.5).
* [x] Puertas de calidad del monorepo sin errores (2026-10-25).
* [ ] Datos cargados y validados en dev, Jobs creados con la imagen fijada y operación programada corriendo (6.6).
