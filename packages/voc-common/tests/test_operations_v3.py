"""Operación v3: modelos, corridas, deriva, KPI, calidad y oro (6.1)."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from voc_common.operations_v3 import (
    DriftAlert,
    DriftAlertEvent,
    DriftAlertMessage,
    DriftMetric,
    GoldLabel,
    InferenceRun,
    KpiEstimate,
    ModelQuality,
    ModelQualityMessage,
    ModelVersion,
    PromotionCheckResult,
    ReviewExplanation,
    TokenAttribution,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "analytics_v3"
KEY = "a" * 64
ACTOR = "b" * 64


def load(name: str) -> dict[str, Any]:
    path = _FIXTURES / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _model(**overrides: Any) -> ModelVersion:
    data: dict[str, Any] = {
        "model_version": "M4_synthetic",
        "registry_uri": "gs://bucket/ml_artifacts/m4",
        "base_checkpoint": "pysentimiento/robertuito-base-uncased",
        "training_data": "silver_synthetic",
        "calibration_version": "temperature_synthetic",
        "calibration_t": 1.7,
        "license": "non-commercial",
        "status": "candidate",
        "recorded_at": "2026-10-22T00:00:00Z",
    }
    data.update(overrides)
    return ModelVersion(**data)


def test_model_version_promotion() -> None:
    promoted = _model(
        status="promoted",
        promoted_at="2026-10-23T00:00:00Z",
        promoted_by_hash=ACTOR,
    )
    assert promoted.promoted_by_hash == ACTOR
    with pytest.raises(ValidationError, match="promoted versions"):
        _model(status="promoted")
    with pytest.raises(ValidationError, match="all present or all null"):
        _model(promoted_at="2026-10-23T00:00:00Z")
    with pytest.raises(ValidationError, match="positive"):
        _model(calibration_t=0)


def _run(**overrides: Any) -> InferenceRun:
    data: dict[str, Any] = {
        "run_id": "delta-20261021",
        "kind": "delta",
        "environment": "cloudrun",
        "model_version": "M4_synthetic",
        "started_at": "2026-10-21T07:00:00Z",
        "ended_at": "2026-10-21T07:05:00Z",
        "reviews": 4000,
        "texts": 3500,
        "status": "succeeded",
        "cost_usd": 0.02,
        "peak_memory_mib": 1500,
    }
    data.update(overrides)
    return InferenceRun(**data)


def test_inference_run() -> None:
    assert (
        _run(environment="local", kind="backfill").environment.value == "local"
    )
    with pytest.raises(ValidationError, match="ended_at"):
        _run(ended_at="2026-10-21T06:00:00Z")
    with pytest.raises(ValidationError, match="cost_usd"):
        _run(cost_usd=-1)
    start = _run(status="running", ended_at=None, topic_model_version="t1")
    assert start.ended_at is None and start.topic_model_version == "t1"
    with pytest.raises(ValidationError, match="running"):
        _run(status="running")
    with pytest.raises(ValidationError, match="running"):
        _run(ended_at=None)


def _metric(**overrides: Any) -> DriftMetric:
    data: dict[str, Any] = {
        "bank_id": "BBVA",
        "period": "2026-10-01",
        "metric": "share_neg",
        "value": 0.4,
        "baseline": 0.3,
        "z": 2.0,
        "threshold": 4.0,
        "alert": False,
        "drift_policy_version": "drift_policy_synthetic_bbva",
        "computed_at": "2026-11-03T06:00:00Z",
    }
    data.update(overrides)
    return DriftMetric(**data)


def test_drift_metric() -> None:
    assert _metric(metric="family_AC", threshold=None, z=9.0).alert is False
    with pytest.raises(ValidationError, match="never alert"):
        _metric(threshold=None, alert=True)
    with pytest.raises(ValidationError, match="z or psi"):
        _metric(psi=0.3)


def test_drift_alert_and_events() -> None:
    alert = DriftAlert(
        alert_id="alert-0001",
        bank_id="SANTANDER",
        period="2026-10-01",
        series="share_neg",
        value=5.2,
        threshold=4.0,
        drift_policy_version="drift_policy_synthetic_santander",
        created_at="2026-11-03T06:00:00Z",
    )
    assert alert.hitl_boost_id is None
    event = DriftAlertEvent(
        event_id="ev-1",
        alert_id=alert.alert_id,
        status="open",
        at=alert.created_at,
    )
    assert event.actor_hash is None
    with pytest.raises(ValidationError):
        DriftAlertEvent(
            event_id="ev-2", alert_id="a", status="closed", at=alert.created_at
        )


def test_drift_alert_message_has_no_text_fields() -> None:
    message = DriftAlertMessage(**load("drift_alert_message"))
    assert set(DriftAlertMessage.model_fields) == {
        "alert_id",
        "bank_id",
        "period",
        "series",
        "value",
        "threshold",
        "drift_policy_version",
        "hitl_boost_id",
        "triggered_at",
    }
    assert (
        DriftAlertMessage.model_validate_json(message.model_dump_json())
        == message
    )
    for period in ("2026-13", "26-10", "2026/10"):
        with pytest.raises(ValidationError, match="YYYY-MM"):
            DriftAlertMessage(
                **{**load("drift_alert_message"), "period": period}
            )


def _kpi(**overrides: Any) -> KpiEstimate:
    data: dict[str, Any] = {
        "metric": "neg",
        "bank_id": "BBVA",
        "period": "2026-10",
        "method": "ppi",
        "estimate": 0.42,
        "ci_low": 0.40,
        "ci_high": 0.44,
        "n_gold": 800,
        "n_unlabeled": 50000,
        "model_version": "M4_synthetic",
        "gold_version": "gold_dev_v1",
        "computed_at": "2026-11-01T00:00:00Z",
    }
    data.update(overrides)
    return KpiEstimate(**data)


def test_kpi_estimate() -> None:
    raw = _kpi(
        method="raw", ci_low=None, ci_high=None, n_gold=None, gold_version=None
    )
    assert raw.ci_low is None
    with pytest.raises(ValidationError, match="ppi estimates"):
        _kpi(gold_version=None)
    with pytest.raises(ValidationError, match="inside its interval"):
        _kpi(estimate=0.5)
    with pytest.raises(ValidationError, match="all present or all null"):
        _kpi(method="raw", ci_high=None)


def test_review_explanation_stores_offsets_not_text() -> None:
    explanation = ReviewExplanation(
        text_key=KEY,
        model_version="M4_synthetic",
        method="occlusion_v1",
        attributions=[{"start": 0, "end": 4, "weight": 0.7}],
        source="precomputed_hitl",
        computed_at="2026-10-21T07:06:00Z",
    )
    assert set(TokenAttribution.model_fields) == {
        "start",
        "end",
        "weight",
        "d_neg",
        "d_neu",
        "d_pos",
    }
    assert explanation.attributions[0].end == 4
    with pytest.raises(ValidationError, match="greater than start"):
        TokenAttribution(start=3, end=3, weight=0.1)


def test_occlusion_v2_attributions_carry_the_direction() -> None:
    explanation = ReviewExplanation(
        text_key=KEY,
        model_version="M4_synthetic",
        method="occlusion_v2",
        attributions=[
            {"start": 0, "end": 4, "d_neg": 0.4, "d_neu": -0.1, "d_pos": -0.3}
        ],
        source="on_demand",
        computed_at="2026-10-26T07:06:00Z",
    )
    assert explanation.attributions[0].d_neg == 0.4
    with pytest.raises(ValidationError, match="wrong fields"):
        ReviewExplanation(
            text_key=KEY,
            model_version="M4_synthetic",
            method="occlusion_v2",
            attributions=[{"start": 0, "end": 4, "weight": 0.7}],
            source="on_demand",
            computed_at="2026-10-26T07:06:00Z",
        )
    with pytest.raises(ValidationError, match="wrong fields"):
        ReviewExplanation(
            text_key=KEY,
            model_version="M4_synthetic",
            method="occlusion_v1",
            attributions=[
                {"start": 0, "end": 4, "d_neg": 0, "d_neu": 0, "d_pos": 0}
            ],
            source="on_demand",
            computed_at="2026-10-26T07:06:00Z",
        )
    with pytest.raises(ValidationError, match="weight or all"):
        TokenAttribution(start=0, end=4, d_neg=0.1)
    with pytest.raises(ValidationError, match="excludes"):
        TokenAttribution(start=0, end=4, weight=0.1, d_pos=0.1)


def _quality(**overrides: Any) -> ModelQuality:
    data: dict[str, Any] = {
        "model_version": "M4_synthetic",
        "signal": "kappa_monitor",
        "period": "2026Q4",
        "value": 0.91,
        "n": 300,
        "ci_low": 0.88,
        "ci_high": 0.94,
        "threshold": 0.89,
        "status": "ok",
        "computed_at": "2027-01-02T00:00:00Z",
    }
    data.update(overrides)
    return ModelQuality(**data)


def test_model_quality_subject() -> None:
    families = _quality(
        model_version=None,
        llm_model="gemini-3.6-flash",
        prompt_version="aspects_v2_1",
        signal="families_validation",
        status="rejected",
    )
    assert families.llm_model == "gemini-3.6-flash"
    with pytest.raises(ValidationError, match="families_validation"):
        _quality(signal="families_validation")
    with pytest.raises(ValidationError, match="requires model_version"):
        _quality(model_version=None)


def _gold(**overrides: Any) -> GoldLabel:
    data: dict[str, Any] = {
        "gold_version": "gold_dev_v1",
        "split": "dev",
        "task": "sentiment",
        "id_resena": "synthetic-0001",
        "text_key": KEY,
        "label": "NEG",
        "weight": 12.5,
        "guideline_version": "v2.2",
        "loaded_at": "2026-10-24T00:00:00Z",
    }
    data.update(overrides)
    return GoldLabel(**data)


def _gold_aspects(**overrides: Any) -> GoldLabel:
    data: dict[str, Any] = {
        "gold_version": "aspects_gold_v2_1",
        "split": "aspects_gold_v2_1",
        "task": "aspects",
        "id_resena": None,
        "weight": None,
        "label": None,
        "families": ["AC"],
        "flag_update": False,
        "flag_security": True,
        "praise": False,
        "guideline_version": "v2.1",
    }
    data.update(overrides)
    return _gold(**data)


def test_gold_labels() -> None:
    assert _gold().label is not None
    assert _gold_aspects().families
    with pytest.raises(ValidationError, match="sentiment gold"):
        _gold(families=["AC"])
    with pytest.raises(ValidationError, match="aspects gold"):
        _gold_aspects(praise=None)
    with pytest.raises(ValidationError, match="repeat"):
        _gold_aspects(families=["AC", "AC"])
    with pytest.raises(ValidationError, match="holds sentiment"):
        _gold_aspects(split="dev")
    with pytest.raises(ValidationError, match="sentiment or aspects only"):
        _gold(task="topic")
    with pytest.raises(ValidationError, match="id_resena and weight"):
        _gold(weight=None)
    with pytest.raises(ValidationError, match="positive"):
        _gold(weight=0)
    with pytest.raises(ValidationError, match="design weight"):
        _gold_aspects(weight=1.0)
    assert _gold_aspects().id_resena is None


def test_model_quality_message_is_a_notice_without_text() -> None:
    row = _quality(status="retrain", value=0.85, threshold=0.89)
    message = ModelQualityMessage.from_quality(row)
    assert message.status == "retrain" and message.value == 0.85
    assert "ci_low" not in ModelQualityMessage.model_fields
    assert not {"text", "texto", "comment", "note"} & set(
        ModelQualityMessage.model_fields
    )
    with pytest.raises(ValidationError, match="only warnings"):
        ModelQualityMessage.from_quality(_quality(status="ok"))


def _check(**overrides: Any) -> PromotionCheckResult:
    data: dict[str, Any] = {
        "candidate_version": "robertuito_sentiment_v2",
        "current_version": "robertuito_sentiment_v1",
        "gold_version": "gold_synthetic",
        "n": 794,
        "kappa_diff": 0.004,
        "kappa_ci_low": -0.01,
        "kappa_ci_high": 0.02,
        "macro_f1_diff": 0.003,
        "macro_f1_ci_low": -0.012,
        "macro_f1_ci_high": 0.018,
        "verdict": "tie",
        "run_id": "rescore-robertuito_sentiment_v2-202610250900",
        "computed_at": "2026-10-25T09:00:00Z",
    }
    data.update(overrides)
    return PromotionCheckResult(**data)


def test_promotion_check_round_trips() -> None:
    check = _check()
    assert (
        PromotionCheckResult.model_validate_json(check.model_dump_json())
        == check
    )


@pytest.mark.parametrize(
    ("overrides", "verdict"),
    [
        ({}, "tie"),
        ({"kappa_ci_low": 0.001}, "better"),
        (
            {
                "macro_f1_diff": -0.02,
                "macro_f1_ci_low": -0.03,
                "macro_f1_ci_high": -0.01,
            },
            "worse",
        ),
        # Peor gana a mejor: un IC entero bajo 0 basta para negarse.
        (
            {
                "kappa_ci_low": 0.001,
                "macro_f1_diff": -0.02,
                "macro_f1_ci_low": -0.03,
                "macro_f1_ci_high": -0.01,
            },
            "worse",
        ),
    ],
)
def test_promotion_verdict_follows_the_rule(
    overrides: dict[str, Any], verdict: str
) -> None:
    assert _check(**overrides, verdict=verdict).verdict == verdict
    others = {"better", "tie", "worse"} - {verdict}
    for other in others:
        with pytest.raises(ValidationError, match=f"verdict must be {verdict}"):
            _check(**overrides, verdict=other)


def test_promotion_check_consistency() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        _check(candidate_version="robertuito_sentiment_v1")
    with pytest.raises(ValidationError, match="inside its interval"):
        _check(kappa_diff=0.05)
    with pytest.raises(ValidationError):
        _check(n=0)
