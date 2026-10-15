"""Feature 4.3: upsert TDS idempotente, recibos inmutables y cierre de página.

GCS simulado con generaciones (mismas reglas que las pruebas de EPIC-3) y una
página comprometida de verdad con `WatermarkRepository`, que aquí solo se lee.
"""

import ast
import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import BadRequest, NotFound, PreconditionFailed
from ingestion_worker.watermark_store import (
    ReviewLedgerEntry,
    WatermarkRepository,
)
from sanitization_pipeline import bq_writer as bq
from sanitization_pipeline import processing_ledger as pl
from voc_common import (
    PLAYSTORE_BANK_APPS,
    BankKey,
    PageManifest,
    ProcessingReceipt,
    ProcessingStatus,
    PublicationStatus,
    RawReviewEnvelope,
    RawReviewEvent,
    SanitizationStatus,
    SanitizedReviewEnvelope,
    SanitizedReviewRecord,
    ScanContext,
    ScanStreamState,
)

BANK = BankKey.BBVA
APP = PLAYSTORE_BANK_APPS[BANK]
T0 = datetime(2026, 10, 15, 8, tzinfo=UTC)
SALT = "salt-for-sanitization-tests"
CURSOR = "opaque-cursor"
ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------- fake GCS
class FakeBlob:
    def __init__(self, bucket: "FakeBucket", name: str) -> None:
        self.bucket, self.name = bucket, name
        self.metadata: dict[str, str] | None = None
        self.generation: int | None = None

    def _get(self, expected: int | None = None) -> dict[str, Any]:
        if self.name not in self.bucket.objects:
            raise NotFound("missing")
        record = self.bucket.objects[self.name]
        if expected is not None and record["generation"] != expected:
            raise PreconditionFailed("changed")
        return record

    def reload(self, *, if_generation_match=None, timeout=None) -> None:
        record = self._get(if_generation_match)
        self.generation = record["generation"]
        self.metadata = copy.deepcopy(record["metadata"])

    def download_as_bytes(self, *, if_generation_match=None, timeout=None):
        return self._get(if_generation_match)["data"]

    def upload_from_string(
        self, data, *, content_type, if_generation_match, timeout
    ) -> None:
        if self.name in self.bucket.vanish_after_conflict:
            self.bucket.objects.pop(self.name, None)
            raise PreconditionFailed("raced")
        record = self.bucket.objects.get(self.name)
        if (record["generation"] if record else 0) != if_generation_match:
            raise PreconditionFailed("changed")
        self.bucket.counter += 1
        self.generation = self.bucket.counter
        self.bucket.objects[self.name] = {
            "generation": self.generation,
            "data": bytes(data),
            "metadata": copy.deepcopy(self.metadata),
        }


class FakeBucket:
    name = "test-bucket"

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.counter = 0
        self.vanish_after_conflict: set[str] = set()

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)


class FakeStorage:
    def __init__(self) -> None:
        self.value = FakeBucket()

    def bucket(self, _: str) -> FakeBucket:
        return self.value


# ------------------------------------------------------------- fixtures
def raw_envelope(
    rid: str,
    *,
    page_id: str = "page-1",
    fecha: datetime = T0,
    observed: datetime = T0,
    votos: int = 0,
) -> RawReviewEnvelope:
    raw = RawReviewEvent(
        id_resena=rid,
        bank_id=BANK,
        app_id=APP,
        usuario="usuario",
        texto="falla al transferir dinero",
        estrellas=2,
        fecha=fecha,
        votos_utilidad=votos,
        ingested_at=observed,
    )
    return RawReviewEnvelope.from_raw(raw, page_id=page_id, stream_id="stream")


def sanitized(raw: RawReviewEnvelope) -> SanitizedReviewEnvelope:
    record = SanitizedReviewRecord.from_raw_and_dlp(
        raw.raw, "falla al transferir dinero", 0, SALT
    )
    return SanitizedReviewEnvelope.from_event(raw, record)


def receipt(
    event: RawReviewEnvelope | SanitizedReviewEnvelope,
    status: ProcessingStatus,
    *,
    at: datetime = T0,
    error_code: str | None = None,
) -> ProcessingReceipt:
    return ProcessingReceipt(
        bank_id=event.bank_id,
        app_id=event.app_id,
        receipt_id=event.event_id,
        event_id=event.event_id,
        review_id=event.review_id,
        source_revision=event.source_revision,
        page_id=event.page_id,
        status=status,
        processed_at=at,
        error_code=error_code,
        result_digest="a" * 64
        if status == ProcessingStatus.TDS_COMMITTED
        else None,
        bigquery_job_ids=("job",)
        if status == ProcessingStatus.TDS_COMMITTED
        else (),
    )


