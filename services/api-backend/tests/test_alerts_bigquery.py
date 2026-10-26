"""Alertas sobre BigQuery, con un lector y un escritor falsos."""

from datetime import UTC, date, datetime
from typing import Any

from api_backend.sections.alerts.repository import BigQueryAlertRepository
from api_backend.sections.alerts.sample import sample_repository
from api_backend.settings import ApiSettings
from voc_common import AlertStatus, BoostEndReason, DriftAlert

T0 = datetime(2026, 10, 26, 12, tzinfo=UTC)
SAMPLE = sample_repository(T0)
ALERT = SAMPLE.alert_rows[0]
EVENT = SAMPLE.event_rows[0]
METRIC = SAMPLE.metric_rows[0]
BOOST = SAMPLE.boost_rows[0]


class FakeReader:
    def __init__(self, *batches: list[dict[str, Any]]) -> None:
        self.batches = list(batches)
        self.sql: list[str] = []
        self.params: list[Any] = []

    def rows(self, sql: str, params: Any, **_: object) -> list[dict[str, Any]]:
        self.sql.append(sql)
        self.params.append({p.name: p.value for p in params})
        return self.batches.pop(0) if self.batches else []


class FakeWriter:
    def __init__(self) -> None:
        self.inserted: list[tuple[str, Any, list[str]]] = []

    def insert(self, table: str, row: Any, key: list[str]) -> bool:
        self.inserted.append((table, row, key))
        return True


def bq_repo(
    *batches: list[dict[str, Any]],
) -> tuple[BigQueryAlertRepository, FakeReader, FakeWriter]:
    reader, writer = FakeReader(*batches), FakeWriter()
    settings = ApiSettings.model_validate(
        {"gcp_project_id": "p", "bq_dataset_id": "d", "iap_audience": "/a"}
    )
    repo = BigQueryAlertRepository(reader, writer, settings)  # type: ignore[arg-type]
    return repo, reader, writer


def current_row(alert: DriftAlert, status: str = "open") -> dict[str, Any]:
    return {**alert.model_dump(), "status": status, "status_at": T0}


def test_alertas_filtra_en_sql_y_con_parametros() -> None:
    alert = ALERT
    repo, reader, _ = bq_repo([current_row(alert, "confirmed")])

    records = repo.alerts(AlertStatus.CONFIRMED, ["BBVA", "NUBANK"])

    assert records[0].alert == alert
    assert records[0].status is AlertStatus.CONFIRMED
    sql = reader.sql[0]
    assert "`p.d.drift_alerts_current`" in sql
    assert "COALESCE(a.status, 'open') = @status" in sql
    assert "a.bank_id IN UNNEST(@banks)" in sql
    assert reader.params[0] == {
        "status": "confirmed",
        "banks": ("BBVA", "NUBANK"),
    }

    repo, reader, _ = bq_repo()
    repo.alerts(None, [])
    assert "@status" not in reader.sql[0] and "@banks" not in reader.sql[0]


def test_una_alerta_sin_eventos_cuenta_como_abierta() -> None:
    alert = ALERT
    row = {**alert.model_dump(), "status": "open", "status_at": None}
    repo, reader, _ = bq_repo([row], [])

    record = repo.alert(alert.alert_id)

    assert record is not None
    assert record.status is AlertStatus.OPEN and record.status_at is None
    assert reader.params[0] == {"alert_id": alert.alert_id}
    assert repo.alert("nada") is None


def test_eventos_serie_y_subidas() -> None:
    alert = ALERT
    event, metric, boost = EVENT, METRIC, BOOST
    repo, reader, _ = bq_repo(
        [event.model_dump()], [metric.model_dump()], [boost.model_dump()]
    )

    assert repo.events(alert.alert_id) == [event]
    assert "`p.d.drift_alert_events`" in reader.sql[0]
    assert "ORDER BY `at`" in reader.sql[0]
    assert repo.metrics(
        ALERT.bank_id, ALERT.series, date(2024, 10, 1), ALERT.period
    ) == [metric]
    assert "`p.d.drift_metrics`" in reader.sql[1]
    assert "period BETWEEN @first AND @last" in reader.sql[1]
    assert repo.boosts([boost.boost_id]) == {boost.boost_id: boost}
    assert "ORDER BY ended_reason IS NULL" in reader.sql[2]
    assert repo.boosts([]) == {}
    assert len(reader.sql) == 3


def test_resumen_cuenta_solo_abiertas() -> None:
    repo, reader, _ = bq_repo([{"bank_id": "BBVA", "n": 2}])

    assert repo.open_by_bank() == {"BBVA": 2}
    assert "COALESCE(status, 'open') = 'open'" in reader.sql[0]


def test_escribe_el_evento_y_el_cierre_con_su_clave() -> None:
    boost = BOOST.model_copy(
        update={"ended_reason": BoostEndReason.ALERT_CLOSED}
    )
    repo, _, writer = bq_repo()

    repo.add_event(EVENT)
    repo.close_boost(boost)

    assert [(t, k) for t, _, k in writer.inserted] == [
        ("drift_alert_events", ["event_id"]),
        ("hitl_boosts", ["boost_id", "ended_reason"]),
    ]
