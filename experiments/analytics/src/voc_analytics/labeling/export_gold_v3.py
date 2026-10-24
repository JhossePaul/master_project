"""Exporta el oro para ``gold_labels`` de EPIC-6 (D10), sin texto.

* **Sentimiento:** el oro *dev* aleatorio de EPIC-5 (``gold_v0_r2`` +
  ``gold_v1``, partición ``dev``, sin ``NA``): 794 reseñas con su peso de
  diseño 1/π, como lo usan la curva HITL y PPI de 5.6. El oro *test* no se
  exporta: quedó consumido en 5.8.
* **Aspectos:** las 300 reseñas de ``muestra_v21`` etiquetadas por el autor
  con la guía v2.1 (``aspects_gold_v2_1`` en EPIC-6); se toma la última
  anotación de cada ítem.

El texto solo se usa para calcular ``text_key`` (SHA-256 de
``texto_sanitizado``) y no se escribe. Salida, fuera de git:
``data/handoff/gold_labels_v1.parquet``. La carga a BigQuery la hace
``ml_inference load-local`` (EPIC-6, 6.3).

    uv run python -m voc_analytics.labeling.export_gold_v3
"""

import hashlib

import polars as pl

from voc_analytics.paths import DATA
from voc_analytics.sentiment.data import _gold_v0, _gold_v1, _kish_scale

OUT = DATA / "handoff" / "gold_labels_v1.parquet"
ASPECTS = DATA / "eda" / "aspects_v2"
CODES = ("AC", "TR", "DI", "PR", "AT", "FA", "LE", "CO", "DV", "UX", "OT")
SCHEMA = {
    "split": pl.String,
    "task": pl.String,
    "id_resena": pl.String,
    "text_key": pl.String,
    "label": pl.String,
    "families": pl.List(pl.String),
    "flag_update": pl.Boolean,
    "flag_security": pl.Boolean,
    "praise": pl.Boolean,
    "weight": pl.Float64,
    "guideline_version": pl.String,
}


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sentiment() -> pl.DataFrame:
    df = pl.concat([_gold_v0(), _gold_v1()], how="diagonal_relaxed")
    df = df.with_columns(peso=_kish_scale(df) / pl.col("prob_inclusion"))
    dev = df.filter(
        (pl.col("particion") == "dev")
        & (pl.col("bloque_oro") == "aleatorio")
        & (pl.col("oro") != "NA")
    )
    return dev.select(
        split=pl.lit("dev"),
        task=pl.lit("sentiment"),
        id_resena="id_resena",
        text_key=pl.col("texto_sanitizado").map_elements(
            text_key, return_dtype=pl.String
        ),
        label="oro",
        families=pl.lit([], dtype=pl.List(pl.String)),
        flag_update=pl.lit(None, dtype=pl.Boolean),
        flag_security=pl.lit(None, dtype=pl.Boolean),
        praise=pl.lit(None, dtype=pl.Boolean),
        weight="peso",
        guideline_version=pl.lit("v2.2"),
    )


def aspects() -> pl.DataFrame:
    texts = pl.read_csv(ASPECTS / "muestra_v21.csv")
    notes = (
        pl.read_csv(ASPECTS / "muestra_v21_annotations.csv")
        .sort("fin")
        .unique("item", keep="last")
    )
    df = notes.join(texts.select("item", "texto_sanitizado"), on="item")
    families = (
        pl.col("codigos")
        .fill_null("")
        .str.replace_all(r"\s", "")
        .str.split(",")
        .list.eval(pl.element().filter(pl.element().is_in(CODES)))
        .list.unique(maintain_order=True)
    )
    return df.select(
        split=pl.lit("aspects_gold_v2_1"),
        task=pl.lit("aspects"),
        id_resena=pl.lit(None, dtype=pl.String),
        text_key=pl.col("texto_sanitizado").map_elements(
            text_key, return_dtype=pl.String
        ),
        label=pl.lit(None, dtype=pl.String),
        families=families,
        flag_update=pl.col("u") == 1,
        flag_security=pl.col("s") == 1,
        praise=pl.col("elogio") == 1,
        weight=pl.lit(None, dtype=pl.Float64),
        guideline_version=pl.lit("v2.1"),
    )


def main() -> None:
    gold = pl.concat([sentiment(), aspects()]).cast(SCHEMA)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    gold.write_parquet(OUT)
    print(gold.group_by("split").len().sort("split"), OUT)


if __name__ == "__main__":
    main()
