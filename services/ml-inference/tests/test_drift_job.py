"""Monitor de deriva: entrada, alertas por banco, contexto y cierres."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from ml_inference.bq_io import StagingMergeWriter
from ml_inference.monitor.drift_job import (
    ASPECTS_SQL,
    INPUT_SQL,
    TOPICS_SQL,
    BqDriftSource,
    MonitorClients,
    MonthlyInput,
    close_boosts,
    evaluate_bank,
    last_closed_month,
    month_range,
    run_drift,
)
from ml_inference.seed import drift_thresholds
from voc_common.operations_v3 import DriftAlertMessage
from voc_common.policies import DriftPolicy, HitlBoost, RiskPolicy

ACTOR = "a" * 64
NOW = datetime(2026, 7, 8, 6, tzinfo=UTC)
MONTHS = month_range("2024-01", "2026-06")
HIST = [10, 20, 50, 100, 60, 40, 15, 5]


def policy(bank: str) -> DriftPolicy:
    return DriftPolicy(
        drift_policy_version=f"drift_{bank}_v1",
        bank_id=bank,
        template_version="drift_policy_template_v1",
        valid_from=NOW - timedelta(days=30),
        thresholds=drift_thresholds(),
        baseline_months=12,
        min_baseline_months=6,
        min_rows_per_month=200,
        entry_months=12,
        set_by_hash=ACTOR,
        reason="prueba",
    )


def risk(boost: bool = True) -> RiskPolicy:
    extra: dict[str, Any] = (
        {
            "drift_boost_coverage": 0.8,
            "drift_boost_days": 14,
            "drift_boost_weekly_cap": 500,
        }
        if boost
        else {}
    )
    return RiskPolicy(
        policy_version="risk_policy_v1",
        valid_from=NOW - timedelta(days=30),
        hitl_signal="prob_max",
        hitl_target_coverage=0.9,
        hitl_threshold=0.7,
        model_version="robertuito_sentiment_v1",
        monitor_sample_size=300,
        monitor_frequency="quarterly",
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


def series(bank: str, spikes: dict[str, float] | None = None, rows=300):
    """Series estables (|z| < 1) con picos en el último mes."""
    out = []
    for i, period in enumerate(MONTHS):
        wobble = 0.5 * ((i % 3) - 1)
        values: dict[str, float | None] = {
            "mean_words": 10 + wobble,
            "neg_share": 0.4 + wobble / 50,
            "family_FA": 0.2 + wobble / 50,
            "flag_update_share": 0.1 + wobble / 50,
        }
        if period == MONTHS[-1]:
            values |= spikes or {}
        out.append(MonthlyInput(bank, period, rows, values, HIST))
    return out


@dataclass
class FakeSource:
    banks: list[DriftPolicy]
    data: list[MonthlyInput]
    risk_row: RiskPolicy | None = None
    done_rows: dict[str, set[str]] = field(default_factory=dict)
    boosts: list[HitlBoost] = field(default_factory=list)
    dismissed: set[str] = field(default_factory=set)

    def policies(self) -> list[DriftPolicy]:
        return self.banks

    def risk_policy(self) -> RiskPolicy | None:
        return self.risk_row

    def monthly(self, before: datetime) -> list[MonthlyInput]:
        assert before == datetime(2026, 7, 1, tzinfo=UTC)
        return self.data

    def done(self) -> dict[str, set[str]]:
        return self.done_rows

    def open_boosts(self) -> list[HitlBoost]:
        return self.boosts

    def dismissed_alerts(self) -> set[str]:
        return self.dismissed


def clients(source: FakeSource, bq: Any) -> tuple[MonitorClients, Any, list]:
    sent: list[DriftAlertMessage] = []
    writer = StagingMergeWriter(bq, "p.ds")  # type: ignore[arg-type]
    return MonitorClients(source, writer, sent.append, "test"), bq, sent


def test_last_closed_month() -> None:
    assert last_closed_month(NOW) == "2026-06"
    assert last_closed_month(datetime(2026, 1, 3, tzinfo=UTC)) == "2025-12"


def test_spike_alerts_only_its_bank_with_event_message_and_boost(
    fake_bq: Any,
) -> None:
    source = FakeSource(
        [policy("bbva"), policy("banorte")],
        series("bbva", {"mean_words": 30.0})
        + series("banorte", {"family_FA": 0.9, "flag_update_share": 0.9}),
        risk(),
    )
    c, bq, sent = clients(source, fake_bq)
    alerts = run_drift(None, c, NOW)  # type: ignore[arg-type]

    assert [(a.bank_id, a.series) for a in alerts] == [("bbva", "mean_words")]
    alert = alerts[0]
    assert alert.period == date(2026, 6, 1) and alert.threshold == 4.0
    events = bq.rows("drift_alert_events")
    assert [(e["alert_id"], e["status"]) for e in events] == [
        (alert.alert_id, "open")
    ]
    assert [m.alert_id for m in sent] == [alert.alert_id]
    boosts = bq.rows("hitl_boosts")
    assert [(b["bank_id"], b["coverage"]) for b in boosts] == [("bbva", 0.8)]
    assert alert.hitl_boost_id == boosts[0]["boost_id"]
    assert sent[0].hitl_boost_id == alert.hitl_boost_id

    metrics = bq.rows("drift_metrics")
    context = [
        m for m in metrics if m["metric"] in {"family_FA", "flag_update_share"}
    ]
    assert context and all(not m["alert"] for m in context)
    assert all(m["threshold"] is None for m in context)
    spiked = next(
        m
        for m in context
        if m["bank_id"] == "banorte"
        and m["metric"] == "family_FA"
        and m["period"] == "2026-06-01"
    )
    assert spiked["z"] > 4
    # Meses desde el siguiente al de entrada (2024-12) hasta el último cerrado.
    periods = {m["period"] for m in metrics if m["bank_id"] == "bbva"}
    assert min(periods) == "2025-01-01" and max(periods) == "2026-06-01"
    # Sin datos de vocabulario, la serie no se escribe.
    assert not any(m["metric"] == "out_of_vocabulary_share" for m in metrics)


def test_second_run_writes_nothing_new(fake_bq: Any) -> None:
    source = FakeSource(
        [policy("bbva")], series("bbva", {"mean_words": 30.0}), risk()
    )
    c, bq, _ = clients(source, fake_bq)
    run_drift(None, c, NOW)  # type: ignore[arg-type]
    source.done_rows = {"bbva": set(MONTHS)}
    assert run_drift(None, c, NOW) == []  # type: ignore[arg-type]


def test_bank_before_its_entry_month_never_alerts() -> None:
    data = series("nuevo", {"mean_words": 30.0}, rows=150)
    outcome = evaluate_bank(policy("nuevo"), data, set(), "2026-06", NOW)
    assert outcome.metrics == [] and outcome.alerts == []
    assert (
        evaluate_bank(policy("nuevo"), [], set(), "2026-06", NOW).metrics == []
    )


def test_without_boost_rules_the_alert_is_kept_without_boost(
    fake_bq: Any,
) -> None:
    source = FakeSource(
        [policy("bbva")], series("bbva", {"mean_words": 30.0}), risk(False)
    )
    c, bq, sent = clients(source, fake_bq)
    alerts = run_drift(None, c, NOW)  # type: ignore[arg-type]
    assert len(alerts) == 1 and alerts[0].hitl_boost_id is None
    assert bq.rows("hitl_boosts") == [] and len(sent) == 1


def test_active_boost_is_reused(fake_bq: Any) -> None:
    active = HitlBoost(
        boost_id="boost_previo",
        bank_id="bbva",
        risk_policy_version="risk_policy_v1",
        coverage=0.8,
        weekly_cap=500,
        starts_at=NOW - timedelta(days=2),
        ends_at=NOW + timedelta(days=5),
    )
    source = FakeSource(
        [policy("bbva")],
        series("bbva", {"mean_words": 30.0, "neg_share": 0.9}),
        risk(),
        boosts=[active],
    )
    c, bq, _ = clients(source, fake_bq)
    alerts = run_drift(None, c, NOW)  # type: ignore[arg-type]
    assert len(alerts) == 2
    assert {a.hitl_boost_id for a in alerts} == {"boost_previo"}
    assert bq.rows("hitl_boosts") == []


def test_history_is_measured_but_only_the_last_month_alerts(
    fake_bq: Any,
) -> None:
    data = series("bbva", {"mean_words": 30.0})
    # Pico también en un mes viejo: queda marcado, sin alerta ni mensaje.
    old = next(i for i, m in enumerate(data) if m.period == "2025-09")
    data[old] = MonthlyInput(
        "bbva",
        "2025-09",
        data[old].rows,
        data[old].values | {"neg_share": 0.9},
        HIST,
    )
    source = FakeSource([policy("bbva")], data, risk())
    c, bq, sent = clients(source, fake_bq)
    alerts = run_drift(None, c, NOW)  # type: ignore[arg-type]
    assert [(a.period, a.series) for a in alerts] == [
        (date(2026, 6, 1), "mean_words")
    ]
    assert len(sent) == 1 and len(bq.rows("hitl_boosts")) == 1
    flagged = {
        (m["period"], m["metric"])
        for m in bq.rows("drift_metrics")
        if m["alert"]
    }
    assert flagged == {
        ("2025-09-01", "neg_share"),
        ("2026-06-01", "mean_words"),
    }


def test_length_shift_alerts_by_psi() -> None:
    data = series("bbva")
    last = data[-1]
    data[-1] = MonthlyInput(
        "bbva",
        last.period,
        last.rows,
        last.values,
        [200, 50, 20, 10, 5, 5, 5, 5],
    )
    outcome = evaluate_bank(policy("bbva"), data, set(), "2026-06", NOW)
    psi_alerts = [
        a for a in outcome.alerts if a.series == "length_distribution"
    ]
    assert len(psi_alerts) == 1 and psi_alerts[0].value >= 0.25
    stable = [
        m
        for m in outcome.metrics
        if m.metric == "length_distribution" and m.period < date(2026, 6, 1)
    ]
    assert stable and all(m.psi == pytest.approx(0.0) for m in stable)


def test_message_has_no_text_fields() -> None:
    fields = set(DriftAlertMessage.model_fields)
    assert fields == {
        "alert_id",
        "bank_id",
        "period",
        "series",
        "value",
        "threshold",
        "drift_policy_version",
        "hitl_boost_id",
        "triggered_at",
    }


def _boost(
    boost_id: str, ends: datetime, alert: str | None = None
) -> HitlBoost:
    return HitlBoost(
        boost_id=boost_id,
        bank_id="bbva",
        alert_id=alert,
        risk_policy_version="risk_policy_v1",
        coverage=0.8,
        weekly_cap=500,
        starts_at=ends - timedelta(days=14),
        ends_at=ends,
    )


def test_close_boosts_inserts_closing_rows(fake_bq: Any) -> None:
    expired = _boost("b1", NOW - timedelta(hours=1))
    running = _boost("b2", NOW + timedelta(days=3))
    dismissed = _boost("b3", NOW + timedelta(days=3), alert="drift_x")
    closed = _boost("b4", NOW - timedelta(days=1)).model_copy(
        update={"ended_reason": "expired"}
    )
    source = FakeSource(
        [],
        [],
        boosts=[expired, running, dismissed, closed],
        dismissed={"drift_x"},
    )
    c, bq, _ = clients(source, fake_bq)
    rows = close_boosts(c, NOW)
    assert [(r.boost_id, r.ended_reason) for r in rows] == [
        ("b1", "expired"),
        ("b3", "alert_closed"),
    ]
    assert len(bq.rows("hitl_boosts")) == 2


class _Client:
    """Cliente de BigQuery que responde por fragmentos del SQL."""

    def __init__(self, answers: dict[str, list[dict[str, Any]]]) -> None:
        self.answers = answers
        self.sql: list[str] = []

    def create_table(self, table: Any) -> None:
        self.created = table.table_id

    def load_table_from_json(self, rows: list, table_id: str, **_: Any) -> Any:
        self.vocab_rows = rows
        return _Job([])

    def delete_table(self, table: str, **_: Any) -> None:
        self.deleted = table

    def query(self, sql: str, job_config: Any = None, **_: Any) -> Any:
        self.sql.append(sql)
        rows = next((v for k, v in self.answers.items() if k in sql), [])
        return _Job(rows)


@dataclass
class _Job:
    rows: list[dict[str, Any]]

    def result(self, timeout: float | None = None) -> list[dict[str, Any]]:
        return self.rows


def test_bq_source_reads_and_merges_monthly_inputs() -> None:
    p = policy("bbva").model_dump()
    row = {
        "bank_id": "bbva",
        "period": "2026-06",
        "n_rows": 300,
        "mean_words": 10,
        "neg_share": None,
        **{f"b{i}": n for i, n in enumerate(HIST)},
    }
    boost = _boost("b1", NOW).model_dump()
    client = _Client(
        {
            "topic_noise_share": [
                {
                    "bank_id": "bbva",
                    "period": "2026-06",
                    "topic_noise_share": 0.36,
                    "topic_unaligned_share": None,
                }
            ],
            "drift_policy_current": [p],
            "risk_policy_current": [risk().model_dump()],
            "review_predictions_current": [row],
            "review_aspects": [
                {"bank_id": "bbva", "period": "2026-06", "family_FA": 0.2}
            ],
            "FROM `p.ds.drift_metrics`": [
                {"bank_id": "bbva", "period": "2026-05"}
            ],
            "hitl_boosts": [boost],
            "drift_alerts_current": [{"alert_id": "drift_x"}],
        }
    )
    source = BqDriftSource(client, "p.ds")
    assert source.policies()[0].bank_id == "bbva"
    assert source.risk_policy() is not None
    [month] = source.monthly(NOW)
    assert month.rows == 300 and month.histogram == HIST
    assert month.values == {
        "mean_words": 10.0,
        "neg_share": None,
        "family_FA": 0.2,
        "topic_noise_share": 0.36,
        "topic_unaligned_share": None,
    }
    assert source.done() == {"bbva": {"2026-05"}}
    assert [b.boost_id for b in source.open_boosts()] == ["b1"]
    assert source.dismissed_alerts() == {"drift_x"}
    assert BqDriftSource(_Client({}), "p.ds").risk_policy() is None


def test_bq_source_adds_out_of_vocabulary_share() -> None:
    row = {
        "bank_id": "bbva",
        "period": "2026-06",
        "n_rows": 300,
        **{f"b{i}": n for i, n in enumerate(HIST)},
    }
    client = _Client(
        {
            "out_of_vocabulary_share": [
                {
                    "bank_id": "bbva",
                    "period": "2026-06",
                    "out_of_vocabulary_share": 0.03,
                }
            ],
            "review_predictions_current": [row],
        }
    )
    source = BqDriftSource(
        client, "p.ds", "p.ds.tds", frozenset({"hola"}), clock=lambda: NOW
    )
    [month] = source.monthly(NOW)
    assert month.values["out_of_vocabulary_share"] == 0.03
    oov_sql = next(q for q in client.sql if "UNNEST(SPLIT" in q)
    assert "`p.ds.tds`" in oov_sql and "`p.ds._vocab_20260708060000`" in oov_sql
    assert client.vocab_rows == [{"word": "hola"}]
    assert client.deleted == "p.ds._vocab_20260708060000"


def test_generated_sql_uses_constants_and_parameters() -> None:
    assert "COUNTIF(palabras > 60) AS b7" in INPUT_SQL
    assert "@before" in INPUT_SQL and "@predictable" in INPUT_SQL
    assert (
        "family_OT" in ASPECTS_SQL and "GROUP BY bank_id, period" in ASPECTS_SQL
    )


def test_topic_series_are_stored_and_never_alert() -> None:
    p = policy("bbva")
    assert p.thresholds.z["topic_noise_share"] is None
    assert p.thresholds.z["topic_unaligned_share"] is None
    months = [
        MonthlyInput(
            "bbva",
            m,
            300,
            {
                "topic_noise_share": 0.9 if m == "2026-06" else 0.3,
                "topic_unaligned_share": 0.1 + (i % 3) / 100,
            },
        )
        for i, m in enumerate(MONTHS)
    ]
    outcome = evaluate_bank(p, months, set(), "2026-06", NOW)
    shares = [m for m in outcome.metrics if m.metric.startswith("topic_")]
    assert {m.metric for m in shares} == {
        "topic_noise_share",
        "topic_unaligned_share",
    }
    assert all(m.threshold is None and not m.alert for m in shares)
    assert outcome.alerts == []


def test_topic_sql_measures_noise_and_alignment_of_the_current_version() -> (
    None
):
    assert "topic_model_current" in TOPICS_SQL and "@before" in TOPICS_SQL
    assert "COUNTIF(s.topic_id = -1) AS noise" in TOPICS_SQL
    assert "ARRAY_LENGTH(c.families) > 0 AS aligned" in TOPICS_SQL
    assert "sentiment = 'NEG' AND palabras >= 2" in TOPICS_SQL
