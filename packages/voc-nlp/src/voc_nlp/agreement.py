"""Acuerdo entre etiquetadores del monitor de calidad.

Port de ``voc_analytics.scale.model_monitor`` sin scikit-learn: κ de Cohen
(con pesos opcionales, como ``cohen_kappa_score``), macro-F1 (como
``f1_score(average="macro", zero_division=0)``, la otra métrica de la regla
de promoción), acuerdo exacto de
conjuntos de familias y κ por familia con su IC *bootstrap*. Las familias
con prevalencia < 5 % no se juzgan: sus intervalos son demasiado anchos
(``docs/analytics/scale/scale_report.md``).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

BOOT: Final = 2000
SEED: Final = 20261022
MIN_PREVALENCE: Final = 0.05


@dataclass(frozen=True, slots=True)
class FamilyAgreement:
    """κ de una familia (presente o ausente) entre dos etiquetadores."""

    family: str
    kappa: float
    ci: tuple[float, float]
    prevalence: float
    """Prevalencia según el primer etiquetador (la referencia humana)."""

    @property
    def judged(self) -> bool:
        return self.prevalence >= MIN_PREVALENCE


def cohen_kappa(
    a: Sequence[object],
    b: Sequence[object],
    w: Sequence[float] | NDArray[np.floating] | None = None,
) -> float:
    """κ de Cohen; 0 si el acuerdo esperado es total (como scikit-learn)."""
    if len(a) != len(b):
        raise ValueError("label sequences must align")
    weights = np.ones(len(a)) if w is None else np.asarray(w, dtype=float)
    cats = sorted({*a, *b}, key=str)
    idx = {c: i for i, c in enumerate(cats)}
    m = np.zeros((len(cats), len(cats)))
    for x, y, wi in zip(a, b, weights, strict=True):
        m[idx[x], idx[y]] += wi
    m /= m.sum()
    observed = np.trace(m)
    expected = float(m.sum(axis=1) @ m.sum(axis=0))
    return (
        0.0 if expected == 1 else float((observed - expected) / (1 - expected))
    )


def macro_f1(
    y_true: Sequence[object],
    y_pred: Sequence[object],
    labels: Sequence[object],
    w: Sequence[float] | NDArray[np.floating] | None = None,
) -> float:
    """Media del F1 de cada clase de ``labels``; 0 en una clase sin casos."""
    if len(y_true) != len(y_pred):
        raise ValueError("label sequences must align")
    weights = np.ones(len(y_true)) if w is None else np.asarray(w, dtype=float)
    t, p = np.asarray(y_true, dtype=object), np.asarray(y_pred, dtype=object)
    scores = []
    for label in labels:
        tp = weights[(t == label) & (p == label)].sum()
        denom = weights[t == label].sum() + weights[p == label].sum()
        scores.append(0.0 if denom == 0 else 2 * tp / denom)
    return float(np.mean(scores))


def exact_agreement(
    a: Sequence[frozenset[str]], b: Sequence[frozenset[str]]
) -> float:
    """Proporción de textos con el mismo conjunto de familias."""
    if len(a) != len(b) or not a:
        raise ValueError("label sequences must align and not be empty")
    return float(np.mean([x == y for x, y in zip(a, b, strict=True)]))


def exact_agreement_ci(
    a: Sequence[frozenset[str]],
    b: Sequence[frozenset[str]],
    n_boot: int = BOOT,
    seed: int = SEED,
) -> tuple[float, float]:
    """IC 95 % *bootstrap* del acuerdo exacto."""
    exact = np.array([x == y for x, y in zip(a, b, strict=True)])
    rng = np.random.default_rng(seed)
    n = len(exact)
    boots = [exact[rng.integers(0, n, n)].mean() for _ in range(n_boot)]
    return float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def family_kappa(
    a: Sequence[frozenset[str]],
    b: Sequence[frozenset[str]],
    family: str,
    n_boot: int = BOOT,
    seed: int = SEED,
) -> FamilyAgreement:
    """κ de presencia de ``family`` con IC 95 % *bootstrap*.

    Se omiten las réplicas donde nadie marcó la familia.
    """
    x = np.array([family in s for s in a])
    y = np.array([family in s for s in b])
    rng = np.random.default_rng(seed)
    n = len(x)
    ks = []
    for _ in range(n_boot):
        i = rng.integers(0, n, n)
        if x[i].any() or y[i].any():
            ks.append(cohen_kappa(list(x[i]), list(y[i])))
    ci = (
        (float(np.percentile(ks, 2.5)), float(np.percentile(ks, 97.5)))
        if ks
        else (0.0, 0.0)
    )
    return FamilyAgreement(
        family=family,
        kappa=cohen_kappa(list(x), list(y)),
        ci=ci,
        prevalence=float(x.mean()),
    )
