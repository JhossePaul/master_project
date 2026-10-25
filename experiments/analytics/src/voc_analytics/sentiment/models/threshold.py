"""M4 con sesgo de `NEU` ajustado sobre la plata (EPIC-5, feature 5.4).

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.sentiment.models.threshold \\
        [M4_robertuito_s1 M4_robertuito_s2 M4_robertuito_s3]

* No reentrena: suma un sesgo b al log-probabilidad de `NEU` de un modelo ya
  ajustado, log p'(c) = log p(c) + b · [c = NEU], y renormaliza.
* **b se elige con la plata de `holdout_nuevo`** (textos nunca vistos en el
  ajuste), maximizando el macro-F1 contra la plata; en empate, el |b| menor.
  Se usa `holdout_nuevo` porque M4 no guarda pesos ni las probabilidades de
  su validación del 5 %. El oro *dev* no interviene.
* Escribe `<modelo>_sesgo_neu` en `data/models/preds/`. Sus métricas de
  holdout contra la plata quedan **dentro de muestra** (b se eligió ahí).
"""

import sys

import numpy as np
import polars as pl

from voc_analytics.sentiment.data import (
    CLASSES,
    PREDS,
    holdout_rows,
    save_predictions,
    silver_rows,
)
from voc_analytics.sentiment.metrics import quality

DEFAULT = ["M4_robertuito_s1", "M4_robertuito_s2", "M4_robertuito_s3"]
GRID = np.round(np.arange(-1.0, 4.0001, 0.05), 2)
NEU = CLASSES.index("NEU")
P_COLS = [f"p_{c}" for c in CLASSES]


def shift(proba: np.ndarray, b: float) -> np.ndarray:
    logp = np.log(np.clip(proba, 1e-12, 1.0))
    logp[:, NEU] += b
    logp -= logp.max(1, keepdims=True)
    out = np.exp(logp)
    return out / out.sum(1, keepdims=True)


def frame(df: pl.DataFrame, proba: np.ndarray) -> pl.DataFrame:
    return df.drop(["pred", *P_COLS]).with_columns(
        pred=pl.Series(np.asarray(CLASSES)[proba.argmax(1)], dtype=pl.String),
        **{c: pl.Series(proba[:, i]) for i, c in enumerate(P_COLS)},
    )


def main() -> None:
    models = sys.argv[1:] or DEFAULT
    plata = (
        holdout_rows(silver_rows()).unique("text_id").select("text_id", "plata")
    )
    for model in models:
        hold = pl.read_parquet(PREDS / f"{model}__holdout.parquet")
        dev = pl.read_parquet(PREDS / f"{model}__dev.parquet")
        y = hold.join(plata, on="text_id", how="left")["plata"].to_numpy()
        proba = hold.select(P_COLS).to_numpy()
        scores = []
        for b in GRID:
            pred = np.asarray(CLASSES)[shift(proba, b).argmax(1)]
            scores.append(quality(y, pred)["macro_f1"])
        scores = np.asarray(scores)
        best = GRID[np.flatnonzero(scores == scores.max())]
        b = float(best[np.argmin(np.abs(best))])
        base = quality(y, np.asarray(CLASSES)[proba.argmax(1)])
        tuned = quality(y, np.asarray(CLASSES)[shift(proba, b).argmax(1)])
        name = f"{model}_sesgo_neu"
        save_predictions(
            name,
            frame(dev, shift(dev.select(P_COLS).to_numpy(), b)),
            frame(hold, shift(proba, b)),
            {
                "modelo": name,
                "base": model,
                "sesgo_neu": b,
                "criterio": "macro-F1 contra la plata de holdout_nuevo",
                "textos_seleccion": len(y),
                "neu_seleccion": int((y == "NEU").sum()),
                "seleccion_macro_f1_base": round(base["macro_f1"], 4),
                "seleccion_macro_f1_ajustado": round(tuned["macro_f1"], 4),
                "nota": "métricas de holdout dentro de muestra",
            },
        )
        print(
            f"{name}: b = {b:+.2f}, macro-F1 holdout "
            f"{base['macro_f1']:.4f} → {tuned['macro_f1']:.4f}",
            flush=True,
        )


if __name__ == "__main__":
    main()
