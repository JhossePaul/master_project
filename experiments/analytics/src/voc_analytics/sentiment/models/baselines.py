"""Líneas base M0 y M1 de la competencia de sentimiento (EPIC-5, feature 5.4).

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.sentiment.models.baselines

* **M0:** estrellas → polaridad (1–2 `NEG`, 3 `NEU`, 4–5 `POS`). Sin
  entrenamiento.
* **M1:** TF-IDF + regresión logística sobre `texto_sanitizado`, entrenada con
  la plata (`prompt_v3`), un ejemplo por texto único.
  * Hiperparámetros elegidos por validación cruzada de 5 particiones sobre la
    plata de entrenamiento: agrupada por `clave` (las variantes de un mismo
    texto no cruzan particiones) y estratificada por banco × periodo × clase.
  * La configuración final se fija antes de mirar el oro. Las variantes de
    ponderación (filas, peso de diseño) son ablaciones: se reportan, no se
    eligen con el oro *dev*.
  * Ablación de limpieza: el mismo M1 sobre `texto_limpio`
    (`limpiar_texto_bancario`, la entrada del EDA preliminar).
* Solo predice el oro *dev* y los textos de `holdout_nuevo`; las métricas las
  calcula `evaluate.py`. El oro *test* no se toca.

Escribe, fuera de git, las predicciones en `data/models/preds/`, el resultado
de la validación cruzada en `data/models/m1_cv.json` (se reutiliza si existe)
y el modelo M1 en `data/models/m1_tfidf_lr.pkl`.
"""

import itertools
import json
import pickle
import time

import numpy as np
import polars as pl
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold

from voc_analytics.paths import MODELS
from voc_analytics.sentiment.data import (
    gold,
    holdout_rows,
    holdout_texts,
    save_predictions,
    silver_rows,
    training_texts,
)
from voc_analytics.sentiment.metrics import quality

CV_CACHE = MODELS / "m1_cv.json"
SEED = 20261019
FOLDS = 5
GRID = {
    "features": ["word12", "word12_char25"],
    "C": [1.0, 4.0, 16.0, 64.0],
    "class_weight": [None, "balanced"],
}


class TfidfLR:
    """TF-IDF de palabras (1–2) y, opcionalmente, caracteres (2–5) + LR."""

    def __init__(self, features: str, C: float, class_weight: str | None):
        self.params = {
            "features": features,
            "C": C,
            "class_weight": class_weight,
        }
        self.vecs = [
            TfidfVectorizer(
                lowercase=True,
                ngram_range=(1, 2),
                min_df=2,
                sublinear_tf=True,
                strip_accents=None,
            )
        ]
        if features == "word12_char25":
            self.vecs.append(
                TfidfVectorizer(
                    lowercase=True,
                    analyzer="char_wb",
                    ngram_range=(2, 5),
                    min_df=3,
                    sublinear_tf=True,
                    max_features=300_000,
                )
            )
        self.clf = LogisticRegression(
            C=C,
            class_weight=class_weight,
            max_iter=2000,
            solver="lbfgs",
        )

    def _x(self, texts, fit=False):
        mats = [
            v.fit_transform(texts) if fit else v.transform(texts)
            for v in self.vecs
        ]
        return hstack(mats).tocsr()

    def fit(self, texts, y, w=None):
        self.clf.fit(self._x(texts, fit=True), y, sample_weight=w)
        return self

    def predict_proba(self, texts) -> np.ndarray:
        return self.clf.predict_proba(self._x(texts))

    def predict(self, texts) -> np.ndarray:
        return self.clf.classes_[self.predict_proba(texts).argmax(axis=1)]


def cross_validate(train: pl.DataFrame) -> list[dict]:
    # La caché guarda cada configuración ya evaluada; solo se calculan las
    # que faltan (por ejemplo, al ampliar la cuadrícula).
    results = json.loads(CV_CACHE.read_text()) if CV_CACHE.exists() else []
    done = {(r["features"], r["C"], r["class_weight"]) for r in results}
    todo = [
        (f, C, cw)
        for f in GRID["features"]
        for C, cw in itertools.product(GRID["C"], GRID["class_weight"])
        if (f, C, cw) not in done
    ]
    if not todo:
        return results
    texts = train["texto_sanitizado"].to_numpy()
    y = train["plata"].to_numpy()
    strata = (
        train["bank_id"] + "|" + train["periodo"] + "|" + train["plata"]
    ).to_numpy()
    folds = list(
        StratifiedGroupKFold(
            n_splits=FOLDS, shuffle=True, random_state=SEED
        ).split(texts, strata, groups=train["clave"].to_numpy())
    )
    for features in sorted({f for f, _, _ in todo}):
        # Los vectorizadores se ajustan dentro de cada partición.
        mats = []
        for tr, te in folds:
            base = TfidfLR(features, 1.0, None)
            mats.append((base._x(texts[tr], fit=True), base._x(texts[te])))
        for _, C, cw in (t for t in todo if t[0] == features):
            scores = []
            for (tr, te), (xtr, xte) in zip(folds, mats, strict=True):
                clf = LogisticRegression(C=C, class_weight=cw, max_iter=2000)
                clf.fit(xtr, y[tr])
                scores.append(quality(y[te], clf.predict(xte))["macro_f1"])
            results.append(
                {
                    "features": features,
                    "C": C,
                    "class_weight": cw,
                    "macro_f1_media": round(float(np.mean(scores)), 4),
                    "macro_f1_de": round(float(np.std(scores)), 4),
                }
            )
            print(results[-1], flush=True)
    MODELS.mkdir(parents=True, exist_ok=True)
    CV_CACHE.write_text(json.dumps(results, indent=2) + "\n")
    return results


