"""Feature 2.8: tabla única de auditoría y contrato compartido de voc-common."""

import json
import runpy
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pulumi
import pytest
from voc_common import IngestionRunAudit, Settings

from infra.tests.conftest import InfrastructureMonitor, unwrap_outputs

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("environment", ["dev", "prod"])
@pytest.mark.parametrize("cmek", [False, True])
def test_ingestion_audit_schema_storage_and_consumer_wiring(
    pulumi_mocks: InfrastructureMonitor,
    environment: str,
    cmek: bool,
) -> None:
    exported: dict[str, Any] = {}
    original_export = pulumi.export

    def capture(name: str, value: Any) -> None:
        exported[name] = value
        original_export(name, value)

    @pulumi.runtime.test
    def deploy() -> None:
        pulumi.runtime.set_all_config(
            {
                "gcp:project": "test-voc-project",
                "bbva-voc-infra:environment": environment,
                "bbva-voc-infra:enable_cmek": str(cmek).lower(),
                "bbva-voc-infra:user_hash_salt": "fixture-only-salt-1234567890",
            }
        )
        with patch("pulumi.export", side_effect=capture):
            program = runpy.run_path(str(REPO / "infra/__main__.py"))
        resource = program["storage_bq"].ingestion_runs_log
        assert resource is not None

    deploy()
    registrations = list(pulumi_mocks.resources.values())
    tables = {
        r.state["tableId"]: r for r in registrations if "tableId" in r.state
    }
    assert set(tables) == {
        "ingestion_runs_log_v2",
        "sanitized_reviews_tds",
        "delora_predictions",
        "hitl_triage_audit_log",
    }
    audit = tables["ingestion_runs_log_v2"]
    state = audit.state
    assert (
        state["tableId"]
        == Settings.model_fields["bq_ingestion_runs_log_table"].default
    )
    assert state["timePartitioning"] == {"type": "DAY", "field": "updated_at"}
    assert state["clusterings"] == ["bank_id", "run_id", "status"]
    assert state["deletionProtection"] == (environment != "dev")
    assert bool(state.get("encryptionConfiguration")) == cmek
    schema = {f["name"]: f for f in json.loads(state["schema"])}
    model_schema = IngestionRunAudit.model_json_schema()
    assert set(schema) == set(model_schema["properties"])
    for name, field in model_schema["properties"].items():
        alternatives = field.get("anyOf", [field])
        nullable = any(p.get("type") == "null" for p in alternatives)
        shape = next(p for p in alternatives if p.get("type") != "null")
        if "$ref" in shape:
            shape = model_schema["$defs"][shape["$ref"].rsplit("/", 1)[-1]]
        expected_type = (
            "TIMESTAMP"
            if shape.get("format") == "date-time"
            else {"integer": "INTEGER", "string": "STRING"}[shape["type"]]
        )
        assert schema[name] == {
            "name": name,
            "type": expected_type,
            "mode": "NULLABLE" if nullable else "REQUIRED",
        }
    fixture_path = (
        REPO / "packages/voc-common/tests/fixtures/ingestion/audit_v2.json"
    )
    fixture = IngestionRunAudit.model_validate_json(fixture_path.read_text())
    assert set(fixture.model_dump(mode="json")) == set(schema)
    assert not {
        "texto",
        "usuario",
        "raw",
        "input_token",
        "output_token",
    } & set(schema)
    assert "bq_ingestion_runs_log_table" in exported
    for name in (
        "voc-ingestion-worker",
        "voc-sanitization-job",
        "voc-api-backend",
    ):
        resource = next(
            r for r in registrations if r.urn.rsplit("::", 1)[-1] == name
        )
        template = unwrap_outputs(resource.state["template"])
        if "template" in template:
            template = template["template"]
        env = {
            v["name"]: v.get("value") for v in template["containers"][0]["envs"]
        }
        assert env["BQ_INGESTION_RUNS_LOG_TABLE"] == state["tableId"]
        assert audit.urn in pulumi_mocks.dependencies[name]
    if cmek:
        key = next(
            r for r in registrations if "gcp:kms/cryptoKey:CryptoKey::" in r.urn
        )
        assert state["encryptionConfiguration"] == {"kmsKeyName": key.id}
        bq_grant = next(
            r
            for r in registrations
            if r.state.get("member")
            == (
                "serviceAccount:bq-123@bigquery-encryption.iam.gserviceaccount.com"
            )
        )
        assert (
            bq_grant.urn in pulumi_mocks.dependencies["ingestion_runs_log_v2"]
        )
