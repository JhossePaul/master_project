"""Cláusulas, embeddings y tópicos congelados (extra ``[topics]``).

Port de ``voc_analytics.topics.units`` (segmentador ``clauses_v0``, aquí
``clause_segmenter_v1``), ``voc_analytics.topics.working_set``
(MiniLM, 128 tokens, sin normalizar) y ``voc_analytics.incidents.
backfill_topics.assign`` (UMAP congelado y ``BERTopic.transform``; ``-1`` es
ruido). El modelo de tópicos ``topics_v1`` es el ``model_v0`` de los
experimentos.
"""

import pickle  # nosec B403 - solo artefactos propios de ml_artifacts/
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer

SEGMENTER: Final = "clause_segmenter_v1"
EMBEDDING_MODEL: Final = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
MAX_SEQ_LENGTH: Final = 128
EMBED_BATCH_SIZE: Final = 64
ASSIGN_BATCH_SIZE: Final = 50_000
MIN_WORDS: Final = 3
NOISE_TOPIC: Final = -1

_SPLIT = re.compile(
    r"[.!?;\n]+"
    r"|,?\s+(?=(?:pero|adem[aá]s|aparte|tambi[eé]n|y\s+encima|y\s+aparte"
    r"|y\s+adem[aá]s)\b)",
    flags=re.IGNORECASE,
)
_TAIL = re.compile(r"(?:,|\s+y)\s*$", flags=re.IGNORECASE)


def segment(text: str) -> list[str]:
    """Cláusulas de ``text``; las de menos de 3 palabras se unen a la vecina."""
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


def load_embedder(path: Path | str = EMBEDDING_MODEL) -> SentenceTransformer:
    """MiniLM en CPU con tope de 128 tokens (en producción, carpeta local)."""
    model = SentenceTransformer(str(path), device="cpu")
    model.max_seq_length = MAX_SEQ_LENGTH
    return model


def embed(
    model: SentenceTransformer,
    texts: Sequence[str],
    batch_size: int = EMBED_BATCH_SIZE,
) -> NDArray[np.float32]:
    """Embeddings ``(n, 384)`` en float32, sin normalizar (como en los
    experimentos)."""
    out = model.encode(
        list(texts),
        batch_size=batch_size,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return np.asarray(out, dtype=np.float32)


@dataclass(frozen=True)
class FrozenTopicModel:
    """UMAP y BERTopic ajustados una vez; solo asignan, no se re-ajustan."""

    umap: Any
    bertopic: Any


def load_topic_model(path: Path) -> FrozenTopicModel:
    """Carga ``umap.pkl`` y ``bertopic`` (*pickle*) desde ``path``."""
    from bertopic import BERTopic

    with (path / "umap.pkl").open("rb") as f:
        umap = pickle.load(f)  # noqa: S301  # nosec B301 - artefacto propio
    return FrozenTopicModel(umap, BERTopic.load(str(path / "bertopic")))


def assign(
    model: FrozenTopicModel,
    segments: Sequence[str],
    embeddings: NDArray[np.floating],
    batch_size: int = ASSIGN_BATCH_SIZE,
) -> list[int]:
    """Tópico de cada segmento (``-1`` = ruido), con el UMAP congelado."""
    if len(segments) != len(embeddings):
        raise ValueError("segments and embeddings differ in length")
    topics: list[int] = []
    for start in range(0, len(segments), batch_size):
        reduced = model.umap.transform(
            np.asarray(embeddings[start : start + batch_size])
        )
        batch, _ = model.bertopic.transform(
            list(segments[start : start + batch_size]), embeddings=reduced
        )
        topics.extend(int(t) for t in batch)
    return topics


def topics_by_review(topics: Sequence[int]) -> list[int]:
    """Tópicos distintos de una reseña, ordenados y sin ruido."""
    return sorted({t for t in topics if t != NOISE_TOPIC})
