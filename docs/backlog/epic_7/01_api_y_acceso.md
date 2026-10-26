# Paso 1. Features 7.1 (API, base) y 7.2 (Seguridad y acceso)

* **Estado (2026-10-25):** Pendiente.
* **Nivel:** imprescindible.
* **Depende de:** paso 0. En local no depende de nada: se trabaja con `PORTAL_AUTH_MODE=local` y `PORTAL_DATA=fixtures`. El despliegue en dev espera a B1, B2 y B3.
* **Objetivo:** el esqueleto de `services/api-backend/` que usarán todas las secciones: configuración, identidad con IAP, roles, acceso a BigQuery con costo acotado, escritura de solo inserción, errores, registros, archivos del portal, imagen, CI y CD, y la infraestructura del servicio privado. **No implementa las rutas de cada sección:** cada paso agrega las suyas.

## 1. Paquete

`services/api-backend/` existe con 7 archivos vacíos. Se reemplazan todos.

* **`pyproject.toml`:** `name = "api-backend"`, Python ≥ 3.11, *build backend* `hatchling`. Dependencias: `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `google-cloud-bigquery`, `google-cloud-secret-manager`, `google-cloud-dlp`, `google-auth`, `requests`, `cachetools`, `voc-common` y `voc-nlp` (sin extras: solo trae numpy y emoji). **Nunca** `ml-inference` ni `sanitization-pipeline`, que arrastran PyTorch, Gemini y Apache Beam. Las versiones, con los rangos que ya usa `uv.lock` (FastAPI 0.143, uvicorn 0.54).
* **Workspace:** quitar `services/api-backend` del `exclude` de `[tool.uv.workspace]` en el `pyproject.toml` de la raíz (lleva el comentario "TEMPORAL") y regenerar `uv.lock` con `uv lock`.
* **Estructura:**

```
services/api-backend/
├── pyproject.toml
├── Dockerfile
├── openapi.json                # generado: python -m api_backend.openapi > openapi.json
├── src/api_backend/
│   ├── __init__.py
│   ├── main.py                 # create_app(settings) -> FastAPI; app = create_app()
│   ├── openapi.py              # imprime el esquema sin levantar el servidor
│   ├── settings.py             # ApiSettings
│   ├── errors.py               # ApiError y el manejador que da el formato de error
│   ├── middleware.py           # id de petición, registro estructurado, encabezados de seguridad
│   ├── static.py               # sirve dist/ y la vuelta a index.html
│   ├── auth/
│   │   ├── iap.py              # verify_iap_jwt()
│   │   ├── roles.py            # Role, RoleMap, carga desde Secret Manager o local
│   │   └── deps.py             # current_principal(), require()
│   ├── bq/
│   │   ├── names.py            # tablas y vistas permitidas -> nombre calificado
│   │   ├── reader.py           # BigQueryReader: consultas parametrizadas con tope de bytes y caché
│   │   └── writer.py           # BigQueryWriter: INSERT idempotente desde modelos de voc-common
│   ├── fixtures.py             # repositorios en memoria con datos sintéticos (PORTAL_DATA=fixtures)
│   └── sections/
│       └── me/                 # router.py, schemas.py (este paso); cada paso agrega su carpeta
└── tests/
    ├── conftest.py             # app con principal falso, repositorios en memoria
    ├── fixtures/               # JSON sintéticos (sin texto real de reseñas)
    └── test_*.py
