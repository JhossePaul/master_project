"""Cómputo privado, payloads compatibles y horarios según modo operativo."""

import base64
import json
import runpy
from pathlib import Path
from typing import Any

import pulumi
import pytest
from pulumi.runtime import rpc
from voc_common import (
    BankKey,
    IngestionRequestPayload,
    SequentialBatchIngestionRequest,
)
from voc_common.config import DEV_USER_HASH_SALT

from infra.modules.cloud_run import _validate_hash_salt
from infra.tests.conftest import InfrastructureMonitor


def _unwrap(value: Any) -> Any:
    if rpc.is_rpc_secret(value):
        return _unwrap(rpc.unwrap_rpc_secret(value))
    if isinstance(value, dict):
        return {k: _unwrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_unwrap(v) for v in value]
    return value


@pytest.mark.parametrize("free_tier", [True, False])
@pytest.mark.parametrize("vertex", [False, True])
def test_compute_and_scheduler_modes(
    pulumi_mocks: InfrastructureMonitor, free_tier: bool, vertex: bool
) -> None:
    @pulumi.runtime.test
    def deploy() -> None:
        pulumi.runtime.set_all_config(
            {
                "gcp:project": "test-voc-project",
                "gcp:region": "us-central1",
                "bbva-voc-infra:free_tier_mode": str(free_tier).lower(),
                "bbva-voc-infra:enable_dedicated_vertex_endpoints": str(
                    vertex
                ).lower(),
                "bbva-voc-infra:ingestion_worker_image": "example/ingestion:v1",
                "bbva-voc-infra:sanitization_job_image": (
                    "example/sanitization:v1"
                ),
                "bbva-voc-infra:api_backend_image": "example/backend:v1",
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
        ("voc-ingestion-worker", "voc-sa-ingestion", "example/ingestion:v1"),
        ("voc-api-backend", "voc-sa-ml-backend", "example/backend:v1"),
    ):
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
    assert worker_env["SCRAPER_PAGE_SIZE"] == "199"
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
    assert sanitizer["image"] == "example/sanitization:v1"
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
    assert len(schedules) == (2 if free_tier else 6)
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
                single.page_size == 199 and single.max_reviews_per_run == 2000
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
    if vertex:
        index = states["voc-vector-search-index"]
        assert index["indexUpdateMethod"] == "BATCH_UPDATE"
        assert index["metadata"]["config"]["dimensions"] == 768
        assert (
            index["metadata"]["config"]["distanceMeasureType"]
            == "COSINE_DISTANCE"
        )
        assert (
            index["metadata"]["contentsDeltaUri"]
            == "gs://voc-datalake-test-voc-project/vertex/embeddings/"
        )
        assert states["delora-tnss-endpoint"]["location"] == "us-central1"
    else:
        assert not any("gcp:vertex/" in r.urn for r in registrations)


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
