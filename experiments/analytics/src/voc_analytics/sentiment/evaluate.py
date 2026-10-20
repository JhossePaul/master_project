"""Evaluación común de los modelos de sentimiento (EPIC-5, feature 5.4).

Uso (desde experiments/analytics), después de `baselines.py` y
`pretrained.py`:
    uv run python -m voc_analytics.sentiment.evaluate

Lee todas las predicciones de `data/models/preds/` y las evalúa con el mismo
protocolo (ver `metrics.py` y el plan en `docs/backlog/epic_5.md`, 5.4):

* **Oro *dev* aleatorio** (`gold_v0` y `gold_v1`, 794 evaluables desde la
  segunda ronda del oro): puntos e IC 95 % por bootstrap
  estratificado, sin ponderar y ponderados por 1/π, con diferencias pareadas
  contra M0, M1 y M3 (la referencia ingenua de los métodos de ruido).
  Agrega **M9** (`gemini-3.6-flash`, `prompt_v3`, corrida
  principal de 5.3) como techo de referencia; sus `NA` cuentan como `NEU`.
* **Oro *dev* dirigido** (`gold_v1`, 297 evaluables): las mismas métricas sin
  ponderar, aparte. Sirve para comparar modelos en los casos difíciles, no
  para cifras poblacionales. También se reporta κ por muestra y por criterio.
* Un modelo sin predicciones para todo *dev* no se evalúa y queda en
  `pendientes` (hay que volver a correr su script).
* **Desgloses en *dev* aleatorio** (solo puntos, n chicos): longitud en
  palabras, texto visto o no en entrenamiento, filas donde las estrellas
  difieren del oro y el filtro de 2–60 palabras del EDA preliminar.
* **`holdout_nuevo`** contra la plata (deriva temporal), ponderado por 1/π, con
  desglose por banco y por longitud. Las predicciones por texto se propagan a
  sus filas.
* **Costo:** lo que cada modelo registró al predecir.

Escribe `docs/analytics/sentiment_models_gold_v1_metrics.json`, solo
agregados. `sentiment_models_metrics.json` queda como registro de la primera
ronda (*dev* de 199).
"""

import json

import numpy as np
import polars as pl

from voc_analytics.paths import DOCS, LABELS
from voc_analytics.sentiment.data import (
    PREDS,
    gold,
    holdout_rows,
    silver_rows,
    training_texts,
)
from voc_analytics.sentiment.metrics import ece, evaluate, quality

OUT = DOCS / "sentiment_models_gold_v1_metrics.json"
REFERENCES = ["M0", "M1", "M3", "M4_robertuito_mac"]
HOLDOUT_BOOT = 500


def load_models() -> dict[str, dict]:
    models = {}
    for meta_path in sorted(PREDS.glob("*.json")):
        name = meta_path.stem
        models[name] = {
            "meta": json.loads(meta_path.read_text()),
            "dev": pl.read_parquet(PREDS / f"{name}__dev.parquet"),
            "holdout": pl.read_parquet(PREDS / f"{name}__holdout.parquet"),
        }
    return models


def gemini_dev() -> pl.DataFrame:
    runs = sorted(
        (json.loads(p.read_text())["run"], p)
        for p in (LABELS / "gold_v0").glob("run_*.json")
        if json.loads(p.read_text())["prompt_version"] == "prompt_v3"
    )
    run = runs[0][0]
    first = pl.read_parquet(
        LABELS / "gold_v0" / f"labels_{run}.parquet"
    ).select("item_id", "gemini_s")
    # `gold_v1`: corrida de la cola en el aleatorio, plata en el dirigido;
    # ambas con `prompt_v3`.
    second = pl.read_parquet(LABELS / "gold_v1" / "design.parquet").select(
        "item_id", pl.col("plata").alias("gemini_s")
    )
    return pl.concat([first, second]).select(
        "item_id",
        pl.when(pl.col("gemini_s").is_in(["NEG", "NEU", "POS"]))
        .then(pl.col("gemini_s"))
        .otherwise(pl.lit("NEU"))
        .alias("pred"),
        (~pl.col("gemini_s").is_in(["NEG", "NEU", "POS"])).alias("era_na"),
    ), run


