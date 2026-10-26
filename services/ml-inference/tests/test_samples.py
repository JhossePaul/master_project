"""Muestras del monitor: siempre blind, reproducibles y sin duplicar."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ml_inference.bq_io import StagingMergeWriter
from ml_inference.monitor.samples import (
    Candidate,
    SampleJob,
    create_agreement_sample,
    create_monitor_sample,
    draw,
    last_closed_period,
    period_bounds,
    period_of,
    sample_seed,
)
from voc_common.analytics_codes import DisplayMode, HitlReason
from voc_common.policies import RiskPolicy

NOW = datetime(2026, 7, 8, 6, tzinfo=UTC)
ACTOR = "a" * 64


def candidates(n: int) -> list[Candidate]:
    return [
        Candidate(
            id_resena=f"r{i:04d}",
            bank_id="bbva" if i % 2 else "banorte",
            text_key=f"{i:064x}",
            sentiment="NEG",
            p_neg=0.8,
            p_neu=0.1,
            p_pos=0.1,
            model_version="m1",
            risk_policy_version="risk_policy_v1",
        )
        for i in range(n)
    ]


def risk(agreement: tuple[int, str] | None = None, freq: str = "quarterly"):  # noqa: E501
    extra: dict[str, Any] = (
        {
            "human_agreement_sample_size": agreement[0],
            "human_agreement_frequency": agreement[1],
        }
        if agreement
        else {}
    )
    return RiskPolicy(
        policy_version="risk_policy_v1",
        valid_from=NOW - timedelta(days=30),
        hitl_signal="prob_max",
        hitl_target_coverage=0.9,
        hitl_threshold=0.7,
        model_version="m1",
        monitor_sample_size=5,
        monitor_frequency=freq,
        topic_refit_frequency="quarterly",
        retrain_kappa_floor=0.89,
        warn_correction_rate=0.28,
        warn_agreement_floor=0.94,
        agreement_sample_weekly=500,
        families_exact_floor=0.53,
        families_min_prevalence=0.05,
        set_by_hash=ACTOR,
        reason="prueba",
        **extra,
    )


def test_periods() -> None:
    assert period_of(NOW.date(), "quarterly") == "2026Q3"
    assert period_of(NOW.date(), "monthly") == "2026-07"
    assert last_closed_period(NOW, "quarterly") == "2026Q2"
    assert (
        last_closed_period(datetime(2026, 1, 5, tzinfo=UTC), "quarterly")
        == "2025Q4"
    )
    assert last_closed_period(NOW, "monthly") == "2026-06"
    assert period_bounds("2026Q4") == (
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2027, 1, 1, tzinfo=UTC),
    )
    assert period_bounds("2026-12")[1] == datetime(2027, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="frequency"):
        period_of(NOW.date(), "weekly")


def test_monitor_sample_is_blind_and_reproducible() -> None:
    pool = candidates(100)
    items = create_monitor_sample(pool, "2026Q2", 10, NOW)
    assert len(items) == 10 and len({i.item_id for i in items}) == 10
    assert all(i.display_mode is DisplayMode.BLIND for i in items)
    assert all(i.reason is HitlReason.MONITOR_SAMPLE for i in items)
    assert all(i.item_id.startswith("monitor_sample:2026Q2:") for i in items)
    assert items[0].predicted == {
        "label": "NEG",
        "p_neg": 0.8,
        "p_neu": 0.1,
        "p_pos": 0.1,
    }
    # Mismo sorteo con la misma semilla aunque cambie el orden de llegada.
    again = create_monitor_sample(list(reversed(pool)), "2026Q2", 10, NOW)
    assert [i.item_id for i in again] == [i.item_id for i in items]
    other = create_monitor_sample(pool, "2026Q3", 10, NOW)
    assert {i.id_resena for i in other} != {i.id_resena for i in items}


def test_small_pool_takes_everything_and_seed_is_stable() -> None:
    assert (
        len(draw(candidates(3), 10, HitlReason.MONITOR_SAMPLE, "2026Q2")) == 3
    )
    assert sample_seed(HitlReason.MONITOR_SAMPLE, "2026Q2") == sample_seed(
        HitlReason.MONITOR_SAMPLE, "2026Q2"
    )
    assert sample_seed(HitlReason.MONITOR_SAMPLE, "2026Q2") != sample_seed(
        HitlReason.AGREEMENT_SAMPLE, "2026Q2"
    )


def test_agreement_sample_needs_the_policy_values() -> None:
    assert create_agreement_sample(candidates(50), risk(), NOW) == []
    items = create_agreement_sample(candidates(50), risk((4, "monthly")), NOW)
    assert len(items) == 4
    assert all(i.display_mode is DisplayMode.BLIND for i in items)
    assert all(i.item_id.startswith("agreement_sample:2026-06:") for i in items)


class _Client:
    def __init__(self, existing: set[str], pool: list[Candidate]) -> None:
        self.existing, self.pool = existing, pool
        self.params: list[dict[str, Any]] = []

    def query(self, sql: str, job_config: Any = None, **_: Any) -> Any:
        params = {p.name: p.value for p in job_config.query_parameters}
        self.params.append(params)
        if "COUNT(*)" in sql:
            n = int(any(e.startswith(params["prefix"]) for e in self.existing))
            return _Job([{"n": n}])
        return _Job([vars(c) for c in self.pool])


class _Job:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def result(self, timeout: float | None = None) -> list[dict[str, Any]]:
        return self.rows


def job(fake_bq: Any, existing: set[str]) -> tuple[SampleJob, _Client]:
    client = _Client(existing, candidates(40))
    writer = StagingMergeWriter(fake_bq, "p.ds")
    return SampleJob(client, writer, "p.ds", "test"), client


def test_job_creates_missing_samples_with_queued_events(fake_bq: Any) -> None:
    sample, client = job(fake_bq, set())
    out = sample.run(risk((3, "quarterly")), "m1", NOW)
    assert out == {"monitor_sample": 5, "agreement_sample": 3}
    assert len(fake_bq.rows("hitl_items")) == 8
    events = fake_bq.rows("hitl_events")
    assert len(events) == 8 and {e["status"] for e in events} == {"queued"}
    query = next(p for p in client.params if "start" in p)
    assert query["model_version"] == "m1"
    assert query["start"] == datetime(2026, 4, 1, tzinfo=UTC)


def test_job_skips_existing_periods_and_unknown_frequencies(
    fake_bq: Any,
) -> None:
    done = {"monitor_sample:2026Q2:x", "agreement_sample:2026-06:x"}
    sample, _ = job(fake_bq, done)
    assert sample.run(risk((3, "monthly")), "m1", NOW) == {
        "monitor_sample": 0,
        "agreement_sample": 0,
    }
    sample, _ = job(fake_bq, set())
    # Filas anteriores a la validación pueden traer otra frecuencia: el Job las
    # sigue sorteando sin romperse (``model_copy`` no revalida).
    legacy = risk().model_copy(
        update={
            "human_agreement_sample_size": 3,
            "human_agreement_frequency": "weekly",
            "monitor_frequency": "yearly",
        }
    )
    out = sample.run(legacy, "m1", NOW)
    assert out == {"monitor_sample": 0, "agreement_sample": 0}
    assert sample.run(None, "m1", NOW)["monitor_sample"] == 0
