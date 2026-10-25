"""Periodos de la estratificación del oro (EPIC-5, feature 5.3).

Los definió la primera ronda (`sample_gold_v0`); `sample_gold_v1` los reutiliza
para que los estratos banco × periodo coincidan.
"""

import polars as pl

# Cortes por año de `fecha`; NUBANK no tiene filas elegibles antes de 2020.
PERIODS = {"<=2019": 2019, "2020-2022": 2022, "2023-2024": 2024}


def period() -> pl.Expr:
    year = pl.col("fecha").dt.year()
    expr = pl.lit("2025-2026")
    for label, last in reversed(PERIODS.items()):
        expr = pl.when(year <= last).then(pl.lit(label)).otherwise(expr)
    return expr
