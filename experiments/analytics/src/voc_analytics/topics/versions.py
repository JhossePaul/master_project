"""Normalización de `version_app` por banco (5.5, `topics_design.md` §7.1).

Cada banco tiene su esquema, así que `Major.Minor` no es comparable entre
bancos. Se derivan dos niveles:

* `release`: la versión publicada, sin sufijos de compilación;
* `feature`: `mayor.menor`, como en `labeling.temporal_context`.

Esquemas observados en `tds_20261016T054714Z`:

* AZTECA: `2.3.15` sin cambio; las `2.6.2 - BETA` quedan nulas;
* BANORTE: `7.0.9.45841` → `7.0.9` (el 4.º componente es compilación);
* BBVA: `11.33.210429` → `11.33` (un 3.er componente de 6 dígitos es
  fecha); `10.90` y `25.60.10` sin cambio;
* NUBANK: `9.38.75-minApi28` → `9.38.75`;
* SANTANDER: `5.54.8` y `5.30` sin cambio.

`UNKNOWN` y las `BETA` quedan nulas y se reportan como cobertura.
"""

import polars as pl

MIN_NEG_PER_VERSION = 50  # §7.1: por debajo se agrupan en "OTRAS"


def normalize(df: pl.DataFrame) -> pl.DataFrame:
    """Agrega `release` y `feature` a partir de `bank_id` y `version_app`."""
    v = pl.col("version_app").str.strip_chars()
    valid = (
        (v != "UNKNOWN") & ~v.str.contains("(?i)beta") & v.str.contains(r"^\d")
    )
    base = (
        v.str.replace(r"-minApi\d+$", "")
        .str.extract(r"^([\d.]+)")
        .str.strip_chars(".")
    )
    release = (
        pl.when(pl.col("bank_id") == "BANORTE")
        .then(base.str.extract(r"^(\d+\.\d+\.\d+)"))
        .when(
            (pl.col("bank_id") == "BBVA")
            & base.str.contains(r"^\d+\.\d+\.\d{6}$")
        )
        .then(base.str.extract(r"^(\d+\.\d+)"))
        .otherwise(base)
    )
    return df.with_columns(
        release=pl.when(valid).then(release),
        feature=pl.when(valid).then(base.str.extract(r"^(\d+\.\d+)")),
    )


def group_small(
    df: pl.DataFrame, col: str = "release", n_min: int = MIN_NEG_PER_VERSION
) -> pl.DataFrame:
    """Agrupa en `OTRAS` las versiones con menos de `n_min` filas por banco."""
    counts = df.group_by("bank_id", col).len("_n")
    return (
        df.join(counts, on=["bank_id", col], how="left", nulls_equal=True)
        .with_columns(
            pl.when(pl.col(col).is_not_null() & (pl.col("_n") < n_min))
            .then(pl.lit("OTRAS"))
            .otherwise(pl.col(col))
            .alias(f"{col}_agrupada")
        )
        .drop("_n")
    )