def throughput(predict, texts: np.ndarray) -> dict:
    start = time.perf_counter()
    predict(texts)
    secs = time.perf_counter() - start
    return {
        "textos": len(texts),
        "segundos": round(secs, 2),
        "textos_por_segundo": round(len(texts) / secs),
    }


def frame(
    keys: pl.DataFrame,
    pred: np.ndarray,
    proba: np.ndarray | None = None,
    classes=None,
) -> pl.DataFrame:
    out = keys.with_columns(pred=pl.Series(pred, dtype=pl.String))
    if proba is not None:
        out = out.with_columns(
            pl.Series(f"p_{c}", proba[:, i]) for i, c in enumerate(classes)
        )
    return out


def main() -> None:
    rows = silver_rows()
    train = training_texts(rows)
    hold = holdout_texts(holdout_rows(rows))
    dev = gold().filter(
        (pl.col("particion") == "dev") & (pl.col("oro") != "NA")
    )
    print(
        f"entrenamiento {train.height} textos, holdout {hold.height} "
        f"textos, dev {dev.height}",
        flush=True,
    )

    # M0: no necesita texto; en holdout se asigna por fila en evaluate.py.
    save_predictions(
        "M0",
        frame(dev.select("item_id"), dev["estrellas_clase"].to_numpy()),
        pl.DataFrame(schema={"text_id": pl.UInt32, "pred": pl.String}),
        {
            "modelo": "M0",
            "descripcion": "estrellas 1-2 NEG, 3 NEU, 4-5 POS",
            "por_fila": True,
        },
    )

    cv = cross_validate(train)
    best = max(cv, key=lambda r: r["macro_f1_media"])
    params = {k: best[k] for k in ("features", "C", "class_weight")}
    print("elegido", params, flush=True)

    y = train["plata"].to_numpy()
    variants = {
        "M1": ("texto_sanitizado", None),
        "M1_peso_filas": (
            "texto_sanitizado",
            train["filas"].cast(pl.Float64).to_numpy(),
        ),
        "M1_peso_diseno": ("texto_sanitizado", train["peso_diseno"].to_numpy()),
        "M1_texto_limpio": ("texto_limpio", None),
    }
    for name, (field, w) in variants.items():
        if w is not None:
            w = w / w.mean()
        start = time.perf_counter()
        model = TfidfLR(**params).fit(train[field].to_numpy(), y, w)
        fit_secs = round(time.perf_counter() - start, 1)
        classes = list(model.clf.classes_)
        p_dev = model.predict_proba(dev[field].to_numpy())
        p_hold = model.predict_proba(hold[field].to_numpy())
        meta = {
            "modelo": name,
            "entrada": field,
            "params": params,
            "ponderacion": None if w is None else name.removeprefix("M1_"),
            "textos_entrenamiento": train.height,
            "segundos_ajuste": fit_secs,
            "equipo": "Mac M2 8 GB, CPU, un proceso",
        }
        if name == "M1":
            MODELS.mkdir(parents=True, exist_ok=True)
            artifact = MODELS / "m1_tfidf_lr.pkl"
            artifact.write_bytes(pickle.dumps(model))
            meta["artefacto_mb"] = round(artifact.stat().st_size / 2**20, 1)
            meta["inferencia"] = throughput(
                model.predict_proba,
                rows["texto_sanitizado"].unique().to_numpy(),
            )
            meta["validacion_cruzada"] = {"particiones": FOLDS, "grid": cv}
        save_predictions(
            name,
            frame(
                dev.select("item_id"),
                np.asarray(classes)[p_dev.argmax(axis=1)],
                p_dev,
                classes,
            ),
            frame(
                hold.select("text_id"),
                np.asarray(classes)[p_hold.argmax(axis=1)],
                p_hold,
                classes,
            ),
            meta,
        )
        print(name, fit_secs, "s", flush=True)


if __name__ == "__main__":
    main()
