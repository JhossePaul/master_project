"""Estimaciones poblacionales con *prediction-powered inference* (5.6).

Combina una muestra grande con predicciones (la plata) y una muestra chica
con etiqueta humana (el oro *dev* aleatorio, 799 ítems) para estimar
proporciones por banco × periodo con intervalos válidos (Angelopoulos et al.,
2023). Se usa la variante PPI++ con λ ajustado por celda, que nunca es más
ancha que el estimador solo-oro salvo por ruido en λ.

* **Objetivos** (sobre filas evaluables; misma definición que `gold_v1`):
  * `neg`: proporción de texto `NEG`;
  * `estrellas_difiere`: estrellas (1–2 `NEG`, 3 `NEU`, 4–5 `POS`) distintas
    del texto, 12.5 % en el oro aleatorio completo;
  * `incongruencia_extremos`: 1–2★ con texto `POS` o 4–5★ con texto `NEG`;
  * *Satisfaction Gap* simétrico (P8-9, objeción del autor 2026-10-22: no
    medir solo las quejas escondidas): `texto_peor` (el texto es más
    negativo que las estrellas), `texto_mejor` (más positivo), la
    `brecha_neta` ordinal (puntaje del texto menos el de las estrellas, con
    −1, 0 y +1 para `NEG`, `NEU` y `POS`; va de −2 a +2) y las 9 celdas de la
    matriz estrellas × texto (`m_<estrellas>_<texto>`).
* **Predictor** (D2 de 5.6, `--predictor`):
  * `gemini` (opción A): `prompt_v3` sobre la plata y sobre el oro;
  * `m4` (opción B1, decisión del autor 2026-10-22): M4 RoBERTuito del lote
    `m4_ppi` de Kaggle (reentrenado con pesos guardados). M4 se entrenó con
    la plata, así que no puede ser su muestra sin etiqueta: usa la muestra
    nueva de `sampling.sample_ppi` (`data/labels/ppi_v0/`) y sus predicciones
    `<modelo>__ppi.parquet`. En el oro usa el `__dev` del mismo modelo.
* **Celdas:** banco × los 4 periodos del oro (`<=2019`, `2020-2022`,
  `2023-2024`, `2025-2026`); la plata se reasigna a esos periodos por año.
  Dentro de cada celda, medias de Hájek con 1 / π de cada muestra. Los
  totales por banco, por periodo y del corpus combinan celdas por su tamaño
  estimado con la plata.
* **Independencia:** se quitan de la muestra sin etiqueta las reseñas de
  cualquier cola del oro (`sample_ppi` ya excluye la plata y el oro). Con
  Gemini se usan las tres particiones de la plata (incluida
  `holdout_visto`), porque ahí la plata es la muestra sin etiqueta.
* **No evaluables:** se quitan del oro las `NA` humanas y de la plata las
  `NA` del predictor; en el oro, una `NA` del predictor cuenta como `NEU`
  (como en `sentiment.evaluate`).

Escribe `docs/analytics/calibration/ppi_v0_<predictor>_metrics.json`, solo
agregados. El oro *test* no se toca.

    uv run python -m voc_analytics.calibration.ppi --predictor gemini
"""

import argparse
import json
from datetime import UTC, datetime

import numpy as np
import polars as pl

from voc_analytics.calibration.calibrate import proba_for
from voc_analytics.paths import DOCS
from voc_analytics.sentiment.data import (
    CLASSES,
    PREDS,
    SILVER,
    gold,
    gold_ids,
    stars_class,
)
from voc_analytics.sentiment.evaluate import gemini_dev

OUT_DIR = DOCS / "calibration"
SCORE = {"NEG": -1, "NEU": 0, "POS": 1}
TARGETS = [
    "neg",
    "estrellas_difiere",
    "incongruencia_extremos",
    "texto_peor",
    "texto_mejor",
    "brecha_neta",
    *(f"m_{a}_{b}" for a in SCORE for b in SCORE),
]
Z = 1.959964
M4_MODEL = "M4_robertuito_s1_ppi"
PPI_ROWS = SILVER.parent / "ppi_v0" / "rows.parquet"


def period(year: pl.Expr) -> pl.Expr:
    return (
        pl.when(year <= 2019)
        .then(pl.lit("<=2019"))
        .when(year <= 2022)
        .then(pl.lit("2020-2022"))
        .when(year <= 2024)
        .then(pl.lit("2023-2024"))
        .otherwise(pl.lit("2025-2026"))
    )


