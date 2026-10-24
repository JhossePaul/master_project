"""Calibración de las probabilidades de los modelos de sentimiento (5.6).

Ajusta *temperature scaling* (un parámetro T) y *vector scaling* (T más un
sesgo por clase) sobre las probabilidades guardadas en 5.4, sin reentrenar.
Como solo se guardaron probabilidades, se usa log p como logit: softmax de
log p / T es p^(1/T) normalizado, equivalente al escalado de los logits.

* **Ajuste:** pérdida logarítmica ponderada por 1 / π en el oro *dev*
  aleatorio (794 evaluables), para calibrar en sentido poblacional.
* **Sin optimismo:** ese *dev* ya sirvió para elegir modelos, así que el ECE
  calibrado se mide fuera de partición, con validación cruzada de 5
  particiones estratificadas por la etiqueta del oro. Los parámetros finales
  se ajustan con todo el *dev*.
* **Prueba de transferencia:** con los parámetros finales, el *dev* dirigido
  (sin pesos) y `holdout_nuevo` contra la plata (deriva temporal; la plata es
  Gemini, así que solo indica la dirección).
* **Intervalos:** bootstrap estratificado por el estrato del diseño, pareado
  entre la versión sin calibrar y la calibrada fuera de partición.

Escribe `docs/analytics/calibration/calibration_v0_metrics.json` y un
diagrama de fiabilidad en `docs/analytics/calibration/figures/`, solo
agregados. El oro *test* no se toca.

    uv run python -m voc_analytics.calibration.calibrate
"""

import json
from datetime import UTC, datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import polars as pl  # noqa: E402
from scipy.optimize import minimize  # noqa: E402
from sklearn.model_selection import StratifiedKFold  # noqa: E402

from voc_analytics.paths import DOCS  # noqa: E402
from voc_analytics.sentiment.data import (  # noqa: E402
    CLASSES,
    PREDS,
    gold,
    holdout_rows,
    silver_rows,
)
from voc_analytics.sentiment.metrics import _resample, ece  # noqa: E402

OUT_DIR = DOCS / "calibration"
OUT = OUT_DIR / "calibration_v0_metrics.json"
FIGURES = OUT_DIR / "figures"
MODELS = [
    "M1",
    *(f"M4_robertuito_s{s}" for s in (1, 2, 3)),
    *(f"M4_beto_s{s}" for s in (1, 2, 3)),
    # Lote `m4_ppi` (5.6): mismos ajustes con pesos guardados.
    *(f"M4_robertuito_s{s}_ppi" for s in (1, 2, 3)),
]
FOLDS = 5
BOOTSTRAP = 2000
SEED = 20261022
EPS = 1e-6


def logits(proba: np.ndarray) -> np.ndarray:
    return np.log(np.clip(proba, EPS, 1.0))


def apply(z: np.ndarray, params: np.ndarray) -> np.ndarray:
    """`params` = [log T] o [log T, b_NEU, b_POS] (b_NEG fijo en 0)."""
    s = z / np.exp(params[0])
    if params.size > 1:
        s = s + np.concatenate([[0.0], params[1:]])
    s = s - s.max(axis=1, keepdims=True)
    e = np.exp(s)
    return e / e.sum(axis=1, keepdims=True)


def nll(proba: np.ndarray, y_idx: np.ndarray, w: np.ndarray) -> float:
    p = np.clip(proba[np.arange(len(y_idx)), y_idx], EPS, 1.0)
    return float(np.average(-np.log(p), weights=w))


def brier(proba: np.ndarray, y_idx: np.ndarray, w: np.ndarray) -> float:
    onehot = np.eye(len(CLASSES))[y_idx]
    return float(np.average(((proba - onehot) ** 2).sum(axis=1), weights=w))


def fit(z: np.ndarray, y_idx: np.ndarray, w: np.ndarray, kind: str):
    x0 = np.zeros(1 if kind == "temperature" else 3)
    res = minimize(
        lambda q: nll(apply(z, q), y_idx, w), x0, method="Nelder-Mead"
    )
    return res.x


