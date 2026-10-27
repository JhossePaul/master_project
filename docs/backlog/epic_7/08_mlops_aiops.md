# Paso 8. Feature 7.9: MLOps y AIOps

* **Estado (2026-10-26):** Implementado y probado en local (API, `ml-inference`, `voc-common`, infraestructura en código y portal). Falta lo que exige dev y la aprobación del autor: aplicar la infraestructura, mirar el registro contra dev y re-ajustar tópicos desde el botón. Detalle en "Avance".
* **Nivel:** importante.
* **Depende de:** pasos 2 y 5 (componentes de la curva y lógica movida a `voc-nlp`), y la decisión B5.3 del paso 0 (autoría del re-ajuste de tópicos).
* **Objetivo:** vigilar el modelo, las familias, los tópicos y el pipeline (lo que mide el monitor de EPIC-6), cada señal con su umbral vigente y su estado; ver el registro de modelos, y que un administrador lance desde aquí reentrenar, *re-scoring*, promover, *rollback* y re-ajustar tópicos, con quién y por qué.

## 1. Señales y fuentes

| Bloque | Fuente | Umbral | Estado |
| :--- | :--- | :--- | :--- |
| κ trimestral en la muestra de monitoreo | `model_quality` (`signal = kappa_monitor`) | `retrain_kappa_floor` (0.89) | `ok` o `retrain` |
| Tasa de corrección de la cola (4 semanas) | `model_quality` (`correction_rate`) | `warn_correction_rate` (0.28) | `ok` o `warning` |
| Acuerdo con Gemini (4 semanas) | `model_quality` (`gemini_agreement`) | `warn_agreement_floor` (0.94) | `ok` o `warning` |
| Revalidación de las familias | `model_quality` (`families_validation`, con `llm_model` y `prompt_version`) | `families_exact_floor` (0.53) y `families_min_prevalence` (0.05) | `ok` o `rejected` |
| Curva de cobertura y riesgo vigente | `hitl_coverage_curves` | Cobertura objetivo | — |
| Tópicos (contexto, sin umbral) | `drift_metrics` (`topic_noise_share`, `topic_unaligned_share`) por banco y mes | Ninguno | — |
| Deriva de entrada y de predicción | `drift_metrics` por banco, mes y serie | El de la `drift_policy` del banco | `alert` |
| Registro de modelos | `model_versions` (todas las filas: cada cambio de estado es una), `promotion_checks` | Regla de promoción | `candidate`, `promoted`, `retired` |
| Corridas | `inference_runs_current` | Memoria: 4 GiB del delta | `running`, `succeeded`, `failed` |
| Ingesta | `ingestion_runs_log_v2` (deduplicado por `audit_event_id`) | — | `COMPLETED`, `FAILED`… |
| No predecibles por motivo | `eligibility_counts` | — | — |

**Huecos conocidos:**

* **El monitor no escribe en `inference_runs`:** su última corrida se infiere de `MAX(computed_at)` de `kpi_estimates` y no hay registro de su duración ni de su memoria. Se anota en EPIC-8.
* **La ingesta no tiene costo:** la duración sale de `MIN` y `MAX(updated_at)` por `run_id`, y el costo se muestra como "sin dato". Medirlo exigiría la exportación de facturación de Cloud Billing, que queda fuera del alcance.

## 2. Acciones sobre el modelo

Todas son de rol administrador, abren `ConfirmWithReason` y ejecutan un Job de EPIC-6 con `jobs.run` y sus argumentos.

