"""Exercise actual repository algorithms with generation-enforcing fake GCS."""

import asyncio
import copy
import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import httpx
import pytest
from google.api_core.exceptions import (
    NotFound,
    PreconditionFailed,
    ServiceUnavailable,
)
from ingestion_worker.audit import AuditDeliveryError, BigQueryAuditWriter
from ingestion_worker.main import create_app
from ingestion_worker.watermark_store import (
    IntegrityError,
    LeaseConflict,
    ObjectReference,
    ReviewLedgerEntry,
    StateConflict,
    WatermarkRepository,
)
from pydantic import ValidationError
from voc_common import (
    PLAYSTORE_BANK_APPS,
    BankKey,
    HistoricalPlan,
    IngestionMode,
    IngestionRunAudit,
    IngestionStorageLayout,
    PageManifest,
    PlanExtensionEvent,
    PublicationStatus,
    RunAuditStatus,
    ScanContext,
    ScanStatus,
    ScanStreamState,
    compute_event_id,
)

BANK = BankKey.BBVA
APP = PLAYSTORE_BANK_APPS[BANK]
T0 = datetime(2026, 10, 14, tzinfo=UTC)
CURSOR = "opaque-cursor-private"
IDENTITY = {"bank_id": BANK, "app_id": APP}


class FakeBlob:
    def __init__(self, bucket, name):
        self.bucket, self.name = bucket, name
        self._metadata = None
        self.generation = None

    @property
    def metadata(self):
        # Como google-cloud-storage 3.x: el getter devuelve una copia, así que
        # mutar `blob.metadata[k] = v` no persiste.
        return copy.deepcopy(self._metadata)

    @metadata.setter
    def metadata(self, value):
        self._metadata = copy.deepcopy(value)

    def _get(self, expected=None):
        if self.name not in self.bucket.objects:
            raise NotFound("missing")
        record = self.bucket.objects[self.name]
        if expected is not None and record["generation"] != expected:
            raise PreconditionFailed("changed")
        return record

    def reload(self, *, if_generation_match=None, timeout=None):
        record = self._get(if_generation_match)
        self.generation = record["generation"]
        self.metadata = copy.deepcopy(record["metadata"])

    def download_as_bytes(self, *, if_generation_match=None, timeout=None):
        if self.bucket.before_download:
            hook, self.bucket.before_download = (
                self.bucket.before_download,
                None,
            )
            hook(self.name)
        return self._get(if_generation_match)["data"]

    def upload_from_string(
        self, data, *, content_type, if_generation_match, timeout
    ):
        if self.bucket.before_upload:
            self.bucket.before_upload(self.name)
        record = self.bucket.objects.get(self.name)
        current = record["generation"] if record else 0
        if current != if_generation_match:
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

    def __init__(self):
        self.objects = {}
        self.counter = 0
        self.before_upload = None
        self.before_download = None

    def blob(self, name):
        return FakeBlob(self, name)


class FakeClient:
    def __init__(self):
        self.value = FakeBucket()

    def bucket(self, _):
        return self.value


@pytest.fixture
def env():
    client = FakeClient()
    now = [T0]
    repo = WatermarkRepository(
        client, "test-bucket", clock=lambda: now[0], lease_duration_sec=120
    )
    return repo, client.value, now


def stream(plan_id=None):
    return ScanStreamState(
        **IDENTITY,
        stream_id="stream",
        plan_id=plan_id,
        context=ScanContext(app_id=APP, protocol_version="test"),
    )


def setup(env, historical=False):
    repo, bucket, now = env
    handle = repo.acquire_lease(BANK, "run")
    s = stream("plan" if historical else None)
    plan = (
        HistoricalPlan(
            **IDENTITY,
            plan_id="plan",
            started_at=T0,
            upper_anchor_at=T0,
            requested_lower_at=T0 - timedelta(days=365),
            stream_ids=("stream",),
        )
        if historical
        else None
    )
    repo.register(handle, [s], plan=plan)
    if not historical:
        repo.start_incremental(handle, s.stream_id)
    return handle


def review(number=0, at=T0):
    revision = hashlib.sha256(str(number).encode()).hexdigest()
    rid = f"review-{number}"
    return ReviewLedgerEntry(
        review_id=rid,
        source_revision=revision,
        event_id=compute_event_id(BANK, rid, revision),
        reviewed_at=at,
    )


