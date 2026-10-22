"""Muestra sin etiqueta para PPI con M4 (EPIC-5, feature 5.6, opción B1).

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.sampling.sample_ppi \\
        data/tds_<SNAPSHOT>.parquet

PPI necesita un predictor independiente de la muestra sin etiqueta, y M4 se
entrenó con la plata. Esta muestra repite el diseño de `sample_silver.py`
(decisión del autor, 2026-10-22) sobre las filas que no están en la plata ni
en ninguna cola del oro:

* **Marco:** filas elegibles (`eligibility_rules_v0.1`) menos las reseñas de
  `silver_v0` y del oro. Lo excluido es ~4 % del corpus y son muestras
  probabilísticas, así que el marco sigue representando la población; π se
  calcula sobre este marco.
* **Estratos y asignación:** los de la plata (banco × periodo × estrellas,
  20 000 filas por banco proporcionales a la raíz del tamaño del estrato).
* **Selección:** hash de `id_resena` con otra semilla.
* **Sin etiquetado:** no se llama a Gemini; M4 la predice en Kaggle.

Escribe en `data/labels/ppi_v0/` (fuera de git): `rows.parquet`,
`texts.parquet` (un registro por texto único) y `sample_meta.json`.
"""

import json
import sys
from pathlib import Path

import polars as pl

from voc_analytics.labeling.eligibility import RULES_VERSION, with_tnss_rule
from voc_analytics.paths import LABELS
from voc_analytics.sampling.sample_silver import PER_BANK, period
from voc_analytics.sentiment.data import gold_ids

SEED = 20261022
OUT = LABELS / "ppi_v0"
SILVER_ROWS = LABELS / "silver_v0" / "rows.parquet"


def main(snapshot: str) -> None:
    excluded = set(pl.read_parquet(SILVER_ROWS)["id_resena"]) | gold_ids()
    raw = pl.read_parquet(
        snapshot,
        columns=[
            "id_resena",
            "bank_id",
            "texto_sanitizado",
            "texto_limpio",
            "estrellas",
            "fecha",
        ],
    )
    df = (
        with_tnss_rule(raw)
        .filter(pl.col("tnss_rule").is_null())
        .filter(~pl.col("id_resena").is_in(list(excluded)))
        .with_columns(
            periodo=period(),
            clave=pl.col("texto_limpio")
            .str.to_lowercase()
            .str.replace_all(r"[^\p{L}\p{N}]+", ""),
        )
    )
    cells = ["bank_id", "periodo", "estrellas"]
    alloc = (
        df.group_by(cells)
        .len("N_h")
        .with_columns(w=pl.col("N_h").cast(pl.Float64).sqrt())
        .with_columns(
            n_h=(pl.col("w") / pl.col("w").sum().over("bank_id") * PER_BANK)
            .round()
            .cast(pl.Int64)
            .clip(upper_bound=pl.col("N_h"))
        )
        .drop("w")
    )
    rows = (
        df.join(alloc, on=cells)
        .with_columns(
            orden=pl.col("id_resena").hash(SEED).rank("ordinal").over(cells)
        )
        .filter(pl.col("orden") <= pl.col("n_h"))
        .with_columns(prob_inclusion=pl.col("n_h") / pl.col("N_h"))
    )
    texts = (
        rows.sort("orden")
        .group_by("texto_limpio", maintain_order=True)
        .agg(pl.col("texto_sanitizado").first(), pl.col("clave").first())
        .sort("texto_limpio")
        .with_row_index("text_id")
    )
    rows = rows.join(
        texts.select("texto_limpio", "text_id"), on="texto_limpio"
    ).select(
        "id_resena",
        "bank_id",
        "periodo",
        "estrellas",
        "fecha",
        "N_h",
        "n_h",
        "prob_inclusion",
        "text_id",
    )
    overlap = rows.filter(pl.col("id_resena").is_in(list(excluded))).height
    if overlap:
        raise SystemExit(f"{overlap} filas de la plata o del oro en la muestra")
    OUT.mkdir(parents=True, exist_ok=True)
    rows.sort("bank_id", "periodo", "estrellas").write_parquet(
        OUT / "rows.parquet"
    )
    texts.drop("texto_limpio").write_parquet(OUT / "texts.parquet")
    meta = {
        "snapshot_file": Path(snapshot).name,
        "rules_version": RULES_VERSION,
        "seed": SEED,
        "per_bank": PER_BANK,
        "allocation": "sqrt(N_h) dentro de banco, tope N_h",
        "excluded_rows": len(excluded),
        "frame_rows": df.height,
        "cells": alloc.height,
        "rows": rows.height,
        "rows_by_bank": dict(
            rows.group_by("bank_id").len().sort("bank_id").iter_rows()
        ),
        "unique_texts": texts.height,
        "overlap_with_excluded": overlap,
    }
    (OUT / "sample_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