| Acción | Se habilita cuando | Job y argumentos |
| :--- | :--- | :--- |
| **Reentrenar** | `retrain_trigger` es `manual` (o nulo), la señal `kappa_monitor` del último periodo está en `retrain` y no hay una corrida `training` `running` más reciente que el tiempo máximo del Job. El diálogo avisa del costo (~$1 de Gemini, tope $2) y de que el texto sale a Kaggle | `voc-ml-training`: `["train", "--actor-hash=<h>", "--reason=<motivo>"]` |
| ***Re-scoring*** | Hay un candidato sin fila en `promotion_checks` y no hay otro *re-scoring* en curso | `voc-ml-rescoring`: `["rescore", "--model-version=<v>", "--actor-hash=<h>", "--reason=<motivo>"]` |
| **Promover** | El candidato tiene fila en `promotion_checks` (su *re-scoring* está verificado). Antes de confirmar se ven el veredicto, las diferencias de κ y macro-F1 con su IC, la curva nueva, la temperatura y el diagrama de confiabilidad. Con `verdict = worse`, pide además escribir `FORZAR` y agrega `--force` | `voc-ml-promote`: `["promote", "--model-version=<v>", "--actor-hash=<h>", "--reason=<motivo>"]` (+ `"--force"`) |
| ***Rollback*** | La versión ya estuvo `promoted` alguna vez y no es la vigente | El mismo comando `promote` con esa versión |
| **Re-ajustar tópicos** | `topic_refit_trigger` es `manual` y no hay un re-ajuste en curso. Con `scheduled`, el botón muestra la próxima fecha programada y remite a Administración para cambiar el modo (pregunta `M-02`) | `voc-ml-topics-refit`: `["topics-refit", "--force", "--actor-hash=<h>", "--reason=<motivo>"]` (requiere B5.3) |

* **Cliente de Jobs** (`api_backend/jobs.py`): una copia mínima de `ml_inference.jobs.CloudRunJobs.execute`: un POST a `https://run.googleapis.com/v2/projects/<p>/locations/<r>/jobs/<job>:run` con `{"overrides": {"containerOverrides": [{"args": [...]}]}}` y `google.auth.transport.requests.AuthorizedSession`. Devuelve el nombre de la operación. Se copia en lugar de importarse porque `ml-inference` arrastra dependencias pesadas, y la prueba fija el mismo formato de petición que la de `ml-inference`.
* **Lista cerrada:** la API solo ejecuta esos cuatro Jobs con esos subcomandos; los argumentos se arman en el servidor, nunca vienen del cliente.
* **Después de lanzar**, la pantalla consulta `inference_runs_current` cada 30 segundos mientras está abierta, para mostrar la corrida.
* **Cambio en `ml-inference` (B5.3):** `topics-refit` acepta `--actor-hash` y `--reason` y escribe sus filas de inicio y cierre en `inference_runs` con `RunKind.TOPIC_REFIT` (nuevo en `voc_common.analytics_codes`), como `train`. Pruebas en `ml-inference` y `voc-common`.
* **Diagrama de confiabilidad y temperatura:** salen de `training_manifest.json`, junto a los pesos de cada versión en `ml_artifacts/`. La API lo lee con `google-cloud-storage` (se agrega la dependencia), con el permiso condicionado al prefijo `ml_artifacts/` del paso 1. Si el manifiesto no existe (`robertuito_sentiment_v1` se registró desde los experimentos), se muestran los JSON de calibración de `docs/analytics/calibration/` y se dice de dónde vienen.

## 3. API (`sections/mlops/`)

Lectura: rol analista. Acciones: rol administrador.

| Método y ruta | Respuesta |
| :--- | :--- |
| `GET /api/v1/mlops/quality` | Por señal: serie de `model_quality` (periodo, valor, IC, `n`, umbral, estado, `model_version` o `llm_model` y `prompt_version`) |
| `GET /api/v1/mlops/drift?metric=` | `drift_metrics` por banco y mes de la serie (valor, línea base, z o PSI, umbral, alerta), y la lista de series disponibles |
| `GET /api/v1/mlops/topics-context` | Las dos series de tópicos por banco y mes, con las familias y `u` del mismo periodo |
| `GET /api/v1/mlops/models` | Versiones con su historia de estados, métricas en el oro *dev* (κ, ECE, AURC), temperatura, hash de datos, licencia, el último `promotion_checks` de cada candidato y qué acciones están habilitadas (con el motivo si no) |
| `GET /api/v1/mlops/models/{model_version}/calibration` | Temperatura y diagrama de confiabilidad antes y después de la temperatura (del manifiesto o de los JSON de los experimentos) |
| `GET /api/v1/mlops/runs?kind=&days=30` | `inference_runs_current` (tipo, estado, inicio, fin, duración, reseñas, textos, costo, memoria pico, versiones, hash corto del actor, motivo) |
| `GET /api/v1/mlops/ingestion?days=30` | Corridas de ingesta por `run_id` con banco, modo, inicio, fin, duración, último estado y reseñas extraídas, publicadas y descartadas |
| `GET /api/v1/mlops/eligibility` | `eligibility_counts` por banco y mes |
| `POST /api/v1/mlops/actions/{action}` | `action` en `retrain`, `rescore`, `promote`, `rollback`, `topics_refit`. Cuerpo `{ reason, model_version?, confirm_word? }`. Revisa en el servidor que la acción esté habilitada (409 si no), lanza el Job y devuelve `{ operation, job }` |

