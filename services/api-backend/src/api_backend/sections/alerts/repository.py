"""Lecturas y escrituras de las alertas: ``Protocol``, BigQuery y memoria."""

# ruff: noqa: S608
# Los nombres de tablas salen de ``qualified`` (lista cerrada); los valores
# viajan siempre como parámetros.

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from voc_common import (
    AlertStatus,
    DriftAlert,
    DriftAlertEvent,
    DriftMetric,
    HitlBoost,
)

from api_backend.bq.names import qualified
from api_backend.bq.reader import BigQueryReader, Param
from api_backend.bq.writer import BigQueryWriter
from api_backend.settings import ApiSettings

ALERT_FIELDS = tuple(DriftAlert.model_fields)


@dataclass(frozen=True)
class AlertRecord:
    """Una alerta con su estado vigente (el último de sus eventos)."""

    alert: DriftAlert
    status: AlertStatus
    status_at: datetime | None


class AlertRepository(Protocol):
    def alerts(
        self, status: AlertStatus | None, banks: Sequence[str]
    ) -> list[AlertRecord]:
        """Las alertas más recientes primero; ``banks`` vacío es todos."""

    def alert(self, alert_id: str) -> AlertRecord | None: ...

    def events(self, alert_id: str) -> list[DriftAlertEvent]:
        """En orden cronológico."""

    def metrics(
        self, bank_id: str, series: str, first: date, last: date
    ) -> list[DriftMetric]:
        """Una fila por mes entre ``first`` y ``last``, el más viejo primero."""

    def boosts(self, boost_ids: Sequence[str]) -> dict[str, HitlBoost]:
        """La fila más reciente de cada subida (la de cierre, si la hay)."""

    def open_by_bank(self) -> dict[str, int]: ...

    def add_event(self, event: DriftAlertEvent) -> bool:
        """``False`` si el ``event_id`` ya existía (un reintento)."""

    def close_boost(self, boost: HitlBoost) -> None:
        """Inserta la fila de cierre (idempotente por subida y motivo)."""


