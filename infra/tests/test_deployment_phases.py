"""Despliegue por fases: base sin cargas e imágenes fijadas por digest."""

import runpy
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pulumi
import pytest
import yaml
from pydantic import ValidationError

from infra.modules.cloud_run import WorkloadImages
from infra.tests.conftest import (
    INGESTION_IMAGE,
    ML_INFERENCE_IMAGE,
    REGISTRY,
    SANITIZATION_IMAGE,
    WORKLOAD_CONFIG,
    InfrastructureMonitor,
    assert_acyclic,
    unwrap_outputs,
)

REPO = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO / "infra/__main__.py"
WORKLOAD_TOKENS = ("gcp:cloudrunv2/", "gcp:cloudscheduler/")
LATEST = {
    f"bbva-voc-infra:{key}": f"{REGISTRY}/{service}:latest"
    for key, service in (
        ("ingestion_worker_image", "ingestion-worker"),
        ("sanitization_job_image", "sanitization-pipeline"),
        ("api_backend_image", "api-backend"),
        ("ml_inference_image", "ml-inference"),
    )
}


def _run(config: dict[str, str]) -> dict[str, Any]:
    exported: dict[str, Any] = {}
    resolved: dict[str, Any] = {}
    original = pulumi.export

    def capture(name: str, value: Any) -> None:
        exported[name] = value
        original(name, value)

    @pulumi.runtime.test
    def deploy() -> None:
        pulumi.runtime.set_all_config(
            {"gcp:project": "test-voc-project", **config}
        )
        with patch("pulumi.export", side_effect=capture):
            runpy.run_path(str(ENTRYPOINT))
        pulumi.Output.all(
            **{k: pulumi.Output.from_input(v) for k, v in exported.items()}
        ).apply(resolved.update)

    deploy()
    return resolved


def _names(monitor: InfrastructureMonitor) -> dict[str, str]:
    return {
        r.urn.rsplit("::", 1)[-1]: r.urn.rsplit("::", 2)[-2].split("$")[-1]
        for r in monitor.resources.values()
    }


@pytest.mark.parametrize(
    "config",
    [{}, {"bbva-voc-infra:deploy_workloads": "false", **LATEST}],
    ids=["default", "explicit-with-mutable-tags"],
)
def test_phase_one_creates_base_without_workloads(
    pulumi_mocks: InfrastructureMonitor, config: dict[str, str]
) -> None:
    exports = _run(config)
    names = _names(pulumi_mocks)
    assert_acyclic(pulumi_mocks)
    assert not [t for t in names.values() if t.startswith(WORKLOAD_TOKENS)]
    types = set(names.values())
    for token in (
        "gcp:projects/service:Service",
        "gcp:artifactregistry/repository:Repository",
        "gcp:serviceaccount/account:Account",
        "gcp:storage/bucket:Bucket",
        "gcp:pubsub/topic:Topic",
        "gcp:bigquery/dataset:Dataset",
        "gcp:bigquery/table:Table",
        "gcp:dataloss/preventionInspectTemplate:PreventionInspectTemplate",
    ):
        assert token in types, token
    repo = unwrap_outputs(
        next(
            r.state
            for r in pulumi_mocks.resources.values()
            if r.urn.endswith("::voc-containers-repo")
        )
    )
    assert repo["dockerConfig"] == {"immutableTags": True}
    assert exports["deploy_workloads"] is False
    assert exports["artifact_registry_url"] == REGISTRY
    assert exports["scheduler_job_ids"] == []
    for key in (
        "ingestion_worker_uri",
        "api_backend_uri",
        "sanitization_job_id",
        "ingestion_history_job_name",
    ):
        assert key not in exports


def test_phase_two_without_backend_image(
    pulumi_mocks: InfrastructureMonitor,
) -> None:
    config = dict(WORKLOAD_CONFIG)
    del config["bbva-voc-infra:api_backend_image"]
    exports = _run(config)
    names = _names(pulumi_mocks)
    assert_acyclic(pulumi_mocks)
    assert "voc-api-backend" not in names
    assert {"voc-ingestion-worker", "voc-sanitization-job"} <= set(names)
    assert len(exports["scheduler_job_ids"]) == 2
    assert exports["deploy_workloads"] is True
    assert exports["ingestion_worker_uri"] == (
        "https://voc-ingestion-worker.run.app"
    )
    assert "api_backend_uri" not in exports
    assert "voc-ml-inference-delta" not in names
    assert "ml_delta_job_id" not in exports


def test_phase_two_with_ml_inference_image(
    pulumi_mocks: InfrastructureMonitor,
) -> None:
    exports = _run(
        {
            **WORKLOAD_CONFIG,
            "bbva-voc-infra:ml_inference_image": ML_INFERENCE_IMAGE,
        }
    )
    names = _names(pulumi_mocks)
    assert_acyclic(pulumi_mocks)
    assert {"voc-ml-inference-delta", "voc-ml-monitor"} <= set(names)
    assert len(exports["scheduler_job_ids"]) == 4
    assert exports["ml_delta_job_id"] == "voc-ml-inference-delta-id"
    assert exports["ml_monitor_job_id"] == "voc-ml-monitor-id"
    assert "bq_predictions_table" not in exports
    assert "bq_hitl_audit_table" not in exports
    assert set(exports["bq_analytics_tables"]) >= {
        "review_predictions",
        "hitl_reviews",
        "gold_labels",
    }
    assert "daily_topic_labels" in exports["bq_analytics_views"]


