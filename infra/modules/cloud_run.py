"""Servicios Gen2 y sanitización efímera con identidad dedicada."""

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
from infra.modules.storage_bq import StorageAndBqResources

ARTIFACT_REPOSITORY_ID: Final = "voc-containers-repo"
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
    enable_vertex: bool = False,
    scraper_proxy_pool_urls: pulumi.Output[str] | None = None,
    ingestion_execution: IngestionExecutionConfig | None = None,
    historical_config: HistoricalJobConfig | None = None,
    ingestion_v2_enabled: bool = False,
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
        "BQ_PREDICTIONS_TABLE": storage_bq.delora_predictions.table_id,
        "BQ_INGESTION_RUNS_LOG_TABLE": storage_bq.ingestion_runs_log.table_id,
        "BQ_HITL_AUDIT_TABLE": storage_bq.hitl_triage_audit_log.table_id,
        "PUBSUB_RAW_REVIEWS_TOPIC": pubsub.raw_topic.name,
        "PUBSUB_RAW_SUBSCRIPTION": pubsub.raw_subscription.name,
        "PUBSUB_ALERTS_TOPIC": pubsub.alerts_topic.name,
        "ENABLE_DEDICATED_VERTEX_ENDPOINTS": str(enable_vertex).lower(),
    }
    deps = [
        repository,
        *api_deps,
        *security.iam_members,
        *[
            storage_bq.sanitized_reviews_tds,
            storage_bq.delora_predictions,
            storage_bq.ingestion_runs_log,
            storage_bq.hitl_triage_audit_log,
        ],
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
    ) -> gcp.cloudrunv2.Service:
        return gcp.cloudrunv2.Service(
            name,
            name=name,
            project=project_id,
            location=region,
            template={
                "execution_environment": "EXECUTION_ENVIRONMENT_GEN2",
                "service_account": account,
                "scaling": {"min_instance_count": 0, "max_instance_count": 2},
                "timeout": f"{timeout_sec}s",
                "containers": [
                    {
                        "image": image,
                        "resources": {
                            "limits": {"cpu": "1", "memory": "1Gi"},
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
    # El backend (EPIC-5) es opcional para activar ingesta y sanitización.
    backend = (
        service(
            "voc-api-backend",
            images.api_backend,
            security.sa_ml_and_backend.email,
            common,
        )
        if images.api_backend is not None
        else None
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
    return CloudRunResources(
        ingestion,
        sanitization,
        backend,
        ingestion_invoker,
        sanitization_invoker,
        historical,
        history_access,
        history_name,
    )
