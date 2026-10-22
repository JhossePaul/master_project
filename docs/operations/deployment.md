# Activación del primer despliegue

EPIC-2 declara recursos y dispone de aceptación local con mocks. No hay datos
anteriores que convertir. EPIC-3 y EPIC-4 ya tienen sus consumidores e imágenes
(validados localmente; sin integración real con GCP).
El contrato de watermark es único y se inicia vacío cuando falta el objeto;
Pulumi no crea checkpoints, planes, manifiestos o ejecuciones de backfill.

## Verificación local

Desde la raíz del repositorio, usar Python 3.11 como CI:

```bash
uv sync --all-packages --locked --python 3.11
uv run pytest packages/voc-common/tests --cov=packages/voc-common/src --cov-fail-under=85
uv run pytest infra/tests --cov=infra/modules --cov-fail-under=80
```

La suite se valida con Python 3.11.14. Con la selección automática de Python
3.14 se observó un fallo de inicialización del event loop de Pulumi Mocks;
por eso el comando fija el intérprete usado por CI.

Además de esas dos suites, CI ejecuta las de cada servicio (cobertura ≥ 85 %):

```bash
uv run pytest services/ingestion-worker/tests --cov=ingestion_worker --cov-fail-under=85
uv run pytest services/sanitization-pipeline/tests --cov=sanitization_pipeline --cov-fail-under=85
```

CI ejecuta además Ruff, Pyrefly y Bandit. La matriz integrada de `infra`
combina dev/prod, Free Tier/normal, CMEK on/off y las dos fases de despliegue.
Comprueba DAG, tablas, jobs, Scheduler, lifecycle, grants, exports y Settings
cargado desde las variables de los contenedores. Los secretos simulados solo se
desempaquetan dentro de tests; no se imprimen sus valores en informes.

Los mocks no certifican permisos efectivos, cuotas, disponibilidad de imágenes,
comportamiento del proveedor ni recuperación ante cambios del origen.

## Protección de `main`

`main` solo recibe cambios mediante PR. El workflow `Quality gates` corre en
PRs hacia `main` y en push a `main`; su job `quality` es el check obligatorio.
La protección no vive en el YAML: es un ruleset del repositorio que debe crear
un administrador. En repos privados requiere un plan de GitHub con rulesets.

Con `gh` autenticado (`gh auth login`), desde la raíz del repositorio:

```bash
gh api --method POST repos/JhossePaul/master_project/rulesets --input - <<'EOF'
{
  "name": "main-solo-por-pr",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 0,
      "dismiss_stale_reviews_on_push": true,
      "require_code_owner_review": false,
      "require_last_push_approval": false,
      "required_review_thread_resolution": true
    }},
    {"type": "required_status_checks", "parameters": {
      "strict_required_status_checks_policy": true,
      "required_status_checks": [{"context": "quality"}]
    }}
  ]
}
EOF
```

Las aprobaciones requeridas quedan en 0 porque GitHub no permite aprobar el
propio PR; subirlas cuando haya otro revisor. El check `quality` debe haber
corrido al menos una vez para aparecer como seleccionable en la interfaz.
Equivalente en la UI: Settings → Rules → Rulesets → New branch ruleset.

## Backend de estado

El estado de Pulumi vive en un bucket GCS dedicado, creado **fuera** del stack
(si el stack lo gestionara, un `pulumi destroy` borraría su propio estado).
`pulumi login --local` (`~/.pulumi` de un solo equipo, sin respaldo ni bloqueo
compartido) ya no se usa.

| Stack | Backend | Secretos |
| --- | --- | --- |
| `dev` | `gs://pulumi-state-voc-project-7bafd424-a385-4c05-b5b` | Cloud KMS: `gcpkms://projects/project-7bafd424-a385-4c05-b5b/locations/global/keyRings/pulumi-secrets/cryptoKeys/dev` (`secretsprovider` y `encryptedkey` en `Pulumi.dev.yaml`) |
| `prod` | pendiente: mismo patrón, bucket en el proyecto de prod | se recomienda `gcpkms://` |

Bucket de `dev` (2026-10-15): `us-central1`, versionado activo, acceso uniforme
a nivel de bucket y soft delete de 7 días. El stack `dev` se creó con
`pulumi stack init dev` en ese backend. La **fase 1 se aplicó el 2026-10-15**
(46 recursos; sin Cloud Run ni Scheduler). El stack usa Cloud KMS y no una
passphrase: una passphrase vacía con `Pulumi.dev.yaml` versionado en un
repositorio público dejaría cualquier secreto descifrable por cualquiera.

Para operar el stack:

```bash
gcloud auth application-default login       # credenciales para backend y proveedor
pulumi login gs://pulumi-state-voc-project-7bafd424-a385-4c05-b5b
cd infra && pulumi stack select dev
```

