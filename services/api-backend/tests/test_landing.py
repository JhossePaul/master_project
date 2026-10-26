"""``GET /api/v1/landing`` con repositorios en memoria."""

from datetime import UTC, date, datetime

import pytest
from api_backend.sections.landing.repository import (
    InMemoryLandingRepository,
    KpiRow,
    sample_repository,
)
from api_backend.sections.landing.schemas import RunSummary
from api_backend.sections.landing.service import headlines
from api_backend.testing import local_app
from fastapi.testclient import TestClient
from voc_common import HitlTask, RunKind, RunStatus

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
TODAY = date(2026, 10, 26)


def kpi(metric: str, bank: str, period: str, value: float = 0.2) -> KpiRow:
    return KpiRow(
        metric=metric,
        bank_id=bank,
        period=period,
        estimate=value,
        ci_low=value - 0.01,
        ci_high=value + 0.01,
        n_gold=100,
        n_unlabeled=1000,
        model_version="m1",
        gold_version="g1",
    )


def pair(bank: str, period: str) -> list[KpiRow]:
    return [kpi("neg", bank, period), kpi("gap_estrellas", bank, period, -0.3)]


def client(
    repo: InMemoryLandingRepository, roles: str = "lector"
) -> TestClient:
    app = local_app(roles)
    app.state.landing_repository = repo
    return TestClient(app)


def run(started: str, status: RunStatus = RunStatus.SUCCEEDED) -> RunSummary:
    return RunSummary(
        run_id="r1",
        kind=RunKind.DELTA,
        status=status,
        started_at=datetime.fromisoformat(started),
        ended_at=None,
        model_version="m1",
    )


def test_devuelve_frescura_alertas_y_bancos() -> None:
    repo = InMemoryLandingRepository(
        ingestion_at=NOW,
        delta=run("2026-10-26T01:00:00+00:00"),
        monitor_at=NOW,
        until=TODAY,
        alerts={"BBVA": 2},
        kpis=pair("BBVA", "2026-09"),
    )

    body = client(repo).get("/api/v1/landing").json()

    assert body["freshness"]["data_until"] == "2026-10-26"
    assert body["freshness"]["last_delta"]["status"] == "succeeded"
    assert body["open_alerts"] == {"BBVA": 2}
    assert body["banks"][0]["bank_id"] == "BBVA"
    assert body["banks"][0]["neg"]["method"] == "ppi"


def test_un_banco_sin_ppi_en_el_ultimo_mes_cae_al_anterior() -> None:
    rows = pair("BBVA", "2026-09") + pair("AZTECA", "2026-08")
    rows.append(kpi("neg", "AZTECA", "2026-09"))  # falta el gap de septiembre

    result = {h.bank_id: h.period for h in headlines(rows, TODAY)}

    assert result == {"AZTECA": "2026-08", "BBVA": "2026-09"}


def test_el_mes_en_curso_no_cuenta() -> None:
    rows = pair("BBVA", "2026-10") + pair("BBVA", "2026-09")

    assert headlines(rows, TODAY)[0].period == "2026-09"


def test_la_ultima_corrida_gana_en_la_frescura() -> None:
    repo = InMemoryLandingRepository(delta=run("2026-10-25T01:00:00+00:00"))

    body = client(repo).get("/api/v1/landing").json()

    assert body["freshness"]["last_delta"]["started_at"].startswith(
        "2026-10-25"
    )
    assert body["freshness"]["last_ingestion_at"] is None


def test_hitl_pending_solo_para_revisores() -> None:
    repo = InMemoryLandingRepository(pending={HitlTask.SENTIMENT: 7})

    lector = client(repo, "lector").get("/api/v1/landing").json()
    revisor = client(repo, "revisor").get("/api/v1/landing").json()

    assert lector["hitl_pending"] is None
    assert revisor["hitl_pending"] == 7


