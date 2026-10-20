"""Métricas de la segunda ronda del oro, `gold_v1` (EPIC-5, feature 5.3).

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.analysis.analyze_gold_v1

Lee la cola, el diseño y las anotaciones de `data/labels/gold_v1/` (fuera de
git) y escribe `docs/analytics/gold_v1_metrics.json`, solo agregados.

* **El oro *test* no se compara con ningún modelo** (ni Gemini ni estrellas):
  queda para 5.8. De *test* solo se usan medidas del etiquetado que no
  evalúan modelos: tiempo, consistencia del anotador y `nombre_persona`.
* Gemini es `prompt_v3`: la corrida de la cola en el bloque aleatorio y la
  plata en el dirigido.
* Las cifras poblacionales salen del bloque aleatorio de *dev*, con su π.
"""

import json

import polars as pl

from voc_analytics.labeling.agreement import (
    CLASSES,
    confusion,
    kappa,
    weighted_share,
)
from voc_analytics.paths import DATA, DOCS, LABELS

GOLD = LABELS / "gold_v1"
SNAPSHOT = DATA / "tds_20261016T054714Z.parquet"
OUT = DOCS / "gold_v1_metrics.json"
CRITERIA = ["neu", "cinco_neg", "pico_3_4", "desacuerdo", "incertidumbre_m1"]
# Notas del anotador sobre quejas por falta de claridad o comunicación del
# banco (decisiones que parecen unilaterales: ubicación, montos, bloqueos).
CLARITY = r"(?i)claridad|comunicaci|notificaci|explicar"


def annotations() -> pl.DataFrame:
    return (
        pl.read_csv(GOLD / "annotations.csv", infer_schema_length=0)
        .with_row_index("fila")
        .sort("fila")
        .group_by("item_id")
        .last()
        .select(
            "item_id",
            pl.when(pl.col("no_evaluable") == "1")
            .then(pl.lit("NA"))
            .otherwise(pl.col("sentimiento"))
            .alias("oro"),
            (pl.col("menciona_falla") == "1").alias("oro_falla"),
            (pl.col("duda") == "1").alias("duda"),
            (pl.col("nombre_persona") == "1").alias("nombre_persona"),
            pl.col("notas")
            .fill_null("")
            .str.contains(CLARITY)
            .alias("nota_claridad"),
            (pl.col("notas").fill_null("") != "").alias("con_nota"),
            pl.col("segundos").cast(pl.Float64),
        )
    )


def stars_class() -> pl.Expr:
    return (
        pl.when(pl.col("estrellas") <= 2)
        .then(pl.lit("NEG"))
        .when(pl.col("estrellas") == 3)
        .then(pl.lit("NEU"))
        .otherwise(pl.lit("POS"))
    )


def rule_of_three(hits: int, n: int) -> dict:
    """Proporción y cota superior al 95 % (regla del tres si no hay casos)."""
    return {
        "casos": hits,
        "n": n,
        "tasa": round(hits / n, 4),
        "cota_95_si_cero": round(3 / n, 4) if hits == 0 else None,
    }