def page(env, *, ordinal=0, **kwargs):
    repo, bucket, now = env
    ledger = repo.write_review_ledger(
        BANK, f"reviews-{ordinal}", [review(ordinal)]
    )
    backup_name = f"raw_staging/BBVA/run/page-{ordinal}/fetch.json.gz"
    backup = bucket.blob(backup_name)
    backup.upload_from_string(
        b"raw backup",
        content_type="application/gzip",
        if_generation_match=0,
        timeout=30,
    )
    values = dict(
        **IDENTITY,
        page_id=f"page-{ordinal}",
        stream_id="stream",
        fetch_attempt_id="fetch",
        run_id="run",
        chain_epoch=0,
        ordinal=ordinal,
        context=stream().context,
        fetched_at=now[0],
        ledger=ledger,
        raw_count=1,
        valid_count=1,
        discarded_count=0,
        published_count=1,
        publication_status=PublicationStatus.PUBLISHED,
        observed_min_at=T0,
        observed_max_at=T0,
        content_fingerprint="a" * 64,
        backup_uri=f"gs://test-bucket/{backup_name}",
        backup_generation=backup.generation,
        output_token=CURSOR,
    )
    return PageManifest(**(values | kwargs))


def commit(repo, handle, manifest):
    return repo.commit_page(
        handle, manifest, expected_revision=repo.load(BANK).state.revision
    )


def replace(model, **kwargs):
    return type(model).model_validate(model.model_dump() | kwargs)


def event(event_id="audit", **kwargs):
    return IngestionRunAudit(
        **(
            dict(
                **IDENTITY,
                audit_event_id=event_id,
                run_id="run",
                mode_executed=IngestionMode.INCREMENTAL,
                status=RunAuditStatus.STARTED,
                updated_at=T0,
            )
            | kwargs
        )
    )


def test_bootstrap_and_strict_v2(env):
    repo, bucket, now = env
    empty = repo.load(BANK)
    assert empty.generation == 0 and empty.state.revision == 0
    assert not bucket.objects
    handle = repo.acquire_lease(BANK, "run")
    loaded = repo.load(BANK)
    assert loaded.state.schema_version == 2 and loaded.lease.epoch == 1
    assert loaded.lease.expires_at == T0 + timedelta(seconds=120)
    blob = bucket.blob(repo._root(BANK))
    blob.reload()
    blob.upload_from_string(
        b'{"schema_version":1}',
        content_type="application/json",
        if_generation_match=blob.generation,
        timeout=30,
    )
    with pytest.raises(ValidationError):
        repo.renew_lease(handle)


def test_lease_conflict_heartbeat_release_and_takeover(env):
    repo, bucket, now = env
    first = repo.acquire_lease(BANK, "run")
    with pytest.raises(LeaseConflict):
        repo.acquire_lease(BANK, "run")
    now[0] += timedelta(seconds=20)
    repo.renew_lease(first)
    assert repo.load(BANK).lease.expires_at == now[0] + timedelta(seconds=120)
    repo.release_lease(first)
    second = repo.acquire_lease(BANK, "other")
    assert second.epoch == first.epoch + 1
    for operation in (repo.renew_lease, repo.release_lease):
        with pytest.raises(LeaseConflict):
            operation(first)
    now[0] += timedelta(seconds=120)
    with pytest.raises(LeaseConflict):
        repo.renew_lease(second)
    third = repo.acquire_lease(BANK, "next")
    assert third.epoch == 3


def test_read_retries_when_generation_changes_between_metadata_and_body(env):
    repo, bucket, now = env
    handle = repo.acquire_lease(BANK, "run")

    def heartbeat(_):
        repo.renew_lease(handle)

    bucket.before_download = heartbeat
    snapshot = repo.load(BANK)
    assert snapshot.generation == bucket.objects[repo._root(BANK)]["generation"]


def test_page_commit_duplicate_and_full_chain(env):
    repo, bucket, now = env
    handle = setup(env)
    first = page(env)
    committed = commit(repo, handle, first)
    assert committed.state.incremental.candidate_high_at == T0
    assert committed.state.incremental.committed_high_at is None
    s = repo.get_stream(committed, "stream")
    assert s.committed_pages == s.committed_reviews == 1
    assert commit(repo, handle, first) == committed
    with pytest.raises(IntegrityError):
        commit(repo, handle, replace(first, fetch_attempt_id="other"))
    second = page(
        env, ordinal=1, previous_page_id=first.page_id, input_token=CURSOR
    )
    result = commit(repo, handle, second)
    assert repo.get_stream(result, "stream").committed_pages == 2
    assert result.state.manifest_ledger.entry_count == 2
    assert len(list(repo.iter_ledger(result.state.manifest_ledger))) == 2
    assert repo.find_page(result, "stream", first.page_id) == first
    old = repo.get_stream(committed, "stream")
    assert old.committed_pages == 1  # old snapshot remains readable


