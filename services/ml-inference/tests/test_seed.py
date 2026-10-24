"""Siembra: valores de los experimentos, nulos y familias sin umbral."""

from pathlib import Path
from typing import Any

import pytest
from ml_inference.bq_io import StagingMergeWriter
from ml_inference.seed import (
    CONTEXT_SERIES,
    MODEL_VERSION,
    coverage_curve,
    drift_thresholds,
    seed,
)

DOCS = Path(__file__).resolve().parents[3] / "docs" / "analytics"
pytestmark = pytest.mark.skipif(not DOCS.exists(), reason="sin docs/")


def _seed(world: Any) -> dict[str, int]:
    world.bq.tables.clear()
    writer = StagingMergeWriter(world.bq, world.settings.dataset)
    return seed(
        world.settings, writer, DOCS, "b" * 64, "siembra inicial", world.now
    )


def test_seed_inserts_the_initial_versions(world: Any) -> None:
    counts = _seed(world)
    assert counts == {
        "model_versions": 1,
        "hitl_coverage_curves": 1,
        "risk_policy": 1,
        "drift_policy_template": 1,
        "drift_policy": 5,
        "guidelines": 2,
    }
    model = world.bq.rows("model_versions")[0]
    assert model["model_version"] == MODEL_VERSION
    assert model["status"] == "promoted"
    assert model["calibration_t"] == 1.6811
    assert model["kappa_dev"] == pytest.approx(0.9329)
    assert model["registry_uri"].endswith(f"/sentiment/{MODEL_VERSION}/")


def test_risk_policy_v1_keeps_business_parameters_null(world: Any) -> None:
    _seed(world)
    policy = world.bq.rows("risk_policy")[0]
    assert policy["hitl_threshold"] == 0.974
    assert policy["hitl_target_coverage"] == 0.9
    for field in (
        "hitl_weekly_cap",
        "drift_boost_coverage",
        "drift_boost_days",
        "drift_boost_weekly_cap",
        "human_agreement_sample_size",
        "human_agreement_frequency",
    ):
        assert policy[field] is None, field


def test_seed_is_idempotent(world: Any) -> None:
    _seed(world)
    writer = StagingMergeWriter(world.bq, world.settings.dataset)
    again = seed(world.settings, writer, DOCS, "b" * 64, "otra vez", world.now)
    assert set(again.values()) == {0}


def test_curve_has_reviews_and_minutes_per_week() -> None:
    from datetime import UTC, datetime

    curve = coverage_curve(DOCS, datetime(2026, 11, 1, tzinfo=UTC))
    point = next(p for p in curve.points if round(p.coverage, 2) == 0.90)
    assert point.threshold == 0.974
    assert point.reviews_per_week == pytest.approx(0.0995 * 3492.8, abs=1)
    assert point.minutes_per_week == pytest.approx(
        point.reviews_per_week * 7.1 / 60, abs=0.1
    )
    assert [p.coverage for p in curve.points] == sorted(
        p.coverage for p in curve.points
    )


def test_context_series_never_alert() -> None:
    thresholds = drift_thresholds()
    assert all(thresholds.z[s] is None for s in CONTEXT_SERIES)
    assert thresholds.z["neg_share"] == 4.0
    assert thresholds.psi == {"length_distribution": 0.25}
    assert (
        "family_AC" in CONTEXT_SERIES and "flag_update_share" in CONTEXT_SERIES
    )
