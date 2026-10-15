"""Feature 4.1: configuración de ejecución, precedencia y preflight."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from sanitization_pipeline import (
    DLP_REQUEST_LIMIT_BYTES,
    ExecutionMode,
    PreflightError,
    SanitizationExecutionConfig,
    dlp_parent,
    load_config,
    preflight,
)

ROOT = Path(__file__).resolve().parents[3]


def test_defaults_are_valid_for_the_job_without_arguments():
    config = load_config([], {})
    assert config == SanitizationExecutionConfig()
    assert config.execution_mode == ExecutionMode.BATCH_PULL_SERVERLESS
    assert (config.max_messages, config.microbatch_size) == (2000, 200)
    assert config.max_runtime_sec + config.checkpoint_margin_sec == 1800
    assert config.ack_renew_interval_sec < config.ack_deadline_sec == 600
    assert config.dlp_max_bytes < DLP_REQUEST_LIMIT_BYTES
    assert config.use_cloud_dlp_api is False


def test_container_timeout_matches_pulumi_job():
    source = (ROOT / "infra/modules/cloud_run.py").read_text()
    sanitization = source[source.index('"voc-sanitization-job"') :]
    assert '"timeout": "1800s"' in sanitization[:600]
    assert SanitizationExecutionConfig().container_timeout_sec == 1800


def test_environment_and_flags_precedence():
    environ = {
        "SANITIZATION_MAX_MESSAGES": "500",
        "SANITIZATION_MICROBATCH_SIZE": "100",
        "SANITIZATION_USE_CLOUD_DLP_API": "false",
        "SANITIZATION_EXECUTION_MODE": " ",
        "UNRELATED": "x",
    }
    config = load_config(["--microbatch-size", "50"], environ)
    assert config.max_messages == 500
    assert config.microbatch_size == 50
    assert config.use_cloud_dlp_api is False
    config = load_config(
        ["--use-cloud-dlp-api", "--execution-mode", "GCS_BACKFILL_MANIFESTS"],
        environ,
    )
    assert config.use_cloud_dlp_api is True
    assert config.execution_mode == ExecutionMode.GCS_BACKFILL_MANIFESTS


@pytest.mark.parametrize(
    "changes",
    [
        {"max_messages": 0},
        {"microbatch_size": 3000},
        {"max_runtime_sec": 1600},
        {"ack_deadline_sec": 601},
        {"ack_renew_interval_sec": 600},
        {"dlp_max_bytes": DLP_REQUEST_LIMIT_BYTES},
        {"execution_mode": "STREAMING"},
        {"unknown": 1},
    ],
)
def test_invalid_budgets_are_rejected(changes):
    with pytest.raises(ValidationError):
        SanitizationExecutionConfig.model_validate(changes)


def test_preflight_accepts_regional_templates(settings, dlp_names):
    parent = dlp_names["parent"]
    cloud = SanitizationExecutionConfig(use_cloud_dlp_api=True)
    assert preflight(cloud, settings(), {}) == parent
    assert dlp_parent(settings()) == parent


@pytest.mark.parametrize(
    ("config", "changes", "environ", "message"),
    [
        ({}, {"ingestion_v2_enabled": False}, {}, "not enabled"),
        (
            {"execution_mode": "DATAFLOW_MANAGED"},
            {},
            {},
            "Dataflow",
        ),
        ({}, {}, {"BEAM_RUNNER": "DataflowRunner"}, "DirectRunner"),
        (
            {"use_cloud_dlp_api": True},
            {"dlp_inspect_template_id": None},
            {},
            "inspectTemplates",
        ),
        (
            {"use_cloud_dlp_api": True},
            {
                "dlp_deidentify_template_id": (
                    "projects/test-project/locations/europe-west1/"
                    "deidentifyTemplates/voc-dlp-deidentify-template"
                )
            },
            {},
            "deidentifyTemplates",
        ),
        (
            {"use_cloud_dlp_api": True},
            {"dlp_inspect_template_id": "voc-dlp-inspect-template"},
            {},
            "inspectTemplates",
        ),
    ],
)
def test_preflight_fails_closed(settings, config, changes, environ, message):
    with pytest.raises(PreflightError, match=message):
        preflight(
            SanitizationExecutionConfig.model_validate(config),
            settings(**changes),
            environ,
        )


def test_regex_mode_is_default_and_allowed_in_production(settings):
    local = SanitizationExecutionConfig()
    assert local.use_cloud_dlp_api is False
    production = settings(
        environment="production",
        user_hash_salt="salt-for-production-tests",
        dlp_inspect_template_id=None,
    )
    assert preflight(local, production, {}) == dlp_parent(production)


def test_dlp_tokens_and_infra_templates_stay_aligned():
    # Guardia temprana: 4.2 reutilizará exactamente estos info types.
    source = (ROOT / "infra/modules/dlp.py").read_text()
    for name in (
        "PERSON_NAME",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "CREDIT_CARD_NUMBER",
        "MEXICO_CURP_NUMBER",
        "MX_CLABE_BANCARIA",
        "MX_RFC_TAX_ID",
        "BBVA_ACCOUNT_NUMBER",
    ):
        assert f'"{name}"' in source
    assert 'f"[{name}]"' in source
