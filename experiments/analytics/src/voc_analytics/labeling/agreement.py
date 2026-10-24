"""Acuerdo y estimaciones ponderadas del oro (EPIC-5, feature 5.3).

Lo comparten los análisis de `analysis/` (`analyze_gold_v0`,
`analyze_gold_v0_r2`, `analyze_gold_v1` y `validate_prompt`).
"""

from collections import Counter

import polars as pl

CLASSES = ["NEG", "NEU", "POS", "NA"]


def kappa(a: list, b: list) -> dict:
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n / n
    k = (observed - expected) / (1 - expected) if expected < 1 else 1.0
    return {"n": n, "acuerdo": round(observed, 3), "kappa": round(k, 3)}


def confusion(df: pl.DataFrame, row: str, col: str) -> list[dict]:
    return (
        df.group_by(row, col)
        .len()
        .pivot(on=col, index=row, values="len")
        .fill_null(0)
        .sort(row)
        .to_dicts()
    )


def weighted_share(df: pl.DataFrame, flag: str) -> dict:
    """Proporción poblacional y error estándar (estratificado, sin fpc)."""
    strata = df.group_by("estrato").agg(
        pl.len().alias("n_h"),
        (1 / pl.col("prob_inclusion").first() * pl.len()).alias("N_h"),
        pl.col(flag).cast(pl.Float64).mean().alias("p_h"),
    )
    total = strata["N_h"].sum()
    strata = strata.with_columns(W_h=pl.col("N_h") / total)
    p = (strata["W_h"] * strata["p_h"]).sum()
    var = (
        strata["W_h"] ** 2
        * strata["p_h"]
        * (1 - strata["p_h"])
        / (strata["n_h"] - 1).clip(lower_bound=1)
    ).sum()
    return {"p": round(p, 4), "se": round(var**0.5, 4), "n": df.height}
