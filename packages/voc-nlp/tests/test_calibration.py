"""*Temperature scaling*: no cambia la clase y T = 1 es la identidad."""

import numpy as np
import pytest
from voc_nlp.calibration import apply_temperature, confidence

P = np.array([[0.9, 0.07, 0.03], [0.2, 0.5, 0.3], [0.34, 0.33, 0.33]])


def test_temperature_one_is_identity() -> None:
    assert np.allclose(apply_temperature(P, 1.0), P)


def test_temperature_keeps_the_argmax_and_softens() -> None:
    calibrated = apply_temperature(P, 1.6811)
    assert (calibrated.argmax(axis=1) == P.argmax(axis=1)).all()
    assert np.allclose(calibrated.sum(axis=1), 1.0)
    assert calibrated[0, 0] < P[0, 0]


def test_matches_power_formula() -> None:
    t = 1.7
    expected = P ** (1 / t)
    expected /= expected.sum(axis=1, keepdims=True)
    assert np.allclose(apply_temperature(P, t), expected)


def test_zero_probabilities_are_clipped() -> None:
    out = apply_temperature(np.array([[1.0, 0.0, 0.0]]), 2.0)
    assert np.isfinite(out).all() and out[0, 0] > 0.99


def test_rejects_non_positive_temperature() -> None:
    with pytest.raises(ValueError, match="positive"):
        apply_temperature(P, 0.0)


def test_confidence_is_row_max() -> None:
    assert np.allclose(confidence(P), [0.9, 0.5, 0.34])