## 4. Pantalla (`src/sections/mlops/`)

Pestañas:

1. **Modelo:**
   * una tarjeta por señal con su estado (`StatusPill`), el último valor con IC y el umbral;
   * debajo de cada tarjeta, la serie con su umbral (línea discontinua dorada);
   * la curva de cobertura y riesgo vigente (el componente del paso 5, en modo de solo lectura);
   * las dos series de tópicos con el aviso "contexto, sin umbral: se acumulan para fijar uno con evidencia".
2. **Deriva:**
   * selector de serie;
   * mapa de calor banco × mes con el z (escala divergente) y borde en los meses que superan el umbral;
   * al pulsar una celda, la serie de ese banco con su umbral.
3. **Registro y acciones:**
   * línea de tiempo de versiones (promociones, retiros, *rollbacks*, con quién y motivo);
   * tabla de candidatos con su regla de promoción: diferencias de κ y macro-F1 como puntos con intervalo alrededor de 0 y el veredicto;
   * el diagrama de confiabilidad y la temperatura del candidato;
   * los botones de acción, cada uno con el motivo cuando está deshabilitado ("no hay aviso de reentrenamiento vigente").
4. **Pipeline:**
   * corridas de inferencia de 30 días (tabla, más la duración y el costo del delta por día; la memoria pico contra la línea de 4 GiB);
   * corridas de ingesta;
   * frescura;
   * proporción de no predecibles por motivo y banco.

## 5. Pruebas

* **API:**
  * reglas de habilitación de cada acción (sin `retrain`, con un entrenamiento en curso, candidato sin `promotion_checks`, `worse` sin `FORZAR`, *rollback* a una versión nunca promovida) → 409 o 422;
  * los argumentos de cada Job son exactamente los de la tabla, con el `actor_hash` del principal;
  * nunca se ejecuta un Job fuera de la lista;
  * un analista recibe 403 en las acciones y 200 en la lectura;
  * la duración de la ingesta se deduplica por `audit_event_id`.
* **`ml-inference` y `voc-common`:** `topics-refit` con `--actor-hash` y `--reason` escribe inicio y cierre en `inference_runs` con `topic_refit`.
* **Portal:** cada tarjeta muestra su umbral y su estado; los botones deshabilitados explican por qué; Promover con `worse` pide `FORZAR`; `axe` sin violaciones.

## Terminado cuando

* [x] Cada señal del monitor tiene su gráfica con el umbral vigente y el estado (`ok`, `warning`, `retrain`). (Probado con datos de muestra en la API y en el portal.)
* [ ] En dev, con aprobación del autor: re-ajustar tópicos desde el botón deja su corrida en `inference_runs` con quién y por qué (costo $0). Si el paso 14 de 6.6 ya dejó un candidato, se prueba su promoción o se pospone por decisión del autor. (Pendiente 14 de [EPIC-8](../epic_8.md): necesita la infraestructura aplicada y la aprobación del autor. La prueba de `ml-inference` ya cubre las filas de inicio y cierre con `topic_refit`.)
* [ ] El registro de modelos muestra `robertuito_sentiment_v1` promovido con sus métricas. (La lectura del registro y la calibración desde los experimentos están probadas con datos de muestra y con el JSON real; falta mirarlo contra `model_versions` de dev, pendiente 14 de EPIC-8.)