def test_el_repositorio_de_muestra_sirve_en_fixtures() -> None:
    response = TestClient(local_app("lector")).get("/api/v1/landing")

    assert response.status_code == 200
    assert len(response.json()["banks"]) == 5
    assert sample_repository(NOW).hitl_pending([]) == 0


class FakeReader:
    """Devuelve filas fijas y guarda el SQL que recibió."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows_out = rows
        self.sql: list[str] = []

    def rows(self, sql: str, params: object, **_: object) -> list[dict]:
        self.sql.append(sql)
        return self.rows_out


def bq_repo(rows: list[dict[str, object]]) -> tuple[object, FakeReader]:
    from api_backend.sections.landing.repository import (
        BigQueryLandingRepository,
    )
    from api_backend.settings import ApiSettings

    reader = FakeReader(rows)
    settings = ApiSettings.model_validate(
        {"gcp_project_id": "p", "bq_dataset_id": "d", "iap_audience": "/a"}
    )
    return BigQueryLandingRepository(reader, settings), reader  # type: ignore[arg-type]


def test_bigquery_lee_valores_unicos_y_nulos() -> None:
    repo, reader = bq_repo([{"v": NOW}])
    assert repo.last_ingestion_at() == NOW  # type: ignore[attr-defined]
    assert repo.last_monitor_at() == NOW  # type: ignore[attr-defined]
    assert repo.data_until() == NOW  # type: ignore[attr-defined]
    assert "`p.d.ingestion_runs_log_v2`" in reader.sql[0]
    assert "review_predictions`" in reader.sql[2]

    empty, _ = bq_repo([])
    assert empty.last_ingestion_at() is None  # type: ignore[attr-defined]
    assert empty.last_delta() is None  # type: ignore[attr-defined]


def test_bigquery_alertas_corrida_y_pendientes() -> None:
    repo, _ = bq_repo([{"bank_id": "BBVA", "n": 3}])
    assert repo.open_alerts() == {"BBVA": 3}  # type: ignore[attr-defined]

    repo, _ = bq_repo([{"n": 5}])
    assert repo.hitl_pending([HitlTask.SENTIMENT]) == 5  # type: ignore[attr-defined]
    assert repo.hitl_pending([]) == 0  # type: ignore[attr-defined]

    repo, _ = bq_repo(
        [
            {
                "run_id": "r",
                "kind": "delta",
                "status": "succeeded",
                "started_at": NOW,
                "ended_at": NOW,
                "model_version": "m1",
            }
        ]
    )
    assert repo.last_delta().run_id == "r"  # type: ignore[attr-defined]


def test_bigquery_kpis_se_convierten_en_filas() -> None:
    row = {
        "metric": "neg",
        "bank_id": "BBVA",
        "period": "2026-09",
        "estimate": 0.2,
        "ci_low": 0.19,
        "ci_high": 0.21,
        "n_gold": 10,
        "n_unlabeled": 100,
        "model_version": "m1",
        "gold_version": "g1",
    }
    repo, _ = bq_repo([row])

    assert repo.ppi_kpis()[0].bank_id == "BBVA"  # type: ignore[attr-defined]


def test_el_router_arma_el_repositorio_de_bigquery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api_backend.bq import deps
    from api_backend.main import create_app
    from api_backend.settings import ApiSettings

    monkeypatch.setattr(deps.bigquery, "Client", lambda project: object())
    settings = ApiSettings.model_validate(
        {
            "environment": "local",
            "portal_auth_mode": "local",
            "portal_local_user": "ana@example.com",
            "portal_local_roles": "lector",
            "gcp_project_id": "p",
            "user_hash_salt": "s" * 16,
        }
    )
    app = create_app(settings)
    fake = FakeReader([])
    monkeypatch.setattr(deps, "BigQueryReader", lambda client, s: fake)

    body = TestClient(app).get("/api/v1/landing").json()

    assert body["banks"] == [] and body["freshness"]["data_until"] is None
    assert app.state.bq_reader is fake
