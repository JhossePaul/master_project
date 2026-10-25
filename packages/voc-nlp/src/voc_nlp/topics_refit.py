"""Re-ajuste del modelo de tópicos y emparejamiento con el anterior.

Port de ``voc_analytics.incidents.backfill_topics.fit`` y
``voc_analytics.topics.pilot.fit`` (el ajuste de ``topics_v1``), con los
mismos parámetros: UMAP de 5 dimensiones (15 vecinos, ``min_dist`` 0,
coseno, semilla 0) conservado para ``transform``; HDBSCAN con
``min_cluster_size`` 100 y ``min_samples`` 10; c-TF-IDF con unigramas y
bigramas, sin acentos y con las palabras vacías de spaCy menos las
negaciones (``data/topic_stop_words_es.json``, las mismas del modelo
guardado). Ningún paso usa un LLM: los nombres los pone el curador.

El emparejamiento compara centroides en el espacio de MiniLM (384
dimensiones): los de la versión nueva salen de su ajuste y los de la
anterior, de asignar las mismas cláusulas con su modelo congelado. Cada
tópico nuevo se empareja con el anterior más parecido (coseno), sin umbral
automático: el curador confirma o rechaza cada par. La firma cambia frente
a la prevista (``match`` recibía entradas del catálogo): el catálogo no
guarda centroides, así que ``match`` los recibe.
"""

import json
import pickle  # nosec B403 - solo artefactos propios de ml_artifacts/
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from voc_nlp.topics import NOISE_TOPIC, FrozenTopicModel

TOP_N_WORDS: Final = 10


@dataclass(frozen=True)
class TopicParams:
    """Parámetros del ajuste; se guardan en ``topic_model_versions``."""

    min_cluster_size: int = 100
    min_samples: int = 10
    seed: int = 0
    n_components: int = 5
    n_neighbors: int = 15
    min_dist: float = 0.0
    top_n_words: int = TOP_N_WORDS

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_PARAMS: Final = TopicParams()


@dataclass(frozen=True)
class TopicMatch:
    topic_id: int
    previous_topic_id: int
    similarity: float


@cache
def stop_words() -> list[str]:
    data = resources.files("voc_nlp") / "data" / "topic_stop_words_es.json"
    return list(json.loads(data.read_text(encoding="utf-8"))["words"])


def refit(
    segments: Sequence[str],
    embeddings: NDArray[np.floating],
    params: TopicParams = DEFAULT_PARAMS,
) -> tuple[FrozenTopicModel, list[int]]:
    """Ajusta UMAP y BERTopic; devuelve el modelo y el tópico de cada unidad."""
    from bertopic import BERTopic
    from bertopic.dimensionality import BaseDimensionalityReduction
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP

    if len(segments) != len(embeddings):
        raise ValueError("segments and embeddings differ in length")
    umap = UMAP(
        n_components=params.n_components,
        n_neighbors=params.n_neighbors,
        min_dist=params.min_dist,
        metric="cosine",
        random_state=params.seed,
        low_memory=True,
    ).fit(np.asarray(embeddings))
    model = BERTopic(
        umap_model=BaseDimensionalityReduction(),
        hdbscan_model=HDBSCAN(
            min_cluster_size=params.min_cluster_size,
            min_samples=params.min_samples,
            prediction_data=True,
        ),
        # c-TF-IDF cuenta tópicos: ``min_df`` > 1 quitaría los términos
        # exclusivos de un tópico.
        vectorizer_model=CountVectorizer(
            strip_accents="unicode",
            stop_words=stop_words(),
            ngram_range=(1, 2),
            min_df=1,
        ),
        language="multilingual",
        top_n_words=params.top_n_words,
        calculate_probabilities=False,
    )
    model.fit(list(segments), embeddings=umap.embedding_)
    return FrozenTopicModel(umap, model), [int(t) for t in model.topics_]


def topic_terms(
    model: FrozenTopicModel, top: int = TOP_N_WORDS
) -> dict[int, list[str]]:
    """Términos de cada tópico, sin el ruido."""
    return {
        int(topic): [w for w, _ in (model.bertopic.get_topic(topic) or [])][
            :top
        ]
        for topic in model.bertopic.get_topics()
        if int(topic) != NOISE_TOPIC
    }


def save_topic_model(model: FrozenTopicModel, path: Path) -> Path:
    """``umap.pkl`` y ``bertopic`` (*pickle*), como los lee el delta."""
    path.mkdir(parents=True, exist_ok=True)
    with (path / "umap.pkl").open("wb") as f:
        pickle.dump(model.umap, f)
    model.bertopic.save(str(path / "bertopic"), serialization="pickle")
    return path


def centroids(
    embeddings: NDArray[np.floating], topics: Sequence[int]
) -> dict[int, NDArray[np.float64]]:
    """Media de los embeddings de cada tópico, sin el ruido."""
    emb = np.asarray(embeddings, dtype=np.float64)
    labels = np.asarray(topics)
    if len(labels) != len(emb):
        raise ValueError("embeddings and topics differ in length")
    return {
        int(t): emb[labels == t].mean(axis=0)
        for t in np.unique(labels)
        if int(t) != NOISE_TOPIC
    }


def match(
    previous: Mapping[int, NDArray[np.floating]],
    new: Mapping[int, NDArray[np.floating]],
) -> list[TopicMatch]:
    """Para cada tópico nuevo, el anterior de mayor similitud coseno."""
    if not previous or not new:
        return []
    old_ids = sorted(previous)
    old = np.array([previous[t] for t in old_ids], dtype=np.float64)
    old /= np.linalg.norm(old, axis=1, keepdims=True)
    out = []
    for topic in sorted(new):
        vec = np.asarray(new[topic], dtype=np.float64)
        sims = old @ (vec / np.linalg.norm(vec))
        best = int(np.argmax(sims))
        out.append(
            TopicMatch(
                topic_id=topic,
                previous_topic_id=old_ids[best],
                similarity=float(np.clip(sims[best], -1.0, 1.0)),
            )
        )
    return out