Con el proveedor KMS no hace falta `PULUMI_CONFIG_PASSPHRASE`; quien opere el
stack necesita `roles/cloudkms.cryptoKeyEncrypterDecrypter` sobre la llave.

Quien opere Pulumi necesita `roles/storage.objectAdmin` sobre el bucket; nadie
necesita acceso público. Endurecimiento opcional del bucket existente:

```bash
export STATE_BUCKET=gs://pulumi-state-voc-project-7bafd424-a385-4c05-b5b
gcloud storage buckets update "$STATE_BUCKET" --public-access-prevention
# Conservar solo las 10 versiones no actuales más recientes del estado.
cat > /tmp/state-lifecycle.json <<'EOF'
{"rule": [{"action": {"type": "Delete"},
           "condition": {"isLive": false, "numNewerVersions": 10}}]}
EOF
gcloud storage buckets update "$STATE_BUCKET" \
  --lifecycle-file=/tmp/state-lifecycle.json
```

### Crear el backend de otro ambiente

Mismo patrón para `prod` (o para recrear el de `dev`):

```bash
export STATE_PROJECT=<proyecto-gcp>
export STATE_BUCKET=gs://pulumi-state-voc-${STATE_PROJECT}
gcloud storage buckets create "$STATE_BUCKET" --project="$STATE_PROJECT" \
  --location=us-central1 --uniform-bucket-level-access \
  --public-access-prevention
gcloud storage buckets update "$STATE_BUCKET" --versioning
pulumi login "$STATE_BUCKET"
cd infra && pulumi stack init prod          # opcional: --secrets-provider (abajo)
```

### Migrar un stack con estado entre backends

Para `dev` bastó `pulumi login` + `pulumi stack init dev` porque el stack local
no tenía recursos. Si un stack ya tiene estado (p. ej. tras `pulumi up`),
exportarlo e importarlo; el stack de origen no se borra hasta comprobar el
destino:

```bash
cd infra
pulumi login <backend-origen>               # p. ej. --local
pulumi stack select dev
pulumi stack export --show-secrets --file /tmp/dev.state.json

pulumi login "$STATE_BUCKET"
pulumi stack init dev                       # mismo nombre de stack
pulumi stack import --file /tmp/dev.state.json
pulumi stack export | jq '.deployment.resources | length'
pulumi preview --stack dev --non-interactive  # no debe planear cambios nuevos

rm /tmp/dev.state.json                      # contiene secretos en claro
```

`stack init` puede reescribir `encryptionsalt` (o `secretsprovider`) en
`Pulumi.<stack>.yaml`; los valores de configuración se conservan. Si había
secretos cifrados con otra passphrase, volver a fijarlos con
`pulumi config set --secret`.

### Secrets provider con Cloud KMS (opcional)

Con `gcpkms://` el cifrado de secretos depende de IAM y no de una passphrase
compartida (`PULUMI_CONFIG_PASSPHRASE`). La llave es de plataforma y se crea
fuera del stack, igual que el bucket; es independiente de `enable_cmek`.

```bash
gcloud kms keyrings create pulumi-secrets --location=global \
  --project="$STATE_PROJECT"
gcloud kms keys create dev --keyring=pulumi-secrets --location=global \
  --purpose=encryption --project="$STATE_PROJECT"
KMS_KEY="gcpkms://projects/${STATE_PROJECT}/locations/global/keyRings/pulumi-secrets/cryptoKeys/dev"

# Stack nuevo:
pulumi stack init dev --secrets-provider="$KMS_KEY"
# Stack existente (re-cifra secretos de config y estado):
pulumi stack change-secrets-provider "$KMS_KEY"
```

Quien opere Pulumi necesita `roles/cloudkms.cryptoKeyEncrypterDecrypter` sobre
esa llave.

## Preparar stack y preview

1. Autenticarse con el backend GCS del ambiente (ver «Backend de estado»); no
   crear un backend alternativo solo para que pase el preview.
2. Desde `infra/`, seleccionar el stack `dev` (los secretos se descifran con
   la llave KMS; hace falta el ADC del paso anterior).
3. Revisar `Pulumi.dev.yaml`: proyecto/región reales, fase
   (`deploy_workloads`), imágenes por digest, perfiles HTTP/histórico, modo de
   operación y prefijos. Configurar los secretos con `pulumi config set
   --secret`; nunca incluir valores reales en archivos o logs.
4. Proporcionar credenciales GCP válidas (`gcloud auth application-default
   login`) y confirmar proyecto y permisos del ambiente elegido.
5. Ejecutar `pulumi preview --stack dev --non-interactive` y revisar el plan.

