"""*Temperature scaling* de RoBERTuito.

Port de ``voc_analytics.calibration.calibrate.apply`` y ``fit`` (solo
temperatura): los logits son ``log(p)`` recortado en ``EPS``, así que el
resultado es ``p ** (1 / T)`` normalizado. La T no cambia la clase predicha.
``fit_temperature`` minimiza la pérdida logarítmica ponderada en log T, como
el original, pero con sección áurea en lugar de Nelder-Mead de scipy: la
pérdida es convexa en 1 / T, así que tiene un solo mínimo.
"""

from typing import Final

import numpy as np
from numpy.typing import NDArray

EPS: Final = 1e-6
# Intervalo de búsqueda de log T (T entre 0.05 y 20) y su tolerancia.
_LOG_T_BOUNDS: Final = (-3.0, 3.0)
_TOL: Final = 1e-9
_GOLDEN: Final = (np.sqrt(5) - 1) / 2

Proba = NDArray[np.floating]


def apply_temperature(proba: Proba, t: float) -> NDArray[np.float64]:
    """Calibra probabilidades ``(n, 3)`` con la temperatura ``t`` (> 0)."""
    if t <= 0:
        raise ValueError("temperature must be positive")
    z = np.log(np.clip(np.asarray(proba, dtype=np.float64), EPS, 1.0)) / t
    z -= z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def confidence(proba: Proba) -> NDArray[np.float64]:
    """Probabilidad máxima por fila: la señal de revisión (``prob_max``)."""
    return np.asarray(proba, dtype=np.float64).max(axis=1)


def _nll(
    proba: Proba, y: NDArray[np.integer], w: NDArray[np.floating]
) -> float:
    p = np.clip(proba[np.arange(len(y)), y], EPS, 1.0)
    return float(np.average(-np.log(p), weights=w))


def fit_temperature(
    proba: Proba, y: NDArray[np.integer], w: NDArray[np.floating]
) -> float:
    """T que minimiza la pérdida logarítmica ponderada por ``w``.

    ``proba`` son las probabilidades ``(n, 3)`` sin calibrar e ``y`` el
    índice de la clase verdadera de cada fila (``NEG``, ``NEU``, ``POS``).
    """
    proba = np.asarray(proba, dtype=np.float64)
    y = np.asarray(y)
    w = np.asarray(w, dtype=np.float64)
    if not len(y) or len(y) != len(proba) or len(w) != len(y):
        raise ValueError("proba, y and w must be non-empty and aligned")

    def loss(log_t: float) -> float:
        return _nll(apply_temperature(proba, float(np.exp(log_t))), y, w)

    lo, hi = _LOG_T_BOUNDS
    a, b = hi - _GOLDEN * (hi - lo), lo + _GOLDEN * (hi - lo)
    fa, fb = loss(a), loss(b)
    while hi - lo > _TOL:
        if fa <= fb:
            hi, b, fb = b, a, fa
            a = hi - _GOLDEN * (hi - lo)
            fa = loss(a)
        else:
            lo, a, fa = a, b, fb
            b = lo + _GOLDEN * (hi - lo)
            fb = loss(b)
    return float(np.exp((lo + hi) / 2))
