"""Plantillas regionales DLP para PII y diagnósticos de la app bancaria."""

from dataclasses import dataclass

import pulumi
import pulumi_gcp as gcp

_NATIVE_INFO_TYPES: tuple[str, ...] = (
    "PERSON_NAME",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD_NUMBER",
    "MEXICO_CURP_NUMBER",
)
_CUSTOM_INFO_TYPES: tuple[tuple[str, str, str], ...] = (
    ("MX_CLABE_BANCARIA", r"\b\d{18}\b", "VERY_LIKELY"),
    ("MX_RFC_TAX_ID", r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b", "VERY_LIKELY"),
    ("BBVA_ACCOUNT_NUMBER", r"\b\d{10}\b", "LIKELY"),
)
_ERROR_CODE_PATTERN = r"ref\s*:\s*\d{4}\s*:\s*[a-zA-Z0-9]+\s*:\s*[a-zA-Z0-9]+"


@dataclass
class DlpTemplates:
    inspect_template: gcp.dataloss.PreventionInspectTemplate
    deidentify_template: gcp.dataloss.PreventionDeidentifyTemplate


def create_dlp_templates(
    project_id: str, region: str, api_deps: list[pulumi.Resource]
) -> DlpTemplates:
    """Crea detectores y sustituciones semánticas sin incluir citas de PII."""
    parent = f"projects/{project_id}/locations/{region}"
    opts = pulumi.ResourceOptions(depends_on=api_deps)
    inspect_template = gcp.dataloss.PreventionInspectTemplate(
        "voc-dlp-inspect-template",
        template_id="voc-dlp-inspect-template",
        parent=parent,
        inspect_config={
            "min_likelihood": "POSSIBLE",
            "include_quote": False,
            "info_types": [{"name": name} for name in _NATIVE_INFO_TYPES],
            "custom_info_types": [
                {
                    "info_type": {"name": name},
                    "regex": {"pattern": pattern},
                    "likelihood": likelihood,
                }
                for name, pattern, likelihood in _CUSTOM_INFO_TYPES
            ],
            "rule_sets": [
                {
                    "info_types": [
                        {"name": "PHONE_NUMBER"},
                        {"name": "BBVA_ACCOUNT_NUMBER"},
                    ],
                    "rules": [
                        {
                            "exclusion_rule": {
                                "regex": {"pattern": _ERROR_CODE_PATTERN},
                                "matching_type": "MATCHING_TYPE_PARTIAL_MATCH",
                            }
                        }
                    ],
                }
            ],
        },
        opts=opts,
    )
    info_types = (*_NATIVE_INFO_TYPES, *(t[0] for t in _CUSTOM_INFO_TYPES))
    deidentify_template = gcp.dataloss.PreventionDeidentifyTemplate(
        "voc-dlp-deidentify-template",
        template_id="voc-dlp-deidentify-template",
        parent=parent,
        deidentify_config={
            "info_type_transformations": {
                "transformations": [
                    {
                        "info_types": [{"name": name}],
                        # replaceWithInfoTypeConfig no agrega corchetes.
                        "primitive_transformation": {
                            "replace_config": {
                                "new_value": {"string_value": f"[{name}]"}
                            }
                        },
                    }
                    for name in info_types
                ]
            }
        },
        opts=opts,
    )
    return DlpTemplates(inspect_template, deidentify_template)
