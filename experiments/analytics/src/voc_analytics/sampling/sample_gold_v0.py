"""Cola del conjunto de oro, primera ronda (EPIC-5, feature 5.3).

**Histórico:** primera ronda del oro (`gold_v0`), superada por
`sample_gold_v1`; se conserva para reproducir sus reportes.

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.sampling.sample_gold_v0 \\
        data/tds_<SNAPSHOT>.parquet

Arma `data/labels/gold_v0/queue.parquet` (fuera de git) en el orden de la
guía de anotación:

1. `calibracion`: 30 textos del piloto (la mitad donde las corridas de Gemini
   discrepan). Se anotan a ciegas y luego se muestra lo que dijo Gemini.
2. `aleatorio`: 400 reseñas elegibles, muestreo aleatorio simple dentro de
   banco × periodo, con probabilidad de inclusión registrada. La mitad de cada
   estrato va a ciegas y la otra mitad asistida (propuesta de `prompt_v1`).
3. `reanotacion`: 5 % del bloque aleatorio a ciegas, repetido al final.

El bloque dirigido (desacuerdos, baja confianza) se agrega cuando exista la
plata. La cola no incluye las estrellas: se unen por `id_resena` al analizar.
"""

import json
import sys
from pathlib import Path

import polars as pl

from voc_analytics.labeling.eligibility import RULES_VERSION, with_tnss_rule
from voc_analytics.labeling.label_gemini import label_frame
from voc_analytics.paths import LABELS
from voc_analytics.sampling.strata import period

SEED = 20261018
PILOT = LABELS / "pilot_v0"
OUT = LABELS / "gold_v0"
PROMPT_VERSION = "prompt_v1"
CALIBRATION = 30
RANDOM_PER_BANK = 80
REANNOTATION_SHARE = 0.05


def pilot_runs() -> dict[str, pl.DataFrame]:
    """Primera corrida del piloto por versión de prompt."""
    runs: dict[str, pl.DataFrame] = {}
    for meta_path in sorted(PILOT.glob("run_*.json")):
        meta = json.loads(meta_path.read_text())
        version = meta["prompt_version"]
        if version not in runs:
            runs[version] = pl.read_parquet(
                PILOT / f"labels_{meta['run']}.parquet"
            )
    return runs


def calibration_block() -> pl.DataFrame:
    sample = pl.read_parquet(PILOT / "sample.parquet")
    labels = [
        pl.read_parquet(p).select("pilot_id", pl.col("gemini_s").alias(f"s{n}"))
        for n, p in enumerate(sorted(PILOT.glob("labels_*.parquet")))
    ]
    joined = sample
    for frame in labels:
        joined = joined.join(frame, on="pilot_id")
    cols = [c for c in joined.columns if c.startswith("s") and c[1:].isdigit()]
    joined = joined.with_columns(
        discrepa=pl.concat_list(cols).list.n_unique() > 1
    )
    half = CALIBRATION // 2
    picked = pl.concat(
        [
            joined.filter(pl.col("discrepa")).sample(half, seed=SEED),
            joined.filter(~pl.col("discrepa")).sample(
                CALIBRATION - half, seed=SEED
            ),
        ]
    ).sample(fraction=1.0, shuffle=True, seed=SEED)

    feedback = picked.select("pilot_id")
    for version, frame in pilot_runs().items():
        feedback = feedback.join(
            frame.select(
                "pilot_id",
                pl.format(
                    "{} (falla: {})",
                    "gemini_s",
                    pl.when("gemini_falla")
                    .then(pl.lit("sí"))
                    .otherwise(pl.lit("no")),
                ).alias(f"retro_{version}"),
            ),
            on="pilot_id",
            how="left",
        )
    return (
        picked.join(feedback, on="pilot_id")
        .with_row_index("n", offset=1)
        .select(
            pl.format("C{}", pl.col("n").cast(pl.String).str.zfill(3)).alias(
                "item_id"
            ),
            pl.lit("calibracion").alias("bloque"),
            pl.lit("ciego").alias("modo"),
            "id_resena",
            "bank_id",
            "texto_sanitizado",
            pl.col("^retro_.*$"),
        )
    )


