"""Feature 2.9: Job privado, perfiles y permisos para overrides."""

import json
import runpy
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pulumi
import pytest
from pydantic import ValidationError
from voc_common import IngestionExecutionConfig, Settings

from infra.modules.cloud_run import (
    HistoricalExecutionConfig,
    HistoricalJobConfig,
)
from infra.tests.conftest import (
    INGESTION_IMAGE,
    WORKLOAD_CONFIG,
    InfrastructureMonitor,
    digest_image,
    unwrap_outputs,
)

HISTORY_IMAGE = digest_image("ingestion-history", "d")

ENTRYPOINT = Path(__file__).resolve().parents[1] / "__main__.py"


@pytest.mark.parametrize("free_tier", [False, True])
@pytest.mark.parametrize("custom", [False, True])
def test_historical_job_profiles_access_and_scheduler(
    pulumi_mocks: InfrastructureMonitor,
    free_tier: bool,
    custom: bool,
) -> None:
    exported: dict[str, Any] = {}
    export = pulumi.export

    def capture(name: str, value: Any) -> None:
        exported[name] = value
        export(name, value)

    profile = (
        HistoricalJobConfig()
        if not custom
        else HistoricalJobConfig(
            command=("custom-entrypoint",),
            max_retries=2,
            execution=HistoricalExecutionConfig(
                ingestion_max_runtime_sec=1680,
                ingestion_container_timeout_sec=1800,
                ingestion_checkpoint_margin_sec=120,
                ingestion_max_requests=200,
            ),
        )
    )

    @pulumi.runtime.test
    def deploy() -> None:
        config = {
            "gcp:project": "test-voc-project",
            "gcp:region": "us-east1",
            **WORKLOAD_CONFIG,
            "bbva-voc-infra:free_tier_mode": str(free_tier).lower(),
            "bbva-voc-infra:ingestion_v2_enabled": str(custom).lower(),
        }
        if custom:
            config.update(
                {
                    "bbva-voc-infra:historical_ingestion": (
                        profile.model_dump_json()
                    ),
                    "bbva-voc-infra:historical_job_image": HISTORY_IMAGE,
                    "bbva-voc-infra:ingestion_execution": json.dumps(
                        {
                            "ingestion_max_requests": 50,
                            "ingestion_container_timeout_sec": 1000,
                        }
                    ),
                }
            )
        pulumi.runtime.set_all_config(config)
        with patch("pulumi.export", side_effect=capture):
            runpy.run_path(str(ENTRYPOINT))

    deploy()
    registered = list(pulumi_mocks.resources.values())
    by_name = {r.urn.rsplit("::", 1)[-1]: r for r in registered}
    states = {name: unwrap_outputs(r.state) for name, r in by_name.items()}
    historical = states["voc-ingestion-history-job"]
    task = historical["template"]["template"]
    assert historical["location"] == "us-east1"
    assert historical["template"]["taskCount"] == 1
    assert historical["template"]["parallelism"] == 1
    assert task["serviceAccount"] == (
        "voc-sa-ingestion@test-voc-project.iam.gserviceaccount.com"
    )
    assert (
        task["timeout"]
        == f"{profile.execution.ingestion_container_timeout_sec}s"
    )
    assert task["maxRetries"] == profile.max_retries
    container = task["containers"][0]
    assert container["commands"] == list(profile.command)
    assert container["image"] == (HISTORY_IMAGE if custom else INGESTION_IMAGE)
    assert container["name"] == "historical-ingestion"
    job_env = {v["name"]: v.get("value") for v in container["envs"]}
    for name, value in profile.execution.model_dump().items():
        assert job_env[name.upper()] == str(value)
    assert job_env["SCRAPER_PAGE_SIZE"] == "199"
    assert job_env["BQ_INGESTION_RUNS_LOG_TABLE"] == "ingestion_runs_log_v2"
    assert job_env["GCS_INGESTION_LEDGERS_PREFIX"] == "state/ingestion/ledgers"
    assert not {
        "INGESTION_PLAN_ID",
        "INGESTION_STREAM_ID",
        "WATERMARK_STATE",
    } & set(job_env)
    access = states["voc-history-ingestion-executor"]
    assert access["name"] == historical["name"]
    assert access["role"] == "roles/run.jobsExecutorWithOverrides"
    assert access["member"] == "serviceAccount:" + task["serviceAccount"]
    assert access["location"] == "us-east1"
    grants = [r.state for r in registered if "member" in r.state]
    assert all(
        g["member"] not in ("allUsers", "allAuthenticatedUsers") for g in grants
    )
    scheduler = (
        "serviceAccount:voc-sa-scheduler@"
        "test-voc-project.iam.gserviceaccount.com"
    )
    scheduler_grants = [g for g in grants if g["member"] == scheduler]
    assert len(scheduler_grants) == 2
    assert all(g["name"] != historical["name"] for g in scheduler_grants)
    assert not any(
        "project" in g and g.get("name") is None for g in scheduler_grants
    )
    worker = states["voc-ingestion-worker"]["template"]
    worker_env = {
        v["name"]: v.get("value") for v in worker["containers"][0]["envs"]
    }
    assert worker_env["INGESTION_HISTORY_JOB_NAME"] == (
        "projects/test-voc-project/locations/us-east1/jobs/voc-ingestion-history-job"
    )
    assert worker["timeout"] == ("1000s" if custom else "900s")
    assert worker_env["INGESTION_CONTAINER_TIMEOUT_SEC"] == (
        "1000" if custom else "900"
    )
    assert worker_env["INGESTION_MAX_REQUESTS"] == ("50" if custom else "100")
    assert worker_env["INGESTION_V2_ENABLED"] == str(custom).lower()
    assert job_env["INGESTION_V2_ENABLED"] == worker_env["INGESTION_V2_ENABLED"]
    sanitization = states["voc-sanitization-job"]["template"]["template"]
    sanitization_env = {
        v["name"]: v.get("value") for v in sanitization["containers"][0]["envs"]
    }
    assert (
        sanitization_env["INGESTION_V2_ENABLED"]
        == worker_env["INGESTION_V2_ENABLED"]
    )
    assert {
        "ingestion_history_job_id",
        "ingestion_history_job_name",
        "ingestion_history_job_region",
    } <= set(exported)
    assert exported["ingestion_history_job_region"] == "us-east1"
    for name in ("voc-ingestion-history-job", "voc-history-ingestion-executor"):
        assert (
            by_name[name].urn
            in pulumi_mocks.dependencies["voc-ingestion-worker"]
        )
    schedules = {n for n, s in states.items() if "schedule" in s}
    assert len(schedules) == (2 if free_tier else 6)
    assert all("history" not in n for n in schedules)
    # Comparar el perfil común con Settings sin depender de .env del equipo.
    for key, field in IngestionExecutionConfig.model_fields.items():
        assert field.default == Settings.model_fields[key].default


