"""Métricas del oro, primera ronda (EPIC-5, feature 5.3), solo agregados.

**Histórico:** métricas de `gold_v0`, superadas por `analyze_gold_v1`; se
conserva para reproducir `gold_v0_metrics.json`.

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.analysis.analyze_gold_v0 \\
        data/tds_<SNAPSHOT>.parquet <run_prompt_v0>

Une `annotations.csv` (última fila por `item_id`), la cola, las estrellas del
snapshot y las etiquetas de Gemini (`prompt_v1` en la cola y `prompt_v0` de la
corrida indicada). Escribe `docs/analytics/gold_v0_metrics.json`.

* Estimaciones poblacionales: solo bloque `aleatorio`, ponderado por
  1 / probabilidad de inclusión, con error estándar de muestreo estratificado.
* Acuerdo con Gemini: bloque `aleatorio` a ciegas (sin anclaje). El asistido
  se compara contra él para estimar el anclaje.
"""

import json
import sys

import polars as pl

from voc_analytics.labeling.agreement import (
    CLASSES,
    confusion,
    kappa,
    weighted_share,
)
from voc_analytics.paths import DOCS, LABELS

GOLD = LABELS / "gold_v0"
OUT = DOCS / "gold_v0_metrics.json"


def main(snapshot: str, run_v0: str) -> None:
    annotations = (
        pl.read_csv(GOLD / "annotations.csv", infer_schema_length=0)
        .with_row_index("fila")
        .sort("fila")
        .group_by("item_id")
        .last()
        .with_columns(
            humano=pl.when(pl.col("no_evaluable") == "1")
            .then(pl.lit("NA"))
            .otherwise(pl.col("sentimiento")),
            humano_falla=pl.col("menciona_falla") == "1",
            humano_duda=pl.col("duda") == "1",
            segundos=pl.col("segundos").cast(pl.Float64),
        )
    )
    corrections = (
        pl.read_csv(GOLD / "annotations.csv", infer_schema_length=0).height
        - annotations.height
    )
    queue = pl.read_parquet(GOLD / "queue.parquet")
    v0 = pl.read_parquet(GOLD / f"labels_{run_v0}.parquet").select(
        "item_id",
        pl.col("gemini_s").alias("v0"),
        pl.col("gemini_falla").alias("v0_falla"),
    )
    stars = pl.read_parquet(
        snapshot, columns=["bank_id", "id_resena", "estrellas"]
    )
    df = (
        queue.drop("bank_id")
        .join(
            annotations.select(
                "item_id",
                "humano",
                "humano_falla",
                "humano_duda",
                "segundos",
            ),
            on="item_id",
            how="left",
        )
        .join(v0, on="item_id", how="left")
        .join(
            stars,
            on="id_resena",
            how="left",
        )
        .rename({"gemini_s": "v1", "gemini_falla": "v1_falla"})
        .with_columns(
            palabras=pl.col("texto_sanitizado").str.count_matches(r"\S+"),
            estrellas_clase=pl.when(pl.col("estrellas") <= 2)
            .then(pl.lit("NEG"))
            .when(pl.col("estrellas") == 3)
            .then(pl.lit("NEU"))
            .otherwise(pl.lit("POS")),
        )
    )
    random = df.filter(pl.col("bloque") == "aleatorio").with_columns(
        incongruente=(
            ((pl.col("estrellas") <= 2) & (pl.col("humano") == "POS"))
            | ((pl.col("estrellas") >= 4) & (pl.col("humano") == "NEG"))
        ),
        estrellas_difiere=(pl.col("estrellas_clase") != pl.col("humano")),
        **{f"es_{c}": pl.col("humano") == c for c in CLASSES},
    )
    blind = random.filter(pl.col("modo") == "ciego")
    assisted = random.filter(pl.col("modo") == "asistido")
    calibration = df.filter(pl.col("bloque") == "calibracion").with_columns(
        r0=pl.col("retro_prompt_v0").str.extract(r"^(\w+)"),
        r1=pl.col("retro_prompt_v1").str.extract(r"^(\w+)"),
        discrepa=pl.col("retro_prompt_v0").str.extract(r"^(\w+)")
        != pl.col("retro_prompt_v1").str.extract(r"^(\w+)"),
    )
    repeats = (
        df.filter(pl.col("bloque") == "reanotacion")
        .select("repite_item", pl.col("humano").alias("segunda"))
        .join(
            df.select("item_id", "humano"),
            left_on="repite_item",
            right_on="item_id",
        )
    )
    evaluable = random.filter(pl.col("humano") != "NA")

    metrics = {
        "anotadas": annotations.height,
        "correcciones": corrections,
        "tiempo": {
            "total_min": round(annotations["segundos"].sum() / 60, 1),
            "mediana_s_por_modo": dict(
                df.group_by("bloque", "modo")
                .agg(pl.col("segundos").median())
                .select(pl.format("{}|{}", "bloque", "modo"), "segundos")
                .iter_rows()
            ),
        },
        "poblacion": {
            "clase": {c: weighted_share(random, f"es_{c}") for c in CLASSES},
            "duda": weighted_share(random, "humano_duda"),
            "menciona_falla": weighted_share(random, "humano_falla"),
            "incongruencia_extremos": weighted_share(random, "incongruente"),
            "estrellas_difiere_de_oro": weighted_share(
                evaluable, "estrellas_difiere"
            ),
            "incongruencia_por_banco": {
                bank: weighted_share(group, "incongruente")
                for (bank,), group in sorted(
                    random.partition_by("bank_id", as_dict=True).items()
                )
            },
            "incongruencia_por_periodo": {
                period: weighted_share(group, "incongruente")
                for (period,), group in sorted(
                    random.partition_by("periodo", as_dict=True).items()
                )
            },
        },
        # El asistido está anclado a v1; el ciego también es aleatorio
        # estratificado (mitad de cada estrato) y sirve de contraste.
        "poblacion_solo_ciego": {
            "clase": {c: weighted_share(blind, f"es_{c}") for c in CLASSES},
            "incongruencia_extremos": weighted_share(blind, "incongruente"),
            "estrellas_difiere_de_oro": weighted_share(
                blind.filter(pl.col("humano") != "NA"), "estrellas_difiere"
            ),
        },
        "estrellas_vs_oro": {
            "kappa": kappa(
                evaluable["estrellas_clase"].to_list(),
                evaluable["humano"].to_list(),
            ),
            "confusion": confusion(evaluable, "estrellas", "humano"),
        },
        "gemini_ciego": {
            "v1": kappa(blind["humano"].to_list(), blind["v1"].to_list()),
            "v0": kappa(blind["humano"].to_list(), blind["v0"].to_list()),
            "v1_falla": kappa(
                blind["humano_falla"].to_list(), blind["v1_falla"].to_list()
            ),
            "v0_falla": kappa(
                blind["humano_falla"].to_list(), blind["v0_falla"].to_list()
            ),
            "confusion_v1": confusion(blind, "humano", "v1"),
            "confusion_v0": confusion(blind, "humano", "v0"),
        },
        "anclaje": {
            "acuerdo_v1_ciego": kappa(
                blind["humano"].to_list(), blind["v1"].to_list()
            ),
            "acuerdo_v1_asistido": kappa(
                assisted["humano"].to_list(), assisted["v1"].to_list()
            ),
            # v0 nunca se mostró: mide si el asistido se acercó solo a v1.
            "acuerdo_v0_asistido": kappa(
                assisted["humano"].to_list(), assisted["v0"].to_list()
            ),
        },
        "calibracion": {
            "v0": kappa(
                calibration["humano"].to_list(), calibration["r0"].to_list()
            ),
            "v1": kappa(
                calibration["humano"].to_list(), calibration["r1"].to_list()
            ),
            "discrepantes_v0_v1": {
                "n": int(calibration["discrepa"].sum()),
                "humano_igual_v0": int(
                    calibration.filter("discrepa")
                    .select((pl.col("humano") == pl.col("r0")).sum())
                    .item()
                ),
                "humano_igual_v1": int(
                    calibration.filter("discrepa")
                    .select((pl.col("humano") == pl.col("r1")).sum())
                    .item()
                ),
            },
        },
        "reanotacion": kappa(
            repeats["humano"].to_list(), repeats["segunda"].to_list()
        ),
    }
    OUT.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
