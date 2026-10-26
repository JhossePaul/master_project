"""BigQueryWriter: INSERT por nombre, idempotente por clave."""

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from api_backend.bq.writer import (
    BigQueryWriter,
    insert_statement,
    param_value,
)
from api_backend.errors import ApiError, ErrorCode
from api_backend.settings import ApiSettings
from google.api_core.exceptions import InternalServerError
from google.cloud import bigquery
from voc_common import ANALYTICS_V3_TABLES, HitlEvent, HitlStatus
from voc_common.bq_schema import bq_schema
from voc_common.policies import DriftPolicy

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "packages/voc-common/tests/fixtures/analytics_v3"
SETTINGS = ApiSettings.model_validate(
    {"gcp_project_id": "p", "bq_dataset_id": "ds", "iap_audience": "/a"}
)
EVENT = HitlEvent(
    event_id="e1",
    item_id="i1",
    status=HitlStatus.IN_REVIEW,
    actor_hash="a" * 64,
    at=datetime(2026, 10, 25, 12, 0, tzinfo=UTC),
)


@dataclass
class FakeJob:
    affected: int
    error: Exception | None = None

    @property
    def num_dml_affected_rows(self) -> int:
        return self.affected

    def result(self) -> None:
        if self.error:
            raise self.error


@dataclass
class FakeClient:
    affected: list[int] = field(default_factory=lambda: [1])
    error: Exception | None = None
    calls: list[tuple[str, bigquery.QueryJobConfig]] = field(
        default_factory=list
    )

    def query(self, sql: str, job_config: bigquery.QueryJobConfig):
        self.calls.append((sql, job_config))
        return FakeJob(self.affected.pop(0), self.error)


def writer(client: FakeClient) -> BigQueryWriter:
    return BigQueryWriter(cast(Any, client), SETTINGS)


def test_columnas_por_nombre_entre_comillas_incluida_at() -> None:
    client = FakeClient()

    writer(client).insert("hitl_events", EVENT, ["event_id"])

    sql, _ = client.calls[0]
    assert sql.startswith(
        "INSERT INTO `p.ds.hitl_events` "
        "(`event_id`, `item_id`, `status`, `actor_hash`, `at`) SELECT "
        "@event_id, @item_id, @status, @actor_hash, @at FROM (SELECT 1)"
    )
    assert "WHERE NOT EXISTS (SELECT 1 FROM `p.ds.hitl_events` WHERE" in sql
    assert "`event_id` = @event_id" in sql


def test_los_valores_viajan_como_parametros_con_su_tipo() -> None:
    client = FakeClient()

    writer(client).insert("hitl_events", EVENT, ["event_id"])

    params = {p.name: p for p in client.calls[0][1].query_parameters}
    assert params["status"].value == "in_review"
    assert params["status"].type_ == "STRING"
    assert params["at"].type_ == "TIMESTAMP"
    assert params["at"].value == EVENT.at
    assert "e1" not in client.calls[0][0]
    assert client.calls[0][1].maximum_bytes_billed == 2_000_000_000


def test_segundo_insert_con_la_misma_clave_da_false() -> None:
    client = FakeClient(affected=[1, 0])
    w = writer(client)

    assert w.insert("hitl_events", EVENT, ["event_id"]) is True
    assert w.insert("hitl_events", EVENT, ["event_id"]) is False


def test_json_va_con_parse_json() -> None:
    policy = DriftPolicy.model_validate_json(
        (FIXTURES / "drift_policy.json").read_text()
    )
    client = FakeClient()

    writer(client).insert(
        "drift_policy", policy, ["drift_policy_version", "bank_id"]
    )

    sql, config = client.calls[0]
    assert "PARSE_JSON(@thresholds)" in sql
    thresholds = next(
        p for p in config.query_parameters if p.name == "thresholds"
    )
    assert thresholds.type_ == "STRING"
    assert isinstance(json.loads(thresholds.value), dict)


def test_clave_nula_se_compara_con_is_null() -> None:
    columns = bq_schema(ANALYTICS_V3_TABLES["hitl_events"])

    sql = insert_statement("`t`", columns, ["actor_hash"])

    assert "(`actor_hash` = @actor_hash OR (`actor_hash` IS NULL AND " in sql


def test_json_repetido_viaja_como_arreglo_de_texto() -> None:
    columns = bq_schema(ANALYTICS_V3_TABLES["review_explanations"])

    sql = insert_statement("`t`", columns, ["text_key", "model_version"])

    assert "ARRAY(SELECT PARSE_JSON(v) FROM UNNEST(@attributions) AS v)" in sql


def test_clave_fuera_de_la_tabla_falla() -> None:
    columns = bq_schema(ANALYTICS_V3_TABLES["hitl_events"])

    with pytest.raises(ValueError, match="clave"):
        insert_statement("`t`", columns, ["nada"])
    with pytest.raises(ValueError, match="clave"):
        insert_statement("`t`", columns, [])


def test_tabla_o_modelo_incorrectos_fallan() -> None:
    w = writer(FakeClient())

    with pytest.raises(TypeError):
        w.insert("nada", EVENT, ["event_id"])
    with pytest.raises(TypeError):
        w.insert("hitl_items", EVENT, ["item_id"])


def test_error_de_bigquery_da_502() -> None:
    client = FakeClient(error=InternalServerError("boom"))

    with pytest.raises(ApiError) as caught:
        writer(client).insert("hitl_events", EVENT, ["event_id"])

    assert caught.value.code is ErrorCode.UPSTREAM


def test_param_value_convierte_cada_tipo() -> None:
    assert param_value("STRING", "NULLABLE", None) is None
    assert param_value("DATE", "NULLABLE", "2026-10-25") == date(2026, 10, 25)
    assert param_value("INT64", "REPEATED", [1, 2]) == [1, 2]
    assert param_value("JSON", "REPEATED", [{"a": 1}]) == ['{"a": 1}']
    assert param_value("TIMESTAMP", "NULLABLE", "2026-10-25T12:00:00Z") == (
        datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    )
