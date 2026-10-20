"""Escalera de ruido con TF-IDF: M3, M6 y M7 (EPIC-5, feature 5.4).

Uso (desde experiments/analytics), después de `baselines.py`:
    uv run python -m voc_analytics.sentiment.models.noisy

Los tres modelos aprenden de las **estrellas**, no de la plata, con la misma
representación y los mismos hiperparámetros que M1 (elegidos por validación
cruzada sobre la plata, en `data/models/m1_cv.json`). Así la diferencia con
M1 mide el efecto de la etiqueta, no el del modelo. Se entrena sobre pares
(texto único, estrellas), ponderados por sus filas: equivale a entrenar por
reseña, como lo haría un sistema que solo tiene estrellas.

* **M3:** etiqueta ingenua (1–2 `NEG`, 3 `NEU`, 4–5 `POS`). Aprende el ruido.
* **M6:** corrección *forward* (Patrini et al., 2017) con una matriz de
  transición T de 3 × 5: P(estrellas = k | sentimiento = c). El modelo
  predice el sentimiento; la pérdida se calcula sobre P(estrellas | x) =
  P(sentimiento | x) · T. T se estima con la plata en las mismas filas de
  entrenamiento (15 números agregados; ninguna etiqueta individual de la
  plata entra al ajuste). Usar las 5 estrellas conserva la información del
  3★, que es mayoritariamente `NEG`.
* **M7:** *Confident Learning* (Northcutt et al., 2021, `cleanlab`).
  Probabilidades fuera de partición (5 particiones agrupadas por `clave`),
  se quitan los pares marcados como ruidosos y se reentrena (poda).

Solo predice el oro *dev* y `holdout_nuevo`. Escribe en `data/models/preds/`.
"""

import json
import time

import numpy as np
import polars as pl
import torch
from sklearn.model_selection import StratifiedGroupKFold

from voc_analytics.sentiment.data import (
    CLASSES,
    gold,
    holdout_rows,
    holdout_texts,
    save_predictions,
    silver_rows,
    training_star_pairs,
)
from voc_analytics.sentiment.models.baselines import (
    CV_CACHE,
    FOLDS,
    SEED,
    TfidfLR,
    frame,
)

STARS = [1, 2, 3, 4, 5]


def m1_params() -> dict:
    cv = json.loads(CV_CACHE.read_text())
    best = max(cv, key=lambda r: r["macro_f1_media"])
    return {k: best[k] for k in ("features", "C", "class_weight")}


def transition(pairs: pl.DataFrame) -> np.ndarray:
    """T[c, k] = P(estrellas = k | plata = c), por fila de entrenamiento."""
    counts = (
        pairs.group_by("plata", "estrellas")
        .agg(pl.col("filas").sum())
        .pivot(on="estrellas", index="plata", values="filas")
        .fill_null(0)
    )
    t = np.array(
        [
            [counts.filter(pl.col("plata") == c)[str(k)].item() for k in STARS]
            for c in CLASSES
        ],
        dtype=float,
    )
    return t / t.sum(axis=1, keepdims=True)


class ForwardLR:
    """Regresión logística multinomial con pérdida *forward* (torch, CPU).

    Minimiza Σ w·(−log (softmax(XW + b) · T)[estrellas]) / n + ‖W‖² / (2 C n),
    el mismo objetivo regularizado que `LogisticRegression` con T = I.
    """

    def __init__(self, base: TfidfLR, t: np.ndarray, C: float):
        self.base, self.C = base, C
        self.t = torch.tensor(t, dtype=torch.float32)

    @staticmethod
    def _sparse(x) -> torch.Tensor:
        x = x.tocsr().astype(np.float32)
        return torch.sparse_csr_tensor(
            torch.from_numpy(x.indptr).long(),
            torch.from_numpy(x.indices).long(),
            torch.from_numpy(x.data),
            size=x.shape,
        )

    def fit(self, texts, noisy: np.ndarray, w: np.ndarray):
        x = self._sparse(self.base._x(texts, fit=True))
        n, d = x.shape
        y = torch.from_numpy(noisy).long()
        wt = torch.from_numpy(w / w.mean())
        self.W = torch.zeros(
            d, len(CLASSES), dtype=torch.float32, requires_grad=True
        )
        self.b = torch.zeros(
            len(CLASSES), dtype=torch.float32, requires_grad=True
        )
        opt = torch.optim.LBFGS(
            [self.W, self.b],
            max_iter=500,
            line_search_fn="strong_wolfe",
            tolerance_grad=1e-6,
            tolerance_change=1e-9,
            history_size=20,
        )

        calls = [0]

        def closure():
            calls[0] += 1
            opt.zero_grad()
            p = torch.softmax(torch.sparse.mm(x, self.W) + self.b, dim=1)
            noisy_p = (p @ self.t).clamp_min(1e-12)
            nll = -(wt * noisy_p.log()[torch.arange(n), y]).sum() / n
            loss = nll + (self.W**2).sum() / (2 * self.C * n)
            loss.backward()
            if calls[0] % 25 == 1:
                print(
                    f"  M6 evaluación {calls[0]} pérdida {loss.item():.5f}",
                    flush=True,
                )
            return loss

        opt.step(closure)
        return self

    def predict_proba(self, texts) -> np.ndarray:
        x = self._sparse(self.base._x(texts))
        with torch.no_grad():
            p = torch.softmax(torch.sparse.mm(x, self.W) + self.b, dim=1)
        return p.numpy()