**Proyecto de cuota (credenciales de usuario).** Con ADC de usuario, el
proveedor factura cada llamada al proyecto del cliente OAuth de `gcloud`, y
APIs como DLP responden 403 «requires a quota project» (`consumer:
projects/764086051850`). Repetir `pulumi up` no lo arregla. El stack fija:

```bash
pulumi config set --stack dev gcp:userProjectOverride true
pulumi config set --stack dev gcp:billingProject <proyecto-gcp>
```

En cambio, un 403 «API no habilitada» con el proyecto propio como `consumer`
sí es propagación de una API recién habilitada: esperar unos minutos y repetir
`pulumi up` (es idempotente).

El entorno virtual de Pulumi es `../.venv` (`Pulumi.yaml`); sincronizarlo con
`uv sync --all-packages --locked --python 3.11` antes del preview.

## Despliegue por fases

`bbva-voc-infra:deploy_workloads` separa la base de las cargas de trabajo:

| Fase | `deploy_workloads` | Crea |
| --- | --- | --- |
| 1 (por defecto) | `false` | APIs, Artifact Registry `voc-containers-repo`, cuentas de servicio e IAM, bucket datalake, Pub/Sub, BigQuery, DLP |
| 2 | `true` | Además: Cloud Run (`voc-ingestion-worker`, `voc-sanitization-job`, `voc-ingestion-history-job`, `voc-api-backend` si hay imagen), invokers y Cloud Scheduler |

La fase 1 resuelve el huevo y la gallina: Cloud Run no puede crearse sin una
imagen existente, y el registro donde se publica la imagen lo crea este mismo
stack. En fase 2 las imágenes son obligatorias y deben ir fijadas por digest
(`<registry>/<servicio>:<sha>@sha256:<64 hex>`); un tag mutable como `:latest`
se rechaza porque no cambia el plan de Pulumi y no dispara un redeploy.
`api_backend_image` es opcional: sin ella no se crea `voc-api-backend`.
`historical_job_image` sigue siendo opcional y por defecto usa la del worker.

```bash
cd infra
# Fase 1: base sin cargas (preview esperado: cero recursos cloudrunv2/cloudscheduler).
pulumi config set --stack dev bbva-voc-infra:deploy_workloads false
pulumi preview --stack dev --non-interactive
pulumi up --stack dev                       # cuando se autorice el despliegue

# Fase 2: tras publicar imágenes con Cloud Build (ver sección siguiente).
pulumi config set --stack dev bbva-voc-infra:ingestion_worker_image '<ref@sha256:...>'
pulumi config set --stack dev bbva-voc-infra:sanitization_job_image '<ref@sha256:...>'
pulumi config set --stack dev bbva-voc-infra:deploy_workloads true
pulumi preview --stack dev --non-interactive
```

En fase 1 se exportan `deploy_workloads=false`, `artifact_registry_url` y
`scheduler_job_ids=[]`; los outputs de URIs/jobs Cloud Run solo existen en
fase 2. Volver a `false` tras la fase 2 elimina las cargas en el siguiente
`pulumi up`.

## Imágenes con Cloud Build

Las imágenes no se construyen con Pulumi (`pulumi_docker` construiría arm64 en
una Mac). El flujo es GitHub → Cloud Build → Artifact Registry:

- [`cloudbuild.yaml`](../../cloudbuild.yaml) construye `services/<_SERVICE>/Dockerfile`
  con contexto en la raíz del workspace uv, `--platform=linux/amd64`, y publica
  `<region>-docker.pkg.dev/<proyecto>/voc-containers-repo/<servicio>:<_TAG>`.
  Rechaza `_TAG` que no sea un SHA de 40 caracteres y Dockerfiles vacíos.
- [`.github/workflows/cd-cloud-build.yaml`](../../.github/workflows/cd-cloud-build.yaml)
  lo invoca por servicio al hacer merge a `main` (cambios en `services/`,
  `packages/`, lock o pipeline) o con `workflow_dispatch`, siempre desde `main`.
  No tiene disparador `pull_request`, así que las credenciales nunca llegan a
  código no revisado. Omite servicios con Dockerfile vacío: construye
  `ingestion-worker` (feature 3.5) y `sanitization-pipeline` (feature 4.4);
  `api-backend` entra cuando tenga Dockerfile. `develop` no publica imágenes:
  se publican al integrar en `main` por PR.
- Solo se sube a Cloud Build lo que permite [`.gcloudignore`](../../.gcloudignore)
  (nunca `.env` ni `evidence/`), y el contexto Docker lo restringe
  [`.dockerignore`](../../.dockerignore); el build usa BuildKit
  (`DOCKER_BUILDKIT=1`) por los montajes de caché del Dockerfile.
