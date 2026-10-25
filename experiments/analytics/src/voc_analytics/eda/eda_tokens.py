"""Longitud en tokens con los tokenizadores de 5.4 (EPIC-5 feature 5.2).

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.eda.eda_tokens data/tds_<SNAPSHOT>.parquet

Mide cada texto único de `texto_sanitizado` (el campo que usan los modelos)
con el mismo preprocesamiento que `sentiment.encoder.encode`
(`preprocess_tweet`), sin truncar, y pondera por filas. Escribe solo
agregados en `docs/analytics/eda/tokens_metrics.json` y una figura en
`docs/analytics/eda/figures/tokens_ccdf.png`.
"""

import json
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import polars as pl  # noqa: E402

from voc_analytics.paths import DOCS  # noqa: E402
from voc_analytics.sampling.strata import period  # noqa: E402

OUT = DOCS / "eda"
FIG = OUT / "figures"
# Mismos checkpoints que `sentiment.encoder.ENCODERS`.
TOKENIZERS = {
    "robertuito": "pysentimiento/robertuito-sentiment-analysis",
    "beto": "finiteautomata/beto-sentiment-analysis",
}
TRAIN_MAX_LENGTH = 128  # `sentiment.encoder.MAX_LENGTH`
CUTS = [32, 64, 128, 256, 512]
QUANTILES = [0.5, 0.9, 0.95, 0.99, 0.999]
BATCH = 20_000
COLORS = {"robertuito": "#2a78d6", "beto": "#eb6834"}


def count_tokens(name: str, texts: list[str]) -> np.ndarray:
    from pysentimiento.preprocessing import preprocess_tweet
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(name)
    out = np.empty(len(texts), dtype=np.int32)
    for i in range(0, len(texts), BATCH):
        chunk = [preprocess_tweet(t) for t in texts[i : i + BATCH]]
        ids = tok(chunk, truncation=False, add_special_tokens=True)["input_ids"]
        out[i : i + BATCH] = [len(x) for x in ids]
    return out


def summary(df: pl.DataFrame, col: str) -> dict:
    """Cuantiles y colas ponderados por filas (`filas` = repeticiones)."""
    order = df.sort(col)
    cum = order["filas"].cum_sum() / order["filas"].sum()
    values = order[col].to_numpy()
    q = {
        f"p{str(p * 100).rstrip('0').rstrip('.')}": int(
            values[np.searchsorted(cum.to_numpy(), p)]
        )
        for p in QUANTILES
    }
    total = df["filas"].sum()
    over = {
        f"filas_mas_de_{c}": round(
            df.filter(pl.col(col) > c)["filas"].sum() / total, 5
        )
        for c in CUTS
    }
    return {"filas": int(total), **q, "max": int(values[-1]), **over}


def main(path: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    rows = pl.read_parquet(
        path, columns=["bank_id", "fecha", "texto_sanitizado"]
    ).with_columns(
        texto=pl.col("texto_sanitizado").fill_null(""), periodo=period()
    )
    unique = rows.select("texto").unique(maintain_order=True)
    texts = unique["texto"].to_list()
    metrics: dict = {
        "snapshot_file": Path(path).name,
        "rows": rows.height,
        "unique_texts": len(texts),
        "campo": "texto_sanitizado",
        "preprocesamiento": "pysentimiento.preprocess_tweet, sin truncar",
        "max_length_entrenamiento": TRAIN_MAX_LENGTH,
        "tokenizers": TOKENIZERS,
    }

    for key, name in TOKENIZERS.items():
        start = time.time()
        unique = unique.with_columns(pl.Series(key, count_tokens(name, texts)))
        metrics.setdefault("seconds", {})[key] = round(time.time() - start, 1)
        print(f"{key}: {metrics['seconds'][key]} s", flush=True)

    df = rows.join(unique, on="texto", how="left")
    by_text = unique.join(
        rows.group_by("texto").len().rename({"len": "filas"}), on="texto"
    )
    metrics["por_texto_unico"] = {
        k: summary(by_text.with_columns(filas=pl.lit(1)), k) for k in TOKENIZERS
    }
    metrics["por_fila"] = {k: summary(by_text, k) for k in TOKENIZERS}
    metrics["por_banco_periodo"] = {
        k: [
            {
                "bank_id": b,
                "periodo": p,
                **summary(g.with_columns(filas=pl.lit(1)), k),
            }
            for (b, p), g in df.group_by("bank_id", "periodo")
        ]
        for k in TOKENIZERS
    }
    for k in TOKENIZERS:
        metrics["por_banco_periodo"][k].sort(
            key=lambda r: (r["bank_id"], r["periodo"])
        )
    # Tokens por palabra (palabras = tokens separados por espacios).
    words = by_text.with_columns(
        palabras=pl.col("texto").str.count_matches(r"\S+")
    )
    words = words.filter(pl.col("palabras") > 0)
    metrics["tokens_por_palabra"] = {
        k: round(
            float(
                (words[k] * words["filas"]).sum()
                / (words["palabras"] * words["filas"]).sum()
            ),
            3,
        )
        for k in TOKENIZERS
    }
    metrics["truncadas_entrenamiento"] = {
        k: {
            "textos_unicos": int((by_text[k] > TRAIN_MAX_LENGTH).sum()),
            "filas": int(
                by_text.filter(pl.col(k) > TRAIN_MAX_LENGTH)["filas"].sum()
            ),
        }
        for k in TOKENIZERS
    }

    fig, ax = plt.subplots(figsize=(7, 4))
    for k in TOKENIZERS:
        order = by_text.sort(k)
        x = order[k].to_numpy()
        tail = 1 - order["filas"].cum_sum().to_numpy() / order["filas"].sum()
        ax.step(x, tail, where="post", label=k, color=COLORS[k])
    for c in (TRAIN_MAX_LENGTH, 512):
        ax.axvline(c, color="#888888", lw=0.8, ls="--")
    ax.set(
        xscale="log",
        yscale="log",
        xlabel="Tokens (con especiales)",
        ylabel="Proporción de filas con más tokens",
        title="Cola de la longitud en tokens",
    )
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG / "tokens_ccdf.png", dpi=150)

    (OUT / "tokens_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: metrics[k]
                for k in (
                    "por_fila",
                    "truncadas_entrenamiento",
                    "tokens_por_palabra",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main(sys.argv[1])