def out_of_fold(pairs: pl.DataFrame, params: dict) -> np.ndarray:
    """Probabilidades fuera de partición contra la etiqueta de estrellas."""
    texts = pairs["texto_sanitizado"].to_numpy()
    y = pairs["estrellas_clase"].to_numpy()
    w = pairs["filas"].cast(pl.Float64).to_numpy()
    strata = (pairs["bank_id"] + "|" + pairs["estrellas_clase"]).to_numpy()
    proba = np.zeros((len(texts), len(CLASSES)))
    folds = StratifiedGroupKFold(
        n_splits=FOLDS, shuffle=True, random_state=SEED
    )
    for tr, te in folds.split(texts, strata, groups=pairs["clave"].to_numpy()):
        model = TfidfLR(**params).fit(texts[tr], y[tr], w[tr] / w[tr].mean())
        order = [list(model.clf.classes_).index(c) for c in CLASSES]
        proba[te] = model.predict_proba(texts[te])[:, order]
    return proba


def predict_and_save(name, model, dev, hold, meta) -> None:
    p_dev = model.predict_proba(dev["texto_sanitizado"].to_numpy())
    p_hold = model.predict_proba(hold["texto_sanitizado"].to_numpy())
    classes = (
        list(model.clf.classes_) if isinstance(model, TfidfLR) else CLASSES
    )
    save_predictions(
        name,
        frame(
            dev.select("item_id"),
            np.asarray(classes)[p_dev.argmax(1)],
            p_dev,
            classes,
        ),
        frame(
            hold.select("text_id"),
            np.asarray(classes)[p_hold.argmax(1)],
            p_hold,
            classes,
        ),
        meta | {"equipo": "Mac M2 8 GB, CPU"},
    )


def main() -> None:
    from cleanlab.filter import find_label_issues

    rows = silver_rows()
    pairs = training_star_pairs(rows)
    hold = holdout_texts(holdout_rows(rows))
    dev = gold().filter(
        (pl.col("particion") == "dev") & (pl.col("oro") != "NA")
    )
    params = m1_params()
    texts = pairs["texto_sanitizado"].to_numpy()
    y3 = pairs["estrellas_clase"].to_numpy()
    w = pairs["filas"].cast(pl.Float64).to_numpy()
    base_meta = {
        "params": params,
        "pares_entrenamiento": pairs.height,
        "filas_entrenamiento": int(w.sum()),
        "etiqueta": "estrellas",
    }
    print(f"{pairs.height} pares, params {params}", flush=True)

    start = time.perf_counter()
    m3 = TfidfLR(**params).fit(texts, y3, w / w.mean())
    predict_and_save(
        "M3",
        m3,
        dev,
        hold,
        base_meta
        | {
            "modelo": "M3",
            "segundos_ajuste": round(time.perf_counter() - start, 1),
        },
    )
    print("M3 listo", flush=True)

    t = transition(pairs)
    stars = pairs["estrellas"].to_numpy() - 1
    start = time.perf_counter()
    m6 = ForwardLR(TfidfLR(**params), t, params["C"]).fit(texts, stars, w)
    predict_and_save(
        "M6",
        m6,
        dev,
        hold,
        base_meta
        | {
            "modelo": "M6",
            "matriz_T": {
                c: dict(
                    zip(
                        map(str, STARS),
                        map(lambda v: round(v, 4), row),
                        strict=True,
                    )
                )
                for c, row in zip(CLASSES, t, strict=True)
            },
            "segundos_ajuste": round(time.perf_counter() - start, 1),
        },
    )
    print("M6 listo", flush=True)

    start = time.perf_counter()
    proba = out_of_fold(pairs, params)
    labels = np.array([CLASSES.index(c) for c in y3])
    issues = find_label_issues(labels, proba, filter_by="prune_by_noise_rate")
    keep = ~issues
    m7 = TfidfLR(**params).fit(texts[keep], y3[keep], w[keep] / w[keep].mean())
    flagged = pairs.filter(pl.Series(issues))
    predict_and_save(
        "M7",
        m7,
        dev,
        hold,
        base_meta
        | {
            "modelo": "M7",
            "pares_marcados": int(issues.sum()),
            "filas_marcadas": int(flagged["filas"].sum()),
            # Diagnóstico: qué dice la plata de los pares que cleanlab quita.
            "marcados_estrellas_vs_plata": {
                f"{a}->{b}": n
                for a, b, n in flagged.group_by("estrellas_clase", "plata")
                .agg(pl.col("filas").sum())
                .sort("estrellas_clase", "plata")
                .iter_rows()
            },
            "segundos_ajuste": round(time.perf_counter() - start, 1),
        },
    )
    print("M7 listo", int(issues.sum()), "pares marcados", flush=True)


if __name__ == "__main__":
    main()
