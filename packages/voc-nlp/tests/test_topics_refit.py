"""Re-ajuste de tópicos: palabras vacías, centroides, pares y un ajuste real."""

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("bertopic")

from voc_nlp.topics import assign, load_topic_model  # noqa: E402
from voc_nlp.topics_refit import (  # noqa: E402
    TopicMatch,
    TopicParams,
    centroids,
    match,
    refit,
    save_topic_model,
    stop_words,
    topic_terms,
)


def test_stop_words_keep_negations() -> None:
    words = stop_words()
    assert len(words) == 456 and words == sorted(words)
    assert {"de", "la", "que", "ademas"} <= set(words)
    assert not {"no", "sin", "nunca", "nada", "ningun", "ninguna"} & set(words)


def test_centroids_skip_noise() -> None:
    emb = np.array([[1.0, 0.0], [3.0, 0.0], [0.0, 2.0], [9.0, 9.0]])
    out = centroids(emb, [0, 0, 1, -1])
    assert set(out) == {0, 1}
    assert out[0].tolist() == [2.0, 0.0] and out[1].tolist() == [0.0, 2.0]
    with pytest.raises(ValueError):
        centroids(emb, [0, 1])


def test_match_pairs_each_new_topic_with_the_closest_previous() -> None:
    previous = {0: np.array([1.0, 0.0]), 5: np.array([0.0, 1.0])}
    new = {0: np.array([0.1, 2.0]), 1: np.array([3.0, 0.3])}
    pairs = match(previous, new)
    assert [(p.topic_id, p.previous_topic_id) for p in pairs] == [
        (0, 5),
        (1, 0),
    ]
    assert pairs[0].similarity == pytest.approx(2.0 / np.hypot(0.1, 2.0))
    # Sin umbral: dos tópicos nuevos pueden caer en el mismo anterior.
    both = match({7: np.array([1.0, 1.0])}, new)
    assert {p.previous_topic_id for p in both} == {7}
    assert match({}, new) == [] and match(previous, {}) == []
    assert isinstance(pairs[0], TopicMatch)


THEMES = {
    "transferencias": "la transferencia spei no llega rechazada",
    "acceso": "no puedo entrar contraseña bloqueada token",
    "cobros": "me cobraron doble comision cargo indebido",
}


def synthetic(n: int = 60, seed: int = 1):
    rng = np.random.default_rng(seed)
    docs, emb, truth = [], [], []
    for k, (name, words) in enumerate(THEMES.items()):
        center = np.zeros(20)
        center[k * 5] = 10.0
        for i in range(n):
            docs.append(f"{words} {name} caso {i}")
            emb.append(center + rng.normal(0, 0.3, 20))
            truth.append(k)
    return docs, np.array(emb, dtype=np.float32), np.array(truth)


def test_refit_finds_the_themes_and_round_trips(tmp_path: Path) -> None:
    docs, emb, truth = synthetic()
    params = TopicParams(min_cluster_size=15, min_samples=3, n_neighbors=10)
    model, topics = refit(docs, emb, params)
    labels = np.array(topics)
    assert len(set(labels) - {-1}) == 3
    # Cada tema sintético cae en un solo tópico.
    for k in range(3):
        found = set(labels[(truth == k) & (labels != -1)])
        assert len(found) == 1
    terms = topic_terms(model)
    assert len(terms) == 3 and all(len(t) <= 10 for t in terms.values())
    assert any("transferencia" in " ".join(t) for t in terms.values())
    assert not any("de" in t for t in terms.values())
    loaded = load_topic_model(save_topic_model(model, tmp_path / "v2"))
    again = assign(loaded, docs[:30], emb[:30])
    assert np.mean(np.array(again) == labels[:30]) >= 0.9
    assert params.as_dict()["min_cluster_size"] == 15
    with pytest.raises(ValueError):
        refit(docs[:5], emb[:4], params)
