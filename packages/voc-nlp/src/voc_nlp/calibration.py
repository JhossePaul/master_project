"""*Temperature scaling* de RoBERTuito.

Port de ``voc_analytics.calibration.calibrate.apply`` con una T por semilla:
los logits son ``log(p)`` recortado en ``EPS``, así que el resultado es
``p ** (1 / T)`` normalizado. La T no cambia la clase predicha.
"""

from typing import Final

import numpy as np
from numpy.typing import NDArray

EPS: Final = 1e-6

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
