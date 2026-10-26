"""Lecturas de la landing: ``Protocol``, BigQuery y versión en memoria."""

# ruff: noqa: S608
# Los nombres de tablas salen de ``qualified`` (lista cerrada); los valores
# viajan siempre como parámetros.

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from voc_common import HitlTask, RunKind, RunStatus

from api_backend.bq.names import qualified
from api_backend.bq.reader import BigQueryReader, Param
from api_backend.sections.landing.schemas import RunSummary
from api_backend.settings import ApiSettings

KPI_METRICS = ("neg", "gap_estrellas")
DATA_WINDOW_DAYS = 31


@dataclass(frozen=True)
class KpiRow:
    """Última corrida de un (métrica, banco, periodo) con PPI."""

    metric: str
    bank_id: str
    period: str
    estimate: float
    ci_low: float | None
    ci_high: float | None
    n_gold: int | None
    n_unlabeled: int | None
    model_version: str
    gold_version: str | None


class LandingRepository(Protocol):
    def last_ingestion_at(self) -> datetime | None: ...

    def last_delta(self) -> RunSummary | None: ...

    def last_monitor_at(self) -> datetime | None: ...

    def data_until(self) -> date | None: ...

    def open_alerts(self) -> dict[str, int]: ...

    def ppi_kpis(self) -> list[KpiRow]: ...

    def hitl_pending(self, tasks: Sequence[HitlTask]) -> int: ...


class BigQueryLandingRepository:
    def __init__(self, reader: BigQueryReader, settings: ApiSettings) -> None:
        self._reader = reader
        self._project = settings.gcp_project_id
        self._dataset = settings.bq_dataset_id

    def _table(self, name: str) -> str:
        return qualified(name, self._project, self._dataset)

    def _one(self, sql: str, name: str, params: Sequence[Param] = ()) -> object:
        rows = self._reader.rows(sql, params, name=name, cache=True)
        return next(iter(rows[0].values()), None) if rows else None

    def last_ingestion_at(self) -> datetime | None:
        sql = (
            "SELECT MAX(updated_at) AS v FROM "  # nosec B608
            f"{self._table('ingestion_runs_log_v2')} "
            "WHERE status = 'COMPLETED'"
        )
        return self._one(sql, "landing_last_ingestion")  # type: ignore[return-value]

    def last_delta(self) -> RunSummary | None:
        sql = (
            "SELECT run_id, kind, status, started_at, ended_at, model_version "  # nosec B608
            f"FROM {self._table('inference_runs_current')} "
            "WHERE kind = @kind ORDER BY started_at DESC LIMIT 1"
        )
        rows = self._reader.rows(
            sql,
            [Param("kind", "STRING", RunKind.DELTA.value)],
            name="landing_last_delta",
            cache=True,
        )
        return RunSummary.model_validate(rows[0]) if rows else None

    def last_monitor_at(self) -> datetime | None:
        sql = (
            f"SELECT MAX(computed_at) AS v FROM {self._table('kpi_estimates')}"  # nosec B608
        )
        return self._one(sql, "landing_last_monitor")  # type: ignore[return-value]

    def data_until(self) -> date | None:
        # La tabla, no la vista: una o dos particiones.
        sql = (
            "SELECT DATE(MAX(fecha)) AS v FROM "  # nosec B608
            f"{self._table('review_predictions')} "
            f"WHERE fecha >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), "
            f"INTERVAL {DATA_WINDOW_DAYS} DAY)"
        )
        return self._one(sql, "landing_data_until")  # type: ignore[return-value]

    def open_alerts(self) -> dict[str, int]:
        sql = (
            "SELECT bank_id, COUNT(*) AS n FROM "  # nosec B608
            f"{self._table('drift_alerts_current')} "
            "WHERE status = 'open' GROUP BY bank_id"
        )
        rows = self._reader.rows(
            sql, [], name="landing_open_alerts", cache=True
        )
        return {str(r["bank_id"]): int(r["n"]) for r in rows}  # type: ignore[call-overload]

    def ppi_kpis(self) -> list[KpiRow]:
        sql = (
            "SELECT metric, bank_id, period, estimate, ci_low, ci_high, "  # nosec B608
            "n_gold, n_unlabeled, model_version, gold_version "
            f"FROM {self._table('kpi_estimates')} "
            "WHERE method = 'ppi' AND metric IN UNNEST(@metrics) "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY metric, bank_id, period "
            "ORDER BY computed_at DESC) = 1"
        )
        rows = self._reader.rows(
            sql,
            [Param("metrics", "STRING", KPI_METRICS, array=True)],
            name="landing_ppi_kpis",
            cache=True,
        )
        return [KpiRow(**row) for row in rows]  # type: ignore[arg-type]

    def hitl_pending(self, tasks: Sequence[HitlTask]) -> int:
        if not tasks:
            return 0
        sql = (
            "SELECT COUNT(*) AS n FROM "  # nosec B608
            f"{self._table('hitl_queue')} "
            "WHERE COALESCE(status, 'queued') = 'queued' "
            "AND task IN UNNEST(@tasks)"
        )
        value = self._one(
            sql,
            "landing_hitl_pending",
            [Param("tasks", "STRING", [t.value for t in tasks], array=True)],
        )
        return int(value or 0)  # type: ignore[call-overload]