class World:
    """Ingesta con una página comprometida y el ledger de sanitización."""

    def __init__(self, events: int = 3) -> None:
        self.storage = FakeStorage()
        self.bucket = self.storage.value
        self.now = [T0]
        self.ingestion = WatermarkRepository(
            self.storage, "test-bucket", clock=lambda: self.now[0]
        )
        self.ledger = pl.ProcessingLedgerRepository(
            self.storage,
            "test-bucket",
            self.ingestion,
            clock=lambda: self.now[0],
        )
        self.events = [raw_envelope(f"r{i}") for i in range(events)]

    def commit_page(self, page_id: str = "page-1") -> PageManifest:
        repo = self.ingestion
        handle = repo.acquire_lease(BANK, "run")
        stream = ScanStreamState(
            bank_id=BANK,
            app_id=APP,
            stream_id="stream",
            context=ScanContext(app_id=APP, protocol_version="test"),
        )
        repo.register(handle, [stream])
        repo.start_incremental(handle, "stream")
        ledger = repo.write_review_ledger(
            BANK,
            f"{page_id}-ledger",
            [
                ReviewLedgerEntry(
                    review_id=e.review_id,
                    source_revision=e.source_revision,
                    event_id=e.event_id,
                    reviewed_at=e.raw.fecha,
                )
                for e in self.events
            ],
        )
        backup = self.bucket.blob(f"raw_staging/BBVA/run/{page_id}/f.jsonl.gz")
        backup.upload_from_string(
            b"capture",
            content_type="application/gzip",
            if_generation_match=0,
            timeout=30,
        )
        count = len(self.events)
        manifest = PageManifest(
            bank_id=BANK,
            app_id=APP,
            page_id=page_id,
            fetch_attempt_id="fetch",
            run_id="run",
            stream_id="stream",
            chain_epoch=0,
            ordinal=0,
            context=stream.context,
            fetched_at=T0,
            observed_min_at=T0,
            observed_max_at=T0,
            ledger=ledger,
            raw_count=count,
            valid_count=count,
            discarded_count=0,
            published_count=count,
            publication_status=PublicationStatus.PUBLISHED,
            content_fingerprint="b" * 64,
            backup_uri=f"gs://test-bucket/{backup.name}",
            backup_generation=backup.generation,
            output_token=CURSOR,
        )
        repo.commit_page(
            handle, manifest, expected_revision=repo.load(BANK).state.revision
        )
        repo.release_lease(handle)
        return manifest

    def root(self) -> dict[str, Any]:
        return copy.deepcopy(self.bucket.objects["state/watermarks/BBVA.json"])


# ------------------------------------------------------------ BigQuery
class FakeBigQuery:
    def __init__(self) -> None:
        self.created: list[Any] = []
        self.loaded: list[tuple[list[dict[str, Any]], str, dict[str, Any]]] = []
        self.queries: list[tuple[str, dict[str, Any]]] = []
        self.deleted: list[str] = []
        self.fail_merge: Exception | None = None
        self.merge_errors: list[dict[str, str]] | None = None
        self.load_errors: list[dict[str, str]] | None = None
        self.fail_delete = False

    def create_table(self, table, timeout=None):
        self.created.append(table)
        return table

    def load_table_from_json(self, rows, destination, **kwargs):
        self.loaded.append((list(rows), destination, kwargs))
        return Mock(job_id="load-1", errors=self.load_errors)

    def query(self, sql, **kwargs):
        self.queries.append((sql, kwargs))
        job = Mock(job_id="merge-1", errors=self.merge_errors)
        if self.fail_merge is not None:
            job.result.side_effect = self.fail_merge
        return job

    def delete_table(self, table, not_found_ok=False, timeout=None):
        assert not_found_ok
        self.deleted.append(table)
        if self.fail_delete:
            raise BadRequest("cannot delete")


def manager(client: FakeBigQuery) -> bq.BigQueryTdsUpsertManager:
    return bq.BigQueryTdsUpsertManager(
        client,  # type: ignore[arg-type]
        project="test-project",
        dataset="bbva_voc_tds",
        clock=lambda: T0,
    )


