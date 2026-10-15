"""Feature 2.7: persistencia metadata, grants de bucket y configuración real."""

import runpy
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pulumi
import pytest
from pydantic import ValidationError
from voc_common import IngestionStorageLayout, Settings

from infra.tests.conftest import InfrastructureMonitor, unwrap_outputs

ENTRYPOINT = Path(__file__).resolve().parents[1] / "__main__.py"


def resources(
    monitor: InfrastructureMonitor,
    token: str,
) -> dict[str, Any]:
    return {
        r.urn.rsplit("::", 1)[-1]: r
        for r in monitor.resources.values()
        if f"{token}::" in r.urn
    }


@pytest.mark.parametrize("cmek", [False, True])
@pytest.mark.parametrize("custom", [False, True])
def test_watermark_storage_lifecycle_iam_and_consumers(
    pulumi_mocks: InfrastructureMonitor,
    cmek: bool,
    custom: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected = (
        IngestionStorageLayout()
        if not custom
        else IngestionStorageLayout(
            gcs_raw_staging_prefix="raw_v2",
            gcs_watermark_prefix="metadata/watermarks",
            gcs_ingestion_state_prefix="metadata/ingestion",
            gcs_ingestion_manifests_prefix="metadata/ingestion/manifests",
            gcs_ingestion_ledgers_prefix="metadata/ingestion/ledgers",
            gcs_processing_receipts_prefix="metadata/ingestion/receipts",
        )
    )
    # IaC no debe leer ni aceptar el .env o entorno local del runtime.
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GCS_RAW_STAGING_PREFIX=state\n")
    monkeypatch.setenv("GCS_INGESTION_STATE_PREFIX", "raw_staging")
    exported: dict[str, Any] = {}
    original_export = pulumi.export

    def capture(name: str, value: Any) -> None:
        exported[name] = value
        original_export(name, value)

    @pulumi.runtime.test
    def deploy() -> None:
        config = {
            "gcp:project": "test-voc-project",
            "bbva-voc-infra:enable_cmek": str(cmek).lower(),
        }
        if custom:
            config.update(
                {
                    f"bbva-voc-infra:{k}": v
                    for k, v in expected.model_dump().items()
                }
            )
        pulumi.runtime.set_all_config(config)
        with patch("pulumi.export", side_effect=capture):
            program = runpy.run_path(str(ENTRYPOINT))
        assert program["storage_layout"] == expected
        assert program["storage_bq"].storage_layout == expected

    deploy()
    buckets = resources(pulumi_mocks, "gcp:storage/bucket:Bucket")
    assert list(buckets) == ["voc-datalake"]
    bucket = buckets["voc-datalake"]
    assert bucket.state["name"] == "voc-datalake-test-voc-project"
    conditions = bucket.state["lifecycleRules"]
    assert conditions == [
        {
            "action": {"type": "Delete"},
            "condition": {
                "age": 7,
                "matchesPrefixes": [
                    expected.gcs_raw_staging_prefix + "/",
                    "temp_beam/",
                ],
            },
        }
    ]
    ephemeral = conditions[0]["condition"]["matchesPrefixes"]
    for prefix in (
        expected.gcs_watermark_prefix,
        expected.gcs_ingestion_state_prefix,
        expected.gcs_ingestion_manifests_prefix,
        expected.gcs_ingestion_ledgers_prefix,
        expected.gcs_processing_receipts_prefix,
    ):
        assert not any((prefix + "/").startswith(p) for p in ephemeral)
    assert bucket.state["uniformBucketLevelAccess"] is True
    assert bucket.state["softDeletePolicy"]["retentionDurationSeconds"] == 0
    assert bool(bucket.state.get("encryption")) == cmek
    grants = resources(
        pulumi_mocks, "gcp:storage/bucketIAMMember:BucketIAMMember"
    )
    assert set(grants) == {
        "voc-datalake-ingestion-objects",
        "voc-datalake-sanitization-objects",
    }
    assert {r.state["member"] for r in grants.values()} == {
        f"serviceAccount:voc-sa-{actor}@test-voc-project.iam.gserviceaccount.com"
        for actor in ("ingestion", "sanitization")
    }
    for name, grant in grants.items():
        assert grant.state["bucket"] == bucket.state["name"]
        assert grant.state["role"] == "roles/storage.objectUser"
        assert bucket.urn in pulumi_mocks.dependencies[name]
    project_iam = resources(pulumi_mocks, "gcp:projects/iAMMember:IAMMember")
    assert project_iam  # No confundir un filtro vacío con ausencia de grants.
    assert not any(
        r.state["role"].startswith("roles/storage.")
        for r in project_iam.values()
    )
    for token in (
        "gcp:storage/bucketObject:BucketObject",
        "gcp:storage/bucketIAMBinding:BucketIAMBinding",
        "gcp:storage/bucketIAMPolicy:BucketIAMPolicy",
    ):
        assert not resources(pulumi_mocks, token)
    for token, name in (
        ("gcp:cloudrunv2/service:Service", "voc-ingestion-worker"),
        ("gcp:cloudrunv2/job:Job", "voc-sanitization-job"),
    ):
        consumer = resources(pulumi_mocks, token)[name]
        template = unwrap_outputs(consumer.state["template"])
        if "template" in template:
            template = template["template"]
        env = {
            item["name"]: item.get("value")
            for item in template["containers"][0]["envs"]
        }
        for key, value in expected.model_dump().items():
            assert env[key.upper()] == value
            assert exported[key] == value
        assert env["GCS_RAW_DATALAKE_BUCKET"] == bucket.state["name"]
        for grant in grants.values():
            assert grant.urn in pulumi_mocks.dependencies[name]
    if cmek:
        kms = resources(
            pulumi_mocks, "gcp:kms/cryptoKeyIAMMember:CryptoKeyIAMMember"
        )
        storage_grant = next(
            g
            for g in kms.values()
            if g.state["member"]
            == (
                "serviceAccount:service-123@gs-project-accounts.iam.gserviceaccount.com"
            )
        )
        assert storage_grant.urn in pulumi_mocks.dependencies["voc-datalake"]


@pytest.mark.parametrize(
    "change",
    [
        {"gcs_raw_staging_prefix": "state"},
        {"gcs_watermark_prefix": "temp_beam/watermarks"},
        {"gcs_ingestion_manifests_prefix": "raw_staging/manifests"},
        {"gcs_watermark_prefix": ""},
    ],
)
def test_invalid_prefixes_fail_before_creating_resources(
    pulumi_mocks: InfrastructureMonitor,
    change: dict[str, str],
) -> None:
    @pulumi.runtime.test
    def deploy() -> None:
        pulumi.runtime.set_all_config(
            {
                "gcp:project": "test-voc-project",
                **{f"bbva-voc-infra:{k}": v for k, v in change.items()},
            }
        )
        with pytest.raises(ValidationError):
            runpy.run_path(str(ENTRYPOINT))

    deploy()
    assert not [r for r in pulumi_mocks.resources.values() if "gcp:" in r.urn]


def test_layout_defaults_match_runtime_settings_without_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for key in Settings.model_fields:
        monkeypatch.delenv(key.upper(), raising=False)
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None)
    layout = IngestionStorageLayout()
    assert layout.model_dump() == {
        key: getattr(settings, key)
        for key in IngestionStorageLayout.model_fields
    }