def main() -> None:
    queue = pl.read_parquet(GOLD / "queue.parquet").select(
        "item_id", "id_resena"
    )
    design = pl.read_parquet(GOLD / "design.parquet")
    ann = annotations()
    stars = pl.scan_parquet(SNAPSHOT).select("id_resena", "estrellas")
    df = (
        queue.join(design, on="item_id")
        .join(ann, on="item_id")
        .join(
            stars.filter(
                pl.col("id_resena").is_in(queue["id_resena"].to_list())
            ).collect(),
            on="id_resena",
            how="left",
        )
        .with_columns(
            gemini=pl.col("plata"),
            gemini_falla=pl.col("gemini_falla").cast(pl.Boolean),
            estrellas_clase=stars_class(),
            **{f"es_{c}": pl.col("oro") == c for c in CLASSES},
        )
        .with_columns(
            incongruente=((pl.col("estrellas") <= 2) & (pl.col("oro") == "POS"))
            | ((pl.col("estrellas") >= 4) & (pl.col("oro") == "NEG")),
            estrellas_difiere=pl.col("estrellas_clase") != pl.col("oro"),
        )
    )
    main_items = df.filter(pl.col("bloque") != "reanotacion")
    rand = main_items.filter(pl.col("bloque") == "aleatorio")
    dev_rand = rand.filter(pl.col("particion") == "dev")
    directed = main_items.filter(pl.col("bloque") == "dirigido")
    dev_all = main_items.filter(pl.col("particion") == "dev")
    evaluable = dev_rand.filter(pl.col("oro") != "NA")

    repeats = (
        df.filter(pl.col("bloque") == "reanotacion")
        .select("repite_item", pl.col("oro").alias("oro_r"))
        .join(
            df.select("item_id", "oro", "particion"),
            left_on="repite_item",
            right_on="item_id",
        )
    )

    def k(frame: pl.DataFrame, a: str, b: str) -> dict:
        return kappa(frame[a].to_list(), frame[b].to_list())

    def falla(frame: pl.DataFrame) -> dict:
        frame = frame.filter(pl.col("gemini_falla").is_not_null())
        return {
            **kappa(
                frame["oro_falla"].to_list(), frame["gemini_falla"].to_list()
            ),
            "oro_si_gemini_no": frame.filter(
                pl.col("oro_falla") & ~pl.col("gemini_falla")
            ).height,
            "oro_no_gemini_si": frame.filter(
                ~pl.col("oro_falla") & pl.col("gemini_falla")
            ).height,
            "tasa_oro": round(frame["oro_falla"].mean(), 3),
            "tasa_gemini": round(frame["gemini_falla"].mean(), 3),
        }

    seconds = main_items["segundos"].clip(0, 120)
    clarity = main_items.filter(pl.col("nota_claridad"))
    metrics = {
        "anotadas": df.height,
        "tiempo": {
            "minutos_efectivos": round(
                df["segundos"].clip(0, 120).sum() / 60, 1
            ),
            "mediana_s": main_items["segundos"].median(),
            "media_s_truncada": round(seconds.mean(), 1),
            "por_bloque_media_s": {
                b: round(g["segundos"].clip(0, 120).mean(), 1)
                for (b,), g in sorted(
                    main_items.partition_by("bloque", as_dict=True).items()
                )
            },
        },
        "consistencia_reanotacion": {
            **k(repeats, "oro", "oro_r"),
            "transiciones": confusion(
                repeats.filter(pl.col("oro") != pl.col("oro_r")), "oro", "oro_r"
            ),
        },
        "marcas": {
            "duda": round(main_items["duda"].mean(), 3),
            "con_nota": main_items["con_nota"].sum(),
            "nota_claridad": clarity.height,
            "nota_claridad_oro": dict(
                clarity["oro"].value_counts().iter_rows()
            ),
            "nota_claridad_falla_oro": clarity["oro_falla"].sum(),
            "nota_claridad_falla_gemini": clarity["gemini_falla"].sum(),
        },
        "nombre_persona": {
            "aleatorio": rule_of_three(
                rand["nombre_persona"].sum(), rand.height
            ),
            "dirigido": rule_of_three(
                directed["nombre_persona"].sum(), directed.height
            ),
        },
        "clases_dev": {
            "aleatorio": dict(
                dev_rand["oro"].value_counts().sort("oro").iter_rows()
            ),
            "dirigido": dict(
                directed["oro"].value_counts().sort("oro").iter_rows()
            ),
            "total_dev_gold_v1": dict(
                dev_all["oro"].value_counts().sort("oro").iter_rows()
            ),
        },
        "poblacion_dev_aleatorio": {
            "clase": {c: weighted_share(dev_rand, f"es_{c}") for c in CLASSES},
            "incongruencia_extremos": weighted_share(dev_rand, "incongruente"),
            "estrellas_difiere_de_oro": weighted_share(
                evaluable, "estrellas_difiere"
            ),
            "estrellas_vs_oro": k(evaluable, "estrellas_clase", "oro"),
            "confusion_estrellas": confusion(evaluable, "estrellas", "oro"),
        },
        "gemini_vs_oro": {
            "dev_aleatorio": k(dev_rand, "oro", "gemini"),
            "dev_aleatorio_confusion": confusion(dev_rand, "oro", "gemini"),
            "dirigido": k(directed, "oro", "gemini"),
            "falla_dev_aleatorio": falla(dev_rand),
            "falla_dirigido": falla(directed),
        },
        "dirigido_por_criterio": {
            c: {
                "n": g.height,
                "oro": dict(g["oro"].value_counts().sort("oro").iter_rows()),
                "acuerdo_gemini": round((g["oro"] == g["gemini"]).mean(), 3),
                "acuerdo_m1_seleccion": round((g["oro"] == g["m1"]).mean(), 3),
                "acuerdo_estrellas": round(
                    (g["oro"] == g["estrellas_clase"]).mean(), 3
                ),
                "duda": round(g["duda"].mean(), 3),
            }
            for c in CRITERIA
            if (g := directed.filter(pl.col("criterio") == c)).height
        },
    }
    OUT.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
