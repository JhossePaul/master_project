"""Tasas de alerta contra la línea base del análisis de escala."""

from typing import Any

import ml_inference.__main__ as cli
import pytest
from ml_inference.monitor.drift_rates import (
    CEILING,
    REFERENCE,
    TOLERANCE,
    Rate,
    rates,
    report,
)


def test_rates_per_year_and_tolerance() -> None:
    found = rates(
        [
            {
                "metric": "mean_words",
                "bank_id": "BBVA",
                "months": 60,
                "alerts": 5,
            },
            {
                "metric": "mean_words",
                "bank_id": "BBVA",
                "months": 60,
                "alerts": 0,
            },
            {
                "metric": "neg_share",
                "bank_id": "NUBANK",
                "months": 24,
                "alerts": 4,
            },
            {
                "metric": "family_FA",
                "bank_id": "BBVA",
                "months": 12,
                "alerts": 0,
            },
        ]
    )
    by_key = {(r.series, r.bank_id): r for r in found}
    words = by_key[("mean_words", "BBVA")]
    assert (words.months, words.alerts, words.per_year) == (120, 5, 0.5)
    assert words.reference == 1.0 and words.ok
    neg = by_key[("neg_share", "NUBANK")]
    assert neg.per_year == 2.0 and not neg.ok
    # Sin referencia, se juzga contra el techo del análisis.
    other = by_key[("family_FA", "BBVA")]
    assert other.reference is None and other.ok
    assert not Rate("x", "B", 12, 3, None).ok
    assert Rate("x", "B", 0, 0, 0.0).per_year == 0.0
    assert TOLERANCE == 0.5 and CEILING == 1.4
    assert all(len(v) == 5 for v in REFERENCE.values())


class _Job:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def result(self, timeout: float | None = None) -> list[dict]:
        return self.rows


class _Client:
    def __init__(self, rows: list[dict]) -> None:
        self.rows, self.sql = rows, ""

    def query(self, sql: str, **_: Any) -> _Job:
        self.sql = sql
        return _Job(self.rows)


def test_report_reads_only_series_with_threshold() -> None:
    client = _Client(
        [
            {
                "metric": "mean_words",
                "bank_id": "AZTECA",
                "months": 12,
                "alerts": 1,
            }
        ]
    )
    (rate,) = report(client, "p.ds")
    assert rate.per_year == 1.0 and rate.ok
    assert "threshold IS NOT NULL" in client.sql
    assert "`p.ds.drift_metrics`" in client.sql


@pytest.mark.parametrize(("alerts", "code"), [(1, 0), (6, 1)])
def test_drift_rates_command(
    monkeypatch: pytest.MonkeyPatch, alerts: int, code: int
) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "p")
    monkeypatch.setenv("GCS_RAW_DATALAKE_BUCKET", "b")
    rows = [
        {
            "metric": "mean_words",
            "bank_id": "BBVA",
            "months": 12,
            "alerts": alerts,
        }
    ]
    monkeypatch.setattr(cli, "_clients", lambda s: (_Client(rows), "gcs"))
    assert cli.main(["drift-rates"]) == code
