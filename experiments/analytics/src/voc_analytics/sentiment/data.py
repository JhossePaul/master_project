"""Datos comunes de la competencia de sentimiento (EPIC-5, feature 5.4).

* **Plata (`silver_v0`, `prompt_v3`):** solo `entrenamiento` entrena; solo
  `holdout_nuevo` evalúa la deriva; `holdout_visto` nunca se usa.
  * Las filas cuya reseña está en cualquier cola del oro (`gold_v0`,
    `gold_v1`, `gold_v1_a2`) se quitan del entrenamiento, para que el oro no
    se entrene consigo mismo. Su texto puede seguir entrando por otras
    filas con el mismo texto: es la repetición natural del corpus
    ("excelente") y se reporta aparte (`visto`).
  * Se entrena **una vez por texto único** (`text_id`, igual que el
    etiquetado). Cada texto lleva sus filas de entrenamiento y su peso de
    diseño (suma de 1 / probabilidad de inclusión) para las ablaciones.
  * `NA` de Gemini queda fuera: los modelos son de 3 clases y
    `NO_EVALUABLE` lo cubren las reglas de elegibilidad.
* **Oro vigente:** dos muestras aleatorias y un bloque dirigido.
  * `gold_v0_r2`: las 400 reseñas del bloque `aleatorio`. `dev` = las 199 que
    en la primera ronda fueron asistidas; `test` = las 201 que siempre fueron
    a ciegas. La primera ronda ya partió cada estrato banco × periodo a la
    mitad, así que ambas son muestras estratificadas.
  * `gold_v1` (5.3, segunda ronda, todo a ciegas): 1 000 aleatorias
    estratificadas por banco × periodo × estrellas (600 `dev`, 400 `test`) y
    300 dirigidas, que también son `dev`.
  * `bloque_oro` distingue `aleatorio` de `dirigido`. **Las métricas
    principales y las poblacionales usan solo `aleatorio`**; el dirigido no
    tiene π (`peso` nulo) y se reporta aparte.
  * `peso` combina las dos muestras aleatorias: 1/π de cada una, escalado por
    su tamaño efectivo de Kish, para que cada muestra estime la población y
    pese según su información.
  * `test` no se evalúa hasta el registro de decisión (5.8).
"""

import os
from pathlib import Path

import polars as pl

from voc_analytics.paths import DATA, LABELS, MODELS

SILVER = LABELS / "silver_v0"
PREDS = Path(os.environ.get("VOC_PREDS", MODELS / "preds"))
# Pesos de los modelos ajustados (fuera de git; en Kaggle, la salida).
WEIGHTS = Path(os.environ.get("VOC_WEIGHTS", MODELS / "weights"))
PPI_TEXTS = LABELS / "ppi_v0" / "texts.parquet"
# En Kaggle, `VOC_BUNDLE` apunta al paquete de `export_bundle.py`: las mismas
# tablas que devuelven `silver_rows`, `gold` (solo *dev*) y `gold_ids`.
BUNDLE = Path(os.environ["VOC_BUNDLE"]) if "VOC_BUNDLE" in os.environ else None
SNAPSHOT = DATA / "tds_20261016T054714Z.parquet"
CLASSES = ["NEG", "NEU", "POS"]


def clave(col: str) -> pl.Expr:
    """Misma clave normalizada que `sample_silver.py`."""
    return (
        pl.col(col)
        .str.to_lowercase()
        .str.replace_all(r"[^\p{L}\p{N}]+", "")
        .alias("clave")
    )


def snapshot(ids, columns: list[str]) -> pl.DataFrame:
    """Columnas del snapshot solo para las reseñas pedidas (lectura perezosa).

    Leer las 2.65 M filas de texto ocupa ~1 GB, que en el Mac de 8 GB compite
    con el ajuste de encoders en MPS.
    """
    return (
        pl.scan_parquet(SNAPSHOT)
        .select("id_resena", *columns)
        .filter(pl.col("id_resena").is_in(list(ids)))
        .collect()
    )


def stars_class() -> pl.Expr:
    """M0: 1–2 NEG, 3 NEU, 4–5 POS."""
    return (
        pl.when(pl.col("estrellas") <= 2)
        .then(pl.lit("NEG"))
        .when(pl.col("estrellas") == 3)
        .then(pl.lit("NEU"))
        .otherwise(pl.lit("POS"))
    )


def _human(folder: Path) -> pl.DataFrame:
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
            .alias("oro"),
        )
    )


def words() -> pl.Expr:
    """`palabras` de las reglas de elegibilidad, sobre `texto_limpio`."""
    return pl.col("texto_limpio").fill_null("").str.count_matches(r"\S+")