- El repositorio tiene tags inmutables: un re-run del mismo commit reutiliza la
  imagen publicada. El resumen del job muestra el digest y el comando
  `pulumi config set` para la fase 2.

Uso manual equivalente desde la raíz del repo (requiere un commit en `main`):

```bash
gcloud builds submit . --project="$PROJECT_ID" --region=us-central1 \
  --config=cloudbuild.yaml \
  --substitutions=_SERVICE=ingestion-worker,_TAG="$(git rev-parse HEAD)"
gcloud artifacts docker images describe \
  "us-central1-docker.pkg.dev/$PROJECT_ID/voc-containers-repo/ingestion-worker:$(git rev-parse HEAD)" \
  --format='value(image_summary.digest)'
```

### Identidad de CI (una vez, fuera del stack)

El workflow se autentica con Workload Identity Federation, sin llaves JSON. Como
el backend de estado, esta identidad es de plataforma y no la gestiona el stack
(evita que el despliegue dependa de sí mismo). Requiere la fase 1 aplicada
(APIs y Artifact Registry).

```bash
export PROJECT_ID=<proyecto-gcp> REPO=JhossePaul/master_project
export PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
export SA=voc-sa-cloudbuild@${PROJECT_ID}.iam.gserviceaccount.com

gcloud iam service-accounts create voc-sa-cloudbuild --project="$PROJECT_ID"
for role in roles/cloudbuild.builds.editor roles/logging.logWriter \
    roles/storage.admin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA" --role="$role" --condition=None
done
gcloud artifacts repositories add-iam-policy-binding voc-containers-repo \
  --project="$PROJECT_ID" --location=us-central1 \
  --member="serviceAccount:$SA" --role=roles/artifactregistry.writer
# La misma SA ejecuta el build (--service-account).
gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --member="serviceAccount:$SA" --role=roles/iam.serviceAccountUser

gcloud iam workload-identity-pools create github --location=global \
  --project="$PROJECT_ID"
gcloud iam workload-identity-pools providers create-oidc github-main \
  --project="$PROJECT_ID" --location=global --workload-identity-pool=github \
  --issuer-uri=https://token.actions.githubusercontent.com \
  --attribute-mapping=google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref \
  --attribute-condition="assertion.repository=='${REPO}' && assertion.ref=='refs/heads/main'"
gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/${REPO}"
```

`roles/storage.admin` cubre el bucket de staging `<proyecto>_cloudbuild` que
`gcloud builds submit` crea en el primer uso; tras crearlo puede reducirse a
`roles/storage.objectAdmin` sobre ese bucket. La condición del proveedor limita
los tokens a `main` del repositorio.

En GitHub, crear el environment `dev` (con reglas de protección si se desea) y
estas variables (no son secretos):

| Variable | Valor |
| --- | --- |
| `GCP_PROJECT_ID` | proyecto GCP de dev |
| `GCP_REGION` | `us-central1` (opcional) |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `projects/<número>/locations/global/workloadIdentityPools/github/providers/github-main` |
| `GCP_CLOUD_BUILD_SA` | `voc-sa-cloudbuild@<proyecto>.iam.gserviceaccount.com` |

## Revisión del plan

Revisar nombre/location del bucket, lifecycle solo para crudos/temporales,
protección de borrado fuera de dev, cuatro tablas y, en fase 2, los Jobs Cloud
Run. Verificar que Scheduler tenga solo dos crons en Free Tier o seis en modo
normal, sin cron histórico; IAM debe mantener permisos por recurso y ninguna
invocación pública. Cualquier reemplazo/borrado inesperado requiere entender su
causa antes de aplicar. No activar CMEK, Vertex u otros servicios sin revisar sus
recursos condicionales, permisos y cuotas. El preview no ejecuta el extractor.

## Qué configura cada archivo

El despliegue **no usa `.env`**. Cada pieza lee su configuración de un lugar
distinto:

| Origen | Para qué sirve | En Cloud Run |
| --- | --- | --- |
| `infra/Pulumi.dev.yaml` y secretos del stack (`pulumi config set --secret`) | Proyecto, fase, imágenes, perfiles de ejecución y la sal del hash | Sí: Pulumi inyecta las variables de los contenedores |
| Variables del environment `dev` de GitHub | Identidad de CI para publicar imágenes (ver «Identidad de CI») | No |
| `gcloud auth application-default login` y `PULUMI_CONFIG_PASSPHRASE` | Credenciales de quien opera Pulumi | No |
| `.env` (ignorado por git) | Ejecutar y depurar servicios **en local** | No |

Hallazgos de la revisión del `.env` actual (2026-10-15), que no bloquean el
despliegue pero conviene corregir:

* `GCS_RAW_DATALAKE_BUCKET` apunta a `voc-datalake-bbva-voc-analyzer-dev`, pero
  el bucket que crea Pulumi es `voc-datalake-<proyecto>` (en `dev`:
  `voc-datalake-project-7bafd424-a385-4c05-b5b`). Cualquier ejecución local
  contra GCP usaría un bucket inexistente.
* Conserva `PULUMI_CONFIG_PASSPHRASE` (vacía), que ya no se usa con el proveedor
  KMS; eliminarla del `.env` para no confundir.
* `DLP_*_TEMPLATE_ID` vacíos es correcto: el modo por defecto es regex local y
  no los necesita. Solo hacen falta con `--use-cloud-dlp-api`.
* Le faltan variables de recorrido y recuperación que sí están en
  `.env.example` (`INGESTION_MAX_PAGES`, `INGESTION_MAX_RECOVERY_REQUESTS`…);
  `Settings` usa sus valores por defecto.

## Antes de la fase 2: sal del hash de usuarios

Sin `user_hash_salt`, fuera de producción Pulumi usa `DEV_USER_HASH_SALT`, una
constante pública del repositorio, y los `usuario_hash` del TDS serían
reproducibles. **Fijar una sal secreta antes de escribir datos**, porque
cambiarla después deja hashes inconsistentes entre sí. En `dev` ya está fijada
(2026-10-15, cifrada con KMS). Para otro stack:

```bash
cd infra
pulumi config set --secret --stack dev bbva-voc-infra:user_hash_salt "$(openssl rand -hex 32)"
```

Cifrada en el repositorio, la sal llega a Cloud Run como variable de entorno en
claro, no desde Secret Manager: quien pueda leer el servicio la ve (riesgo
residual F-04 de la [Matriz Ethical FMEA](../governance/ethical_fmea_matrix.md)).

## Runbook del primer despliegue (alimentar el TDS)

Prerrequisitos de operador: `gcloud` y `pulumi` autenticados (ver «Backend de
estado»), `gh` autenticado y el entorno `.venv` sincronizado.

1. **Fase 1.** `pulumi preview` y `pulumi up --stack dev` con
   `deploy_workloads: false` y la sal ya configurada. Revisar el plan según
   «Revisión del plan».
2. **Identidad de CI.** Ejecutar el bloque de «Identidad de CI» y crear las
   variables del environment `dev`:

   ```bash
   gh api -X PUT repos/JhossePaul/master_project/environments/dev
   gh variable set GCP_PROJECT_ID --env dev --repo JhossePaul/master_project --body "$PROJECT_ID"
   gh variable set GCP_REGION --env dev --repo JhossePaul/master_project --body us-central1
   gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER --env dev --repo JhossePaul/master_project \
     --body "projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/github-main"
   gh variable set GCP_CLOUD_BUILD_SA --env dev --repo JhossePaul/master_project --body "$SA"
   ```

3. **Imágenes.** `develop` está por delante de `main`; abrir el PR y esperar
   el check `quality`. Al integrar en `main`, el workflow publica
   `ingestion-worker` y `sanitization-pipeline`:

   ```bash
   gh pr create --base main --head develop --title "Releases EPIC-1 to EPIC-4"
   ```

4. **Fase 2.** Con los digests del resumen del job:

   ```bash
   cd infra
   pulumi config set --stack dev bbva-voc-infra:ingestion_worker_image '<ref@sha256:...>'
   pulumi config set --stack dev bbva-voc-infra:sanitization_job_image '<ref@sha256:...>'
   pulumi config set --stack dev bbva-voc-infra:deploy_workloads true
   pulumi preview --stack dev --non-interactive
   pulumi up --stack dev
   ```

5. **Activar la ingesta v2.** Es requisito de cualquier corrida: sin ella el
   servicio y el Job rechazan toda solicitud (`require_ingestion_v2`), incluido
   el cron. La verificación de integración es la primera corrida del paso 6, que
   conviene vigilar:

   ```bash
   pulumi config set --stack dev bbva-voc-infra:ingestion_v2_enabled true
   pulumi up --stack dev
   ```

6. **Primera corrida manual** (no esperar al cron de las 08:00 y 08:30,
   `America/Mexico_City`):

   ```bash
   gcloud scheduler jobs run voc-ingest-daily-sequential-all --location us-central1
   # Cuando termine la ingesta (revisar logs del servicio):
   gcloud scheduler jobs run voc-trigger-sanitization-daily --location us-central1
   ```

