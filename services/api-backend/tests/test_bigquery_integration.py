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


def _hitl_repository(project: str):  # noqa: ANN202
    from api_backend.bq.reader import BigQueryReader
    from api_backend.sections.hitl.repository import BigQueryHitlRepository
    from api_backend.settings import ApiSettings

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
    return BigQueryHitlRepository(reader, None, settings)  # type: ignore[arg-type]


def test_hitl_consultas_de_lectura() -> None:
    from datetime import UTC, datetime

    from voc_common import HitlTask

    project = os.environ["BQ_TEST_PROJECT"]
    repo = _hitl_repository(project)
    now = datetime.now(UTC)

    entries = repo.entries(HitlTask.SENTIMENT, now)
    assert entries, "dev tiene casos de sentimiento"
    from api_backend.sections.hitl.repository import public_id

    first = entries[0]
    assert repo.entry(public_id(first.item.item_id), now) is not None
    assert repo.entry("0" * 32, now) is None
    assert repo.guidelines(HitlTask.SENTIMENT)
    assert repo.has_review("no-existe") is False
    summary = repo.summary(HitlTask.SENTIMENT, "a" * 64, now)
    assert summary.pending >= len(entries) or len(entries) == 500
    text = repo.review_text(first.item.bank_id, first.item.id_resena)
    assert text is None or isinstance(text, str)
    pairs = [(e.item.bank_id, e.item.id_resena) for e in entries[:10]]
    batch = repo.review_texts(pairs)
    assert set(batch) <= set(pairs) and batch
