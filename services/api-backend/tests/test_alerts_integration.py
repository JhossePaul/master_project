"""Consultas de lectura de las alertas contra BigQuery de dev (fuera de CI).

    RUN_BIGQUERY_TESTS=1 BQ_TEST_PROJECT=<proyecto> \
        uv run pytest services/api-backend/tests/test_alerts_integration.py

Solo lecturas: dev no tiene alertas todavía, así que las consultas deben
devolver listas vacías sin error y la serie de un banco sí trae meses.
"""

import os
from datetime import date

import pytest
from api_backend.bq.reader import BigQueryReader
from api_backend.sections.alerts.repository import BigQueryAlertRepository
from api_backend.settings import ApiSettings
from google.cloud import bigquery

pytestmark = [
    pytest.mark.bigquery,
    pytest.mark.skipif(
        os.environ.get("RUN_BIGQUERY_TESTS") != "1",
        reason="solo con RUN_BIGQUERY_TESTS=1, BQ_TEST_PROJECT y credenciales",
    ),
]


def _repository() -> BigQueryAlertRepository:
    project = os.environ["BQ_TEST_PROJECT"]
    settings = ApiSettings.model_validate(
        {
            "environment": "local",
            "portal_auth_mode": "local",
            "portal_local_user": "x@example.com",
            "gcp_project_id": project,
            "user_hash_salt": "s" * 16,
        }
    )
    reader = BigQueryReader(bigquery.Client(project=project), settings)
    # Solo lecturas: el escritor no se usa.
    return BigQueryAlertRepository(reader, None, settings)  # type: ignore[arg-type]


def test_alertas_consultas_de_lectura() -> None:
    repo = _repository()

    records = repo.alerts(None, [])
    counts = repo.open_by_bank()

    assert sum(counts.values()) == sum(
        1 for r in records if r.status.value == "open"
    )
    assert repo.alert("no-existe") is None
    assert repo.events("no-existe") == []
    assert repo.boosts(["no-existe"]) == {}
    series = repo.metrics(
        "BBVA", "neg_share", date(2025, 1, 1), date(2026, 9, 1)
    )
    assert series, "dev tiene la serie de proporción de negativas"
    assert [m.period for m in series] == sorted({m.period for m in series})
    for record in records[:3]:
        assert repo.events(record.alert.alert_id)