7. **Verificar**, en este orden:

   ```bash
   gcloud logging read 'resource.type="cloud_run_revision"' --limit=50 --freshness=1h
   bq query --use_legacy_sql=false \
     'SELECT bank_id, COUNT(*) AS n, MIN(fecha) AS desde, MAX(fecha) AS hasta
      FROM `bbva_voc_tds.sanitized_reviews_tds` GROUP BY bank_id'
   bq query --use_legacy_sql=false \
     'SELECT COUNT(*) AS con_respuesta FROM `bbva_voc_tds.sanitized_reviews_tds`
      WHERE texto_respuesta_sanitizado IS NOT NULL OR titulo IS NOT NULL'  # debe ser 0
   ```

   Comprobar también la auditoría en `ingestion_runs_log_v2`, que el
   `ack` de Pub/Sub ocurre tras el `MERGE` (mensajes pendientes en
   `voc-raw-reviews-sub` → 0) y que el crudo expira a los 7 días.

8. **Backfill histórico** (después del paso 7, nunca antes). Se lanza por
   solicitud a la API (requiere identidad: si responde 403, otorgar
   `roles/run.invoker` al operador sobre el servicio):

   ```bash
   URL=$(pulumi stack output ingestion_worker_uri --stack dev)
   curl -X POST "$URL/api/v1/ingest" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "Content-Type: application/json" \
     -d '{"bank_id": "BBVA", "mode": "BACKFILL"}'
   ```

   La API persiste el plan y lanza `voc-ingestion-history-job`; cada
   ejecución continúa el plan y se detiene en su presupuesto (1000
   solicitudes, 200 MB o 3480 s). Hay que relanzar hasta completarlo.

### Corregir el ID de aplicación de un banco

El estado de cada banco guarda el `app_id` con el que se creó, y al leerlo se
valida contra `PLAYSTORE_BANK_APPS`. Si se corrige un ID, el estado anterior
queda inválido (`app_id does not match bank_id`) y rompe cualquier lectura de
ese banco. Si el banco aún no ingirió datos (0 capturas en `raw_staging/`),
basta borrar su estado; de lo contrario hay que migrarlo con cuidado. Ejemplo
para AZTECA, tras comprobar con `gcloud storage ls -r` que no hay capturas:

```bash
B=gs://voc-datalake-project-7bafd424-a385-4c05-b5b
gcloud storage rm -r "$B/state/ingestion/AZTECA/" "$B/state/ingestion/ledgers/AZTECA/" "$B/state/watermarks/AZTECA.json"
```

Un banco con estado ilegible ya no frena a los demás: `/api/v1/ingest/all`
sigue con el resto y responde 500 (`status: ERROR` por banco), y el replay de
sanitización lo omite, lo registra como `Bank state unreadable` y termina con
código 75.

### Logs estructurados y cómo consultarlos

Ingesta y sanitización escriben **un evento JSON por unidad de trabajo, nunca
por reseña**, con `run_id` para reconstruir una corrida. No llevan texto de
reseñas, nombres ni cursores: el helper `voc_common.log_event` descarta esos
campos (`FORBIDDEN_FIELDS`) aunque un llamador los pase.

| Mensaje | Servicio | Campos útiles |
| --- | --- | --- |
| `Ingestion run started` / `finished` | ingestion-worker | presupuestos; estado, `reason`, páginas, reseñas, solicitudes, `elapsed_sec` |
| `Play Store request` | ingestion-worker | `outcome` (`ok`, `rate_limited`, `transport_error`, `protocol_shape`), `latency_ms`, `rows`, `response_bytes`, `retries`, `status_code` |
| `Page published` | ingestion-worker | `page_id`, `reviews`, `latency_ms` de Pub/Sub |
| `Lease acquired` / `Lease lost` | ingestion-worker | `epoch`, motivo |
| `Sanitization run started` / `finished` | sanitization-job | presupuestos, `execution` de Cloud Run; totales y `phase_seconds` |
| `Microbatch finished` | sanitization-job | `batch_index`, `messages`, `batch_seconds`, `messages_per_second`, `phase_seconds`, `pages` |
| `Page closed` | sanitization-job | `page_id`, `status` (`WARNING` con huecos), `missing` |

```bash
# Tiempo y rendimiento por microbatch, con el desglose de BigQuery.
gcloud logging read 'resource.type="cloud_run_job" AND jsonPayload.message="Microbatch finished"' --freshness=6h --format='table(timestamp,jsonPayload.batch_index,jsonPayload.messages,jsonPayload.batch_seconds,jsonPayload.messages_per_second,jsonPayload.phase_seconds.bigquery_s,jsonPayload.phase_seconds.receipts_s)'
# Latencia y resultado de las solicitudes a Google Play.
gcloud logging read 'resource.type="cloud_run_revision" AND jsonPayload.message="Play Store request"' --freshness=6h --format='table(timestamp,jsonPayload.bank_id,jsonPayload.outcome,jsonPayload.latency_ms,jsonPayload.rows)'
```