def targets(label: str) -> list[pl.Expr]:
    c = pl.col(label)
    return [
        (c == "NEG").cast(pl.Float64).alias(f"neg_{label}"),
        (pl.col("estrellas_clase") != c)
        .cast(pl.Float64)
        .alias(f"estrellas_difiere_{label}"),
        (
            ((pl.col("estrellas") <= 2) & (c == "POS"))
            | ((pl.col("estrellas") >= 4) & (c == "NEG"))
        )
        .cast(pl.Float64)
        .alias(f"incongruencia_extremos_{label}"),
        (score(c) < score(pl.col("estrellas_clase")))
        .cast(pl.Float64)
        .alias(f"texto_peor_{label}"),
        (score(c) > score(pl.col("estrellas_clase")))
        .cast(pl.Float64)
        .alias(f"texto_mejor_{label}"),
        (score(c) - score(pl.col("estrellas_clase")))
        .cast(pl.Float64)
        .alias(f"brecha_neta_{label}"),
        *(
            ((pl.col("estrellas_clase") == a) & (c == b))
            .cast(pl.Float64)
            .alias(f"m_{a}_{b}_{label}")
            for a in SCORE
            for b in SCORE
        ),
    ]


def score(col: pl.Expr) -> pl.Expr:
    return col.replace_strict(SCORE, default=0, return_dtype=pl.Int8)


def m4_labels(frame: pl.DataFrame, key: str, kind: str) -> pl.Series:
    """Etiqueta de M4 calibrado (la T del *dev* no cambia el argmax)."""
    proba = proba_for(M4_MODEL, frame, key, kind)
    return pl.Series(np.asarray(CLASSES)[proba.argmax(axis=1)])


def labeled(predictor: str) -> pl.DataFrame:
    dev = gold().filter(
        (pl.col("particion") == "dev")
        & (pl.col("bloque_oro") == "aleatorio")
        & (pl.col("oro") != "NA")
    )
    if predictor == "gemini":
        gem, _ = gemini_dev()
        dev = dev.join(gem.select("item_id", "pred"), on="item_id", how="left")
        if dev["pred"].null_count():
            raise ValueError("faltan etiquetas de Gemini en el oro dev")
    else:
        dev = dev.with_columns(pred=m4_labels(dev, "item_id", "dev"))
    return dev.select(
        "bank_id",
        "periodo",
        pl.col("peso").alias("w"),
        *targets("oro"),
        *targets("pred"),
    )


def unlabeled(predictor: str) -> pl.DataFrame:
    source = SILVER / "rows.parquet" if predictor == "gemini" else PPI_ROWS
    rows = pl.read_parquet(source).select(
        "id_resena",
        "bank_id",
        "estrellas",
        "fecha",
        "prob_inclusion",
        "text_id",
    )
    rows = rows.filter(~pl.col("id_resena").is_in(list(gold_ids())))
    if predictor == "gemini":
        labels = pl.read_parquet(SILVER / "labels_prompt_v3.parquet").select(
            "text_id", pl.col("gemini_s").alias("pred")
        )
        rows = rows.join(labels, on="text_id", how="inner")
    else:
        texts = rows.select("text_id").unique().sort("text_id")
        rows = rows.join(
            texts.with_columns(pred=m4_labels(texts, "text_id", "ppi")),
            on="text_id",
        )
    return (
        rows.filter(pl.col("pred").is_in(CLASSES))
        .with_columns(
            periodo=period(pl.col("fecha").dt.year()),
            estrellas_clase=stars_class(),
            w=1 / pl.col("prob_inclusion"),
        )
        .select("bank_id", "periodo", "w", *targets("pred"))
    )


def wmean(x: np.ndarray, w: np.ndarray) -> float:
    return float(np.average(x, weights=w))


def wvar_of_mean(x: np.ndarray, w: np.ndarray) -> float:
    """Varianza de la media de Hájek (linealización)."""
    m = wmean(x, w)
    return float(np.sum(w**2 * (x - m) ** 2) / np.sum(w) ** 2)


