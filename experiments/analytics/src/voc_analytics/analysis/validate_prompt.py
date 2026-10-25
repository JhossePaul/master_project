"""Valida un prompt candidato contra el oro (EPIC-5, feature 5.3).

**Histórico:** validó `prompt_v2` contra `gold_v0`; `prompt_v3` se eligió
con `gold_v0_r2` (`analyze_gold_v0_r2`). Se conserva para reproducir
`prompt_validation_prompt_v2.json`.

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.analysis.validate_prompt \\
        <run_v0> <run_candidato_1> [<run_candidato_2>]

Compara contra las anotaciones humanas (última fila por `item_id`):

* calibración (30): incluye las propuestas de v0 y v1 del piloto;
* bloque aleatorio a ciegas (201): v0 (`<run_v0>`), v1 (la cola) y el
  candidato.

Con dos corridas del candidato mide además su estabilidad. Escribe
`docs/analytics/labeling/prompt_validation_<candidato>.json`, solo agregados.
"""

import json
import sys

import polars as pl

from voc_analytics.labeling.agreement import confusion, kappa
from voc_analytics.paths import DOCS, LABELS

GOLD = LABELS / "gold_v0"


def labels(run: str, name: str) -> pl.DataFrame:
    return pl.read_parquet(GOLD / f"labels_{run}.parquet").select(
        "item_id",
        pl.col("gemini_s").alias(name),
        pl.col("gemini_falla").alias(f"{name}_falla"),
    )


def main(run_v0: str, runs: list[str]) -> None:
    meta = json.loads((GOLD / f"run_{runs[0]}.json").read_text())
    candidate = meta["prompt_version"]
    human = (
        pl.read_csv(GOLD / "annotations.csv", infer_schema_length=0)
        .with_row_index("fila")
        .sort("fila")
        .group_by("item_id")
        .last()
        .select(
            "item_id",
            humano=pl.when(pl.col("no_evaluable") == "1")
            .then(pl.lit("NA"))
            .otherwise(pl.col("sentimiento")),
            humano_falla=pl.col("menciona_falla") == "1",
        )
    )
    df = (
        pl.read_parquet(GOLD / "queue.parquet")
        .join(human, on="item_id")
        .join(labels(run_v0, "v0"), on="item_id", how="left")
        .join(labels(runs[0], "c"), on="item_id", how="left")
        .with_columns(
            v1=pl.col("gemini_s"),
            v1_falla=pl.col("gemini_falla"),
            # En calibración, v0 y v1 vienen del piloto (retroalimentación).
            r0=pl.col("retro_prompt_v0").str.extract(r"^(\w+)"),
            r1=pl.col("retro_prompt_v1").str.extract(r"^(\w+)"),
        )
    )
    calibration = df.filter(pl.col("bloque") == "calibracion")
    blind = df.filter(
        (pl.col("bloque") == "aleatorio") & (pl.col("modo") == "ciego")
    )
    frontier = calibration.filter(pl.col("r0") != pl.col("r1"))

    def vs_human(frame: pl.DataFrame, col: str) -> dict:
        return kappa(frame["humano"].to_list(), frame[col].to_list())

    result = {
        "candidato": candidate,
        "corridas": runs,
        "costo_usd_por_1k": meta["cost_usd_per_1k_texts"],
        "calibracion": {
            "v0": vs_human(calibration, "r0"),
            "v1": vs_human(calibration, "r1"),
            candidate: vs_human(calibration, "c"),
            "fronterizos_v0_v1": {
                "n": frontier.height,
                "humano_igual_v0": int(
                    (frontier["humano"] == frontier["r0"]).sum()
                ),
                "humano_igual_v1": int(
                    (frontier["humano"] == frontier["r1"]).sum()
                ),
                f"humano_igual_{candidate}": int(
                    (frontier["humano"] == frontier["c"]).sum()
                ),
            },
        },
        "ciego": {
            "v0": vs_human(blind, "v0"),
            "v1": vs_human(blind, "v1"),
            candidate: vs_human(blind, "c"),
            f"{candidate}_falla": kappa(
                blind["humano_falla"].to_list(), blind["c_falla"].to_list()
            ),
            f"confusion_{candidate}": confusion(blind, "humano", "c"),
        },
    }
    if len(runs) > 1:
        both = labels(runs[0], "a").join(labels(runs[1], "b"), on="item_id")
        result["estabilidad"] = kappa(both["a"].to_list(), both["b"].to_list())
    out = DOCS / "labeling" / f"prompt_validation_{candidate}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
