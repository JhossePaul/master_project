"""Métricas de la re-anotación a ciegas del oro (EPIC-5, feature 5.3).

**Histórico:** métricas de `gold_v0_r2`, superadas por `analyze_gold_v1`; se
conserva para reproducir `gold_v0_r2_metrics.json`.

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.analysis.analyze_gold_v0_r2 \\
        data/tds_<SNAPSHOT>.parquet

Compara la primera ronda (`gold_v0`, guía v0) con la re-anotación
(`gold_v0_r2`, guía vigente, todo a ciegas) y evalúa cada prompt contra el oro
re-anotado. Las corridas de Gemini se toman de `gold_v0/run_*.json` (la primera
corrida de cada versión es la principal; la segunda mide estabilidad). Escribe
`docs/analytics/gold_v0_r2_metrics.json`, solo agregados.
"""

import json
import random
import sys
from pathlib import Path

import polars as pl

from voc_analytics.labeling.agreement import (
    CLASSES,
    confusion,
    kappa,
    weighted_share,
)
from voc_analytics.paths import DOCS, LABELS

FIRST, SECOND = LABELS / "gold_v0", LABELS / "gold_v0_r2"
OUT = DOCS / "gold_v0_r2_metrics.json"
BOOTSTRAP = 2000
SEED = 20261018


def human(folder: Path, name: str) -> pl.DataFrame:
    return (
        pl.read_csv(folder / "annotations.csv", infer_schema_length=0)
        .with_row_index("fila")
        .sort("fila")
        .group_by("item_id")
        .last()
        .select(
            "item_id",
            pl.when(pl.col("no_evaluable") == "1")
            .then(pl.lit("NA"))
            .otherwise(pl.col("sentimiento"))
            .alias(name),
            (pl.col("menciona_falla") == "1").alias(f"{name}_falla"),
        )
    )


def gemini_runs() -> dict[str, list[str]]:
    runs: dict[str, list[str]] = {}
    for path in sorted(FIRST.glob("run_*.json")):
        meta = json.loads(path.read_text())
        runs.setdefault(meta["prompt_version"], []).append(meta["run"])
    return runs


def bootstrap_diff(gold: list, a: list, b: list) -> dict:
    """IC 95 % de κ(a) − κ(b) contra el mismo oro, remuestreo pareado."""
    rng = random.Random(SEED)  # noqa: S311 - remuestreo, no criptografía
    n = len(gold)
    diffs = []
    for _ in range(BOOTSTRAP):
        idx = [rng.randrange(n) for _ in range(n)]
        g = [gold[i] for i in idx]
        diffs.append(
            kappa(g, [a[i] for i in idx])["kappa"]
            - kappa(g, [b[i] for i in idx])["kappa"]
        )
    diffs.sort()
    return {
        "diferencia": round(
            kappa(gold, a)["kappa"] - kappa(gold, b)["kappa"], 3
        ),
        "ic95": [
            round(diffs[int(0.025 * BOOTSTRAP)], 3),
            round(diffs[int(0.975 * BOOTSTRAP)], 3),
        ],
    }


