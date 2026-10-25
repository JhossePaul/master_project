"""Delta diario: sus criterios con BigQuery, Gemini y modelos falsos."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ml_inference.bq_io import BqWriteError
from ml_inference.delta import peak_memory_mib, run_delta
from ml_inference.state import NoPromotedModel

NOW = datetime(2026, 11, 4, 9, 30, tzinfo=UTC)
MODEL = "robertuito_sentiment_v1"


def _run(world: Any, now: datetime = NOW):
    return run_delta(world.settings, world.clients, now, lexicon=world.lexicon)


def _by_id(world: Any, table: str) -> dict[str, dict]:
    return {r["id_resena"]: r for r in world.bq.rows(table)}


def test_one_inference_per_text_key_propagated_to_its_rows(world: Any) -> None:
    tds = world.bq.rows("sanitized_reviews_tds")
    tds += [
        world.tds_row("r1", "la app no abre"),
        world.tds_row("r2", "la app no abre"),
    ]
    run = _run(world)
    assert world.sentiment.calls == [["la app no abre"]]
    rows = _by_id(world, "review_predictions")
    assert rows["r1"]["p_neg"] == rows["r2"]["p_neg"]
    assert rows["r1"]["text_key"] == world.text_key("la app no abre")
    assert run.reviews == 2 and run.texts == 1
    assert run.status.value == "succeeded"


def test_excluded_and_lexicon_rows(world: Any) -> None:
    world.bq.rows("sanitized_reviews_tds").extend(
        [
            world.tds_row("e1", "😡"),
            world.tds_row("l1", "Excelente"),
            world.tds_row("h1", "hola"),
        ]
    )
    _run(world)
    rows = _by_id(world, "review_predictions")
    assert rows["e1"]["eligibility_code"] == "TNSS_NO_TEXT_CONTENT"
    assert rows["e1"]["sentiment"] == "NO_PREDICTED"
    assert rows["e1"]["p_neg"] is None and rows["e1"]["confidence"] is None
    assert rows["l1"]["label_source"] == "RULE_BASED"
    assert rows["l1"]["sentiment"] == "POS"
    assert rows["h1"]["eligibility_code"] == "TNSS_SINGLE_WORD"
    # Ningún texto fue al modelo: no se carga RoBERTuito.
    assert world.sentiment.calls == []
    assert all(r["model_version"] == MODEL for r in rows.values())


def test_requires_hitl_with_the_policy_and_the_boost_only_for_its_bank(
    world: Any,
) -> None:
    world.bq.rows("hitl_boosts").append(
        {
            "boost_id": "boost-1",
            "bank_id": "NUBANK",
            "alert_id": "alert-1",
            "risk_policy_version": "risk_policy_v1",
            "coverage": 0.8,
            "weekly_cap": 10,
            "starts_at": NOW - timedelta(days=1),
            "ends_at": NOW + timedelta(days=13),
            "ended_reason": None,
        }
    )
    world.bq.rows("sanitized_reviews_tds").extend(
        [
            world.tds_row("b1", "esto me da duda", "BBVA"),
            world.tds_row("n1", "esto me da duda", "NUBANK"),
            # 0.97 pasa el umbral de la política (0.9) y no el de la subida.
            world.tds_row("n2", "app malo malo", "NUBANK"),
            world.tds_row("b2", "app malo malo", "BBVA"),
        ]
    )
    _run(world)
    rows = _by_id(world, "review_predictions")
    assert rows["b1"]["requires_hitl"] and rows["b1"]["hitl_boost_id"] is None
    assert rows["n1"]["requires_hitl"]
    assert rows["n1"]["hitl_boost_id"] == "boost-1"
    assert rows["n2"]["requires_hitl"] and not rows["b2"]["requires_hitl"]
    assert rows["b1"]["risk_policy_version"] == "risk_policy_v1"
    items = _by_id(world, "hitl_items")
    assert items["b1"]["reason"] == "low_confidence"
    assert items["n1"]["reason"] == "drift_boost"
    assert items["n1"]["boost_id"] == "boost-1"
    assert items["b1"]["display_mode"] == "assisted"
    assert len(world.bq.rows("hitl_events")) == 3
    explained = {r["text_key"] for r in world.bq.rows("review_explanations")}
    assert explained == {
        world.text_key("esto me da duda"),
        world.text_key("app malo malo"),
    }
    assert {r["source"] for r in world.bq.rows("review_explanations")} == {
        "precomputed_hitl"
    }


def test_weekly_cap_limits_new_cases(world: Any) -> None:
    world.bq.rows("risk_policy")[-1]["hitl_weekly_cap"] = 1
    world.bq.rows("sanitized_reviews_tds").extend(
        [world.tds_row("a", "duda uno"), world.tds_row("b", "duda dos")]
    )
    _run(world)
    assert len(world.bq.rows("hitl_items")) == 1
    flagged = [
        r for r in world.bq.rows("review_predictions") if r["requires_hitl"]
    ]
    assert len(flagged) == 2


def test_policy_for_another_model_marks_nothing(world: Any) -> None:
    world.bq.rows("risk_policy")[-1]["model_version"] = "otro_modelo"
    world.bq.rows("sanitized_reviews_tds").append(world.tds_row("a", "duda"))
    _run(world)
    row = world.bq.rows("review_predictions")[0]
    assert row["requires_hitl"] is False and row["risk_policy_version"] is None
    assert world.bq.rows("hitl_items") == []


def test_second_run_inserts_nothing(world: Any) -> None:
    world.bq.rows("sanitized_reviews_tds").extend(
        [
            world.tds_row("r1", "la app no abre pero ya"),
            world.tds_row("r2", "duda total"),
        ]
    )
    _run(world)
    sizes = {t: len(rows) for t, rows in world.bq.tables.items()}
    second = _run(world, NOW + timedelta(hours=1))
    assert second.reviews == 0
    for table, size in sizes.items():
        if table != "inference_runs":
            assert len(world.bq.rows(table)) == size, table
    assert len(world.bq.rows("inference_runs")) == 2


def test_staging_is_deleted_even_if_merge_fails(world: Any) -> None:
    world.bq.rows("sanitized_reviews_tds").append(
        world.tds_row("r1", "la app no abre")
    )
    world.bq.fail_merge = True
    with pytest.raises(BqWriteError):
        _run(world)
    assert world.bq.deleted and not world.bq.staging


def test_failed_run_is_recorded(world: Any) -> None:
    world.bq.rows("sanitized_reviews_tds").append(
        world.tds_row("r1", "la app no abre")
    )

    def boom(*_: object) -> None:
        raise RuntimeError("modelo roto")

    world.clients.engines = type(world.clients.engines)(
        sentiment=boom,
        embedder=world.clients.engines.embedder,
        topics=world.clients.engines.topics,
    )
    with pytest.raises(RuntimeError, match="roto"):
        _run(world)
    run = world.bq.rows("inference_runs")[-1]
    assert run["status"] == "failed"


def test_text_omitted_by_gemini_stays_pending(world: Any) -> None:
    world.bq.rows("sanitized_reviews_tds").extend(
        [
            world.tds_row("ok", "la app no abre nunca"),
            world.tds_row("om", "app malo omitir esto"),
            world.tds_row("pos", "muy buena la app"),
            world.tds_row("one", "malo"),
        ]
    )
    _run(world)
    aspects = _by_id(world, "review_aspects")
    assert set(aspects) == {"ok"}
    assert aspects["ok"]["families"] == ["AC"]
    assert aspects["ok"]["flag_update"] is True
    assert aspects["ok"]["prompt_version"] == "aspects_v2_1"
    assert aspects["ok"]["sentiment_model_version"] == MODEL
    calls = world.gemini.calls
    _run(world, NOW + timedelta(days=1))
    assert world.gemini.calls > calls
    assert set(_by_id(world, "review_aspects")) == {"ok"}


def test_known_labels_are_reused_without_calling_gemini(world: Any) -> None:
    world.bq.rows("sanitized_reviews_tds").append(
        world.tds_row("a", "la app no abre")
    )
    _run(world)
    calls = world.gemini.calls
    world.bq.rows("sanitized_reviews_tds").append(
        world.tds_row("b", "la app no abre")
    )
    _run(world, NOW + timedelta(hours=1))
    assert world.gemini.calls == calls
    assert set(_by_id(world, "review_aspects")) == {"a", "b"}


def _old_label(world: Any, id_resena: str, text: str) -> None:
    world.bq.rows("review_aspects").append(
        {
            "id_resena": id_resena,
            "bank_id": "BBVA",
            "text_key": world.text_key(text),
            "fecha": NOW - timedelta(days=400),
            "families": ["TR"],
            "flag_update": False,
            "flag_security": True,
            "praise": False,
            "prompt_version": "aspects_v1",
            "llm_model": "gemini-viejo",
            "guideline_version": "v1",
            "sentiment_model_version": MODEL,
            "run_id": "backfill",
            "labeled_at": NOW - timedelta(days=400),
        }
    )


def test_gemini_never_relabels_a_text_with_families_of_another_prompt(
    world: Any,
) -> None:
    _old_label(world, "viejo", "la app no abre")
    world.bq.rows("sanitized_reviews_tds").extend(
        [
            # La misma reseña, ya etiquetada con el prompt anterior.
            world.tds_row("viejo", "la app no abre"),
            # Otra reseña con el mismo texto: copia la etiqueta anterior.
            world.tds_row("nuevo", "la app no abre"),
        ]
    )
    _run(world)
    assert world.gemini.calls == 0
    aspects = [
        a for a in world.bq.rows("review_aspects") if a["id_resena"] == "nuevo"
    ]
    assert len(aspects) == 1
    copied = aspects[0]
    assert copied["prompt_version"] == "aspects_v1"
    assert copied["guideline_version"] == "v1"
    assert copied["llm_model"] == "gemini-viejo"
    assert copied["families"] == ["TR"] and copied["flag_security"] is True
    assert copied["sentiment_model_version"] == MODEL
    # La reseña ya etiquetada no gana una fila con el prompt vigente.
    assert [
        a["prompt_version"]
        for a in world.bq.rows("review_aspects")
        if a["id_resena"] == "viejo"
    ] == ["aspects_v1"]


def test_only_never_labeled_texts_go_to_gemini(world: Any) -> None:
    _old_label(world, "viejo", "la app no abre")
    world.bq.rows("sanitized_reviews_tds").extend(
        [
            world.tds_row("a", "la app no abre"),
            world.tds_row("b", "app malo hoy"),
        ]
    )
    sent: list[str] = []
    generate = world.gemini.generate_content

    def spy(*, model: str, contents: str, config: Any):
        sent.extend(line.split("\t", 1)[1] for line in contents.splitlines())
        return generate(model=model, contents=contents, config=config)

    world.gemini.generate_content = spy
    _run(world)
    assert sent == ["app malo hoy"]
    prompts = {
        a["id_resena"]: a["prompt_version"]
        for a in world.bq.rows("review_aspects")
    }
    assert prompts == {
        "viejo": "aspects_v1",
        "a": "aspects_v1",
        "b": "aspects_v2_1",
    }


def test_without_gemini_client_aspects_wait(world: Any) -> None:
    world.clients.genai = None
    world.bq.rows("sanitized_reviews_tds").append(
        world.tds_row("a", "la app no abre")
    )
    _run(world)
    assert world.bq.rows("review_aspects") == []


def test_embeddings_one_row_per_bank_and_month_reusing_vectors(
    world: Any,
) -> None:
    october = datetime(2026, 10, 20, tzinfo=UTC)
    world.bq.rows("sanitized_reviews_tds").extend(
        [
            world.tds_row("a", "la app no abre", "BBVA"),
            world.tds_row("b", "la app no abre", "NUBANK"),
            world.tds_row("c", "la app no abre", "BBVA", october),
            world.tds_row("d", "", "BBVA"),
        ]
    )
    _run(world)
    embeddings = world.bq.rows("text_embeddings")
    assert {(e["bank_id"], str(e["mes"])) for e in embeddings} == {
        ("BBVA", "2026-11-01"),
        ("NUBANK", "2026-11-01"),
        ("BBVA", "2026-10-01"),
    }
    assert len(embeddings[0]["embedding"]) == 384
    # El primer llamado es el de los embeddings (el segundo, el de tópicos).
    assert world.embedder.calls[0] == ["la app no abre"]


def test_topics_one_row_per_segment(world: Any) -> None:
    world.bq.rows("sanitized_reviews_tds").append(
        world.tds_row("a", "la app no abre nunca pero el cajero sí funciona")
    )
    _run(world)
    topics = sorted(
        world.bq.rows("topic_assignments"), key=lambda r: r["segment_index"]
    )
    assert [t["topic_id"] for t in topics] == [3, -1]
    assert {t["topic_model_version"] for t in topics} == {"topics_v1"}


def test_without_topic_model_topics_wait(world: Any) -> None:
    world.bq.tables["topic_model_versions"] = []
    world.bq.rows("sanitized_reviews_tds").append(
        world.tds_row("a", "la app no abre")
    )
    _run(world)
    assert world.bq.rows("topic_assignments") == []


def test_needs_a_promoted_model(world: Any) -> None:
    world.bq.rows("model_versions")[0]["status"] = "candidate"
    world.bq.rows("model_versions")[0]["promoted_at"] = None
    world.bq.rows("model_versions")[0]["promoted_by_hash"] = None
    with pytest.raises(NoPromotedModel):
        _run(world)


def test_artifacts_are_downloaded_once(world: Any) -> None:
    world.bq.rows("sanitized_reviews_tds").append(
        world.tds_row("a", "la app no abre")
    )
    _run(world)
    sentiment = [p for p in world.storage.listed if "/sentiment/" in p]
    assert sentiment == [f"ml_artifacts/sentiment/{MODEL}/"]
    world.bq.rows("sanitized_reviews_tds").append(
        world.tds_row("b", "otro malo")
    )
    _run(world, NOW + timedelta(hours=1))
    assert [p for p in world.storage.listed if "/sentiment/" in p] == sentiment


def test_peak_memory_is_positive() -> None:
    assert peak_memory_mib() > 0
