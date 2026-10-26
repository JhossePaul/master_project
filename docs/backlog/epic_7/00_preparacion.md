# Feature 7.0: Preparación y bloqueantes

* **Estado (2026-10-25):** En curso: B1 a B4 resueltos; falta B5 (se aplica la recomendación al llegar a cada paso, con aviso); las verificaciones de la sección 4 están hechas. Revisión hecha en la sesión de planificación contra el código (`2279505`) y BigQuery en dev.
* **Objetivo:** dejar resuelto lo que de verdad detiene el desarrollo y separar lo que no lo detiene. **Cerrar EPIC-6 no es requisito:** los pasos 14 (ciclo de modelo) y 15 de 6.6 y la corrida programada sin intervención no bloquean ningún paso de EPIC-7; lo único que afectan está anotado abajo.

## 1. Lo que ya está y se puede usar

| Insumo | Estado en dev (2026-10-25) | Lo usa |
| :--- | :--- | :--- |
| 28 tablas y 10 vistas del contrato v3 | Aplicadas con Pulumi; `pulumi preview` sin cambios | Todos los pasos |
| Histórico cargado | `review_predictions` 2 654 106 filas; `review_aspects` 703 369; `text_embeddings` 1 826 977; `topic_assignments` 1 079 153; `topic_model_current` = `topics_v1` (97 tópicos, 35 curados) | Cockpit, Explorador |
| Delta diario y monitor semanal | Corrieron en `succeeded`; Schedulers activos (delta 09:30, monitor lunes 10:30, CDMX) | Landing, cockpit, MLOps |
| Casos HITL | 497 en `hitl_items`: 197 `low_confidence` (con su explicación precalculada) y 300 `monitor_sample` sin revisar | HITL de sentimiento |
| KPI con PPI | `kpi_estimates` 19 136 filas (186 meses, banco × mes, `ppi` y `raw`) | Landing, cockpit |
| Deriva y calidad | `drift_metrics` 9 702 filas (0 alertas); `model_quality` 2 filas (`gemini_agreement`, `families_validation`, ambas `ok`) | Alertas, MLOps |
| Políticas | `risk_policy_v1` (cobertura 0.9, `retrain_trigger = manual`, `topic_refit_trigger = scheduled`), `drift_policy` v2 de los 5 bancos | Administración |
| Temas por día | `daily_topic_labels` validada contra los experimentos (99.47 % idéntica) | Cockpit |
| Jobs lanzables con argumentos | `voc-ml-training`, `voc-ml-rescoring`, `voc-ml-promote`, `voc-ml-topics-refit` | MLOps |
| Lógica pura reutilizable | `voc_nlp.hitl` (`threshold_for`, `requires_hitl`), `voc_nlp.ppi` (`gap_stars`, `targets`), `voc_common.text_utils` (`text_key`, `hash_username_pii`) | API |

**Lo que deja pendiente EPIC-6 y a qué afecta:**

* **Paso 14 de 6.6 (primer reentrenamiento):** terminó el 2026-10-26. `robertuito_sentiment_v2` está registrado como candidato, con su *re-scoring* y una fila en `promotion_checks` (`better`); no se ha promovido. La prueba en dev del botón de promover (paso 8) puede usar ese candidato; el desarrollo y sus pruebas usan datos sintéticos.
* **Corrida programada sin intervención:** no afecta; la landing muestra la frescura que haya.

## 2. Bloqueantes

Cada uno dice qué paso detiene. Ninguno detiene el paso 1 en local: la API se construye con el modo local y datos sintéticos (stack, sección 4).

### B1. Acceso de cuentas de `up.edu.mx` y `bbva.com` (detiene el despliegue del paso 1 en dev y la presentación)

El autor confirmó (2026-10-25) que entrarán cuentas de `up.edu.mx` y `bbva.com`. Los dos dominios usan Google Workspace (sus registros MX son de Google), así que tienen identidad de Google y IAP puede autenticarlas. Quedan tres riesgos que **solo se resuelven probando**:

1. **Política de la organización.** El proyecto pertenece a la organización `601552432111`, y la cuenta del autor no puede leer sus políticas (`PERMISSION_DENIED`). Si la organización aplica *Domain restricted sharing* (`iam.allowedPolicyMemberDomains`), Google rechaza dar permisos a correos de otros dominios. Hay que saber quién administra la organización y qué política aplica.
2. **IAP con usuarios externos.** La pantalla de consentimiento de OAuth tiene que ser de tipo externo para aceptar cuentas fuera de la organización.
3. **Controles del Workspace de BBVA o de la UP.** Un administrador de Workspace puede bloquear que sus usuarios inicien sesión en aplicaciones de terceros. Si eso pasa, solo lo puede cambiar ese administrador.

