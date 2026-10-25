"""Backfill de familias: estima sin gastar, respeta el tope y se retoma."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ml_inference.aspects_backfill import estimate, run_aspects_backfill

NOW = datetime(2026, 11, 4, 9, 30, tzinfo=UTC)
MODEL = "robertuito_sentiment_v1"


def _history(world: Any, id_resena: str, text: str, sentiment: str = "NEG"):
    world.bq.rows("sanitized_reviews_tds").append(
        world.tds_row(id_resena, text, fecha=NOW - timedelta(days=300))
    )
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


def _old_label(world: Any, id_resena: str, text: str) -> None:
    world.bq.rows("review_aspects").append(
        {
            "id_resena": id_resena,
            "bank_id": "BBVA",
            "text_key": world.text_key(text),
            "fecha": NOW - timedelta(days=300),
            "families": ["TR"],
            "flag_update": False,
            "flag_security": False,
            "praise": False,
            "prompt_version": "aspects_v1",
            "llm_model": "gemini-viejo",
            "guideline_version": "v1",
            "sentiment_model_version": MODEL,
            "run_id": "backfill",
            "labeled_at": NOW - timedelta(days=300),
        }
    )


def _corpus(world: Any) -> None:
    _history(world, "a1", "la app no abre nunca")
    _history(world, "a2", "la app no abre nunca")
    _old_label(world, "a1", "la app no abre nunca")
    _history(world, "b", "me cobraron doble comisión")
    _history(world, "c", "el cajero se tragó mi tarjeta")
    _history(world, "pos", "muy buena la app", sentiment="POS")


def test_without_approval_it_only_estimates(world: Any) -> None:
    _corpus(world)
    found = estimate(world.settings, world.bq)
    assert (found.prompt_version, found.texts) == ("aspects_v2_1", 3)
    assert found.usd == pytest.approx(3 / 1000 * 0.092)
    assert world.gemini.calls == 0
    assert len(world.bq.rows("review_aspects")) == 1
    assert world.bq.rows("inference_runs") == []


def test_labels_every_pending_text_with_the_current_prompt(world: Any) -> None:
    _corpus(world)
    run = run_aspects_backfill(world.settings, world.bq, world.gemini, 5.0, NOW)
    assert sorted(world.gemini.sent) == sorted(
        [
            "el cajero se tragó mi tarjeta",
            "la app no abre nunca",
            "me cobraron doble comisión",
        ]
    )
    current = {
        a["id_resena"]
        for a in world.bq.rows("review_aspects")
        if a["prompt_version"] == "aspects_v2_1"
    }
    assert current == {"a1", "a2", "b", "c"}
    # La fila del prompt anterior se conserva (solo inserción).
    assert any(
        a["prompt_version"] == "aspects_v1"
        for a in world.bq.rows("review_aspects")
    )
    assert (run.kind.value, run.status.value) == (
        "aspect_backfill",
        "succeeded",
    )
    assert (run.reviews, run.texts) == (4, 3)
    assert world.bq.rows("inference_runs")[-1]["kind"] == "aspect_backfill"


def test_stops_at_the_cap_and_a_second_run_resumes(world: Any) -> None:
    _corpus(world)
    world.gemini.prompt_tokens = 10_000  # $0.0075 por llamada
    settings = world.settings.model_copy(update={"aspects_batch_size": 1})
    first = run_aspects_backfill(settings, world.bq, world.gemini, 0.02, NOW)
    assert world.gemini.calls == 2 and first.texts == 2
    assert first.cost_usd == pytest.approx(0.015)
    assert first.cost_usd <= 0.02 and first.status.value == "succeeded"
    labeled = set(world.gemini.sent)
    world.gemini.sent.clear()
    second = run_aspects_backfill(
        settings, world.bq, world.gemini, 1.0, NOW + timedelta(hours=1)
    )
    assert second.texts == 1 and not set(world.gemini.sent) & labeled
    assert estimate(settings, world.bq).texts == 0


def test_cap_must_be_positive(world: Any) -> None:
    with pytest.raises(ValueError, match="positive"):
        run_aspects_backfill(world.settings, world.bq, world.gemini, 0, NOW)
