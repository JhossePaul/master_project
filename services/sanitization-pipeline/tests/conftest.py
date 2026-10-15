"""Settings de prueba con plantillas DLP regionales válidas."""

from collections.abc import Callable

import pytest
from voc_common import Settings

PROJECT = "test-project"
REGION = "us-central1"
PARENT = f"projects/{PROJECT}/locations/{REGION}"
NAMES = {
    "parent": PARENT,
    "inspect": f"{PARENT}/inspectTemplates/voc-dlp-inspect-template",
    "deidentify": f"{PARENT}/deidentifyTemplates/voc-dlp-deidentify-template",
}


@pytest.fixture
def dlp_names() -> dict[str, str]:
    return dict(NAMES)


@pytest.fixture
def settings() -> Callable[..., Settings]:
    def build(**changes: object) -> Settings:
        values = {
            "gcp_project_id": PROJECT,
            "gcp_region": REGION,
            "ingestion_v2_enabled": True,
            "dlp_inspect_template_id": NAMES["inspect"],
            "dlp_deidentify_template_id": NAMES["deidentify"],
        }
        return Settings(_env_file=None, **(values | changes))

    return build