**Prueba de acceso (con aprobación del autor, costo $0, 30 minutos):**

1. Habilitar `iap.googleapis.com` en el proyecto.
2. Desplegar el contenedor de ejemplo de Cloud Run (`us-docker.pkg.dev/cloudrun/container/hello`) como `voc-portal-spike`, con IAP activado directamente en el servicio (`gcloud beta run deploy … --iap`; confirmar el flag en la documentación vigente de IAP para Cloud Run).
3. Dar `roles/iap.httpsResourceAccessor` sobre el servicio a la cuenta del autor, a una de `up.edu.mx` y a una de `bbva.com`.
4. Cada persona abre la URL. Se anota qué pasó con cada una (entra, error de permiso, bloqueo de su Workspace).
5. Borrar `voc-portal-spike`.

**Si una cuenta no entra:**

* por la política de la organización, el autor pide la excepción a quien administre la organización o mueve el proyecto;
* por IAP directo en Cloud Run, se repite con un balanceador HTTPS externo y IAP en el *backend service* (requiere un dominio: pregunta `S-04` del cuestionario);
* por el Workspace de BBVA, esas personas entran con una cuenta Gmail, y se decide si se acepta (pregunta `S-03`).

**Terminado cuando:** la tabla de resultados está en "Avance" y queda elegida la ruta técnica de IAP (directo en Cloud Run o con balanceador).

### B2. Ruta técnica de IAP en Pulumi (detiene el despliegue del paso 1)

`infra/` fija `pulumi-gcp>=7.18,<8` (hoy 7.38), y esa versión no tiene `iap_enabled` en `cloudrunv2.Service`. Con IAP directo en Cloud Run hay que subir a `pulumi-gcp` 8.x. Es un cambio de versión mayor: se hace en el paso 1, con `pulumi preview` sin cambios inesperados en los 120 recursos actuales y las pruebas de `infra/` en verde. Si B1 lleva al balanceador, no hace falta subir de versión, pero se agregan la IP global, el certificado, el *backend service*, el *URL map* y el NEG *serverless*.

### B3. Personas y roles (detiene el despliegue del paso 1; en local no)

El autor entrega la lista de correos con sus roles (lector, analista, revisor de sentimiento o de aspectos, administrador). Va cifrada en la configuración de Pulumi (`portal_users`), nunca en claro en git. Para la presentación basta con el autor y unas pocas cuentas.

### B4. Preguntas de diseño (detienen el paso 2)

Las del [cuestionario](design_questions.md) marcadas **"antes de 2"**. Las demás se pueden responder al llegar a su paso; mientras tanto se usa la recomendación.

### B5. Decisiones de contrato (cada una detiene un paso, no el inicio)

| # | Hueco | Recomendación | Detiene |
| :-: | :--- | :--- | :--- |
| 1 | **Revisión "no evaluable" de sentimiento.** `HitlReview` exige `validated_label` en las revisiones de sentimiento, pero el prototipo de anotación tiene la opción `NO_EVALUABLE` y la marca `no_evaluable` existe en `ReviewFlag` | Permitir `validated_label` nulo solo si `flags` contiene `no_evaluable`, con `outcome = corrected`. El reentrenamiento ya excluye `no_evaluable`; el κ del monitor la deja fuera. Cambia `voc_common.hitl_v3` y sus pruebas, y se revisan `ml_inference.monitor.quality` y `ml_inference.training` | Paso 4 |
| 2 | **Explicación con dirección.** `occlusion_v1` mide solo la caída de la clase predicha y sin la temperatura; el Explorador quiere ver qué palabras empujan hacia `NEG` y cuáles hacia `POS` | Método nuevo `occlusion_v2`: por palabra, el cambio de `p_neg`, `p_neu` y `p_pos` calibradas al quitarla (`attributions`: `[{start, end, d_neg, d_neu, d_pos}]`). El delta pasa a precalcular `occlusion_v2`; las filas `occlusion_v1` se quedan como historia | Paso 6 |
| 3 | **Quién y por qué del re-ajuste de tópicos.** `topics-refit` no acepta `--actor-hash` ni `--reason` y no escribe en `inference_runs` | Sumar `RunKind.TOPIC_REFIT`, los dos argumentos y las filas de inicio y cierre en `inference_runs`, como en `train` | Paso 8 |
| 4 | **Regla del hash del actor.** La línea de comandos recibe `--actor-hash` ya calculado y no hay una función que lo calcule | `actor_hash(email, salt) = hash_username_pii(email, salt)`, es decir `sha256("<sal>:<correo en minúsculas>")` con `USER_HASH_SALT`, en `voc_common.text_utils`, más `tools/actor_hash.py` para calcularlo a mano. Las filas que ya sembró el autor conservan su hash; si no coincide con la regla, se anota | Paso 1 |
| 5 | **Cola de aspectos.** Ningún Job crea casos `task = aspects` | La API los crea desde administración: una muestra aleatoria de negativas con `reason = manual`, siempre a ciegas | Paso 9 |

