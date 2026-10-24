"""Segmentación de las reseñas en cláusulas (5.5, fase 2; diseño §4.1).

Una reseña larga suele mezclar problemas (multi-aspecto de 46–51 % en las de
20+ palabras, 5.2) y en la fase 1 el ruido de HDBSCAN se concentró en ellas.
Esta segmentación es deliberadamente simple y determinista (`SEGMENTER`):

* corta en fin de oración (`.`, `!`, `?`, `;`, saltos de línea) y antes de
  conectores que suelen introducir otro problema: "pero", "además", "aparte",
  "también", "y encima", "y aparte" y "y además";
* une al segmento anterior los fragmentos de menos de `MIN_WORDS` palabras;
* una reseña sin ningún segmento válido queda como un solo segmento.

No corta en una "y" suelta, porque une tanto problemas distintos ("no puedo
entrar y me cobraron") como partes de uno ("transferencias y pagos"): es una
limitación declarada.

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.topics.units build

Escribe `segments.parquet` y `emb_segments_minilm.npy` en
`data/topics/working_v0/` (fuera de git).
"""

import argparse
import re
import time

import numpy as np
import polars as pl

from voc_analytics.topics.working_set import MAX_SEQ, MODELS, OUT

SEGMENTER = "clauses_v0"
MIN_WORDS = 3
_SPLIT = re.compile(
    r"[.!?;\n]+"
    r"|,?\s+(?=(?:pero|adem[aá]s|aparte|tambi[eé]n|y\s+encima|y\s+aparte"
    r"|y\s+adem[aá]s)\b)",
    flags=re.IGNORECASE,
)
_TAIL = re.compile(r"(?:,|\s+y)\s*$", flags=re.IGNORECASE)  # "se cierra sola y"


def segment(text: str) -> list[str]:
    """Cláusulas de `text` según `SEGMENTER`."""
    parts = [_TAIL.sub("", p.strip(" ,")) for p in _SPLIT.split(text)]
    parts = [p for p in parts if p]
    out: list[str] = []
    for p in parts:
        if out and len(p.split()) < MIN_WORDS:
            out[-1] = f"{out[-1]} {p}"
        else:
            out.append(p)
    if len(out) > 1 and len(out[0].split()) < MIN_WORDS:
        out[1] = f"{out[0]} {out[1]}"
        out = out[1:]
    return out or [text]


def build() -> None:
    texts = pl.read_parquet(
        OUT / "texts.parquet", columns=["text_id", "texto_sanitizado"]
    )
    seg = (
        texts.with_columns(
            segmento=pl.col("texto_sanitizado").map_elements(
                segment, return_dtype=pl.List(pl.String)
            )
        )
        .explode("segmento")
        .with_columns(orden=pl.int_range(pl.len()).over("text_id"))
        .select("text_id", "orden", "segmento")
    )
    seg.write_parquet(OUT / "segments.parquet")
    per = seg.group_by("text_id").len()["len"]
    print(
        f"{texts.height} textos → {seg.height} segmentos; "
        f"por texto: media {per.mean():.2f}, máx {per.max()}"
    )

    import torch
    from sentence_transformers import SentenceTransformer

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = SentenceTransformer(MODELS["minilm"], device=device)
    model.max_seq_length = MAX_SEQ
    t0 = time.perf_counter()
    emb = model.encode(
        seg["segmento"].to_list(), batch_size=64, show_progress_bar=True
    )
    np.save(OUT / "emb_segments_minilm.npy", emb.astype(np.float32))
    print(f"embeddings en {time.perf_counter() - t0:.0f} s ({device})")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_subparsers(dest="cmd", required=True).add_parser("build")
    p.parse_args()
    build()


if __name__ == "__main__":
    main()
