"""Umbral HITL: de la política o de la subida activa del banco."""

from datetime import UTC, datetime
from typing import Any

import pytest
from voc_common.policies import HitlBoost, HitlCoverageCurve, RiskPolicy
from voc_nlp.hitl import requires_hitl, threshold_for

ACTOR = "b" * 64
T0 = datetime(2026, 11, 1, tzinfo=UTC)


def _policy() -> RiskPolicy:
    return RiskPolicy(
        policy_version="risk_policy_test",
        valid_from=T0,
        hitl_signal="prob_max",
        hitl_target_coverage=0.9,
        hitl_threshold=0.974,
        model_version="robertuito_sentiment_v1",
        monitor_sample_size=300,
        monitor_frequency="quarterly",
        topic_refit_frequency="quarterly",
        retrain_kappa_floor=0.89,
        warn_correction_rate=0.28,
        warn_agreement_floor=0.94,
        agreement_sample_weekly=500,
        families_exact_floor=0.53,
        families_min_prevalence=0.05,
        set_by_hash=ACTOR,
        reason="prueba",
    )


def _point(coverage: float, threshold: float) -> dict[str, Any]:
    return {
        "coverage": coverage,
        "risk": 0.01,
        "risk_ci_low": 0.0,
        "risk_ci_high": 0.02,
        "threshold": threshold,
        "errors_caught": 0.5,
        "reviews_per_week": 100.0,
        "minutes_per_week": 100.0,
    }


def _curve(model: str = "robertuito_sentiment_v1") -> HitlCoverageCurve:
    return HitlCoverageCurve(
        model_version=model,
        calibration_version="temperature_s1",
        points=[_point(0.8, 0.9853), _point(0.85, 0.9829), _point(0.9, 0.974)],
        weekly_volume_total=3493,
        weekly_volume_by_bank={"BBVA": 1000},
        computed_at=T0,
    )


def _boost(coverage: float) -> HitlBoost:
    return HitlBoost(
        boost_id="boost-1",
        bank_id="BBVA",
        risk_policy_version="risk_policy_test",
        coverage=coverage,
        weekly_cap=600,
        starts_at=T0,
        ends_at=datetime(2026, 11, 15, tzinfo=UTC),
    )


def test_threshold_without_boost_is_the_policy_threshold() -> None:
    assert threshold_for(_policy(), None, _curve()) == 0.974


def test_threshold_with_boost_comes_from_the_curve() -> None:
    assert threshold_for(_policy(), _boost(0.85), _curve()) == 0.9829


def test_boost_between_points_takes_the_lower_coverage() -> None:
    assert threshold_for(_policy(), _boost(0.87), _curve()) == 0.9829


def test_boost_below_the_curve_fails() -> None:
    with pytest.raises(ValueError, match="no point"):
        threshold_for(_policy(), _boost(0.5), _curve())


def test_curve_must_match_the_policy_model() -> None:
    with pytest.raises(ValueError, match="different models"):
        threshold_for(_policy(), _boost(0.85), _curve("other"))


@pytest.mark.parametrize(
    ("conf", "expected"),
    [(None, False), (0.5, True), (0.974, False), (0.99, False)],
)
def test_requires_hitl(conf: float | None, expected: bool) -> None:
    assert requires_hitl(conf, 0.974) is expected