# ------------------------------------------------------------- bq_writer
def infra_schema() -> tuple[tuple[str, str, str], ...]:
    tree = ast.parse((ROOT / "infra/modules/storage_bq.py").read_text())
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_SANITIZED"
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("TDS schema not found")


def test_schema_and_rows_match_the_17_infra_columns():
    assert bq.TDS_SCHEMA == infra_schema()
    assert len(bq.TDS_COLUMNS) == 17
    row = bq.record_to_bq_row(sanitized(raw_envelope("r1")).record)
    assert tuple(row) == bq.TDS_COLUMNS
    assert row["fecha"] == "2026-10-15T08:00:00Z"
    assert row["source_observed_at"] == "2026-10-15T08:00:00Z"
    assert "usuario" not in row and "imagen_usuario" not in row
    assert [f.name for f in bq.BigQueryTdsUpsertManager.schema()] == list(
        bq.TDS_COLUMNS
    )


def test_batch_keeps_latest_revision_per_review():
    old = sanitized(raw_envelope("r1", observed=T0, votos=1))
    newer = sanitized(
        raw_envelope("r1", observed=T0 + timedelta(hours=1), votos=5)
    )
    edited = sanitized(
        raw_envelope("r1", fecha=T0 + timedelta(days=1), observed=T0, votos=0)
    )
    other = sanitized(raw_envelope("r2"))
    assert bq.latest_revisions([old, newer, other]) == [newer, other]
    assert bq.latest_revisions([edited, newer])[0] is edited


def test_upsert_loads_staging_merges_and_drops_it():
    client = FakeBigQuery()
    envelopes = [sanitized(raw_envelope(f"r{i}")) for i in range(3)]
    duplicate = sanitized(raw_envelope("r0", observed=T0 - timedelta(hours=1)))
    commit = manager(client).upsert_sanitized_batch([*envelopes, duplicate])
    assert commit == bq.TdsCommit(("load-1", "merge-1"), 3)
    (table,) = client.created
    assert table.table_id.startswith("_staging_sanitized_")
    assert table.dataset_id == "bbva_voc_tds"
    assert table.expires == T0 + timedelta(hours=1)
    rows, destination, options = client.loaded[0]
    assert len(rows) == 3 and destination.endswith(table.table_id)
    assert options["job_id_prefix"] == "voc_tds_load_"
    assert "job_id" not in options
    sql, query_options = client.queries[0]
    assert query_options["job_id_prefix"] == "voc_tds_merge_"
    assert "MERGE `test-project.bbva_voc_tds.sanitized_reviews_tds` T" in sql
    assert (
        "WHEN MATCHED AND (S.fecha > T.fecha OR (S.fecha = T.fecha AND "
        "S.source_observed_at >= T.source_observed_at))"
    ) in sql
    assert "source_observed_at = S.source_observed_at" in sql
    assert "id_resena = S.id_resena" not in sql.split("UPDATE SET")[1]
    assert client.deleted == [destination]


def test_retries_use_fresh_staging_tables_and_job_ids():
    client = FakeBigQuery()
    batch = [sanitized(raw_envelope("r1"))]
    manager(client).upsert_sanitized_batch(batch)
    manager(client).upsert_sanitized_batch(batch)
    first, second = (t.table_id for t in client.created)
    assert first != second and first[:35] == second[:35]


@pytest.mark.parametrize("failure", ["merge", "merge_errors", "load_errors"])
def test_failed_upsert_raises_and_always_drops_staging(failure):
    client = FakeBigQuery()
    if failure == "merge":
        client.fail_merge = BadRequest("row with PII must not leak")
    elif failure == "merge_errors":
        client.merge_errors = [{"message": "bad"}]
    else:
        client.load_errors = [{"message": "bad"}]
    with pytest.raises(bq.TdsWriteError) as exc:
        manager(client).upsert_sanitized_batch([sanitized(raw_envelope("r1"))])
    assert "PII" not in str(exc.value)
    assert len(client.deleted) == 1


def test_delete_failure_is_left_to_expiration_and_empty_batch_is_noop():
    client = FakeBigQuery()
    client.fail_delete = True
    assert manager(client).upsert_sanitized_batch(
        [sanitized(raw_envelope("r1"))]
    ).job_ids == ("load-1", "merge-1")
    empty = FakeBigQuery()
    assert manager(empty).upsert_sanitized_batch([]) == bq.TdsCommit((), 0)
    assert not empty.created and not empty.queries