LENGTH_BINS = [(1, 1), (2, 3), (4, 10), (11, 30), (31, None)]


def length_bin() -> pl.Expr:
    expr = pl.lit(None, dtype=pl.String)
    for lo, hi in reversed(LENGTH_BINS):
        cond = pl.col("palabras") >= lo
        if hi is not None:
            cond &= pl.col("palabras") <= hi
        label = f"{lo}" if lo == hi else (f"{lo}-{hi}" if hi else f"{lo}+")
        expr = pl.when(cond).then(pl.lit(label)).otherwise(expr)
    return expr.alias("longitud")


def _gold_v0() -> pl.DataFrame:
    first = pl.read_parquet(LABELS / "gold_v0" / "queue.parquet").select(
        "item_id",
        "modo",
        "bloque",
        "id_resena",
        "bank_id",
        "periodo",
        "estrato",
        "prob_inclusion",
    )
    second = pl.read_parquet(LABELS / "gold_v0_r2" / "queue.parquet").select(
        "item_id", "origen_item", "texto_sanitizado"
    )
    labelled = second.join(_human(LABELS / "gold_v0_r2"), on="item_id").drop(
        "item_id"
    )
    return (
        first.filter(pl.col("bloque") == "aleatorio")
        .join(labelled, left_on="item_id", right_on="origen_item")
        .with_columns(
            muestra=pl.lit("gold_v0"),
            bloque_oro=pl.lit("aleatorio"),
            particion=pl.when(pl.col("modo") == "asistido")
            .then(pl.lit("dev"))
            .otherwise(pl.lit("test")),
        )
        .drop("bloque")
    )


def _gold_v1() -> pl.DataFrame:
    folder = LABELS / "gold_v1"
    if not (folder / "annotations.csv").exists():
        return pl.DataFrame()
    queue = pl.read_parquet(folder / "queue.parquet").filter(
        pl.col("bloque") != "reanotacion"
    )
    design = pl.read_parquet(folder / "design.parquet").select(
        "item_id", "particion", "estrato", "prob_inclusion", "criterio"
    )
    return (
        queue.select(
            "item_id",
            "modo",
            "id_resena",
            "bank_id",
            "texto_sanitizado",
            "bloque",
        )
        .join(design, on="item_id")
        .join(_human(folder), on="item_id")
        .with_columns(
            muestra=pl.lit("gold_v1"),
            bloque_oro=pl.col("bloque"),
            # El dirigido no tiene π (el de la plata no aplica) ni periodo de
            # estrato; su estrato es el criterio de selección.
            estrato=pl.coalesce(
                "estrato", pl.format("dirigido|{}", "criterio")
            ),
            prob_inclusion=pl.when(pl.col("bloque") == "aleatorio").then(
                pl.col("prob_inclusion")
            ),
            periodo=pl.col("estrato")
            .str.split("|")
            .list.get(1, null_on_oob=True),
        )
        .drop("bloque", "criterio")
    )


def _kish_scale(df: pl.DataFrame) -> pl.Expr:
    """Factor por muestra: tamaño efectivo de Kish sobre el total."""
    neff = (
        df.filter(pl.col("prob_inclusion").is_not_null())
        .group_by("muestra")
        .agg(
            (
                (1 / pl.col("prob_inclusion")).sum() ** 2
                / (1 / pl.col("prob_inclusion") ** 2).sum()
            ).alias("neff")
        )
    )
    share = dict(
        zip(neff["muestra"], neff["neff"] / neff["neff"].sum(), strict=True)
    )
    return pl.col("muestra").replace_strict(share, default=None)


def gold() -> pl.DataFrame:
    """Oro vigente con `particion` (`dev` / `test`) y `bloque_oro`."""
    if BUNDLE:
        return pl.read_parquet(BUNDLE / "gold_dev.parquet")
    df = pl.concat([_gold_v0(), _gold_v1()], how="diagonal_relaxed")
    snap = snapshot(df["id_resena"], ["texto_limpio", "estrellas"])
    return (
        df.join(snap, on="id_resena", how="left")
        .with_columns(
            clave("texto_limpio"),
            peso=_kish_scale(df) / pl.col("prob_inclusion"),
            estrellas_clase=stars_class(),
            palabras=words(),
        )
        .with_columns(length_bin())
    )


GOLD_QUEUES = ["gold_v0", "gold_v1", "gold_v1_a2"]


def gold_ids() -> set[str]:
    """Reseñas de **todas** las colas del oro, presentes y futuras.

    Ninguna entra al entrenamiento: las de `gold_v1` (5.3, segunda ronda)
    serán *dev* o *test*, y 341 de ellas estaban en la plata de entrenamiento.
    """
    if BUNDLE:
        return set(pl.read_parquet(BUNDLE / "gold_ids.parquet")["id_resena"])
    return {
        i
        for q in GOLD_QUEUES
        if (LABELS / q / "queue.parquet").exists()
        for i in pl.read_parquet(LABELS / q / "queue.parquet")["id_resena"]
    }


