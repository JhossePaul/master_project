"""Conjunto de plata con Gemini (EPIC-5, feature 5.3).

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.sampling.sample_silver sample \\
        data/tds_<SNAPSHOT>.parquet
    uv run python -m voc_analytics.sampling.sample_silver label [--limit N]

Diseño (aprobado el 2026-10-18):

* **Marco:** filas elegibles (`eligibility_rules_v0.1`).
* **Estratos:** banco × periodo × estrellas, solo donde el banco tiene filas.
  Los periodos son `<=2017`, un periodo por año de 2018 a 2025, `2026T1` y
  `holdout` (`fecha` desde 2026-04-01).
* **Asignación:** 20 000 filas por banco. Dentro de cada banco se reparten
  proporcionales a la raíz cuadrada del tamaño de cada estrato, sin pasar de
  ese tamaño. Probabilidad de inclusión `n_h / N_h`.
* **Selección:** aleatoria dentro del estrato, ordenando por un hash con semilla
  de `id_resena`, que es determinista.
* **Reglas antifuga del holdout** (partición por fila):
  * `entrenamiento`: `fecha` antes del corte. Es lo único que entra al
    entrenamiento.
  * `holdout_nuevo`: `fecha` desde el corte y texto cuya primera aparición en
    el corpus elegible también es desde el corte. Es lo único que evalúa la
    deriva.
  * `holdout_visto`: `fecha` desde el corte con un texto ya visto antes. Queda
    fuera del entrenamiento y de la evaluación de deriva; se reporta aparte.
  * La primera aparición se calcula sobre una clave normalizada (`clave`:
    solo letras y dígitos), para que variantes de puntuación o espacios como
    "Excelente!!" y "excelente" cuenten como el mismo texto.
* **Etiquetado:** una vez por texto único con `prompt_v3`; la etiqueta se
  propaga a sus filas.

Escribe en `data/labels/silver_v0/` (fuera de git):

* `rows.parquet`: filas muestreadas con estrato, probabilidad, `text_id` y
  contexto temporal (`temporal_context.py`): `dia_mes`, `quincena`,
  `dias_desde_version`, `dias_desde_feature`, `dia_pico_total` (pico de
  volumen total) y `dia_pico_estrella` (pico del nivel de estrellas de la
  reseña). Son atributos para análisis, no estratos;
* `texts.parquet`: textos únicos con su partición;
* `labels_prompt_v3.parquet` y `run_<run>.json`;
* `checkpoint_prompt_v3.jsonl`, para reanudar.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import polars as pl

from voc_analytics.labeling.eligibility import RULES_VERSION, with_tnss_rule
from voc_analytics.labeling.label_gemini import label_frame
from voc_analytics.labeling.temporal_context import attach, local_day
from voc_analytics.paths import LABELS

SEED = 20261018
PER_BANK = 20_000
CUTOFF = datetime(2026, 4, 1)
PROMPT_VERSION = "prompt_v3"
WORKERS = 8
MAX_COST_USD = 10.0
OUT = LABELS / "silver_v0"
CHECKPOINT = OUT / f"checkpoint_{PROMPT_VERSION}.jsonl"


def period() -> pl.Expr:
    year = pl.col("fecha").dt.year()
    return (
        pl.when(pl.col("fecha") >= CUTOFF)
        .then(pl.lit("holdout"))
        .when(year <= 2017)
        .then(pl.lit("<=2017"))
        .when(year == 2026)
        .then(pl.lit("2026T1"))
        .otherwise(year.cast(pl.String))
    )


def leakage_checks(rows: pl.DataFrame, texts: pl.DataFrame) -> dict:
    """Verifica las reglas antifuga; falla si alguna no se cumple."""
    keys = rows.join(texts.select("text_id", "clave"), on="text_id")
    train = set(keys.filter(pl.col("split") == "entrenamiento")["clave"])
    new = set(keys.filter(pl.col("split") == "holdout_nuevo")["clave"])
    checks = {
        "claves_holdout_nuevo_en_entrenamiento": len(train & new),
        "filas_entrenamiento_despues_del_corte": rows.filter(
            (pl.col("split") == "entrenamiento") & (pl.col("fecha") >= CUTOFF)
        ).height,
        "filas_holdout_antes_del_corte": rows.filter(
            pl.col("split").str.starts_with("holdout")
            & (pl.col("fecha") < CUTOFF)
        ).height,
    }
    if any(checks.values()):
        raise SystemExit(f"Falla la regla antifuga: {checks}")
    return checks


def sample(snapshot: str) -> None:
    raw = pl.read_parquet(
        snapshot,
        columns=[
            "id_resena",
            "bank_id",
            "texto_sanitizado",
            "texto_limpio",
            "estrellas",
            "fecha",
            "version_app",
        ],
    ).with_columns(dia=local_day())
    # El calendario de releases y los picos usan todo el corpus.
    context = raw.select("bank_id", "version_app", "dia", "estrellas")
    df = with_tnss_rule(raw.drop("version_app")).filter(
        pl.col("tnss_rule").is_null()
    )
    df = df.with_columns(
        periodo=period(),
        clave=pl.col("texto_limpio")
        .str.to_lowercase()
        .str.replace_all(r"[^\p{L}\p{N}]+", ""),
    ).with_columns(primera=pl.col("fecha").min().over("clave"))
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
        .with_columns(
            prob_inclusion=pl.col("n_h") / pl.col("N_h"),
            split=pl.when(pl.col("fecha") < CUTOFF)
            .then(pl.lit("entrenamiento"))
            .when(pl.col("primera") >= CUTOFF)
            .then(pl.lit("holdout_nuevo"))
            .otherwise(pl.lit("holdout_visto")),
        )
    )
    texts = (
        rows.sort("orden")
        .group_by("texto_limpio", maintain_order=True)
        .agg(
            pl.col("texto_sanitizado").first(),
            pl.col("clave").first(),
            pl.col("split").unique().sort().alias("splits"),
            pl.len().alias("filas_en_muestra"),
        )
        .sort("texto_limpio")
        .with_row_index("text_id")
    )
    rows = rows.join(texts.select("texto_limpio", "text_id"), on="texto_limpio")
    rows = rows.select(
        "id_resena",
        "bank_id",
        "periodo",
        "estrellas",
        "fecha",
        "dia",
        "N_h",
        "n_h",
        "prob_inclusion",
        "split",
        "text_id",
    )
    rows = attach(rows, context).sort("bank_id", "periodo", "estrellas", "dia")
    checks = leakage_checks(rows, texts)
    OUT.mkdir(parents=True, exist_ok=True)
    rows.write_parquet(OUT / "rows.parquet")
    texts.drop("texto_limpio").write_parquet(OUT / "texts.parquet")
    # Costo esperado con las tasas de prompt_v3 medidas en el oro.
    chars = texts["texto_sanitizado"].str.len_chars().sum()
    estimate = (
        (chars * 0.272 + texts.height / 100 * 640) * 0.75
        + texts.height * 6.8 * 3.75
    ) / 1e6
    meta = {
        "snapshot_file": Path(snapshot).name,
        "rules_version": RULES_VERSION,
        "seed": SEED,
        "per_bank": PER_BANK,
        "cutoff": CUTOFF.date().isoformat(),
        "allocation": "sqrt(N_h) dentro de banco, tope N_h",
        "cells": alloc.height,
        "rows": rows.height,
        "rows_by_bank": dict(
            rows.group_by("bank_id").len().sort("bank_id").iter_rows()
        ),
        "rows_by_split": dict(rows.group_by("split").len().iter_rows()),
        "temporal_context": {
            "share_quincena": round(rows["quincena"].mean(), 4),
            "share_dia_pico_total": round(rows["dia_pico_total"].mean(), 4),
            "share_dia_pico_estrella": round(
                rows["dia_pico_estrella"].mean(), 4
            ),
            "sin_release_previo": rows["dias_desde_version"].null_count(),
            "mediana_dias_desde_version": rows["dias_desde_version"].median(),
        },
        "unique_texts": texts.height,
        "texts_by_splits": {
            "|".join(k): v
            for k, v in texts.group_by("splits").len().iter_rows()
        },
        "leakage_checks": checks,
        "estimated_cost_usd": round(estimate, 2),
    }
    (OUT / "sample_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))


def label(limit: int | None) -> None:
    texts = pl.read_parquet(OUT / "texts.parquet")
    if limit:
        texts = texts.head(limit)
    out, meta = label_frame(
        texts,
        PROMPT_VERSION,
        id_col="text_id",
        workers=WORKERS,
        checkpoint=CHECKPOINT,
        max_cost_usd=MAX_COST_USD,
    )
    meta["limit"] = limit
    if not limit and not meta["pending_batches"] and not meta["failed_batches"]:
        out.write_parquet(OUT / f"labels_{PROMPT_VERSION}.parquet")
    (OUT / f"run_{meta['run']}.json").write_text(
        json.dumps(meta, indent=2) + "\n"
    )
    summary = {k: v for k, v in meta.items() if k != "batches"}
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sample").add_argument("snapshot")
    sub.add_parser("label").add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.command == "sample":
        sample(args.snapshot)
    else:
        label(args.limit)


if __name__ == "__main__":
    main()