```

**Patrón de cada sección** (lo siguen todos los pasos): `sections/<sección>/` con `router.py` (rutas FastAPI y rol), `schemas.py` (modelos de respuesta y de petición de la API), `service.py` (reglas, sin SQL) y `repository.py` (un `Protocol` más su implementación de BigQuery, que arma el SQL y convierte cada fila en un modelo). Las filas de BigQuery no salen del repositorio: el servicio recibe modelos. Las pruebas de rutas usan la implementación en memoria del repositorio.

## 2. Configuración (`settings.py`)

`ApiSettings(BaseSettings)`, con variables de entorno sin prefijo, como el resto del monorepo:

| Campo | Variable | Por defecto | Nota |
| :--- | :--- | :--- | :--- |
| `environment` | `ENVIRONMENT` | `dev` | `local`, `dev`, `prod` |
| `gcp_project_id` | `GCP_PROJECT_ID` | — | Obligatorio salvo con datos sintéticos |
| `region` | `GCP_REGION` | `us-central1` | |
| `bq_dataset_id` | `BQ_DATASET_ID` | `bbva_voc_tds` | |
| `user_hash_salt` | `USER_HASH_SALT` | — | La misma regla que `voc_common.config`: mínimo 16 caracteres, y la de desarrollo no se acepta en `prod` |
| `iap_audience` | `IAP_AUDIENCE` | — | Obligatoria con `PORTAL_AUTH_MODE=iap`. Con IAP directo en Cloud Run: `/projects/<número>/locations/<región>/services/voc-api-backend`; con balanceador: `/projects/<número>/global/backendServices/<id>` |
| `portal_auth_mode` | `PORTAL_AUTH_MODE` | `iap` | `local` solo si `environment == "local"`: si no, la configuración falla al arrancar |
| `portal_local_user`, `portal_local_roles` | `PORTAL_LOCAL_USER`, `PORTAL_LOCAL_ROLES` | — | Solo en modo local |
| `portal_roles_secret` | `PORTAL_ROLES_SECRET` | `voc-portal-roles` | Nombre del secreto con el mapa de roles |
| `portal_data` | `PORTAL_DATA` | `bigquery` | `fixtures` usa los repositorios en memoria |
| `bq_max_bytes_billed` | `BQ_MAX_BYTES_BILLED` | `2_000_000_000` | Tope por consulta (2 GB) |
| `cache_ttl_seconds` | `CACHE_TTL_SECONDS` | `600` | Caché de agregados |
| `review_window_months` | `REVIEW_WINDOW_MONTHS` | `12` | Ventana por defecto del Explorador y la búsqueda |
| `online_service_url` | `ML_ONLINE_URL` | vacío | Servicio de explicación y embeddings (paso 6) |
| `dlp_inspect_template`, `dlp_deidentify_template` | `DLP_INSPECT_TEMPLATE`, `DLP_DEIDENTIFY_TEMPLATE` | — | Las plantillas que ya crea `infra/modules/dlp.py` (paso 4) |
| `static_dir` | `STATIC_DIR` | `/app/static` | `dist/` del portal |
| `build_commit` | `BUILD_COMMIT` | `unknown` | Lo fija la imagen |

## 3. Identidad y roles

### 3.1 IAP (`auth/iap.py`)

```python
@dataclass(frozen=True)
class Identity:
    email: str  # en minúsculas

def verify_iap_jwt(token: str, audience: str, request: Request | None = None) -> Identity:
    """Verifica x-goog-iap-jwt-assertion: firma (claves públicas de IAP), audiencia,
    emisor https://cloud.google.com/iap y vigencia. Lanza ApiError(401) si algo falla."""
```

* Con `google.oauth2.id_token.verify_token(token, google.auth.transport.requests.Request(), audience=audience, certs_url="https://www.gstatic.com/iap/verify/public_key")`. Comprobar en la documentación vigente de IAP la URL de las claves y el emisor.
* El correo sale del *claim* `email` del JWT. **No** se usa `x-goog-authenticated-user-email`, que puede falsificar quien llegue sin pasar por IAP.
* `/healthz` no pide identidad: la sonda de Cloud Run llega sin pasar por IAP.

### 3.2 Roles (`auth/roles.py`)

```python
class Role(StrEnum):
    LECTOR = "lector"
    ANALISTA = "analista"
    REVISOR = "revisor"
    ADMINISTRADOR = "administrador"

class PortalUser(BaseModel):  # extra="forbid"
    roles: list[Role]
    reviewer_tasks: list[HitlTask] = []  # sentiment, aspects, topic

class RoleMap(BaseModel):
    version: int
    users: dict[str, PortalUser]  # correo en minúsculas -> roles

class RoleSource(Protocol):
    def load(self) -> RoleMap: ...
