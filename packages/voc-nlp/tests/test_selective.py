"""La curva de cobertura y riesgo en un caso construido a mano."""

import numpy as np
import pytest
from voc_nlp.selective import at_coverage, boot_risk, curve, resample

CONF = np.array([0.95, 0.9, 0.8, 0.7, 0.6])
ERR = np.array([0.0, 0.0, 1.0, 0.0, 1.0])
W = np.array([1.0, 1.0, 1.0, 1.0, 1.0])


def test_curve_accepts_from_most_to_least_confident() -> None:
    cov, risk, thr = curve(CONF[::-1], ERR[::-1], W)
    assert cov == pytest.approx([0.2, 0.4, 0.6, 0.8, 1.0])
    assert risk == pytest.approx([0, 0, 1 / 3, 1 / 4, 2 / 5])
    assert thr == pytest.approx(CONF)


def test_at_coverage_gives_the_expected_threshold() -> None:
    point = at_coverage(CONF, ERR, W, 0.8)
    assert point.threshold == pytest.approx(0.7)
    assert point.coverage == pytest.approx(0.8)
    assert point.risk == pytest.approx(0.25)
    assert point.review_error == pytest.approx(1.0)
    assert point.errors_caught == pytest.approx(0.5)


def test_full_coverage_reviews_nothing() -> None:
    point = at_coverage(CONF, ERR, W, 1.0)
    assert point.review_error is None and point.errors_caught == 0.0


def test_weights_move_the_coverage() -> None:
    w = np.array([1.0, 1.0, 1.0, 1.0, 6.0])
    assert at_coverage(CONF, ERR, W, 0.5).threshold == pytest.approx(0.8)
    assert at_coverage(CONF, ERR, w, 0.5).threshold == pytest.approx(0.6)


def test_resample_keeps_strata_sizes() -> None:
    strata = np.array(["a", "a", "b", "b", "b"])
    idx = resample(strata, np.random.default_rng(0))
    assert sorted(strata[idx]) == ["a", "a", "b", "b", "b"]


def test_boot_risk_brackets_the_point_and_is_reproducible() -> None:
    rng = np.random.default_rng(1)
    conf = rng.uniform(0.4, 1.0, 400)
    err = (rng.uniform(size=400) > conf).astype(float)
    w = rng.uniform(1, 3, 400)
    strata = rng.integers(0, 4, 400)
    lo, hi = boot_risk(conf, err, w, strata, 0.9, n_boot=200)
    assert lo <= at_coverage(conf, err, w, 0.9).risk <= hi
    assert boot_risk(conf, err, w, strata, 0.9, n_boot=200) == (lo, hi)


def test_aurc_is_zero_without_errors_and_mean_risk_otherwise() -> None:
    from voc_nlp.selective import aurc

    conf = np.array([0.9, 0.8, 0.7, 0.6])
    w = np.ones(4)
    assert aurc(conf, np.zeros(4), w) == 0.0
    # Error en la menos segura: riesgo 0, 0, 0 y 1/4 en cada cuarto.
    assert aurc(conf, np.array([0, 0, 0, 1.0]), w) == pytest.approx(1 / 16)