## 3. Huecos de EPIC-6 que EPIC-7 cierra (no bloquean el inicio)

| Hueco | Se cierra en |
| :--- | :--- |
| `services/api-backend/` y `web/portal/` existen pero todos sus archivos están vacíos; `api-backend` está excluido del workspace uv | Pasos 1 y 2 |
| `voc-api-backend` corre con `voc-sa-ml-backend` (escritura en todo el dataset), sin IAP, con *ingress* abierto | Paso 1: cuenta `voc-sa-portal-api`, permisos por tabla, IAP |
| CI, CD, `cloudbuild.yaml`, `.dockerignore` y `.gcloudignore` no conocen la API ni el portal (`.gcloudignore` excluye `web/`); `tools/deploy_images.py` no fija la imagen de la API | Paso 1 |
| `point_for`, `propose_risk_policy` y `drift_rates.rates` son puras pero viven en `ml-inference`, que importa BigQuery, Gemini y pyarrow | Pasos 5 y 8: se mueven a `voc-nlp` sin extras y `ml-inference` las re-exporta |
| El sanitizador local importa Apache Beam y no detecta nombres | Paso 4: comentarios y notas pasan por Cloud DLP |
| Nadie calcula explicaciones bajo pedido ni embebe consultas (PyTorch no cabe en la API) | Paso 6: servicio privado `voc-ml-online` |
| `voc-ml-promote` y `voc-ml-topics-refit` no tienen permiso de ejecución para ninguna cuenta de la API | Paso 1 (permisos) y paso 8 (uso) |
| `ingestion_runs_log_v2` no tiene duración ni costo | Paso 8: duración derivada de `updated_at`; costo "sin dato" |
| Nadie asigna casos ni mide el acuerdo entre personas | Paso 4: el caso se toma al abrirlo (bloqueo de 15 minutos); la doble revisión exige otro revisor |
| `gold_versions` no tiene productor | Paso 5 |
| `kpi_estimates` es banco × mes; no hay series diarias ni agregado de los cinco bancos | Paso 3: la API las calcula sobre `review_predictions_current` |
| No hay índice vectorial y los vectores no están normalizados | Paso 6: `VECTOR_SEARCH` con distancia coseno y la partición por mes; el índice solo si la medición lo pide |
| Las métricas de `docs/analytics/` no traen series diarias ni mensuales por banco, y sus PNG usan los nombres reales de los bancos | Paso 12: exportación de agregados para la tesis |
| `README.md` raíz (líneas 50-52) presenta la API y el portal como si existieran; `docs/operations/deployment.md` dice que la API entra "cuando tenga Dockerfile" | Paso 1 |

## 4. Verificaciones de la sesión (antes del paso 1)

* [x] `uv sync --all-packages` y las puertas de calidad actuales en verde (línea base).
* [x] Node 24 LTS disponible para CI y la imagen; en local, Node 26.12 sirve (`node --version`).
* [x] `npm create vite@latest` responde (hay acceso al registro de npm).
* [x] `bq query --dry_run` de `SELECT fecha, bank_id, sentiment, estrellas FROM bbva_voc_tds.review_predictions_current WHERE fecha >= '2026-07-01'`: anotar los bytes. La vista elige la última fila por reseña con una ventana, y eso puede impedir que el filtro por fecha pode particiones. Con más de 1 GB por consulta, el paso 3 materializa los agregados diarios.

## Terminado cuando

