"""Servicios Gen2 y sanitización efímera con identidad dedicada."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Final

import pulumi
import pulumi_gcp as gcp
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from voc_common.config import DEV_USER_HASH_SALT, IngestionExecutionConfig

from infra.modules.dlp import DlpTemplates
from infra.modules.kms_iam import (
    SecurityResources,
    create_historical_job_access,
)
from infra.modules.pubsub import PubSubResources
from infra.modules.secrets import (
    KAGGLE_SECRET_ID,
    PORTAL_ROLES_SECRET_ID,
    SecretResources,
)
from infra.modules.storage_bq import StorageAndBqResources

ARTIFACT_REPOSITORY_ID: Final = "voc-containers-repo"
API_SERVICE_NAME: Final = "voc-api-backend"
# Solo digest inmutable: un tag mutable (p. ej. :latest) no dispara redeploys.
DigestImage = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^[a-z0-9.-]+(:[0-9]+)?(/[a-z0-9._-]+)+"
            r"(:[A-Za-z0-9._-]{1,128})?@sha256:[0-9a-f]{64}$"
        )
    ),
]


class WorkloadImages(BaseModel):
    """Imágenes publicadas por Cloud Build y fijadas por digest."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    ingestion_worker: DigestImage
    sanitization_job: DigestImage
    api_backend: DigestImage | None = None
    historical_job: DigestImage | None = None
    # Sin ella no se crean los Jobs de inferencia y monitoreo (EPIC-6).
    ml_inference: DigestImage | None = None


class HistoricalExecutionConfig(IngestionExecutionConfig):
    """Los overrides parciales mantienen defaults del histórico, no del HTTP."""

    ingestion_max_requests: int = Field(default=1000, gt=0)
    ingestion_max_response_bytes: int = Field(default=200_000_000, gt=0)
    ingestion_max_runtime_sec: int = Field(default=3480, gt=0)
    ingestion_container_timeout_sec: int = Field(default=3600, gt=0)
    ingestion_checkpoint_margin_sec: int = Field(default=120, gt=0)