def classwise_ece(
    y: np.ndarray, proba: np.ndarray, w: np.ndarray, bins: int = 10
) -> dict[str, float]:
    out = {}
    edges = np.linspace(0, 1, bins + 1)
    for k, c in enumerate(CLASSES):
        conf, hit, err = proba[:, k], (y == c).astype(float), 0.0
        for lo, hi in zip(edges[:-1], edges[1:], strict=True):
            m = (conf > lo) & (conf <= hi) if lo else (conf <= hi)
            if m.any():
                err += (
                    w[m].sum()
                    / w.sum()
                    * abs(
                        np.average(hit[m], weights=w[m])
                        - np.average(conf[m], weights=w[m])
                    )
                )
        out[c] = round(float(err), 4)
    return out


def reliability(
    y: np.ndarray, proba: np.ndarray, w: np.ndarray, bins: int = 10
) -> list[dict]:
    conf = proba.max(axis=1)
    hit = (np.asarray(CLASSES)[proba.argmax(axis=1)] == y).astype(float)
    edges = np.linspace(0, 1, bins + 1)
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            rows.append(
                {
                    "bin": [round(lo, 1), round(hi, 1)],
                    "n": int(m.sum()),
                    "peso": round(float(w[m].sum() / w.sum()), 4),
                    "confianza": round(
                        float(np.average(conf[m], weights=w[m])), 4
                    ),
                    "acierto": round(
                        float(np.average(hit[m], weights=w[m])), 4
                    ),
                }
            )
    return rows


def summary(y: np.ndarray, proba: np.ndarray, w: np.ndarray) -> dict:
    y_idx = np.array([CLASSES.index(v) for v in y])
    pred = np.asarray(CLASSES)[proba.argmax(axis=1)]
    return {
        "ece": ece(y, proba, CLASSES, w),
        "ece_por_clase": classwise_ece(y, proba, w),
        "log_loss": round(nll(proba, y_idx, w), 4),
        "brier": round(brier(proba, y_idx, w), 4),
        "exactitud": round(float(np.average(pred == y, weights=w)), 4),
        "confianza_media": round(
            float(np.average(proba.max(axis=1), weights=w)), 4
        ),
    }


def out_of_fold(
    z: np.ndarray, y: np.ndarray, w: np.ndarray, kind: str
) -> np.ndarray:
    y_idx = np.array([CLASSES.index(v) for v in y])
    proba = np.zeros_like(z)
    folds = StratifiedKFold(FOLDS, shuffle=True, random_state=SEED)
    for train, test in folds.split(z, y):
        params = fit(z[train], y_idx[train], w[train], kind)
        proba[test] = apply(z[test], params)
    return proba


def paired_ci(
    y: np.ndarray,
    raw: np.ndarray,
    cal: np.ndarray,
    w: np.ndarray,
    strata: np.ndarray,
) -> dict:
    rng = np.random.default_rng(SEED)
    a, b, d = [], [], []
    for _ in range(BOOTSTRAP):
        i = _resample(strata, rng)
        ea = ece(y[i], raw[i], CLASSES, w[i])
        eb = ece(y[i], cal[i], CLASSES, w[i])
        a.append(ea)
        b.append(eb)
        d.append(eb - ea)

    def ci(v):
        return [round(float(np.percentile(v, q)), 4) for q in (2.5, 97.5)]

    return {"sin_calibrar": ci(a), "calibrado": ci(b), "diferencia": ci(d)}


def load(name: str, kind: str) -> pl.DataFrame:
    return pl.read_parquet(PREDS / f"{name}__{kind}.parquet")


def proba_for(
    name: str, frame: pl.DataFrame, key: str, kind: str
) -> np.ndarray:
    joined = frame.select(key).join(load(name, kind), on=key, how="left")
    if joined["p_NEG"].null_count():
        raise ValueError(f"{name}: faltan predicciones de {kind}")
    return joined.select("p_NEG", "p_NEU", "p_POS").to_numpy()