* [x] B1 y B2 tienen su resultado anotado y la ruta de IAP elegida (2026-10-25: IAP directo en Cloud Run con cliente de OAuth External).
* [x] B3: el autor decidió desplegar solo con su cuenta al principio (2026-10-25); el paso 1 la pone en `portal_users` cifrada.
* [x] B4: las preguntas "antes de 2" tienen respuesta (2026-10-25).
* [ ] B5 (la #4 está aprobada, 2026-10-25): cada decisión tiene la respuesta del autor (o se aplica la recomendación al llegar a su paso, con aviso).
* [x] Las verificaciones de la sección 4 están marcadas (2026-10-25, resultados en "Avance").

## Avance

### B1. Prueba de acceso (2026-10-25)

* **Política de la organización:** no bloquea. La política efectiva de `iam.allowedPolicyMemberDomains` en el proyecto es `allValues: ALLOW` y `iam.managed.allowedPolicyMembers` no se aplica; IAM aceptó dar `roles/iap.httpsResourceAccessor` a correos de Gmail, `up.edu.mx` y `bbva.com`.
* **IAP directo en Cloud Run:** `gcloud run deploy … --no-allow-unauthenticated --iap` es GA (gcloud 590). Con gcloud hay que dar `roles/run.invoker` al agente de IAP (`service-<número>@gcp-sa-iap.iam.gserviceaccount.com`); la consola lo hace sola.
* **Cliente de OAuth:** el que gestiona Google solo admite identidades de la organización; con él, ni la cuenta del autor (Gmail) entró aunque tenía el permiso. El autor creó en la consola un cliente propio con audiencia **External** y lo aplicó a nivel de proyecto con `gcloud iap settings set`. El *client secret* no está en el repo; en el paso 1, Pulumi solo referencia la configuración de IAP del proyecto, no la crea (los clientes de OAuth no se crean por API).

| Cuenta | Con el cliente de Google | Con el cliente propio (External) |
| :--- | :--- | :--- |
| Gmail del autor | *You don't have access* | Entra |
| Segunda cuenta Gmail | *You don't have access* (aún sin permiso) | Entra |
| `up.edu.mx` | *Internal server error 604* | Entra |
| `bbva.com` | — | **No entra:** bloqueo del Workspace de BBVA |

* **Ruta elegida:** IAP directo en Cloud Run, sin balanceador ni dominio (`S-04` resuelta). Implica subir `pulumi-gcp` a 8.x en el paso 1 (B2).
* **BBVA:** según `S-03`, se pide la excepción al administrador del Workspace de BBVA y, mientras tanto, esas personas entran con una cuenta Gmail.
* `voc-portal-spike` se borró al terminar. `iap.googleapis.com` queda habilitada.

### Verificaciones de la sección 4 (2026-10-25)

* **Línea base:** `uv sync --all-packages --locked`, Ruff (lint y formato), Pyrefly (0 errores) y Bandit sin hallazgos; las siete suites de CI en verde con su umbral de cobertura (voc-common 344 pruebas, 99.9 %; infra 128, 100 %; ingestion-worker 196, 96 %; sanitization-pipeline 130, 100 %; tools 50, 97 %; voc-nlp 139, 99 %; ml-inference 214, 98 %).
* **Node:** 26.12.1 en local; Node 24.22.1 se obtiene con `npx node@24`. npm 11.20 y el registro responden (`vite` 8.3.5).
* **BigQuery:** la consulta de `review_predictions_current` desde 2026-07-01 procesa como máximo 266 768 144 bytes (≈ 0.27 GB), bajo el límite de 1 GB. El paso 3 puede consultar la vista sin materializar los agregados diarios, y se revisa si crece el rango.

### B5.4. Hash del actor sembrado (2026-10-25)

* **Aprobada** por el autor la regla `actor_hash = hash_username_pii(correo, USER_HASH_SALT)`.
* **Corroborado contra BigQuery:** `inference_runs.actor_hash` y `risk_policy.set_by_hash` tienen un único valor, `ab498e0e…4611`, y es exactamente el SHA-256 del correo del autor en minúsculas **sin sal** (`sha256("traslasnovenas@gmail.com")`). No coincide con la regla aprobada, que antepone la sal.
* **Migrado (2026-10-25, con aprobación del autor):** se hizo una excepción puntual a la regla de solo agregar. Se reemplazó el hash sin sal por el hash con sal en las 58 filas que lo llevaban: `curation_topics` 35, `drift_policy` 10, `inference_runs` 7, `drift_policy_template` 2, `guidelines` 2, `model_versions` 1 y `risk_policy` 1. Los totales de cada tabla no cambiaron y no queda ninguna fila con el hash viejo. El origen del hash era solo el argumento `--actor-hash` de `seed`, `load-local`, `train` y `rescore`: no está en los JSON de `docs/analytics/`, en los cuerpos de los Schedulers ni en `ml_artifacts/`. El *time travel* del dataset (168 h) permite revertir hasta el 2026-11-01.
* **Pendiente de seguir la regla:** los próximos `seed`, `load-local`, `train`, `rescore` y `promote` deben recibir el hash con sal (`tools/actor_hash.py`, paso 1), no el SHA-256 del correo.