def test_destination_validation():
    for kwargs in (
        {"project": "bad project", "dataset": "d"},
        {"project": "p-123", "dataset": "bad-dataset"},
    ):
        with pytest.raises(ValueError):
            bq.BigQueryTdsUpsertManager(FakeBigQuery(), **kwargs)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        bq.BigQueryTdsUpsertManager(
            FakeBigQuery(),  # type: ignore[arg-type]
            project="p-123",
            dataset="d",
            staging_ttl=timedelta(0),
        )
    with pytest.raises(ValueError):
        bq.merge_statement("p.d.t`; DROP TABLE x; --", "p.d.s")
    record = sanitized(raw_envelope("r1")).record
    with pytest.raises(ValueError):
        bq.record_to_bq_row(Mock(model_dump=lambda mode: {"x": 1}))
    assert bq.record_to_bq_row(record)["id_resena"] == "r1"


# ------------------------------------------------------------ receipts
def test_tds_receipts_carry_digest_and_jobs():
    envelope = sanitized(raw_envelope("r1"))
    (committed,) = pl.tds_committed_receipts([envelope], ("l", "m"), T0)
    assert committed.status == ProcessingStatus.TDS_COMMITTED
    assert committed.result_digest == bq.envelope_digest(envelope)
    assert committed.receipt_id == committed.event_id
    assert committed.bigquery_job_ids == ("l", "m")
    with pytest.raises(ValueError):
        pl.tds_committed_receipts([envelope], (), T0)


def test_receipts_are_immutable_first_writer_wins():
    world = World()
    event = world.events[0]
    first = receipt(event, ProcessingStatus.FILTERED_LENGTH)
    assert world.ledger.write_event_receipts([first]) == [first]
    later = receipt(
        event, ProcessingStatus.FILTERED_LENGTH, at=T0 + timedelta(hours=1)
    )
    assert world.ledger.write_event_receipts([later]) == [first]
    paths = sorted(n for n in world.bucket.objects if "receipts" in n)
    assert paths == [
        f"state/ingestion/receipts/BBVA/_events/{event.event_id}.json",
        f"state/ingestion/receipts/BBVA/page-1/{event.event_id}.json",
    ]
    found = world.ledger.find_already_processed_event_ids(
        BANK, [event.event_id, world.events[1].event_id]
    )
    assert found == {event.event_id: first}
    with pytest.raises(ValueError):
        world.ledger.write_event_receipts(
            [receipt(event, ProcessingStatus.RETRYABLE_ERROR, error_code="DLP")]
        )
    with pytest.raises(ValueError):
        world.ledger.write_event_receipts(
            [first.model_copy(update={"receipt_id": "other"})]
        )


def test_redelivery_from_another_page_copies_outcome():
    world = World()
    event = world.events[0]
    stored = world.ledger.write_event_receipts(
        [receipt(event, ProcessingStatus.TDS_COMMITTED)]
    )[0]
    world.now[0] = T0 + timedelta(days=1)
    copied = world.ledger.copy_receipt_for_page(stored, "page-2")
    assert (copied.page_id, copied.status, copied.result_digest) == (
        "page-2",
        stored.status,
        stored.result_digest,
    )
    assert copied.processed_at == T0 + timedelta(days=1)
    world.ledger.write_event_receipts([copied])
    assert world.ledger.page_receipt(BANK, "page-2", event.event_id) == copied
    # El índice conserva el primer resultado del evento.
    assert (
        world.ledger.find_already_processed_event_ids(BANK, [event.event_id])[
            event.event_id
        ]
        == stored
    )


def test_corrupt_or_foreign_ledger_objects_are_rejected():
    world = World()
    event = world.events[0]
    path = world.ledger.event_index_path(BANK, event.event_id)
    world.bucket.objects[path] = {
        "generation": 1,
        "data": b"{",
        "metadata": None,
    }
    with pytest.raises(pl.LedgerError):
        world.ledger.find_already_processed_event_ids(BANK, [event.event_id])
    other = receipt(
        world.events[1], ProcessingStatus.QUARANTINED, error_code="X"
    )
    world.bucket.objects[path]["data"] = other.model_dump_json().encode()
    with pytest.raises(pl.LedgerError):
        world.ledger.find_already_processed_event_ids(BANK, [event.event_id])
    page_path = world.ledger.receipt_path(BANK, "page-1", event.event_id)
    world.bucket.objects[page_path] = {
        "generation": 2,
        "data": other.model_dump_json().encode(),
        "metadata": None,
    }
    with pytest.raises(pl.LedgerError):
        world.ledger.page_receipt(BANK, "page-1", event.event_id)
    with pytest.raises(ValueError):
        world.ledger.receipt_path(BANK, "../page", event.event_id)


