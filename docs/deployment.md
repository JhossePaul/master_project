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

CI ejecuta esas suites y Ruff, Pyrefly y Bandit. La matriz integrada de `infra`
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
| `dev` | `gs://pulumi-state-voc-project-7bafd424-a385-4c05-b5b` | passphrase (`encryptionsalt` en `Pulumi.dev.yaml`) |
| `prod` | pendiente: mismo patrón, bucket en el proyecto de prod | se recomienda `gcpkms://` |

Bucket de `dev` (2026-10-15): `us-central1`, versionado activo, acceso uniforme
a nivel de bucket y soft delete de 7 días. El stack `dev` se creó con
`pulumi stack init dev` en ese backend y el preview se validó; aún no tiene
recursos desplegados.

Para operar el stack:

```bash
gcloud auth application-default login       # credenciales para backend y proveedor
pulumi login gs://pulumi-state-voc-project-7bafd424-a385-4c05-b5b
cd infra && pulumi stack select dev
export PULUMI_CONFIG_PASSPHRASE=...           # la del stack; nunca en archivos ni logs
```

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
2. Desde `infra/`, seleccionar el stack `dev` con `PULUMI_CONFIG_PASSPHRASE`.
3. Revisar `Pulumi.dev.yaml`: proyecto/región reales, fase
   (`deploy_workloads`), imágenes por digest, perfiles HTTP/histórico, modo de
   operación y prefijos. Configurar los secretos con `pulumi config set
   --secret`; nunca incluir valores reales en archivos o logs.
4. Proporcionar credenciales GCP válidas (`gcloud auth application-default
   login`) y confirmar proyecto y permisos del ambiente elegido.
5. Ejecutar `pulumi preview --stack dev --non-interactive` y revisar el plan.

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

- [`cloudbuild.yaml`](../cloudbuild.yaml) construye `services/<_SERVICE>/Dockerfile`
  con contexto en la raíz del workspace uv, `--platform=linux/amd64`, y publica
  `<region>-docker.pkg.dev/<proyecto>/voc-containers-repo/<servicio>:<_TAG>`.
  Rechaza `_TAG` que no sea un SHA de 40 caracteres y Dockerfiles vacíos.
- [`.github/workflows/cd-cloud-build.yaml`](../.github/workflows/cd-cloud-build.yaml)
  lo invoca por servicio al hacer merge a `main` (cambios en `services/`,
  `packages/`, lock o pipeline) o con `workflow_dispatch`, siempre desde `main`.
  No tiene disparador `pull_request`, así que las credenciales nunca llegan a
  código no revisado. Omite servicios con Dockerfile vacío: hoy solo construye
  `ingestion-worker` (feature 3.5); `sanitization-pipeline` y `api-backend`
  entran cuando tengan Dockerfile. `develop` no publica imágenes: se publican
  al integrar en `main` por PR.
- Solo se sube a Cloud Build lo que permite [`.gcloudignore`](../.gcloudignore)
  (nunca `.env` ni `evidence/`), y el contexto Docker lo restringe
  [`.dockerignore`](../.dockerignore); el build usa BuildKit
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

## Orden de activación

1. Aplicar la fase 1 cuando se autorice (`pulumi up`) y configurar la identidad
   de CI.
2. Integrar en `main` las imágenes de EPIC-3 (feature 3.5) y EPIC-4 (feature
   4.4), ya en `develop`; el merge a `main` publica las imágenes.
   La declaración IaC de una imagen no comprueba que su módulo arranque.
3. Fijar las imágenes por digest, pasar a `deploy_workloads: true`, revisar el
   preview y desplegar la fase 2.
4. Verificar acceso real a GCS y objetos cifrados si CMEK está activo, publicación
   Pub/Sub, auditoría BigQuery e invocación del Job con overrides de IDs.
5. Probar lease/fencing/CAS, publicación parcial, replay y continuación, y límites
   de ejecución en EPIC-3. Sanitización debe confirmar resultados duraderos antes
   de ack y respetar el TTL crudo de siete días.
6. Habilitar explícitamente `ingestion_v2_enabled` cuando runtime e integración
   estén verificados. Mantener los históricos bajo demanda y observar sus estados,
   presupuesto y recuperación antes de ampliar volumen o tamaño de página.

Los consumidores reciben configuración desde outputs/variables del despliegue.
Para detalles de identidad, rutas, presupuestos y overrides, consultar los
[contratos de ingesta](contracts/ingestion_v2.md).