def test_cas_failure_keeps_orphans_invisible_and_retry_reconciles(env):
    repo, bucket, now = env
    handle = setup(env)
    manifest = page(env)
    old = repo.load(BANK)

    def race(name):
        if name == repo._root(BANK):
            bucket.before_upload = None
            repo.renew_lease(handle)

    bucket.before_upload = race
    with pytest.raises(StateConflict):
        commit(repo, handle, manifest)
    unchanged = repo.load(BANK)
    assert unchanged.state == old.state
    assert repo.find_page(unchanged, "stream", manifest.page_id) is None
    assert any("/manifests/" in name for name in bucket.objects)
    result = commit(repo, handle, manifest)
    assert result.state.revision == old.state.revision + 1
    assert repo.get_stream(result, "stream").committed_reviews == 1


def test_takeover_during_inflight_commit_fences_old_writer(env):
    repo, bucket, now = env
    handle = setup(env)
    manifest = page(env)

    def takeover(name):
        if name == repo._root(BANK):
            bucket.before_upload = None
            now[0] += timedelta(seconds=120)
            repo.acquire_lease(BANK, "new-owner")

    bucket.before_upload = takeover
    with pytest.raises(StateConflict):
        commit(repo, handle, manifest)
    assert repo.load(BANK).state.manifest_ledger is None
    with pytest.raises(LeaseConflict):
        commit(repo, handle, manifest)


@pytest.mark.parametrize("change", ["backup", "ledger", "revision", "partial"])
def test_missing_evidence_or_stale_revision_never_advances(env, change):
    repo, bucket, now = env
    handle = setup(env)
    manifest = page(env)
    old = repo.load(BANK)
    revision = old.state.revision
    error = IntegrityError
    if change == "backup":
        del bucket.objects[repo._name(manifest.backup_uri)]
    elif change == "ledger":
        bucket.objects[repo._name(manifest.ledger.uri)]["data"] = b"altered"
    elif change == "revision":
        revision -= 1
        error = StateConflict
    else:
        manifest = replace(
            manifest,
            publication_status=PublicationStatus.PENDING,
            published_count=0,
        )
        error = ValueError
    with pytest.raises(error):
        repo.commit_page(handle, manifest, expected_revision=revision)
    assert repo.load(BANK).state == old.state


def test_ledger_keeps_all_ids_above_500_and_detects_changed_generation(env):
    repo, bucket, now = env
    entries = [review(n) for n in range(1001)]
    ref = repo.write_review_ledger(BANK, "large", entries, page_size=100)
    actual = list(repo.iter_ledger(ref))
    assert ref.entry_count == 1001
    assert {x["event_id"] for x in actual} == {x.event_id for x in entries}
    record = bucket.objects[repo._name(ref.uri)]
    record["generation"] += 1
    with pytest.raises(IntegrityError):
        list(repo.iter_ledger(ref))


def test_immutable_manifest_collision_and_safe_ids(env):
    repo, bucket, now = env
    manifest = page(env)
    ref = repo.put_manifest(manifest)
    assert repo.put_manifest(manifest) == ref
    with pytest.raises(IntegrityError):
        repo.put_manifest(replace(manifest, output_token=CURSOR + "-different"))
    with pytest.raises(ValueError):
        repo.put_manifest(replace(manifest, page_id="../bad"))
    with pytest.raises(ValueError):
        repo.acquire_lease(BANK, "../run")
    with pytest.raises(IntegrityError):
        repo._read_ref(
            ObjectReference(
                uri="gs://other-bucket/key",
                generation=1,
                content_fingerprint="a" * 64,
            )
        )


def test_register_plan_and_extend_preserves_t0_and_stream(env):
    repo, bucket, now = env
    handle = setup(env, historical=True)
    old = repo.load(BANK)
    plan = repo.get_plan(old, "plan")
    assert repo.register(handle, [stream("plan")], plan=plan) == old
    extension = PlanExtensionEvent(
        event_id="extension",
        extended_at=T0,
        previous_lower_at=plan.requested_lower_at,
    )
    updated = repo.extend_plan(handle, "plan", extension)
    actual = repo.get_plan(updated, "plan")
    assert actual.requested_lower_at is None
    assert actual.started_at == plan.started_at
    assert repo.get_stream(updated, "stream") == stream("plan")
    assert repo.extend_plan(handle, "plan", extension) == updated
    repo.set_stream_status(handle, "stream", ScanStatus.RUNNING)
    paused = repo.set_stream_status(handle, "stream", ScanStatus.PAUSED)
    assert repo.get_stream(paused, "stream").status == ScanStatus.PAUSED


def test_persistent_index_splits_without_losing_pages(env):
    repo, bucket, now = env
    ref = None
    refs = []
    for n in range(140):
        value = ObjectReference(
            uri=f"gs://test-bucket/manifest-{n}",
            generation=1,
            content_fingerprint="a" * 64,
        )
        key = repo._index_key("stream", f"page-{n}")
        ref = repo._index_put(BANK, ref, key, value)
        refs.append((key, value))
    for key, value in refs:
        assert repo._index_get(ref, key) == value
    assert repo._index_get(ref, "f" * 64) is None


