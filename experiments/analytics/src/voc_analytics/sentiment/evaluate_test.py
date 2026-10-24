"""Evaluación única de M4 y M9 en el oro *test* (EPIC-5, 5.8, P8-1).

Protocolo y regla de decisión aprobados por el autor el 2026-10-22, antes de
mirar el *test* (`docs/analytics/decision_record.md`, tema 1):

* **M4:** predice el *test* en el Mac con los pesos
  `M4_robertuito_s{1,2,3}_ppi` y aplica la T de cada semilla
  (`calibration_v0_metrics.json`). La T no cambia la clase predicha; solo
  afecta al ECE. Antes, como control, predice el *dev* aleatorio y compara con
  las predicciones guardadas de Kaggle (deben coincidir).
* **M9:** la etiqueta de `prompt_v3` ya guardada para esos ítems (la misma
  fuente que `evaluate.py`); sus `NA` cuentan como `NEU`. Si falta alguna,
  el script se detiene.
* **Métricas:** las de 5.4 (`metrics.evaluate`): κ, macro-F1, exactitud y
  recall y precisión de `NEG`, sin ponderar y ponderados por 1/π, con IC por
  *bootstrap* estratificado (2 000 réplicas) y la diferencia pareada M9 − M4
  por semilla. Se agregan las diferencias pareadas de recall y precisión de
  `NEG` y de F1 por clase, que pide la regla de decisión, y el ECE de M4.

Corre una sola vez. Escribe
`docs/analytics/sentiment/sentiment_models_test_metrics.json`, solo
agregados; las predicciones del *test* no se guardan.

    uv run python -m voc_analytics.sentiment.evaluate_test
"""

import json
from datetime import UTC, datetime

import numpy as np
import polars as pl
import torch

from voc_analytics.calibration.calibrate import apply, logits
from voc_analytics.paths import DOCS
from voc_analytics.sentiment.data import CLASSES, PREDS, WEIGHTS, gold
from voc_analytics.sentiment.encoder import encode, predict_proba
from voc_analytics.sentiment.evaluate import gemini_dev
from voc_analytics.sentiment.metrics import (
    BOOTSTRAP,
    SEED,
    _ci,
    _resample,
    ece,
    evaluate,
    quality,
)

OUT = DOCS / "sentiment" / "sentiment_models_test_metrics.json"
CALIBRATION = DOCS / "calibration" / "calibration_v0_metrics.json"
SEEDS = [f"M4_robertuito_s{s}_ppi" for s in (1, 2, 3)]
GEMINI = "M9_gemini"
EXTRA = ["kappa", "neg_recall", "neg_precision", "f1_NEG", "f1_NEU", "f1_POS"]


def load_model(name: str):
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    path = WEIGHTS / name
    tok = AutoTokenizer.from_pretrained(path)
    model = AutoModelForSequenceClassification.from_pretrained(
        path, dtype=torch.float32
    ).eval()
    if [model.config.id2label[i] for i in range(3)] != CLASSES:
        raise ValueError(f"{name}: orden de clases inesperado")
    return tok, model


def scalars(y: np.ndarray, p: np.ndarray) -> dict:
    q = quality(y, p)
    return {k: q[k] for k in EXTRA[:3]} | {
        f"f1_{c}": q["f1_por_clase"][c] for c in CLASSES
    }


def paired(y: np.ndarray, preds: dict, strata: np.ndarray) -> dict:
    """M9 − cada semilla de M4, pareado, para las métricas de la regla."""
    rng = np.random.default_rng(SEED)
    acc = {(m, s): [] for m in SEEDS for s in EXTRA}
    for _ in range(BOOTSTRAP):
        i = _resample(strata, rng)
        gem = scalars(y[i], preds[GEMINI][i])
        for m in SEEDS:
            own = scalars(y[i], preds[m][i])
            for s in EXTRA:
                acc[m, s].append(gem[s] - own[s])
    gem = scalars(y, preds[GEMINI])
    return {
        m: {
            s: {
                "diferencia": round(gem[s] - scalars(y, preds[m])[s], 4),
                "ic95": _ci(acc[m, s]),
            }
            for s in EXTRA
        }
        for m in SEEDS
    }


