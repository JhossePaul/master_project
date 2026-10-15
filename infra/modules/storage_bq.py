"""Data Lake temporal y tablas TDS: nunca se crea una tabla de PII cruda."""

import json
from dataclasses import dataclass

import pulumi
import pulumi_gcp as gcp
from voc_common.config import IngestionStorageLayout


@dataclass
class StorageAndBqResources:
    datalake_bucket: gcp.storage.Bucket
    dataset: gcp.bigquery.Dataset
    sanitized_reviews_tds: gcp.bigquery.Table
    delora_predictions: gcp.bigquery.Table
    ingestion_runs_log: gcp.bigquery.Table
    hitl_triage_audit_log: gcp.bigquery.Table
    storage_layout: IngestionStorageLayout


def _schema(
    fields: tuple[tuple[str, str, str], ...],
) -> str:
    return json.dumps(
        [
            {"name": name, "type": kind, "mode": mode}
            for name, kind, mode in fields
        ]
    )


_SANITIZED = (
    ("id_resena", "STRING", "REQUIRED"),
    ("bank_id", "STRING", "REQUIRED"),
    ("app_id", "STRING", "REQUIRED"),
    ("usuario_hash", "STRING", "REQUIRED"),
    ("titulo", "STRING", "NULLABLE"),
    ("texto_sanitizado", "STRING", "REQUIRED"),
    ("texto_limpio", "STRING", "REQUIRED"),
    ("conteo_palabras", "INTEGER", "REQUIRED"),
    ("pii_findings_count", "INTEGER", "REQUIRED"),
    ("estrellas", "INTEGER", "REQUIRED"),
    ("votos_utilidad", "INTEGER", "REQUIRED"),
    ("version_app", "STRING", "REQUIRED"),
    ("fecha", "TIMESTAMP", "REQUIRED"),
    ("texto_respuesta_sanitizado", "STRING", "NULLABLE"),
    ("fecha_respuesta", "TIMESTAMP", "NULLABLE"),
    ("sanitized_at", "TIMESTAMP", "REQUIRED"),
)
_PREDICTIONS = (
    ("id_resena", "STRING", "REQUIRED"),
    ("bank_id", "STRING", "REQUIRED"),
    ("version_app", "STRING", "REQUIRED"),
    ("fecha", "TIMESTAMP", "REQUIRED"),
    ("estrellas", "INTEGER", "REQUIRED"),
    ("votos_utilidad", "INTEGER", "REQUIRED"),
    ("sentimiento_roberta", "STRING", "REQUIRED"),
    ("tnss_score", "STRING", "REQUIRED"),
    ("tnss_numeric_calibrated", "FLOAT", "REQUIRED"),
    ("is_obligatory_5_star_bias", "BOOLEAN", "REQUIRED"),
    ("topico", "STRING", "REQUIRED"),
    ("priority_weight_score", "FLOAT", "REQUIRED"),
    ("prediction_entropy", "FLOAT", "REQUIRED"),
    ("requires_hitl", "BOOLEAN", "REQUIRED"),
    ("embedding_vector", "FLOAT", "REPEATED"),
)
_INGESTION_RUNS = (
    ("audit_event_id", "STRING", "REQUIRED"),
    ("schema_version", "INTEGER", "REQUIRED"),
    ("bank_id", "STRING", "REQUIRED"),
    ("app_id", "STRING", "REQUIRED"),
    ("run_id", "STRING", "REQUIRED"),
    ("mode_executed", "STRING", "REQUIRED"),
    ("status", "STRING", "REQUIRED"),
    ("updated_at", "TIMESTAMP", "REQUIRED"),
    ("plan_id", "STRING", "NULLABLE"),
    ("stream_id", "STRING", "NULLABLE"),
    ("reason", "STRING", "NULLABLE"),
    ("state_revision", "INTEGER", "NULLABLE"),
    ("committed_high_at", "TIMESTAMP", "NULLABLE"),
    ("observed_min_at", "TIMESTAMP", "NULLABLE"),
    ("observed_max_at", "TIMESTAMP", "NULLABLE"),
    ("pages_committed", "INTEGER", "NULLABLE"),
    ("reviews_extracted", "INTEGER", "NULLABLE"),
    ("reviews_published", "INTEGER", "NULLABLE"),
    ("reviews_discarded", "INTEGER", "NULLABLE"),
    ("recovery_requests", "INTEGER", "NULLABLE"),
)
_AUDIT = (
    ("audit_id", "STRING", "REQUIRED"),
    ("id_resena", "STRING", "REQUIRED"),
    ("bank_id", "STRING", "REQUIRED"),
    ("original_tnss", "STRING", "REQUIRED"),
    ("validated_tnss", "STRING", "REQUIRED"),
    ("original_topic", "STRING", "REQUIRED"),
    ("validated_topic", "STRING", "REQUIRED"),
    ("reviewer_email_hash", "STRING", "REQUIRED"),
    ("backlog_jira_ticket", "STRING", "NULLABLE"),
    ("reviewed_at", "TIMESTAMP", "REQUIRED"),
)