def silver_rows() -> pl.DataFrame:
    if BUNDLE:
        return pl.read_parquet(BUNDLE / "silver_rows.parquet")
    rows = pl.read_parquet(SILVER / "rows.parquet").select(
        "id_resena",
        "bank_id",
        "periodo",
        "estrellas",
        "prob_inclusion",
        "split",
        "text_id",
    )
    texts = pl.read_parquet(SILVER / "texts.parquet").select(
        "text_id", "texto_sanitizado", "clave"
    )
    labels = pl.read_parquet(SILVER / "labels_prompt_v3.parquet").select(
        "text_id", pl.col("gemini_s").alias("plata")
    )
    rows = rows.filter(pl.col("split") != "holdout_visto")
    snap = snapshot(rows["id_resena"], ["texto_limpio"])
    return (
        rows.join(texts, on="text_id")
        .join(labels, on="text_id")
        .join(snap, on="id_resena", how="left")
        .with_columns(peso=1 / pl.col("prob_inclusion"), palabras=words())
        .with_columns(length_bin())
    )


def ppi_texts() -> pl.DataFrame:
    """Textos únicos de la muestra sin etiqueta de PPI (5.6, `sample_ppi`)."""
    path = BUNDLE / "ppi_texts.parquet" if BUNDLE else PPI_TEXTS
    return pl.read_parquet(path).select("text_id", "texto_sanitizado")


def training_texts(rows: pl.DataFrame) -> pl.DataFrame:
    """Un registro por texto único de entrenamiento, sin reseñas del oro."""
    return (
        rows.filter(
            (pl.col("split") == "entrenamiento")
            & ~pl.col("id_resena").is_in(list(gold_ids()))
            & (pl.col("plata") != "NA")
        )
        .sort("id_resena")
        .group_by("text_id")
        .agg(
            pl.col(
                "texto_sanitizado",
                "texto_limpio",
                "clave",
                "plata",
                "bank_id",
                "periodo",
            ).first(),
            pl.len().alias("filas"),
            pl.col("peso").sum().alias("peso_diseno"),
        )
        .sort("text_id")
    )


def holdout_rows(rows: pl.DataFrame) -> pl.DataFrame:
    """Filas de `holdout_nuevo` con etiqueta evaluable (deriva temporal)."""
    return rows.filter(
        (pl.col("split") == "holdout_nuevo") & (pl.col("plata") != "NA")
    ).with_columns(estrellas_clase=stars_class())


def holdout_texts(hold: pl.DataFrame) -> pl.DataFrame:
    """Textos únicos de `holdout_nuevo`: se predice una vez por texto."""
    return (
        hold.sort("id_resena")
        .group_by("text_id")
        .agg(pl.col("texto_sanitizado", "texto_limpio").first())
        .sort("text_id")
    )


def save_predictions(
    model: str, dev: pl.DataFrame, hold: pl.DataFrame, meta: dict
) -> None:
    """Predicciones de un modelo: `dev` por `item_id`, holdout por `text_id`.

    Cada frame trae `pred` y, si el modelo da probabilidades, `p_NEG`,
    `p_NEU` y `p_POS`. El oro *test* nunca se predice aquí.
    """
    import json

    PREDS.mkdir(parents=True, exist_ok=True)
    dev.write_parquet(PREDS / f"{model}__dev.parquet")
    hold.write_parquet(PREDS / f"{model}__holdout.parquet")
    (PREDS / f"{model}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n"
    )


def training_star_pairs(rows: pl.DataFrame) -> pl.DataFrame:
    """Pares (texto único, estrellas) de entrenamiento para M3, M6 y M7.

    Mismas filas que `training_texts` (sin reseñas del oro ni `NA` de la
    plata, para comparar sobre la misma población de textos). Un texto con
    filas de distintas estrellas da un par por nivel; `filas` es el peso.
    """
    return (
        rows.filter(
            (pl.col("split") == "entrenamiento")
            & ~pl.col("id_resena").is_in(list(gold_ids()))
            & (pl.col("plata") != "NA")
        )
        .sort("id_resena")
        .group_by("text_id", "estrellas")
        .agg(
            pl.col(
                "texto_sanitizado",
                "texto_limpio",
                "clave",
                "plata",
                "bank_id",
                "periodo",
            ).first(),
            pl.len().alias("filas"),
        )
        .with_columns(estrellas_clase=stars_class())
        .sort("text_id", "estrellas")
    )
