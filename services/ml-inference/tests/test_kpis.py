"""KPI: corrección del oro, meses pendientes, versiones del oro y escritura."""

from datetime import UTC, datetime
from typing import Any

import numpy as np
import pytest
from ml_inference.bq_io import StagingMergeWriter
from ml_inference.monitor.kpis import (
    METRICS,
    CorpusCell,
    GoldRow,
    KpiJob,
    compute_kpis,
    corpus_cells,
    expected_series,
    gold_rows,
    months_to_compute,
    ppi_kpis,
    raw_kpis,
)
from voc_nlp.ppi import gap_stars

NOW = datetime(2026, 7, 8, 6, tzinfo=UTC)


def biased_gold(bank: str = "BBVA", n: int = 100) -> list[GoldRow]:
    """30 % de texto NEG; el modelo dice NEU en 10 de esos 30."""
    rows = []
    for i in range(n):
        label = "NEG" if i < 30 else ("NEU" if i < 60 else "POS")
        predicted = "NEU" if i < 10 else label
        stars = {"NEG": 1, "NEU": 3, "POS": 5}[label]
        rows.append(GoldRow(bank, stars, label, predicted, 1.0))
    return rows


def cell(counts: dict[tuple[int, str], int]) -> CorpusCell:
    keys = sorted(counts)
    return CorpusCell(
        stars=tuple(s for s, _ in keys),
        predicted=tuple(p for _, p in keys),
        counts=tuple(counts[k] for k in keys),
    )


# 20 % de NEG predicho en el mes, como el 20 % predicho en el oro.
MONTH = cell({(1, "NEG"): 200, (3, "NEU"): 400, (5, "POS"): 400})


def by_metric(rows: list[Any]) -> dict[str, Any]:
    return {r.metric: r for r in rows}


def test_metrics_are_the_cockpit_kpis() -> None:
    assert METRICS[:4] == ("neg", "gap_estrellas", "texto_peor", "texto_mejor")
    assert len(METRICS) == 13


def test_ppi_corrects_the_bias_measured_in_the_gold() -> None:
    raw = by_metric(raw_kpis("BBVA", "2026-06", MONTH, "m1", NOW))
    ppi = by_metric(
        ppi_kpis("BBVA", "2026-06", biased_gold(), MONTH, "m1", "g1", NOW)
    )
    assert raw["neg"].estimate == pytest.approx(0.2)
    assert raw["neg"].method == "raw" and raw["neg"].ci_low is None
    assert raw["neg"].n_unlabeled == 1000 and raw["neg"].gold_version is None
    # 0.3 + λ · (0.2 − 0.2): el modelo subestima las NEG en un tercio.
    neg = ppi["neg"]
    assert neg.estimate == pytest.approx(0.3)
    assert neg.ci_low < 0.3 < neg.ci_high
    assert (neg.n_gold, neg.n_unlabeled) == (100, 1000)
    assert (neg.gold_version, neg.model_version) == ("g1", "m1")


def test_gap_matches_the_shared_gap_stars() -> None:
    gold = biased_gold()
    w = np.linspace(1.0, 3.0, len(gold))
    gold = [
        GoldRow(g.bank_id, g.stars, g.label, g.predicted, x)
        for g, x in zip(gold, w, strict=True)
    ]
    ppi = by_metric(ppi_kpis("BBVA", "2026-06", gold, MONTH, "m1", "g1", NOW))
    stars_u, pred_u = MONTH.expand()
    expected = gap_stars(
        [g.stars for g in gold],
        [g.label for g in gold],
        [g.predicted for g in gold],
        stars_u,
        pred_u,
        w,
    )
    assert ppi["gap_estrellas"].estimate == pytest.approx(expected.value)
    assert (ppi["gap_estrellas"].ci_low, ppi["gap_estrellas"].ci_high) == (
        pytest.approx(expected.ci[0]),
        pytest.approx(expected.ci[1]),
    )


def test_compute_only_wanted_months_and_banks_with_gold() -> None:
    corpus = {
        ("BBVA", "2026-06"): MONTH,
        ("BBVA", "2026-05"): MONTH,
        ("NUBANK", "2026-06"): MONTH,
        ("NUBANK", "2026-04"): cell({}),
    }
    rows = compute_kpis(
        ["2026-06", "2026-04"], {"g1": biased_gold()}, corpus, "m1", NOW
    )
    series = {(r.bank_id, r.period, r.method) for r in rows}
    assert series == {
        ("BBVA", "2026-06", "raw"),
        ("BBVA", "2026-06", "ppi"),
        ("NUBANK", "2026-06", "raw"),
    }
    assert len(rows) == 3 * len(METRICS)


