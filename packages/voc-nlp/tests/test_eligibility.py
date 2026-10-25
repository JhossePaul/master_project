"""Reglas ``eligibility_rules_v1`` con casos sintéticos."""

from datetime import UTC, datetime

import pytest
from voc_common.analytics_codes import (
    EligibilityCode,
    LabelSource,
    SentimentValue,
    TopicEligibilityCode,
)
from voc_common.constants import SentimentLabel
from voc_nlp.eligibility import (
    count_words,
    has_text_content,
    tnss_rule,
    topic_rule,
)
from voc_nlp.lexicon import Lexicon

LEXICON = Lexicon(
    "lexicon_v1",
    {"excelente": SentimentLabel.POS, "pesimo": SentimentLabel.NEG},
)
T = datetime(2026, 10, 1, tzinfo=UTC)


def _rule(text: str | None, bank: str = "BBVA", fecha: datetime = T):
    return tnss_rule(text, fecha, bank, LEXICON)


@pytest.mark.parametrize(
    ("text", "words"),
    [("", 0), ("   ", 0), ("una", 1), ("dos  palabras\n", 2), ("a\tb c", 3)],
)
def test_count_words(text: str, words: int) -> None:
    assert count_words(text) == words


@pytest.mark.parametrize(
    ("text", "content"),
    [
        ("hola", True),
        ("3702", True),
        ("😡😡", False),
        ("[PERSON_NAME]", False),
        ("[person_name] 👍 !!", False),
        ("[PERSON_NAME] ñ", True),
        ("...", False),
    ],
)
def test_has_text_content(text: str, content: bool) -> None:
    assert has_text_content(text) is content


def test_empty_text_is_tnss_empty() -> None:
    for text in (None, "", "   "):
        decision = _rule(text)
        assert decision.code is EligibilityCode.TNSS_EMPTY
        assert decision.source is LabelSource.NO_PREDICTED
        assert decision.palabras == 0


def test_text_without_content() -> None:
    decision = _rule("😡 [PERSON_NAME]")
    assert decision.code is EligibilityCode.TNSS_NO_TEXT_CONTENT
    assert decision.palabras == 2


def test_nubank_cut_and_other_banks() -> None:
    old = datetime(2019, 12, 31, 23, 59, tzinfo=UTC)
    assert (
        _rule("no abre la app", "NUBANK", old).code
        is EligibilityCode.TNSS_TIME_OUTLIER
    )
    assert _rule("no abre la app", "BBVA", old).code is EligibilityCode.ELEGIBLE
    cut = datetime(2020, 1, 1)  # naive = UTC
    assert _rule("no abre", "NUBANK", cut).code is EligibilityCode.ELEGIBLE


def test_precedence_no_content_before_time_outlier() -> None:
    old = datetime(2019, 1, 1, tzinfo=UTC)
    assert (
        _rule("😡", "NUBANK", old).code is EligibilityCode.TNSS_NO_TEXT_CONTENT
    )


def test_single_word_with_and_without_lexicon_label() -> None:
    labeled = _rule("Excelente!!")
    assert labeled.code is EligibilityCode.ELEGIBLE
    assert labeled.source is LabelSource.RULE_BASED
    assert labeled.label is SentimentLabel.POS
    unlabeled = _rule("hola")
    assert unlabeled.code is EligibilityCode.TNSS_SINGLE_WORD
    assert unlabeled.source is LabelSource.NO_PREDICTED
    assert unlabeled.label is None


def test_longer_texts_go_to_the_model() -> None:
    decision = _rule("excelente app")
    assert decision.code is EligibilityCode.ELEGIBLE
    assert decision.source is LabelSource.MODEL
    assert decision.palabras == 2
    assert decision.label is None


@pytest.mark.parametrize(
    ("sentiment", "palabras", "code"),
    [
        (None, 5, TopicEligibilityCode.TOPIC_TNSS_NOT_PREDICTED),
        (SentimentValue.NO_PREDICTED, 5, "TOPIC_TNSS_NOT_PREDICTED"),
        (SentimentValue.POS, 5, "TOPIC_NOT_NEGATIVE"),
        (SentimentValue.NEU, 1, "TOPIC_NOT_NEGATIVE"),
        (SentimentValue.NEG, 1, "TOPIC_TOO_SHORT"),
        (SentimentValue.NEG, 2, "ELEGIBLE"),
    ],
)
def test_topic_rule(
    sentiment: SentimentValue | None, palabras: int, code: str
) -> None:
    assert topic_rule(sentiment, palabras) == code