def create_storage_and_bq_resources(
    project_id: str,
    region: str,
    kms_key_id: pulumi.Output[str] | None,
    api_deps: list[pulumi.Resource],
    *,
    environment: str = "dev",
    storage_layout: IngestionStorageLayout | None = None,
) -> StorageAndBqResources:
    """Aprovisiona staging con caducidad y cuatro tablas curadas/auditoría."""
    layout = storage_layout or IngestionStorageLayout()
    is_dev = environment.strip().lower() == "dev"
    bucket_deps = list(api_deps)
    bq_deps = list(api_deps)
    if kms_key_id is not None:
        invoke_opts = pulumi.InvokeOutputOptions(depends_on=api_deps)
        storage_agent = gcp.storage.get_project_service_account_output(
            project=project_id, opts=invoke_opts
        )
        bq_agent = gcp.bigquery.get_default_service_account_output(
            project=project_id, opts=invoke_opts
        )
        for name, email, deps in (
            ("storage", storage_agent.email_address, bucket_deps),
            ("bigquery", bq_agent.email, bq_deps),
        ):
            grant = gcp.kms.CryptoKeyIAMMember(
                f"voc-{name}-cmek-access",
                crypto_key_id=kms_key_id,
                role="roles/cloudkms.cryptoKeyEncrypterDecrypter",
                member=email.apply(lambda value: f"serviceAccount:{value}"),
                opts=pulumi.ResourceOptions(depends_on=api_deps),
            )
            deps.append(grant)
    bucket = gcp.storage.Bucket(
        "voc-datalake",
        name=f"voc-datalake-{project_id}",
        project=project_id,
        location=region,
        uniform_bucket_level_access=True,
        soft_delete_policy={"retention_duration_seconds": 0},
        force_destroy=is_dev,
        encryption=(
            {"default_kms_key_name": kms_key_id}
            if kms_key_id is not None
            else None
        ),
        lifecycle_rules=[
            {
                "action": {"type": "Delete"},
                "condition": {
                    "age": 7,
                    "matches_prefixes": [
                        layout.gcs_raw_staging_prefix + "/",
                        "temp_beam/",
                    ],
                },
            }
        ],
        opts=pulumi.ResourceOptions(depends_on=bucket_deps),
    )
    dataset = gcp.bigquery.Dataset(
        "bbva-voc-tds",
        project=project_id,
        dataset_id="bbva_voc_tds",
        location=region,
        delete_contents_on_destroy=is_dev,
        default_encryption_configuration=(
            {"kms_key_name": kms_key_id} if kms_key_id is not None else None
        ),
        opts=pulumi.ResourceOptions(depends_on=bq_deps),
    )

    def table(
        name: str,
        fields: tuple[tuple[str, str, str], ...],
        clustering: list[str] | None = None,
        partition_field: str | None = None,
    ) -> gcp.bigquery.Table:
        return gcp.bigquery.Table(
            name,
            project=project_id,
            dataset_id=dataset.dataset_id,
            table_id=name,
            schema=_schema(fields),
            deletion_protection=not is_dev,
            time_partitioning=(
                {"type": "DAY", "field": partition_field}
                if partition_field
                else None
            ),
            clusterings=clustering,
            encryption_configuration=(
                {"kms_key_name": kms_key_id} if kms_key_id is not None else None
            ),
            opts=pulumi.ResourceOptions(depends_on=[dataset, *bq_deps]),
        )

    return StorageAndBqResources(
        bucket,
        dataset,
        table(
            "sanitized_reviews_tds",
            _SANITIZED,
            ["bank_id", "version_app"],
            "fecha",
        ),
        table(
            "delora_predictions",
            _PREDICTIONS,
            ["bank_id", "topico", "tnss_score"],
            "fecha",
        ),
        table(
            "ingestion_runs_log_v2",
            _INGESTION_RUNS,
            ["bank_id", "run_id", "status"],
            "updated_at",
        ),
        table("hitl_triage_audit_log", _AUDIT),
        layout,
    )
