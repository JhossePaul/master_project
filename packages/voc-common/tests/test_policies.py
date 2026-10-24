"""Políticas v3: riesgo global, deriva por banco y curva HITL (6.1)."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from voc_common.policies import (
    CoveragePoint,
    DriftPolicy,
    DriftPolicyTemplate,
    DriftThresholds,
    HitlBoost,
    HitlCoverageCurve,
    RiskPolicy,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "analytics_v3"
KEY = "a" * 64
ACTOR = "b" * 64


def load(name: str) -> dict[str, Any]:
    path = _FIXTURES / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_risk_policy_round_trips() -> None:
    policy = RiskPolicy(**load("risk_policy"))
    assert RiskPolicy.model_validate_json(policy.model_dump_json()) == policy


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hitl_target_coverage", 1.2),
        ("retrain_kappa_floor", -0.1),
        ("families_min_prevalence", 2),
        ("set_by_hash", "not-a-sha"),
        ("hitl_signal", "entropy"),
        ("hitl_weekly_cap", 0),
    ],
)
def test_risk_policy_bounds(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        RiskPolicy(**{**load("risk_policy"), field: value})


def test_drift_policy_round_trips_with_null_thresholds() -> None:
    policy = DriftPolicy(**load("drift_policy"))
    assert policy.thresholds.z["family_AC"] is None
    assert policy.thresholds.psi["length_distribution"] == 0.25
    assert DriftPolicy.model_validate_json(policy.model_dump_json()) == policy


def test_drift_thresholds_are_non_negative_and_single_statistic() -> None:
    with pytest.raises(ValidationError, match="non-negative"):
        DriftThresholds(z={"share_neg": -1.0})
    with pytest.raises(ValidationError, match="both z and psi"):
        DriftThresholds(z={"length": 4.0}, psi={"length": 0.25})
    assert DriftThresholds().z == {}


def test_drift_policy_baseline_and_template() -> None:
    data = load("drift_policy")
    with pytest.raises(ValidationError, match="min_baseline_months"):
        DriftPolicy(**{**data, "min_baseline_months": 13})
    template_data = {
        key: value
        for key, value in data.items()
        if key not in {"drift_policy_version", "bank_id"}
    }
    template = DriftPolicyTemplate(**template_data)
    assert template.template_version == "drift_template_synthetic"
    with pytest.raises(ValidationError, match="extra"):
        DriftPolicyTemplate(**{**template_data, "bank_id": "BBVA"})


def _boost(**overrides: Any) -> HitlBoost:
    data: dict[str, Any] = {
        "boost_id": "boost-0001",
        "bank_id": "SANTANDER",
        "alert_id": "alert-0001",
        "risk_policy_version": "risk_policy_synthetic",
        "coverage": 0.8,
        "weekly_cap": 150,
        "starts_at": "2026-11-03T06:00:00Z",
        "ends_at": "2026-11-17T06:00:00Z",
    }
    data.update(overrides)
    return HitlBoost(**data)


def test_hitl_boost_window_and_close_row() -> None:
    assert _boost().ended_reason is None
    assert _boost(ended_reason="expired").ended_reason.value == "expired"
    with pytest.raises(ValidationError, match="ends_at"):
        _boost(ends_at="2026-11-03T06:00:00Z")


def _point(coverage: float, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "coverage": coverage,
        "risk": 0.05,
        "risk_ci_low": 0.03,
        "risk_ci_high": 0.07,
        "threshold": 0.97,
        "errors_caught": 0.5,
        "reviews_per_week": 350.0,
        "minutes_per_week": 700.0,
    }
    data.update(overrides)
    return data


def test_coverage_curve() -> None:
    curve = HitlCoverageCurve(
        model_version="M4_synthetic",
        calibration_version="temperature_synthetic",
        points=[_point(0.8), _point(0.9)],
        weekly_volume_total=3500,
        weekly_volume_by_bank={"BBVA": 1000, "NUBANK": 200},
        computed_at="2026-10-22T00:00:00Z",
    )
    assert (
        HitlCoverageCurve.model_validate_json(curve.model_dump_json()) == curve
    )
    with pytest.raises(ValidationError, match="increasing"):
        HitlCoverageCurve(
            **{**curve.model_dump(), "points": [_point(0.9), _point(0.8)]}
        )
    with pytest.raises(ValidationError, match="inside its interval"):
        CoveragePoint(**_point(0.9, risk=0.2))
    assert ACTOR
