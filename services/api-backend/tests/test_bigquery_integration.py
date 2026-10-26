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


def _reviews_repository(project: str):  # noqa: ANN202
    from api_backend.bq.reader import BigQueryReader
    from api_backend.sections.reviews.repository import (
        BigQueryReviewsRepository,
    )
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
    return BigQueryReviewsRepository(reader, settings), reader, settings


def test_explorador_consultas_de_lectura(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import UTC, datetime, timedelta

    from api_backend.sections.kpis.schemas import BANK_IDS
    from api_backend.sections.reviews.filters import ReviewFilters

    project = os.environ["BQ_TEST_PROJECT"]
    repo, reader, settings = _reviews_repository(project)
    today = datetime.now(UTC).date()
    f = ReviewFilters(
        banks=tuple(BANK_IDS),
        date_from=today - timedelta(days=365),
        date_to=today,
    )

    rows, total = repo.page(f, "fecha_desc", 1, 50)
    assert rows and total >= len(rows)
    assert any(r.text for r in rows), "el texto del TDS no llegó"
    total_facets, by = repo.facets(f)
    assert total_facets == total and by["bank"]
    narrow = ReviewFilters(
        banks=("BBVA",),
        date_from=today - timedelta(days=30),
        date_to=today,
        sentiment=("NEG",),
        stars=(1, 2),
    )
    small, _ = repo.page(narrow, "confidence_asc", 1, 20)
    assert all(r.bank_id == "BBVA" and r.sentiment == "NEG" for r in small)
    first = rows[0]
    detail = repo.detail(first.bank_id, first.id_resena)
    assert detail is not None and detail[0].id_resena == first.id_resena
    repo.hitl_reviews(first.id_resena)
    repo.stored_explanation(first.text_key)
    with capsys.disabled():
        print(f"\nfilas de la primera página: {len(rows)}, total {total}")
    # Una consulta vectorial con un vector fijo (no necesita el servicio).
    from api_backend.sections.reviews.filters import months_back

    stats: dict[str, int] = {}
    vector = [((i * 7) % 11 - 5) / 10 for i in range(384)]
    hits = repo.vector_search(
        vector, list(BANK_IDS), months_back(today, 12), 10, stats
    )
    groups = repo.groups(hits, months_back(today, 12))
    assert hits and groups
    with capsys.disabled():
        print(f"búsqueda: {len(hits)} vecinos, {stats['bytes_billed']} bytes")
