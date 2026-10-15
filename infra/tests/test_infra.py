"""Aceptación de la Épica 2 sobre el programa completo con Pulumi Mocks."""

import json
import runpy
from pathlib import Path
from typing import Any

import pulumi
import pytest

from infra.tests.conftest import (
    InfrastructureMonitor,
    assert_acyclic,
    unwrap_outputs,
)


@pytest.fixture
def dev_stack(
    pulumi_mocks: InfrastructureMonitor,
) -> dict[str, dict[str, Any]]:
    @pulumi.runtime.test
    def deploy() -> None:
        pulumi.runtime.set_all_config(
            {
                "gcp:project": "test-voc-project",
                "gcp:region": "us-central1",
                "bbva-voc-infra:environment": "dev",
                # Se omiten flags: la aceptación verifica defaults Free Tier.
            }
        )
        runpy.run_path(str(Path(__file__).resolve().parents[1] / "__main__.py"))

    deploy()
    registrations = list(pulumi_mocks.resources.values())
    names = {r.urn: r.urn.rsplit("::", 1)[-1] for r in registrations}
    assert_acyclic(pulumi_mocks)
    return {names[r.urn]: unwrap_outputs(r.state) for r in registrations}


@pulumi.runtime.test
def test_bigquery_tables_privacy_and_partitioning(
    dev_stack: dict[str, dict[str, Any]],
) -> None:
    tables = {
        name: state for name, state in dev_stack.items() if "tableId" in state
    }
    assert set(tables) == {
        "sanitized_reviews_tds",
        "delora_predictions",
        "ingestion_runs_log_v2",
        "hitl_triage_audit_log",
    }
    for state in tables.values():
        columns = {field["name"] for field in json.loads(state["schema"])}
        assert (
            not {"usuario", "imagen_usuario", "texto", "texto_respuesta"}
            & columns
        )
    tds = tables["sanitized_reviews_tds"]
    columns = {field["name"]: field for field in json.loads(tds["schema"])}
    assert columns["usuario_hash"] == {
        "name": "usuario_hash",
        "type": "STRING",
        "mode": "REQUIRED",
    }
    assert columns["texto_sanitizado"]["mode"] == "REQUIRED"
    assert columns["fecha"]["type"] == "TIMESTAMP"
    assert tds["timePartitioning"] == {"type": "DAY", "field": "fecha"}
    assert tds["clusterings"] == ["bank_id", "version_app"]


@pulumi.runtime.test
def test_dlp_templates_custom_regex_and_exclusions(
    dev_stack: dict[str, dict[str, Any]],
) -> None:
    inspect = dev_stack["voc-dlp-inspect-template"]["inspectConfig"]
    assert inspect["includeQuote"] is False
    custom = {
        item["infoType"]["name"]: item["regex"]["pattern"]
        for item in inspect["customInfoTypes"]
    }
    assert custom == {
        "MX_CLABE_BANCARIA": r"\b\d{18}\b",
        "MX_RFC_TAX_ID": r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b",
        "BBVA_ACCOUNT_NUMBER": r"\b\d{10}\b",
    }
    rule_set = inspect["ruleSets"][0]
    assert {t["name"] for t in rule_set["infoTypes"]} == {
        "PHONE_NUMBER",
        "BBVA_ACCOUNT_NUMBER",
    }
    exclusion = rule_set["rules"][0]["exclusionRule"]
    assert exclusion["matchingType"] == "MATCHING_TYPE_PARTIAL_MATCH"
    assert exclusion["regex"]["pattern"] == (
        r"ref\s*:\s*\d{4}\s*:\s*[a-zA-Z0-9]+\s*:\s*[a-zA-Z0-9]+"
    )


@pulumi.runtime.test
def test_cloud_run_scale_to_zero_and_free_tier(
    dev_stack: dict[str, dict[str, Any]],
) -> None:
    for name in ("voc-ingestion-worker", "voc-api-backend"):
        assert dev_stack[name]["template"]["scaling"] == {
            "minInstanceCount": 0,
            "maxInstanceCount": 2,
        }
    jobs = {
        name: state for name, state in dev_stack.items() if "schedule" in state
    }
    assert set(jobs) == {
        "voc-ingest-daily-sequential-all",
        "voc-trigger-sanitization-daily",
    }
    assert jobs["voc-ingest-daily-sequential-all"]["schedule"] == "0 8 * * *"
    assert jobs["voc-trigger-sanitization-daily"]["schedule"] == "30 8 * * *"
    assert all(j["timeZone"] == "America/Mexico_City" for j in jobs.values())
    assert "delora-tnss-endpoint" not in dev_stack
    assert "voc-vector-search-index" not in dev_stack
    assert "voc-cmek-key" not in dev_stack


@pulumi.runtime.test
def test_datalake_lifecycle_rule(
    dev_stack: dict[str, dict[str, Any]],
) -> None:
    bucket = dev_stack["voc-datalake"]
    assert bucket["name"] == "voc-datalake-test-voc-project"
    assert bucket["uniformBucketLevelAccess"] is True
    assert bucket["softDeletePolicy"]["retentionDurationSeconds"] == 0
    assert bucket["lifecycleRules"] == [
        {
            "action": {"type": "Delete"},
            "condition": {
                "age": 7,
                "matchesPrefixes": ["raw_staging/", "temp_beam/"],
            },
        }
    ]
    assert (
        "state/watermarks/"
        not in bucket["lifecycleRules"][0]["condition"]["matchesPrefixes"]
    )
