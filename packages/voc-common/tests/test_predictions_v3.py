"""Invariantes de las salidas del modelo del esquema v3 (6.1)."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from voc_common.analytics_codes import (
    EligibilityCode,
    LabelSource,
    SentimentValue,
)
from voc_common.predictions_v3 import (
    ReviewAspects,
    ReviewPrediction,
    TextEmbedding,
    TopicAssignment,
    TopicCatalogEntry,
    TopicCuration,
    TopicModelVersion,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "analytics_v3"
KEY = "a" * 64
ACTOR = "b" * 64


def load(name: str) -> dict[str, Any]:
    path = _FIXTURES / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _prediction(**overrides: Any) -> ReviewPrediction:
    data = load("review_prediction_model")
    data.update(overrides)
    return ReviewPrediction(**data)


def _excluded(**overrides: Any) -> ReviewPrediction:
    data = load("review_prediction_excluded")
    data.update(overrides)
    return ReviewPrediction(**data)


def _rule_based(**overrides: Any) -> ReviewPrediction:
    data = {
        "palabras": 1,
        "label_source": "RULE_BASED",
        "sentiment": "POS",
        "p_neg": None,
        "p_neu": None,
        "p_pos": None,
        "confidence": None,
        "requires_hitl": False,
    }
    data.update(overrides)
    return _prediction(**data)


def test_fixtures_are_valid_and_round_trip() -> None:
    for prediction in (_prediction(), _excluded(), _rule_based()):
        restored = ReviewPrediction.model_validate_json(
            prediction.model_dump_json()
        )
        assert restored == prediction


def test_prediction_is_frozen_and_strict() -> None:
    prediction = _prediction()
    with pytest.raises(ValidationError):
        prediction.estrellas = 2  # type: ignore[misc]
    with pytest.raises(ValidationError, match="extra"):
        _prediction(topico="UX")


def test_unevaluated_row_has_no_sentiment() -> None:
    row = _excluded(eligibility_code=None, sentiment=None)
    assert row.sentiment is None
    with pytest.raises(ValidationError, match="unevaluated"):
        _excluded(eligibility_code=None)


@pytest.mark.parametrize(
    "overrides",
    [
        {"eligibility_code": "TNSS_TIME_OUTLIER"},
        {"label_source": "NO_PREDICTED"},
        {"sentiment": "NO_PREDICTED"},
    ],
)
def test_eligibility_label_source_and_sentiment_move_together(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        _prediction(**overrides)


def test_excluded_row_cannot_have_a_label() -> None:
    with pytest.raises(ValidationError, match="must hold together"):
        _excluded(sentiment="NEG")
    with pytest.raises(ValidationError, match="must hold together"):
        _excluded(eligibility_code="ELEGIBLE")


@pytest.mark.parametrize(
    ("code", "palabras"),
    [("TNSS_EMPTY", 2), ("TNSS_SINGLE_WORD", 3)],
)
def test_word_count_matches_the_rule(code: str, palabras: int) -> None:
    with pytest.raises(ValidationError, match="palabras"):
        _excluded(eligibility_code=code, palabras=palabras)
    assert _excluded(eligibility_code=code, palabras=int(code != "TNSS_EMPTY"))


def test_rule_based_rows_are_single_words_without_probabilities() -> None:
    row = _rule_based()
    assert row.label_source is LabelSource.RULE_BASED
    with pytest.raises(ValidationError, match="palabras"):
        _rule_based(palabras=2)
    with pytest.raises(ValidationError, match="require label_source = MODEL"):
        _rule_based(confidence=0.9)


@pytest.mark.parametrize(
    "overrides",
    [
        {"p_pos": None},
        {"confidence": None},
        {"model_version": None},
        {"calibration_version": None},
    ],
)
def test_model_rows_need_probabilities_and_versions(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match="requires"):
        _prediction(**overrides)


def test_probabilities_sum_to_one_within_tolerance() -> None:
    assert _prediction(p_neg=0.9 + 5e-7)
    with pytest.raises(ValidationError, match="sum to 1"):
        _prediction(p_neg=0.8)


def test_confidence_is_the_largest_probability() -> None:
    with pytest.raises(ValidationError, match="largest probability"):
        _prediction(confidence=0.07)


def test_requires_hitl_is_false_without_model() -> None:
    with pytest.raises(ValidationError, match="requires_hitl"):
        _excluded(requires_hitl=True)
    with pytest.raises(ValidationError, match="requires_hitl"):
        _rule_based(requires_hitl=True)


def test_boost_requires_policy_version() -> None:
    assert _prediction(hitl_boost_id="boost-1").hitl_boost_id == "boost-1"
    with pytest.raises(ValidationError, match="hitl_boost_id"):
        _prediction(hitl_boost_id="boost-1", risk_policy_version=None)


def test_excluded_fixture_values() -> None:
    row = _excluded()
    assert row.eligibility_code is EligibilityCode.TNSS_TIME_OUTLIER
    assert row.sentiment is SentimentValue.NO_PREDICTED
    assert row.p_neg is None


@pytest.mark.parametrize(
    "field", ["text_key", "estrellas", "eligibility_rules_version"]
)
def test_prediction_rejects_bad_scalars(field: str) -> None:
    bad = {"text_key": "ABC", "estrellas": 6, "eligibility_rules_version": "v2"}
    with pytest.raises(ValidationError):
        _prediction(**{field: bad[field]})


def _aspects(**overrides: Any) -> ReviewAspects:
    data: dict[str, Any] = {
        "id_resena": "synthetic-0001",
        "bank_id": "BBVA",
        "text_key": KEY,
        "fecha": "2026-10-20T12:00:00Z",
        "families": ["AC", "TR"],
        "flag_update": True,
        "flag_security": False,
        "praise": False,
        "prompt_version": "aspects_v2_1",
        "llm_model": "gemini-3.6-flash",
        "guideline_version": "v2.1",
        "sentiment_model_version": "M4_robertuito_s1_ppi",
        "run_id": "delta-20261021",
        "labeled_at": "2026-10-21T07:10:00Z",
    }
    data.update(overrides)
    return ReviewAspects(**data)


def test_review_aspects_rules() -> None:
    assert _aspects(families=[]).families == []
    with pytest.raises(ValidationError, match="repeat"):
        _aspects(families=["AC", "AC"])
    with pytest.raises(ValidationError):
        _aspects(families=["XX"])
    with pytest.raises(ValidationError):
        _aspects(sentiment_model_version="")


def _embedding(**overrides: Any) -> TextEmbedding:
    data: dict[str, Any] = {
        "text_key": KEY,
        "bank_id": "BBVA",
        "mes": "2026-10-01",
        "embedding": [0.0] * 384,
        "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2",
        "created_at": "2026-10-22T00:00:00Z",
    }
    data.update(overrides)
    return TextEmbedding(**data)


def test_text_embedding_has_384_dimensions_and_month_partition() -> None:
    assert _embedding().mes == date(2026, 10, 1)
    with pytest.raises(ValidationError):
        _embedding(embedding=[0.0] * 768)
    with pytest.raises(ValidationError, match="first day"):
        _embedding(mes="2026-10-15")


def test_topic_tables() -> None:
    version = TopicModelVersion(
        topic_model_version="model_v0",
        fitted_at="2026-10-15T00:00:00Z",
        embedding_model="paraphrase-multilingual-MiniLM-L12-v2",
        segmenter="clauses_v0",
        params={"min_cluster_size": 50, "min_samples": 10},
        fit_sample="working_set_v0",
    )
    assert version.params["min_cluster_size"] == 50
    entry = TopicCatalogEntry(
        topic_model_version="model_v1",
        topic_id=3,
        terms=["token", "sms"],
        previous_topic_id=7,
        centroid_similarity=0.82,
    )
    assert entry.previous_topic_id == 7
    with pytest.raises(ValidationError, match="all present or all null"):
        TopicCatalogEntry(
            topic_model_version="model_v1",
            topic_id=3,
            terms=[],
            previous_topic_id=7,
        )
    assignment = TopicAssignment(
        id_resena="synthetic-0001",
        bank_id="BBVA",
        text_key=KEY,
        fecha="2026-10-20T12:00:00Z",
        segment_index=0,
        topic_model_version="model_v0",
        topic_id=-1,
    )
    assert assignment.topic_id == -1
    with pytest.raises(ValidationError):
        TopicAssignment(**{**assignment.model_dump(), "topic_id": -2})


def test_topic_curation() -> None:
    data: dict[str, Any] = {
        "topic_model_version": "model_v0",
        "topic_id": 4,
        "curated_name": "Token y SMS",
        "coherence_1_5": 4,
        "audience": "ingenieria",
        "families": ["AC"],
        "is_new_theme": False,
        "mapping_confirmed": True,
        "curator_hash": ACTOR,
        "curated_at": "2026-10-16T00:00:00Z",
    }
    assert TopicCuration(**data).audience.value == "ingenieria"
    with pytest.raises(ValidationError):
        TopicCuration(**{**data, "coherence_1_5": 6})
    with pytest.raises(ValidationError, match="repeat"):
        TopicCuration(**{**data, "families": ["AC", "AC"]})