def main() -> None:
    torch.manual_seed(SEED)
    g = gold().filter(pl.col("oro") != "NA")
    test = g.filter(pl.col("particion") == "test").sort("item_id")
    dev = g.filter(
        (pl.col("particion") == "dev") & (pl.col("bloque_oro") == "aleatorio")
    ).sort("item_id")
    if set(test["bloque_oro"]) != {"aleatorio"}:
        raise ValueError("el test debería ser solo aleatorio")

    gem, gem_run = gemini_dev()
    gem_test = test.select("item_id").join(gem, on="item_id", how="left")
    if gem_test["pred"].null_count():
        raise ValueError("M9: faltan etiquetas de Gemini en el test")

    temps = json.loads(CALIBRATION.read_text())["modelos"]
    preds, ece_m4, control = {}, {}, {}
    y = test["oro"].to_numpy()
    w = test["peso"].to_numpy()
    for name in SEEDS:
        print(f"prediciendo {name}", flush=True)
        tok, model = load_model(name)
        saved = dev.select("item_id").join(
            pl.read_parquet(PREDS / f"{name}__dev.parquet"),
            on="item_id",
            how="left",
        )
        saved_proba = saved.select("p_NEG", "p_NEU", "p_POS").to_numpy()
        p_dev, _ = predict_proba(
            model, tok, encode(tok, dev["texto_sanitizado"].to_list())
        )
        control[name] = {
            "acuerdo_clase_dev": round(
                float(
                    np.mean(
                        np.asarray(CLASSES)[p_dev.argmax(axis=1)]
                        == saved["pred"].to_numpy()
                    )
                ),
                4,
            ),
            "max_dif_prob_dev": round(
                float(np.abs(p_dev - saved_proba).max()), 4
            ),
        }
        if control[name]["acuerdo_clase_dev"] < 0.99:
            # Se detiene antes de predecir el test.
            raise ValueError(f"{name}: no reproduce dev: {control[name]}")
        raw, stats = predict_proba(
            model, tok, encode(tok, test["texto_sanitizado"].to_list())
        )
        t = temps[name]["temperature"]["temperatura"]
        cal = apply(logits(raw), np.array([np.log(t)]))
        pred = np.asarray(CLASSES)[raw.argmax(axis=1)]
        if not np.array_equal(pred, np.asarray(CLASSES)[cal.argmax(axis=1)]):
            raise ValueError(f"{name}: la T cambió alguna clase")
        preds[name] = pred
        ece_m4[name] = {
            "temperatura": t,
            "sin_calibrar": {
                "muestra": round(ece(y, raw, CLASSES), 4),
                "poblacion": round(ece(y, raw, CLASSES, w), 4),
            },
            "calibrado": {
                "muestra": round(ece(y, cal, CLASSES), 4),
                "poblacion": round(ece(y, cal, CLASSES, w), 4),
            },
            "inferencia": stats,
        }
        del model
    preds[GEMINI] = gem_test["pred"].to_numpy()

    strata = test["estrato"].to_numpy()
    print("evaluando el test", flush=True)
    metrics = evaluate(y, preds, strata, w, reference=SEEDS)
    for name in preds:
        for kind in ("muestra", "poblacion"):
            metrics[name][kind].pop("f1_por_clase", None)
            q = quality(y, preds[name], None if kind == "muestra" else w)
            metrics[name][kind]["f1_por_clase"] = {
                c: round(v, 4) for c, v in q["f1_por_clase"].items()
            }
    mean = {
        kind: {
            s: round(float(np.mean([metrics[m][kind][s] for m in SEEDS])), 4)
            for s in ("kappa", "macro_f1", "exactitud", "neg_recall")
            + ("neg_precision",)
        }
        for kind in ("muestra", "poblacion")
    }

    result = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "protocolo": "decision_record.md, tema 1 (aprobado 2026-10-22)",
        "n_test": int(test.height),
        "n_test_na_humano_excluidos": int(
            gold()
            .filter((pl.col("particion") == "test") & (pl.col("oro") == "NA"))
            .height
        ),
        "por_muestra": dict(
            test.group_by("muestra").len().sort("muestra").iter_rows()
        ),
        "distribucion_oro": dict(
            test.group_by("oro").len().sort("oro").iter_rows()
        ),
        "m9_corrida": gem_run,
        "m9_na_como_neu": int(gem_test["era_na"].sum()),
        "bootstrap": BOOTSTRAP,
        "control_dev_contra_kaggle": control,
        "modelos": metrics,
        "m4_media_3_semillas": mean,
        "m9_menos_m4_regla": paired(y, preds, strata),
        "ece_m4": ece_m4,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