def test_audit_outbox_survives_bq_error_and_reuses_event_id(env):
    repo, bucket, now = env
    handle = setup(env)
    queued = repo.record_audit(handle, event())
    assert repo.record_audit(handle, event()) == queued
    with pytest.raises(IntegrityError):
        repo.record_audit(handle, event(reason="other"))
    bq = Mock()
    bq.insert_rows_json.return_value = [{"errors": [{"message": "private"}]}]
    writer = BigQueryAuditWriter(
        bq, project="test-project", dataset="tds", table="custom_audit"
    )
    with pytest.raises(AuditDeliveryError, match="rejected") as caught:
        writer.flush(repo, BANK)
    assert "private" not in str(caught.value)
    assert list(repo.iter_audits(repo.load(BANK))) == [event()]
    assert not repo.audit_delivered(event())
    bq.insert_rows_json.return_value = []
    assert writer.flush(repo, BANK) == 1
    call = bq.insert_rows_json.call_args
    assert call.args[0] == "test-project.tds.custom_audit"
    assert call.kwargs["row_ids"] == ["audit"]
    assert "input_token" not in call.args[1][0]
    assert writer.flush(repo, BANK) == 0


def test_audit_crash_after_bq_confirmation_can_duplicate_with_same_id(env):
    repo, bucket, now = env
    handle = setup(env)
    repo.record_audit(handle, event())
    bq = Mock()
    bq.insert_rows_json.return_value = []
    writer = BigQueryAuditWriter(
        bq, project="test-project", dataset="tds", table="runs"
    )

    def fail_marker(name):
        if "audit-delivered" in name:
            raise ServiceUnavailable("marker failed")

    bucket.before_upload = fail_marker
    with pytest.raises(ServiceUnavailable):
        writer.flush(repo, BANK)
    bucket.before_upload = None
    assert writer.flush(repo, BANK) == 1
    assert bq.insert_rows_json.call_count == 2
    assert [
        c.kwargs["row_ids"] for c in bq.insert_rows_json.call_args_list
    ] == ([["audit"], ["audit"]])


def test_audit_delivery_network_error_and_budget(env):
    repo, bucket, now = env
    handle = setup(env)
    repo.record_audit(handle, event("one"))
    repo.record_audit(handle, event("two"))
    bq = Mock()
    bq.insert_rows_json.side_effect = ServiceUnavailable("private")
    writer = BigQueryAuditWriter(
        bq, project="test-project", dataset="tds", table="runs"
    )
    with pytest.raises(AuditDeliveryError, match="request failed"):
        writer.flush(repo, BANK)
    bq.insert_rows_json.side_effect = None
    bq.insert_rows_json.return_value = []
    assert writer.flush(repo, BANK, max_events=1) == 1
    assert writer.flush(repo, BANK) == 1
    with pytest.raises(ValueError):
        writer.flush(repo, BANK, max_events=0)


def test_readonly_progress_endpoint_excludes_tokens_and_cloud_references(env):
    repo, bucket, now = env

    class APIClient:
        def get(self, url):
            async def request():
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=create_app(repo)),
                    base_url="http://test",
                ) as client:
                    return await client.get(url)

            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(request())
            finally:
                loop.close()

    api = APIClient()
    assert api.get("/api/v1/watermarks/BBVA").json()["persisted"] is False
    assert not bucket.objects
    handle = setup(env)
    commit(repo, handle, page(env))
    response = api.get("/api/v1/watermarks/BBVA")
    assert response.status_code == 200
    body = response.json()
    assert body["coverage"] == "UNVERIFIED"
    assert body["committed_high_at"] is None
    assert body["streams"][0]["committed_reviews"] == 1
    assert CURSOR not in response.text and "gs://" not in response.text
    assert "percent" not in response.text
    assert api.get("/api/v1/watermarks/UNKNOWN").status_code == 422
    bucket.objects[repo._root(BANK)]["metadata"]["catalog"] = (
        '{"uri":"gs://other/key","generation":1,'
        '"content_fingerprint":"' + "a" * 64 + '"}'
    )
    assert api.get("/api/v1/watermarks/BBVA").status_code == 503


def test_audit_orphan_after_failed_cas_is_not_delivered(env):
    repo, bucket, now = env
    handle = setup(env)

    def race(name):
        if name == repo._root(BANK):
            bucket.before_upload = None
            repo.renew_lease(handle)

    bucket.before_upload = race
    with pytest.raises(StateConflict):
        repo.record_audit(handle, event())
    bq = Mock()
    bq.insert_rows_json.return_value = []
    writer = BigQueryAuditWriter(
        bq, project="test-project", dataset="tds", table="runs"
    )
    assert writer.flush(repo, BANK) == 0
    bq.insert_rows_json.assert_not_called()
    repo.record_audit(handle, event())
    assert writer.flush(repo, BANK) == 1