## Decisiones al implementar

* **La API de lectura es de rol analista y las acciones de administrador**, como dice la tabla; el portal muestra los botones al analista, deshabilitados con "Solo el rol administrador lanza acciones".
* **Las reglas de las acciones viven en la API, no en el portal.** `GET /mlops/models` devuelve por versión (`rescore`, `promote`, `rollback`) y en global (`retrain`, `topics_refit`) si está habilitada y el motivo si no; `POST /mlops/actions/{action}` las revisa de nuevo (409) y la pantalla solo pinta lo que recibe. Las reglas que no estaban en la tabla:
  * **Promover** exige que el `promotion_checks` se haya calculado contra la versión vigente de hoy (`current_version`); si la vigente cambió, pide volver a re-puntuar.
  * **Reentrenar** mira el último periodo de `kappa_monitor` **del modelo vigente**, no el de otras versiones.
  * **Una corrida `running` más vieja que el tiempo máximo de su Job** (4 h el entrenamiento, 3 h el re-scoring, 1 h el re-ajuste) no cuenta como en curso, como en `ml-inference` (`runs.py`).
  * **`FORZAR`:** con veredicto `worse` falta la palabra → 422; con ella se agrega `--force`. El *rollback* nunca lleva `--force`, aunque el cliente mande la palabra.
  * `retrain_trigger` nulo equivale a `manual` y `topic_refit_trigger` nulo a `scheduled`, como dice el contrato (`retrain_mode` y `topic_refit_mode`).
  * **Re-ajuste programado:** la próxima fecha es hoy si el último ajuste es de un trimestre anterior (el Job toca en su próxima corrida) y el primer día del trimestre siguiente si ya hay uno de este.
* **Lista cerrada de Jobs en dos capas.** `jobs.py` solo conoce `voc-ml-training`, `voc-ml-rescoring`, `voc-ml-promote` y `voc-ml-topics-refit`, cada uno con su único subcomando; la API arma los argumentos con el hash del principal y el motivo, y el cuerpo de la petición no tiene dónde meter argumentos ni el Job. La prueba de `jobs.py` fija la misma petición que la de `ml-inference`.
* **Permisos en `infra/`:** la cuenta de la API recibe `roles/run.jobsExecutorWithOverrides` (la misma que usa la ingesta histórica: cambia los argumentos pero no edita el Job) solo sobre esos cuatro Jobs, `roles/storage.objectViewer` condicionado a `ml_artifacts/` (la misma condición del servicio en línea) y la variable `GCS_RAW_DATALAKE_BUCKET`. El paso 1 no los había dejado: solo existían para el servicio en línea.
* **Calibración.** Se lee `training_manifest.json` de `ml_artifacts/sentiment/<versión>/` con `google-cloud-storage` (dependencia nueva de la API). Sin manifiesto, la única versión que se resuelve es la sembrada (`robertuito_sentiment_v1` → `M4_robertuito_s1_ppi` del JSON de calibración, que la imagen copia en `/app/calibration/`) y la respuesta dice de dónde sale (`source = docs`). Cualquier otra versión sin manifiesto da 404 y la pantalla lo explica.
* **La curva vigente la sirve MLOps con el mismo servicio de Administración** (`GET /mlops/coverage-curve`, rol analista): el endpoint de administración es de rol administrador. Acepta `model_version` para mostrar la curva de una candidata ("la curva nueva") antes de promoverla; si la candidata no la tiene, la pantalla lo dice.
* **Frescura.** `GET /mlops/runs` agrega `freshness` (última ingesta completa, último delta exitoso y último monitor, inferido de `kpi_estimates`) y `memory_limit_mib` (4 096, el límite del Job del delta); la tabla de endpoints no los listaba, pero evita dos rutas más.
* **Series de deriva.** La lista de series excluye las de tópicos (no tienen umbral y salen en `topics-context`); `topics-context` trae los tópicos y, junto, las familias (`family_*`) y la marca `u` (`flag_update_share`) de los mismos meses. La ventana es de 24 meses.
* **El mapa de calor** pinta el z; el PSI de la longitud se lleva a la misma escala con su umbral (`psi / umbral × 4`) para no tener dos escalas. El borde dorado marca la alerta que escribió el monitor (`alert`), no una comparación del portal. Cada celda trae el número escrito: el color no es el único canal.
* **Elegir la versión.** La tabla de versiones tiene un botón "Elegir" por versión no vigente; sobre la elegida se ven la regla de promoción, la calibración y la curva, y se arman los botones de *re-scoring*, *promover* y *rollback*. Así el *rollback* se lanza desde la versión retirada.
* **`topics-refit` y `inference_runs`.** `RunKind.TOPIC_REFIT` es nuevo en `voc-common` (y en el contrato). El Job escribe la fila de inicio y la de cierre solo cuando corre (toca o va con `--force`); si no toca, no escribe nada, para no llenar el registro con corridas mensuales vacías. Una corrida forzada con pocos textos cierra `failed`. Cuesta $0 (`cost_usd = 0`), con la memoria pico, y `actor_hash` y `reason` nulos en la corrida programada. `ended_at` nunca es anterior a `started_at`.
* **FMEA:** ningún texto sale por un camino nuevo: el botón lanza Jobs que ya existían y que ya tienen su fila (el entrenamiento y el *re-scoring* mandan texto a Kaggle, y el diálogo lo avisa). No se agregó una fila.

