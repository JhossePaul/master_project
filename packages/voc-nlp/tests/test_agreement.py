"""κ de Cohen, acuerdo exacto y κ por familia en casos calculados a mano."""

import numpy as np
import pytest
from voc_nlp.agreement import (
    MIN_PREVALENCE,
    cohen_kappa,
    exact_agreement,
    exact_agreement_ci,
    family_kappa,
    macro_f1,
)


def test_cohen_kappa_matches_a_hand_solution() -> None:
    a = ["NEG", "NEG", "POS", "POS"]
    b = ["NEG", "POS", "POS", "POS"]
    # p_o = 3/4, p_e = 1/2·1/4 + 1/2·3/4 = 1/2 → κ = 1/2.
    assert cohen_kappa(a, b) == pytest.approx(0.5)
    assert cohen_kappa(a, a) == 1.0
    assert cohen_kappa(["NEU"] * 3, ["NEU"] * 3) == 0.0


def test_weights_count_as_repeated_rows() -> None:
    a, b = ["NEG", "NEG", "POS"], ["NEG", "POS", "POS"]
    repeated = cohen_kappa(a + ["POS"], b + ["POS"])
    assert cohen_kappa(a, b, [1.0, 1.0, 2.0]) == pytest.approx(repeated)


def test_cohen_kappa_matches_scikit_learn_when_available() -> None:
    metrics = pytest.importorskip("sklearn.metrics")
    rng = np.random.default_rng(3)
    a = list(rng.choice(["NEG", "NEU", "POS"], 200))
    b = list(rng.choice(["NEG", "NEU", "POS"], 200))
    w = rng.uniform(1, 5, 200)
    expected = metrics.cohen_kappa_score(a, b, sample_weight=w)
    assert cohen_kappa(a, b, w) == pytest.approx(expected)


LABELS = ("NEG", "NEU", "POS")


def test_macro_f1_matches_a_hand_solution() -> None:
    y = ["NEG", "NEG", "POS", "POS"]
    p = ["NEG", "POS", "POS", "POS"]
    # F1: NEG 2/3, POS 4/5 y NEU 0 (sin casos ni predicciones).
    assert macro_f1(y, p, LABELS) == pytest.approx((2 / 3 + 4 / 5) / 3)
    assert macro_f1(y, p, ("NEG", "POS"), [1.0, 1.0, 2.0, 2.0]) == (
        pytest.approx(
            macro_f1(y + ["POS"] * 2, p + ["POS"] * 2, ("NEG", "POS"))
        )
    )
    with pytest.raises(ValueError):
        macro_f1(y, p[:2], LABELS)


def test_macro_f1_matches_scikit_learn_when_available() -> None:
    metrics = pytest.importorskip("sklearn.metrics")
    rng = np.random.default_rng(5)
    a = list(rng.choice(["NEG", "NEU", "POS"], 200))
    b = list(rng.choice(["NEG", "POS"], 200))
    w = rng.uniform(1, 5, 200)
    expected = metrics.f1_score(
        a,
        b,
        labels=list(LABELS),
        average="macro",
        sample_weight=w,
        zero_division=0,
    )
    assert macro_f1(a, b, LABELS, w) == pytest.approx(expected)


def test_exact_agreement_compares_whole_sets() -> None:
    a = [frozenset({"FA", "UX"}), frozenset({"TR"}), frozenset()]
    b = [frozenset({"FA"}), frozenset({"TR"}), frozenset()]
    assert exact_agreement(a, b) == pytest.approx(2 / 3)
    lo, hi = exact_agreement_ci(a * 50, b * 50, n_boot=300)
    assert lo < 2 / 3 < hi
    with pytest.raises(ValueError):
        exact_agreement(a, b[:2])
    with pytest.raises(ValueError):
        cohen_kappa(["NEG"], [])


def test_family_kappa_and_its_prevalence() -> None:
    a = [frozenset({"FA"})] * 10 + [frozenset()] * 30
    b = [frozenset({"FA"})] * 8 + [frozenset()] * 32
    fam = family_kappa(a, b, "FA", n_boot=300)
    assert fam.prevalence == 0.25 and fam.judged
    assert fam.ci[0] <= fam.kappa <= fam.ci[1] <= 1.0
    assert family_kappa(a, b, "FA", n_boot=300) == fam


def test_absent_family_is_not_judged() -> None:
    a = [frozenset({"FA"})] * 20
    fam = family_kappa(a, a, "DI", n_boot=50)
    assert fam.prevalence == 0.0 < MIN_PREVALENCE and not fam.judged
    assert fam.ci == (0.0, 0.0)
