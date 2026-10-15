"""Feature 4.1: entrypoint del Job, preflight y despacho de modos."""

import json

import pytest
from sanitization_pipeline import pipeline
from voc_common import Settings


def last_log(capsys) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_invalid_configuration_exits_before_any_work(capsys, settings):
    code = pipeline.main(["--max-messages", "0"], {}, settings_factory=settings)
    assert code == pipeline.EX_USAGE
    log = last_log(capsys)
    assert log["severity"] == "ERROR"
    assert log["message"] == "Invalid sanitization configuration"


def test_disabled_v2_and_missing_templates_fail_closed(capsys, settings):
    disabled = pipeline.main(
        [],
        {},
        settings_factory=lambda: Settings(_env_file=None),
    )
    assert disabled == pipeline.EX_USAGE
    assert "not enabled" in last_log(capsys)["error"]
    missing = pipeline.main(
        [],
        {},
        settings_factory=lambda: settings(dlp_deidentify_template_id=None),
    )
    assert missing == pipeline.EX_USAGE


def test_unimplemented_modes_do_not_pretend_success(capsys, settings):
    assert pipeline.main([], {}, settings_factory=settings) == (
        pipeline.EX_SOFTWARE
    )
    assert last_log(capsys)["execution_mode"] == "BATCH_PULL_SERVERLESS"


def test_registered_runner_receives_validated_inputs(
    monkeypatch, settings, dlp_names
):
    calls = []

    def runner(config, loaded, parent):
        calls.append((config, loaded, parent))
        return pipeline.EX_OK

    monkeypatch.setitem(
        pipeline.RUNNERS, pipeline.ExecutionMode.GCS_BACKFILL_MANIFESTS, runner
    )
    code = pipeline.main(
        ["--execution-mode", "GCS_BACKFILL_MANIFESTS"],
        {},
        settings_factory=settings,
    )
    assert code == pipeline.EX_OK
    config, loaded, parent = calls[0]
    assert parent == dlp_names["parent"]
    assert loaded.dlp_inspect_template_id == dlp_names["inspect"]
    assert loaded.dlp_deidentify_template_id == dlp_names["deidentify"]
    assert config.execution_mode == "GCS_BACKFILL_MANIFESTS"


def test_unknown_flag_is_a_usage_error(settings):
    with pytest.raises(SystemExit) as exc:
        pipeline.main(["--nope"], {}, settings_factory=settings)
    assert exc.value.code == 2
