"""Series de deriva del monitor.

Port de ``voc_analytics.scale.drift_baseline`` sin Polars ni rutas: el z
robusto de una serie mensual contra sus meses previos, el PSI de la
distribución de longitud y el mes desde el que se vigila cada banco. Los
umbrales no viven aquí: los pone la ``drift_policy`` de cada banco.
"""

from collections.abc import Mapping, Sequence
from typing import Final

import numpy as np

BINS: Final = (0, 1, 2, 5, 10, 20, 40, 60, 10_000)
"""Bordes de la longitud en palabras (intervalos cerrados a la derecha)."""

MAD_SCALE: Final = 1.4826


def length_bin(words: int) -> int:
    """Índice del intervalo de ``BINS`` al que pertenece ``words``.

    Igual que ``pl.cut(BINS[1:-1], left_closed=False)``: ``(-inf, 1]``,
    ``(1, 2]``, …, ``(60, inf)``.
    """
    return int(np.searchsorted(BINS[1:-1], words, side="left"))


def length_histogram(words: Sequence[int]) -> list[int]:
    """Conteo por intervalo de ``BINS`` (8 intervalos)."""
    counts = [0] * (len(BINS) - 1)
    for w in words:
        counts[length_bin(w)] += 1
    return counts


def robust_z(
    values: Sequence[float | None], baseline: int = 12, min_baseline: int = 6
) -> float | None:
    """z robusto del último valor contra los ``baseline`` previos.

    Mediana y 1.4826·MAD de los previos no nulos; ``None`` si el último es
    nulo o hay menos de ``min_baseline`` previos. El denominador tiene piso
    (1 % de la mediana) para que una serie constante no divida por cero.
    """
    if not values or values[-1] is None:
        return None
    hist = [x for x in values[-baseline - 1 : -1] if x is not None]
    if len(hist) < min_baseline:
        return None
    med = float(np.median(hist))
    mad = MAD_SCALE * float(np.median(np.abs(np.array(hist) - med)))
    return (values[-1] - med) / max(mad, 0.01 * max(abs(med), 1e-6), 1e-6)


def psi(
    current: Sequence[int], reference: Sequence[int], floor: float = 1e-4
) -> float:
    """PSI entre dos histogramas de conteos con los mismos intervalos.

    Las proporciones se recortan en ``floor`` (sin renormalizar), como en
    el análisis histórico. La referencia es la suma de los meses previos.
    """
    cur = np.asarray(current, dtype=np.float64)
    ref = np.asarray(reference, dtype=np.float64)
    if cur.shape != ref.shape:
        raise ValueError("histograms must have the same bins")
    if cur.sum() == 0 or ref.sum() == 0:
        raise ValueError("histograms must not be empty")
    p = np.clip(cur / cur.sum(), floor, None)
    q = np.clip(ref / ref.sum(), floor, None)
    return float(np.sum((p - q) * np.log(p / q)))


def _month_range(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    out = []
    while (key := f"{y:04d}-{m:02d}") <= last:
        out.append(key)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def entry_month(
    rows_by_month: Mapping[str, int], min_rows: int = 200, months: int = 12
) -> str | None:
    """Primer mes que cierra ``months`` meses seguidos con ``min_rows`` filas.

    Las claves son ``YYYY-MM``; un mes ausente cuenta como cero filas y
    corta la racha. ``None`` si el banco todavía no entra al monitor.
    """
    if not rows_by_month:
        return None
    run = 0
    for key in _month_range(min(rows_by_month), max(rows_by_month)):
        run = run + 1 if rows_by_month.get(key, 0) >= min_rows else 0
        if run == months:
            return key
    return None
