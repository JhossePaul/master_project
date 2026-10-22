"""Conjunto de trabajo de 5.5: negativas de la plata y sus embeddings (fase 0).

5.5 trabaja con las filas `NEG` de la plata `silver_v0` (`prompt_v3`), no
con el corpus completo (el backfill es de 5.7, 5.8 y EPIC-6). Esa muestra ya
está estratificada por banco × periodo y trae `prob_inclusion`, así que sirve
como muestra de ajuste del BERTopic global (`topics_design.md` §4.2): cada fila
pesa 1 / π para estimar proporciones del corpus.

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.topics.working_set build
    uv run python -m voc_analytics.topics.working_set embed \\
        [--model minilm|robertuito]

* **build:** une las filas `NEG` de la plata con el snapshot (versión,
  `palabras` de las reglas de elegibilidad), normaliza versiones y escribe
  `rows.parquet` (una fila por reseña) y `texts.parquet` (un texto único por
  fila, con su número de filas y su peso).
* **embed:** embeddings de `texto_sanitizado` en el orden de `texts.parquet`,
  en `emb_<modelo>.npy` (MPS si está disponible).

Escribe en `data/topics/working_v0/` (fuera de git) y solo agregados en
`docs/analytics/topics_working_v0_metrics.json`.
"""

import argparse
import json
import time
from datetime import UTC, datetime

import numpy as np
import polars as pl

from voc_analytics.labeling.eligibility import RULES_VERSION, with_tnss_rule
from voc_analytics.paths import DATA, DOCS, LABELS
from voc_analytics.topics.versions import group_small, normalize

SILVER = LABELS / "silver_v0"
OUT = DATA / "topics" / "working_v0"
METRICS = DOCS / "topics_working_v0_metrics.json"
MODELS = {
    "minilm": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "robertuito": "pysentimiento/robertuito-base-uncased",
}
MAX_SEQ = 128  # el tope de 128 tokens trunca menos del 0.1 % (EDA §5.1)


def snapshot_file() -> str:
    return json.loads((SILVER / "sample_meta.json").read_text())[
        "snapshot_file"
    ]


def build() -> None:
    labels = pl.read_parquet(SILVER / "labels_prompt_v3.parquet").filter(
        pl.col("gemini_s") == "NEG"
    )
    texts = pl.read_parquet(
        SILVER / "texts.parquet", columns=["text_id", "texto_sanitizado"]
    )
    rows = pl.read_parquet(
        SILVER / "rows.parquet",
        columns=[
            "id_resena",
            "bank_id",
            "periodo",
            "estrellas",
            "fecha",
            "prob_inclusion",
            "split",
            "text_id",
        ],
    ).join(labels.select("text_id"), on="text_id")
    tds = (
        pl.scan_parquet(DATA / snapshot_file())
        .select("id_resena", "texto_limpio", "version_app")
        .join(
            rows.lazy().select("id_resena", "bank_id", "fecha"), on="id_resena"
        )
        .collect()
    )
    tds = with_tnss_rule(tds).select(
        "id_resena", "version_app", "palabras", "tnss_rule"
    )
    rows = normalize(rows.join(tds, on="id_resena", how="left"))
    rows = group_small(rows).with_columns(peso=1 / pl.col("prob_inclusion"))

    by_text = (
        rows.group_by("text_id")
        .agg(
            filas=pl.len(),
            peso=pl.col("peso").sum(),
            palabras=pl.col("palabras").first(),
            bancos=pl.col("bank_id").unique().sort().str.join("|"),
        )
        .join(texts, on="text_id")
        .sort("text_id")
    )
    OUT.mkdir(parents=True, exist_ok=True)
    rows.write_parquet(OUT / "rows.parquet")
    by_text.write_parquet(OUT / "texts.parquet")

    cov = (
        rows.group_by("bank_id")
        .agg(
            filas=pl.len(),
            sin_version=pl.col("release").is_null().mean().round(4),
            releases=pl.col("release").n_unique(),
            releases_con_masa=pl.col("release_agrupada")
            .filter(pl.col("release_agrupada") != "OTRAS")
            .n_unique(),
            filas_no_elegibles=pl.col("tnss_rule").is_not_null().sum(),
        )
        .sort("bank_id")
    )
    metrics = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": "silver_v0 (prompt_v3), gemini_s == NEG",
        "snapshot_file": snapshot_file(),
        "rules_version": RULES_VERSION,
        "rows": rows.height,
        "unique_texts": by_text.height,
        "rows_estimated_population": round(rows["peso"].sum()),
        "words_quantiles": {
            f"p{q}": by_text["palabras"].quantile(q / 100)
            for q in (10, 25, 50, 75, 90)
        },
        "by_bank": cov.to_dicts(),
    }
    METRICS.parent.mkdir(parents=True, exist_ok=True)
    METRICS.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def embed(model_key: str) -> None:
    import torch
    from sentence_transformers import SentenceTransformer

    docs = pl.read_parquet(OUT / "texts.parquet", columns=["texto_sanitizado"])[
        "texto_sanitizado"
    ].to_list()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = SentenceTransformer(MODELS[model_key], device=device)
    model.max_seq_length = MAX_SEQ
    t0 = time.perf_counter()
    emb = model.encode(
        docs, batch_size=64, show_progress_bar=True, convert_to_numpy=True
    )
    dt = time.perf_counter() - t0
    np.save(OUT / f"emb_{model_key}.npy", emb.astype(np.float32))
    print(
        f"{model_key}: {len(docs)} textos en {dt:.0f} s "
        f"({len(docs) / dt:.0f}/s, {device}), dim {emb.shape[1]}"
    )


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    e = sub.add_parser("embed")
    e.add_argument("--model", choices=sorted(MODELS), default="minilm")
    a = p.parse_args()
    build() if a.cmd == "build" else embed(a.model)


if __name__ == "__main__":
    main()
