# EPIC-6: Despliegue del Core Analítico (Contratos, Infraestructura e Inferencia)

* **Estado (2026-10-24, limpieza antes de 6.5):**
  * **6.1 y 6.2 terminadas** y desplegadas en el stack dev.
  * **6.3 y 6.4 con el código terminado**, pero nada de ML corre todavía en dev: la imagen `ml-inference` no está fijada en `Pulumi.dev.yaml`, así que los Jobs de ML no existen y no se ha sembrado ni cargado nada. Los pasos que faltan son del autor ([pendientes en dev](#-pendientes-en-dev-del-autor)).
  * **6.5 detallada** ([detalle](#feature-65-reentrenamiento-y-backfills)); sus decisiones (D25 a D34) están aprobadas; falta implementarla.
* **Dependencias:** [EPIC-5](epic_5.md) cerrada, con el [registro de decisión](../analytics/decision_record.md) aprobado, y EPIC-1 a EPIC-4 cerradas ([estado](epics.md#cierre-de-las-épicas-1-a-4)).
* **La consume:** [EPIC-7](epic_7.md): su API y su portal leen las tablas y vistas de salida, escriben en las de curaduría y HITL y muestran alertas, calidad y KPI.
* **Orden:** 6.1 → 6.2 → 6.3 → 6.4 → 6.5.
* **Directorios:**
  * `packages/voc-common/`: contratos v3 (modelos Pydantic, enums, `bq_schema`);
  * `packages/voc-nlp/`: lógica pura portada de EPIC-5 sin cambiar el criterio (elegibilidad, léxico, calibración, HITL, RoBERTuito, oclusión, familias, sentimiento con Gemini, tópicos y su re-ajuste, deriva, curva, PPI y acuerdo). La reusa el servicio de explicaciones de EPIC-7;
  * `services/ml-inference/`: una imagen con todos los comandos ([flujo](#-flujo-disponible-hoy));
  * `infra/`: tablas, vistas, Jobs, Scheduler, IAM, secretos y avisos;
  * [`docs/contracts/analytics_outputs_v3.md`](../contracts/analytics_outputs_v3.md): el contrato de las 26 tablas y sus vistas.

Lo que esta limpieza quitó (la especificación detallada de 6.1 a 6.4 ya implementada, el anexo de la fase 3 anterior con Delora, `ABSATopic` y `delora_predictions`, y la lista de cambios en otros documentos) sigue en git: `git show d126591:docs/backlog/epic_6.md`.

---

## 🎯 Objetivo

Llevar a producción lo que decidió EPIC-5: cargar los backfills de 5.8 y 5.9, correr un delta diario, guardar salidas versionadas en BigQuery, vigilar deriva y calidad por banco, mantener las tablas de curaduría y HITL, y reentrenar y re-predecir sin repetir la experimentación en local. Esta épica no decide modelos ni umbrales; implementa los de EPIC-5.

---

## 🔁 Flujo disponible hoy

Todo con la imagen `ml-inference` (`python -m ml_inference <comando>`) y la cuenta `voc-sa-ml-backend`. **Nada de esto corre todavía en dev** (ver los pendientes).

| Comando | Dónde corre | Cuándo | Qué hace | Costo |
| :--- | :--- | :--- | :--- | :--- |
| `seed` | Local (autor) | Una vez | Versiones iniciales: `robertuito_sentiment_v1` promovido (T 1.6811), curva de 5.6, `risk_policy` v1, `drift_policy` por banco, guías y `gold_labels` | $0 |
| `load-local` | Local (autor) | Una vez | Carga los backfills de 5.8 y 5.9 desde `experiments/analytics/data/backfill/20261022/` (sentimiento, familias, embeddings, tópicos `topics_v1`) y sube pesos y modelo de tópicos a `ml_artifacts/`. Del TDS solo lee en memoria lo que pide la elegibilidad | $0 |
| `build-vocab` | Local o Job | Una vez por modelo | Vocabulario de entrenamiento junto a los pesos, para la serie de vocabulario fuera del entrenamiento | $0 |
| `delta` | Job `voc-ml-inference-delta` (1 vCPU, 2 GiB) | Diario, una hora después de la sanitización | Elegibilidad → RoBERTuito en CPU → familias con Gemini → MiniLM y tópicos → casos HITL `low_confidence` con su oclusión → `inference_runs`. Hasta 20 000 reseñas por corrida | ~$0.03 al día de Gemini |
| `monitor` | Job `voc-ml-monitor` (1 vCPU, 2 GiB) | Lunes | Cierra subidas vencidas; deriva por banco (alerta, mensaje y subida solo del último mes cerrado); muestras `monitor_sample` y `agreement_sample`; calidad (κ trimestral, tasa de corrección, acuerdo semanal con Gemini, validación de familias al cambiar modelo o prompt); KPI con PPI | ~$0.02 a la semana; $0.03 por validación de familias |
| `drift-rates` | Job `voc-ml-monitor` | A mano | Compara las tasas de alerta de `drift_metrics` con las de 5.7 (sale con código 1 si alguna queda fuera) | $0 |
| `topics-refit` | Job `voc-ml-topics-refit` (2 vCPU, 4 GiB) | Día 2 de cada trimestre | Re-ajusta BERTopic sobre hasta 40 000 negativas de 12 meses y empareja cada tópico nuevo con el anterior más parecido. Se activa cuando el curador decide cada par | $0 |
| `register` | Local o Job | Por candidato | Registra el candidato en Vertex Model Registry con su T, curva y métricas | $0 |
| `rescore` | Job `voc-ml-rescoring` (2 vCPU, 4 GiB, 3 h) + kernel de Kaggle con GPU | A mano, por candidato | Exporta los textos únicos, sube a Kaggle ids de tokens y pesos (no texto), predice en GPU, carga con la `model_version` candidata, verifica y borra el dataset de Kaggle | $0 (30 h de GPU a la semana) |
| `promote` | Local o Job | A mano | Exige las predicciones del candidato en el oro *dev*; aplica la regla de promoción (`--force` para saltarla, queda en el log), escribe la curva, mueve el alias y crea la `risk_policy` siguiente. A una versión ya promovida es el *rollback*, sin re-predecir | $0 |
| `curve`, `risk-policy` | Local | A mano | Recalcula la curva de una versión; cambia la cobertura objetivo (CLI hasta la pantalla de 7.10) | $0 |

**Ciclo de un modelo nuevo** (hoy sin candidato: el primero saldrá de 6.5): `register` → `rescore` → `promote`. Promover antes del *re-scoring* dejaría el cockpit vacío, porque `review_predictions_current` solo muestra la versión promovida.

**Avisos:** las alertas de deriva publican `DriftAlertMessage` en `voc-incident-alerts-topic` y los avisos de calidad (`warning`, `retrain`, `rejected`) `ModelQualityMessage` en `voc-model-quality-topic`, los dos sin texto ni PII. Cloud Monitoring manda un correo cuando cualquiera de los dos tópicos recibe mensajes; el correo dice de qué suscripción leer. Ningún aviso dispara nada solo.

**Lo que hoy no está automatizado** (lo cubre 6.5):

* el reentrenamiento: el aviso `retrain` llega por correo y nadie entrena;
* el histórico de tópicos al activarse una versión nueva (6.5 lo pasa a un Job sobre los embeddings de cláusulas guardados): hoy lo re-asigna el delta en CPU, 20 000 reseñas por corrida de lo más reciente a lo más viejo (~33 días para ~660 000 negativas);
* las familias del histórico: hoy el delta re-etiqueta con Gemini, sin aviso ni tope de costo, lo que no tenga fila para el prompt vigente; 6.5 lo limita a los textos que Gemini nunca etiquetó ([ver 6.5](#feature-65-reentrenamiento-y-backfills)).

---

## 🧭 Insumos de EPIC-5 que cambian EPIC-1 y EPIC-2

Todos aplicados. La tabla queda como referencia de qué reemplazó a qué.

| Tema | Antes (EPIC-1 y EPIC-2) | Ahora | Evidencia |
| :--- | :--- | :--- | :--- |
| Modelo de sentimiento | `sentimiento_roberta`, Delora | RoBERTuito ajustado con la plata de Gemini (`robertuito_sentiment_v1`), fp32 en CPU | [registro de decisión](../analytics/decision_record.md) |
| Calibración | Ninguna | *Temperature scaling*, T 1.6811 | [calibración](../analytics/calibration/calibration_report.md) |
| Umbral HITL | Entropía ≥ 0.65 | Probabilidad máxima calibrada; 90 % de cobertura por defecto (umbral 0.974), configurable y versionado en `risk_policy` con su curva | [calibración](../analytics/calibration/calibration_design.md#31-decisión-del-autor-2026-10-22) |
| Taxonomía | 8 `ABSATopic`, un tópico obligatorio | 11 familias multi-etiqueta `aspects_v2_1` con marcas `u` y `s` (Gemini) y tópicos de BERTopic como capa aparte, con versión y curaduría | [tópicos](../analytics/topics/topics_report.md) |
| Filtro de longitud | 2 a 60 palabras | Sin filtro; elegibilidad `eligibility_rules_v1` con código (`NO_PREDICTED`) | [reglas](../analytics/eda/eligibility_rules.md) |
| Priorización | `tnss_numeric_calibrated`, `priority_weight_score` | Volumen de negativas por familia y marca `u`; los votos solo como contexto | [calibración, §4](../analytics/calibration/calibration_report.md#4-priorización-q4-decidido) |
| Salidas | `delora_predictions` (15 columnas) | 26 tablas y sus vistas del esquema v3 | [contrato](../contracts/analytics_outputs_v3.md) |
| Embeddings | 768 dimensiones e índice de Vertex | MiniLM de 384 en `text_embeddings`; sin índice ni endpoint | [escala](../analytics/scale/scale_report.md) |
| *Drift* | JSD de los 8 tópicos | z robusta y PSI por banco; familias y `u` como contexto, sin alerta | [escala, §2](../analytics/scale/scale_report.md) |
| Curaduría | `hitl_triage_audit_log` | `hitl_items`, `hitl_events`, `hitl_reviews`, `curation_topics`, inmutables | [contrato](../contracts/analytics_outputs_v3.md) |
| Cómputo | Sin definir | Delta y monitor en Cloud Run Jobs de CPU; *re-scoring* en la GPU de Kaggle; Gemini en Vertex AI dentro del proyecto | [escala](../analytics/scale/scale_report.md) |

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

Solo las vigentes. D5 se retiró (la reemplazó D13) y los dos huecos de diseño de 6.4 quedaron resueltos en D21 y D22. Las del 2026-10-24 se tomaron al implementar 6.3 y 6.4.

| # | Tema | Decisión |
| :---: | :--- | :--- |
| D1 | Dónde vive el código | `voc-common` solo contratos; `voc-nlp` la lógica pura; `ml-inference` una imagen con varios comandos. Se borró `services/ml-delora/` |
| D2 | Léxico `lexicon_v1` | Versionado en git dentro de `voc-nlp` (151 formas con su etiqueta agregada y su SHA-256); excepción aprobada a la regla de datos |
| D3 | Alertas | Todas en el monitor (6.4); el delta solo predice y escribe |
| D4 | Precisión del delta | RoBERTuito en fp32 en 1 vCPU; los pesos fp16 del registro se cargan en fp32; sin int8 |
| D6 | Histórico de familias, tópicos y embeddings | Hecho en 5.9 ([reporte, §2](../analytics/incidents/incidents_report.md#2-backfill-de-familias-y-tópicos-p9-3)); 6.3 solo lo carga |
| D7 | Piezas sin dueño | El delta crea los casos `low_confidence` y su oclusión; el monitor, `monitor_sample`, `agreement_sample` y `kpi_estimates` con PPI sobre el oro *dev* (más `gold_hitl` cuando exista) |
| D8 | Familias y `u` en el monitor | Se guardan en `drift_metrics` con su z y umbral nulo: nunca alertan ni suben la revisión |
| D9 | Delta | Un Job con pasos en serie y un modelo cargado a la vez; 2 GiB, a 4 GiB si la primera corrida lo pide |
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
| D26 | Botón de promoción (2026-10-24) | MLOps (7.9) promueve un candidato con un botón, que se habilita cuando su *re-scoring* está verificado. Antes de confirmar muestra el resultado de la regla de promoción (diferencias de κ y macro-F1 con su IC) y la curva nueva; si la regla no pasa, pide confirmación explícita y motivo (el `--force` de la CLI). El mismo panel hace el *rollback* a una versión que ya estuvo promovida. Ejecuta el comando `promote` en un Job y queda en el log con el actor y el motivo |
| D27 | Punto de partida del reentrenamiento (2026-10-24) | La receta de 5.4 desde el modelo base (`pysentimiento/robertuito-sentiment-analysis`), no desde el modelo vigente: cada versión sale solo de la receta y de un conjunto con hash, y un error de una versión no se hereda a la siguiente. Una semilla por reentrenamiento (en 5.4 las tres quedaron dentro de 0.01 de κ) |
| D28 | Conjunto de entrenamiento (2026-10-24) | La partición `entrenamiento` de la plata de 5.3 (63 720 textos, sin `NA`) más las revisiones de sentimiento del HITL de `low_confidence` y `drift_boost` (primera ronda, sin `no_evaluable`); la revisión reemplaza a la plata del mismo texto. Se excluyen `monitor_sample` y `agreement_sample` (miden el κ y alimentan el oro de PPI) y todo texto del oro *dev* y *test* |
| D29 | Gemini solo etiqueta lo que nunca etiquetó (2026-10-24) | El delta manda a Gemini solo los textos `NEG` sin ninguna fila en `review_aspects`, con cualquier prompt. Un cambio de prompt no re-etiqueta el histórico: las familias quedan con el prompt con el que se etiquetaron, y la serie mezcla prompts. Es un hueco aceptado por presupuesto (un backfill cuesta ~$60, unos $1 200 MXN, en un proyecto académico); en producción se re-etiquetaría. RoBERTuito, MiniLM y los tópicos, que no cuestan, solo procesan lo que llega por la ingesta diaria; sus históricos se rehacen con el *re-scoring* y el backfill de tópicos |
| D30 | Embeddings de cláusulas (2026-10-24) | Tabla `segment_embeddings` en BigQuery (vector de MiniLM por `text_key` × `segment_index`, agrupada por `text_key`), calculada una sola vez y extendida por el delta. Leer todos los vectores cuesta ~$0.02 por corrida y guardarlos ~$0.06 al mes. La re-asignación del histórico de tópicos corre en Cloud Run sobre ellos, sin Kaggle: el texto no sale de GCP |
| D31 | Plata reciente en cada reentrenamiento (2026-10-24) | Prendida por defecto: cada reentrenamiento sortea 20 000 textos de los meses posteriores a la plata de 5.3, los etiqueta con Gemini con el prompt de la plata y los suma al conjunto. Es lo que más acerca el modelo a los datos recientes, porque las revisiones humanas son pocas y son los casos difíciles. Cuesta ~$1 (~$0.048 por 1 000 textos) y lleva un tope de $2 por corrida en lugar de `--approve`, así que también corre en modo `auto`; `--recent-silver 0` la apaga |
| D32 | Disparo del backfill de tópicos (2026-10-24) | Lo lanza el delta cuando la versión de tópicos en uso no tiene su backfill terminado ni uno en curso; mientras tanto, el delta asigna tópicos solo a lo que llegó por la ingesta diaria |
| D33 | Calibración y curva de cada candidato (2026-10-24) | Un modelo recién entrenado exagera su seguridad; se corrige con un solo número (la temperatura) ajustado contra las reseñas que etiquetaron personas (el oro *dev*), como se hizo con el modelo vigente. Con la confianza corregida se calcula la curva de cobertura y riesgo: para cada porcentaje de reseñas que se aceptan sin revisión, cuántos errores quedan. El corte que se usa no es fijo: sale de la cobertura objetivo de la `risk_policy` (90 % por defecto, parámetro del apetito de riesgo que se cambia en 7.10). Los dos se calculan antes de `register` con el mismo oro *dev*; el error estimado sale un poco optimista, igual que en el modelo vigente, así que se comparan en las mismas condiciones. Además se guarda, sin costo (son ~800 reseñas y un parámetro), la curva de la temperatura: el error de calibración para cada temperatura probada, con la elegida marcada, y el diagrama de confiabilidad antes y después. MLOps (7.9) los muestra para decidir la promoción |
| D34 | Un switch de reentrenamiento por modelo (2026-10-24) | **Sentimiento:** `retrain_trigger` (`auto` o `manual`, `manual` en v1). En `auto`, cuando el κ trimestral cae bajo su piso, se entrena un candidato y se vuelve a predecir el histórico con él, pero no se pone en uso: eso lo decide una persona con el botón de promoción. Como mucho uno por trimestre. **Tópicos:** `topic_refit_trigger` (`scheduled` o `manual`, `scheduled` en v1). EPIC-5 no dejó evidencia para un umbral: `OT` no sirve como alarma (es el 0.6 % de las negativas y su κ autor–Gemini es 0) y que los tópicos no alineados detecten temas nuevos quedó como hipótesis. Por eso el re-ajuste sigue por calendario (`topic_refit_frequency`) o con el botón de MLOps, y una versión nueva solo se usa cuando el curador revisa sus tópicos. El monitor guarda como contexto, sin umbral, la proporción de cláusulas sin tópico (ruido; 36.2 % en el histórico de 5.9) y la de negativas cuyos tópicos no tienen familia en la curaduría (no alineados), para fijar un umbral cuando haya trimestres de datos. **Familias y marca `u`:** siguen como contexto sin umbral (D8); se decide si llevan umbral con las tasas que dé `drift-rates` en el primer monitor de dev |

### Parámetros que fija el dueño de negocio (EPIC-7, 7.10)

No son huecos de diseño: no hay evidencia en EPIC-5 para ellos ([registro de decisión](../analytics/decision_record.md), sección 4), así que la `risk_policy` v1 los deja nulos (D12).

| Parámetro | Nulo en v1 significa | Referencia |
| :--- | :--- | :--- |
| `hitl_weekly_cap` | Sin tope | La semana real de 5.9 dio 387 casos con el umbral del 90 % |
| `drift_boost_coverage`, `drift_boost_days`, `drift_boost_weekly_cap` | La alerta se registra y se publica, sin subida | La curva da el costo de cada cobertura |
| `human_agreement_sample_size`, `human_agreement_frequency` | Sin doble revisión entre personas | — |

---

## 🛠️ Pendientes en dev (del autor)

En orden. Hasta el paso 2 no existe ningún Job de ML en dev.

1. **Confirmar el `pulumi up` de 6.4** que borra el `roles/pubsub.publisher` de proyecto de `voc-sa-ml-backend` (falló porque faltaba la API de Cloud Resource Manager, ya agregada en `0c70310`). Un `pulumi preview` sin cambios lo confirma.
2. **Publicar y fijar la imagen:** mezclar en `main`, esperar el CD y correr `uv run python tools/deploy_images.py --project <proyecto> --apply`. Crea los Jobs `voc-ml-inference-delta`, `voc-ml-monitor`, `voc-ml-topics-refit` y `voc-ml-rescoring` y sus triggers. Commitear `infra/Pulumi.dev.yaml`.
3. **Exportar el oro:** `uv run python -m voc_analytics.labeling.export_gold_v3`, en `experiments/analytics`.
4. **Sembrar:** `uv run python -m ml_inference seed --actor-hash <sha256> --reason "..."`.
5. **Cargar el backfill:** `uv run python -m ml_inference load-local --actor-hash <sha256> --work <carpeta>`.
6. **Vocabulario:** `uv run python -m ml_inference build-vocab` para `robertuito_sentiment_v1`.
7. **Primer delta:** `gcloud run jobs execute voc-ml-inference-delta`; revisar duración y memoria en `inference_runs` (D9). Cubre los textos posteriores al snapshot y el lote que Gemini no etiquetó.
8. **Validar `daily_topic_labels`** contra `daily_topics_v0` de 5.9 en una muestra de días × banco.
9. **Primer monitor:** `gcloud run jobs execute voc-ml-monitor`; llena el histórico de `drift_metrics` sin alertas viejas, crea la muestra del trimestre, mide la calidad (~$0.05) y llena `kpi_estimates`.
10. **Tasas:** `gcloud run jobs execute voc-ml-monitor --args=drift-rates`. Con las de las familias y la marca `u` se decide si llevan umbral (D34).
11. **Avisos:** comprobar que llega un correo (el primero real o un mensaje de prueba en `voc-model-quality-topic`).
12. **Secreto de Kaggle:** `gcloud secrets versions add voc-kaggle-token` (hace falta antes del primer `rescore`, en 6.5).
13. **Borrar las copias locales** que usó la carga (F-11).

---

## 📦 Features

### FEATURE 6.1: Contratos de predicción v3 en `voc-common` ✅

**Terminada (2026-10-23).** Enums (`analytics_codes.py`), modelos por tabla (`predictions_v3.py`, `operations_v3.py`, `policies.py`, `hitl_v3.py`), `text_key` (SHA-256 igual a `TO_HEX(SHA256(...))` de BigQuery) y `bq_schema` con el registro de las 26 tablas (`ANALYTICS_V3_TABLES`). Los invariantes del esquema v3 se validan en los modelos. Se retiraron los contratos de EPIC-1 (`AnalyzedReviewPrediction`, `HitlTriageAuditRecord`, `IncidentAlertMessage`, `ABSATopic`, el filtro de 2 a 60 palabras y sus `Settings`). Después se sumó `ModelQualityMessage` (6.4). Cobertura 99.9 %. Las columnas que el borrador dejaba abiertas están en la [sección 8 del contrato](../contracts/analytics_outputs_v3.md#8-columnas-fijadas-al-implementar-2026-10-23).

### FEATURE 6.2: Infraestructura de salidas y curadurías ✅

**Terminada y desplegada en dev (2026-10-24).** `infra/modules/analytics_bq.py` crea las 26 tablas (partición mensual y agrupación donde existe la columna) y las vistas de `infra/modules/sql/`. Se borraron `delora_predictions`, `hitl_triage_audit_log`, el índice de 768 y el endpoint de Vertex. El bucket suma `ml_artifacts/` (sin caducidad) y `backfill/` (7 días). `voc-sa-ml-backend` recibe `storage.objectUser`. Los Jobs de ML y sus triggers se crean solo con `ml_inference_image` fijada. Cobertura de `infra/modules` 100 %. FMEA F-21 calificada (RPN 40). Lección del despliegue: `at` es palabra reservada de BigQuery; una prueba comprueba que ninguna vista la lea sin comillas.

### FEATURE 6.3: Servicio de inferencia batch

**Código terminado (2026-10-24); falta correrlo en dev** (pendientes 2 a 8).

**Entregado:**

* `voc-nlp`: `eligibility`, `lexicon`, `calibration`, `hitl`, `sentiment_model`, `explain` (`occlusion_v1`: cuánto baja la probabilidad de la clase predicha al quitar cada palabra), `aspects` y `topics`. Contrastado con EPIC-5: elegibilidad y léxico iguales en 662 filas sintéticas; RoBERTuito da probabilidades idénticas con los pesos reales. Cobertura 100 %.
* `ml-inference`: `delta`, `seed`, `load-local`, `register`, con `bq_io` (tabla temporal y `MERGE`), `state`, `engines` y `artifacts`. Las etiquetas y embeddings ya conocidos se reutilizan sin volver a llamar al modelo; un texto que Gemini omite queda pendiente para el día siguiente. Cobertura 98 %.
* Imagen multi-stage con torch de CPU (2.48 GB), usuario 10001, sin descargas en ejecución. CI con pruebas e imagen; `tools/deploy_images.py` fija las tres imágenes del mismo commit.

**Terminado cuando** (se comprueba en dev):

* [ ] `review_predictions` tiene una fila por reseña del export del 2026-10-20 (2 653 238) con `robertuito_sentiment_v1`, y los conteos por banco y `eligibility_code` reproducen `eligibility_v1_counts.json` salvo las reseñas que cambiaron después;
* [ ] `review_aspects` tiene los 659 316 textos de 5.9, `text_embeddings` los 1 429 675 `text_key` y `topic_assignments` los tópicos de `topics_v1`;
* [ ] `daily_topic_labels` reproduce `daily_topics_v0` en una muestra;
* [ ] el delta programado corre dentro de 2 GiB (o 4) con su duración y memoria en `inference_runs`;
* [x] los *quality gates* pasan sin red.

### FEATURE 6.4: Monitoreo y ciclo de vida

**Código terminado (2026-10-24); falta correrlo en dev** (pendientes 1 y 9 a 11).

**Entregado:**

* `voc-nlp`: `drift` (`robust_z`, `psi`, `entry_month` y los intervalos de longitud, iguales a los de 5.7), `selective` (curva, punto de cobertura y *bootstrap*), `ppi` (PPI++ con pesos, `gap_stars` en la escala de 1 a 5 y los 13 KPI), `agreement` (κ, macro-F1, acuerdo exacto, κ por familia), `sentiment_gemini` (el prompt de la plata) y `topics_refit`. Cobertura 99 %.
* `ml-inference`, comando `monitor`: `drift_job` (series del contrato, ids deterministas, una subida por banco, cierre de subidas), `samples` (sorteo reproducible, siempre `blind`), `quality` (κ trimestral, tasa de corrección semanal, acuerdo semanal con Gemini y validación de familias por modelo y prompt) y `kpis` (`raw` y `ppi` por banco y mes, recalcula el mes en curso, el anterior y los que les falte una serie).
* `ml-inference`: `lifecycle` con `promote`, `curve` y `risk-policy` (D18, D19), `rescore` (D13), `topics_refit` (D21, D22), `build-vocab` (D24) y `drift-rates`. Cobertura 99 %.
* `infra/`: `voc-model-quality-topic`, publicación por tópico en lugar del permiso de proyecto, avisos por correo (`modules/alerting.py`), Job `voc-ml-rescoring` y secreto `voc-kaggle-token`, Job y trigger `voc-ml-topics-refit` (quinto Scheduler; el *free tier* cubre tres, ~$0.10 al mes cada uno extra). Cobertura 99 %.

**Terminado cuando** (se comprueba en dev):

* [ ] corrido sobre el histórico, `drift-rates` reproduce las tasas de alerta de 5.7 (de 0 a 1.4 meses al año por serie y banco);
* [ ] las alertas llegan al tópico con los umbrales de cada banco y por correo;
* [ ] `model_quality` registra las mediciones y `kpi_estimates` llena el cockpit;
* [x] promoción, curva, política nueva y *rollback* probados con dobles (la primera corrida real llega con el primer candidato de 6.5);
* [x] *re-scoring* probado con Kaggle, GCS y BigQuery simulados (no se ha corrido);
* [ ] el portal de EPIC-7 consulta todo lo anterior.

### FEATURE 6.5: Reentrenamiento y backfills

**Objetivo:** reentrenar RoBERTuito y rehacer los históricos que dependen de un modelo sin pasar por la máquina de nadie y sin gastos sin aprobar. El entrenamiento y el *re-scoring* corren en Kaggle; la re-asignación de tópicos, en Cloud Run (D30); Gemini solo etiqueta textos que nunca etiquetó (D29).

**Estado (2026-10-24):** detallada, con todas sus decisiones aprobadas (D25 a D34). Se implementa por partes, una sesión por parte si el contexto lo pide:

1. [x] **`voc-common`** (2026-10-24): `RunKind` (`training`, `topic_backfill`, `aspect_backfill`), `PromotionVerdict`, `RetrainTrigger` y `TopicRefitTrigger`; los dos switches en `RiskPolicy` (`retrain_mode` y `topic_refit_mode` dan el valor efectivo con nulo); los modelos `PromotionCheckResult` y `SegmentEmbedding`; el contrato v3. Las dos tablas **todavía no están en `ANALYTICS_V3_TABLES`**: entran con su tabla en `infra/` (parte 2). `risk_policy` gana dos columnas nulas: el próximo `pulumi up` las agrega, y la imagen de `ml-inference` que escriba políticas debe desplegarse después. Pruebas de `infra/` (125) y `ml-inference` (135) sin cambios.
2. [x] **`infra/`** (2026-10-24): `promotion_checks` y `segment_embeddings` (agrupada por `text_key`) en `ANALYTICS_V3_TABLES` y `TABLE_LAYOUTS` (28 tablas); los cuatro Jobs sin Scheduler (`voc-ml-training` con la clave de Kaggle, `voc-ml-topics-backfill`, `voc-ml-aspects-backfill`, `voc-ml-promote`), con sus exportaciones; `roles/run.developer` de `voc-sa-ml-backend` solo sobre `voc-ml-training`, `voc-ml-rescoring` y `voc-ml-topics-backfill` (campo `executed_by_ml` de `MlJobSpec`); los comandos en el correo de `voc-model-quality-topic`. Desvíos del detalle: el comando de promoción del correo lleva `--actor-hash` y `--reason` porque `promote` los exige; el correo ya no dice que el aviso "no dispara nada solo" sin más, sino que eso vale con `retrain_trigger` en `manual`; la prueba provisional de `voc-common` quedó como prueba de que las dos tablas están en el registro (sigue cubriendo las columnas nulas de `risk_policy`). Pruebas de `infra/` 127 (cobertura de `infra/modules` 100 %), `voc-common` 344, `ml-inference` 135. Aplicada en dev con `pulumi up` (autor, 2026-10-25).
3. [x] **`voc-nlp`** (2026-10-25): `training.py` `[sentiment]` (`TrainParams`, `val_split`, `train`, `predict`, `kernel_source`) y `calibration.fit_temperature`. Desvíos del detalle: `TrainParams` suma `weight_decay` (0.01) y `split_seed` (20261019, la de 5.4: con los mismos textos sale la misma validación; `seed` = 1 solo controla el ajuste); `train` recibe además `device` y `log`, y `TrainResult` trae el historial por época, `best_epoch`, los conteos, los segundos y el dispositivo; `kernel_source(run, params, input_dir, work_dir)` lleva la corrida y la receta, como el kernel del *re-scoring*, y copia este módulo con `agreement` (κ y macro-F1 sin scikit-learn); el kernel lee los parquet con `pyarrow`, que trae la imagen de Kaggle. El contrato del dataset y de la salida del kernel queda en las constantes del módulo (`train.parquet` con `input_ids`, `label` e `is_val`; `dev.parquet` con `key` e `input_ids`; el modelo base en `base/`; salida `model/` en fp16 con tokenizador, `dev_preds.parquet` y `train_log.json` con `run`), para la parte 5. `predict` repite el de `sentiment_model` porque ese módulo importa `pysentimiento`, que el kernel no necesita. `fit_temperature` usa sección áurea sobre log T en lugar de Nelder-Mead de scipy (la pérdida es convexa en 1 / T); la prueba lo iguala al ajuste original al 0.1 %. Pruebas de `voc-nlp` 137 (`training.py` 99 %, `calibration.py` 100 %), con una corrida completa del kernel sobre un RoBERTa diminuto.
4. [ ] `ml-inference`, en tres subtareas (decisión del autor, 2026-10-25: la parte completa no cabe en una pasada):
   * 4a. [x] **Delta y familias** (D29, 2026-10-25): el delta solo manda a Gemini las negativas sin ninguna fila en `review_aspects`, con cualquier `prompt_version`; una reseña cuyo texto ya tiene familias copia la etiqueta más reciente con su `prompt_version`, `guideline_version` y `llm_model`, y una reseña ya etiquetada con otro prompt no gana fila nueva. Pruebas de `ml-inference` 137 (`delta.py` 99 %).
   * 4b. [x] **`segment_embeddings` y backfill de tópicos** (D30, D32, 2026-10-25): el delta asigna tópicos solo a las negativas que predijo una corrida `delta` (la suya o una registrada en `inference_runs`), reutiliza los vectores de `segment_embeddings` y guarda los de las cláusulas nuevas; si quedan negativas sin asignar a la versión vigente y `voc-ml-topics-backfill` no tiene una ejecución en curso, lo lanza. `topics_backfill.py` (comando `topics-backfill`): embebe y guarda los textos pendientes sin vectores, lee los vectores por páginas (`bq_io.iter_rows`) en lotes de unas 50 000 cláusulas que no parten un texto, asigna con el modelo congelado sin leer el texto (`BERTopic.transform` no lo usa si recibe los vectores), escribe después de cada lote (se retoma si se corta) y verifica que no quede ninguna negativa sin asignar. `jobs.py` (`CloudRunJobs.execute` y `running`, API REST v2 de Cloud Run). `load_local.py` carga `segment_embeddings` desde `topics/emb_segments_minilm.npy` del backfill de 5.9 (1 035 052 vectores en el orden de `segment_topics_v0.parquet`). Desvíos del detalle: "en curso" se pregunta a Cloud Run (las ejecuciones sin `completionTime`), porque `inference_runs` solo registra corridas terminadas y no guarda la versión de tópicos, y el delta lanza el backfill mientras queden negativas sin asignar (no una vez por versión con registro propio: si un backfill falla, el siguiente delta lo vuelve a lanzar); `jobs.py` suma `running` a `execute`; los embeddings de texto (`text_embeddings`) siguen llenando cualquier fila del TDS sin vector, porque no dependen de ningún modelo versionado y solo cubren huecos. Pruebas de `ml-inference` 158 (`topics_backfill.py` 100 %, `delta.py` 99 %, `jobs.py` 97 %, `load_local.py` 97 %).
   * 4c. [ ] **`aspects-backfill`**: estimación sin `--approve`, tope `--max-usd`, reanudación y fila `aspect_backfill` en `inference_runs`; `gemini_usd_per_1000` (0.092) en `config.py`.
5. [ ] `ml-inference`: entrenamiento, `promotion_checks`, switches en el monitor y el re-ajuste, `jobs.py`.

#### Los tres backfills

| Backfill | Cuándo hace falta | Dónde | Costo | Estado |
| :--- | :--- | :--- | :--- | :--- |
| **Sentimiento** (*re-scoring*) | Cada candidato, antes de `promote` | Kaggle con GPU (`voc-ml-rescoring`) | $0 | Hecho en 6.4; 6.5 le suma guardar la regla de promoción |
| **Tópicos** (re-asignación del histórico) | Al activarse una versión nueva de tópicos (trimestral) | Cloud Run en CPU (`voc-ml-topics-backfill`, nuevo), sobre los embeddings de cláusulas guardados (D30) | ~$0.02 de lectura en BigQuery por corrida | Nuevo. Reemplaza la re-asignación por tandas del delta |
| **Familias** (Gemini) | Solo si el autor lo decide (prompt nuevo) | Gemini en Vertex AI (`voc-ml-aspects-backfill`, nuevo) | Medido en 5.9: **$60.61 por 659 316 textos** ($0.092 por 1 000), con el precio introductorio vigente hasta el 2026-12-31 | Nuevo: comando con costo estimado y `--approve`. Por presupuesto, no se espera correrlo (D29) |

#### Decisiones del autor (2026-10-24)

Todas están en la [tabla de decisiones](#-decisiones-de-diseño-de-epic-6-autor-2026-10-23) como D25 a D34. Además:

* **La mejor alternativa para las familias sería destilarlas a un clasificador propio**, entrenado con las etiquetas de Gemini y corrido en Kaggle, como RoBERTuito con la plata: cada backfill costaría $0 y dejaría de depender del precio y de la vigencia del modelo de Gemini. **No se hace porque implica un modelo nuevo**, que tendría que pasar por la experimentación y por la regla de familias (acuerdo exacto ≥ 53 % y sin familias frecuentes bajo su IC en `aspects_gold_v2_1`). Eso es trabajo de EPIC-5, no de despliegue, y queda fuera del alcance de la tesis.
* **Descartadas para las familias:** re-etiquetar el histórico en cada cambio de prompt (~$60, unos $1 200 MXN, que un proyecto académico no puede costear cada vez; en producción sí se haría) y *batch prediction* de Vertex AI (abarataría el comando, por verificar con el precio vigente, pero no cambia la decisión).
* **Descartados para los embeddings de cláusulas:** un vector por fila del TDS (mezcla la salida de la sanitización con artefactos del modelo y repite el vector de textos idénticos) y un almacén clave-valor (Bigtable y Memorystore cobran por estar encendidos; Firestore es lento y más caro para leer el millón de vectores de una vez, que es el uso real).
* **Disparo del reentrenamiento (D25)** y **botón de promoción (D26)**.

#### Archivos que cambian o se crean

**`packages/voc-common/`:**

* `analytics_codes.py`: `RunKind` suma `TRAINING = "training"`, `TOPIC_BACKFILL = "topic_backfill"` y `ASPECT_BACKFILL = "aspect_backfill"`; nuevos `RetrainTrigger` (`auto`, `manual`) y `TopicRefitTrigger` (`scheduled`, `manual`).
* `policies.py`: `RiskPolicy.retrain_trigger: RetrainTrigger | None` (nulo = `manual`) y `RiskPolicy.topic_refit_trigger: TopicRefitTrigger | None` (nulo = `scheduled`), para que las versiones ya sembradas sigan valiendo (D34).
* `operations_v3.py`: `PromotionCheckResult` (tabla `promotion_checks`): `candidate_version`, `current_version`, `gold_version`, `n`, las diferencias de κ y de macro-F1 con su IC en columnas planas (`kappa_diff`, `kappa_ci_low`, `kappa_ci_high` y las tres de `macro_f1`), `verdict` (`better`, `tie`, `worse`, validado contra los IC), `run_id`, `computed_at`.
* `predictions_v3.py`: `SegmentEmbedding` (tabla `segment_embeddings`, D30): `text_key`, `segment_index`, `segmenter`, `embedding_model`, `embedding` (384 floats), `run_id`, `created_at` (los nombres de `TextEmbedding`).
* `bq_schema.py`: las dos tablas en `ANALYTICS_V3_TABLES` (28 tablas), en el mismo cambio que su `TABLE_LAYOUTS` de `infra/`: `analytics_bq.py` exige que el registro y las tablas coincidan.
* [Contrato v3](../contracts/analytics_outputs_v3.md): las dos tablas, los dos switches, los tres `RunKind` y las series de contexto `topic_noise_share` y `topic_unaligned_share` de `drift_metrics`.

**`packages/voc-nlp/`:**

* `training.py` `[sentiment]`: port de `voc_analytics.sentiment.models.finetune` y de `encoder.val_split` y `train_defaults`, sin constantes de proyecto.

  ```python
  @dataclass(frozen=True)
  class TrainParams:  # la receta de 5.4 (D27)
      base: str = "pysentimiento/robertuito-sentiment-analysis"
      epochs: int = 2; lr: float = 2e-5; warmup: float = 0.06; clip: float = 1.0
      batch: int = 32; accum: int = 1; max_length: int = 128; seed: int = 1; val_share: float = 0.05

  def val_split(groups: Sequence[str], share: float, seed: int) -> NDArray[np.bool_]: ...  # por texto, como 5.4
  def train(model, ids: Sequence[Sequence[int]], labels: NDArray[np.int64], is_val: NDArray[np.bool_],
            params: TrainParams) -> TrainResult: ...  # mejor época por macro-F1 de validación
  def kernel_source() -> str: ...  # el script del kernel, sin dependencias fuera de torch y transformers
  ```

* `calibration.py`: suma `fit_temperature(proba: NDArray, y: NDArray, w: NDArray) -> float`, port de `calibration.calibrate.fit` (solo temperatura).

**`services/ml-inference/`:**

* `training.py` (comando `train`, Job `voc-ml-training`):

  ```python
  def build_training_set(bigquery, storage, settings, now) -> TrainingSet: ...  # D28; manifiesto con conteos y SHA-256
  def run_training(job: Training, writer: StagingMergeWriter, timeout_sec: float,
                   now: Callable[[], datetime]) -> InferenceRun: ...
  ```

  Pasos: `build` (plata de `archive/epic5/labels/silver_v0/`, las revisiones del HITL y la plata reciente (D31); en memoria) → `tokenize` (`preprocess_tweet` y el tokenizador, como el *re-scoring*: a Kaggle suben ids de tokens y etiquetas, no texto) → `push_dataset` (ids, etiquetas, ids del oro *dev* y el modelo base de `ml_artifacts/sentiment/base/`) → `run_kernel` y `wait_kernel` (GPU, sin internet) → `pull` (pesos fp16, métricas de validación y predicciones del oro *dev*) → `calibrate` (D33: temperatura, su curva y la curva de cobertura y riesgo) → `publish` (pesos y `training_vocab.txt` en `ml_artifacts/sentiment/<versión>/`) → `register` (con `training_data_hash` del manifiesto) → `cleanup` (borra el dataset de Kaggle tras verificar la subida). En `auto` termina lanzando `voc-ml-rescoring` (D34). La versión nueva sigue el patrón vigente: `robertuito_sentiment_v<n>` y `temperature_v<n>`.
* `rescore.py`: al verificar la carga, calcula `check_promotion` contra la versión promovida y escribe `promotion_checks`. `promote` lo sigue recalculando (es barato) y se niega igual que hoy.
* `topics_backfill.py` (comando `topics-backfill`, Job `voc-ml-topics-backfill`, D30): lee de `segment_embeddings`, por lotes de 50 000 cláusulas, las de las negativas de dos palabras o más sin asignación para la versión activa; asigna con el UMAP y el BERTopic congelados de la versión y escribe `topic_assignments` con `MERGE`. Una negativa sin vectores (por ejemplo, una que pasó a `NEG` tras una promoción) se segmenta y se embebe en el momento, y sus vectores se guardan. Verifica que cada negativa pendiente quedó asignada.
* `aspects_backfill.py` (comando `aspects-backfill`, Job `voc-ml-aspects-backfill`), para cuando el autor decida pagar un prompt nuevo:
  * sin `--approve`: cuenta los textos únicos de las negativas sin fila para el `prompt_version` vigente y escribe en el log el costo estimado con `gemini_usd_per_1000` (0.092); no llama a Gemini;
  * con `--approve --max-usd <tope>`: etiqueta como el delta (lotes de 100, reintento en lotes más chicos) y se detiene al llegar al tope con el costo medido; una corrida interrumpida se retoma sin repetir lo hecho. Fila en `inference_runs` con `kind = aspect_backfill` y su costo.
* `delta.py` (D29):
  * familias: solo los textos `NEG` sin ninguna fila en `review_aspects`, con cualquier `prompt_version`;
  * tópicos y embeddings: solo lo que llegó por la ingesta diaria (filas que predijo una corrida `delta`); guarda los vectores de las cláusulas nuevas en `segment_embeddings`; lanza `voc-ml-topics-backfill` si hace falta (D32).
* `load_local.py`: carga `segment_embeddings` si 5.9 guardó los vectores de las cláusulas en `data/backfill/20261022/`; si no, los calcula una vez.
* `monitor/quality.py`: con `retrain_trigger = auto`, al escribir `retrain` lanza `voc-ml-training` si no hay un reentrenamiento del trimestre (D34).
* `monitor/drift_job.py`: suma `topic_noise_share` y `topic_unaligned_share` por banco y mes, con umbral nulo (D34).
* `topics_refit.py`: con `topic_refit_trigger = manual`, el Job programado no re-ajusta; solo `--force` (el botón de MLOps).
* `jobs.py` (nuevo): `execute(job: str, args: Sequence[str]) -> str`, el `jobs.run` de Cloud Run con argumentos; lo usan el delta, el monitor, el entrenamiento y, en EPIC-7, la API.
* `seed.py`: la `risk_policy` v1 nace con `retrain_trigger = manual` y `topic_refit_trigger = scheduled`.
* `config.py`: `training_kernel_timeout_sec` (3 h) y `gemini_usd_per_1000` (0.092).

**`infra/`:**

* `cloud_run.py`: cuatro `MlJobSpec` nuevos, sin Scheduler:
  * `voc-ml-training` (`train`; 2 vCPU, 4 GiB, 4 h, sin reintentos, secreto de Kaggle);
  * `voc-ml-topics-backfill` (`topics-backfill`; 2 vCPU, 4 GiB, 2 h, sin reintentos; a 8 GiB si UMAP no cabe con lotes de 50 000);
  * `voc-ml-aspects-backfill` (`aspects-backfill`; 1 vCPU, 2 GiB, 6 h, sin reintentos);
  * `voc-ml-promote` (`promote`; 1 vCPU, 2 GiB, 30 min, sin reintentos), para el botón de EPIC-7.
* IAM: `voc-sa-ml-backend` recibe `roles/run.developer` solo sobre `voc-ml-training`, `voc-ml-rescoring` y `voc-ml-topics-backfill` (ejecutar con argumentos). El permiso de la API sobre `voc-ml-training`, `voc-ml-rescoring` y `voc-ml-promote` lo agrega EPIC-7 con su cuenta.
* `alerting.py`: el texto de la política de `voc-model-quality-topic` suma el comando del reentrenamiento (`gcloud run jobs execute voc-ml-training`) y el de la promoción.
* `analytics_bq.py`: `promotion_checks` y `segment_embeddings` (agrupada por `text_key`).

**Paso único del autor:** subir el modelo base (`pysentimiento/robertuito-sentiment-analysis`, licencia no comercial) a `ml_artifacts/sentiment/base/` y comprobar que `labels_prompt_v3.parquet` de la plata está en `archive/epic5/labels/silver_v0/` (el código de hoy solo lee `texts.parquet` y `rows.parquet` de ahí).

**Efecto en el portal (EPIC-7):** con D29, las familias de un mismo periodo pueden venir de prompts distintos. Las gráficas de familias del cockpit (7.5) marcan la fecha de cada cambio de prompt y el `prompt_version` de cada tramo.

#### Pruebas

Sin red ni descargas; cobertura ≥ 85 % (≥ 80 % en `infra/`).

* `voc-nlp`:
  * `test_training.py`: con un RoBERTa diminuto aleatorio, una época baja la pérdida, la mejor época se elige por macro-F1 de validación, la partición agrupa por texto y es reproducible con su semilla, y `kernel_source` se compila;
  * `test_calibration.py`: `fit_temperature` recupera una T conocida en datos sintéticos e iguala a `calibrate.fit` en un caso fijo.
* `ml-inference` (Kaggle, GCS, BigQuery y Cloud Run simulados):
  * `test_training.py`: el conjunto excluye `monitor_sample`, `agreement_sample` y el oro; la revisión reemplaza a la plata; la plata reciente se detiene al llegar a su tope; a Kaggle no sube texto; un kernel fallido o que excede el tiempo deja la corrida en `failed` sin registrar; el registro lleva `training_data_hash`; en `auto` se lanza el *re-scoring* y en `manual` no;
  * `test_rescore.py`: la carga verificada escribe `promotion_checks`, la fallida no;
  * `test_topics_backfill.py`: solo procesa las negativas sin asignación de la versión activa; embebe y guarda los vectores que faltan; la verificación falla si una negativa queda sin asignar;
  * `test_aspects_backfill.py`: sin `--approve` no llama a Gemini; con tope, se detiene al alcanzarlo; una segunda corrida retoma;
  * `test_delta.py`: Gemini nunca recibe un texto que ya tiene familias con otro prompt; los tópicos solo cubren lo que llegó por la ingesta; los vectores de las cláusulas nuevas se guardan; el backfill de tópicos se lanza una vez por versión;
  * `test_quality.py`: `retrain` con `auto` lanza el entrenamiento una vez por trimestre; con `manual` o nulo, no.
  * `test_drift_job.py`: las dos series de tópicos se guardan y nunca alertan;
  * `test_topics_refit.py`: con `manual`, el Job programado no re-ajusta y `--force` sí.
* `infra/`: los cuatro Jobs con su memoria, comando, secreto y sin Scheduler; el permiso de ejecución solo sobre sus Jobs; las dos tablas; el comando en el texto de la alerta.

#### Terminado cuando

* un reentrenamiento manual en dev produce un candidato registrado con su T, su curva, su `training_data_hash` y su vocabulario, entrenado desde el modelo base y sin pasar por la máquina de nadie;
* su *re-scoring* deja `promotion_checks` con la regla, y `promote` (o su *rollback*) funciona sobre él;
* `segment_embeddings` tiene los vectores de las cláusulas del histórico, y el backfill de tópicos de una versión activada llena `topic_assignments` sin Kaggle;
* el delta ya no manda a Gemini textos que tienen familias, ni re-asigna el histórico;
* `aspects-backfill` estima sin gastar y, aprobado, respeta el tope;
* en `auto`, un `retrain` simulado lanza la cadena hasta el *re-scoring* y se detiene antes de promover;
* la FMEA refleja F-13 (entrenamiento en Kaggle) con el modo `auto`.

---

## ✅ Checklist de Aceptación de la Épica 6

* [x] Contratos v3 en `voc-common`, con `bq_schema` y su contrato en `docs/contracts/` (6.1).
* [x] Tablas y vistas v3, IAM y avisos aprovisionados con Pulumi; lo de EPIC-2 retirado (6.2).
* [ ] Jobs de ML creados en dev con la imagen fijada (6.2, 6.3).
* [ ] Backfills de 5.8 y 5.9 cargados y delta diario en operación (6.3).
* [ ] Política HITL y curva versionadas en BigQuery; el delta marca con la política vigente (6.3).
* [ ] Monitor de deriva, calidad y KPI corriendo en dev con las tasas de 5.7 (6.4).
* [ ] Reentrenamiento y backfills de sentimiento, tópicos y familias con costo aprobado (6.5).
* [ ] *Quality gates* del monorepo (`ruff`, `pyrefly`, `bandit`, `pytest` con cobertura ≥ 85 %, ≥ 80 % en `infra/`) sin errores al cerrar la épica (pasaban al cerrar el código de 6.4).