Para analizar con SQL se puede enrutar a BigQuery con un *sink* de Cloud
Logging filtrado por esos mensajes (no implementado en Pulumi; el costo es
almacenamiento mínimo).

### Reprocesar lo que filtró la versión anterior

La primera corrida real (antes de retirar el filtro de 2 a 60 palabras)
descartó 467 de 2000 reseñas y dejó recibos `FILTERED_LENGTH`. Tras
desplegar la imagen nueva y **antes de que expiren las capturas** (7 días,
hasta el 2026-10-22 para lo ingerido el 2026-10-15), borrar el ledger derivado
de recibos y reproducir desde los manifiestos. El `MERGE` es idempotente, así
que lo ya cargado se reescribe igual:

```bash
gcloud storage rm -r "gs://voc-datalake-project-7bafd424-a385-4c05-b5b/state/ingestion/receipts/"
gcloud run jobs execute voc-sanitization-job --region us-central1 --args="--execution-mode=GCS_BACKFILL_MANIFESTS" --wait
```

No tocar `state/ingestion/manifests/`, `state/ingestion/ledgers/` ni
`state/watermarks/`: son el estado de la ingesta. Comprobar después con
`SELECT bank_id, COUNT(*), COUNTIF(conteo_palabras NOT BETWEEN 2 AND 60)
FROM bbva_voc_tds.sanitized_reviews_tds GROUP BY bank_id`: debe haber filas
fuera del rango.

Para la carga completa del histórico (decenas de ejecuciones, con puertas
de verificación) ver el [plan del full histórico](full_backfill.md), los
controladores `tools/backfill_controller.py` y el modo `GCS_FAST_REPLAY`
(`drain --fast-replay`), que reproduce desde las capturas con un cierre por
página en lugar de un recibo por evento.

### Capacidad: el cuello de botella es la sanitización

* Medición real (2026-10-15, antes de optimizar): **2.5 mensajes/s**, 2000
  mensajes en 805 s. A ese ritmo un full de ~2 M de eventos tomaría ~9 días,
  más que la expiración de 7 días del crudo. Las optimizaciones (E/S del
  ledger en paralelo, microbatch de 1000, tope por defecto de 20 000
  mensajes) están en el código; el informe de cada corrida trae
  `phase_seconds` para ver dónde se va el tiempo. El Scheduler lo lanza **una
  vez al día**; el flujo incremental normal cabe (BBVA ronda las 166 reseñas
  diarias).
* El crudo en `raw_staging/` y los mensajes de Pub/Sub **expiran a los 7 días**.
  Un backfill que publica más de lo que se drena en ese plazo pierde páginas
  (cierre `STAGING_EXPIRED`). Por eso: lanzar el backfill por tramos y drenar
  entre ellos con ejecuciones manuales del Job:

  ```bash
  gcloud run jobs execute voc-sanitization-job --region us-central1 \
    --args="--max-messages=20000" --wait
  ```

* Para el histórico completo, `GCS_FAST_REPLAY` evita los ~4 M de escrituras de
  recibos por evento (ver [plan del full](full_backfill.md)); su rendimiento
  real **tampoco está medido** y se mide en el piloto del plan.
* El rendimiento **tras las optimizaciones** no está medido: comparar
  `messages / elapsed_sec` de la próxima corrida contra los 2.5 de referencia
  antes de planear el backfill. Los mocks no validan ni cuotas ni latencia de
  BigQuery.
* Antes de cualquier ingesta verificar que los IDs de aplicación existan en
  Google Play: AZTECA y BANORTE fallaron con `protocol_shape` porque los IDs
  originales eran incorrectos (corregidos el 2026-10-15).
* El sondeo de la ingesta (`experiments/playstore/protocol_probe.py`) se ejecutó
  desde Colab. Cloud Run sale por otras IP de Google y no hay proxies
  configurados (`SCRAPER_PROXY_POOL_URLS` vacío): si Google Play responde con
  limitación (`RateLimitedError`) o con una página distinta, la primera corrida
  lo mostrará en los logs y en la auditoría.

## Desplegar nuevas imágenes de los workers

Las dos imágenes (`ingestion-worker` y `sanitization-pipeline`) comparten
código (`ingestion_worker` va dentro de la de sanitización), así que **siempre
se despliegan juntas y con el mismo SHA**. El 2026-10-16 se actualizó solo la de
ingesta y las páginas finales de los cinco bancos se cerraron con hueco (F-08).
`tools/deploy_images.py` lo hace en un paso y se niega a mezclar versiones:

```bash
uv run python tools/deploy_images.py --project <proyecto>            # preview
uv run python tools/deploy_images.py --project <proyecto> --apply    # + pulumi up
uv run python tools/deploy_images.py --project <proyecto> --sha <40 hex>
```

