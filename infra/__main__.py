"""Entrada Pulumi: datos, cómputo y orquestación (EPIC-2 y EPIC-6, 6.2)."""

import json

import pulumi
from voc_common.config import (
    DEV_USER_HASH_SALT,
    IngestionExecutionConfig,
    IngestionStorageLayout,
)

from infra.modules.alerting import create_alerting_resources
from infra.modules.analytics_bq import create_analytics_bq
from infra.modules.apis import enable_project_apis
from infra.modules.cloud_run import (
    ARTIFACT_REPOSITORY_ID,
    HistoricalJobConfig,
    WorkloadImages,
    create_artifact_registry,
    create_cloud_run_resources,
    validate_execution_profiles,
)
from infra.modules.cloud_scheduler import create_scheduler_jobs
from infra.modules.dlp import create_dlp_templates
from infra.modules.kms_iam import (
    create_datalake_access,
    create_security_resources,
)
from infra.modules.pubsub import create_pubsub_resources
from infra.modules.secrets import create_secrets
from infra.modules.storage_bq import create_storage_and_bq_resources

gcp_config = pulumi.Config("gcp")
config = pulumi.Config("bbva-voc-infra")
project_id = gcp_config.require("project")
region = gcp_config.get("region") or "us-central1"
enable_cmek = config.get_bool("enable_cmek") or False
# Solo la API de Vertex AI (Gemini y Model Registry), sin endpoints dedicados.
enable_vertex_ai_api = config.get_bool("enable_vertex_ai_api") or False
free_tier = config.get_bool("free_tier_mode")
free_tier = True if free_tier is None else free_tier
environment = config.get("environment") or pulumi.get_stack()
user_hash_salt = config.get_secret("user_hash_salt")
if user_hash_salt is None:
    if environment.strip().lower() in {"prod", "production"}:
        user_hash_salt = config.require_secret("user_hash_salt")
    else:
        user_hash_salt = pulumi.Output.secret(DEV_USER_HASH_SALT)
proxies = config.get_secret_object("scraper_proxy_pool_urls")
# Destino de los avisos de deriva y de calidad; sin él no hay correo.
# Secreto (cifrado con la llave del stack): el repositorio es público.
alert_email = config.get_secret("alert_email")
# Fase 1 (false): base sin Cloud Run ni Scheduler hasta publicar imágenes.
deploy_workloads = config.get_bool("deploy_workloads") or False
# Leer solo Pulumi: los prefijos no dependen de .env ni variables del host.
storage_layout = IngestionStorageLayout.model_validate(
    {
        name: value
        for name in IngestionStorageLayout.model_fields
        if (value := config.get(name)) is not None
    }
)

project_apis = enable_project_apis(
    project_id,
    enable_cmek=enable_cmek,
    enable_vertex_ai_api=enable_vertex_ai_api,
)
security = create_security_resources(
    project_id,
    region,
    enable_cmek=enable_cmek,
    api_deps=list(project_apis.values()),
)
dlp_templates = create_dlp_templates(
    project_id, region, api_deps=list(project_apis.values())
)
pubsub = create_pubsub_resources(
    security.kms_crypto_key_id,
    list(project_apis.values()),
    project_id=project_id,
    alert_publisher_email=security.sa_ml_and_backend.email,
)
# Fase 1: el autor carga el valor antes de desplegar voc-ml-rescoring.
secrets = create_secrets(
    project_id, security.sa_ml_and_backend, list(project_apis.values())
)
alerting = (
    create_alerting_resources(
        project_id, alert_email, list(project_apis.values())
    )
    if alert_email is not None
    else None
)
storage_bq = create_storage_and_bq_resources(
    project_id,
    region,
    security.kms_crypto_key_id,
    list(project_apis.values()),
    environment=environment,
    storage_layout=storage_layout,
)
analytics_bq = create_analytics_bq(
    project_id,
    storage_bq.dataset,
    security.kms_crypto_key_id,
    is_dev=environment.strip().lower() == "dev",
    deps=storage_bq.bq_deps,
)
storage_access = create_datalake_access(
    storage_bq.datalake_bucket,
    security,
    list(project_apis.values()),
)
repository = create_artifact_registry(
    project_id, region, list(project_apis.values())
)
ingestion_execution = IngestionExecutionConfig.model_validate(
    config.get_object("ingestion_execution") or {}
)
historical_config = HistoricalJobConfig.model_validate(
    config.get_object("historical_ingestion") or {}
)
validate_execution_profiles(ingestion_execution, historical_config)
cloud_run = None
scheduler_jobs = []
if deploy_workloads:
    images = WorkloadImages.model_validate(
        {
            "ingestion_worker": config.require("ingestion_worker_image"),
            "sanitization_job": config.require("sanitization_job_image"),
            "api_backend": config.get("api_backend_image"),
            "historical_job": config.get("historical_job_image"),
            "ml_inference": config.get("ml_inference_image"),
        }
    )
    cloud_run = create_cloud_run_resources(
        project_id,
        region,
        security,
        pubsub,
        storage_bq,
        dlp_templates,
        [*project_apis.values(), *storage_access],
        repository=repository,
        images=images,
        ingestion_execution=ingestion_execution,
        historical_config=historical_config,
        ingestion_v2_enabled=config.get_bool("ingestion_v2_enabled") or False,
        secrets=secrets,
        user_hash_salt=user_hash_salt,
        environment=environment,
        free_tier_mode=free_tier,
        scraper_proxy_pool_urls=proxies.apply(json.dumps)
        if proxies is not None
        else None,
    )
    scheduler_jobs = create_scheduler_jobs(
        region,
        cloud_run.ingestion_worker.uri,
        cloud_run.sanitization_job.name,
        security.sa_scheduler_invoker.email,
        free_tier_mode=free_tier,
        project_id=project_id,
        api_deps=[
            *project_apis.values(),
            cloud_run.ingestion_invoker,
            cloud_run.sanitization_invoker,
            *cloud_run.ml_invokers,
        ],
        ml_delta_job_name=(
            cloud_run.ml_delta_job.name if cloud_run.ml_delta_job else None
        ),
        ml_monitor_job_name=(
            cloud_run.ml_monitor_job.name if cloud_run.ml_monitor_job else None
        ),
    )

