"""*Prediction-powered inference* de los KPI.

Port de ``voc_analytics.calibration.ppi`` sin Polars: la media ponderada
(Hájek) del oro se corrige con las predicciones sobre el corpus sin
etiquetar. λ es el PPI++ (Angelopoulos et al., 2023) recortado a [0, 1]:
con λ = 0 queda la estimación solo-oro. Las celdas banco × periodo se
combinan pesando por su tamaño poblacional (suma de 1 / π del corpus).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

Z: Final = 1.959964
SCORE: Final = {"NEG": -1, "NEU": 0, "POS": 1}

Array = NDArray[np.floating]


@dataclass(frozen=True, slots=True)
class Estimate:
    """Estimación PPI de una celda o de la combinación de varias."""

    value: float
    var: float
    classic: float
    """Media ponderada solo con el oro."""
    var_classic: float
    predictor: float
    """Media ponderada de las predicciones en el corpus (versión cruda)."""
    size: float
    n_gold: int
    n_unlabeled: int
    lam: float | None
    """λ de la celda; ``None`` en una combinación."""

    @property
    def ci(self) -> tuple[float, float]:
        half = Z * self.var**0.5
        return self.value - half, self.value + half

    @property
    def classic_ci(self) -> tuple[float, float]:
        half = Z * self.var_classic**0.5
        return self.classic - half, self.classic + half


def _wmean(x: NDArray[np.float64], w: NDArray[np.float64]) -> float:
    return float(np.average(x, weights=w))


def _wvar_of_mean(x: NDArray[np.float64], w: NDArray[np.float64]) -> float:
    """Varianza de la media de Hájek (linealización)."""
    m = _wmean(x, w)
    return float(np.sum(w**2 * (x - m) ** 2) / np.sum(w) ** 2)


def ppi_mean(
    y_gold: Array,
    yhat_gold: Array,
    yhat_unlabeled: Array,
    w: Array | None = None,
    w_unlabeled: Array | None = None,
) -> Estimate:
    """PPI de la media de ``y`` en una celda.

    ``w`` y ``w_unlabeled`` son los pesos 1 / π del oro y del corpus; sin
    pesos, todos valen 1.
    """
    y = np.asarray(y_gold, dtype=np.float64)
    fg = np.asarray(yhat_gold, dtype=np.float64)
    fu = np.asarray(yhat_unlabeled, dtype=np.float64)
    if y.shape != fg.shape:
        raise ValueError("gold labels and predictions must align")
    if y.size == 0 or fu.size == 0:
        raise ValueError("a cell needs gold and unlabeled rows")
    wg = np.ones_like(y) if w is None else np.asarray(w, dtype=np.float64)
    wu = (
        np.ones_like(fu)
        if w_unlabeled is None
        else np.asarray(w_unlabeled, dtype=np.float64)
    )
    n, big_n = len(y), len(fu)
    var_f = np.average((fg - _wmean(fg, wg)) ** 2, weights=wg)
    cov = np.average((y - _wmean(y, wg)) * (fg - _wmean(fg, wg)), weights=wg)
    lam = (
        0.0
        if var_f == 0
        else float(np.clip(cov / ((1 + n / big_n) * var_f), 0, 1))
    )
    return Estimate(
        value=_wmean(y, wg) + lam * (_wmean(fu, wu) - _wmean(fg, wg)),
        var=_wvar_of_mean(y - lam * fg, wg) + lam**2 * _wvar_of_mean(fu, wu),
        classic=_wmean(y, wg),
        var_classic=_wvar_of_mean(y, wg),
        predictor=_wmean(fu, wu),
        size=float(wu.sum()),
        n_gold=n,
        n_unlabeled=big_n,
        lam=lam,
    )


def combine(cells: Sequence[Estimate]) -> Estimate:
    """Combina celdas (banco × periodo) pesando por su tamaño poblacional."""
    if not cells:
        raise ValueError("nothing to combine")
    total = sum(c.size for c in cells)
    share = [c.size / total for c in cells]
    return Estimate(
        value=sum(s * c.value for s, c in zip(share, cells, strict=True)),
        var=sum(s**2 * c.var for s, c in zip(share, cells, strict=True)),
        classic=sum(s * c.classic for s, c in zip(share, cells, strict=True)),
        var_classic=sum(
            s**2 * c.var_classic for s, c in zip(share, cells, strict=True)
        ),
        predictor=sum(
            s * c.predictor for s, c in zip(share, cells, strict=True)
        ),
        size=total,
        n_gold=sum(c.n_gold for c in cells),
        n_unlabeled=sum(c.n_unlabeled for c in cells),
        lam=None,
    )


def _scores(labels: Sequence[str]) -> NDArray[np.float64]:
    return np.array([SCORE[x] for x in labels], dtype=np.float64)


def gap_stars(
    stars_gold: Sequence[str],
    y_gold: Sequence[str],
    yhat_gold: Sequence[str],
    stars_unlabeled: Sequence[str],
    yhat_unlabeled: Sequence[str],
    w: Array | None = None,
    w_unlabeled: Array | None = None,
) -> Estimate:
    """*Gap* en estrellas: puntaje de las estrellas menos el del texto.

    Las estrellas y el texto van como clase (``NEG``, ``NEU``, ``POS``,
    puntajes −1, 0 y 1). Positivo: las estrellas son mejores que el texto.
    Es la brecha neta con el signo cambiado.
    """
    stars_g = _scores(stars_gold)
    return ppi_mean(
        stars_g - _scores(y_gold),
        stars_g - _scores(yhat_gold),
        _scores(stars_unlabeled) - _scores(yhat_unlabeled),
        w,
        w_unlabeled,
    )
