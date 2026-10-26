"""Versiones de la ``risk_policy``: umbral por cobertura y cambios validados."""

from datetime import UTC, datetime

import pytest
from voc_common.policies import CoveragePoint, HitlCoverageCurve, RiskPolicy
from voc_nlp.policy import (
    next_policy_version,
    next_risk_policy,
    point_for,
    propose_risk_policy,
)

NOW = datetime(2026, 11, 4, 9, 30, tzinfo=UTC)
ACTOR = "b" * 64


def curve(model: str = "modelo_v2") -> HitlCoverageCurve:
    points = [
        CoveragePoint(
            coverage=c,
            risk=0.1 - c / 20,
            threshold=t,
            errors_caught=e,
            reviews_per_week=100 * (1 - c),
            minutes_per_week=10 * (1 - c),
        )
        for c, t, e in (
            (0.8, 0.5, 0.5),
            (0.85, 0.55, 0.6),
            (0.9, 0.62, 0.7),
            (0.95, 0.75, 0.85),
        )
    ]
    return HitlCoverageCurve(
        model_version=model,
        calibration_version="cal_v1",
        points=points,
        weekly_volume_total=1000,
        weekly_volume_by_bank={"BBVA": 1000},
        computed_at=NOW,
    )


def policy(**changes: object) -> RiskPolicy:
    base = {
        "policy_version": "risk_policy_v1",
        "valid_from": datetime(2026, 10, 1, tzinfo=UTC),
        "hitl_signal": "prob_max",
        "hitl_target_coverage": 0.9,
        "hitl_threshold": 0.6,
        "model_version": "modelo_v1",
        "monitor_sample_size": 300,
        "monitor_frequency": "quarterly",
        "topic_refit_frequency": "quarterly",
        "retrain_kappa_floor": 0.89,
        "warn_correction_rate": 0.28,
        "warn_agreement_floor": 0.94,
        "agreement_sample_weekly": 500,
        "families_exact_floor": 0.53,
        "families_min_prevalence": 0.05,
        "set_by_hash": "a" * 64,
        "reason": "inicio",
    }
    return RiskPolicy.model_validate({**base, **changes})


def test_point_for_takes_the_first_point_that_reaches_the_coverage() -> None:
    assert point_for(curve(), 0.9).threshold == 0.62
    assert point_for(curve(), 0.86).coverage == 0.9
    with pytest.raises(ValueError, match="reach"):
        point_for(curve(), 0.99)


def test_next_policy_version() -> None:
    assert next_policy_version("risk_policy_v9") == "risk_policy_v10"
    assert next_policy_version("custom") == "custom_v2"


def test_proposed_policy_takes_the_threshold_of_its_coverage() -> None:
    new = propose_risk_policy(curve(), policy(), ACTOR, "nuevo modelo", NOW)
    assert new.policy_version == "risk_policy_v2"
    assert (new.model_version, new.hitl_threshold) == ("modelo_v2", 0.62)
    lower = propose_risk_policy(curve(), policy(), ACTOR, "r", NOW, 0.85)
    assert lower.hitl_target_coverage == 0.85
    assert lower.hitl_threshold == 0.55


def test_changing_the_coverage_recomputes_the_threshold_and_the_model() -> None:
    new = next_risk_policy(
        policy(), {"hitl_target_coverage": 0.85}, curve(), ACTOR, "prueba", NOW
    )
    assert new.hitl_threshold == 0.55
    assert new.model_version == "modelo_v2"
    assert (new.set_by_hash, new.reason, new.valid_from) == (
        ACTOR,
        "prueba",
        NOW,
    )
    assert new.policy_version == "risk_policy_v2"


def test_other_changes_keep_the_threshold_and_the_model() -> None:
    new = next_risk_policy(
        policy(), {"retrain_kappa_floor": 0.9}, curve(), ACTOR, "prueba", NOW
    )
    assert new.retrain_kappa_floor == 0.9
    assert (new.hitl_threshold, new.model_version) == (0.6, "modelo_v1")


def test_incomplete_groups_are_rejected_by_the_model() -> None:
    with pytest.raises(ValueError, match="together|drift_boost"):
        next_risk_policy(
            policy(), {"drift_boost_days": 7}, curve(), ACTOR, "prueba", NOW
        )
    full = next_risk_policy(
        policy(),
        {
            "drift_boost_coverage": 0.95,
            "drift_boost_days": 7,
            "drift_boost_weekly_cap": 200,
        },
        curve(),
        ACTOR,
        "prueba",
        NOW,
    )
    assert full.drift_boost_days == 7


def test_system_fields_and_unknown_fields_cannot_be_changed() -> None:
    with pytest.raises(ValueError, match="system"):
        next_risk_policy(
            policy(), {"hitl_threshold": 0.1}, curve(), ACTOR, "prueba", NOW
        )
    with pytest.raises(ValueError, match="unknown"):
        next_risk_policy(policy(), {"nope": 1}, curve(), ACTOR, "prueba", NOW)
