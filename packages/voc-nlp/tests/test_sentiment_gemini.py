"""Sentimiento con Gemini: mismo prompt que la plata, lectura y reintentos."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("google.genai")

from voc_nlp.aspects import Usage  # noqa: E402
from voc_nlp.sentiment_gemini import (  # noqa: E402
    PROMPT_PATH,
    label_texts,
    load_prompt,
    parse,
)

SILVER_PROMPT = (
    Path(__file__).resolve().parents[3]
    / "experiments/analytics/src/voc_analytics/labeling/prompts/prompt_v3.md"
)


@dataclass
class _Response:
    text: str
    usage_metadata: Any = None


class _Models:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = replies
        self.calls: list[str] = []

    def generate_content(self, *, model: str, contents: str, config: Any):
        self.calls.append(contents)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return _Response(reply(contents) if callable(reply) else reply)


class _Client:
    def __init__(self, replies: list[Any]) -> None:
        self.models = _Models(replies)


def _all(label: str = "NEG"):
    def reply(contents: str) -> str:
        n = len(contents.splitlines())
        return "\n".join(f"{i} {label} 1" for i in range(n))

    return reply


@pytest.mark.skipif(not SILVER_PROMPT.exists(), reason="sin experiments/")
def test_prompt_is_the_one_that_labeled_the_silver() -> None:
    digest = hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()
    assert digest == hashlib.sha256(SILVER_PROMPT.read_bytes()).hexdigest()
    assert load_prompt().startswith("Eres un anotador")


def test_parse_reads_labels_and_ignores_noise() -> None:
    assert parse("hola\n0 POS 0\n 1  NA 1 \n2 MAL 0") == {
        0: ("POS", False),
        1: ("NA", True),
    }
    assert parse("0 POS 0\n0 NEG 1") is None


def test_label_texts_in_batches() -> None:
    client = _Client([_all("POS"), _all("NEG")])
    items = [(f"k{i}", f"texto {i}") for i in range(5)]
    usage = Usage()
    got = label_texts(client, items, "p", batch_size=3, usage=usage)
    assert [(g.key, g.label) for g in got] == [
        ("k0", "POS"),
        ("k1", "POS"),
        ("k2", "POS"),
        ("k3", "NEG"),
        ("k4", "NEG"),
    ]
    assert usage.calls == 2 and got[0].problem


def test_missing_texts_are_retried_and_failures_dropped() -> None:
    client = _Client(
        [
            "0 POS 0\n2 NEU 0",  # falta el 1
            RuntimeError("caída"),
            "basura",
            "7 POS 0",  # índice ajeno
        ]
    )
    items = [("a", "x"), ("b", "y"), ("c", "z")]
    usage = Usage()
    got = label_texts(client, items, "p", usage=usage, sleep=lambda s: None)
    assert [g.key for g in got] == ["a", "c"]
    assert usage.errors[0].startswith("RuntimeError")
    assert len(usage.errors) == 3


def test_whole_batch_failure_splits_in_halves() -> None:
    client = _Client(["", "", "", _all(), _all()])
    items = [("a", "x"), ("b", "y")]
    got = label_texts(client, items, "p", sleep=lambda s: None)
    assert sorted(g.key for g in got) == ["a", "b"]
