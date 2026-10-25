"""Calidad: κ bajo el piso, corrección alta, familias en los bordes y avisos."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ml_inference.bq_io import StagingMergeWriter
from ml_inference.monitor.quality import (
    FAMILY_BASELINE,
    QualityJob,
    correction_rate,
    families_validation,
    gemini_agreement,
    iso_week,
    kappa_monitor,
    last_closed_week,
)
from voc_common.analytics_codes import RetrainTrigger
from voc_common.policies import RiskPolicy

NOW = datetime(2026, 7, 8, 6, tzinfo=UTC)


def policy() -> RiskPolicy:
    return RiskPolicy(
        policy_version="risk_policy_v1",
        valid_from=NOW - timedelta(days=30),
        hitl_signal="prob_max",
        hitl_target_coverage=0.9,
        hitl_threshold=0.7,
        model_version="m1",
        monitor_sample_size=300,
        monitor_frequency="quarterly",
        topic_refit_frequency="quarterly",
        retrain_kappa_floor=0.89,
        warn_correction_rate=0.28,
        warn_agreement_floor=0.94,
        agreement_sample_weekly=500,
        families_exact_floor=0.53,
        families_min_prevalence=0.05,
        set_by_hash="a" * 64,
        reason="prueba",
    )


def labels(n_wrong: int, n: int = 100) -> tuple[list[str], list[str]]:
    gold = ["NEG", "NEU", "POS"] * (n // 3) + ["NEG"] * (n % 3)
    pred = list(gold)
    for i in range(n_wrong):
        pred[i] = "POS" if gold[i] != "POS" else "NEG"
    return pred, gold


def test_kappa_below_the_floor_asks_for_retraining() -> None:
    pred, gold = labels(20)
    row = kappa_monitor(pred, gold, "2026Q2", "m1", policy(), NOW, n_boot=200)
    assert row.value < 0.89 and row.status == "retrain"
    assert row.ci_low <= row.value <= row.ci_high
    assert row.n == 100 and row.threshold == 0.89
    pred, gold = labels(2)
    ok = kappa_monitor(pred, gold, "2026Q2", "m1", policy(), NOW, n_boot=200)
    assert ok.value >= 0.89 and ok.status == "ok"


def test_correction_rate_of_30_percent_is_a_warning() -> None:
    row = correction_rate(
        [True] * 30 + [False] * 70, "2026-W28", "m1", policy(), NOW
    )
    assert row.value == pytest.approx(0.30) and row.status == "warning"
    assert 0 <= row.ci_low < 0.30 < row.ci_high <= 1
    low = correction_rate(
        [True] * 25 + [False] * 75, "2026-W28", "m1", policy(), NOW
    )
    assert low.status == "ok"


def fam(n_same: int, n: int = 100, family: str = "FA", gold_share: int = 20):
    """``gold_share`` textos con ``family``; Gemini acierta ``n_same``."""
    gold = [
        frozenset({family}) if i < gold_share else frozenset() for i in range(n)
    ]
    gemini = list(gold)
    for i in range(n - n_same):
        gemini[-1 - i] = frozenset({"UX"})
    return gold, gemini


def test_families_accept_at_the_exact_agreement_floor() -> None:
    gold, gemini = fam(53)
    row, failing = families_validation(
        gold, gemini, "g", "p", policy(), NOW, n_boot=100
    )
    assert row.value == pytest.approx(0.53) and failing == []
    assert (
        row.status == "ok"
        and row.llm_model == "g"
        and row.period == "2026-07-08"
    )


def test_families_reject_below_the_exact_agreement_floor() -> None:
    gold, gemini = fam(52)
    row, _ = families_validation(
        gold, gemini, "g", "p", policy(), NOW, n_boot=100
    )
    assert row.value == pytest.approx(0.52) and row.status == "rejected"


def test_family_below_its_baseline_rejects_only_if_prevalent() -> None:
    # FA presente en 20 textos; Gemini solo marca 4 → κ bajo 0.4385.
    gold = [frozenset({"FA"})] * 20 + [frozenset()] * 80
    gemini = [frozenset({"FA"})] * 4 + [frozenset()] * 96
    row, failing = families_validation(
        gold, gemini, "g", "p", policy(), NOW, n_boot=100
    )
    assert row.value == pytest.approx(0.84) and failing == ["FA"]
    assert row.status == "rejected"
    # Con 4 % de prevalencia la familia no se juzga.
    gold = [frozenset({"FA"})] * 4 + [frozenset()] * 96
    gemini = [frozenset()] * 100
    row, failing = families_validation(
        gold, gemini, "g", "p", policy(), NOW, n_boot=100
    )
    assert failing == [] and row.status == "ok"
    assert set(FAMILY_BASELINE) == {
        "AC",
        "TR",
        "DI",
        "PR",
        "AT",
        "FA",
        "LE",
        "CO",
        "DV",
        "UX",
        "OT",
    }


def test_iso_week() -> None:
    assert iso_week(NOW) == "2026-W28"


class _Client:
    def __init__(self, answers: dict[str, list[dict[str, Any]]]) -> None:
        self.answers = answers
        self.params: list[dict[str, Any]] = []

    def query(self, sql: str, job_config: Any = None, **_: Any) -> Any:
        self.params.append(
            {p.name: p.value for p in job_config.query_parameters}
        )
        return _Job(next((v for k, v in self.answers.items() if k in sql), []))


class _Job:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def result(self, timeout: float | None = None) -> list[dict[str, Any]]:
        return self.rows


def sample_rows(n_wrong: int, missing: int = 0) -> list[dict[str, Any]]:
    pred, gold = labels(n_wrong)
    return [
        {
            "item_id": f"monitor_sample:2026Q2:r{i}",
            "predicted_label": p,
            "validated_label": None if i < missing else g,
        }
        for i, (p, g) in enumerate(zip(pred, gold, strict=True))
    ]


class _Jobs:
    def __init__(self, busy: bool = False) -> None:
        self.executed: list[tuple[str, list[str]]] = []
        self.busy = busy

    def execute(self, job: str, args: Any) -> str:
        self.executed.append((job, list(args)))
        return "operations/1"

    def running(self, job: str) -> bool:
        return self.busy


def job(
    fake_bq: Any,
    answers: dict,
    labeler: Any = None,
    sentiment: Any = None,
    jobs: Any = None,
):
    sent: list[Any] = []
    writer = StagingMergeWriter(fake_bq, "p.ds")
    q = QualityJob(
        _Client(answers),
        writer,
        "p.ds",
        "p.ds.tds",
        sent.append,
        "t",
        family_labeler=labeler,
        sentiment_labeler=sentiment,
        jobs=jobs,
    )
    return q, sent


def test_job_measures_writes_and_publishes_warnings(fake_bq: Any) -> None:
    gold = [
        {
            "text_key": f"{i:064x}",
            "families": ["FA"] if i < 20 else [],
            "texto_sanitizado": "x",
        }
        for i in range(100)
    ]

    def labeler(items: Any) -> dict[str, frozenset[str]]:
        return {
            k: frozenset({"FA"}) if int(k, 16) < 20 else frozenset()
            for k, _ in items
        }

    q, sent = job(
        fake_bq,
        {
            "FROM `p.ds.model_quality`": [],
            "monitor_sample": sample_rows(20),
            "low_confidence": [{"outcome": "corrected"}] * 3
            + [{"outcome": "confirmed"}] * 7,
            "gold_labels": gold,
        },
        labeler,
    )
    rows = q.run(policy(), "m1", NOW)
    assert [(r.signal, r.status) for r in rows] == [
        ("kappa_monitor", "retrain"),
        ("correction_rate", "warning"),
        ("families_validation", "ok"),
    ]
    assert len(fake_bq.rows("model_quality")) == 3
    assert [m.signal for m in sent] == ["kappa_monitor", "correction_rate"]
    since = next(p for p in q.client.params if "since" in p)
    assert since["until"] - since["since"] == timedelta(weeks=4)


def test_job_waits_and_skips_what_is_measured(fake_bq: Any) -> None:
    measured = [
        {
            "model_version": "m1",
            "llm_model": None,
            "prompt_version": None,
            "signal": "correction_rate",
            "period": "2026-W28",
        },
        {
            "model_version": None,
            "llm_model": "gemini-3.6-flash",
            "prompt_version": "aspects_v2_1",
            "signal": "families_validation",
            "period": "2026-01-01",
        },
    ]
    q, sent = job(
        fake_bq,
        {
            "FROM `p.ds.model_quality`": measured,
            "monitor_sample": sample_rows(0, missing=5),
        },
        labeler=lambda items: pytest.fail("already validated"),
    )
    assert q.run(policy(), "m1", NOW) == [] and sent == []
    assert q.run(None, "m1", NOW) == []


def test_job_retries_families_when_gemini_misses_texts(fake_bq: Any) -> None:
    gold = [{"text_key": "k1", "families": [], "texto_sanitizado": "x"}] * 2
    q, _ = job(fake_bq, {"gold_labels": gold}, labeler=lambda items: {})
    assert q.run(policy(), "m1", NOW) == []
    q, _ = job(fake_bq, {}, labeler=lambda items: {})
    assert q.run(policy(), "m1", NOW) == []


def test_gemini_agreement_skips_not_evaluable_and_warns_on_four_weeks() -> None:
    model = ["NEG"] * 95 + ["POS"] * 5 + ["NEU"] * 3
    gemini = ["NEG"] * 95 + ["NEG"] * 5 + ["NA"] * 3
    row = gemini_agreement(model, gemini, [], "2026-W27", "m1", policy(), NOW)
    assert row is not None and row.n == 100
    assert row.value == pytest.approx(0.95) and row.status == "ok"
    assert row.signal == "gemini_agreement" and row.threshold == 0.94
    # Semana buena, pero las 3 anteriores bajan el combinado de 4 semanas.
    low = [(0.90, 100)] * 3
    warned = gemini_agreement(
        model, gemini, low, "2026-W27", "m1", policy(), NOW
    )
    assert warned.value == pytest.approx(0.95) and warned.status == "warning"
    # Solo cuentan 3 semanas anteriores.
    many = [(0.95, 100)] * 3 + [(0.0, 1000)]
    assert (
        gemini_agreement(model, gemini, many, "w", "m1", policy(), NOW).status
        == "ok"
    )
    assert (
        gemini_agreement(["NEG"], ["NA"], [], "w", "m1", policy(), NOW) is None
    )


def test_last_closed_week() -> None:
    week, start, end = last_closed_week(NOW)
    assert week == "2026-W27"
    assert start == datetime(2026, 6, 29, tzinfo=UTC)
    assert end == datetime(2026, 7, 6, tzinfo=UTC)


def test_job_measures_the_weekly_agreement(fake_bq: Any) -> None:
    sampled = [
        {"text_key": f"k{i}", "sentiment": "NEG", "texto_sanitizado": "x"}
        for i in range(10)
    ]

    def sentiment(items: Any) -> dict[str, str]:
        # Gemini deja un texto sin etiqueta y discrepa en otro.
        labels = {k: "NEG" for k, _ in items[:-1]}
        labels["k0"] = "POS"
        return labels

    q, sent = job(
        fake_bq,
        {
            "signal = 'gemini_agreement'": [{"value": 0.8, "n": 100}],
            "FARM_FINGERPRINT": sampled,
        },
        sentiment=sentiment,
    )
    [row] = q.run(policy(), "m1", NOW)
    assert row.signal == "gemini_agreement" and row.period == "2026-W27"
    assert row.n == 9 and row.value == pytest.approx(8 / 9)
    assert row.status == "warning" and [m.signal for m in sent] == [
        "gemini_agreement"
    ]
    params = next(p for p in q.client.params if "seed" in p)
    assert params["seed"] == "gemini_agreement:2026-W27"
    assert params["size"] == 500
    previous = next(p for p in q.client.params if "weeks" in p)
    assert previous == {"model_version": "m1", "week": "2026-W27", "weeks": 3}


def test_job_skips_agreement_without_texts(fake_bq: Any) -> None:
    q, _ = job(fake_bq, {}, sentiment=lambda items: pytest.fail("no texts"))
    assert q.run(policy(), "m1", NOW) == []


def _retrain_answers(trainings: int = 0) -> dict:
    return {
        "FROM `p.ds.model_quality`": [],
        "monitor_sample": sample_rows(20),
        "AS trainings": [{"trainings": trainings}],
    }


@pytest.mark.parametrize("trigger", [None, RetrainTrigger.MANUAL])
def test_retrain_in_manual_mode_only_warns(fake_bq: Any, trigger: Any) -> None:
    jobs = _Jobs()
    q, sent = job(fake_bq, _retrain_answers(), jobs=jobs)
    p = policy().model_copy(update={"retrain_trigger": trigger})
    rows = q.run(p, "m1", NOW)
    assert ("kappa_monitor", "retrain") in [(r.signal, r.status) for r in rows]
    assert [m.signal for m in sent] == ["kappa_monitor"]
    assert jobs.executed == []


def test_retrain_in_auto_mode_launches_training(fake_bq: Any) -> None:
    jobs = _Jobs()
    q, _ = job(fake_bq, _retrain_answers(), jobs=jobs)
    q.run(
        policy().model_copy(update={"retrain_trigger": RetrainTrigger.AUTO}),
        "m1",
        NOW,
    )
    assert jobs.executed == [("voc-ml-training", ["train"])]
    since = next(p for p in q.client.params if set(p) == {"since"})["since"]
    assert since == datetime(2026, 7, 1, tzinfo=UTC)


@pytest.mark.parametrize(("trainings", "busy"), [(1, False), (0, True)])
def test_auto_retrain_at_most_once_per_quarter(
    fake_bq: Any, trainings: int, busy: bool
) -> None:
    jobs = _Jobs(busy=busy)
    q, _ = job(fake_bq, _retrain_answers(trainings), jobs=jobs)
    q.run(
        policy().model_copy(update={"retrain_trigger": RetrainTrigger.AUTO}),
        "m1",
        NOW,
    )
    assert jobs.executed == []


def test_auto_retrain_without_job_runner_only_warns(fake_bq: Any) -> None:
    q, sent = job(fake_bq, _retrain_answers())
    q.run(
        policy().model_copy(update={"retrain_trigger": RetrainTrigger.AUTO}),
        "m1",
        NOW,
    )
    assert [m.signal for m in sent] == ["kappa_monitor"]
