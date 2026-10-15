"""Aceptación integrada 2.10: un único contrato, matriz de despliegue y DAG."""

import json
import runpy
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pulumi
import pytest
from voc_common import IngestionRunAudit, IngestionWatermarkState, Settings

from infra.tests.conftest import (
    InfrastructureMonitor,
    assert_acyclic,
    unwrap_outputs,
)

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "packages/voc-common/tests/fixtures/ingestion"


@pytest.mark.parametrize("environment", ["dev", "prod"])
@pytest.mark.parametrize("free_tier", [False, True])
@pytest.mark.parametrize("cmek", [False, True])
def test_complete_infrastructure_matrix(
    pulumi_mocks: InfrastructureMonitor,
    environment: str,
    free_tier: bool,
    cmek: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in Settings.model_fields:
        monkeypatch.delenv(key.upper(), raising=False)
    exports: dict[str, Any] = {}
    resolved: dict[str, Any] = {}
    original_export = pulumi.export

    def capture(name: str, value: Any) -> None:
        exports[name] = value
        original_export(name, value)

    @pulumi.runtime.test
    def deploy() -> None:
        pulumi.runtime.set_all_config(
            {
                "gcp:project": "test-voc-project",
                "gcp:region": "us-central1",
                "bbva-voc-infra:environment": environment,
                "bbva-voc-infra:free_tier_mode": str(free_tier).lower(),
                "bbva-voc-infra:enable_cmek": str(cmek).lower(),
                "bbva-voc-infra:user_hash_salt": "fixture-only-salt-1234567890",
            }
        )
        with patch("pulumi.export", side_effect=capture):
            runpy.run_path(str(REPO / "infra/__main__.py"))
        pulumi.Output.all(**exports).apply(resolved.update)

    deploy()
    registrations = list(pulumi_mocks.resources.values())
    by_name = {r.urn.rsplit("::", 1)[-1]: r for r in registrations}
    states = {n: unwrap_outputs(r.state) for n, r in by_name.items()}
    assert_acyclic(pulumi_mocks)
    jobs = {
        n for n, r in by_name.items() if "gcp:cloudrunv2/job:Job::" in r.urn
    }
    assert jobs == {"voc-ingestion-history-job", "voc-sanitization-job"}
    tables = {n for n, s in states.items() if "tableId" in s}
    assert tables == {
        "ingestion_runs_log_v2",
        "sanitized_reviews_tds",
        "delora_predictions",
        "hitl_triage_audit_log",
    }
    for name in tables:
        assert states[name]["deletionProtection"] == (environment != "dev")
        columns = {f["name"] for f in json.loads(states[name]["schema"])}
        assert (
            not {"usuario", "imagen_usuario", "texto", "texto_respuesta"}
            & columns
        )
    schema = json.loads(states["ingestion_runs_log_v2"]["schema"])
    audit = IngestionRunAudit.model_validate_json(
        (FIXTURES / "audit_v2.json").read_text()
    )
    assert {f["name"] for f in schema} == set(audit.model_dump())
    bucket = states["voc-datalake"]
    assert bool(bucket.get("encryption")) == cmek
    assert bucket["forceDestroy"] == (environment == "dev")
    assert bucket["lifecycleRules"] == [
        {
            "action": {"type": "Delete"},
            "condition": {
                "age": 7,
                "matchesPrefixes": ["raw_staging/", "temp_beam/"],
            },
        }
    ]
    assert not any(
        "gcp:storage/bucketObject:BucketObject::" in r.urn
        for r in registrations
    )
    assert len([s for s in states.values() if "schedule" in s]) == (
        2 if free_tier else 6
    )
    for name in ("voc-ingestion-worker", *sorted(jobs)):
        template = states[name]["template"]
        if "template" in template:
            template = template["template"]
        env = {
            v["name"]: v.get("value") for v in template["containers"][0]["envs"]
        }
        assert (
            env["GCS_RAW_DATALAKE_BUCKET"]
            == resolved["gcs_raw_datalake_bucket"]
        )
        assert (
            env["GCS_INGESTION_MANIFESTS_PREFIX"]
            == resolved["gcs_ingestion_manifests_prefix"]
        )
        assert (
            env["BQ_INGESTION_RUNS_LOG_TABLE"]
            == resolved["bq_ingestion_runs_log_table"]
        )
        if name != "voc-sanitization-job":
            assert env["INGESTION_V2_ENABLED"] == "false"
            settings = Settings(
                _env_file=None, **{k.lower(): v for k, v in env.items()}
            )
            assert (
                template["timeout"]
                == f"{settings.ingestion_container_timeout_sec}s"
            )
            assert (
                settings.ingestion_max_runtime_sec
                < settings.ingestion_container_timeout_sec
            )
        for grant in (
            "voc-datalake-ingestion-objects",
            "voc-datalake-sanitization-objects",
        ):
            assert by_name[grant].urn in pulumi_mocks.dependencies[name]
    assert resolved["ingestion_history_job_name"] == (
        "projects/test-voc-project/locations/us-central1/jobs/voc-ingestion-history-job"
    )
    assert resolved["ingestion_history_job_region"] == "us-central1"
    # El único estado inicial es un contrato vacío; IaC no posee estos objetos.
    initial = IngestionWatermarkState.model_validate_json(
        (FIXTURES / "watermark_v2.json").read_text()
    )
    assert initial.revision == 0 and initial.observed_max_at is None
    assert initial.historical_plan_ids == initial.stream_ids == ()
