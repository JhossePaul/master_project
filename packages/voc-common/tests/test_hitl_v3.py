"""Casos, transiciones y revisiones HITL del esquema v3 (6.1)."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from voc_common.analytics_codes import DisplayMode, HitlReason
from voc_common.hitl_v3 import (
    BLIND_REASONS,
    GoldVersion,
    Guideline,
    HitlEvent,
    HitlItem,
    HitlReview,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "analytics_v3"
KEY = "a" * 64
ACTOR = "b" * 64


def load(name: str) -> dict[str, Any]:
    path = _FIXTURES / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _item(**overrides: Any) -> HitlItem:
    data = load("hitl_item_monitor")
    data.update(overrides)
    return HitlItem(**data)


def test_blind_reasons() -> None:
    assert BLIND_REASONS == {
        HitlReason.MONITOR_SAMPLE,
        HitlReason.AGREEMENT_SAMPLE,
    }
    assert _item().display_mode is DisplayMode.BLIND


@pytest.mark.parametrize("reason", ["monitor_sample", "agreement_sample"])
def test_assisted_sample_is_rejected(reason: str) -> None:
    with pytest.raises(ValidationError, match="must be blind"):
        _item(reason=reason, display_mode="assisted")


def test_low_confidence_can_be_assisted() -> None:
    assert _item(reason="low_confidence", display_mode="assisted")


def test_drift_boost_requires_its_boost_id() -> None:
    assert _item(
        reason="drift_boost", boost_id="boost-1", display_mode="assisted"
    )
    with pytest.raises(ValidationError, match="boost_id"):
        _item(reason="drift_boost", display_mode="assisted")
    with pytest.raises(ValidationError, match="boost_id"):
        _item(boost_id="boost-1")


def test_hitl_event() -> None:
    event = HitlEvent(
        event_id="e1",
        item_id="item-0001",
        status="queued",
        at="2026-11-02T08:00:00Z",
    )
    assert event.actor_hash is None
    with pytest.raises(ValidationError):
        HitlEvent(
            event_id="e2",
            item_id="item-0001",
            status="done",
            at="2026-11-02T08:00:00Z",
        )


def _review(**overrides: Any) -> HitlReview:
    data: dict[str, Any] = {
        "review_id": "review-0001",
        "item_id": "item-0001",
        "id_resena": "synthetic-0001",
        "task": "sentiment",
        "predicted_label": "NEG",
        "validated_label": "NEG",
        "outcome": "confirmed",
        "display_mode": "blind",
        "review_round": 1,
        "flags": ["menciona_falla"],
        "guideline_version": "v2.2",
        "model_version": "M4_robertuito_s1_ppi",
        "risk_policy_version": "risk_policy_v1",
        "reviewer_hash": ACTOR,
        "opened_at": "2026-11-02T09:00:00Z",
        "submitted_at": "2026-11-02T09:00:40Z",
        "seconds_spent": 40,
    }
    data.update(overrides)
    return HitlReview(**data)


def test_second_review_is_another_row() -> None:
    first = _review()
    second = _review(
        review_id="review-0002", review_round=2, reviewer_hash="c" * 64
    )
    assert (first.item_id, first.review_round) != (
        second.item_id,
        second.review_round,
    )
    with pytest.raises(ValidationError):
        _review(review_round=3)


def test_outcome_matches_the_labels() -> None:
    assert _review(validated_label="NEU", outcome="corrected")
    with pytest.raises(ValidationError, match="outcome"):
        _review(validated_label="NEU")
    with pytest.raises(ValidationError, match="outcome"):
        _review(outcome="corrected")


def test_sentiment_review_shape() -> None:
    with pytest.raises(
        ValidationError, match="require predicted and validated"
    ):
        _review(validated_label=None)
    with pytest.raises(ValidationError, match="no aspects"):
        _review(predicted_families=["AC"])
    with pytest.raises(ValidationError, match="repeat"):
        _review(flags=["duda", "duda"])
    with pytest.raises(ValidationError, match="submitted_at"):
        _review(submitted_at="2026-11-02T08:00:00Z")


def _aspects_review(**overrides: Any) -> HitlReview:
    data: dict[str, Any] = {
        "task": "aspects",
        "predicted_label": None,
        "validated_label": None,
        "predicted_families": ["AC", "TR"],
        "validated_families": ["TR", "AC"],
        "predicted_flag_update": False,
        "validated_flag_update": False,
        "predicted_flag_security": False,
        "validated_flag_security": False,
        "flags": [],
        "guideline_version": "v2.1",
    }
    data.update(overrides)
    return _review(**data)


def test_aspects_review_compares_sets_and_flags() -> None:
    assert _aspects_review().outcome.value == "confirmed"
    assert _aspects_review(validated_flag_update=True, outcome="corrected")
    with pytest.raises(ValidationError, match="outcome"):
        _aspects_review(validated_families=["AC"])
    with pytest.raises(ValidationError, match="u and s"):
        _aspects_review(validated_flag_security=None)
    with pytest.raises(ValidationError, match="no sentiment label"):
        _aspects_review(predicted_label="NEG")
    with pytest.raises(ValidationError, match="repeat"):
        _aspects_review(validated_families=["AC", "AC"], outcome="corrected")


def test_topic_reviews_go_to_curation_topics() -> None:
    with pytest.raises(ValidationError):
        _review(task="topic")


def test_guideline_and_gold_version() -> None:
    guideline = Guideline(
        guideline_version="v2.2",
        task="sentiment",
        content_uri="docs/analytics/labeling/guideline_v2_2.md",
        valid_from="2026-10-01T00:00:00Z",
        published_by_hash=ACTOR,
    )
    assert guideline.task.value == "sentiment"
    gold = GoldVersion(
        gold_version="gold_hitl_v1",
        criteria={
            "reason": "monitor_sample",
            "period": "2026Q4",
            "guideline_version": "v2.2",
        },
        cutoff_at="2027-01-01T00:00:00Z",
        items=300,
        created_by_hash=ACTOR,
        created_at="2027-01-02T00:00:00Z",
    )
    assert gold.criteria["reason"] == "monitor_sample"
    with pytest.raises(ValidationError):
        GoldVersion(**{**gold.model_dump(), "items": -1})
