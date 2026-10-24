"""Las series de deriva reproducen ``drift_baseline`` (5.7) en sintéticos."""

import numpy as np
import pytest
from voc_nlp.drift import (
    BINS,
    entry_month,
    length_bin,
    length_histogram,
    psi,
    robust_z,
)


def _reference_z(values: list) -> list:
    """``drift_baseline.robust_z`` de EPIC-5, copiado tal cual."""
    out = []
    for i, v in enumerate(values):
        hist = [x for x in values[max(0, i - 12) : i] if x is not None]
        if v is None or len(hist) < 6:
            out.append(None)
            continue
        med = float(np.median(hist))
        mad = 1.4826 * float(np.median(np.abs(np.array(hist) - med)))
        out.append((v - med) / max(mad, 0.01 * max(abs(med), 1e-6), 1e-6))
    return out


def test_robust_z_matches_drift_baseline_on_a_series() -> None:
    rng = np.random.default_rng(7)
    series: list[float | None] = list(rng.normal(10, 2, 40))
    series[3] = series[15] = None
    expected = _reference_z(series)
    got = [robust_z(series[: i + 1]) for i in range(len(series))]
    assert got == pytest.approx(expected)


def test_robust_z_needs_history_and_a_value() -> None:
    assert robust_z([]) is None
    assert robust_z([1.0] * 5 + [2.0]) is None
    assert robust_z([1.0] * 6 + [None]) is None


def test_constant_series_has_a_floor_instead_of_zero_mad() -> None:
    assert robust_z([10.0] * 12 + [11.0]) == pytest.approx(10.0)


def test_length_bins_are_right_closed() -> None:
    assert len(BINS) == 9
    assert [length_bin(w) for w in (0, 1, 2, 3, 5, 6, 60, 61, 500)] == [
        0,
        0,
        1,
        2,
        2,
        3,
        6,
        7,
        7,
    ]
    assert length_histogram([1, 1, 2, 61]) == [2, 1, 0, 0, 0, 0, 0, 1]


def test_psi_matches_drift_baseline_formula() -> None:
    cur, ref = [5, 0, 10, 3], [20, 4, 30, 0]
    p = np.clip(np.array(cur) / 18, 1e-4, None)
    q = np.clip(np.array(ref) / 54, 1e-4, None)
    expected = float(np.sum((p - q) * np.log(p / q)))
    assert psi(cur, ref) == pytest.approx(expected)
    assert psi(ref, ref) == 0.0


def test_psi_rejects_bad_histograms() -> None:
    with pytest.raises(ValueError, match="same bins"):
        psi([1, 2], [1, 2, 3])
    with pytest.raises(ValueError, match="empty"):
        psi([0, 0], [1, 1])


def test_entry_month_needs_twelve_full_months_in_a_row() -> None:
    rows = {f"2020-{m:02d}": 250 for m in range(1, 13)}
    rows |= {f"2021-{m:02d}": 250 for m in range(1, 13)}
    assert entry_month(rows) == "2020-12"
    rows["2020-06"] = 199
    assert entry_month(rows) == "2021-06"
    del rows["2020-09"]
    assert entry_month(rows) == "2021-09"


def test_entry_month_none_when_never_reached() -> None:
    assert entry_month({}) is None
    assert entry_month({"2020-01": 500, "2020-03": 500}) is None
