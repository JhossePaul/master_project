"""MLOps sobre BigQuery, con un lector falso: SQL, parámetros y filas."""

from datetime import UTC, date, datetime
from typing import Any

import pytest
from api_backend.sections.mlops.repository import BigQueryMlopsRepository
from api_backend.sections.mlops.sample import sample_repository
from api_backend.settings import ApiSettings
from voc_common import RunKind

T0 = datetime(2026, 10, 26, 12, tzinfo=UTC)
SAMPLE = sample_repository(T0)


class FakeReader:
    def __init__(self, *batches: list[dict[str, Any]]) -> None:
        self.batches = list(batches)
        self.sql: list[str] = []
        self.params: list[dict[str, Any]] = []

    def rows(self, sql: str, params: Any, **_: object) -> list[dict[str, Any]]:
        self.sql.append(sql)
        self.params.append({p.name: p.value for p in params})
        return self.batches.pop(0) if self.batches else []


def bq_repo(
    *batches: list[dict[str, Any]],
) -> tuple[BigQueryMlopsRepository, FakeReader]:
    reader = FakeReader(*batches)
    settings = ApiSettings.model_validate(
        {"gcp_project_id": "p", "bq_dataset_id": "d", "iap_audience": "/a"}
    )
    return BigQueryMlopsRepository(reader, settings), reader  # type: ignore[arg-type]


def test_la_ingesta_se_deduplica_por_evento_antes_de_agrupar() -> None:
    repo, reader = bq_repo(
        [
            {
                "run_id": "run-1",
                "bank_id": "BBVA",
                "mode": "incremental",
                "started_at": T0,
                "ended_at": T0.replace(minute=7),
                "status": "COMPLETED",
                "reviews_extracted": 420,
                "reviews_published": 400,
                "reviews_discarded": 20,
            },
            {
                "run_id": "run-2",
                "bank_id": "AZTECA",
                "mode": "historical",
                "started_at": T0,
                "ended_at": T0,
                "status": "FAILED",
                "reviews_extracted": None,
                "reviews_published": None,
                "reviews_discarded": None,
            },
        ]
    )

    runs = repo.ingestion(T0)

    sql = reader.sql[0]
    assert "`p.d.ingestion_runs_log_v2`" in sql
    assert "PARTITION BY audit_event_id" in sql
    assert sql.index("PARTITION BY audit_event_id") < sql.index(
        "GROUP BY run_id"
    )
    assert reader.params[0] == {"since": T0}
    assert (runs[0].run_id, runs[0].reviews_published) == ("run-1", 400)
    assert runs[1].reviews_extracted is None and runs[1].status == "FAILED"


def test_la_deriva_filtra_por_nombre_y_prefijo_con_parametros() -> None:
    metric = SAMPLE.drift_rows[0]
    repo, reader = bq_repo([metric.model_dump()])

    rows = repo.drift(
        date(2024, 11, 1),
        date(2026, 10, 1),
        names=("neg_share",),
        prefix="family_",
    )

    assert rows == [metric]
    sql = reader.sql[0]
    assert "`p.d.drift_metrics`" in sql
    assert "metric IN UNNEST(@names)" in sql
    assert "STARTS_WITH(metric, @prefix)" in sql
    assert "PARTITION BY bank_id, period, metric" in sql
    assert reader.params[0] == {
        "first": date(2024, 11, 1),
        "last": date(2026, 10, 1),
        "names": ("neg_share",),
        "prefix": "family_",
    }


def test_las_corridas_leen_la_vista_vigente_y_filtran_el_tipo() -> None:
    run = SAMPLE.run_rows[0]
    repo, reader = bq_repo([run.model_dump()], [])

    assert repo.runs(T0, RunKind.DELTA) == [run]
    repo.runs(T0)

    assert "`p.d.inference_runs_current`" in reader.sql[0]
    assert (
        "kind = @kind" in reader.sql[0] and "kind = @kind" not in reader.sql[1]
    )
    assert reader.params[0]["kind"] == "delta"


def test_calidad_trae_la_fila_mas_reciente_de_cada_sujeto() -> None:
    quality = SAMPLE.quality_rows[0]
    repo, reader = bq_repo([quality.model_dump()])

    assert repo.quality() == [quality]
    assert "`p.d.model_quality`" in reader.sql[0]
    assert "IFNULL(prompt_version, '')" in reader.sql[0]
    assert "ORDER BY computed_at DESC" in reader.sql[0]


def test_registro_checks_y_politicas() -> None:
    versions = SAMPLE.model_rows
    repo, reader = bq_repo(
        [v.model_dump() for v in versions],
        [c.model_dump() for c in SAMPLE.check_rows],
        [SAMPLE.policies[0].model_dump()],
    )

    assert repo.model_versions() == versions
    assert repo.promotion_checks() == SAMPLE.check_rows
    assert repo.risk_policies() == SAMPLE.policies
    assert "`p.d.model_versions`" in reader.sql[0]
    assert "PARTITION BY candidate_version" in reader.sql[1]


def test_elegibilidad_y_frescura() -> None:
    repo, reader = bq_repo(
        [
            {
                "bank_id": "BBVA",
                "mes": date(2026, 9, 1),
                "eligibility_code": "ELEGIBLE",
                "filas": 700,
            }
        ],
        [{"v": T0}],
        [{"v": T0}],
        [{"v": None}],
    )

    (row,) = repo.eligibility()
    assert (row.bank_id, row.period, row.code, row.n) == (
        "BBVA",
        date(2026, 9, 1),
        "ELEGIBLE",
        700,
    )
    assert repo.last_ingestion_at() == T0
    assert repo.last_monitor_at() == T0
    assert repo.last_topic_fit() is None
    assert "`p.d.eligibility_counts`" in reader.sql[0]
    assert "status = 'COMPLETED'" in reader.sql[1]
    assert "`p.d.kpi_estimates`" in reader.sql[2]


def test_series_de_deriva() -> None:
    repo, reader = bq_repo(
        [{"metric": "neg_share"}, {"metric": "topic_noise_share"}]
    )
    assert repo.drift_series() == ["neg_share", "topic_noise_share"]
    assert "DISTINCT metric" in reader.sql[0]


@pytest.mark.parametrize("name", ["model_quality", "promotion_checks"])
def test_las_tablas_estan_en_la_lista_cerrada(name: str) -> None:
    from api_backend.bq.names import qualified

    assert qualified(name, "p", "d") == f"`p.d.{name}`"
