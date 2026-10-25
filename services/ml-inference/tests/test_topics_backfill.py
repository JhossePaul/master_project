"""Backfill de tópicos: solo las negativas pendientes, vectores guardados."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ml_inference import topics_backfill
from ml_inference.topics_backfill import TopicBackfillError, run_topics_backfill

NOW = datetime(2026, 11, 4, 9, 30, tzinfo=UTC)
MODEL = "robertuito_sentiment_v1"
VERSION = "topics_v1"


def _prediction(world: Any, id_resena: str, text: str, sentiment: str = "NEG"):
    world.bq.rows("review_predictions").append(
        {
            "id_resena": id_resena,
            "bank_id": "BBVA",
            "text_key": world.text_key(text),
            "fecha": NOW - timedelta(days=300),
            "sentiment": sentiment,
            "palabras": len(text.split()),
            "model_version": MODEL,
            "run_id": "backfill-20261022",
            "predicted_at": NOW - timedelta(days=2),
        }
    )


def _history(world: Any, id_resena: str, text: str, **kwargs: Any) -> None:
    world.bq.rows("sanitized_reviews_tds").append(
        world.tds_row(id_resena, text, fecha=NOW - timedelta(days=300))
    )
    _prediction(world, id_resena, text, **kwargs)


def _stored(world: Any, text: str, segments: int) -> None:
    for i in range(segments):
        world.bq.rows("segment_embeddings").append(
            {
                "text_key": world.text_key(text),
                "segment_index": i,
                "segmenter": "clause_segmenter_v1",
                "embedding_model": "minilm",
                "embedding": [0.1] * 384,
                "run_id": "backfill-20261022",
                "created_at": NOW,
            }
        )


def _run(world: Any, now: datetime = NOW):
    return run_topics_backfill(
        world.settings,
        world.bq,
        world.storage,
        VERSION,
        now,
        engines=world.clients.engines,
    )


def test_assigns_only_pending_negatives_and_embeds_what_is_missing(
    world: Any,
) -> None:
    _history(world, "h1", "la app no abre nunca pero el cajero funciona")
    _stored(world, "la app no abre nunca pero el cajero funciona", 2)
    _history(world, "h2", "me cobraron doble comisión")
    _history(world, "pos", "muy buena la app", sentiment="POS")
    _history(world, "done", "el cajero no sirve")
    world.bq.rows("topic_assignments").append(
        {
            "id_resena": "done",
            "bank_id": "BBVA",
            "text_key": world.text_key("el cajero no sirve"),
            "fecha": NOW,
            "segment_index": 0,
            "topic_model_version": VERSION,
            "topic_id": 5,
        }
    )
    run = _run(world)
    by_review: dict[str, list[int]] = {}
    for t in world.bq.rows("topic_assignments"):
        by_review.setdefault(t["id_resena"], []).append(t["segment_index"])
    assert sorted(by_review["h1"]) == [0, 1]
    assert by_review["h2"] == [0] and by_review["done"] == [0]
    assert "pos" not in by_review
    # Solo el texto sin vectores pasó por MiniLM, y sus vectores se guardaron.
    assert world.embedder.calls == [["me cobraron doble comisión"]]
    new = [
        e
        for e in world.bq.rows("segment_embeddings")
        if e["run_id"] == run.run_id
    ]
    assert [e["text_key"] for e in new] == [
        world.text_key("me cobraron doble comisión")
    ]
    assert run.kind.value == "topic_backfill"
    assert run.status.value == "succeeded"
    assert (run.reviews, run.texts) == (2, 2)
    assert world.bq.rows("inference_runs")[-1]["kind"] == "topic_backfill"


def test_batches_never_split_a_text(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    texts = [f"texto largo número {i} pero con otra cláusula" for i in range(3)]
    for i, text in enumerate(texts):
        _history(world, f"r{i}", text)
        _stored(world, text, 2)
    sizes: list[int] = []

    class _Topics:
        def assign(self, segments: Any, embeddings: Any) -> list[int]:
            sizes.append(len(segments))
            return [3] * len(segments)

    monkeypatch.setattr(topics_backfill, "BATCH_SEGMENTS", 1)
    world.clients.engines = type(world.clients.engines)(
        sentiment=world.clients.engines.sentiment,
        embedder=world.clients.engines.embedder,
        topics=lambda path: _Topics(),
    )
    run = _run(world)
    assert sizes == [2, 2, 2]
    assert len(world.bq.rows("topic_assignments")) == 6
    assert run.texts == 3


def test_verification_fails_if_a_negative_stays_without_topic(
    world: Any,
) -> None:
    # Sin texto en el TDS ni vectores: no se puede asignar.
    _prediction(world, "huerfana", "texto que ya no está")
    with pytest.raises(TopicBackfillError, match="1 negatives"):
        _run(world)
    assert world.bq.rows("inference_runs")[-1]["status"] == "failed"


def test_nothing_pending_loads_no_model(world: Any) -> None:
    def boom(path: Any) -> Any:
        raise AssertionError("no model should load")

    world.clients.engines = type(world.clients.engines)(
        sentiment=world.clients.engines.sentiment,
        embedder=boom,
        topics=boom,
    )
    run = _run(world)
    assert run.status.value == "succeeded" and run.reviews == 0
