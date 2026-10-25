"""Ingesta diaria, sanitización y ML con autenticación de Scheduler."""

import base64

import pulumi
import pulumi_gcp as gcp
from voc_common import (
    PLAYSTORE_BANK_APPS,
    IngestionRequestPayload,
    SequentialBatchIngestionRequest,
)


def create_scheduler_jobs(
    region: str,
    worker_uri: pulumi.Output[str],
    sanitization_job_name: pulumi.Output[str],
    invoker_sa_email: pulumi.Output[str],
    free_tier_mode: bool = True,
    *,
    project_id: str | None = None,
    api_deps: list[pulumi.Resource] | None = None,
    ml_delta_job_name: pulumi.Output[str] | None = None,
    ml_monitor_job_name: pulumi.Output[str] | None = None,
    ml_topics_refit_job_name: pulumi.Output[str] | None = None,
) -> list[gcp.cloudscheduler.Job]:
    """Crea dos jobs en Free Tier; fuera de él cinco bancos y sanitización.

    Con los Jobs de ``ml-inference`` (EPIC-6) suma el delta diario, una hora
    después de la sanitización, el monitor de los lunes y el re-ajuste de
    tópicos el día 2 de cada trimestre (el Job decide si toca).

    Solo se invoca en la fase 2 (``deploy_workloads``): sin Cloud Run no hay
    destino que invocar y los crons fallarían en cada disparo.
    """
    project = project_id or pulumi.Config("gcp").require("project")
    opts = pulumi.ResourceOptions(depends_on=api_deps or [])
    jobs: list[gcp.cloudscheduler.Job] = []

    def ingest(name: str, schedule: str, path: str, payload: str) -> None:
        jobs.append(
            gcp.cloudscheduler.Job(
                name,
                name=name,
                project=project,
                region=region,
                schedule=schedule,
                time_zone="America/Mexico_City",
                attempt_deadline="900s",
                http_target={
                    "uri": pulumi.Output.concat(worker_uri, path),
                    "http_method": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "body": base64.b64encode(payload.encode()).decode(),
                    "oidc_token": {
                        "service_account_email": invoker_sa_email,
                        "audience": worker_uri,
                    },
                },
                opts=opts,
            )
        )

    if free_tier_mode:
        ingest(
            "voc-ingest-daily-sequential-all",
            "0 8 * * *",
            "/api/v1/ingest/all",
            SequentialBatchIngestionRequest().model_dump_json(),
        )
    else:
        for index, bank in enumerate(PLAYSTORE_BANK_APPS):
            minute = index * 15
            ingest(
                f"voc-ingest-daily-{bank.value.lower()}",
                f"{minute % 60} {8 + minute // 60} * * *",
                "/api/v1/ingest",
                IngestionRequestPayload(
                    bank_id=bank, max_reviews_per_run=2000
                ).model_dump_json(),
            )

    def run_job(name: str, schedule: str, job_name: pulumi.Output[str]) -> None:
        jobs.append(
            gcp.cloudscheduler.Job(
                name,
                name=name,
                project=project,
                region=region,
                schedule=schedule,
                time_zone="America/Mexico_City",
                http_target={
                    "uri": job_name.apply(
                        lambda value: (
                            f"https://run.googleapis.com/v2/projects/{project}"
                            f"/locations/{region}/jobs/"
                            f"{value.rsplit('/', 1)[-1]}:run"
                        )
                    ),
                    "http_method": "POST",
                    "body": base64.b64encode(b"{}").decode(),
                    "headers": {"Content-Type": "application/json"},
                    "oauth_token": {
                        "service_account_email": invoker_sa_email,
                        "scope": (
                            "https://www.googleapis.com/auth/cloud-platform"
                        ),
                    },
                },
                opts=opts,
            )
        )

    sanitization_hour = 8 if free_tier_mode else 9
    run_job(
        "voc-trigger-sanitization-daily",
        f"30 {sanitization_hour} * * *",
        sanitization_job_name,
    )
    if ml_delta_job_name is not None:
        run_job(
            "voc-trigger-ml-delta-daily",
            f"30 {sanitization_hour + 1} * * *",
            ml_delta_job_name,
        )
    if ml_monitor_job_name is not None:
        run_job(
            "voc-trigger-ml-monitor-weekly",
            f"30 {sanitization_hour + 2} * * 1",
            ml_monitor_job_name,
        )
    if ml_topics_refit_job_name is not None:
        run_job(
            "voc-trigger-ml-topics-refit-quarterly",
            f"30 {sanitization_hour + 3} 2 1,4,7,10 *",
            ml_topics_refit_job_name,
        )
    return jobs
