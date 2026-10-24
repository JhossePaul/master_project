"""Modelos detrás de interfaces chicas, para cargarlos de a uno (D9).

Las pruebas los reemplazan por modelos falsos; en producción envuelven los
módulos de ``voc-nlp``. Cada motor se carga solo si su paso tiene trabajo y
se libera antes del siguiente.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from voc_common.operations_v3 import TokenAttribution


class SentimentEngine(Protocol):
    def predict(self, texts: Sequence[str]) -> NDArray[np.floating]: ...
    def explain(self, text: str) -> list[TokenAttribution]: ...


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> NDArray[np.floating]: ...


class TopicAssigner(Protocol):
    def assign(
        self, segments: Sequence[str], embeddings: NDArray[np.floating]
    ) -> list[int]: ...


class _RobertuitoEngine:
    def __init__(self, path: Path, batch_size: int, threads: int) -> None:
        import torch
        from voc_nlp.sentiment_model import load_sentiment_model

        torch.set_num_threads(threads)
        self.model = load_sentiment_model(path)
        self.batch_size = batch_size

    def predict(self, texts: Sequence[str]) -> NDArray[np.floating]:
        from voc_nlp.sentiment_model import predict_proba

        return predict_proba(self.model, texts, self.batch_size)

    def explain(self, text: str) -> list[TokenAttribution]:
        from voc_nlp.explain import occlusion

        return occlusion(self.model, text, self.batch_size)


class _MiniLmEmbedder:
    def __init__(self, path: Path) -> None:
        from voc_nlp.topics import load_embedder

        self.model = load_embedder(path)

    def embed(self, texts: Sequence[str]) -> NDArray[np.floating]:
        from voc_nlp.topics import embed

        return embed(self.model, texts)


class _FrozenTopics:
    def __init__(self, path: Path) -> None:
        from voc_nlp.topics import load_topic_model

        self.model = load_topic_model(path)

    def assign(
        self, segments: Sequence[str], embeddings: NDArray[np.floating]
    ) -> list[int]:
        from voc_nlp.topics import assign

        return assign(self.model, segments, embeddings)


def _robertuito(path: Path, batch_size: int, threads: int) -> SentimentEngine:
    return _RobertuitoEngine(path, batch_size, threads)


@dataclass(frozen=True)
class EngineLoaders:
    sentiment: Callable[[Path, int, int], SentimentEngine] = field(
        default=_robertuito
    )
    embedder: Callable[[Path], Embedder] = field(default=_MiniLmEmbedder)
    topics: Callable[[Path], TopicAssigner] = field(default=_FrozenTopics)
