"""Entrada Pulumi: datos, cómputo y orquestación (Features 2.1–2.5)."""

import json

import pulumi
from voc_common.config import DEV_USER_HASH_SALT

from infra.modules.apis import enable_project_apis
from infra.modules.cloud_run import create_cloud_run_resources
from infra.modules.cloud_scheduler import create_scheduler_jobs
from infra.modules.dlp import create_dlp_templates
from infra.modules.kms_iam import create_security_resources
from infra.modules.pubsub import create_pubsub_resources
from infra.modules.storage_bq import create_storage_and_bq_resources
from infra.modules.vertex_ai import create_vertex_resources

gcp_config = pulumi.Config("gcp")
config = pulumi.Config("bbva-voc-infra")
project_id = gcp_config.require("project")
region = gcp_config.get("region") or "us-central1"
enable_cmek = config.get_bool("enable_cmek") or False
enable_vertex = config.get_bool("enable_dedicated_vertex_endpoints") or False
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

project_apis = enable_project_apis(
    project_id, enable_cmek=enable_cmek, enable_vertex=enable_vertex
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
)
storage_bq = create_storage_and_bq_resources(
    project_id,
    region,
    security.kms_crypto_key_id,
    list(project_apis.values()),
    environment=environment,
)
image_prefix = f"{region}-docker.pkg.dev/{project_id}/voc-containers-repo"
cloud_run = create_cloud_run_resources(
    project_id,
    region,
    security,
    pubsub,
    storage_bq,
    dlp_templates,
    list(project_apis.values()),
    ingestion_worker_image=(
        config.get("ingestion_worker_image")
        or f"{image_prefix}/ingestion-worker:latest"
    ),
    sanitization_job_image=(
        config.get("sanitization_job_image")
        or f"{image_prefix}/sanitization-pipeline:latest"
    ),
    api_backend_image=(
        config.get("api_backend_image") or f"{image_prefix}/api-backend:latest"
    ),
    user_hash_salt=user_hash_salt,
    environment=environment,
    free_tier_mode=free_tier,
    enable_vertex=enable_vertex,
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
    ],
)
vertex = create_vertex_resources(
    project_id,
    region,
    storage_bq.datalake_bucket.name,
    enable_vertex,
    api_deps=list(project_apis.values()),
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
pulumi.export("dlp_inspect_template_id", dlp_templates.inspect_template.id)
pulumi.export(
    "dlp_deidentify_template_id", dlp_templates.deidentify_template.id
)
pulumi.export("gcs_raw_datalake_bucket", storage_bq.datalake_bucket.name)
pulumi.export("bq_dataset_id", storage_bq.dataset.dataset_id)
pulumi.export("pubsub_raw_reviews_topic", pubsub.raw_topic.id)
pulumi.export("pubsub_raw_subscription", pubsub.raw_subscription.id)
pulumi.export("pubsub_alerts_topic", pubsub.alerts_topic.id)
pulumi.export("pubsub_dlq_topic", pubsub.dlq_topic.id)
pulumi.export("pubsub_dlq_subscription", pubsub.dlq_subscription.id)
pulumi.export("pubsub_alerts_subscription", pubsub.alerts_subscription.id)
pulumi.export(
    "bq_sanitized_tds_table", storage_bq.sanitized_reviews_tds.table_id
)
pulumi.export("bq_predictions_table", storage_bq.delora_predictions.table_id)
pulumi.export(
    "bq_watermarks_log_table", storage_bq.ingestion_watermarks_log.table_id
)
pulumi.export("bq_hitl_audit_table", storage_bq.hitl_triage_audit_log.table_id)
pulumi.export("artifact_registry_id", cloud_run.repository.id)
pulumi.export("ingestion_worker_uri", cloud_run.ingestion_worker.uri)
pulumi.export("api_backend_uri", cloud_run.api_backend.uri)
pulumi.export("sanitization_job_id", cloud_run.sanitization_job.id)
pulumi.export("scheduler_job_ids", [job.id for job in scheduler_jobs])
pulumi.export(
    "vertex_endpoint_id", vertex.endpoint.id if vertex.endpoint else None
)
pulumi.export("vertex_index_id", vertex.index.id if vertex.index else None)