def point(y, p, w=None) -> dict:
    q = quality(y, p, w)
    return {
        k: round(q[k], 4)
        for k in (
            "macro_f1",
            "kappa",
            "exactitud",
            "neg_recall",
            "neg_precision",
        )
    }


def main() -> None:
    models = load_models()
    rows = silver_rows()
    train = training_texts(rows)
    seen = set(train["clave"])
    dev_all = (
        gold()
        .filter((pl.col("particion") == "dev") & (pl.col("oro") != "NA"))
        .sort("bloque_oro", "item_id")
    )
    hold = holdout_rows(rows).sort("id_resena")

    pending = {}
    for name, m in list(models.items()):
        missing = dev_all.join(m["dev"], on="item_id", how="anti").height
        if missing:
            pending[name] = missing
            del models[name]
    if pending:
        print(f"sin predicciones para todo dev: {pending}", flush=True)

    gem, gem_run = gemini_dev()
    all_preds, all_proba = {}, {}
    for name, m in models.items():
        joined = dev_all.select("item_id").join(
            m["dev"], on="item_id", how="left"
        )
        all_preds[name] = joined["pred"].to_numpy()
        if "p_NEG" in joined.columns:
            all_proba[name] = joined.select(
                "p_NEG", "p_NEU", "p_POS"
            ).to_numpy()
    gem_joined = dev_all.select("item_id").join(gem, on="item_id", how="left")
    if gem_joined["pred"].null_count():
        raise ValueError("M9: faltan etiquetas de Gemini en dev")
    all_preds["M9_gemini"] = gem_joined["pred"].to_numpy()

    is_rand = (dev_all["bloque_oro"] == "aleatorio").to_numpy()
    dev, directed = dev_all.filter(is_rand), dev_all.filter(~is_rand)
    dev_preds = {k: v[is_rand] for k, v in all_preds.items()}
    dev_proba = {k: v[is_rand] for k, v in all_proba.items()}
    dir_preds = {k: v[~is_rand] for k, v in all_preds.items()}
    y_dir = directed["oro"].to_numpy()
    print("evaluando dev dirigido", flush=True)
    dir_metrics = evaluate(
        y_dir,
        dir_preds,
        directed["estrato"].to_numpy(),
        np.ones(directed.height),
        reference=[r for r in REFERENCES if r in dir_preds],
    )
    by_group = {}
    for col, frame, preds in (
        ("muestra", dev, dev_preds),
        ("estrato", directed, dir_preds),
    ):
        for value in sorted(frame[col].unique()):
            m = (frame[col] == value).to_numpy()
            y = frame["oro"].to_numpy()
            by_group[value] = {"n": int(m.sum())} | {
                name: point(y[m], p[m]) for name, p in preds.items()
            }

    y_dev = dev["oro"].to_numpy()
    w_dev = dev["peso"].to_numpy()
    print("evaluando dev", flush=True)
    dev_metrics = evaluate(
        y_dev,
        dev_preds,
        dev["estrato"].to_numpy(),
        w_dev,
        reference=[r for r in REFERENCES if r in dev_preds],
    )

    masks = {
        f"longitud_{b}": (dev["longitud"] == b).to_numpy()
        for b in ("1", "2-3", "4-10", "11-30", "31+")
    } | {
        "palabras_2_a_60_eda_preliminar": dev["palabras"]
        .is_between(2, 60)
        .to_numpy(),
        "texto_visto_en_entrenamiento": dev["clave"]
        .is_in(list(seen))
        .to_numpy(),
        "texto_no_visto": ~dev["clave"].is_in(list(seen)).to_numpy(),
        "estrellas_distintas_del_oro": (
            dev["estrellas_clase"] != dev["oro"]
        ).to_numpy(),
    }
    subsets = {}
    for label, mask in masks.items():
        subsets[label] = {"n": int(mask.sum())}
        for name, p in dev_preds.items():
            if label == "estrellas_distintas_del_oro":
                # Clases desbalanceadas y n chico: solo exactitud.
                subsets[label][name] = round(
                    float((p[mask] == y_dev[mask]).mean()), 4
                )
            else:
                subsets[label][name] = point(y_dev[mask], p[mask])

    confusion = {
        name: pl.DataFrame({"oro": y_dev, "pred": p})
        .group_by("oro", "pred")
        .len()
        .pivot(on="pred", index="oro", values="len", sort_columns=True)
        .fill_null(0)
        .sort("oro")
        .to_dicts()
        for name, p in dev_preds.items()
    }
    calibration = {
        name: {
            "muestra": ece(y_dev, pr, ["NEG", "NEU", "POS"]),
            "poblacion": ece(y_dev, pr, ["NEG", "NEU", "POS"], w_dev),
        }
        for name, pr in dev_proba.items()
    }

    hold_preds = {}
    for name, m in models.items():
        if m["meta"].get("por_fila"):
            hold_preds[name] = hold["estrellas_clase"].to_numpy()
            continue
        joined = hold.select("text_id").join(
            m["holdout"], on="text_id", how="left"
        )
        if joined["pred"].null_count():
            raise ValueError(f"{name}: faltan predicciones de holdout")
        hold_preds[name] = joined["pred"].to_numpy()
    y_hold = hold["plata"].to_numpy()
    w_hold = hold["peso"].to_numpy()
    print("evaluando holdout", flush=True)
    hold_metrics = evaluate(
        y_hold,
        hold_preds,
        (hold["bank_id"] + "|" + hold["estrellas"].cast(pl.String)).to_numpy(),
        w_hold,
        reference=[r for r in REFERENCES if r in hold_preds],
        n_boot=HOLDOUT_BOOT,
    )
    hold_breakdown = {}
    for col in ("bank_id", "longitud"):
        hold_breakdown[col] = {}
        for value in sorted(hold[col].unique()):
            m = (hold[col] == value).to_numpy()
            hold_breakdown[col][value] = {"n": int(m.sum())} | {
                name: point(y_hold[m], p[m], w_hold[m])
                for name, p in hold_preds.items()
            }

    metrics = {
        "datos": {
            "plata": "silver_v0 / prompt_v3",
            "textos_entrenamiento": train.height,
            "oro_dev": dev.height,
            "oro_dev_por_muestra": dict(
                dev.group_by("muestra").len().sort("muestra").iter_rows()
            ),
            "oro_dev_dirigido": directed.height,
            "oro_dev_dirigido_clases": dict(
                directed.group_by("oro").len().sort("oro").iter_rows()
            ),
            "oro_dev_clases": dict(
                dev.group_by("oro").len().sort("oro").iter_rows()
            ),
            "oro_dev_longitud": dict(
                dev.group_by("longitud").len().sort("longitud").iter_rows()
            ),
            "filas_holdout_nuevo": hold.height,
            "m9_corrida": gem_run,
            "m9_na_como_neu": int(gem_joined["era_na"].sum()),
        },
        "oro_dev": dev_metrics,
        "oro_dev_dirigido": dir_metrics,
        "oro_dev_por_muestra_y_criterio": by_group,
        "pendientes_sin_prediccion_dev": pending,
        "oro_dev_desgloses": subsets,
        "oro_dev_confusion": confusion,
        "oro_dev_ece": calibration,
        "holdout_nuevo_vs_plata": hold_metrics,
        "holdout_nuevo_desgloses_poblacion": hold_breakdown,
        "modelos": {name: m["meta"] for name, m in models.items()},
    }
    OUT.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")
    for name in dev_preds:
        mm = dev_metrics[name]["muestra"]
        dd = dir_metrics[name]["muestra"]
        print(
            f"{name:24s} F1 {mm['macro_f1']:.3f} {mm['macro_f1_ic95']} "
            f"κ {mm['kappa']:.3f} {mm['kappa_ic95']} · dirigido "
            f"κ {dd['kappa']:.3f} {dd['kappa_ic95']}"
        )


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()