```

* **Fuente:** el secreto `voc-portal-roles` (JSON con la forma de `RoleMap`), leído con `google-cloud-secret-manager` y guardado en caché 5 minutos. En modo local, `PORTAL_LOCAL_USER` y `PORTAL_LOCAL_ROLES`.
* **Qué permite cada rol** (un rol incluye al lector; el administrador incluye al analista):

| Capacidad | Lector | Analista | Revisor | Administrador |
| :--- | :-: | :-: | :-: | :-: |
| Landing, reporte, cockpit (solo agregados) | ✔ | ✔ | ✔ | ✔ |
| Explorador y búsqueda (texto sanitizado) | | ✔ | | ✔ |
| Alertas de deriva: ver y cambiar su estado | | ✔ | | ✔ |
| MLOps y AIOps: ver | | ✔ | | ✔ |
| HITL: las colas de sus `reviewer_tasks` | | | ✔ | |
| Administración, versiones del oro y acciones sobre el modelo (reentrenar, promover, *rollback*, re-ajustar tópicos) | | | | ✔ |

  El administrador revisa casos HITL solo si además tiene el rol de revisor (pregunta `S-02`).

* **Correo sin entrada en el mapa:** 403 en toda ruta `/api/*`, y el portal muestra "Tu cuenta no tiene acceso; pide acceso al autor". IAP ya habrá dejado fuera a quien no tenga permiso; el mapa es la segunda barrera.

### 3.3 Principal y dependencias (`auth/deps.py`)

```python
@dataclass(frozen=True)
class Principal:
    email: str
    actor_hash: str            # voc_common.text_utils.actor_hash(email, salt)
    roles: frozenset[Role]
    reviewer_tasks: frozenset[HitlTask]

def current_principal(request: Request, settings: ApiSettings = Depends(get_settings)) -> Principal: ...
def require(*roles: Role) -> Callable[..., Principal]: ...           # 403 si no tiene ninguno
def require_reviewer(task: HitlTask) -> Callable[..., Principal]: ...
```

* Cada ruta declara su rol con `Depends(require(...))`, y `router.py` registra el rol mínimo de cada ruta en `ROUTE_ROLES` (lo usa la prueba del centinela).
* **Hash del actor:** agregar `actor_hash(email: str, salt: str) -> str` a `packages/voc-common/src/voc_common/text_utils.py`, que llama a `hash_username_pii` (la regla `sha256("<sal>:<correo en minúsculas>")`), con su prueba; y `tools/actor_hash.py` (`uv run python tools/actor_hash.py <correo>`, que lee `USER_HASH_SALT`) para que el autor calcule su hash para la línea de comandos. El correo **nunca** se guarda ni se registra: solo el hash.

## 4. BigQuery

### 4.1 Nombres (`bq/names.py`)

Los identificadores no se pueden parametrizar, así que `qualified(name: str) -> str` devuelve `` `proyecto.dataset.nombre` `` solo para los nombres de una lista cerrada: las 28 tablas de `voc_common.bq_schema.ANALYTICS_V3_TABLES`, las 10 vistas del contrato, `sanitized_reviews_tds` e `ingestion_runs_log_v2`. Cualquier otro lanza un error.

### 4.2 Lectura (`bq/reader.py`)

```python
@dataclass(frozen=True)
class Param:
    name: str
    type: Literal["STRING", "INT64", "FLOAT64", "BOOL", "DATE", "TIMESTAMP"]
    value: object
    array: bool = False

class BigQueryReader:
    def __init__(self, client: bigquery.Client, settings: ApiSettings) -> None: ...
    def rows(self, sql: str, params: Sequence[Param], *, cache: bool = False,
             max_bytes: int | None = None) -> list[Mapping[str, object]]: ...
```

* Todo valor viaja como parámetro (`@nombre`); nunca se interpola en el SQL.
* `QueryJobConfig(maximum_bytes_billed=max_bytes or settings.bq_max_bytes_billed, use_query_cache=True)`. Si BigQuery rechaza la consulta por el tope, la API responde 503 con el código `query_too_expensive`.
* `cache=True` guarda el resultado en un `TTLCache` (`cache_ttl_seconds`) con clave (SQL, parámetros). Solo para agregados; nunca para HITL, administración ni texto.
* El registro de cada consulta lleva bytes facturados, segundos y el nombre de la consulta, para medir el costo.

### 4.3 Escritura (`bq/writer.py`)

```python
class BigQueryWriter:
    def insert(self, table: str, row: BaseModel, key: Sequence[str]) -> bool:
        """INSERT de una fila de un modelo de voc-common; devuelve False si la clave ya existía."""
```

* SQL: ``INSERT INTO t (`c1`, `c2`, …) SELECT @c1, @c2, … FROM (SELECT 1) WHERE NOT EXISTS (SELECT 1 FROM t WHERE `k1` = @k1 AND …)``. Las columnas van **listadas por nombre y entre comillas invertidas**: es lo que se corrigió en 6.6 (`INSERT` por posición y `at` como palabra reservada).
* El tipo de cada parámetro sale de `voc_common.bq_schema` del modelo: los campos `JSON` van con `PARSE_JSON(@c)` y las listas como parámetro de arreglo.
* Es DML de solo inserción (sin *streaming* ni `UPDATE` ni `DELETE`). La clave hace idempotente el reintento: el portal genera el id (`review_id`, `event_id`) al abrir el formulario.

### 4.4 Datos sintéticos (`fixtures.py`)

Repositorios en memoria que cumplen los mismos `Protocol`, cargados desde `tests/fixtures/*.json`. Los usan las pruebas y el modo `PORTAL_DATA=fixtures` para diseñar sin GCP. Los textos son inventados y cortos; uno de ellos es el **centinela** `"CENTINELA: este texto nunca debe llegar a un lector"`.

## 5. Base de la aplicación

* **`main.py`:** `create_app(settings: ApiSettings | None = None) -> FastAPI` monta el *middleware*, el manejador de errores, el router `/api/v1` de cada sección y, al final, los archivos estáticos. `docs_url` y `redoc_url` solo con `environment == "local"`.
* **Rutas de este paso:**

| Método y ruta | Rol | Respuesta |
| :--- | :--- | :--- |
| `GET /healthz` | Ninguno | `{"status": "ok", "commit": "<sha>"}` |
| `GET /api/v1/me` | Cualquiera con rol | `MeResponse { email, actor_hash, roles, reviewer_tasks, environment, commit }` |

* **Errores (`errors.py`):** toda respuesta de error es `{"error": {"code": "...", "message": "...", "request_id": "..."}}`. Códigos: `unauthenticated` (401), `forbidden` (403), `not_found` (404), `conflict` (409, por ejemplo una política que cambió mientras se editaba), `invalid` (422), `query_too_expensive` (503) y `upstream` (502, BigQuery, DLP o Jobs).
* **Middleware:**
  * id de petición: el de `X-Cloud-Trace-Context`, o un UUID si no viene; va en el encabezado `X-Request-Id` y en cada registro;
  * registro en JSON (`severity`, `request_id`, `route`, `status`, `latency_ms`, `actor_hash`). **Nunca** el cuerpo de la petición ni de la respuesta, ni el correo;
  * encabezados de seguridad: `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` y `Cache-Control: no-store` en `/api/*`.
* **Archivos del portal (`static.py`):** sirve `static_dir`. Los archivos de `assets/` (con *hash* en el nombre) van con `Cache-Control: public, max-age=31536000, immutable`; `index.html`, con `no-cache`. Cualquier `GET` que no sea `/api/*`, `/healthz` ni un archivo existente devuelve `index.html`. Sin `static_dir` (en pruebas), `/` responde 404.

## 6. Imagen, CI, CD e infraestructura

### 6.1 Imagen (`services/api-backend/Dockerfile`)

Multi-stage, desde la raíz del repo, con la plantilla de `services/ingestion-worker/Dockerfile`:

1. `node:24-bookworm-slim` AS `web`: `npm ci` y `npm run build` en `web/hitl-portal/` (desde el paso 2; mientras no exista, la etapa se omite con un `ARG BUILD_WEB=0`).
2. `uv` + `python:3.11-slim-bookworm` AS `builder`: `uv sync --frozen --no-dev --package api-backend --no-editable`.
3. `python:3.11-slim-bookworm` AS `runtime`: usuario 10001 sin root, `/opt/venv`, `dist/` en `/app/static`, `BUILD_COMMIT` como `ARG`, `CMD uvicorn api_backend.main:app --host 0.0.0.0 --port ${PORT}`.

* **`.dockerignore`** (lista de permitidos): sumar `services/api-backend/pyproject.toml`, `services/api-backend/src/`, `packages/voc-nlp/` (solo `pyproject.toml` y `src/`), `web/hitl-portal/` (sin `node_modules/` ni `dist/`) y, desde los pasos que los usen, `docs/thesis/`, los JSON de `docs/analytics/` y las guías de anotación.
* **`.gcloudignore`:** quitar la exclusión de `web/`.
* Borrar `web/hitl-portal/Dockerfile` (vacío): la imagen única es la de la API.

### 6.2 CI y CD

* **`ci.yaml`:**
  * en el trabajo `quality`, sumar `uv run pytest services/api-backend --cov=api_backend --cov-fail-under=85`;
  * un trabajo `api-backend-image` como los de las otras imágenes: construir y probar con el usuario 10001 que `/healthz` responde;
  * desde el paso 2, un trabajo `portal` con Node 24: `npm ci`, `npm run check`, `npm test` y `npm run build` en `web/hitl-portal/`, y la comprobación de que `src/api/schema.d.ts` está al día con `openapi.json`.
* **`cd-cloud-build.yaml`:** sumar `web/**` a las rutas que construyen `api-backend`. El paso `known` ya mapea `api_backend_image` y se salta si el Dockerfile está vacío.
* **`tools/deploy_images.py`:** sumar `("api-backend", "api_backend_image")` a `WORKERS` y corregir el mensaje "las dos imágenes".

### 6.3 Infraestructura (`infra/`)

Todo con `pulumi preview` revisado por el autor antes de `pulumi up`.

| Cambio | Dónde | Lo usa |
| :--- | :--- | :--- |
| `pulumi-gcp` 8.x, si B1 eligió IAP directo en Cloud Run; `pulumi preview` sin cambios inesperados en los recursos actuales | `infra/pyproject.toml`, `uv.lock` | Este paso |
| APIs `iap.googleapis.com` (y `compute`, `certificatemanager` si va con balanceador) | `infra/modules/apis.py` | Este paso |
| Cuenta `voc-sa-portal-api` | `infra/modules/kms_iam.py` | Todos |
| `roles/bigquery.jobUser` en el proyecto; `roles/bigquery.dataViewer` en el dataset `bbva_voc_tds` | `kms_iam.py` | Todos |
| `roles/bigquery.dataEditor` **por tabla** (`gcp.bigquery.IamMember` de tabla) solo en `hitl_items`, `hitl_events`, `hitl_reviews`, `hitl_boosts` (cierre de una subida), `drift_alert_events`, `risk_policy`, `drift_policy`, `gold_versions`, `review_explanations` y `curation_topics` | `kms_iam.py` o `analytics_bq.py` | Pasos 4 a 9 |
| `roles/dlp.user` | `kms_iam.py` | Paso 4 |
| `roles/secretmanager.secretAccessor` sobre `voc-portal-roles` | `infra/modules/secrets.py` | Este paso |
| `roles/run.jobsExecutorWithOverrides` sobre `voc-ml-training`, `voc-ml-rescoring`, `voc-ml-promote` y `voc-ml-topics-refit` | `cloud_run.py`, junto a los permisos de los Jobs de ML | Paso 8 |
| `roles/storage.objectViewer` en el bucket del datalake **con condición** de prefijo `ml_artifacts/` (los `training_manifest.json` del diagrama de confiabilidad) | `kms_iam.py` | Paso 8 |
| Secreto `voc-portal-roles` con su versión, armada desde la configuración cifrada `portal_users` | `secrets.py`, `Pulumi.dev.yaml` | Este paso |
| `service()` parametrizado: `cpu`, `memory`, `min_instances`, `max_instances`, `ingress` e `iap_enabled` (o el *backend* del balanceador), sin cambiar los valores de los servicios que ya existen | `cloud_run.py` | Este paso y el 6 |
| `voc-api-backend` con `voc-sa-portal-api`, 1 vCPU, 1 GiB, IAP activado, máximo 2 instancias y las variables de la sección 2 | `cloud_run.py`, `__main__.py` | Este paso |
| `roles/run.invoker` para el agente de servicio de IAP (`service-<número>@gcp-sa-iap.iam.gserviceaccount.com`) sobre `voc-api-backend` | `cloud_run.py` | Este paso |
| `roles/iap.httpsResourceAccessor` para cada correo de `portal_users` (el recurso de IAM de IAP para un servicio de Cloud Run; en `pulumi-gcp` 8, `gcp.iap.WebCloudRunServiceIamMember`; confirmar el nombre) | `cloud_run.py` | Este paso |
| Pantalla de consentimiento de OAuth de tipo externo, si la prueba de B1 lo pidió | Consola (una vez), anotado en `docs/operations/deployment.md` | Este paso |

* Los registros de auditoría de acceso a datos de BigQuery vienen activos por defecto: se comprueba y se anota en la Data Card (paso 10).
* `voc-sa-ml-backend` deja de ser la cuenta de la API. Sus permisos no cambian, porque los usan los Jobs.
* Las pruebas de `infra/tests/` que hoy esperan `voc-sa-ml-backend` en la API (`test_compute.py:68` y los de `test_deployment_phases.py`) se actualizan.

## 7. Pruebas (`services/api-backend/tests/`)

| Archivo | Comprueba |
| :--- | :--- |
| `test_settings.py` | `PORTAL_AUTH_MODE=local` falla fuera de `ENVIRONMENT=local`; la sal de desarrollo no se acepta en `prod`; `IAP_AUDIENCE` es obligatoria con IAP |
| `test_iap.py` | JWT válido firmado con una llave de prueba (las claves públicas se sustituyen por un doble) → `Identity`; audiencia, emisor o vigencia incorrectos → 401; sin encabezado → 401; el encabezado de correo sin JWT no autentica |
| `test_roles.py` | Lectura del mapa; correo sin entrada → 403 en `/api/v1/me`; un rol incluye al lector y el administrador al analista; `require_reviewer` exige la tarea; caché de 5 minutos |
| `test_me.py` | `/api/v1/me` devuelve roles y `actor_hash`, nunca guarda ni registra el correo |
| `test_sentinel.py` | **Ninguna ruta de rol lector entrega texto.** Recorre `ROUTE_ROLES`, llama a cada ruta `GET` de rol lector con los parámetros de `SAMPLE_PARAMS` contra los datos sintéticos (que incluyen el centinela en reseñas, comentarios y notas) y comprueba que el centinela no aparezca en ninguna respuesta. Una ruta de lector sin entrada en `SAMPLE_PARAMS` hace fallar la prueba, así que cada paso la extiende |
| `test_reader.py` | Ningún valor se interpola en el SQL; `maximum_bytes_billed` se fija siempre; el rechazo por tope da 503 `query_too_expensive`; la caché solo aplica con `cache=True` |
| `test_writer.py` | Columnas por nombre y entre comillas invertidas (incluida `at`); `NOT EXISTS` por la clave; JSON con `PARSE_JSON`; segundo `insert` con la misma clave → `False` |
| `test_static.py` | `/cockpit` y `/hitl/sentimiento` devuelven `index.html`; `/api/v1/nada` devuelve 404 en JSON; encabezados de caché y de seguridad |
| `test_errors.py` | Formato de error con `request_id` |
| `packages/voc-common/tests/…` | `actor_hash` igual a `hash_username_pii` y estable con mayúsculas y espacios |

Una prueba de integración opcional, marcada `@pytest.mark.bigquery` y fuera de CI, hace `dry_run` de cada consulta de los repositorios contra dev y anota los bytes.

## 8. Documentación

* `docs/operations/deployment.md`: una sección "Portal y API" con el despliegue, el alta de personas (`pulumi config set --secret portal_users …`), IAP y el cálculo del hash del actor.
* `README.md` de la raíz: corregir las líneas 50-52.
* `docs/contracts/analytics_outputs_v3.md`, sección 6, fila Seguridad: los roles salen del mapa `voc-portal-roles`, no de grupos de IAP.
* `CLAUDE.md`: el mapa de áreas ya tiene las filas de EPIC-7 (planificación, 2026-10-25).

## Terminado cuando

* [ ] La API arranca en local con datos sintéticos (`PORTAL_DATA=fixtures`, `PORTAL_AUTH_MODE=local`) y `/api/v1/me` responde.
* [ ] Las pruebas de la sección 7 pasan con cobertura ≥ 85 %, y la del centinela está lista para que cada paso la extienda.
* [ ] La imagen se construye y pasa su prueba de humo en CI.
* [ ] En dev (con B1 a B3 resueltos y `pulumi up` aprobado): `voc-api-backend` corre con `voc-sa-portal-api` detrás de IAP; una cuenta del mapa entra a `/api/v1/me`; una cuenta sin permiso de IAP no llega a la API; una cuenta con permiso de IAP pero sin entrada en el mapa recibe 403.
* [ ] `pulumi preview` queda sin cambios después del `up`.

## Decisiones al implementar

_(Se llena al ejecutar.)_

## Avance

_(Se llena al ejecutar.)_
