"""Oclusión ``occlusion_v1``: una atribución por palabra, sin copiar texto."""

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("torch")

from voc_nlp.explain import METHOD, occlusion  # noqa: E402
from voc_nlp.sentiment_model import (  # noqa: E402
    load_sentiment_model,
    predict_proba,
)


def test_one_attribution_per_word_with_character_offsets(
    tiny_weights: Path,
) -> None:
    model = load_sentiment_model(tiny_weights)
    text = "la  app no abre"
    attributions = occlusion(model, text)
    assert METHOD == "occlusion_v1"
    assert [text[a.start : a.end] for a in attributions] == [
        "la",
        "app",
        "no",
        "abre",
    ]


def test_weight_is_the_drop_of_the_predicted_class(tiny_weights: Path) -> None:
    model = load_sentiment_model(tiny_weights)
    text = "me cobraron doble"
    attributions = occlusion(model, text)
    full = predict_proba(model, [text])[0]
    predicted = int(np.argmax(full))
    without_first = predict_proba(model, ["cobraron doble"])[0]
    expected = full[predicted] - without_first[predicted]
    assert attributions[0].weight == pytest.approx(expected, abs=1e-5)


def test_blank_text_has_no_attributions(tiny_weights: Path) -> None:
    model = load_sentiment_model(tiny_weights)
    assert occlusion(model, "   ") == []
