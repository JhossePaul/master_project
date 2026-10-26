"""Identidades dedicadas y cifrado CMEK opcional para los servicios de VoC."""

from dataclasses import dataclass, field

import pulumi
import pulumi_gcp as gcp


@dataclass
class SecurityResources:
    sa_ingestion_worker: gcp.serviceaccount.Account
    sa_scheduler_invoker: gcp.serviceaccount.Account
    sa_sanitization_worker: gcp.serviceaccount.Account
    sa_ml_and_backend: gcp.serviceaccount.Account
    sa_portal_api: gcp.serviceaccount.Account
    sa_ml_online: gcp.serviceaccount.Account
    kms_crypto_key_id: pulumi.Output[str] | None
    iam_members: list[gcp.projects.IAMMember] = field(default_factory=list)


def create_security_resources(
    project_id: str,
    region: str,
    enable_cmek: bool,
    api_deps: list[pulumi.Resource],
) -> SecurityResources:
    """Crea cuentas, permisos aditivos y CMEK condicional."""
    opts = pulumi.ResourceOptions(depends_on=api_deps)
    iam_members: list[gcp.projects.IAMMember] = []

    def create_account(
        account_id: str, roles: tuple[str, ...]
    ) -> gcp.serviceaccount.Account:
        account = gcp.serviceaccount.Account(
            account_id,
            project=project_id,
            account_id=account_id,
            display_name=account_id,
            opts=opts,
        )
        member = account.email.apply(lambda email: f"serviceAccount:{email}")
        for role in roles:
            grant = gcp.projects.IAMMember(
                f"{account_id}-{role.removeprefix('roles/').replace('.', '-')}",
                project=project_id,
                role=role,
                member=member,
                opts=opts,
            )
            iam_members.append(grant)
        return account

    ingestion = create_account(
        "voc-sa-ingestion",
        (
            "roles/pubsub.publisher",
            "roles/bigquery.dataEditor",
        ),
    )
    scheduler = create_account("voc-sa-scheduler", ())
    sanitization = create_account(
        "voc-sa-sanitization",
        (
            "roles/pubsub.subscriber",
            "roles/pubsub.viewer",
            "roles/dlp.user",
            "roles/bigquery.dataEditor",
            "roles/bigquery.jobUser",
        ),
    )
    ml_backend = create_account(
        "voc-sa-ml-backend",
        (
            "roles/bigquery.dataEditor",
            "roles/bigquery.jobUser",
            # Publica solo en los tópicos de avisos (permiso por tópico).
            "roles/aiplatform.user",
            "roles/dlp.user",
        ),
    )

    # API y portal (EPIC-7): lee el dataset y escribe solo en las tablas de
    # curaduría y HITL (permisos por tabla en analytics_bq).
    portal_api = create_account(
        "voc-sa-portal-api",
        (
            "roles/bigquery.jobUser",
            "roles/dlp.user",
        ),
    )

    # Servicio privado de explicación y embeddings (EPIC-7): lee pesos de
    # ml_artifacts/ (permiso condicional en el bucket) y model_versions
    # (permiso por tabla en analytics_bq); no escribe nada.
    ml_online = create_account("voc-sa-ml-online", ("roles/bigquery.jobUser",))

    kms_crypto_key_id: pulumi.Output[str] | None = None
    if enable_cmek:
        keyring = gcp.kms.KeyRing(
            "voc-keyring",
            name="voc-kms-keyring",
            project=project_id,
            location=region,
            opts=opts,
        )
        crypto_key = gcp.kms.CryptoKey(
            "voc-cmek-key",
            key_ring=keyring.id,
            purpose="ENCRYPT_DECRYPT",
            rotation_period="7776000s",
            version_template=gcp.kms.CryptoKeyVersionTemplateArgs(
                algorithm="GOOGLE_SYMMETRIC_ENCRYPTION",
                protection_level="SOFTWARE",
            ),
            opts=opts,
        )
        kms_crypto_key_id = crypto_key.id

    return SecurityResources(
        sa_ingestion_worker=ingestion,
        sa_scheduler_invoker=scheduler,
        sa_sanitization_worker=sanitization,
        sa_ml_and_backend=ml_backend,
        sa_portal_api=portal_api,
        sa_ml_online=ml_online,
        kms_crypto_key_id=kms_crypto_key_id,
        iam_members=iam_members,
    )


def create_datalake_access(
    bucket: gcp.storage.Bucket,
    security: SecurityResources,
    api_deps: list[pulumi.Resource],
) -> list[gcp.storage.BucketIAMMember]:
    """Grants aditivos de objetos solo en el bucket, sin administrar su IAM.

    ``voc-sa-ml-backend`` lee los pesos de ``ml_artifacts/`` y escribe las
    exportaciones de ``backfill/`` (EPIC-6, 6.2).
    """
    grants = []
    for label, account in (
        ("ingestion", security.sa_ingestion_worker),
        ("sanitization", security.sa_sanitization_worker),
        ("ml-backend", security.sa_ml_and_backend),
    ):
        grants.append(
            gcp.storage.BucketIAMMember(
                f"voc-datalake-{label}-objects",
                bucket=bucket.name,
                role="roles/storage.objectUser",
                member=account.email.apply(
                    lambda email: f"serviceAccount:{email}"
                ),
                opts=pulumi.ResourceOptions(depends_on=[bucket, *api_deps]),
            )
        )
    grants.append(
        gcp.storage.BucketIAMMember(
            "voc-datalake-ml-online-artifacts",
            bucket=bucket.name,
            role="roles/storage.objectViewer",
            member=security.sa_ml_online.email.apply(
                lambda email: f"serviceAccount:{email}"
            ),
            # Solo los pesos. Listar un prefijo se evalúa contra el bucket,
            # por eso la condición también admite ese tipo de recurso.
            condition=gcp.storage.BucketIAMMemberConditionArgs(
                title="solo-ml-artifacts",
                expression=bucket.name.apply(
                    lambda name: (
                        'resource.type == "storage.googleapis.com/Bucket" || '
                        "resource.name.startsWith("
                        f'"projects/_/buckets/{name}/objects/ml_artifacts/")'
                    )
                ),
            ),
            opts=pulumi.ResourceOptions(depends_on=[bucket, *api_deps]),
        )
    )
    return grants


def create_historical_job_access(
    job: gcp.cloudrunv2.Job,
    launcher: gcp.serviceaccount.Account,
    project_id: str,
    region: str,
) -> gcp.cloudrunv2.JobIamMember:
    """Permite a la API de ingesta ejecutar solo este Job con overrides."""
    return gcp.cloudrunv2.JobIamMember(
        "voc-history-ingestion-executor",
        project=project_id,
        location=region,
        name=job.name,
        role="roles/run.jobsExecutorWithOverrides",
        member=launcher.email.apply(lambda email: f"serviceAccount:{email}"),
        opts=pulumi.ResourceOptions(depends_on=[job, launcher]),
    )