def test_custom_layout_and_lazy_factories_use_settings(env, monkeypatch):
    from ingestion_worker import main
    from voc_common import Settings

    repo, bucket, now = env
    settings = Settings(
        _env_file=None,
        ingestion_v2_enabled=True,
        bq_ingestion_runs_log_table="configured_audits",
        gcs_watermark_prefix="durable/roots",
        gcs_ingestion_state_prefix="durable/metadata",
        gcs_ingestion_manifests_prefix="durable/metadata/manifests",
        gcs_ingestion_ledgers_prefix="durable/metadata/ledgers",
        gcs_processing_receipts_prefix="durable/metadata/receipts",
    )
    bq = Mock()
    writer = BigQueryAuditWriter.from_settings(bq, settings)
    assert writer.table.endswith(".configured_audits")
    client = FakeClient()
    monkeypatch.setattr(main, "Settings", lambda: settings)
    monkeypatch.setattr(main.storage, "Client", lambda **_: client)
    main.get_repository.cache_clear()
    try:
        configured = main.get_repository()
        assert configured.layout == IngestionStorageLayout.model_validate(
            {
                key: getattr(settings, key)
                for key in IngestionStorageLayout.model_fields
            }
        )
        configured.acquire_lease(BANK, "run")
        assert "durable/roots/BBVA.json" in client.value.objects
    finally:
        main.get_repository.cache_clear()
    disabled = Settings(_env_file=None, ingestion_v2_enabled=False)
    with pytest.raises(ValueError):
        BigQueryAuditWriter.from_settings(bq, disabled)


def test_receipts_are_immutable_and_use_configured_path(env):
    from voc_common import ProcessingReceipt, ProcessingStatus

    repo, bucket, now = env
    entry = review()
    receipt = ProcessingReceipt(
        **IDENTITY,
        receipt_id="receipt",
        event_id=entry.event_id,
        review_id=entry.review_id,
        source_revision=entry.source_revision,
        page_id="page",
        status=ProcessingStatus.RETRYABLE_ERROR,
        error_code="UPSTREAM_FAILED",
        processed_at=T0,
    )
    ref = repo.put_receipt(receipt)
    assert ref.uri.endswith("/receipts/BBVA/page/receipt.json")
    assert repo.put_receipt(receipt) == ref
    with pytest.raises(IntegrityError):
        repo.put_receipt(replace(receipt, error_code="OTHER"))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"project": "bad.project", "dataset": "tds", "table": "runs"},
        {"project": "project", "dataset": "tds;drop", "table": "runs"},
        {
            "project": "project",
            "dataset": "tds",
            "table": "runs",
            "timeout_sec": 0,
        },
    ],
)
def test_audit_destination_rejects_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        BigQueryAuditWriter(Mock(), **kwargs)


def test_initial_acquisition_race_does_not_overwrite_new_owner(env):
    repo, bucket, now = env

    def other_wins(name):
        if name == repo._root(BANK):
            bucket.before_upload = None
            repo.acquire_lease(BANK, "winner")

    bucket.before_upload = other_wins
    with pytest.raises(StateConflict):
        repo.acquire_lease(BANK, "loser")
    assert repo.load(BANK).lease.owner_run_id == "winner"


def test_invalid_ledger_identities_and_counts_are_rejected(env):
    repo, bucket, now = env
    entry = review()
    with pytest.raises(ValueError):
        repo.write_review_ledger(BANK, "dup", [entry, entry])
    with pytest.raises(ValueError):
        repo.write_review_ledger(
            BANK, "bad", [replace(entry, event_id="b" * 64)]
        )
    with pytest.raises(ValueError):
        repo.write_review_ledger(BANK, "bad", [entry], page_size=0)
    ref = repo.write_review_ledger(BANK, "valid", [entry])
    with pytest.raises(IntegrityError, match="count"):
        list(repo.iter_ledger(replace(ref, entry_count=2)))
    assert (
        list(repo.iter_ledger(repo.write_review_ledger(BANK, "empty", [])))
        == []
    )