class BigQueryAlertRepository:
    def __init__(
        self,
        reader: BigQueryReader,
        writer: BigQueryWriter,
        settings: ApiSettings,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._project = settings.gcp_project_id
        self._dataset = settings.bq_dataset_id

    def _table(self, name: str) -> str:
        return qualified(name, self._project, self._dataset)

    def _current_sql(self, where: str) -> str:
        columns = ", ".join(f"a.{name}" for name in ALERT_FIELDS)
        return (
            f"SELECT {columns}, COALESCE(a.status, 'open') AS status, "
            "a.status_at "
            f"FROM {self._table('drift_alerts_current')} AS a "
            f"WHERE {where} "
            "ORDER BY a.period DESC, a.bank_id, a.series"
        )

    def alerts(
        self, status: AlertStatus | None, banks: Sequence[str]
    ) -> list[AlertRecord]:
        clauses, params = ["TRUE"], []
        if status is not None:
            clauses.append("COALESCE(a.status, 'open') = @status")
            params.append(Param("status", "STRING", status.value))
        if banks:
            clauses.append("a.bank_id IN UNNEST(@banks)")
            params.append(Param("banks", "STRING", tuple(banks), array=True))
        rows = self._reader.rows(
            self._current_sql(" AND ".join(clauses)),
            params,
            name="alerts_list",
        )
        return [_record(row) for row in rows]

    def alert(self, alert_id: str) -> AlertRecord | None:
        rows = self._reader.rows(
            self._current_sql("a.alert_id = @alert_id"),
            [Param("alert_id", "STRING", alert_id)],
            name="alerts_one",
        )
        return _record(rows[0]) if rows else None

    def events(self, alert_id: str) -> list[DriftAlertEvent]:
        sql = (
            "SELECT event_id, alert_id, status, actor_hash, `at`, note, ticket "
            f"FROM {self._table('drift_alert_events')} "
            "WHERE TRUE AND alert_id = @alert_id ORDER BY `at`, event_id"
        )
        rows = self._reader.rows(
            sql, [Param("alert_id", "STRING", alert_id)], name="alerts_events"
        )
        return [DriftAlertEvent.model_validate(row) for row in rows]

    def metrics(
        self, bank_id: str, series: str, first: date, last: date
    ) -> list[DriftMetric]:
        sql = (
            "SELECT bank_id, period, metric, value, baseline, z, psi, "
            "threshold, alert, drift_policy_version, computed_at "
            f"FROM {self._table('drift_metrics')} "
            "WHERE bank_id = @bank AND metric = @series "
            "AND period BETWEEN @first AND @last "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY period "
            "ORDER BY computed_at DESC) = 1 ORDER BY period"
        )
        rows = self._reader.rows(
            sql,
            [
                Param("bank", "STRING", bank_id),
                Param("series", "STRING", series),
                Param("first", "DATE", first),
                Param("last", "DATE", last),
            ],
            name="alerts_series",
        )
        return [DriftMetric.model_validate(row) for row in rows]

    def boosts(self, boost_ids: Sequence[str]) -> dict[str, HitlBoost]:
        if not boost_ids:
            return {}
        sql = (
            "SELECT boost_id, bank_id, alert_id, risk_policy_version, "
            "coverage, weekly_cap, starts_at, ends_at, ended_reason "
            f"FROM {self._table('hitl_boosts')} "
            "WHERE boost_id IN UNNEST(@ids) "
            # La fila de cierre (con motivo) gana a la de inicio.
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY boost_id "
            "ORDER BY ended_reason IS NULL) = 1"
        )
        rows = self._reader.rows(
            sql,
            [Param("ids", "STRING", tuple(boost_ids), array=True)],
            name="alerts_boosts",
        )
        return {
            str(row["boost_id"]): HitlBoost.model_validate(row) for row in rows
        }

    def open_by_bank(self) -> dict[str, int]:
        sql = (
            "SELECT bank_id, COUNT(*) AS n "
            f"FROM {self._table('drift_alerts_current')} "
            "WHERE COALESCE(status, 'open') = 'open' GROUP BY bank_id"
        )
        rows = self._reader.rows(sql, [], name="alerts_summary")
        return {str(r["bank_id"]): int(r["n"]) for r in rows}  # type: ignore[call-overload]

    def add_event(self, event: DriftAlertEvent) -> bool:
        return self._writer.insert(
            "drift_alert_events", event, key=["event_id"]
        )

    def close_boost(self, boost: HitlBoost) -> None:
        self._writer.insert(
            "hitl_boosts", boost, key=["boost_id", "ended_reason"]
        )


def _record(row: Any) -> AlertRecord:
    alert = DriftAlert.model_validate(
        {name: row[name] for name in ALERT_FIELDS}
    )
    return AlertRecord(
        alert=alert,
        status=AlertStatus(row["status"]),
        status_at=row["status_at"],
    )


@dataclass
class InMemoryAlertRepository:
    """Lo que usan las pruebas y ``PORTAL_DATA=fixtures``."""

    alert_rows: list[DriftAlert]
    event_rows: list[DriftAlertEvent]
    metric_rows: list[DriftMetric] = field(default_factory=list)
    boost_rows: list[HitlBoost] = field(default_factory=list)

    def _record(self, alert: DriftAlert) -> AlertRecord:
        events = self.events(alert.alert_id)
        last = events[-1] if events else None
        return AlertRecord(
            alert=alert,
            status=last.status if last else AlertStatus.OPEN,
            status_at=last.at if last else None,
        )

    def alerts(
        self, status: AlertStatus | None, banks: Sequence[str]
    ) -> list[AlertRecord]:
        records = [self._record(a) for a in self.alert_rows]
        records = [
            r
            for r in records
            if (status is None or r.status is status)
            and (not banks or r.alert.bank_id in banks)
        ]
        return sorted(
            records,
            key=lambda r: (
                -r.alert.period.toordinal(),
                r.alert.bank_id,
                r.alert.series,
            ),
        )

    def alert(self, alert_id: str) -> AlertRecord | None:
        return next(
            (
                self._record(a)
                for a in self.alert_rows
                if a.alert_id == alert_id
            ),
            None,
        )

    def events(self, alert_id: str) -> list[DriftAlertEvent]:
        mine = [e for e in self.event_rows if e.alert_id == alert_id]
        return sorted(mine, key=lambda e: e.at)  # estable: respeta el orden

    def metrics(
        self, bank_id: str, series: str, first: date, last: date
    ) -> list[DriftMetric]:
        rows = [
            m
            for m in self.metric_rows
            if m.bank_id == bank_id
            and m.metric == series
            and first <= m.period <= last
        ]
        return sorted(rows, key=lambda m: m.period)

    def boosts(self, boost_ids: Sequence[str]) -> dict[str, HitlBoost]:
        out: dict[str, HitlBoost] = {}
        for boost in self.boost_rows:
            if boost.boost_id not in boost_ids:
                continue
            seen = out.get(boost.boost_id)
            if seen is None or (
                seen.ended_reason is None and boost.ended_reason is not None
            ):
                out[boost.boost_id] = boost
        return out

    def open_by_bank(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self.alerts(AlertStatus.OPEN, []):
            bank = record.alert.bank_id
            counts[bank] = counts.get(bank, 0) + 1
        return counts

    def add_event(self, event: DriftAlertEvent) -> bool:
        if any(e.event_id == event.event_id for e in self.event_rows):
            return False
        self.event_rows.append(event)
        return True

    def close_boost(self, boost: HitlBoost) -> None:
        if not any(
            b.boost_id == boost.boost_id
            and b.ended_reason == boost.ended_reason
            for b in self.boost_rows
        ):
            self.boost_rows.append(boost)