def main() -> None:
    dev_all = gold().filter(
        (pl.col("particion") == "dev") & (pl.col("oro") != "NA")
    )
    dev = dev_all.filter(pl.col("bloque_oro") == "aleatorio").sort("item_id")
    directed = dev_all.filter(pl.col("bloque_oro") == "dirigido").sort(
        "item_id"
    )
    hold = holdout_rows(silver_rows()).sort("id_resena")
    y, w = dev["oro"].to_numpy(), dev["peso"].to_numpy()
    strata = dev["estrato"].to_numpy()
    y_idx = np.array([CLASSES.index(v) for v in y])
    y_dir = directed["oro"].to_numpy()
    w_dir = np.ones(directed.height)
    y_hold, w_hold = hold["plata"].to_numpy(), hold["peso"].to_numpy()

    results: dict = {}
    oof_for_plot: dict[str, np.ndarray] = {}
    for name in MODELS:
        print(f"calibrando {name}", flush=True)

        raw = proba_for(name, dev, "item_id", "dev")
        raw_dir = proba_for(name, directed, "item_id", "dev")
        raw_hold = proba_for(name, hold, "text_id", "holdout")
        z, z_dir, z_hold = logits(raw), logits(raw_dir), logits(raw_hold)

        entry: dict = {"sin_calibrar": summary(y, raw, w)}
        entry["sin_calibrar"]["fiabilidad"] = reliability(y, raw, w)
        for kind in ("temperature", "vector"):
            oof = out_of_fold(z, y, w, kind)
            params = fit(z, y_idx, w, kind)
            block = {
                "temperatura": round(float(np.exp(params[0])), 4),
                "sesgos": (
                    dict(
                        zip(
                            CLASSES,
                            [0.0, *(round(float(b), 4) for b in params[1:])],
                            strict=True,
                        )
                    )
                    if kind == "vector"
                    else None
                ),
                "dev_fuera_de_particion": summary(y, oof, w),
                "dev_dirigido": summary(y_dir, apply(z_dir, params), w_dir),
                "holdout_contra_plata": summary(
                    y_hold, apply(z_hold, params), w_hold
                ),
            }
            if kind == "temperature":
                block["ic_ece"] = paired_ci(y, raw, oof, w, strata)
                block["dev_fuera_de_particion"]["fiabilidad"] = reliability(
                    y, oof, w
                )
                oof_for_plot[name] = oof
            entry[kind] = block
        entry["dev_dirigido_sin_calibrar"] = summary(y_dir, raw_dir, w_dir)
        entry["holdout_sin_calibrar"] = summary(y_hold, raw_hold, w_hold)
        results[name] = entry

    FIGURES.mkdir(parents=True, exist_ok=True)
    plot_name = "M4_robertuito_s1"
    raw = proba_for(plot_name, dev, "item_id", "dev")
    oof = oof_for_plot[plot_name]
    fig, ax = plt.subplots(figsize=(4.5, 4.5))
    ax.plot([0, 1], [0, 1], color="#999999", lw=1, ls="--")
    for label, proba, color in (
        ("sin calibrar", raw, "#7A1A37"),
        ("temperatura (fuera de partición)", oof, "#002D72"),
    ):
        rel = reliability(y, proba, w)
        ax.plot(
            [r["confianza"] for r in rel],
            [r["acierto"] for r in rel],
            marker="o",
            color=color,
            label=label,
        )
    ax.set_xlabel("Confianza (probabilidad máxima)")
    ax.set_ylabel("Acierto ponderado")
    ax.set_title(f"{plot_name}, dev aleatorio (n = {len(y)})")
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "reliability_m4_robertuito_s1.png", dpi=150)

    OUT.write_text(
        json.dumps(
            {
                "generado": datetime.now(UTC).isoformat(timespec="seconds"),
                "n_dev_aleatorio": int(dev.height),
                "n_dev_dirigido": int(directed.height),
                "n_holdout_filas": int(hold.height),
                "particiones": FOLDS,
                "bootstrap": BOOTSTRAP,
                "modelos": results,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(f"escrito {OUT}", flush=True)


if __name__ == "__main__":
    main()