# Feature 3.3: exercise publisher + repository together across crash boundaries.
@pytest.fixture
def durable(env):
    from pathlib import Path

    from ingestion_worker import PROTOCOL_VERSION, parse_batchexecute_response
    from ingestion_worker.publisher import RawReviewBatchPublisher

    repo, bucket, now = env
    handle = repo.acquire_lease(BANK, "run")
    s = ScanStreamState(
        **IDENTITY,
        stream_id="stream",
        context=ScanContext(app_id=APP, protocol_version=PROTOCOL_VERSION),
    )
    repo.register(handle, [s])
    repo.start_incremental(handle, s.stream_id)
    parsed = parse_batchexecute_response(
        (Path(__file__).parent / "fixtures" / "observed_015.txt").read_bytes(),
        bank_id=BANK,
        app_id=APP,
    )
    pubsub = Mock()
    futures = []

    def publish(*args, **kwargs):
        assert repo.load(BANK).catalog.pending
        future = Mock()
        future.result.return_value = "message"
        futures.append(future)
        return future

    pubsub.publish.side_effect = publish
    publisher = RawReviewBatchPublisher(
        repo, pubsub, "projects/test-project/topics/raw"
    )
    return publisher, handle, s, parsed, pubsub, futures


def prepare(durable, env):
    publisher, handle, s, parsed, *_ = durable
    return publisher.prepare_page(
        handle,
        s,
        parsed,
        mode=IngestionMode.INCREMENTAL,
        fetched_at=env[2][0],
        fetch_attempt_id="capture",
    )


def test_durable_backup_precedes_publication_and_commit(durable, env):
    import gzip
    import json

    repo, bucket, now = env
    publisher, handle, s, parsed, pubsub, futures = durable
    manifest = prepare(durable, env)
    assert manifest.publication_status == PublicationStatus.PENDING
    snapshot = repo.load(BANK)
    assert repo.get_stream(snapshot, s.stream_id).committed_pages == 0
    capture = repo.pending_capture(snapshot, manifest.page_id)
    lines = gzip.decompress(repo.read_object(capture.backup)).splitlines()
    assert len(lines) == 1 + len(parsed.reviews)
    assert json.loads(lines[0])["discarded"] == []
    assert prepare(durable, env) == manifest
    result = publisher.publish_page(handle, manifest)
    assert result.catalog.pending == {}
    committed = repo.find_page(result, s.stream_id, manifest.page_id)
    assert committed.publication_status == PublicationStatus.PUBLISHED
    assert committed.sanitization_status.value == "PENDING"
    assert result.state.coverage.value == "UNVERIFIED"
    assert result.state.incremental.committed_high_at is None
    assert len(futures) == len(parsed.reviews)
    for future in futures:
        future.result.assert_called_once()
        assert 0 <= future.result.call_args.kwargs["timeout"] <= 30
    for call in pubsub.publish.call_args_list:
        message = json.loads(call.args[1])
        assert call.kwargs["page_id"] == manifest.page_id
        assert call.kwargs["event_id"] == message["event_id"]
        assert call.kwargs["source_revision"] == message["source_revision"]
        assert call.kwargs["mode"] == "INCREMENTAL"
    count = pubsub.publish.call_count
    assert publisher.publish_page(handle, manifest) == result
    assert prepare(durable, env) == committed
    assert pubsub.publish.call_count == count


def test_partial_publication_resolves_every_future_and_replays_stable_ids(
    durable, env
):
    from ingestion_worker.publisher import PublicationIncomplete

    repo, bucket, now = env
    publisher, handle, s, parsed, pubsub, futures = durable
    manifest = prepare(durable, env)
    original = pubsub.publish.side_effect

    def partial(*args, **kwargs):
        future = original(*args, **kwargs)
        if len(futures) != 2:
            future.result.side_effect = TimeoutError("private upstream detail")
        return future

    pubsub.publish.side_effect = partial
    with pytest.raises(PublicationIncomplete) as caught:
        publisher.publish_page(handle, manifest)
    assert caught.value.manifest.publication_status == PublicationStatus.PARTIAL
    assert caught.value.manifest.published_count == 1
    assert "private" not in str(caught.value)
    assert all(f.result.call_count == 1 for f in futures)
    snapshot = repo.load(BANK)
    assert repo.get_stream(snapshot, "stream").committed_pages == 0
    assert snapshot.state.manifest_ledger is None
    before = [c.args[1] for c in pubsub.publish.call_args_list]
    pubsub.publish.side_effect = original
    result = publisher.publish_page(handle, manifest)
    after = [c.args[1] for c in pubsub.publish.call_args_list][len(before) :]
    assert after == before
    assert repo.get_stream(result, "stream").committed_reviews == len(
        parsed.reviews
    )


@pytest.mark.parametrize("failure_point", [1, 2])
def test_publication_and_cas_crashes_remain_recoverable(
    durable, env, failure_point
):
    repo, bucket, now = env
    publisher, handle, s, parsed, pubsub, futures = durable
    manifest = prepare(durable, env)
    writes = []

    def race(name):
        if name == repo._root(BANK):
            writes.append(name)
            if len(writes) == failure_point:
                bucket.before_upload = None
                repo.renew_lease(handle)

    bucket.before_upload = race
    with pytest.raises(StateConflict):
        publisher.publish_page(handle, manifest)
    assert repo.get_stream(repo.load(BANK), "stream").committed_pages == 0
    sent = pubsub.publish.call_count
    result = publisher.publish_page(handle, manifest)
    assert repo.get_stream(result, "stream").committed_pages == 1
    assert pubsub.publish.call_count == sent * (2 if failure_point == 1 else 1)


