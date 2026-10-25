"""Backfill de tópicos: cláusulas, embeddings y modelo global (5.9, P9-3).

Decisión del autor (2026-10-22): segmentar y embeber todas las negativas del
corpus y asignarles tópicos con el modelo global de 5.5; el descubrimiento
por episodio y las alternativas (por ejemplo, `topics_over_time` de
BERTopic) se exploran después en 5.9, así que este backfill es provisional.
Los artefactos se conservan para EPIC-6 (6.3).

* **Textos:** los de `incidents.backfill_aspects` (negativas para familias,
  por `text_key`).
* **Cláusulas:** `topics.units.segment` (`clauses_v0`), igual que 5.5.
* **Embeddings:** MiniLM multilingüe (`topics.working_set.MODELS`), tope de
  128 tokens, en el Mac (F-11: el texto no sale del equipo).
* **Modelo (`fit`):** se reajusta el modelo de 5.5 (cláusulas,
  `min_cluster_size` 100, `min_samples` 10, UMAP con semilla 0) sobre los
  mismos 63 040 segmentos de la plata y se comprueba que reproduce los
  tópicos que curó el autor (`sets_clausulas_mcs100`). Se guarda congelado:
  entre reajustes los identificadores no cambian (P7-8).
* **Asignación (`assign`):** UMAP `transform` y `approximate_predict` de
  HDBSCAN para todas las cláusulas; la reseña toma el conjunto de tópicos de
  sus cláusulas, como en 5.5.

Escribe en `data/backfill/20261022/topics/` (fuera de git) y
`docs/analytics/incidents/backfill_topics_v0_metrics.json`, solo agregados.

    uv run python -m voc_analytics.incidents.backfill_topics segments
    uv run python -m voc_analytics.incidents.backfill_topics embed
    uv run python -m voc_analytics.incidents.backfill_topics fit
    uv run python -m voc_analytics.incidents.backfill_topics assign
"""

import argparse
import json
import pickle
import time
from datetime import UTC, datetime

import numpy as np
import polars as pl

from voc_analytics.incidents.backfill_aspects import BACKFILL
from voc_analytics.incidents.backfill_aspects import OUT as ASPECTS
from voc_analytics.paths import DOCS
from voc_analytics.topics.dynamics import MS, SEED
from voc_analytics.topics.dynamics import OUT as PHASE2
from voc_analytics.topics.units import SEGMENTER, segment
from voc_analytics.topics.working_set import MAX_SEQ, MODELS
from voc_analytics.topics.working_set import OUT as WORKING

OUT = BACKFILL / "topics"
MODEL_DIR = OUT / "model_v0"
METRICS = DOCS / "incidents" / "backfill_topics_v0_metrics.json"
MCS = 100
VARIANT = f"clausulas_mcs{MCS}"
BATCH = 50_000


def segments() -> None:
    texts = pl.read_parquet(
        ASPECTS / "texts.parquet",
        columns=["text_id", "text_key", "texto_sanitizado"],
    )
    seg = (
        texts.with_columns(
            segmento=pl.col("texto_sanitizado").map_elements(
                segment, return_dtype=pl.List(pl.String)
            )
        )
        .explode("segmento")
        .with_columns(orden=pl.int_range(pl.len()).over("text_id"))
        .select("text_id", "text_key", "orden", "segmento")
    )
    OUT.mkdir(parents=True, exist_ok=True)
    seg.write_parquet(OUT / "segments.parquet")
    print({"textos": texts.height, "segmentos": seg.height})


def embed() -> None:
    import torch
    from sentence_transformers import SentenceTransformer

    seg = pl.read_parquet(OUT / "segments.parquet", columns=["segmento"])
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = SentenceTransformer(MODELS["minilm"], device=device)
    model.max_seq_length = MAX_SEQ
    t0 = time.perf_counter()
    emb = model.encode(
        seg["segmento"].to_list(), batch_size=64, show_progress_bar=True
    )
    np.save(OUT / "emb_segments_minilm.npy", emb.astype(np.float32))
    print(f"embeddings en {time.perf_counter() - t0:.0f} s ({device})")


