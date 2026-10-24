"""κ de Cohen, acuerdo exacto y κ por familia en casos calculados a mano."""

import numpy as np
import pytest
from voc_nlp.agreement import (
    MIN_PREVALENCE,
    cohen_kappa,
    exact_agreement,
    exact_agreement_ci,
    family_kappa,
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
