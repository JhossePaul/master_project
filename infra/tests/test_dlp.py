"""Plantillas DLP y patrones locales; no simula el detector NER de Google."""

import re
import runpy
from pathlib import Path
from typing import Any

import pulumi
import pulumi_gcp as gcp
import pytest

from infra.modules.dlp import create_dlp_templates
from infra.tests.conftest import InfrastructureMonitor

_NATIVE = {
    "PERSON_NAME",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD_NUMBER",
    "MEXICO_CURP_NUMBER",
}
_CUSTOM = {"MX_CLABE_BANCARIA", "MX_RFC_TAX_ID", "BBVA_ACCOUNT_NUMBER"}


@pytest.fixture
def templates(
    pulumi_mocks: InfrastructureMonitor,
) -> dict[str, dict[str, Any]]:
    @pulumi.runtime.test
    def deploy() -> pulumi.Output[Any]:
        api = gcp.projects.Service(
            "test-dlp-api",
            project="test-voc-project",
            service="dlp.googleapis.com",
        )
        result = create_dlp_templates("test-voc-project", "us-central1", [api])

        def check_ids(ids: list[str]) -> None:
            assert ids == [
                "voc-dlp-inspect-template-id",
                "voc-dlp-deidentify-template-id",
            ]

        return pulumi.Output.all(
            result.inspect_template.id, result.deidentify_template.id
        ).apply(check_ids)

    deploy()
    registrations = list(pulumi_mocks.resources.values())
    assert len(registrations) == 3
    api_urn = next(r.urn for r in registrations if "test-dlp-api" in r.urn)
    for name in ("voc-dlp-inspect-template", "voc-dlp-deidentify-template"):
        assert api_urn in pulumi_mocks.dependencies[name]
    return {r.urn.rsplit("::", 1)[-1]: r.state for r in registrations}


def test_dlp_templates_privacy_and_semantic_tokens(
    templates: dict[str, dict[str, Any]],
) -> None:
    inspect = templates["voc-dlp-inspect-template"]
    deidentify = templates["voc-dlp-deidentify-template"]
    for name, resource in (
        ("voc-dlp-inspect-template", inspect),
        ("voc-dlp-deidentify-template", deidentify),
    ):
        assert (
            resource["parent"]
            == "projects/test-voc-project/locations/us-central1"
        )
        assert resource["templateId"] == name
    config = inspect["inspectConfig"]
    assert config["minLikelihood"] == "POSSIBLE"
    assert config["includeQuote"] is False
    assert {t["name"] for t in config["infoTypes"]} == _NATIVE
    custom = {t["infoType"]["name"]: t for t in config["customInfoTypes"]}
    assert set(custom) == _CUSTOM
    assert custom["MX_CLABE_BANCARIA"]["likelihood"] == "VERY_LIKELY"
    assert custom["MX_RFC_TAX_ID"]["likelihood"] == "VERY_LIKELY"
    assert custom["BBVA_ACCOUNT_NUMBER"]["likelihood"] == "LIKELY"

    transformations = deidentify["deidentifyConfig"]["infoTypeTransformations"][
        "transformations"
    ]
    assert len(transformations) == 8
    replacements = {
        t["infoTypes"][0]["name"]: t["primitiveTransformation"][
            "replaceConfig"
        ]["newValue"]["stringValue"]
        for t in transformations
    }
    assert replacements == {name: f"[{name}]" for name in _NATIVE | _CUSTOM}


@pytest.mark.parametrize(
    ("info_type", "valid", "invalid"),
    [
        ("MX_CLABE_BANCARIA", "012345678901234567", "0123456789012345678"),
        ("MX_RFC_TAX_ID", "ABCD900101XYZ", "ABCD900101XY"),
        ("MX_RFC_TAX_ID", "Ñ&A900101ABC", "ABC900101ABCD"),
        ("BBVA_ACCOUNT_NUMBER", "0123456789", "01234567890"),
    ],
)
def test_custom_regex_boundaries(
    templates: dict[str, dict[str, Any]],
    info_type: str,
    valid: str,
    invalid: str,
) -> None:
    custom = templates["voc-dlp-inspect-template"]["inspectConfig"][
        "customInfoTypes"
    ]
    pattern = next(
        t["regex"]["pattern"]
        for t in custom
        if t["infoType"]["name"] == info_type
    )
    assert re.search(pattern, f"dato {valid} válido") is not None
    assert re.search(pattern, f"dato {invalid} inválido") is None
    assert re.search(pattern, f"x{valid}y") is None


def test_error_code_exclusion_does_not_cover_adjacent_pii(
    templates: dict[str, dict[str, Any]],
) -> None:
    rule_sets = templates["voc-dlp-inspect-template"]["inspectConfig"][
        "ruleSets"
    ]
    assert len(rule_sets) == 1
    rule_set = rule_sets[0]
    assert {t["name"] for t in rule_set["infoTypes"]} == {
        "PHONE_NUMBER",
        "BBVA_ACCOUNT_NUMBER",
    }
    rule = rule_set["rules"][0]["exclusionRule"]
    assert rule["matchingType"] == "MATCHING_TYPE_PARTIAL_MATCH"
    pattern = rule["regex"]["pattern"]
    for diagnostic in (
        "ref: 3702:65c5:9xhchi",
        "ref : 3702 : 1234567890 : abc123",
    ):
        text = f"error {diagnostic}. cuenta 9876543210"
        match = re.search(pattern, text)
        assert match is not None
        assert match.group() == diagnostic
        assert text.index("9876543210") >= match.end()
    assert (
        re.search(pattern, "mi cuenta 9876543210 y teléfono 5512345678") is None
    )


@pytest.mark.parametrize("cmek", [False, True])
def test_entrypoint_creates_regional_dlp_templates(
    pulumi_mocks: InfrastructureMonitor, cmek: bool
) -> None:
    @pulumi.runtime.test
    def deploy() -> None:
        pulumi.runtime.set_all_config(
            {
                "gcp:project": "test-voc-project",
                "gcp:region": "us-east1",
                "bbva-voc-infra:enable_cmek": str(cmek).lower(),
            }
        )
        entrypoint = Path(__file__).resolve().parents[1] / "__main__.py"
        program = runpy.run_path(str(entrypoint))
        assert program["dlp_templates"].inspect_template is not None
        assert program["dlp_templates"].deidentify_template is not None

    deploy()
    registrations = list(pulumi_mocks.resources.values())
    apis = {
        r.urn for r in registrations if "gcp:projects/service:Service" in r.urn
    }
    templates = [r for r in registrations if "gcp:dataloss/" in r.urn]
    assert len(templates) == 2
    for template in templates:
        assert (
            template.state["parent"]
            == "projects/test-voc-project/locations/us-east1"
        )
        name = template.urn.rsplit("::", 1)[-1]
        assert apis <= pulumi_mocks.dependencies[name]