1. Lee en Artifact Registry las dos imágenes y elige el SHA más reciente que
   existe en **ambas** (o el de `--sha`; falla si falta en alguna). Solo cuentan
   digests `sha256:` y tags de 40 hex; `latest` se ignora.
2. Fija `ingestion_worker_image` y `sanitization_job_image` con
   `<registro>/<imagen>:<sha>@<digest>` (`pulumi config set`; esto modifica
   `infra/Pulumi.dev.yaml` aunque no uses `--apply`).
3. Muestra `pulumi preview --diff`. Con `--apply` ejecuta `pulumi up` solo si el
   preview no borra ni reemplaza recursos; si lo hace, se detiene.
4. No hace commit: versiona `infra/Pulumi.dev.yaml` en un commit aparte
   ("Actualiza las imágenes desplegadas a <sha>").

Se fija por digest y no por `latest` porque Pulumi despliega por diferencias:
un tag mutable no cambia en el texto y no dispara una revisión nueva (el código
de `infra/modules/cloud_run.py` lo rechaza), y el digest deja trazable qué
código produjo cada dato.

## Validación de la operación diaria (2026-10-18)

Venía del cierre de EPIC-1 a EPIC-4 (ahora en [`epics.md`](../backlog/epics.md#cierre-de-las-épicas-1-a-4)).

Dos días de corridas programadas tras la carga (16 y 17 de octubre):

| Comprobación | Resultado |
| --- | --- |
| Ingesta incremental (14:00Z, 5 bancos × 2 días) | Las 10 en `TARGET_REACHED`, 9–23 s; 1 000 reseñas publicadas por banco (500 NUBANK) por la ventana de revisita de 3 días |
| Sanitización (14:30Z) | `exit_code: 0`, `stop_reason: drained`; 4 500 mensajes cada día (847 y 901 filas escritas, el resto ya procesado); 0 cuarentenas, 0 reintentos, 0 `poison`, 0 capturas expiradas, sin errores por banco |
| Cierre de páginas | Las 9 páginas de cada día `RESOLVED` |
| TDS | Sin duplicados; crece cada día (+226 AZTECA, +349 BANORTE, +401 BBVA, +102 NUBANK, +382 SANTANDER desde el cierre de la carga) |
| Colas | `voc-raw-reviews-sub` y DLQ en 0 |
| Infraestructura | `pulumi preview`: 54 recursos sin cambios |
| Permisos temporales | Revocados: `run.invoker` de usuarios sobre `voc-ingestion-worker` y `serviceAccountTokenCreator` sobre `voc-sa-scheduler` |

Observaciones que no bloquean:

- **Retraso de ~24 h estable.** La reseña más reciente de cada banco es de las
  ~13:50 del día anterior a la corrida de las 14:00Z, los dos días. El patrón es
  constante (apunta al origen, no al pipeline), pero no está demostrado contra
  la ficha de Play en vivo.
- **Contador `PENDING` del informe final.** `Sanitization run finished` suma los
  estados intermedios de cada microbatch (p. ej. `PENDING: 16, RESOLVED: 9`)
  aunque todas las páginas cierren `RESOLVED`. Es un defecto de presentación del
  informe; mejora menor: reportar solo el estado final por página.
- **Propietarios del proyecto.** Hay tres cuentas con `roles/owner`
  (`0287289@up.edu.mx`, `traslasnovenas@gmail.com`, `jpaul.marquez.ruiz@gmail.com`);
  no se tocaron. Confirmar que ese nivel es intencional.

## Orden de activación (resumen y verificaciones)

1. Aplicar la fase 1 y configurar la identidad de CI.
2. Integrar en `main` las imágenes de EPIC-3 (feature 3.5) y EPIC-4 (feature
   4.4). La declaración IaC de una imagen no comprueba que su módulo arranque.
3. Fijar las imágenes por digest, pasar a `deploy_workloads: true`, revisar el
   preview y desplegar la fase 2.
4. Verificar acceso real a GCS y objetos cifrados si CMEK está activo, publicación
   Pub/Sub, auditoría BigQuery e invocación del Job con overrides de IDs.
5. Probar lease/fencing/CAS, publicación parcial, replay y continuación, y límites
   de ejecución en EPIC-3. Sanitización debe confirmar resultados duraderos antes
   de ack y respetar el TTL crudo de siete días.
6. Habilitar `ingestion_v2_enabled` (requisito de la primera corrida) y vigilar
   esa corrida. Mantener los históricos bajo demanda y observar sus estados,
   presupuesto y recuperación antes de ampliar volumen o tamaño de página.

Los consumidores reciben configuración desde outputs/variables del despliegue.
Para detalles de identidad, rutas, presupuestos y overrides, consultar los
[contratos de ingesta](../contracts/ingestion_v2.md).