## Avance

* **`voc-common` y `ml-inference` (2026-10-26):** `RunKind.TOPIC_REFIT`; `topics-refit` acepta `--actor-hash` y `--reason` y escribe inicio y cierre en `inference_runs`. Pruebas nuevas: quién y por qué, corrida programada sin actor, cierre `failed` con pocos textos, no escribe si no toca.
* **API (2026-10-26):** `api_backend/jobs.py` y `sections/mlops/` (`router`, `schemas`, `service`, `repository`, `calibration`, `sample`), registrada en `main.py`; `openapi.json` y `schema.d.ts` regenerados. Pruebas nuevas (`test_jobs.py`, `test_mlops.py`, `test_mlops_bigquery.py`): lectura de analista y 403 de lector, reglas de habilitación de cada acción (sin aviso, entrenamiento en curso o muerto, modo automático, candidata sin verificación, verificación contra otra vigente, `worse` sin `FORZAR`, *rollback* a la vigente o a una nunca promovida), argumentos exactos de cada Job con el `actor_hash` del principal, lista cerrada, 502 si el Job no se lanza, y la ingesta deduplicada por `audit_event_id` antes de agrupar.
* **Infraestructura (2026-10-26):** permisos de la cuenta de la API sobre los cuatro Jobs y sobre `ml_artifacts/`, y la variable del bucket; pruebas de Pulumi actualizadas. **No se aplicó** ni se construyó la imagen: queda para el despliegue con la aprobación del autor.
* **Portal (2026-10-26):** `/mlops` con cuatro pestañas en `?tab=` (Modelo, Deriva, Registro y acciones, Pipeline), cada una un trozo perezoso. 15 pruebas nuevas, entre ellas el umbral y el estado de cada tarjeta, los botones deshabilitados con su motivo, *promover* con `worse` que pide `FORZAR`, el *rollback* y `axe` sin violaciones en las pestañas Modelo, Registro y Pipeline. Dos pruebas viejas (`a11y` y `cockpit`) usaban `/mlops` como sección en construcción; ahora usan `/gobernanza`.
* **Revisada en local** (`PORTAL_DATA=fixtures`): se abrieron las pestañas Modelo y Registro; las gráficas se cortaban a la derecha en la rejilla de dos columnas hasta que las tarjetas recibieron `min-w-0`. Las pestañas Deriva y Pipeline solo se probaron con las pruebas del portal, no a ojo.
* **Pendiente:** aplicar la infraestructura, mirar el registro y las señales contra dev y probar el botón de tópicos con la aprobación del autor (pendiente 14 de [EPIC-8](../epic_8.md)). Los huecos conocidos (el monitor sin `inference_runs` y la ingesta sin costo) son los pendientes 8 y 9 de EPIC-8.