def fit() -> None:
    from umap import UMAP

    from voc_analytics.topics.pilot import fit as fit_bertopic

    seg = pl.read_parquet(WORKING / "segments.parquet")
    emb = np.load(WORKING / "emb_segments_minilm.npy")
    # Mismos parámetros que `topics.pilot.reduce`, pero conservando el objeto
    # para `transform`.
    umap = UMAP(
        n_components=5,
        n_neighbors=15,
        min_dist=0.0,
        metric="cosine",
        random_state=SEED,
        low_memory=True,
    ).fit(emb)
    model = fit_bertopic(seg["segmento"].to_list(), umap.embedding_, MCS, MS)

    # ¿Reproduce los tópicos de 5.5 que curó el autor?
    topics = np.array(model.topics_)
    sets = (
        seg.select("text_id")
        .with_columns(t=pl.Series(topics))
        .filter(pl.col("t") != -1)
        .group_by("text_id")
        .agg(pl.col("t").unique().sort())
    )
    prev = pl.read_parquet(PHASE2 / f"sets_{VARIANT}.parquet")
    j = prev.join(sets, on="text_id", how="left").with_columns(
        t=pl.col("t").fill_null([]).cast(pl.List(pl.Int64))
    )
    same = float((j["topicos"].list.sort() == j["t"]).mean())
    print({"textos": j.height, "conjuntos_iguales": round(same, 4)})

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with (MODEL_DIR / "umap.pkl").open("wb") as f:
        pickle.dump(umap, f)
    model.save(str(MODEL_DIR / "bertopic"), serialization="pickle")
    (MODEL_DIR / "model.json").write_text(
        json.dumps(
            {
                "variante": VARIANT,
                "segmentador": SEGMENTER,
                "embeddings": MODELS["minilm"],
                "max_seq": MAX_SEQ,
                "min_cluster_size": MCS,
                "min_samples": MS,
                "semilla_umap": SEED,
                "segmentos_ajuste": seg.height,
                "topicos": int(topics.max() + 1),
                "conjuntos_iguales_a_5_5": round(same, 4),
                "generado": datetime.now(UTC).isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def assign() -> None:
    from bertopic import BERTopic

    with (MODEL_DIR / "umap.pkl").open("rb") as f:
        umap = pickle.load(f)  # noqa: S301 - artefacto propio
    model = BERTopic.load(str(MODEL_DIR / "bertopic"))
    seg = pl.read_parquet(OUT / "segments.parquet")
    emb = np.load(OUT / "emb_segments_minilm.npy", mmap_mode="r")
    docs = seg["segmento"].to_list()
    topics = np.empty(seg.height, dtype=np.int32)
    t0 = time.perf_counter()
    for s in range(0, seg.height, BATCH):
        red = umap.transform(np.asarray(emb[s : s + BATCH]))
        t, _ = model.transform(docs[s : s + BATCH], embeddings=red)
        topics[s : s + BATCH] = t
        print(
            f"{s + len(t)} de {seg.height} ({time.perf_counter() - t0:.0f} s)",
            flush=True,
        )
    seg = seg.drop("segmento").with_columns(topic=pl.Series(topics))
    seg.write_parquet(OUT / "segment_topics_v0.parquet")
    by_key = (
        seg.filter(pl.col("topic") != -1)
        .group_by("text_key")
        .agg(topicos=pl.col("topic").unique().sort())
    )
    keys = pl.read_parquet(ASPECTS / "texts.parquet", columns=["text_key"])
    by_key = keys.join(by_key, on="text_key", how="left").with_columns(
        pl.col("topicos").fill_null([])
    )
    by_key.write_parquet(OUT / "topics_by_key.parquet")

    meta = json.loads((MODEL_DIR / "model.json").read_text())
    counts = seg.group_by("topic").len().sort("len", descending=True)
    result = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "modelo": meta,
        "textos": keys.height,
        "segmentos": seg.height,
        "segmentos_por_texto": round(seg.height / keys.height, 3),
        "ruido_segmentos": round(float((topics == -1).mean()), 4),
        "cobertura_textos": round(
            float((by_key["topicos"].list.len() > 0).mean()), 4
        ),
        "topicos_con_segmentos": int((counts["topic"] != -1).sum()),
        "segundos_asignacion": round(time.perf_counter() - t0),
        "peso_por_topico": {
            str(t): round(n / seg.height, 4) for t, n in counts.iter_rows()
        },
    }
    METRICS.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "peso_por_topico"},
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("segments", "embed", "fit", "assign"):
        sub.add_parser(cmd)
    args = ap.parse_args()
    {"segments": segments, "embed": embed, "fit": fit, "assign": assign}[
        args.cmd
    ]()


if __name__ == "__main__":
    main()