@pytest.mark.parametrize(
    "changes",
    [
        {"command": []},
        {"command": [""]},
        {"max_retries": -1},
        {"max_retries": 11},
        {"execution": {"scraper_page_size": 500}},
        {"execution": {"ingestion_max_runtime_sec": 3600}},
        {"execution": {"ingestion_heartbeat_interval_sec": 120}},
    ],
)
def test_invalid_job_configuration_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        HistoricalJobConfig.model_validate(changes)


@pytest.mark.parametrize(
    "key,profile",
    [
        ("ingestion_execution", {"ingestion_container_timeout_sec": 3601}),
        (
            "historical_ingestion",
            {"execution": {"ingestion_container_timeout_sec": 604801}},
        ),
    ],
)
def test_provider_timeout_limits_rejected(
    pulumi_mocks: InfrastructureMonitor,
    key: str,
    profile: dict[str, Any],
) -> None:
    @pulumi.runtime.test
    def deploy() -> None:
        pulumi.runtime.set_all_config(
            {
                "gcp:project": "test-voc-project",
                f"bbva-voc-infra:{key}": json.dumps(profile),
            }
        )
        with pytest.raises(ValueError, match="timeout cannot exceed"):
            runpy.run_path(str(ENTRYPOINT))

    deploy()
    assert not any(
        "gcp:cloudrunv2/" in r.urn for r in pulumi_mocks.resources.values()
    )


def test_partial_historical_profile_keeps_historical_defaults() -> None:
    config = HistoricalJobConfig.model_validate(
        {
            "execution": {"ingestion_max_requests": 17},
        }
    )
    assert config.execution.ingestion_max_requests == 17
    assert config.execution.ingestion_max_runtime_sec == 3480
    assert config.execution.ingestion_container_timeout_sec == 3600
