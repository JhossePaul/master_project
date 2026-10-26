"""BigQueryReader: parámetros, tope de bytes, caché y errores."""

from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from api_backend.bq.reader import BigQueryReader, Param
from api_backend.errors import ApiError, ErrorCode
from api_backend.settings import ApiSettings
from google.api_core.exceptions import BadRequest, InternalServerError
from google.cloud import bigquery

SETTINGS = ApiSettings.model_validate(
    {"gcp_project_id": "p", "iap_audience": "/a", "cache_ttl_seconds": 600}
)


@dataclass
class Row:
    data: dict[str, object]

    def items(self):
        return self.data.items()


@dataclass
class FakeJob:
    rows: list[dict[str, object]]
    total_bytes_billed: int = 1234

    def result(self) -> list[Row]:
        return [Row(r) for r in self.rows]


@dataclass
class FakeClient:
    rows: list[dict[str, object]] = field(default_factory=list)
    error: Exception | None = None
    calls: list[tuple[str, bigquery.QueryJobConfig]] = field(
        default_factory=list
    )

    def query(self, sql: str, job_config: bigquery.QueryJobConfig):
        self.calls.append((sql, job_config))
        if self.error:
            raise self.error
        return FakeJob(self.rows)


def reader(client: FakeClient) -> BigQueryReader:
    return BigQueryReader(cast(Any, client), SETTINGS)


def test_devuelve_filas_y_pasa_los_valores_como_parametros() -> None:
    client = FakeClient(rows=[{"n": 1}])
    value = "x'; DROP TABLE t; --"

    rows = reader(client).rows(
        "SELECT 1 AS n WHERE s = @s AND b IN UNNEST(@b)",
        [
            Param("s", "STRING", value),
            Param("b", "STRING", ["A", "B"], array=True),
        ],
    )

    sql, config = client.calls[0]
    assert rows == [{"n": 1}]
    assert value not in sql
    scalar, array = config.query_parameters
    assert scalar.value == value
    assert array.values == ["A", "B"]


def test_fija_siempre_el_tope_de_bytes() -> None:
    client = FakeClient()
    r = reader(client)

    r.rows("SELECT 1", [])
    r.rows("SELECT 2", [], max_bytes=5)

    assert client.calls[0][1].maximum_bytes_billed == 2_000_000_000
    assert client.calls[1][1].maximum_bytes_billed == 5
    assert client.calls[0][1].use_query_cache is True


def test_rechazo_por_tope_da_503_query_too_expensive() -> None:
    error = BadRequest(
        "Query exceeded limit for bytes billed",
        errors=[{"reason": "bytesBilledLimitExceeded"}],
    )

    with pytest.raises(ApiError) as caught:
        reader(FakeClient(error=error)).rows("SELECT 1", [])

    assert caught.value.code is ErrorCode.QUERY_TOO_EXPENSIVE
    assert caught.value.status_code == 503


@pytest.mark.parametrize(
    "error", [BadRequest("Syntax error"), InternalServerError("boom")]
)
def test_otro_error_de_bigquery_da_502(error: Exception) -> None:
    with pytest.raises(ApiError) as caught:
        reader(FakeClient(error=error)).rows("SELECT 1", [])

    assert caught.value.code is ErrorCode.UPSTREAM


def test_la_cache_solo_aplica_con_cache_true() -> None:
    client = FakeClient(rows=[{"n": 1}])
    r = reader(client)
    params = [Param("b", "STRING", ["A"], array=True)]

    r.rows("SELECT 1", params)
    r.rows("SELECT 1", params)
    assert len(client.calls) == 2

    r.rows("SELECT 1", params, cache=True)
    r.rows("SELECT 1", params, cache=True)
    assert len(client.calls) == 3

    r.rows("SELECT 1", [Param("b", "STRING", ["B"], array=True)], cache=True)
    assert len(client.calls) == 4


def test_registra_bytes_facturados_sin_valores(
    capsys: pytest.CaptureFixture[str],
) -> None:
    reader(FakeClient(rows=[{"n": 1}])).rows(
        "SELECT 1", [Param("s", "STRING", "secreto")], name="kpis"
    )

    out = capsys.readouterr().out
    assert '"query": "kpis"' in out
    assert '"bytes_billed": 1234' in out
    assert "secreto" not in out