class InMemoryLandingRepository:
    """Doble de pruebas y de ``PORTAL_DATA=fixtures``."""

    def __init__(
        self,
        *,
        ingestion_at: datetime | None = None,
        delta: RunSummary | None = None,
        monitor_at: datetime | None = None,
        until: date | None = None,
        alerts: dict[str, int] | None = None,
        kpis: Sequence[KpiRow] = (),
        pending: dict[HitlTask, int] | None = None,
    ) -> None:
        self._ingestion_at = ingestion_at
        self._delta = delta
        self._monitor_at = monitor_at
        self._until = until
        self._alerts = alerts or {}
        self._kpis = list(kpis)
        self._pending = pending or {}

    def last_ingestion_at(self) -> datetime | None:
        return self._ingestion_at

    def last_delta(self) -> RunSummary | None:
        return self._delta

    def last_monitor_at(self) -> datetime | None:
        return self._monitor_at

    def data_until(self) -> date | None:
        return self._until

    def open_alerts(self) -> dict[str, int]:
        return dict(self._alerts)

    def ppi_kpis(self) -> list[KpiRow]:
        return list(self._kpis)

    def hitl_pending(self, tasks: Sequence[HitlTask]) -> int:
        return sum(self._pending.get(t, 0) for t in tasks)


def sample_repository(now: datetime | None = None) -> InMemoryLandingRepository:
    """Datos sintéticos para diseñar el portal sin GCP."""
    now = now or datetime.now(UTC)
    month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    banks = {
        "BBVA": (0.18, 0.12, 0.30),
        "AZTECA": (0.31, 0.25, 0.41),
        "SANTANDER": (0.22, 0.16, 0.34),
        "NUBANK": (0.14, 0.08, 0.28),
        "BANORTE": (0.20, 0.14, 0.33),
    }
    kpis: list[KpiRow] = []
    for bank, (neg, _, gap) in banks.items():
        common = dict(
            bank_id=bank,
            period=month,
            n_gold=1200,
            n_unlabeled=18_000,
            model_version="sintetico_v1",
            gold_version="gold_sintetico",
        )
        kpis.append(
            KpiRow(
                metric="neg",
                estimate=neg,
                ci_low=neg - 0.015,
                ci_high=neg + 0.015,
                **common,  # type: ignore[arg-type]
            )
        )
        kpis.append(
            KpiRow(
                metric="gap_estrellas",
                estimate=-gap,
                ci_low=-gap - 0.05,
                ci_high=-gap + 0.05,
                **common,  # type: ignore[arg-type]
            )
        )
    return InMemoryLandingRepository(
        ingestion_at=now - timedelta(hours=5),
        delta=RunSummary(
            run_id="delta-sintetico",
            kind=RunKind.DELTA,
            status=RunStatus.SUCCEEDED,
            started_at=now - timedelta(hours=4),
            ended_at=now - timedelta(hours=3),
            model_version="sintetico_v1",
        ),
        monitor_at=now - timedelta(days=3),
        until=(now - timedelta(days=1)).date(),
        alerts={"AZTECA": 1, "NUBANK": 2},
        kpis=kpis,
        pending={HitlTask.SENTIMENT: 42},
    )