def test_cd_workflow_knows_the_ml_inference_image() -> None:
    workflow = (REPO / ".github/workflows/cd-cloud-build.yaml").read_text()
    assert "ml-inference) key=ml_inference_image ;;" in workflow
    assert ' ml-inference"' in workflow


@pytest.mark.parametrize(
    "key",
    [
        "ingestion_worker_image",
        "sanitization_job_image",
        "api_backend_image",
        "ml_inference_image",
    ],
)
def test_phase_two_rejects_mutable_tags(
    pulumi_mocks: InfrastructureMonitor, key: str
) -> None:
    @pulumi.runtime.test
    def deploy() -> None:
        pulumi.runtime.set_all_config(
            {
                "gcp:project": "test-voc-project",
                **WORKLOAD_CONFIG,
                f"bbva-voc-infra:{key}": LATEST[f"bbva-voc-infra:{key}"],
            }
        )
        with pytest.raises(ValidationError, match="sha256"):
            runpy.run_path(str(ENTRYPOINT))

    deploy()
    assert not [
        r for r in pulumi_mocks.resources.values() if "cloudrunv2/" in r.urn
    ]


@pytest.mark.parametrize(
    "key", ["ingestion_worker_image", "sanitization_job_image"]
)
def test_phase_two_requires_core_images(key: str) -> None:
    config = {"gcp:project": "test-voc-project", **WORKLOAD_CONFIG}
    del config[f"bbva-voc-infra:{key}"]
    pulumi.runtime.set_all_config(config)
    with pytest.raises(pulumi.ConfigMissingError):
        runpy.run_path(str(ENTRYPOINT))


@pytest.mark.parametrize(
    "image",
    [
        INGESTION_IMAGE,
        f"{REGISTRY}/ingestion-worker@sha256:{'0' * 64}",
        f"localhost:5000/team/worker@sha256:{'f' * 64}",
    ],
)
def test_digest_images_accepted(image: str) -> None:
    images = WorkloadImages(ingestion_worker=image, sanitization_job=image)
    assert images.api_backend is None and images.historical_job is None


@pytest.mark.parametrize(
    "image",
    [
        f"{REGISTRY}/ingestion-worker:latest",
        f"{REGISTRY}/ingestion-worker",
        f"{REGISTRY}/ingestion-worker@sha256:{'a' * 63}",
        f"{REGISTRY}/ingestion-worker@sha256:{'A' * 64}",
        f"ingestion-worker@sha256:{'a' * 64}",
    ],
)
def test_non_digest_images_rejected(image: str) -> None:
    with pytest.raises(ValidationError):
        WorkloadImages(
            ingestion_worker=image, sanitization_job=SANITIZATION_IMAGE
        )


def test_dev_stack_config_is_consistent_with_its_phase() -> None:
    stack = yaml.safe_load((REPO / "infra/Pulumi.dev.yaml").read_text())
    config = stack["config"]
    assert not [v for v in config.values() if ":latest" in str(v)]
    if config["bbva-voc-infra:deploy_workloads"] in (True, "true"):
        # Fase 2: las imágenes son obligatorias y van fijadas por digest.
        WorkloadImages(
            ingestion_worker=config["bbva-voc-infra:ingestion_worker_image"],
            sanitization_job=config["bbva-voc-infra:sanitization_job_image"],
        )


def test_cloud_build_publishes_sha_tagged_amd64_images() -> None:
    build = yaml.safe_load((REPO / "cloudbuild.yaml").read_text())
    image = "${_REGION}-docker.pkg.dev/${PROJECT_ID}/${_REPOSITORY}/${_SERVICE}"
    assert build["substitutions"]["_IMAGE"] == image
    assert build["substitutions"]["_REPOSITORY"] == "voc-containers-repo"
    args = next(s for s in build["steps"] if s["id"] == "build")["args"]
    assert "--platform=linux/amd64" in args
    assert "--tag=${_IMAGE}:${_TAG}" in args
    assert build["images"] == ["${_IMAGE}:${_TAG}"]
    assert (
        "DOCKER_BUILDKIT=1"
        in next(s for s in build["steps"] if s["id"] == "build")["env"]
    )


def test_cloud_build_upload_keeps_workspace_and_drops_sensitive_files() -> None:
    rules = (REPO / ".gcloudignore").read_text().splitlines()
    # Los Dockerfiles copian infra/pyproject.toml; evidence/ contiene PII.
    assert {"infra/*", "!infra/pyproject.toml", "evidence/", ".env"} <= set(
        rules
    )
    assert "infra/" not in rules


def test_cd_workflow_never_runs_on_pull_requests() -> None:
    workflow = yaml.safe_load(
        (REPO / ".github/workflows/cd-cloud-build.yaml").read_text()
    )
    # PyYAML interpreta la clave `on` como booleano True.
    triggers = workflow[True]
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read"}
    build = workflow["jobs"]["build"]
    assert build["permissions"]["id-token"] == "write"
    assert "--config=cloudbuild.yaml" in str(build["steps"])
