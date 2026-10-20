"""Acuerdo entre anotadores en `gold_v1_a2` (EPIC-5, feature 5.3).

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.analysis.analyze_gold_v1_a2

Un segundo anotador, independiente del autor, etiquetó a ciegas 100 ítems
del bloque aleatorio de `gold_v1` con la guía `v2.2`. Compara sus etiquetas
con las del autor (la última por ítem en `gold_v1`) y escribe
`docs/analytics/gold_v1_a2_metrics.json`, solo agregados.

* **Acuerdo entre personas:** los 100 ítems (68 de *dev* y 32 de *test*).
  No evalúa ningún modelo, así que no toca la reserva de *test*.
* **Gemini y estrellas contra cada anotador:** solo los 68 de *dev*.
* El nombre del segundo anotador no sale en las métricas.
"""

import json
import random

import polars as pl

from voc_analytics.labeling.agreement import confusion, kappa
from voc_analytics.paths import DATA, DOCS, LABELS

GOLD = LABELS / "gold_v1"
A2 = LABELS / "gold_v1_a2"
SNAPSHOT = DATA / "tds_20261016T054714Z.parquet"
OUT = DOCS / "gold_v1_a2_metrics.json"
BOOTSTRAP = 2000
SEED = 20261021


def labels(folder, prefix: str) -> pl.DataFrame:
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
            .alias(prefix),
            (pl.col("menciona_falla") == "1").alias(f"{prefix}_falla"),
            (pl.col("duda") == "1").alias(f"{prefix}_duda"),
            (pl.col("nombre_persona") == "1").alias(f"{prefix}_nombre"),
            pl.col("segundos").cast(pl.Float64).alias(f"{prefix}_segundos"),
        )
    )


def kappa_ci(a: list, b: list) -> dict:
    """κ con IC 95 % por bootstrap de ítems."""
    rng = random.Random(SEED)  # noqa: S311 - remuestreo, no criptografía
    n = len(a)
    values = []
    for _ in range(BOOTSTRAP):
        idx = [rng.randrange(n) for _ in range(n)]
        values.append(kappa([a[i] for i in idx], [b[i] for i in idx])["kappa"])
    values.sort()
    return {
        **kappa(a, b),
        "ic95": [
            values[int(0.025 * BOOTSTRAP)],
            values[int(0.975 * BOOTSTRAP)],
        ],
    }


def stars_class() -> pl.Expr:
    return (
        pl.when(pl.col("estrellas") <= 2)
        .then(pl.lit("NEG"))
        .when(pl.col("estrellas") == 3)
        .then(pl.lit("NEU"))
        .otherwise(pl.lit("POS"))
    )


def main() -> None:
    queue = pl.read_parquet(A2 / "queue.parquet").select(
        "item_id", "origen_item", "id_resena"
    )
    design = pl.read_parquet(GOLD / "design.parquet").select(
        "item_id", "particion", "plata"
    )
    stars = (
        pl.scan_parquet(SNAPSHOT)
        .select("id_resena", "estrellas")
        .filter(pl.col("id_resena").is_in(queue["id_resena"].to_list()))
        .collect()
    )
    df = (
        queue.join(labels(A2, "a2"), on="item_id")
        .join(labels(GOLD, "autor"), left_on="origen_item", right_on="item_id")
        .join(design, left_on="origen_item", right_on="item_id")
        .join(stars, on="id_resena", how="left")
        .with_columns(gemini=pl.col("plata"), estrellas_clase=stars_class())
    )
    both = df.filter((pl.col("autor") != "NA") & (pl.col("a2") != "NA"))
    dev = df.filter(pl.col("particion") == "dev")
    disagree = df.filter(pl.col("autor") != pl.col("a2"))

    def k(frame: pl.DataFrame, a: str, b: str, ci: bool = False) -> dict:
        fn = kappa_ci if ci else kappa
        return fn(frame[a].to_list(), frame[b].to_list())

    metrics = {
        "items": df.height,
        "por_particion": dict(df["particion"].value_counts().iter_rows()),
        "guia_a2": "annotation_guideline_v2.2",
        "tiempo_a2": {
            "minutos_efectivos": round(
                df["a2_segundos"].clip(0, 120).sum() / 60, 1
            ),
            "mediana_s": df["a2_segundos"].median(),
            "mediana_s_autor_mismos_items": df["autor_segundos"].median(),
        },
        "acuerdo_sentimiento": {
            "cuatro_clases": k(df, "autor", "a2", ci=True),
            "tres_clases_ambos_evaluables": k(both, "autor", "a2", ci=True),
            "confusion_autor_vs_a2": confusion(df, "autor", "a2"),
            "desacuerdos": disagree.height,
            "desacuerdos_con_duda_de_alguno": disagree.filter(
                pl.col("autor_duda") | pl.col("a2_duda")
            ).height,
        },
        "acuerdo_falla": {
            **k(df, "autor_falla", "a2_falla"),
            "tasa_autor": round(df["autor_falla"].mean(), 3),
            "tasa_a2": round(df["a2_falla"].mean(), 3),
        },
        "marcas": {
            "duda_autor": int(df["autor_duda"].sum()),
            "duda_a2": int(df["a2_duda"].sum()),
            "nombre_persona_autor": int(df["autor_nombre"].sum()),
            "nombre_persona_a2": int(df["a2_nombre"].sum()),
        },
        "dev_contra_modelos": {
            "n": dev.height,
            "gemini_vs_autor": k(dev, "autor", "gemini"),
            "gemini_vs_a2": k(dev, "a2", "gemini"),
            "autor_vs_a2": k(dev, "autor", "a2"),
            "estrellas_vs_autor": k(
                dev.filter(pl.col("autor") != "NA"),
                "autor",
                "estrellas_clase",
            ),
            "estrellas_vs_a2": k(
                dev.filter(pl.col("a2") != "NA"), "a2", "estrellas_clase"
            ),
        },
    }
    OUT.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