def random_block(path: str) -> tuple[pl.DataFrame, list[dict]]:
    df = with_tnss_rule(
        pl.read_parquet(
            path,
            columns=[
                "id_resena",
                "bank_id",
                "texto_sanitizado",
                "texto_limpio",
                "fecha",
            ],
        )
    )
    eligible = df.filter(pl.col("tnss_rule").is_null()).with_columns(
        periodo=period()
    )
    sizes = eligible.group_by("bank_id", "periodo").len("N_h")
    # Asignación igual por banco, repartida entre sus periodos no vacíos.
    alloc = sizes.with_columns(
        k=pl.len().over("bank_id"),
        r=pl.col("periodo").rank("ordinal").over("bank_id"),
    ).with_columns(
        n_h=(RANDOM_PER_BANK // pl.col("k"))
        + (pl.col("r") <= RANDOM_PER_BANK % pl.col("k")).cast(pl.Int64)
    )
    picked = []
    for row in alloc.sort("bank_id", "periodo").iter_rows(named=True):
        stratum = eligible.filter(
            (pl.col("bank_id") == row["bank_id"])
            & (pl.col("periodo") == row["periodo"])
        )
        take = stratum.sample(row["n_h"], seed=SEED).with_columns(
            prob_inclusion=pl.lit(row["n_h"] / row["N_h"]),
            # Mitad ciega y mitad asistida dentro de cada estrato.
            modo=pl.when(pl.int_range(pl.len()) % 2 == 0)
            .then(pl.lit("ciego"))
            .otherwise(pl.lit("asistido")),
        )
        picked.append(take)
    block = (
        pl.concat(picked)
        .with_columns(estrato=pl.format("{}|{}", "bank_id", "periodo"))
        # Ciegos primero; dentro de cada modo, orden aleatorio.
        .sample(fraction=1.0, shuffle=True, seed=SEED)
        .sort(pl.col("modo") == "asistido", maintain_order=True)
        .with_row_index("n", offset=1)
        .with_columns(
            item_id=pl.format("A{}", pl.col("n").cast(pl.String).str.zfill(3)),
            bloque=pl.lit("aleatorio"),
        )
        .drop("n", "texto_limpio", "palabras", "tnss_rule", "fecha")
    )
    strata = alloc.sort("bank_id", "periodo").drop("k", "r").to_dicts()
    return block, strata


def main(path: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "annotations.csv").exists():
        sys.exit("Ya hay anotaciones en gold_v0; no se regenera la cola.")

    calibration = calibration_block()
    block, strata = random_block(path)
    labels, run_meta = label_frame(block, PROMPT_VERSION, id_col="item_id")
    block = block.join(labels, on="item_id", how="left").with_columns(
        gemini_prompt=pl.lit(PROMPT_VERSION)
    )
    repeats = block.filter(pl.col("modo") == "ciego").sample(
        round(block.height * REANNOTATION_SHARE), seed=SEED
    )
    repeats = (
        repeats.with_row_index("n", offset=1)
        .with_columns(
            repite_item=pl.col("item_id"),
            item_id=pl.format("R{}", pl.col("n").cast(pl.String).str.zfill(3)),
            bloque=pl.lit("reanotacion"),
        )
        .drop("n")
    )

    queue = pl.concat(
        [calibration, block, repeats], how="diagonal_relaxed"
    ).with_row_index("orden")
    queue.write_parquet(OUT / "queue.parquet")
    (OUT / f"run_{run_meta['run']}.json").write_text(
        json.dumps(run_meta, indent=2) + "\n"
    )
    meta = {
        "snapshot_file": Path(path).name,
        "rules_version": RULES_VERSION,
        "seed": SEED,
        "gemini_prompt": PROMPT_VERSION,
        "gemini_run": run_meta["run"],
        "gemini_cost_usd": run_meta["cost_usd"],
        "items": dict(queue["bloque"].value_counts().iter_rows()),
        "random_by_mode": dict(block["modo"].value_counts().iter_rows()),
        "strata": strata,
    }
    (OUT / "queue_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    summary = {k: v for k, v in meta.items() if k != "strata"}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
