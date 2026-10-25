"""RoBERTuito: carga en fp32, orden por longitud y verificación de etiquetas."""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from voc_nlp.sentiment_model import (  # noqa: E402
    CLASSES,
    MAX_LENGTH,
    encode,
    load_sentiment_model,
    load_tokenizer,
    predict_ids,
    predict_proba,
    prepare,
    token_ids,
)

TEXTS = [
    "la app no abre",
    "mala",
    "me cobraron doble pero gracias la app es buena excelente",
    "pésima 😡",
    "",
]


def test_fp16_weights_load_as_fp32(tiny_weights: Path) -> None:
    model = load_sentiment_model(tiny_weights)
    assert next(model.model.parameters()).dtype == torch.float32
    assert not model.model.training


def test_rejects_unexpected_labels(tiny_weights: Path, tmp_path: Path) -> None:
    copy = tmp_path / "w"
    shutil.copytree(tiny_weights, copy)
    config = json.loads((copy / "config.json").read_text())
    config["id2label"] = {"0": "POS", "1": "NEU", "2": "NEG"}
    (copy / "config.json").write_text(json.dumps(config))
    with pytest.raises(ValueError, match="id2label"):
        load_sentiment_model(copy)


def test_batches_by_length_keep_the_input_order(tiny_weights: Path) -> None:
    model = load_sentiment_model(tiny_weights)
    together = predict_proba(model, TEXTS, batch_size=2)
    alone = np.vstack([predict_proba(model, [t]) for t in TEXTS])
    assert together.shape == (len(TEXTS), len(CLASSES))
    assert np.allclose(together, alone, atol=1e-5)
    assert np.allclose(together.sum(axis=1), 1.0, atol=1e-5)


def test_encode_applies_preprocess_tweet_and_truncates(
    tiny_weights: Path,
) -> None:
    model = load_sentiment_model(tiny_weights)
    ids = encode(model, ["😡", "la " * 500])
    vocab = model.tokenizer.get_vocab()
    # preprocess_tweet convierte el emoji en palabras del vocabulario.
    assert vocab["cara"] in ids[0] and vocab["cabreada"] in ids[0]
    assert len(ids[1]) == MAX_LENGTH


def test_prepare_then_token_ids_equals_encode(tiny_weights: Path) -> None:
    model = load_sentiment_model(tiny_weights)
    tokenizer = load_tokenizer(tiny_weights)
    assert token_ids(tokenizer, prepare(TEXTS)) == encode(model, TEXTS)


def test_empty_input(tiny_weights: Path) -> None:
    model = load_sentiment_model(tiny_weights)
    assert predict_ids(model, []).shape == (0, 3)


def test_missing_pad_token_fails(tiny_weights: Path) -> None:
    model = load_sentiment_model(tiny_weights)
    model.tokenizer.pad_token = None
    with pytest.raises(ValueError, match="pad"):
        predict_ids(model, [[0, 4, 2]])
