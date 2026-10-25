"""*Temperature scaling*: T = 1 es la identidad y el ajuste recupera T."""

import numpy as np
import pytest
from voc_nlp.calibration import apply_temperature, confidence, fit_temperature

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


def _synthetic(t: float, n: int = 20_000) -> tuple[np.ndarray, np.ndarray]:
    """Probabilidades sobreconfiadas: las etiquetas salen de ``p ** (1/t)``."""
    rng = np.random.default_rng(7)
    z = rng.normal(scale=3.0, size=(n, 3))
    proba = np.exp(z - z.max(axis=1, keepdims=True))
    proba /= proba.sum(axis=1, keepdims=True)
    true = apply_temperature(proba, t)
    y = np.array([rng.choice(3, p=row) for row in true])
    return proba, y


def test_fit_temperature_recovers_a_known_t() -> None:
    proba, y = _synthetic(2.0)
    assert fit_temperature(proba, y, np.ones(len(y))) == pytest.approx(
        2.0, rel=0.05
    )


def test_fit_temperature_matches_the_original_fit() -> None:
    # El ajuste de los experimentos: Nelder-Mead de scipy sobre log T desde 0.
    minimize = pytest.importorskip("scipy.optimize").minimize
    proba, y = _synthetic(1.7, n=2_000)
    w = np.random.default_rng(3).uniform(0.5, 2.0, len(y))

    def nll(q: np.ndarray) -> float:
        p = apply_temperature(proba, float(np.exp(q[0])))
        return float(
            np.average(
                -np.log(np.clip(p[np.arange(len(y)), y], 1e-6, 1)), weights=w
            )
        )

    expected = float(
        np.exp(minimize(nll, np.zeros(1), method="Nelder-Mead").x[0])
    )
    assert fit_temperature(proba, y, w) == pytest.approx(expected, rel=1e-3)


def test_fit_temperature_rejects_misaligned_inputs() -> None:
    with pytest.raises(ValueError, match="aligned"):
        fit_temperature(P, np.array([0, 1]), np.ones(3))


def test_ece_and_reliability_of_a_perfectly_calibrated_case() -> None:
    from voc_nlp.calibration import ece, reliability

    proba = np.array([[0.95, 0.03, 0.02]] * 20)
    y = np.array([0] * 19 + [1])  # 95 % de acierto con 0.95 de confianza
    assert ece(proba, y, np.ones(20)) == pytest.approx(0.0, abs=1e-12)
    (point,) = reliability(proba, y, np.ones(20))
    assert point["accuracy"] == pytest.approx(0.95)
    assert point["confidence"] == pytest.approx(0.95) and point["n"] == 20
    overconfident = ece(
        np.array([[0.99, 0.005, 0.005]] * 2), np.array([0, 1]), np.ones(2)
    )
    assert overconfident == pytest.approx(0.49)