class HistoricalJobConfig(BaseModel):
    """Perfil histórico independiente del presupuesto HTTP."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    execution: HistoricalExecutionConfig = Field(
        default_factory=HistoricalExecutionConfig,
    )
    command: tuple[Annotated[str, Field(min_length=1)], ...] = Field(
        default=("python", "-m", "ingestion_worker.job"),
        min_length=1,
    )
    max_retries: int = Field(default=1, ge=0, le=10)


@dataclass
class CloudRunResources:
    ingestion_worker: gcp.cloudrunv2.Service
    sanitization_job: gcp.cloudrunv2.Job
    api_backend: gcp.cloudrunv2.Service | None
    ingestion_invoker: gcp.cloudrunv2.ServiceIamMember
    sanitization_invoker: gcp.cloudrunv2.JobIamMember
    historical_job: gcp.cloudrunv2.Job
    historical_invoker: gcp.cloudrunv2.JobIamMember
    historical_job_name: pulumi.Output[str]
    ml_delta_job: gcp.cloudrunv2.Job | None = None
    ml_monitor_job: gcp.cloudrunv2.Job | None = None
    ml_rescoring_job: gcp.cloudrunv2.Job | None = None
    ml_topics_refit_job: gcp.cloudrunv2.Job | None = None
    ml_training_job: gcp.cloudrunv2.Job | None = None
    ml_topics_backfill_job: gcp.cloudrunv2.Job | None = None
    ml_aspects_backfill_job: gcp.cloudrunv2.Job | None = None
    ml_promote_job: gcp.cloudrunv2.Job | None = None
    ml_invokers: tuple[gcp.cloudrunv2.JobIamMember, ...] = ()
    ml_executors: tuple[gcp.cloudrunv2.JobIamMember, ...] = ()
    # IAP directo en voc-api-backend: el agente de IAP invoca el servicio y
    # cada persona de portal_users recibe iap.httpsResourceAccessor.
    iap_invoker: gcp.cloudrunv2.ServiceIamMember | None = None
    iap_accessors: tuple[gcp.iap.WebCloudRunServiceIamMember, ...] = ()


@dataclass(frozen=True)
class MlJobSpec:
    """Job de ``ml-inference``: el subcomando va como argumento."""

    name: str
    command: str
    memory: str = "2Gi"
    cpu: str = "1"
    timeout_sec: int = 1800
    max_retries: int = 1
    # Con Scheduler (invocador) o solo a mano con ``gcloud run jobs execute``.
    scheduled: bool = True
    # Variable de entorno → secreto de Secret Manager (última versión).
    secrets: tuple[tuple[str, str], ...] = ()
    # Lo lanzan otros Jobs de ml-inference con argumentos propios: la cuenta
    # de ML recibe roles/run.developer solo sobre él (run.invoker no deja
    # cambiar los argumentos).
    executed_by_ml: bool = False


# Un solo Job en serie. Con 2 GiB el primer delta se quedó sin memoria al
# embeber y asignar tópicos a las cláusulas (2026-10-25), así que usa 4 GiB.
ML_DELTA_JOB = MlJobSpec("voc-ml-inference-delta", "delta", memory="4Gi")
ML_MONITOR_JOB = MlJobSpec("voc-ml-monitor", "monitor")
# Re-ajuste trimestral de tópicos: MiniLM, UMAP y HDBSCAN sobre ~63 000
# cláusulas; 2 vCPU y 4 GiB, 1 h, sin reintentos (el siguiente trimestre o
# --force).
ML_TOPICS_REFIT_JOB = MlJobSpec(
    "voc-ml-topics-refit",
    "topics-refit",
    memory="4Gi",
    cpu="2",
    timeout_sec=3600,
    max_retries=0,
)
# Re-scoring de una candidata en Kaggle, a mano y antes de promoverla:
#   gcloud run jobs execute voc-ml-rescoring \
#     --args=rescore,--model-version=<versión>
# 2 vCPU para preparar los textos en paralelo; 4 GiB por el dataset que
# arma en memoria; 3 h y sin reintentos (cada corrida sube su dataset).
ML_RESCORING_JOB = MlJobSpec(
    "voc-ml-rescoring",
    "rescore",
    memory="4Gi",
    cpu="2",
    timeout_sec=10800,
    max_retries=0,
    scheduled=False,
    secrets=(("KAGGLE_API_TOKEN", KAGGLE_SECRET_ID),),
    executed_by_ml=True,
)
# Reentrenamiento en Kaggle desde el modelo base, a mano o desde el monitor
# con retrain_trigger = auto:
#   gcloud run jobs execute voc-ml-training
# Arma el conjunto en memoria y espera al kernel (hasta 3 h); 4 h y sin
# reintentos, como el re-scoring.
ML_TRAINING_JOB = MlJobSpec(
    "voc-ml-training",
    "train",
    memory="4Gi",
    cpu="2",
    timeout_sec=14400,
    max_retries=0,
    scheduled=False,
    secrets=(("KAGGLE_API_TOKEN", KAGGLE_SECRET_ID),),
    executed_by_ml=True,
)
# Re-asignación del histórico de tópicos sobre segment_embeddings, en Cloud
# Run y sin Kaggle (el texto no sale de GCP); la lanza el delta cuando la
# versión activa no tiene su backfill. Lotes de 50 000 cláusulas: si UMAP no
# cabe en 4 GiB se sube a 8 GiB.
ML_TOPICS_BACKFILL_JOB = MlJobSpec(
    "voc-ml-topics-backfill",
    "topics-backfill",
    memory="4Gi",
    cpu="2",
    timeout_sec=7200,
    max_retries=0,
    scheduled=False,
    executed_by_ml=True,
)
# Familias con Gemini de un prompt nuevo, solo si el autor paga el costo:
#   gcloud run jobs execute voc-ml-aspects-backfill \
#     --args=aspects-backfill,--approve,--max-usd=<tope>
# Sin --approve solo estima. 6 h; sin reintentos (una corrida se retoma).
ML_ASPECTS_BACKFILL_JOB = MlJobSpec(
    "voc-ml-aspects-backfill",
    "aspects-backfill",
    timeout_sec=21600,
    max_retries=0,
    scheduled=False,
)
# Promoción (o rollback) de una versión, para el botón de MLOps:
#   gcloud run jobs execute voc-ml-promote \
#     --args=promote,--model-version=<versión>,--actor-hash=<hash>,\
#     --reason=<motivo>
ML_PROMOTE_JOB = MlJobSpec(
    "voc-ml-promote",
    "promote",
    max_retries=0,
    scheduled=False,
)


def _validate_hash_salt(value: str, environment: str) -> str:
    if len(value.strip()) < 16:
        raise ValueError("USER_HASH_SALT requiere al menos 16 caracteres")
    if (
        environment.strip().lower() in {"prod", "production"}
        and value.strip() == DEV_USER_HASH_SALT
    ):
        raise ValueError("USER_HASH_SALT de desarrollo no válido en producción")
    return value


def validate_execution_profiles(
    execution: IngestionExecutionConfig,
    history: HistoricalJobConfig,
) -> None:
    """Valida perfiles en ambas fases para fallar antes de publicar imágenes."""
    if execution.ingestion_container_timeout_sec > 3600:
        raise ValueError("HTTP timeout cannot exceed 3600 seconds")
    if history.execution.ingestion_container_timeout_sec > 604800:
        raise ValueError("historical task timeout cannot exceed seven days")


def create_artifact_registry(
    project_id: str,
    region: str,
    api_deps: list[pulumi.Resource],
) -> gcp.artifactregistry.Repository:
    """Fase 1: el repositorio existe antes de que Cloud Build publique."""
    return gcp.artifactregistry.Repository(
        ARTIFACT_REPOSITORY_ID,
        project=project_id,
        location=region,
        repository_id=ARTIFACT_REPOSITORY_ID,
        format="DOCKER",
        # Tags = SHA de commit: inmutables para que digest y tag no diverjan.
        docker_config={"immutable_tags": True},
        opts=pulumi.ResourceOptions(depends_on=api_deps),
    )


def create_cloud_run_resources(
    project_id: str,
    region: str,
    security: SecurityResources,
    pubsub: PubSubResources,
    storage_bq: StorageAndBqResources,
    dlp: DlpTemplates,
    api_deps: list[pulumi.Resource],
    *,
    repository: gcp.artifactregistry.Repository,
    images: WorkloadImages,
    user_hash_salt: pulumi.Output[str],
    environment: str = "dev",
    free_tier_mode: bool = True,
    scraper_proxy_pool_urls: pulumi.Output[str] | None = None,
    ingestion_execution: IngestionExecutionConfig | None = None,
    historical_config: HistoricalJobConfig | None = None,
    ingestion_v2_enabled: bool = False,
    secrets: SecretResources | None = None,
    portal_emails: Sequence[str] = (),
) -> CloudRunResources:
    """Fase 2: define contenedores y permisos; no ejecuta jobs ni builds."""
    execution = ingestion_execution or IngestionExecutionConfig()
    history = historical_config or HistoricalJobConfig()
    validate_execution_profiles(execution, history)
    user_hash_salt = user_hash_salt.apply(
        lambda value: _validate_hash_salt(value, environment)
    )
    common: dict[str, pulumi.Input[str]] = {
        "ENVIRONMENT": environment,
        "USER_HASH_SALT": user_hash_salt,
        "FREE_TIER_MODE": str(free_tier_mode).lower(),
        "GCP_PROJECT_ID": project_id,
        "GCP_REGION": region,
        "GCS_RAW_DATALAKE_BUCKET": storage_bq.datalake_bucket.name,
        **{
            name.upper(): value
            for name, value in storage_bq.storage_layout.model_dump().items()
        },
        "BQ_DATASET_ID": storage_bq.dataset.dataset_id,
        "BQ_SANITIZED_TDS_TABLE": storage_bq.sanitized_reviews_tds.table_id,
        "BQ_INGESTION_RUNS_LOG_TABLE": storage_bq.ingestion_runs_log.table_id,
        "PUBSUB_RAW_REVIEWS_TOPIC": pubsub.raw_topic.name,
        "PUBSUB_RAW_SUBSCRIPTION": pubsub.raw_subscription.name,
        "PUBSUB_ALERTS_TOPIC": pubsub.alerts_topic.name,
    }
    # Tópicos del monitor (InferenceSettings.drift_topic y quality_topic).
    ml_env: dict[str, pulumi.Input[str]] = {
        **common,
        "DRIFT_TOPIC": pubsub.alerts_topic.name,
        "QUALITY_TOPIC": pubsub.quality_topic.name,
        # El registro de modelos de Vertex exige una imagen de serving: la
        # propia (el entrenamiento registra sus candidatos).
        **(
            {"SERVING_IMAGE": images.ml_inference}
            if images.ml_inference is not None
            else {}
        ),
    }
    deps = [
        repository,
        *api_deps,
        *security.iam_members,
        storage_bq.sanitized_reviews_tds,
        storage_bq.ingestion_runs_log,
    ]
    opts = pulumi.ResourceOptions(depends_on=deps)

    def execution_env(
        profile: IngestionExecutionConfig,
    ) -> dict[str, pulumi.Input[str]]:
        return {
            **{
                key.upper(): str(value)
                for key, value in profile.model_dump().items()
            },
            "INGESTION_V2_ENABLED": str(ingestion_v2_enabled).lower(),
            "SCRAPER_PROXY_POOL_URLS": (
                scraper_proxy_pool_urls
                if scraper_proxy_pool_urls is not None
                else "[]"
            ),
        }

    historical = gcp.cloudrunv2.Job(
        "voc-ingestion-history-job",
        name="voc-ingestion-history-job",
        project=project_id,
        location=region,
        # pulumi-gcp 8 protege del borrado; dev sigue como con la 7.
        deletion_protection=False,
        template={
            "task_count": 1,
            "parallelism": 1,
            "template": {
                "service_account": security.sa_ingestion_worker.email,
                "execution_environment": "EXECUTION_ENVIRONMENT_GEN2",
                "timeout": (
                    f"{history.execution.ingestion_container_timeout_sec}s"
                ),
                "max_retries": history.max_retries,
                "containers": [
                    {
                        "name": "historical-ingestion",
                        "image": images.historical_job
                        or images.ingestion_worker,
                        "commands": list(history.command),
                        "resources": {"limits": {"cpu": "1", "memory": "1Gi"}},
                        "envs": [
                            {"name": key, "value": value}
                            for key, value in {
                                **common,
                                **execution_env(history.execution),
                            }.items()
                        ],
                    }
                ],
            },
        },
        opts=opts,
    )
    history_access = create_historical_job_access(
        historical,
        security.sa_ingestion_worker,
        project_id,
        region,
    )
    history_name = pulumi.Output.concat(
        "projects/",
        project_id,
        "/locations/",
        region,
        "/jobs/",
        historical.name,
    )

    def service(
        name: str,
        image: str,
        account: pulumi.Output[str],
        env: dict[str, pulumi.Input[str]],
        timeout_sec: int = 900,
        wait_for: list[pulumi.Resource] | None = None,
        *,
        cpu: str = "1",
        memory: str = "1Gi",
        min_instances: int = 0,
        max_instances: int = 2,
        ingress: str | None = None,
        iap_enabled: bool | None = None,
    ) -> gcp.cloudrunv2.Service:
        # ingress e iap_enabled solo se declaran cuando se piden: los
        # servicios existentes no deben cambiar en `pulumi preview`.
        extra: dict[str, object] = {}
        if ingress is not None:
            extra["ingress"] = ingress
        if iap_enabled is not None:
            extra["iap_enabled"] = iap_enabled
        return gcp.cloudrunv2.Service(
            name,
            name=name,
            project=project_id,
            location=region,
            # pulumi-gcp 8 protege del borrado; dev sigue como con la 7.
            deletion_protection=False,
            **extra,
            # La API devuelve este valor por defecto a nivel de servicio;
            # declararlo evita un diff permanente en `pulumi preview`.
            scaling={"min_instance_count": 0},
            template={
                "execution_environment": "EXECUTION_ENVIRONMENT_GEN2",
                "service_account": account,
                "scaling": {
                    "min_instance_count": min_instances,
                    "max_instance_count": max_instances,
                },
                "timeout": f"{timeout_sec}s",
                "containers": [
                    {
                        "image": image,
                        "resources": {
                            "limits": {"cpu": cpu, "memory": memory},
                            "cpu_idle": True,
                        },
                        "envs": [
                            {"name": k, "value": v} for k, v in env.items()
                        ],
                    }
                ],
            },
            opts=pulumi.ResourceOptions(depends_on=[*deps, *(wait_for or [])]),
        )

    ingestion = service(
        "voc-ingestion-worker",
        images.ingestion_worker,
        security.sa_ingestion_worker.email,
        {
            **common,
            **execution_env(execution),
            "INGESTION_HISTORY_JOB_NAME": history_name,
        },
        timeout_sec=execution.ingestion_container_timeout_sec,
        wait_for=[historical, history_access],
    )
    sanitization = gcp.cloudrunv2.Job(
        "voc-sanitization-job",
        name="voc-sanitization-job",
        project=project_id,
        location=region,
        # pulumi-gcp 8 protege del borrado; dev sigue como con la 7.
        deletion_protection=False,
        template={
            "task_count": 1,
            "parallelism": 1,
            "template": {
                "service_account": security.sa_sanitization_worker.email,
                "execution_environment": "EXECUTION_ENVIRONMENT_GEN2",
                "timeout": "1800s",
                "max_retries": 1,
                "containers": [
                    {
                        "image": images.sanitization_job,
                        "resources": {"limits": {"cpu": "1", "memory": "1Gi"}},
                        "envs": [
                            {"name": k, "value": v}
                            for k, v in {
                                **common,
                                "DLP_INSPECT_TEMPLATE_ID": (
                                    dlp.inspect_template.id
                                ),
                                "DLP_DEIDENTIFY_TEMPLATE_ID": (
                                    dlp.deidentify_template.id
                                ),
                                "BEAM_RUNNER": "DirectRunner",
                                # El preflight lee el estado de la ingesta y
                                # exige el flag (sin él: exit 64).
                                "INGESTION_V2_ENABLED": str(
                                    ingestion_v2_enabled
                                ).lower(),
                            }.items()
                        ],
                    }
                ],
            },
        },
        opts=opts,
    )
    # La API y el portal (EPIC-7) son opcionales para activar la ingesta.
    backend = None
    iap_invoker = None
    iap_accessors: list[gcp.iap.WebCloudRunServiceIamMember] = []
    if images.api_backend is not None:
        # Agente de IAP: su correo trae el número del proyecto, que forma la
        # audiencia del JWT (/projects/<número>/locations/<región>/services/…).
        iap_agent = gcp.projects.ServiceIdentity(
            "voc-iap-service-agent",
            project=project_id,
            service="iap.googleapis.com",
            opts=opts,
        )
        portal_env: dict[str, pulumi.Input[str]] = {
            "ENVIRONMENT": environment,
            "USER_HASH_SALT": user_hash_salt,
            "GCP_PROJECT_ID": project_id,
            "GCP_REGION": region,
            "BQ_DATASET_ID": storage_bq.dataset.dataset_id,
            "PORTAL_AUTH_MODE": "iap",
            "PORTAL_DATA": "bigquery",
            "PORTAL_ROLES_SECRET": PORTAL_ROLES_SECRET_ID,
            "IAP_AUDIENCE": iap_agent.email.apply(
                lambda email: (
                    f"/projects/{email.split('@')[0].removeprefix('service-')}"
                    f"/locations/{region}/services/{API_SERVICE_NAME}"
                )
            ),
            "DLP_INSPECT_TEMPLATE": dlp.inspect_template.id,
            "DLP_DEIDENTIFY_TEMPLATE": dlp.deidentify_template.id,
        }
        backend = service(
            API_SERVICE_NAME,
            images.api_backend,
            security.sa_portal_api.email,
            portal_env,
            timeout_sec=300,
            ingress="INGRESS_TRAFFIC_ALL",
            iap_enabled=True,
        )
        iap_invoker = gcp.cloudrunv2.ServiceIamMember(
            "voc-api-iap-invoker",
            project=project_id,
            location=region,
            name=backend.name,
            role="roles/run.invoker",
            member=iap_agent.email.apply(
                lambda email: f"serviceAccount:{email}"
            ),
            opts=opts,
        )
        for email in portal_emails:
            # El nombre del recurso lleva un hash, no el correo, y el miembro
            # es secreto: ni la URN ni el preview exponen a las personas.
            digest = hashlib.sha256(email.encode()).hexdigest()[:10]
            iap_accessors.append(
                gcp.iap.WebCloudRunServiceIamMember(
                    f"voc-portal-iap-{digest}",
                    project=project_id,
                    location=region,
                    cloud_run_service_name=backend.name,
                    role="roles/iap.httpsResourceAccessor",
                    member=pulumi.Output.secret(f"user:{email}"),
                    opts=opts,
                )
            )
    invoker = security.sa_scheduler_invoker.email.apply(
        lambda email: f"serviceAccount:{email}"
    )
    ingestion_invoker = gcp.cloudrunv2.ServiceIamMember(
        "voc-ingestion-scheduler-invoker",
        project=project_id,
        location=region,
        name=ingestion.name,
        role="roles/run.invoker",
        member=invoker,
        opts=opts,
    )
    sanitization_invoker = gcp.cloudrunv2.JobIamMember(
        "voc-sanitization-scheduler-invoker",
        project=project_id,
        location=region,
        name=sanitization.name,
        role="roles/run.invoker",
        member=invoker,
        opts=opts,
    )
    ml_jobs: dict[str, gcp.cloudrunv2.Job] = {}
    ml_invokers: list[gcp.cloudrunv2.JobIamMember] = []
    ml_executors: list[gcp.cloudrunv2.JobIamMember] = []
    ml_member = security.sa_ml_and_backend.email.apply(
        lambda email: f"serviceAccount:{email}"
    )
    if images.ml_inference is not None:
        specs = [
            ML_DELTA_JOB,
            ML_MONITOR_JOB,
            ML_TOPICS_REFIT_JOB,
            ML_TOPICS_BACKFILL_JOB,
            ML_ASPECTS_BACKFILL_JOB,
            ML_PROMOTE_JOB,
        ]
        if secrets is not None:
            specs += [ML_RESCORING_JOB, ML_TRAINING_JOB]
        for spec in specs:
            secret_envs = [
                {
                    "name": env,
                    "value_source": {
                        "secret_key_ref": {
                            "secret": secret_id,
                            "version": "latest",
                        }
                    },
                }
                for env, secret_id in spec.secrets
            ]
            job_opts = (
                pulumi.ResourceOptions(
                    depends_on=[*deps, secrets.kaggle_accessor]
                )
                if spec.secrets and secrets is not None
                else opts
            )
            job = gcp.cloudrunv2.Job(
                spec.name,
                name=spec.name,
                project=project_id,
                location=region,
                # pulumi-gcp 8 protege del borrado; dev sigue como con la 7.
                deletion_protection=False,
                template={
                    "task_count": 1,
                    "parallelism": 1,
                    "template": {
                        "service_account": security.sa_ml_and_backend.email,
                        "execution_environment": "EXECUTION_ENVIRONMENT_GEN2",
                        "timeout": f"{spec.timeout_sec}s",
                        "max_retries": spec.max_retries,
                        "containers": [
                            {
                                "image": images.ml_inference,
                                # ENTRYPOINT: python -m ml_inference.
                                "args": [spec.command],
                                "resources": {
                                    "limits": {
                                        "cpu": spec.cpu,
                                        "memory": spec.memory,
                                    }
                                },
                                "envs": [
                                    *(
                                        {"name": k, "value": v}
                                        for k, v in ml_env.items()
                                    ),
                                    *secret_envs,
                                ],
                            }
                        ],
                    },
                },
                opts=job_opts,
            )
            ml_jobs[spec.command] = job
            if spec.executed_by_ml:
                ml_executors.append(
                    gcp.cloudrunv2.JobIamMember(
                        f"{spec.name}-ml-backend-developer",
                        project=project_id,
                        location=region,
                        name=job.name,
                        role="roles/run.developer",
                        member=ml_member,
                        opts=opts,
                    )
                )
            if not spec.scheduled:
                continue
            ml_invokers.append(
                gcp.cloudrunv2.JobIamMember(
                    f"{spec.name}-scheduler-invoker",
                    project=project_id,
                    location=region,
                    name=job.name,
                    role="roles/run.invoker",
                    member=invoker,
                    opts=opts,
                )
            )
    return CloudRunResources(
        ingestion,
        sanitization,
        backend,
        ingestion_invoker,
        sanitization_invoker,
        historical,
        history_access,
        history_name,
        ml_delta_job=ml_jobs.get(ML_DELTA_JOB.command),
        ml_monitor_job=ml_jobs.get(ML_MONITOR_JOB.command),
        ml_rescoring_job=ml_jobs.get(ML_RESCORING_JOB.command),
        ml_topics_refit_job=ml_jobs.get(ML_TOPICS_REFIT_JOB.command),
        ml_training_job=ml_jobs.get(ML_TRAINING_JOB.command),
        ml_topics_backfill_job=ml_jobs.get(ML_TOPICS_BACKFILL_JOB.command),
        ml_aspects_backfill_job=ml_jobs.get(ML_ASPECTS_BACKFILL_JOB.command),
        ml_promote_job=ml_jobs.get(ML_PROMOTE_JOB.command),
        ml_invokers=tuple(ml_invokers),
        ml_executors=tuple(ml_executors),
        iap_invoker=iap_invoker,
        iap_accessors=tuple(iap_accessors),
    )