def test_months_are_recent_plus_those_missing_a_series() -> None:
    corpus = {
        ("BBVA", "2026-03"): MONTH,
        ("BBVA", "2026-06"): MONTH,
        ("BBVA", "2026-07"): MONTH,
        ("NUBANK", "2026-04"): MONTH,
        ("NUBANK", "2026-02"): cell({}),
    }
    expected = expected_series(corpus, {"g1": biased_gold()})
    assert ("NUBANK", "2026-04", "ppi", "g1") not in expected
    assert ("BBVA", "2026-03", "ppi", "g1") in expected
    assert months_to_compute(NOW, expected, set()) == [
        "2026-03",
        "2026-04",
        "2026-06",
        "2026-07",
    ]
    # Con todo hecho quedan el mes en curso y el anterior.
    assert months_to_compute(NOW, expected, expected) == ["2026-06", "2026-07"]
    # Un oro nuevo vuelve a pedir la historia de sus bancos.
    with_hitl = expected_series(
        corpus, {"g1": biased_gold(), "g2": biased_gold()}
    )
    assert months_to_compute(NOW, with_hitl, expected) == [
        "2026-03",
        "2026-06",
        "2026-07",
    ]


def test_gold_without_a_model_class_counts_as_neutral() -> None:
    rows = gold_rows(
        [
            {
                "gold_version": "g1",
                "label": "NEG",
                "weight": 2.5,
                "bank_id": "BBVA",
                "estrellas": 2,
                "sentiment": "NO_PREDICTED",
            },
            {
                "gold_version": "g1",
                "label": "POS",
                "weight": 1.0,
                "bank_id": "BBVA",
                "estrellas": 5,
                "sentiment": "POS",
            },
        ]
    )
    assert rows == {
        "g1": [
            GoldRow("BBVA", 2, "NEG", "NEU", 2.5),
            GoldRow("BBVA", 5, "POS", "POS", 1.0),
        ]
    }


def test_corpus_counts_expand_to_reviews() -> None:
    cells = corpus_cells(
        [
            {
                "bank_id": "B",
                "period": "2026-06",
                "estrellas": 5,
                "sentiment": "POS",
                "n": 2,
            },
            {
                "bank_id": "B",
                "period": "2026-06",
                "estrellas": 1,
                "sentiment": "NEG",
                "n": 1,
            },
        ]
    )
    (only,) = cells.values()
    assert only.size == 3
    assert only.expand() == ([1, 5, 5], ["NEG", "POS", "POS"])


# -- Job ---------------------------------------------------------------------


class _Job:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def result(self, timeout: float | None = None) -> list[dict[str, Any]]:
        return self.rows


class _Client:
    """Lecturas del Job; ``done`` sale de lo que ya escribió el writer."""

    def __init__(self, fake_bq: Any, gold: bool = True) -> None:
        self.fake_bq, self.gold = fake_bq, gold
        self.params: list[dict[str, Any]] = []

    def query(self, sql: str, job_config: Any = None, **_: Any) -> Any:
        params = {p.name: p.value for p in job_config.query_parameters}
        self.params.append(params)
        if "FROM `p.ds.kpi_estimates`" in sql:
            return _Job(
                [
                    {
                        k: r[k]
                        for k in ("bank_id", "period", "method", "gold_version")
                    }
                    for r in self.fake_bq.rows("kpi_estimates")
                    if r["model_version"] == params["model_version"]
                ]
            )
        if "COUNT(*)" in sql:
            return _Job(
                [
                    {
                        "bank_id": "BBVA",
                        "period": p,
                        "estrellas": s,
                        "sentiment": c,
                        "n": n,
                    }
                    for p in ("2026-01", "2026-06", "2026-07")
                    for s, c, n in (
                        (1, "NEG", 20),
                        (3, "NEU", 40),
                        (5, "POS", 40),
                    )
                ]
            )
        if not self.gold:
            return _Job([])
        return _Job(
            [
                {
                    "gold_version": "g1",
                    "label": g.label,
                    "weight": g.weight,
                    "bank_id": g.bank_id,
                    "estrellas": g.stars,
                    "sentiment": g.predicted,
                }
                for g in biased_gold()
            ]
        )


def test_job_fills_history_then_recomputes_recent_months(fake_bq: Any) -> None:
    client = _Client(fake_bq)
    writer = StagingMergeWriter(fake_bq, "p.ds")
    job = KpiJob(client, writer, "p.ds", "test")
    assert job.run("m1", NOW) == 3 * 2 * len(METRICS)
    later = NOW.replace(day=15)
    assert job.run("m1", later) == 2 * 2 * len(METRICS)
    rows = fake_bq.rows("kpi_estimates")
    last = max(r["computed_at"] for r in rows)
    assert {r["period"] for r in rows if r["computed_at"] == last} == {
        "2026-06",
        "2026-07",
    }
    assert {p["model_version"] for p in client.params if p} == {"m1"}


def test_job_without_gold_writes_raw_once(fake_bq: Any) -> None:
    writer = StagingMergeWriter(fake_bq, "p.ds")
    job = KpiJob(_Client(fake_bq, gold=False), writer, "p.ds", "test")
    assert job.run("m1", NOW) == 3 * len(METRICS)
    assert job.run("m1", NOW.replace(day=15)) == 2 * len(METRICS)
    assert {r["method"] for r in fake_bq.rows("kpi_estimates")} == {"raw"}
