"""Léxico ``lexicon_v1``: conteos, SHA-256 y forma normalizada."""

import collections
import json
from pathlib import Path

import pytest
from voc_common.constants import SentimentLabel
from voc_nlp.lexicon import LEXICON_PATH, form, load_lexicon


def test_lexicon_has_the_151_frozen_forms() -> None:
    payload = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
    counts = collections.Counter(payload["formas"].values())
    assert len(payload["formas"]) == 151
    assert counts == {"NEG": 22, "NEU": 7, "POS": 117, "NA": 5}
    assert payload["source_sha256"] == (
        "c632e174de021de55375c058d34326b6f02cfb7413b8cbc9fc0c0d0da5c2736d"
    )


def test_load_lexicon_drops_unlabeled_forms() -> None:
    lexicon = load_lexicon()
    assert lexicon.version == "lexicon_v1"
    assert len(lexicon.labels) == 146
    assert set(lexicon.labels.values()) == set(SentimentLabel)


def test_load_lexicon_rejects_a_modified_file(tmp_path: Path) -> None:
    copy = tmp_path / "lexicon.json"
    copy.write_bytes(LEXICON_PATH.read_bytes() + b" ")
    with pytest.raises(ValueError, match="checksum"):
        load_lexicon(copy)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Excelente!!!", "excelente"),
        ("ÉXCELENTE", "excelente"),
        ("muuuy", "muy"),
        ("niño", "nino"),
        ("👍 ok", "ok"),
        (None, ""),
        ("100", "10"),
    ],
)
def test_form(text: str | None, expected: str) -> None:
    assert form(text) == expected


def test_label_uses_the_normalized_form() -> None:
    lexicon = load_lexicon()
    some_form, label = next(iter(lexicon.labels.items()))
    assert lexicon.label(some_form.upper() + "!!") is label
    assert lexicon.label("zzzzqqq") is None
