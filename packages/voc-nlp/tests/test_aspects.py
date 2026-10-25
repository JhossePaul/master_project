"""Familias con Gemini: ``parse``, reintentos, pendientes y copia del prompt."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("google.genai")

from voc_common.analytics_codes import AspectFamily  # noqa: E402
from voc_nlp import aspects  # noqa: E402
from voc_nlp.aspects import (  # noqa: E402
    PROMPT_PATH,
    Usage,
    as_line,
    label_batch,
    load_prompt,
    parse,
)

EXPERIMENT_PROMPT = (
    Path(__file__).resolve().parents[3]
    / "experiments/analytics/src/voc_analytics/eda/prompts/aspects_v2_1.md"
)


@dataclass
class _Meta:
    prompt_token_count: int = 100
    candidates_token_count: int = 20
    thoughts_token_count: int = 5


@dataclass
class _Response:
    text: str
    usage_metadata: _Meta | None = None


class _Models:
    def __init__(self, replies: list[Any], meta: bool = True) -> None:
        self.replies = replies
        self.meta = meta
        self.calls: list[str] = []

    def generate_content(self, *, model: str, contents: str, config: Any):
        self.calls.append(contents)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            reply = reply(contents)
        return _Response(reply, _Meta() if self.meta else None)


class _Client:
    def __init__(self, replies: list[Any], meta: bool = True) -> None:
        self.models = _Models(replies, meta)


def _all_lines(contents: str) -> str:
    n = len(contents.splitlines())
    return "\n".join(f"{i} AC 0 0 0" for i in range(n))


@pytest.mark.skipif(not EXPERIMENT_PROMPT.exists(), reason="sin experiments/")
def test_prompt_copy_is_identical_to_the_experiments() -> None:
    digest = hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()
    assert digest == hashlib.sha256(EXPERIMENT_PROMPT.read_bytes()).hexdigest()
    assert load_prompt().startswith(PROMPT_PATH.read_text()[:20])


def test_parse_valid_lines_flags_and_noise() -> None:
    parsed = parse(
        "texto libre que se ignora\n0 AC,TR 1 0 0\n1 - 0 1 1\n 2  OT 0 0 0 \n"
    )
    assert parsed is not None
    assert parsed[0].families == (AspectFamily.AC, AspectFamily.TR)
    assert (parsed[0].u, parsed[0].s, parsed[0].m) == (True, False, False)
    assert parsed[1].families == () and parsed[1].s and parsed[1].m
    assert parsed[2].families == (AspectFamily.OT,)


@pytest.mark.parametrize("text", ["0 XX 0 0 0", "0 AC 0 0 0\n0 TR 0 0 0"])
def test_unknown_codes_or_repeated_ids_invalidate_the_reply(text: str) -> None:
    assert parse(text) is None


def test_as_line_flattens_and_truncates() -> None:
    assert as_line(3, "a\n b\tc") == "3\ta b c"
    assert len(as_line(0, "x" * 5000)) == len("0\t") + 2000


def test_full_batch_in_one_call_with_usage() -> None:
    client = _Client([_all_lines])
    usage = Usage()
    items = [(f"k{i}", f"texto {i}") for i in range(4)]
    labels = label_batch(client, items, "prompt", usage=usage)  # type: ignore[arg-type]
    assert [lab.key for lab in labels] == ["k0", "k1", "k2", "k3"]
    assert usage.calls == 1 and usage.prompt == 100
    assert usage.cost_usd == pytest.approx((100 * 0.75 + 25 * 3.75) / 1e6)


def test_missing_ids_are_retried_in_a_smaller_batch() -> None:
    client = _Client(["0 AC 0 0 0\n2 TR 0 0 0", "0 DI 0 0 0"])
    items = [("a", "uno"), ("b", "dos"), ("c", "tres")]
    labels = label_batch(client, items, "p")  # type: ignore[arg-type]
    assert {lab.key: lab.families for lab in labels} == {
        "a": (AspectFamily.AC,),
        "c": (AspectFamily.TR,),
        "b": (AspectFamily.DI,),
    }
    assert client.models.calls[1] == "0\tdos"


def test_text_that_keeps_failing_stays_pending() -> None:
    sleeps: list[float] = []
    client = _Client(["", "", "", "0 AC 0 0 0", "", "", ""])
    items = [("a", "uno"), ("b", "dos")]
    labels = label_batch(  # type: ignore[arg-type]
        client, items, "p", sleep=sleeps.append
    )
    assert [lab.key for lab in labels] == ["a"]
    assert sleeps == []


def test_exceptions_back_off_and_retry() -> None:
    sleeps: list[float] = []
    usage = Usage()
    client = _Client([RuntimeError("503"), _all_lines])
    labels = label_batch(  # type: ignore[arg-type]
        client, [("a", "uno")], "p", usage=usage, sleep=sleeps.append
    )
    assert [lab.key for lab in labels] == ["a"]
    assert sleeps == [2] and usage.errors[0].startswith("RuntimeError")


def test_extra_ids_invalidate_the_reply() -> None:
    client = _Client(["0 AC 0 0 0\n7 TR 0 0 0", _all_lines])
    labels = label_batch(client, [("a", "uno")], "p")  # type: ignore[arg-type]
    assert [lab.key for lab in labels] == ["a"]
    assert len(client.models.calls) == 2


def test_client_and_config() -> None:
    config = aspects.generation_config("guía")
    assert config.temperature == 0
    assert config.system_instruction == "guía"
    assert config.max_output_tokens == 4096
    client = aspects.make_client("test-project")
    assert client is not None


def test_reply_without_usage_metadata() -> None:
    usage = Usage()
    client = _Client([_all_lines], meta=False)
    labels = label_batch(  # type: ignore[arg-type]
        client, [("a", "uno")], "p", usage=usage
    )
    assert [lab.key for lab in labels] == ["a"] and usage.prompt == 0
