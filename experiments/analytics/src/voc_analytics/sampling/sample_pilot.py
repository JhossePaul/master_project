"""Muestra del piloto de etiquetado con Gemini (EPIC-5, feature 5.3).

**Histórico:** piloto `pilot_v0` cerrado; se conserva para reproducir sus
reportes.

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.sampling.sample_pilot \\
        data/tds_<SNAPSHOT>.parquet

Muestra de diseño, no probabilística: sirve para medir tokens, costo y
comportamiento del prompt, no para estimar proporciones del corpus. Estratos
banco × estrellas (25), con cuotas fijas por longitud dentro de cada estrato.
La unidad es el texto único (`texto_limpio`); se envía `texto_sanitizado`.
Escribe en `data/labels/pilot_v0/` (fuera de git).
"""

import json
import sys
from pathlib import Path

import polars as pl

from voc_analytics.labeling.eligibility import RULES_VERSION, with_tnss_rule
from voc_analytics.paths import LABELS

SEED = 20261017
OUT = LABELS / "pilot_v0"
# Cuotas por estrato banco × estrellas; suman 20 (500 en total).
LENGTH_QUOTAS = {"1": 2, "2-5": 6, "6-20": 6, "21-60": 4, ">60": 2}


def length_bucket() -> pl.Expr:
    p = pl.col("palabras")
    return (
        pl.when(p == 1)
        .then(pl.lit("1"))
        .when(p <= 5)
        .then(pl.lit("2-5"))
        .when(p <= 20)
        .then(pl.lit("6-20"))
        .when(p <= 60)
        .then(pl.lit("21-60"))
        .otherwise(pl.lit(">60"))
    )


def main(path: str) -> None:
    df = pl.read_parquet(
        path,
        columns=[
            "id_resena",
            "bank_id",
            "texto_sanitizado",
            "texto_limpio",
            "estrellas",
            "fecha",
        ],
    )
    df = with_tnss_rule(df)
    rows_per_text = df.group_by("texto_limpio").len("filas_texto")
    eligible = (
        df.filter(pl.col("tnss_rule").is_null())
        .with_columns(bucket=length_bucket())
        # Un representante por texto único y estrato, elegido con semilla.
        .sample(fraction=1.0, shuffle=True, seed=SEED)
        .unique(["texto_limpio", "bank_id", "estrellas"], keep="first")
    )

    picked: list[pl.DataFrame] = []
    seen: set[str] = set()
    for _, group in sorted(
        eligible.partition_by(["bank_id", "estrellas"], as_dict=True).items()
    ):
        for bucket, quota in LENGTH_QUOTAS.items():
            pool = group.filter(
                (pl.col("bucket") == bucket)
                & ~pl.col("texto_limpio").is_in(seen)
            )
            take = pool.sample(min(quota, pool.height), seed=SEED)
            seen.update(take["texto_limpio"].to_list())
            picked.append(take)

    sample = (
        pl.concat(picked)
        .join(rows_per_text, on="texto_limpio", how="left")
        .sort("bank_id", "estrellas", "palabras")
        .with_row_index("pilot_id")
    )
    OUT.mkdir(parents=True, exist_ok=True)
    sample.write_parquet(OUT / "sample.parquet")
    meta = {
        "snapshot_file": Path(path).name,
        "rules_version": RULES_VERSION,
        "seed": SEED,
        "length_quotas": LENGTH_QUOTAS,
        "texts": sample.height,
        "by_bucket": dict(sample["bucket"].value_counts().iter_rows()),
    }
    (OUT / "sample_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))
    print(sample.group_by("bank_id", "estrellas").len().sort("len").head(5))


if __name__ == "__main__":
    main(sys.argv[1])
