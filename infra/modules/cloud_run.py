"""Servicios Gen2 y sanitización efímera con identidad dedicada."""

from dataclasses import dataclass

import pulumi
import pulumi_gcp as gcp
from voc_common.config import DEV_USER_HASH_SALT

from infra.modules.dlp import DlpTemplates
from infra.modules.kms_iam import SecurityResources
from infra.modules.pubsub import PubSubResources
from infra.modules.storage_bq import StorageAndBqResources


@dataclass
class CloudRunResources:
    repository: gcp.artifactregistry.Repository
    ingestion_worker: gcp.cloudrunv2.Service
    sanitization_job: gcp.cloudrunv2.Job
    api_backend: gcp.cloudrunv2.Service
    ingestion_invoker: gcp.cloudrunv2.ServiceIamMember
    sanitization_invoker: gcp.cloudrunv2.JobIamMember


def _validate_hash_salt(value: str, environment: str) -> str:
    if len(value.strip()) < 16:
        raise ValueError("USER_HASH_SALT requiere al menos 16 caracteres")
    if (
        environment.strip().lower() in {"prod", "production"}
        and value.strip() == DEV_USER_HASH_SALT
    ):
        raise ValueError("USER_HASH_SALT de desarrollo no válido en producción")
    return value


def create_cloud_run_resources(
    project_id: str,
    region: str,
    security: SecurityResources,
    pubsub: PubSubResources,
    storage_bq: StorageAndBqResources,
    dlp: DlpTemplates,
    api_deps: list[pulumi.Resource],
    *,
    ingestion_worker_image: str,
    sanitization_job_image: str,
    api_backend_image: str,
    user_hash_salt: pulumi.Output[str],
    environment: str = "dev",
    free_tier_mode: bool = True,
    enable_vertex: bool = False,
    scraper_proxy_pool_urls: pulumi.Output[str] | None = None,
) -> CloudRunResources:
    """Define contenedores y permisos; no ejecuta jobs ni publica imágenes."""
    user_hash_salt = user_hash_salt.apply(
        lambda value: _validate_hash_salt(value, environment)
    )
    repository = gcp.artifactregistry.Repository(
        "voc-containers-repo",
        project=project_id,
        location=region,
        repository_id="voc-containers-repo",
        format="DOCKER",
        opts=pulumi.ResourceOptions(depends_on=api_deps),
    )
    common: dict[str, pulumi.Input[str]] = {
        "ENVIRONMENT": environment,
        "FREE_TIER_MODE": str(free_tier_mode).lower(),
        "GCP_PROJECT_ID": project_id,
        "GCP_REGION": region,
        "GCS_RAW_DATALAKE_BUCKET": storage_bq.datalake_bucket.name,
        "GCS_WATERMARK_PREFIX": "state/watermarks",
        "GCS_RAW_STAGING_PREFIX": "raw_staging",
        "BQ_DATASET_ID": storage_bq.dataset.dataset_id,
        "BQ_SANITIZED_TDS_TABLE": storage_bq.sanitized_reviews_tds.table_id,
        "BQ_PREDICTIONS_TABLE": storage_bq.delora_predictions.table_id,
        "BQ_WATERMARKS_LOG_TABLE": storage_bq.ingestion_watermarks_log.table_id,
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
            storage_bq.ingestion_watermarks_log,
            storage_bq.hitl_triage_audit_log,
        ],
    ]
    opts = pulumi.ResourceOptions(depends_on=deps)

    def service(
        name: str,
        image: str,
        account: pulumi.Output[str],
        env: dict[str, pulumi.Input[str]],
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
                "timeout": "900s",
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
            opts=opts,
        )

    ingestion = service(
        "voc-ingestion-worker",
        ingestion_worker_image,
        security.sa_ingestion_worker.email,
        {
            **common,
            "SCRAPER_PAGE_SIZE": "199",
            "SCRAPER_BASE_DELAY_SEC": "1.5",
            "SCRAPER_MAX_JITTER_SEC": "2.0",
            "SCRAPER_MAX_RETRIES": "5",
            "SCRAPER_TIMEOUT_SEC": "30.0",
            "SCRAPER_ROTATE_PROXY_EVERY_N_BATCHES": "5",
            "SCRAPER_PROXY_POOL_URLS": (
                scraper_proxy_pool_urls
                if scraper_proxy_pool_urls is not None
                else "[]"
            ),
        },
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
                        "image": sanitization_job_image,
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
                                "USER_HASH_SALT": user_hash_salt,
                                "BEAM_RUNNER": "DirectRunner",
                            }.items()
                        ],
                    }
                ],
            },
        },
        opts=opts,
    )
    backend = service(
        "voc-api-backend",
        api_backend_image,
        security.sa_ml_and_backend.email,
        common,
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
        repository,
        ingestion,
        sanitization,
        backend,
        ingestion_invoker,
        sanitization_invoker,
    )
