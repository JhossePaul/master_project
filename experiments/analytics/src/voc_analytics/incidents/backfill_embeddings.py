"""Embeddings por texto de todo el corpus para la búsqueda semántica (P8-6).

Decisión del autor (2026-10-22): calcularlos ahora, junto con los demás
backfills de 5.9, para cargarlos en EPIC-6 (6.2 y 6.3, `text_embeddings`).

* **Textos:** los 1 429 675 textos únicos del export del backfill de M4
  (`data/backfill/20261022/texts/`), positivos incluidos, con su `text_key`.
* **Modelo:** MiniLM multilingüe de 384 dimensiones
  (`topics.working_set.MODELS`), tope de 128 tokens, como los tópicos y el
  experimento de `VECTOR_SEARCH` de 5.7. En el Mac (F-11): el texto no sale
  del equipo.
* Se ordena por longitud para acelerar, como el benchmark de 5.7, y se
  guarda en el orden de `keys.parquet`.

Escribe en `data/backfill/20261022/embeddings/` (fuera de git):
`keys.parquet` (`text_key`) y `emb_minilm.npy` (float32, una fila por
clave), y `docs/analytics/incidents/backfill_embeddings_v0_metrics.json`,
solo agregados.

    uv run python -m voc_analytics.incidents.backfill_embeddings
"""

import json
import time
from datetime import UTC, datetime

import numpy as np
import polars as pl

from voc_analytics.incidents.backfill_aspects import BACKFILL
from voc_analytics.paths import DOCS
from voc_analytics.topics.working_set import MAX_SEQ, MODELS

OUT = BACKFILL / "embeddings"
METRICS = DOCS / "incidents" / "backfill_embeddings_v0_metrics.json"


def main() -> None:
    import torch
    from sentence_transformers import SentenceTransformer

    texts = (
        pl.read_parquet(
            BACKFILL / "texts", columns=["text_key", "texto_sanitizado"]
        )
        .sort("text_key")
        .with_columns(largo=pl.col("texto_sanitizado").str.len_chars())
    )
    order = np.argsort(texts["largo"].to_numpy(), kind="stable")
    docs = texts["texto_sanitizado"].to_list()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = SentenceTransformer(MODELS["minilm"], device=device)
    model.max_seq_length = MAX_SEQ
    t0 = time.perf_counter()
    emb = model.encode(
        [docs[i] for i in order], batch_size=128, show_progress_bar=True
    )
    seconds = time.perf_counter() - t0
    out = np.empty_like(emb, dtype=np.float32)
    out[order] = emb
    OUT.mkdir(parents=True, exist_ok=True)
    texts.select("text_key").write_parquet(OUT / "keys.parquet")
    np.save(OUT / "emb_minilm.npy", out)
    result = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "modelo": MODELS["minilm"],
        "max_seq": MAX_SEQ,
        "dimensiones": int(out.shape[1]),
        "textos": int(out.shape[0]),
        "dispositivo": device,
        "segundos": round(seconds),
        "textos_por_segundo": round(out.shape[0] / seconds),
        "megabytes": round(out.nbytes / 1e6),
    }
    METRICS.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