pulumi.export("project_id", project_id)
pulumi.export("enabled_apis", sorted(project_apis))
pulumi.export("sa_ingestion_worker_email", security.sa_ingestion_worker.email)
pulumi.export("sa_scheduler_invoker_email", security.sa_scheduler_invoker.email)
pulumi.export(
    "sa_sanitization_worker_email", security.sa_sanitization_worker.email
)
pulumi.export("sa_ml_and_backend_email", security.sa_ml_and_backend.email)
pulumi.export("kms_crypto_key_id", security.kms_crypto_key_id)
pulumi.export("kaggle_secret_id", secrets.kaggle_token.secret_id)
pulumi.export("dlp_inspect_template_id", dlp_templates.inspect_template.id)
pulumi.export(
    "dlp_deidentify_template_id", dlp_templates.deidentify_template.id
)
pulumi.export("gcs_raw_datalake_bucket", storage_bq.datalake_bucket.name)
for prefix_name, prefix_value in storage_layout.model_dump().items():
    pulumi.export(prefix_name, prefix_value)
pulumi.export("bq_dataset_id", storage_bq.dataset.dataset_id)
pulumi.export("pubsub_raw_reviews_topic", pubsub.raw_topic.id)
pulumi.export("pubsub_raw_subscription", pubsub.raw_subscription.id)
pulumi.export("pubsub_alerts_topic", pubsub.alerts_topic.id)
pulumi.export("pubsub_dlq_topic", pubsub.dlq_topic.id)
pulumi.export("pubsub_dlq_subscription", pubsub.dlq_subscription.id)
pulumi.export("pubsub_alerts_subscription", pubsub.alerts_subscription.id)
pulumi.export("pubsub_model_quality_topic", pubsub.quality_topic.id)
pulumi.export(
    "pubsub_model_quality_subscription", pubsub.quality_subscription.id
)
if alerting is not None:
    pulumi.export("alert_notification_channel", alerting.channel.name)
pulumi.export(
    "bq_sanitized_tds_table", storage_bq.sanitized_reviews_tds.table_id
)
pulumi.export(
    "bq_ingestion_runs_log_table", storage_bq.ingestion_runs_log.table_id
)
pulumi.export(
    "bq_analytics_tables",
    {name: table.table_id for name, table in analytics_bq.tables.items()},
)
pulumi.export(
    "bq_analytics_views",
    {name: view.table_id for name, view in analytics_bq.views.items()},
)
pulumi.export("deploy_workloads", deploy_workloads)
pulumi.export("artifact_registry_id", repository.id)
pulumi.export(
    "artifact_registry_url",
    f"{region}-docker.pkg.dev/{project_id}/{ARTIFACT_REPOSITORY_ID}",
)
if cloud_run is not None:
    pulumi.export("ingestion_worker_uri", cloud_run.ingestion_worker.uri)
    if cloud_run.api_backend is not None:
        pulumi.export("api_backend_uri", cloud_run.api_backend.uri)
    pulumi.export("sanitization_job_id", cloud_run.sanitization_job.id)
    pulumi.export("ingestion_history_job_id", cloud_run.historical_job.id)
    pulumi.export("ingestion_history_job_name", cloud_run.historical_job_name)
    pulumi.export("ingestion_history_job_region", region)
    if cloud_run.ml_delta_job is not None:
        pulumi.export("ml_delta_job_id", cloud_run.ml_delta_job.id)
    if cloud_run.ml_monitor_job is not None:
        pulumi.export("ml_monitor_job_id", cloud_run.ml_monitor_job.id)
    if cloud_run.ml_rescoring_job is not None:
        pulumi.export("ml_rescoring_job_id", cloud_run.ml_rescoring_job.id)
pulumi.export("scheduler_job_ids", [job.id for job in scheduler_jobs])
