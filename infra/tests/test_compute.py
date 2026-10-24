"""Cómputo privado, payloads compatibles y horarios según modo operativo."""

import base64
import json
import runpy
from pathlib import Path
from typing import Any

import pulumi
import pytest
from voc_common import (
    BankKey,
    IngestionRequestPayload,
    SequentialBatchIngestionRequest,
)
from voc_common.config import DEV_USER_HASH_SALT

from infra.modules.cloud_run import _validate_hash_salt
from infra.tests.conftest import (
    API_BACKEND_IMAGE,
    INGESTION_IMAGE,
    ML_INFERENCE_IMAGE,
    SANITIZATION_IMAGE,
    WORKLOAD_CONFIG,
    InfrastructureMonitor,
)
from infra.tests.conftest import (
    unwrap_outputs as _unwrap,
)


@pytest.mark.parametrize("free_tier", [True, False])
@pytest.mark.parametrize("ml", [False, True])
def test_compute_and_scheduler_modes(
    pulumi_mocks: InfrastructureMonitor, free_tier: bool, ml: bool
) -> None:
    ml_config = (
        {"bbva-voc-infra:ml_inference_image": ML_INFERENCE_IMAGE} if ml else {}
    )

    @pulumi.runtime.test
    def deploy() -> None:
        pulumi.runtime.set_all_config(
            {
                "gcp:project": "test-voc-project",
                "gcp:region": "us-central1",
                "bbva-voc-infra:free_tier_mode": str(free_tier).lower(),
                # Flag retirado (P8-6): no crea el índice de 768 ni endpoints.
                "bbva-voc-infra:enable_dedicated_vertex_endpoints": "true",
                **WORKLOAD_CONFIG,
                **ml_config,
                "bbva-voc-infra:scraper_proxy_pool_urls": '["http://proxy:8080"]',
                "bbva-voc-infra:user_hash_salt": "test-salt-1234567890",
            },
            secret_keys=[
                "bbva-voc-infra:user_hash_salt",
                "bbva-voc-infra:scraper_proxy_pool_urls",
            ],
        )
        runpy.run_path(str(Path(__file__).resolve().parents[1] / "__main__.py"))

    deploy()
    registrations = list(pulumi_mocks.resources.values())
    by_name = {r.urn.rsplit("::", 1)[-1]: r for r in registrations}
    states = {name: _unwrap(r.state) for name, r in by_name.items()}
    for name, account, image in (
        ("voc-ingestion-worker", "voc-sa-ingestion", INGESTION_IMAGE),
        ("voc-api-backend", "voc-sa-ml-backend", API_BACKEND_IMAGE),
    ):
        # Valor por defecto de la API declarado para evitar deriva en preview.
        assert states[name]["scaling"] == {"minInstanceCount": 0}
        template = states[name]["template"]
        assert template["executionEnvironment"] == "EXECUTION_ENVIRONMENT_GEN2"
        assert template["scaling"] == {
            "minInstanceCount": 0,
            "maxInstanceCount": 2,
        }
        assert (
            template["serviceAccount"]
            == f"{account}@test-voc-project.iam.gserviceaccount.com"
        )
        assert template["timeout"] == "900s"
        container = template["containers"][0]
        assert container["image"] == image
        assert container["resources"]["limits"] == {"cpu": "1", "memory": "1Gi"}
        assert container["resources"]["cpuIdle"] is True
    worker_env = {
        e["name"]: e["value"]
        for e in states["voc-ingestion-worker"]["template"]["containers"][0][
            "envs"
        ]
    }
    assert json.loads(worker_env["SCRAPER_PROXY_POOL_URLS"]) == [
        "http://proxy:8080"
    ]
    assert worker_env["SCRAPER_PAGE_SIZE"] == "500"
    assert worker_env["SCRAPER_BASE_DELAY_SEC"] == "1.5"
    assert worker_env["SCRAPER_MAX_JITTER_SEC"] == "2.0"
    assert worker_env["SCRAPER_MAX_RETRIES"] == "5"
    assert worker_env["PUBSUB_RAW_REVIEWS_TOPIC"] == "voc-raw-reviews-topic"
    assert (
        worker_env["GCS_RAW_DATALAKE_BUCKET"] == "voc-datalake-test-voc-project"
    )
    assert worker_env["BQ_DATASET_ID"] == "bbva_voc_tds"
    job_template = states["voc-sanitization-job"]["template"]
    assert job_template["taskCount"] == job_template["parallelism"] == 1
    task = job_template["template"]
    assert task["timeout"] == "1800s" and task["maxRetries"] == 1
    assert (
        task["serviceAccount"]
        == "voc-sa-sanitization@test-voc-project.iam.gserviceaccount.com"
    )
    sanitizer = task["containers"][0]
    assert sanitizer["image"] == SANITIZATION_IMAGE
    env = {e["name"]: e["value"] for e in sanitizer["envs"]}
    assert env["USER_HASH_SALT"] == "test-salt-1234567890"
    assert env["BEAM_RUNNER"] == "DirectRunner"
    assert (
        env["DLP_INSPECT_TEMPLATE_ID"] == by_name["voc-dlp-inspect-template"].id
    )
    assert (
        env["DLP_DEIDENTIFY_TEMPLATE_ID"]
        == by_name["voc-dlp-deidentify-template"].id
    )
    assert env["PUBSUB_RAW_SUBSCRIPTION"] == "voc-raw-reviews-sub"
    assert env["BQ_SANITIZED_TDS_TABLE"] == "sanitized_reviews_tds"
    for retired in (
        "BQ_PREDICTIONS_TABLE",
        "BQ_HITL_AUDIT_TABLE",
        "ENABLE_DEDICATED_VERTEX_ENDPOINTS",
    ):
        assert retired not in env and retired not in worker_env
    assert states["voc-containers-repo"]["format"] == "DOCKER"
    invoker = (
        "serviceAccount:voc-sa-scheduler@"
        "test-voc-project.iam.gserviceaccount.com"
    )

    for name in (
        "voc-ingestion-scheduler-invoker",
        "voc-sanitization-scheduler-invoker",
    ):
        assert states[name]["role"] == "roles/run.invoker"
        assert states[name]["member"] == invoker
    assert all(s.get("member") != "allUsers" for s in states.values())
    schedules = {name: s for name, s in states.items() if "schedule" in s}
    assert len(schedules) == (2 if free_tier else 6) + (2 if ml else 0)
    _check_ml_jobs(pulumi_mocks, states, schedules, ml, free_tier, invoker)
    sanitizer_job = schedules.pop("voc-trigger-sanitization-daily")
    assert sanitizer_job["schedule"] == (
        "30 8 * * *" if free_tier else "30 9 * * *"
    )
    target = sanitizer_job["httpTarget"]
    assert (
        target["uri"]
        == "https://run.googleapis.com/v2/projects/test-voc-project/locations/us-central1/jobs/voc-sanitization-job:run"
    )
    assert "oauthToken" in target and "oidcToken" not in target
    assert (
        target["oauthToken"]["scope"]
        == "https://www.googleapis.com/auth/cloud-platform"
    )
    seen: list[BankKey] = []
    for name, schedule in schedules.items():
        assert schedule["timeZone"] == "America/Mexico_City"
        target = schedule["httpTarget"]
        assert target["httpMethod"] == "POST"
        assert target["headers"]["Content-Type"] == "application/json"
        assert (
            target["oidcToken"]["audience"]
            == "https://voc-ingestion-worker.run.app"
        )
        body = base64.b64decode(target["body"]).decode()
        assert "batch_size" not in json.loads(body)
        if free_tier:
            payload = SequentialBatchIngestionRequest.model_validate_json(body)
            assert payload.banks == list(BankKey)
            assert (
                payload.inter_bank_delay_sec == 15
                and payload.max_reviews_per_bank == 1000
            )
            assert schedule["schedule"] == "0 8 * * *"
            assert target["uri"].endswith("/api/v1/ingest/all")
        else:
            single = IngestionRequestPayload.model_validate_json(body)
            seen.append(single.bank_id)
            assert (
                single.page_size == 500 and single.max_reviews_per_run == 2000
            )
            offset = list(BankKey).index(single.bank_id) * 15
            assert (
                schedule["schedule"]
                == f"{offset % 60} {8 + offset // 60} * * *"
            )
            assert target["uri"].endswith("/api/v1/ingest")
        deps = pulumi_mocks.dependencies[name]
        assert by_name["voc-ingestion-scheduler-invoker"].urn in deps
        assert by_name["voc-sanitization-scheduler-invoker"].urn in deps
    if not free_tier:
        assert set(seen) == set(BankKey)
    assert not any("gcp:vertex/" in r.urn for r in registrations)


