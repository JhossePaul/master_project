"""Verifica recursos reales del SDK con Pulumi Mocks, sin credenciales."""

import runpy
from pathlib import Path
from typing import Any

import pulumi
import pytest

from infra.modules.apis import enable_project_apis

_PROJECT = "test-voc-project"
_BASE_APIS = {
    "iam.googleapis.com",
    "pubsub.googleapis.com",
    "storage.googleapis.com",
    "bigquery.googleapis.com",
    "dlp.googleapis.com",
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "monitoring.googleapis.com",
}


def _assert_resources(
    resources: dict[str, Any], expected: set[str]
) -> pulumi.Output[Any]:
    assert set(resources) == expected
    assert len({resource._name for resource in resources.values()}) == len(
        expected
    )

    def check(values: list[Any]) -> None:
        assert {row[0] for row in values} == expected
        for _, project, disable_dependents, disable_destroy in values:
            assert project == _PROJECT
            assert disable_dependents is False
            assert disable_destroy is False

    return pulumi.Output.all(
        *[
            pulumi.Output.all(
                resource.service,
                resource.project,
                resource.disable_dependent_services,
                resource.disable_on_destroy,
            )
            for resource in resources.values()
        ]
    ).apply(check)


@pytest.mark.parametrize("cmek", [False, True])
@pytest.mark.parametrize("vertex_api", [False, True])
@pulumi.runtime.test
def test_api_flags_and_destroy_policy(
    cmek: bool, vertex_api: bool
) -> pulumi.Output[Any]:
    expected = set(_BASE_APIS)
    if cmek:
        expected.add("cloudkms.googleapis.com")
    if vertex_api:
        expected.add("aiplatform.googleapis.com")
    return _assert_resources(
        enable_project_apis(
            _PROJECT,
            enable_cmek=cmek,
            enable_vertex_ai_api=vertex_api,
        ),
        expected,
    )


@pytest.mark.parametrize("enabled", [False, True])
@pulumi.runtime.test
def test_pulumi_entrypoint_reads_stack_flags(
    enabled: bool,
) -> pulumi.Output[Any]:
    pulumi.runtime.set_all_config(
        {
            "gcp:project": _PROJECT,
            "bbva-voc-infra:enable_cmek": str(enabled).lower(),
            # Flag retirado en EPIC-6 (P8-6): ya no crea endpoints ni Dataflow.
            "bbva-voc-infra:enable_dedicated_vertex_endpoints": "true",
        }
    )
    entrypoint = Path(__file__).resolve().parents[1] / "__main__.py"
    program = runpy.run_path(str(entrypoint))
    expected = set(_BASE_APIS)
    if enabled:
        expected.add("cloudkms.googleapis.com")
    return _assert_resources(program["project_apis"], expected)


@pulumi.runtime.test
def test_vertex_ai_api_flag_adds_only_the_api() -> pulumi.Output[Any]:
    pulumi.runtime.set_all_config(
        {
            "gcp:project": _PROJECT,
            "bbva-voc-infra:enable_vertex_ai_api": "true",
        }
    )
    entrypoint = Path(__file__).resolve().parents[1] / "__main__.py"
    program = runpy.run_path(str(entrypoint))
    return _assert_resources(
        program["project_apis"], {*_BASE_APIS, "aiplatform.googleapis.com"}
    )


def test_pulumi_entrypoint_requires_project() -> None:
    pulumi.runtime.set_all_config({})
    entrypoint = Path(__file__).resolve().parents[1] / "__main__.py"
    with pytest.raises(pulumi.ConfigMissingError):
        runpy.run_path(str(entrypoint))