@pytest.mark.parametrize("kind", ["missing", "changed", "corrupt"])
def test_lost_or_changed_backup_requires_recovery_without_progress(
    durable, env, kind
):
    from ingestion_worker.publisher import BackupUnavailable

    repo, bucket, now = env
    publisher, handle, s, parsed, pubsub, futures = durable
    manifest = prepare(durable, env)
    name = repo._name(manifest.backup_uri)
    if kind == "missing":
        del bucket.objects[name]
    elif kind == "changed":
        bucket.objects[name]["generation"] += 1
    else:
        bucket.objects[name]["data"] = b"corrupt"
    with pytest.raises(BackupUnavailable):
        publisher.publish_page(handle, manifest)
    assert repo.get_stream(repo.load(BANK), "stream").committed_pages == 0
    assert manifest.page_id in repo.load(BANK).catalog.pending
    pubsub.publish.assert_not_called()


def edit_response(parsed, *, no_text=False, change_votes=False):
    import json

    from ingestion_worker import parse_batchexecute_response

    outer = json.loads(parsed.raw_body.decode().split("\n", 1)[1])
    inner = json.loads(outer[0][2])
    if no_text:
        for entry in inner[0]:
            entry[4] = None
    if change_votes:
        inner[0][0][6] += 1
    outer[0][2] = json.dumps(inner)
    return parse_batchexecute_response(
        json.dumps(outer).encode(), bank_id=BANK, app_id=APP
    )


def test_nontext_page_advances_cursor_with_durable_discard_reasons(
    durable, env
):
    repo, bucket, now = env
    publisher, handle, s, parsed, pubsub, futures = durable
    no_text = edit_response(parsed, no_text=True)
    manifest = publisher.prepare_page(
        handle,
        s,
        no_text,
        mode=IngestionMode.INCREMENTAL,
        fetched_at=now[0],
        fetch_attempt_id="nontext",
    )
    assert manifest.valid_count == 0
    assert manifest.discard_ledger.entry_count == no_text.raw_count
    result = publisher.publish_page(handle, manifest)
    updated = repo.get_stream(result, "stream")
    assert updated.committed_pages == 1 and updated.committed_reviews == 0
    assert updated.output_token == no_text.next_token
    assert updated.status == ScanStatus.RUNNING
    assert result.state.incremental.candidate_high_at == no_text.observed_max_at
    reasons = list(repo.iter_ledger(manifest.discard_ledger))
    assert all(d["reason"] == "NO_TEXT" for d in reasons)
    assert len(reasons) == no_text.raw_count
    pubsub.publish.assert_not_called()


def test_changed_capture_has_another_page_id(durable, env):
    publisher, handle, s, parsed, *_ = durable
    first = prepare(durable, env)
    changed = publisher.prepare_page(
        handle,
        s,
        edit_response(parsed, change_votes=True),
        mode=IngestionMode.INCREMENTAL,
        fetched_at=env[2][0],
        fetch_attempt_id="changed",
    )
    assert changed.page_id != first.page_id
    assert changed.content_fingerprint != first.content_fingerprint


def test_forged_parser_result_and_invalid_context_never_publish(durable, env):
    from dataclasses import replace as dataclass_replace

    from ingestion_worker import ProtocolError

    publisher, handle, s, parsed, pubsub, _ = durable
    with pytest.raises(IntegrityError):
        publisher.prepare_page(
            handle,
            s,
            dataclass_replace(parsed, raw_count=100),
            mode=IngestionMode.INCREMENTAL,
            fetched_at=env[2][0],
            fetch_attempt_id="forged",
        )
    with pytest.raises(ProtocolError):
        publisher.prepare_page(
            handle,
            replace(s, context=replace(s.context, protocol_version="other")),
            parsed,
            mode=IngestionMode.INCREMENTAL,
            fetched_at=env[2][0],
            fetch_attempt_id="bad-context",
        )
    pubsub.publish.assert_not_called()


def test_synchronous_publish_failure_preserves_pending_page(durable, env):
    from ingestion_worker.publisher import PublicationIncomplete

    repo, bucket, now = env
    publisher, handle, s, parsed, pubsub, futures = durable
    manifest = prepare(durable, env)
    pubsub.publish.side_effect = RuntimeError("publisher stopped")
    with pytest.raises(PublicationIncomplete) as caught:
        publisher.publish_page(handle, manifest)
    assert caught.value.manifest.published_count == 0
    assert caught.value.manifest.publication_status == PublicationStatus.PENDING
    assert repo.get_stream(repo.load(BANK), "stream").committed_pages == 0