def cell(g: pl.DataFrame, u: pl.DataFrame, t: str) -> dict:
    y, fg, wg = (
        g[f"{t}_oro"].to_numpy(),
        g[f"{t}_pred"].to_numpy(),
        g["w"].to_numpy(),
    )
    fu, wu = u[f"{t}_pred"].to_numpy(), u["w"].to_numpy()
    classic, v_classic = wmean(y, wg), wvar_of_mean(y, wg)
    n, big_n = len(y), len(fu)
    var_f = np.average((fg - wmean(fg, wg)) ** 2, weights=wg)
    cov = np.average((y - wmean(y, wg)) * (fg - wmean(fg, wg)), weights=wg)
    lam = (
        0.0
        if var_f == 0
        else float(np.clip(cov / ((1 + n / big_n) * var_f), 0, 1))
    )
    est = classic + lam * (wmean(fu, wu) - wmean(fg, wg))
    v = wvar_of_mean(y - lam * fg, wg) + lam**2 * wvar_of_mean(fu, wu)
    return {
        "n_oro": n,
        "n_plata": big_n,
        "lambda": round(lam, 3),
        "ppi": est,
        "var_ppi": v,
        "solo_oro": classic,
        "var_solo_oro": v_classic,
        "solo_predictor": wmean(fu, wu),
        "tamano": float(wu.sum()),
    }


def combine(cells: list[dict]) -> dict:
    total = sum(c["tamano"] for c in cells)
    out = {"n_oro": sum(c["n_oro"] for c in cells)}
    for k in ("ppi", "solo_oro"):
        est = sum(c["tamano"] / total * c[k] for c in cells)
        var = sum((c["tamano"] / total) ** 2 * c[f"var_{k}"] for c in cells)
        half = Z * var**0.5
        out[k] = {
            "estimacion": round(est, 4),
            "ic": [round(est - half, 4), round(est + half, 4)],
            "ancho": round(2 * half, 4),
        }
    out["solo_predictor"] = round(
        sum(c["tamano"] / total * c["solo_predictor"] for c in cells), 4
    )
    # Sin casos en el oro el ancho solo-oro es 0 y la reducción no se define.
    out["reduccion_ancho"] = (
        round(1 - out["ppi"]["ancho"] / out["solo_oro"]["ancho"], 3)
        if out["solo_oro"]["ancho"]
        else None
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictor", choices=["gemini", "m4"], required=True)
    predictor = parser.parse_args().predictor
    if predictor == "m4" and not (PREDS / f"{M4_MODEL}__ppi.parquet").exists():
        raise SystemExit(
            f"faltan {M4_MODEL}__ppi.parquet: correr el lote `m4_ppi` de Kaggle"
        )
    g_all, u_all = labeled(predictor), unlabeled(predictor)
    keys = sorted(
        set(map(tuple, g_all.select("bank_id", "periodo").rows()))
        & set(map(tuple, u_all.select("bank_id", "periodo").rows()))
    )
    result: dict = {}
    for t in TARGETS:
        cells = {}
        for bank, per in keys:
            g = g_all.filter(
                (pl.col("bank_id") == bank) & (pl.col("periodo") == per)
            )
            u = u_all.filter(
                (pl.col("bank_id") == bank) & (pl.col("periodo") == per)
            )
            cells[(bank, per)] = cell(g, u, t)
        by_bank = {
            b: combine([c for (bb, _), c in cells.items() if bb == b])
            for b in sorted({b for b, _ in keys})
        }
        by_period = {
            p: combine([c for (_, pp), c in cells.items() if pp == p])
            for p in sorted({p for _, p in keys})
        }
        result[t] = {
            "corpus": combine(list(cells.values())),
            "por_banco": by_bank,
            "por_periodo": by_period,
            "por_celda": {
                f"{b}|{p}": combine([c]) | {"lambda": c["lambda"]}
                for (b, p), c in cells.items()
            },
        }
    out = OUT_DIR / f"ppi_v0_{predictor}_metrics.json"
    out.write_text(
        json.dumps(
            {
                "generado": datetime.now(UTC).isoformat(timespec="seconds"),
                "predictor": predictor
                if predictor == "gemini"
                else f"{M4_MODEL} (calibrado)",
                "n_oro": int(g_all.height),
                "n_plata": int(u_all.height),
                "celdas": len(keys),
                "objetivos": result,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(f"escrito {out}", flush=True)


if __name__ == "__main__":
    main()
