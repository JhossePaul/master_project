"""Métricas comunes de la competencia de sentimiento (EPIC-5, feature 5.4).

* **Calidad:** macro-F1 sobre `NEG`/`NEU`/`POS`, κ de Cohen, exactitud, y
  precisión y recall de `NEG`.
  * Sin ponderar: la muestra tal cual, comparable con los κ de 5.3.
  * Ponderadas por 1 / probabilidad de inclusión: estimación poblacional.
* **Intervalos:** bootstrap estratificado (remuestreo dentro de cada estrato
  del diseño), percentiles 2.5 y 97.5. Las diferencias entre modelos se
  remuestrean pareadas, sobre los mismos índices.
* **Calibración:** ECE de la probabilidad máxima con 10 bins de igual ancho.
"""

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    cohen_kappa_score,
    f1_score,
    precision_recall_fscore_support,
)

from voc_analytics.sentiment.data import CLASSES

BOOTSTRAP = 2000
SEED = 20261019


def quality(y: np.ndarray, p: np.ndarray, w: np.ndarray | None = None) -> dict:
    prec, rec, f1, _ = precision_recall_fscore_support(
        y, p, labels=CLASSES, sample_weight=w, zero_division=0
    )
    return {
        "macro_f1": float(
            f1_score(
                y,
                p,
                labels=CLASSES,
                average="macro",
                sample_weight=w,
                zero_division=0,
            )
        ),
        "kappa": float(
            cohen_kappa_score(y, p, labels=CLASSES, sample_weight=w)
        ),
        "exactitud": float(accuracy_score(y, p, sample_weight=w)),
        "neg_precision": float(prec[0]),
        "neg_recall": float(rec[0]),
        "f1_por_clase": dict(zip(CLASSES, map(float, f1), strict=True)),
    }


def _round(d: dict) -> dict:
    return {
        k: _round(v) if isinstance(v, dict) else round(v, 4)
        for k, v in d.items()
    }


def _ci(values: list[float]) -> list[float]:
    return [
        round(float(np.percentile(values, 2.5)), 4),
        round(float(np.percentile(values, 97.5)), 4),
    ]


def _resample(strata: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    idx = []
    for s in np.unique(strata):
        members = np.flatnonzero(strata == s)
        idx.append(rng.choice(members, size=members.size, replace=True))
    return np.concatenate(idx)


SCALARS = ["macro_f1", "kappa", "exactitud", "neg_precision", "neg_recall"]


def evaluate(
    y: np.ndarray,
    preds: dict[str, np.ndarray],
    strata: np.ndarray,
    w: np.ndarray,
    reference: str | list[str] | None = None,
    n_boot: int = BOOTSTRAP,
) -> dict:
    """Puntos e IC 95 % por modelo; diferencias pareadas contra `reference`."""
    refs = [reference] if isinstance(reference, str) else list(reference or [])
    rng = np.random.default_rng(SEED)
    boots = {
        (m, kind, s): []
        for m in preds
        for kind in ("muestra", "poblacion")
        for s in SCALARS
    }
    diffs = {
        (m, r, kind, s): []
        for r in refs
        for m in preds
        if m != r
        for kind in ("muestra", "poblacion")
        for s in ("macro_f1", "kappa")
    }
    for _ in range(n_boot):
        idx = _resample(strata, rng)
        stats = {
            (m, kind): quality(
                y[idx], p[idx], None if kind == "muestra" else w[idx]
            )
            for m, p in preds.items()
            for kind in ("muestra", "poblacion")
        }
        for (m, kind, s), acc in boots.items():
            acc.append(stats[m, kind][s])
        for (m, r, kind, s), acc in diffs.items():
            acc.append(stats[m, kind][s] - stats[r, kind][s])
    out = {}
    for m, p in preds.items():
        out[m] = {}
        for kind, weights in (("muestra", None), ("poblacion", w)):
            point = quality(y, p, weights)
            out[m][kind] = _round(point) | {
                f"{s}_ic95": _ci(boots[m, kind, s]) for s in SCALARS
            }
    for m in preds:
        for r in refs:
            if m == r:
                continue
            out[m][f"menos_{r}"] = {
                kind: {
                    s: {
                        "diferencia": round(
                            out[m][kind][s] - out[r][kind][s], 4
                        ),
                        "ic95": _ci(diffs[m, r, kind, s]),
                    }
                    for s in ("macro_f1", "kappa")
                }
                for kind in ("muestra", "poblacion")
            }
    return out


def ece(
    y: np.ndarray,
    proba: np.ndarray,
    classes: list[str],
    w: np.ndarray | None = None,
    bins: int = 10,
) -> float:
    w = np.ones(len(y)) if w is None else w
    conf = proba.max(axis=1)
    hit = (np.asarray(classes)[proba.argmax(axis=1)] == y).astype(float)
    edges = np.linspace(0, 1, bins + 1)
    total, err = w.sum(), 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            err += (
                w[m].sum()
                / total
                * abs(
                    np.average(hit[m], weights=w[m])
                    - np.average(conf[m], weights=w[m])
                )
            )
    return round(float(err), 4)