def main(snapshot: str) -> None:
    runs = gemini_runs()
    queue = pl.read_parquet(FIRST / "queue.parquet")
    second = pl.read_parquet(SECOND / "queue.parquet").select(
        "item_id", "origen_item", pl.col("bloque").alias("seccion")
    )
    df = (
        queue.join(human(FIRST, "h1"), on="item_id", how="left")
        .join(
            second.join(human(SECOND, "h2"), on="item_id").drop("item_id"),
            left_on="item_id",
            right_on="origen_item",
            how="inner",
        )
        .with_columns(
            v1=pl.when(pl.col("bloque") == "calibracion")
            .then(pl.col("retro_prompt_v1").str.extract(r"^(\w+)"))
            .otherwise(pl.col("gemini_s")),
            v1_falla=pl.col("gemini_falla"),
        )
    )
    for version in ("prompt_v0", "prompt_v2", "prompt_v3"):
        short = version.removeprefix("prompt_")
        frame = pl.read_parquet(
            FIRST / f"labels_{runs[version][0]}.parquet"
        ).select(
            "item_id",
            pl.col("gemini_s").alias(short),
            pl.col("gemini_falla").alias(f"{short}_falla"),
        )
        df = df.join(frame, on="item_id", how="left")
    # En calibración, v0 viene del piloto (la corrida de la cola no la cubre).
    df = df.with_columns(
        v0=pl.when(pl.col("bloque") == "calibracion")
        .then(pl.col("retro_prompt_v0").str.extract(r"^(\w+)"))
        .otherwise(pl.col("v0"))
    )
    stars = pl.read_parquet(
        snapshot, columns=["bank_id", "id_resena", "estrellas"]
    ).drop("bank_id")
    rand = (
        df.filter(pl.col("bloque") == "aleatorio")
        .join(stars, on="id_resena", how="left")
        .with_columns(
            estrellas_clase=pl.when(pl.col("estrellas") <= 2)
            .then(pl.lit("NEG"))
            .when(pl.col("estrellas") == 3)
            .then(pl.lit("NEU"))
            .otherwise(pl.lit("POS")),
            incongruente=((pl.col("estrellas") <= 2) & (pl.col("h2") == "POS"))
            | ((pl.col("estrellas") >= 4) & (pl.col("h2") == "NEG")),
            **{f"es_{c}": pl.col("h2") == c for c in CLASSES},
        )
        .with_columns(
            estrellas_difiere=pl.col("estrellas_clase") != pl.col("h2")
        )
    )
    evaluable = rand.filter(pl.col("h2") != "NA")
    blind1 = rand.filter(pl.col("modo") == "ciego")
    assisted1 = rand.filter(pl.col("modo") == "asistido")
    calibration = df.filter(pl.col("bloque") == "calibracion")

    def k(frame: pl.DataFrame, a: str, b: str) -> dict:
        return kappa(frame[a].to_list(), frame[b].to_list())

    prompts = ["v0", "v1", "v2", "v3"]
    gold = rand["h2"].to_list()
    metrics = {
        "anotadas_r2": df.height,
        "consistencia_r1_r2": {
            "aleatorio_ciego_en_r1": k(blind1, "h1", "h2"),
            "aleatorio_asistido_en_r1": k(assisted1, "h1", "h2"),
            "calibracion": k(calibration, "h1", "h2"),
            "transiciones_ciego": confusion(blind1, "h1", "h2"),
            "transiciones_asistido": confusion(assisted1, "h1", "h2"),
        },
        "anclaje_retrospectivo": {
            "asistido_r1_vs_v1": k(assisted1, "h1", "v1"),
            "mismos_textos_a_ciegas_r2_vs_v1": k(assisted1, "h2", "v1"),
        },
        "poblacion_r2": {
            "clase": {c: weighted_share(rand, f"es_{c}") for c in CLASSES},
            "incongruencia_extremos": weighted_share(rand, "incongruente"),
            "estrellas_difiere_de_oro": weighted_share(
                evaluable, "estrellas_difiere"
            ),
            "incongruencia_por_banco": {
                bank: weighted_share(group, "incongruente")
                for (bank,), group in sorted(
                    rand.partition_by("bank_id", as_dict=True).items()
                )
            },
            "incongruencia_por_periodo": {
                period: weighted_share(group, "incongruente")
                for (period,), group in sorted(
                    rand.partition_by("periodo", as_dict=True).items()
                )
            },
            "estrellas_vs_oro": k(evaluable, "estrellas_clase", "h2"),
            "confusion_estrellas": confusion(evaluable, "estrellas", "h2"),
        },
        "prompts_vs_oro_r2": {
            "aleatorio": {p: k(rand, "h2", p) for p in prompts},
            "aleatorio_falla": {
                p: kappa(
                    rand["h2_falla"].to_list(), rand[f"{p}_falla"].to_list()
                )
                for p in prompts
            },
            "calibracion": {p: k(calibration, "h2", p) for p in prompts},
            "confusion_v3": confusion(rand, "h2", "v3"),
            "v3_menos_v0": bootstrap_diff(
                gold, rand["v3"].to_list(), rand["v0"].to_list()
            ),
            "v3_menos_v2": bootstrap_diff(
                gold, rand["v3"].to_list(), rand["v2"].to_list()
            ),
        },
    }
    stability = {}
    for version in ("prompt_v2", "prompt_v3"):
        if len(runs[version]) > 1:
            a, b = (
                pl.read_parquet(FIRST / f"labels_{r}.parquet")
                for r in runs[version][:2]
            )
            both = a.join(b, on="item_id")
            stability[version] = kappa(
                both["gemini_s"].to_list(), both["gemini_s_right"].to_list()
            )
    metrics["estabilidad"] = stability
    OUT.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