def test_object_removed_during_conflict_is_an_error():
    world = World()
    event = world.events[0]
    world.bucket.vanish_after_conflict.add(
        world.ledger.receipt_path(BANK, "page-1", event.event_id)
    )
    with pytest.raises(pl.LedgerError):
        world.ledger.write_event_receipts(
            [receipt(event, ProcessingStatus.FILTERED_LENGTH)]
        )


# --------------------------------------------------------- page closure
def test_page_closure_waits_for_commit_and_all_events():
    world = World()
    assert world.ledger.reconcile_page(BANK, "stream", "page-1") == (
        SanitizationStatus.PENDING
    )
    world.commit_page()
    assert world.ledger.reconcile_page(BANK, "stream", "other-page") == (
        SanitizationStatus.PENDING
    )
    first, second, third = world.events
    world.ledger.write_event_receipts(
        [receipt(first, ProcessingStatus.TDS_COMMITTED)]
    )
    root = world.root()
    assert world.ledger.reconcile_page(BANK, "stream", "page-1") == (
        SanitizationStatus.PENDING
    )
    assert world.ledger.page_closure(BANK, "page-1") is None
    world.ledger.write_event_receipts(
        [
            receipt(second, ProcessingStatus.TDS_COMMITTED),
            receipt(third, ProcessingStatus.FILTERED_LENGTH),
        ]
    )
    assert world.ledger.reconcile_page(BANK, "stream", "page-1") == (
        SanitizationStatus.RESOLVED
    )
    closure = world.ledger.page_closure(BANK, "page-1")
    assert (
        closure.tds_committed,
        closure.filtered_length,
        closure.missing,
    ) == (
        2,
        1,
        0,
    )
    assert closure.reason is None and closure.content_fingerprint == "b" * 64
    # La sanitización nunca escribe en la raíz ni en manifiestos de ingesta.
    assert world.root() == root
    assert world.ledger.reconcile_page(BANK, "stream", "page-1") == (
        SanitizationStatus.RESOLVED
    )


def test_quarantine_and_expired_staging_are_explicit_gaps():
    world = World()
    world.commit_page()
    first, second, third = world.events
    world.ledger.write_event_receipts(
        [
            receipt(first, ProcessingStatus.TDS_COMMITTED),
            receipt(second, ProcessingStatus.QUARANTINED, error_code="X"),
        ]
    )
    assert world.ledger.reconcile_page(BANK, "stream", "page-1") == (
        SanitizationStatus.PENDING
    )
    status = world.ledger.reconcile_page(
        BANK, "stream", "page-1", staging_expired=True
    )
    assert status == SanitizationStatus.GAPS_DETECTED
    closure = world.ledger.page_closure(BANK, "page-1")
    assert closure.reason == pl.STAGING_EXPIRED
    assert closure.missing_event_ids == (third.event_id,)
    assert closure.quarantined_event_ids == (second.event_id,)
    quarantined = World()
    quarantined.commit_page()
    quarantined.ledger.write_event_receipts(
        [
            receipt(e, ProcessingStatus.QUARANTINED, error_code="X")
            for e in quarantined.events
        ]
    )
    assert quarantined.ledger.reconcile_page(BANK, "stream", "page-1") == (
        SanitizationStatus.GAPS_DETECTED
    )
    assert quarantined.ledger.page_closure(BANK, "page-1").reason == (
        pl.QUARANTINED
    )


def test_page_closure_contract():
    base = {
        "bank_id": BANK,
        "page_id": "p",
        "stream_id": "s",
        "manifest_version": 1,
        "content_fingerprint": "f",
        "closed_at": T0,
    }
    for invalid in (
        {"status": SanitizationStatus.PENDING},
        {
            "status": SanitizationStatus.RESOLVED,
            "missing": 1,
            "missing_event_ids": ("e",),
        },
        {"status": SanitizationStatus.GAPS_DETECTED},
        {
            "status": SanitizationStatus.GAPS_DETECTED,
            "reason": "X",
            "missing": 2,
            "missing_event_ids": ("e",),
        },
    ):
        with pytest.raises(ValueError):
            pl.PageClosure(**(base | invalid))
    with pytest.raises(ValueError):
        pl.ProcessingLedgerRepository(
            FakeStorage(),
            "bad/bucket",
            Mock(),  # type: ignore[arg-type]
        )
