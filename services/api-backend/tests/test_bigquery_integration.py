"""Integración opcional con BigQuery de dev (fuera de CI).

    RUN_BIGQUERY_TESTS=1 BQ_TEST_PROJECT=<proyecto> \
        uv run pytest services/api-backend -m bigquery

Hace ``dry_run`` de una consulta por cada tabla y vista permitida: comprueba
que existen y anota los bytes que lee un ``SELECT *``. Cada paso suma el
``dry_run`` de las consultas de sus repositorios.
"""

import os

import pytest
from api_backend.bq.names import ALLOWED_NAMES, qualified
from google.cloud import bigquery

pytestmark = [
    pytest.mark.bigquery,
    pytest.mark.skipif(
        os.environ.get("RUN_BIGQUERY_TESTS") != "1",
        reason="solo con RUN_BIGQUERY_TESTS=1, BQ_TEST_PROJECT y credenciales",
    ),
]


@pytest.mark.parametrize("name", sorted(ALLOWED_NAMES))
def test_tabla_o_vista_existe(
    name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    project = os.environ["BQ_TEST_PROJECT"]
    client = bigquery.Client(project=project)
    job = client.query(
        f"SELECT * FROM {qualified(name, project, 'bbva_voc_tds')}",  # noqa: S608
        job_config=bigquery.QueryJobConfig(dry_run=True),
    )

    assert job.total_bytes_processed is not None
    with capsys.disabled():
        print(f"\n{name}: {job.total_bytes_processed} bytes")
