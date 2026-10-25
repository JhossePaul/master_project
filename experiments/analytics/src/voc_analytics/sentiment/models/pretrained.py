"""M2 (encoders sin ajuste) y el léxico del EDA preliminar (EPIC-5, 5.4).

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.sentiment.models.pretrained [modelo ...]

* **M2_robertuito:** `pysentimiento/robertuito-sentiment-analysis`, el
  analizador por defecto de `pysentimiento` en español (Pérez et al., 2022).
* **M2_beto:** `finiteautomata/beto-sentiment-analysis`, BETO ajustado por el
  mismo grupo con TASS 2020.
* BERTweet (`finiteautomata/bertweet-base-sentiment-analysis`) es el
  analizador **en inglés** de `pysentimiento` y no se evalúa sobre español.
* **T0_textblob:** la referencia del EDA preliminar
  (`experiments/project_viability/`), con la misma receta: polaridad de
  `TextBlob` sobre el texto sin limpiar, `< -0.1` → `NEG`, `> 0.1` → `POS`.
  Su léxico es en inglés; se mide por continuidad.
* **Ablación de limpieza:** cada encoder corre sobre `texto_sanitizado` y
  sobre `texto_limpio`. El EDA preliminar usaba `texto_limpio` (y `NEU` si la
  predicción fallaba; aquí no falla ninguna).

Las tres clases de `pysentimiento` vienen de TASS (tuits) y no siguen la guía
v2: una mezcla de elogio y queja suele salir `NEU`, no `NEG`. Ese desajuste es
parte de lo que mide M2.

Solo predice el oro *dev* y los textos de `holdout_nuevo`, en el Mac (MPS si
está disponible). Escribe en `data/models/preds/`.
"""

import sys
import time

import numpy as np
import polars as pl
import torch

from voc_analytics.sentiment.data import (
    CLASSES,
    gold,
    holdout_rows,
    holdout_texts,
    save_predictions,
    silver_rows,
)

ENCODERS = {
    "M2_robertuito": "pysentimiento/robertuito-sentiment-analysis",
    "M2_beto": "finiteautomata/beto-sentiment-analysis",
}
FIELDS = {"": "texto_sanitizado", "_texto_limpio": "texto_limpio"}
BATCH = 64


def by_length(texts: list[str], predict) -> list:
    """Predice por orden de longitud (menos relleno); respeta el orden."""
    order = np.argsort([len(t) for t in texts])
    out = predict([texts[i] for i in order])
    result = [None] * len(texts)
    for pos, i in enumerate(order):
        result[i] = out[pos]
    return result


def run_encoder(
    name: str, model_name: str, dev: pl.DataFrame, hold: pl.DataFrame
) -> None:
    from pysentimiento import create_analyzer

    analyzer = create_analyzer(
        task="sentiment", lang="es", model_name=model_name, batch_size=BATCH
    )
    device = str(next(analyzer.model.parameters()).device)
    for suffix, field in FIELDS.items():
        frames, speed = {}, None
        for label, df, key in (
            ("dev", dev, "item_id"),
            ("holdout", hold, "text_id"),
        ):
            texts = df[field].to_list()
            start = time.perf_counter()
            outs = by_length(texts, analyzer.predict)
            secs = time.perf_counter() - start
            if label == "holdout":
                speed = {
                    "textos": len(texts),
                    "segundos": round(secs, 1),
                    "textos_por_segundo": round(len(texts) / secs, 1),
                }
            frames[label] = df.select(key).with_columns(
                pred=pl.Series([o.output for o in outs], dtype=pl.String),
                **{
                    f"p_{c}": pl.Series([o.probas[c] for o in outs])
                    for c in CLASSES
                },
            )
        save_predictions(
            name + suffix,
            frames["dev"],
            frames["holdout"],
            {
                "modelo": name + suffix,
                "checkpoint": model_name,
                "entrada": field,
                "dispositivo": device,
                "batch": BATCH,
                "equipo": "Mac M2 8 GB",
                "parametros_millones": round(
                    sum(p.numel() for p in analyzer.model.parameters()) / 1e6, 1
                ),
                "inferencia": speed,
            },
        )
        print(name + suffix, speed, flush=True)
    del analyzer
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()


def textblob_label(text: str) -> str:
    from textblob import TextBlob

    score = TextBlob(text).sentiment.polarity
    return "NEG" if score < -0.1 else "POS" if score > 0.1 else "NEU"


def run_textblob(dev: pl.DataFrame, hold: pl.DataFrame) -> None:
    frames, speed = {}, None
    for label, df, key in (
        ("dev", dev, "item_id"),
        ("holdout", hold, "text_id"),
    ):
        start = time.perf_counter()
        preds = [textblob_label(t) for t in df["texto_sanitizado"].to_list()]
        secs = time.perf_counter() - start
        if label == "holdout":
            speed = {
                "textos": df.height,
                "segundos": round(secs, 1),
                "textos_por_segundo": round(df.height / secs),
            }
        frames[label] = df.select(key).with_columns(
            pred=pl.Series(preds, dtype=pl.String)
        )
    save_predictions(
        "T0_textblob",
        frames["dev"],
        frames["holdout"],
        {
            "modelo": "T0_textblob",
            "entrada": "texto_sanitizado",
            "umbral": 0.1,
            "origen": "EDA preliminar (project_viability)",
            "equipo": "Mac M2 8 GB, CPU",
            "inferencia": speed,
        },
    )
    print("T0_textblob", speed, flush=True)


def main(selected: list[str]) -> None:
    rows = silver_rows()
    hold = holdout_texts(holdout_rows(rows))
    dev = gold().filter(
        (pl.col("particion") == "dev") & (pl.col("oro") != "NA")
    )
    for name, model_name in ENCODERS.items():
        if not selected or name in selected:
            run_encoder(name, model_name, dev, hold)
    if not selected or "T0_textblob" in selected:
        run_textblob(dev, hold)


if __name__ == "__main__":
    main(sys.argv[1:])
