"""Curva de cobertura y riesgo del umbral de revisión humana.

Port de ``voc_analytics.calibration.selective``: se aceptan sin revisión las
predicciones más seguras y el resto va a revisión humana. La **cobertura** es
la proporción aceptada y el **riesgo**, el error entre lo aceptado; todo se
pondera por 1 / π, así que son cifras poblacionales. Es el cálculo de
``docs/analytics/calibration/`` sin redondeo (el redondeo es de
presentación).
"""

from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

BOOTSTRAP: Final = 1000
SEED: Final = 20261022

Array = NDArray[np.floating]


@dataclass(frozen=True, slots=True)
class CoveragePoint:
    """Punto de la curva más cercano a una cobertura objetivo."""

    coverage: float
    risk: float
    threshold: float
    review_error: float | None
    """Error ponderado entre lo que va a revisión; ``None`` si no va nada."""
    errors_caught: float
    """Proporción del error total que cae en la revisión."""


def curve(
    conf: Array, err: Array, w: Array
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Cobertura, riesgo y umbral al aceptar de mayor a menor confianza."""
    conf, err, w = (np.asarray(a, dtype=np.float64) for a in (conf, err, w))
    order = np.argsort(-conf, kind="stable")
    cw = np.cumsum(w[order])
    ce = np.cumsum((w * err)[order])
    return cw / w.sum(), ce / cw, conf[order]


def aurc(conf: Array, err: Array, w: Array) -> float:
    """Área bajo la curva de riesgo y cobertura (menor es mejor)."""
    cov, risk, _ = curve(conf, err, w)
    return float(np.sum(risk * np.diff(np.concatenate([[0.0], cov]))))


def at_coverage(
    conf: Array, err: Array, w: Array, target: float
) -> CoveragePoint:
    """Primer punto de la curva con cobertura ≥ ``target``."""
    conf, err, w = (np.asarray(a, dtype=np.float64) for a in (conf, err, w))
    cov, risk, thr = curve(conf, err, w)
    i = min(int(np.searchsorted(cov, target - 1e-9)), len(cov) - 1)
    rejected = ~(conf >= thr[i])
    review_error = (
        float(np.average(err[rejected], weights=w[rejected]))
        if rejected.any()
        else None
    )
    caught = (w * err)[rejected].sum() / max((w * err).sum(), 1e-12)
    return CoveragePoint(
        coverage=float(cov[i]),
        risk=float(risk[i]),
        threshold=float(thr[i]),
        review_error=review_error,
        errors_caught=float(caught),
    )


def resample(
    strata: NDArray[np.generic], rng: np.random.Generator
) -> NDArray[np.intp]:
    """Índices de un *bootstrap* estratificado (con reemplazo por estrato)."""
    idx = []
    for s in np.unique(strata):
        members = np.flatnonzero(strata == s)
        idx.append(rng.choice(members, size=members.size, replace=True))
    return np.concatenate(idx)


def boot_risk(
    conf: Array,
    err: Array,
    w: Array,
    strata: NDArray[np.generic],
    target: float,
    n_boot: int = BOOTSTRAP,
    seed: int = SEED,
) -> tuple[float, float]:
    """IC 95 % del riesgo a la cobertura ``target`` (percentiles 2.5 y 97.5)."""
    conf, err, w = (np.asarray(a, dtype=np.float64) for a in (conf, err, w))
    strata = np.asarray(strata)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        i = resample(strata, rng)
        vals.append(at_coverage(conf[i], err[i], w[i], target).risk)
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))
