"""PPI contra soluciones calculadas a mano."""

import numpy as np
import pytest
from voc_nlp.ppi import TEXT_SCORE, Z, combine, gap_stars, ppi_mean, targets


def test_ppi_mean_matches_a_hand_solution() -> None:
    # Oro n = 4, corpus N = 4, sin pesos.
    y = [1.0, 0.0, 1.0, 0.0]
    fg = [1.0, 0.0, 0.0, 0.0]
    fu = [1.0, 1.0, 0.0, 0.0]
    est = ppi_mean(y, fg, fu)
    # var(f) = 3/16, cov(y, f) = 1/8 → λ = (1/8) / (2 · 3/16) = 1/3.
    assert est.lam == pytest.approx(1 / 3)
    # 0.5 + 1/3 · (0.5 − 0.25)
    assert est.value == pytest.approx(0.5 + 1 / 12)
    # var(y − λf)/n con y − λf = [2/3, 0, 1, 0] y var(f_u)/N = 1/16 · 1/9.
    r = np.array([2 / 3, 0, 1, 0])
    expected = np.sum((r - r.mean()) ** 2) / 16 + (1 / 9) * (1 / 16)
    assert est.var == pytest.approx(expected)
    assert est.classic == 0.5 and est.var_classic == pytest.approx(1 / 16)
    assert est.predictor == 0.5 and est.size == 4.0
    lo, hi = est.ci
    assert hi - lo == pytest.approx(2 * Z * expected**0.5)


def test_constant_predictor_falls_back_to_gold_only() -> None:
    est = ppi_mean([1.0, 0.0, 1.0], [1.0, 1.0, 1.0], [1.0, 1.0])
    assert est.lam == 0.0
    assert est.value == pytest.approx(2 / 3) and est.ci == est.classic_ci


def test_weights_are_hajek_means() -> None:
    est = ppi_mean([1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [3.0, 1.0], [1.0, 3.0])
    assert est.classic == pytest.approx(0.75)
    assert est.predictor == pytest.approx(0.75) and est.size == 4.0


def test_bad_cells_are_rejected() -> None:
    with pytest.raises(ValueError, match="align"):
        ppi_mean([1.0], [1.0, 0.0], [1.0])
    with pytest.raises(ValueError, match="needs"):
        ppi_mean([], [], [1.0])
    with pytest.raises(ValueError, match="nothing"):
        combine([])


def test_combine_weights_cells_by_size() -> None:
    a = ppi_mean([1.0, 0.0], [1.0, 0.0], [1.0] * 3)
    b = ppi_mean([0.0, 0.0], [0.0, 1.0], [0.0])
    both = combine([a, b])
    assert both.value == pytest.approx(0.75 * a.value + 0.25 * b.value)
    assert both.var == pytest.approx(0.75**2 * a.var + 0.25**2 * b.var)
    assert both.predictor == pytest.approx(0.75)
    assert (both.n_gold, both.n_unlabeled, both.lam) == (4, 4, None)


def test_gap_stars_uses_the_one_to_five_scale() -> None:
    stars = [5, 4, 1, 3]
    text = ["NEG", "POS", "NEG", "NEU"]
    est = gap_stars(stars, text, text, stars, text)
    # 5 − 1, 4 − 5, 1 − 1, 3 − 3 → media 3 / 4; con predicciones perfectas y
    # n = N, λ = 1 / 2.
    assert est.classic == pytest.approx(0.75)
    assert est.value == pytest.approx(0.75)
    assert est.lam == pytest.approx(0.5)
    assert TEXT_SCORE == {"NEG": 1, "NEU": 3, "POS": 5}


def test_targets_classify_stars_against_text() -> None:
    out = targets(
        [1, 2, 3, 4, 5, 5], ["POS", "NEG", "NEG", "NEU", "POS", "NEG"]
    )
    assert out["neg"].tolist() == [0, 1, 1, 0, 0, 1]
    assert out["gap_estrellas"].tolist() == [-4, 1, 2, 1, 0, 4]
    assert out["texto_peor"].tolist() == [0, 0, 1, 1, 0, 1]
    assert out["texto_mejor"].tolist() == [1, 0, 0, 0, 0, 0]
    assert out["estrellas_NEG_texto_POS"].tolist() == [1, 0, 0, 0, 0, 0]
    assert out["estrellas_POS_texto_NEG"].tolist() == [0, 0, 0, 0, 0, 1]
    cells = [k for k in out if k.startswith("estrellas_")]
    assert len(cells) == 9
    # Cada reseña cae en una sola celda de la matriz.
    assert sum(out[k] for k in cells).tolist() == [1] * 6


@pytest.mark.parametrize(
    ("stars", "text"), [([0], ["NEG"]), ([6], ["NEG"]), ([1, 2], ["NEG"])]
)
def test_targets_reject_bad_input(stars: list[int], text: list[str]) -> None:
    with pytest.raises(ValueError):
        targets(stars, text)
