"""Oclusión ``occlusion_v1``: una atribución por palabra, sin copiar texto."""

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("torch")

from voc_nlp.calibration import apply_temperature  # noqa: E402
from voc_nlp.explain import METHOD, METHOD_V2, occlusion, occlusion_v2  # noqa: E402
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


def test_v2_gives_the_calibrated_change_of_the_three_classes(
    tiny_weights: Path,
) -> None:
    model = load_sentiment_model(tiny_weights)
    text = "la app no abre mala"
    temperature = 1.7

    out = occlusion_v2(model, text, temperature)

    assert METHOD_V2 == "occlusion_v2"
    assert [text[a.start : a.end] for a in out] == text.split()
    full = apply_temperature(predict_proba(model, [text]), temperature)[0]
    without = apply_temperature(
        predict_proba(model, ["la app abre mala"]), temperature
    )[0]
    expected = full - without
    got = [out[2].d_neg, out[2].d_neu, out[2].d_pos]
    assert got == pytest.approx(list(expected), abs=1e-5)
    assert all(a.weight is None for a in out)


def test_v2_changes_sum_to_zero_per_word(tiny_weights: Path) -> None:
    model = load_sentiment_model(tiny_weights)

    for a in occlusion_v2(model, "me cobraron doble pero gracias", 1.0):
        assert (a.d_neg + a.d_neu + a.d_pos) == pytest.approx(0, abs=1e-5)  # type: ignore[operator]


def test_v2_temperature_flattens_the_changes(tiny_weights: Path) -> None:
    model = load_sentiment_model(tiny_weights)
    text = "la app no abre mala"

    sharp = occlusion_v2(model, text, 1.0)
    flat = occlusion_v2(model, text, 50.0)

    assert max(abs(a.d_neg) for a in flat) < max(abs(a.d_neg) for a in sharp)  # type: ignore[arg-type]


def test_v2_blank_text_has_no_attributions(tiny_weights: Path) -> None:
    model = load_sentiment_model(tiny_weights)
    assert occlusion_v2(model, "  ", 1.0) == []
