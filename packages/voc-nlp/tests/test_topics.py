"""Segmentador ``clause_segmenter_v1``, embeddings y asignación de tópicos."""

import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pytest

pytest.importorskip("sentence_transformers")

from voc_nlp import topics  # noqa: E402
from voc_nlp.topics import (  # noqa: E402
    FrozenTopicModel,
    assign,
    embed,
    load_embedder,
    load_topic_model,
    segment,
    topics_by_review,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "la app no abre. me cobraron doble",
            ["la app no abre", "me cobraron doble"],
        ),
        (
            "la app es buena pero se cierra sola y",
            ["la app es buena", "pero se cierra sola"],
        ),
        ("no abre. ok", ["no abre ok"]),
        ("ok. la app no abre nunca", ["ok la app no abre nunca"]),
        ("!!!", ["!!!"]),
        ("", [""]),
        (
            # El primer fragmento tiene menos de 3 palabras: se une al segundo.
            "Excelente servicio, Además rápido y seguro",
            ["Excelente servicio Además rápido y seguro"],
        ),
    ],
)
def test_segment(text: str, expected: list[str]) -> None:
    assert segment(text) == expected


def test_embed_with_a_local_tiny_model(
    tiny_weights: Path, tmp_path: Path
) -> None:
    from sentence_transformers import SentenceTransformer, models

    word = models.Transformer(str(tiny_weights))
    pooling = models.Pooling(word.get_word_embedding_dimension())
    SentenceTransformer(modules=[word, pooling]).save(str(tmp_path / "st"))
    model = load_embedder(tmp_path / "st")
    assert model.max_seq_length == 128
    out = embed(model, ["la app no abre", "mala"])
    assert out.shape == (2, 16) and out.dtype == np.float32


class _Umap:
    def transform(self, x: np.ndarray) -> np.ndarray:
        return x[:, :2]


class _Bertopic:
    def __init__(self) -> None:
        self.calls = 0

    def transform(self, docs: list[str], embeddings: np.ndarray) -> Any:
        self.calls += 1
        assert embeddings.shape == (len(docs), 2)
        return [int(e[0]) for e in embeddings], None


def test_assign_in_batches_with_the_frozen_umap() -> None:
    fake = _Bertopic()
    model = FrozenTopicModel(_Umap(), fake)
    emb = np.array([[3, 0, 0], [-1, 0, 0], [7, 0, 0]], dtype=np.float32)
    assert assign(model, ["a", "b", "c"], emb, batch_size=2) == [3, -1, 7]
    assert fake.calls == 2
    with pytest.raises(ValueError, match="length"):
        assign(model, ["a"], emb)


def test_topics_by_review_drops_noise_and_repeats() -> None:
    assert topics_by_review([5, -1, 2, 5]) == [2, 5]
    assert topics_by_review([-1]) == []


def test_load_topic_model_reads_both_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bertopic

    (tmp_path / "umap.pkl").write_bytes(pickle.dumps({"umap": "congelado"}))
    seen: list[str] = []

    def fake_load(path: str) -> str:
        seen.append(path)
        return "bertopic"

    monkeypatch.setattr(bertopic.BERTopic, "load", staticmethod(fake_load))
    model = load_topic_model(tmp_path)
    assert model.umap == {"umap": "congelado"}
    assert model.bertopic == "bertopic"
    assert seen == [str(tmp_path / "bertopic")]
    assert topics.SEGMENTER == "clause_segmenter_v1"