def _check_ml_jobs(
    monitor: InfrastructureMonitor,
    states: dict[str, Any],
    schedules: dict[str, Any],
    ml: bool,
    free_tier: bool,
    invoker: str,
) -> None:
    """Jobs de ml-inference y sus triggers; se sacan de ``schedules``."""
    names = ("voc-ml-inference-delta", "voc-ml-monitor")
    triggers = {
        "voc-ml-inference-delta": "voc-trigger-ml-delta-daily",
        "voc-ml-monitor": "voc-trigger-ml-monitor-weekly",
    }
    if not ml:
        assert not set(names) & set(states)
        assert not set(triggers.values()) & set(schedules)
        return
    hour = 8 if free_tier else 9
    expected = {
        "voc-ml-inference-delta": ("delta", f"30 {hour + 1} * * *"),
        "voc-ml-monitor": ("monitor", f"30 {hour + 2} * * 1"),
    }
    by_name = {r.urn.rsplit("::", 1)[-1]: r for r in monitor.resources.values()}
    for name, (command, cron) in expected.items():
        task = states[name]["template"]["template"]
        assert task["serviceAccount"] == (
            "voc-sa-ml-backend@test-voc-project.iam.gserviceaccount.com"
        )
        assert task["timeout"] == "1800s" and task["maxRetries"] == 1
        container = task["containers"][0]
        assert container["image"] == ML_INFERENCE_IMAGE
        assert container["args"] == [command]
        assert container["resources"]["limits"] == {
            "cpu": "1",
            "memory": "2Gi",
        }
        env = {e["name"]: e["value"] for e in container["envs"]}
        assert env["BQ_DATASET_ID"] == "bbva_voc_tds"
        assert env["DRIFT_TOPIC"] == "voc-incident-alerts-topic"
        assert env["QUALITY_TOPIC"] == "voc-model-quality-topic"
        grant = states[f"{name}-scheduler-invoker"]
        assert grant["role"] == "roles/run.invoker"
        assert grant["member"] == invoker
        trigger = schedules.pop(triggers[name])
        assert trigger["schedule"] == cron
        assert trigger["timeZone"] == "America/Mexico_City"
        assert trigger["httpTarget"]["uri"].endswith(f"/jobs/{name}:run")
        assert "oauthToken" in trigger["httpTarget"]
        assert (
            by_name[f"{name}-scheduler-invoker"].urn
            in monitor.dependencies[triggers[name]]
        )


def test_production_requires_hash_salt() -> None:
    pulumi.runtime.set_all_config(
        {
            "gcp:project": "test-voc-project",
            "bbva-voc-infra:environment": "prod",
        }
    )
    with pytest.raises(pulumi.ConfigMissingError):
        runpy.run_path(str(Path(__file__).resolve().parents[1] / "__main__.py"))


@pytest.mark.parametrize(
    ("salt", "environment"),
    [("short", "dev"), (" " * 16, "prod"), (DEV_USER_HASH_SALT, "prod")],
)
def test_invalid_hash_salt_rejected(salt: str, environment: str) -> None:
    with pytest.raises(ValueError, match="USER_HASH_SALT"):
        _validate_hash_salt(salt, environment)