def test_expired_lease_cannot_publish_pending_capture(durable, env):
    repo, bucket, now = env
    publisher, handle, s, parsed, pubsub, futures = durable
    manifest = prepare(durable, env)
    now[0] += timedelta(seconds=120)
    repo.acquire_lease(BANK, "next")
    with pytest.raises(LeaseConflict):
        publisher.publish_page(handle, manifest)
    pubsub.publish.assert_not_called()


def test_initial_staging_cas_failure_reuses_identical_backup(durable, env):
    repo, bucket, now = env
    publisher, handle, s, parsed, pubsub, futures = durable

    def race(name):
        if name == repo._root(BANK):
            bucket.before_upload = None
            repo.renew_lease(handle)

    bucket.before_upload = race
    with pytest.raises(StateConflict):
        prepare(durable, env)
    backups = {
        name: copy.deepcopy(obj)
        for name, obj in bucket.objects.items()
        if name.endswith(".jsonl.gz")
    }
    assert len(backups) == 1 and not repo.load(BANK).catalog.pending
    manifest = prepare(durable, env)
    assert bucket.objects[repo._name(manifest.backup_uri)] == next(
        iter(backups.values())
    )
    assert repo.progress(BANK)["pending_pages"][0]["fetched_at"]
    pubsub.publish.assert_not_called()


def test_backup_restore_rejects_invalid_gzip_and_changed_event(durable, env):
    import gzip
    import json

    from ingestion_worker.publisher import BackupUnavailable

    repo, bucket, now = env
    publisher, handle, s, parsed, pubsub, futures = durable
    manifest = prepare(durable, env)
    capture = repo.pending_capture(repo.load(BANK), manifest.page_id)
    raw = repo.read_object(capture.backup)
    from ingestion_worker.publisher import CaptureUnreadable

    with pytest.raises(CaptureUnreadable):
        publisher._restore(manifest, b"invalid gzip", capture.mode)
    lines = gzip.decompress(raw).splitlines()
    event_data = json.loads(lines[1])
    event_data["page_id"] = "other"
    lines[1] = json.dumps(event_data).encode()
    with pytest.raises(BackupUnavailable):
        publisher._restore(
            manifest, gzip.compress(b"\n".join(lines)), capture.mode
        )
    publisher.max_backup_bytes = 1
    with pytest.raises(BackupUnavailable):
        publisher._restore(manifest, raw, capture.mode)


def test_capture_size_budget_rejects_before_any_publication(durable, env):
    publisher, handle, s, parsed, pubsub, futures = durable
    publisher.max_backup_bytes = 1
    with pytest.raises(ValueError, match="budget"):
        prepare(durable, env)
    assert not env[0].load(BANK).catalog.pending
    pubsub.publish.assert_not_called()


def test_future_without_message_id_cannot_commit(durable, env):
    from ingestion_worker.publisher import PublicationIncomplete

    publisher, handle, s, parsed, pubsub, futures = durable
    manifest = prepare(durable, env)
    pubsub.publish.side_effect = lambda *_, **__: Mock(
        result=Mock(return_value=None)
    )
    with pytest.raises(PublicationIncomplete):
        publisher.publish_page(handle, manifest)
    assert env[0].get_stream(env[0].load(BANK), "stream").committed_pages == 0


def test_public_capture_reader_for_committed_pages(durable, env):
    from ingestion_worker.publisher import (
        BackupUnavailable,
        CaptureUnreadable,
        read_committed_capture,
        restore_capture,
    )

    repo, bucket, now = env
    publisher, handle, s, parsed, pubsub, futures = durable
    manifest = prepare(durable, env)
    publisher.publish_page(handle, manifest)
    committed = repo.find_page(repo.load(BANK), s.stream_id, manifest.page_id)
    events = read_committed_capture(repo, committed)
    published = [c.kwargs["event_id"] for c in pubsub.publish.call_args_list]
    assert [e.event_id for e in events] == published[: len(events)]
    assert {e.page_id for e in events} == {committed.page_id}
    raw = repo.read_backup(committed)
    assert restore_capture(committed, raw) == events
    with pytest.raises(BackupUnavailable):
        restore_capture(committed, raw, mode=IngestionMode.BACKFILL)
    name = committed.backup_uri.removeprefix("gs://test-bucket/")
    bucket.objects[name]["generation"] += 1
    with pytest.raises(BackupUnavailable):
        read_committed_capture(repo, committed)
    del bucket.objects[name]
    with pytest.raises(BackupUnavailable) as missing:
        read_committed_capture(repo, committed)
    # Ausente o reemplazada no es "ilegible": solo esa es recuperable.
    assert not isinstance(missing.value, CaptureUnreadable)
