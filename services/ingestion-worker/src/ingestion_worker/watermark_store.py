"""GCS repository: immutable children, one fenced CAS publication point."""

import hashlib
import json
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Self, TypeVar

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage
from pydantic import BaseModel, ConfigDict, Field, model_validator
from voc_common import (
    PLAYSTORE_BANK_APPS,
    BankKey,
    HistoricalPlan,
    IngestionMode,
    IngestionRunAudit,
    IngestionStorageLayout,
    IngestionWatermarkState,
    LedgerReference,
    PageManifest,
    PlanExtensionEvent,
    ProcessingReceipt,
    PublicationStatus,
    ScanStatus,
    ScanStreamState,
    begin_incremental,
    change_stream_status,
    commit_page,
    compute_event_id,
    extend_to_full,
)
from voc_common.schemas import Digest, NonEmpty, UtcDatetime, ensure_utc

Model = TypeVar("Model", bound=BaseModel)


class StateConflict(RuntimeError):
    """CAS lost: reread/reconcile; never blindly overwrite."""


class LeaseConflict(StateConflict):
    """Lease absent, expired, or fenced by another acquisition."""


class IntegrityError(RuntimeError):
    """Durable object missing, altered, or inconsistent with its reference."""


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ObjectReference(_Frozen):
    uri: NonEmpty
    generation: Annotated[int, Field(gt=0)]
    content_fingerprint: Digest


class Lease(_Frozen):
    owner_run_id: NonEmpty | None = None
    epoch: Annotated[int, Field(ge=0)] = 0
    heartbeat_at: UtcDatetime | None = None
    expires_at: UtcDatetime | None = None


class LeaseHandle(_Frozen):
    bank_id: BankKey
    owner_run_id: NonEmpty
    epoch: Annotated[int, Field(gt=0)]


class ReviewLedgerEntry(_Frozen):
    review_id: NonEmpty
    source_revision: Digest
    event_id: Digest
    reviewed_at: UtcDatetime


class _Node(_Frozen):
    previous: LedgerReference | None = None
    entries: tuple[dict[str, Any], ...]


class PendingCapture(_Frozen):
    manifest: ObjectReference
    backup: ObjectReference
    mode: IngestionMode


class _Catalog(_Frozen):
    pending: dict[str, PendingCapture] = Field(default_factory=dict)
    streams: dict[str, ObjectReference] = Field(default_factory=dict)
    plans: dict[str, ObjectReference] = Field(default_factory=dict)
    audits: LedgerReference | None = None
    manifest_index: ObjectReference | None = None


class _IndexNode(_Frozen):
    children: dict[str, ObjectReference] = Field(default_factory=dict)
    pages: dict[str, ObjectReference] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.children and self.pages:
            raise ValueError("index node cannot be both leaf and branch")
        if len(self.pages) > 128 or any(
            not re.fullmatch(r"[0-9a-f]", key) for key in self.children
        ):
            raise ValueError("invalid index shape")
        return self


@dataclass(frozen=True)
class RepositorySnapshot:
    state: IngestionWatermarkState
    generation: int
    lease: Lease
    catalog: _Catalog = field(repr=False)
    catalog_ref: ObjectReference | None = field(default=None, repr=False)


def _id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("identifier must be a safe path segment (1..128)")
    return value


def _dump(value: BaseModel) -> bytes:
    return json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _replace(model: Model, **changes: Any) -> Model:
    return type(model).model_validate(model.model_dump() | changes)


class WatermarkRepository:
    """Synchronous SDK calls; use a threadpool in async callers.

    Lease metadata and state share a generation. Every root rewrite carries
    both, so a takeover fences in-flight commits without multiobject locking.
    """

    def __init__(
        self,
        client: storage.Client,
        bucket: str,
        *,
        layout: IngestionStorageLayout | None = None,
        lease_duration_sec: int = 120,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        timeout_sec: float = 30,
    ) -> None:
        if lease_duration_sec <= 0 or timeout_sec <= 0:
            raise ValueError("lease duration and timeout must be positive")
        if not bucket or "/" in bucket:
            raise ValueError("bucket must be a bucket name")
        self.bucket = client.bucket(bucket)
        self.layout = layout or IngestionStorageLayout()
        self.lease_duration_sec = lease_duration_sec
        self.clock = clock
        self.timeout_sec = timeout_sec

    def _now(self) -> datetime:
        return ensure_utc(self.clock())

    def _root(self, bank: BankKey) -> str:
        return f"{self.layout.gcs_watermark_prefix}/{bank.value}.json"

    def _base(self, bank: BankKey) -> str:
        return f"{self.layout.gcs_ingestion_state_prefix}/{bank.value}"

    def _name(self, uri: str) -> str:
        prefix = f"gs://{self.bucket.name}/"
        if not uri.startswith(prefix):
            raise IntegrityError("reference points outside configured bucket")
        name = uri[len(prefix) :]
        if not name or any(x in ("", ".", "..") for x in name.split("/")):
            raise IntegrityError("noncanonical object reference")
        return name

    def _read_ref(self, ref: ObjectReference | LedgerReference) -> bytes:
        blob = self.bucket.blob(self._name(ref.uri))
        try:
            data = blob.download_as_bytes(
                if_generation_match=ref.generation, timeout=self.timeout_sec
            )
        except (NotFound, PreconditionFailed):
            raise IntegrityError(
                "referenced object is missing or changed"
            ) from None
        if _sha(data) != ref.content_fingerprint:
            raise IntegrityError("object fingerprint mismatch")
        return data

    def _immutable(
        self, name: str, data: bytes, *, content_type: str = "application/json"
    ) -> ObjectReference:
        blob = self.bucket.blob(name)
        try:
            blob.upload_from_string(
                data,
                content_type=content_type,
                if_generation_match=0,
                timeout=self.timeout_sec,
            )
            generation = int(blob.generation)
        except PreconditionFailed:
            # Reconcile the same ID; never accept a different orphan.
            blob.reload(timeout=self.timeout_sec)
            generation = int(blob.generation)
            ref = ObjectReference(
                uri=f"gs://{self.bucket.name}/{name}",
                generation=generation,
                content_fingerprint=_sha(data),
            )
            self._read_ref(ref)
        return ObjectReference(
            uri=f"gs://{self.bucket.name}/{name}",
            generation=generation,
            content_fingerprint=_sha(data),
        )

    def _object(self, prefix: str, model: BaseModel) -> ObjectReference:
        data = _dump(model)
        return self._immutable(f"{prefix}/{_sha(data)}.json", data)

    def load(self, bank: BankKey) -> RepositorySnapshot:
        # A reload and an unconditioned download can observe different writes.
        for _ in range(3):
            blob = self.bucket.blob(self._root(bank))
            try:
                blob.reload(timeout=self.timeout_sec)
            except NotFound:
                state = IngestionWatermarkState(
                    bank_id=bank,
                    app_id=PLAYSTORE_BANK_APPS[bank],
                    updated_at=self._now(),
                )
                return RepositorySnapshot(state, 0, Lease(), _Catalog())
            generation = int(blob.generation)
            metadata = dict(blob.metadata or {})
            try:
                data = blob.download_as_bytes(
                    if_generation_match=generation, timeout=self.timeout_sec
                )
            except (NotFound, PreconditionFailed):
                continue
            state = IngestionWatermarkState.model_validate_json(data)
            if state.bank_id != bank:
                raise IntegrityError("root identity mismatch")
            lease = Lease.model_validate_json(metadata.get("lease", "{}"))
            catalog_ref = (
                ObjectReference.model_validate_json(metadata["catalog"])
                if "catalog" in metadata
                else None
            )
            catalog = (
                _Catalog.model_validate_json(self._read_ref(catalog_ref))
                if catalog_ref
                else _Catalog()
            )
            if set(state.stream_ids) != set(catalog.streams) or set(
                state.historical_plan_ids
            ) != set(catalog.plans):
                raise IntegrityError("root/catalog registration mismatch")
            return RepositorySnapshot(
                state, generation, lease, catalog, catalog_ref
            )
        raise StateConflict("root changed repeatedly during read")

    def _write_root(
        self,
        previous: RepositorySnapshot,
        state: IngestionWatermarkState,
        lease: Lease,
        catalog: _Catalog,
        catalog_ref: ObjectReference | None,
    ) -> RepositorySnapshot:
        blob = self.bucket.blob(self._root(state.bank_id))
        blob.metadata = {"lease": lease.model_dump_json()}
        if catalog_ref:
            blob.metadata["catalog"] = catalog_ref.model_dump_json()
        try:
            blob.upload_from_string(
                _dump(state),
                content_type="application/json",
                if_generation_match=previous.generation,
                timeout=self.timeout_sec,
            )
        except PreconditionFailed:
            raise StateConflict(
                "root CAS failed; reread and reconcile"
            ) from None
        return RepositorySnapshot(
            state, int(blob.generation), lease, catalog, catalog_ref
        )

    def _held(self, snapshot: RepositorySnapshot, handle: LeaseHandle) -> None:
        lease = snapshot.lease
        if (
            snapshot.state.bank_id != handle.bank_id
            or lease.owner_run_id != handle.owner_run_id
            or lease.epoch != handle.epoch
            or lease.expires_at is None
            or self._now() >= lease.expires_at
        ):
            raise LeaseConflict("lease lost, expired, or fenced")

    def acquire_lease(self, bank: BankKey, run_id: str) -> LeaseHandle:
        _id(run_id)
        snapshot = self.load(bank)
        now = self._now()
        old = snapshot.lease
        if old.owner_run_id is not None and (
            old.expires_at is None or now < old.expires_at
        ):
            raise LeaseConflict("bank already has an active lease")
        lease = Lease(
            owner_run_id=run_id,
            epoch=old.epoch + 1,
            heartbeat_at=now,
            expires_at=now + timedelta(seconds=self.lease_duration_sec),
        )
        self._write_root(
            snapshot,
            snapshot.state,
            lease,
            snapshot.catalog,
            snapshot.catalog_ref,
        )
        return LeaseHandle(bank_id=bank, owner_run_id=run_id, epoch=lease.epoch)

    def renew_lease(self, handle: LeaseHandle) -> None:
        snapshot = self.load(handle.bank_id)
        self._held(snapshot, handle)
        now = self._now()
        lease = _replace(
            snapshot.lease,
            heartbeat_at=now,
            expires_at=now + timedelta(seconds=self.lease_duration_sec),
        )
        self._write_root(
            snapshot,
            snapshot.state,
            lease,
            snapshot.catalog,
            snapshot.catalog_ref,
        )

    def release_lease(self, handle: LeaseHandle) -> None:
        snapshot = self.load(handle.bank_id)
        self._held(snapshot, handle)
        self._write_root(
            snapshot,
            snapshot.state,
            Lease(epoch=handle.epoch),
            snapshot.catalog,
            snapshot.catalog_ref,
        )

    def _publish(
        self,
        snapshot: RepositorySnapshot,
        handle: LeaseHandle,
        state: IngestionWatermarkState,
        catalog: _Catalog,
    ) -> RepositorySnapshot:
        if state.revision != snapshot.state.revision + 1:
            raise ValueError("transaction must advance exactly one revision")
        ref = self._object(f"{self._base(handle.bank_id)}/catalogs", catalog)
        # CAS also checks any concurrent heartbeat/takeover since load.
        self._held(snapshot, handle)
        return self._write_root(snapshot, state, snapshot.lease, catalog, ref)

    def get_stream(
        self, snapshot: RepositorySnapshot, stream_id: str
    ) -> ScanStreamState:
        stream = ScanStreamState.model_validate_json(
            self._read_ref(snapshot.catalog.streams[_id(stream_id)])
        )
        if stream.stream_id != stream_id or (
            stream.bank_id != snapshot.state.bank_id
        ):
            raise IntegrityError("stream identity mismatch")
        return stream

    def get_plan(
        self, snapshot: RepositorySnapshot, plan_id: str
    ) -> HistoricalPlan:
        plan = HistoricalPlan.model_validate_json(
            self._read_ref(snapshot.catalog.plans[_id(plan_id)])
        )
        if plan.plan_id != plan_id or plan.bank_id != snapshot.state.bank_id:
            raise IntegrityError("plan identity mismatch")
        return plan

    def register(
        self,
        handle: LeaseHandle,
        streams: Sequence[ScanStreamState],
        *,
        plan: HistoricalPlan | None = None,
    ) -> RepositorySnapshot:
        """Register new contexts/plan together; retry identical IDs safely."""
        snapshot = self.load(handle.bank_id)
        self._held(snapshot, handle)
        stream_refs = dict(snapshot.catalog.streams)
        plan_refs = dict(snapshot.catalog.plans)
        for stream in streams:
            _id(stream.stream_id)
            if stream.bank_id != handle.bank_id:
                raise ValueError("stream bank mismatch")
            if stream.stream_id in stream_refs:
                if self.get_stream(snapshot, stream.stream_id) != stream:
                    raise IntegrityError("stream ID already has another value")
            if stream.plan_id is not None and (
                plan is None or stream.plan_id != plan.plan_id
            ):
                raise ValueError("register historical streams with their plan")
            if (
                stream.status != ScanStatus.NOT_STARTED
                or stream.committed_pages
                or stream.committed_reviews
                or stream.frontier_page_id is not None
            ):
                raise ValueError("new streams cannot carry unverified progress")
            stream_refs[stream.stream_id] = self._object(
                f"{self._base(handle.bank_id)}/streams/{stream.stream_id}",
                stream,
            )
        if plan:
            _id(plan.plan_id)
            if plan.bank_id != handle.bank_id or (
                set(plan.stream_ids) != {s.stream_id for s in streams}
            ):
                raise ValueError("plan must register all its streams")
            if (
                plan.status != ScanStatus.NOT_STARTED
                or plan.completion_evidence is not None
            ):
                raise ValueError("new plan cannot claim verified completion")
            if plan.plan_id in plan_refs:
                if self.get_plan(snapshot, plan.plan_id) != plan:
                    raise IntegrityError("plan ID already has another value")
            plan_refs[plan.plan_id] = self._object(
                f"{self._base(handle.bank_id)}/plans/{plan.plan_id}", plan
            )
        catalog = _replace(
            snapshot.catalog, streams=stream_refs, plans=plan_refs
        )
        if catalog == snapshot.catalog:
            return snapshot
        state = _replace(
            snapshot.state,
            stream_ids=tuple(stream_refs),
            historical_plan_ids=tuple(plan_refs),
            revision=snapshot.state.revision + 1,
            updated_at=self._now(),
        )
        return self._publish(snapshot, handle, state, catalog)

    def start_incremental(
        self, handle: LeaseHandle, stream_id: str
    ) -> RepositorySnapshot:
        snapshot = self.load(handle.bank_id)
        self._held(snapshot, handle)
        state = begin_incremental(
            snapshot.state,
            self.get_stream(snapshot, stream_id),
            run_id=handle.owner_run_id,
            expected_revision=snapshot.state.revision,
            at=self._now(),
        )
        return self._publish(snapshot, handle, state, snapshot.catalog)

    def set_stream_status(
        self, handle: LeaseHandle, stream_id: str, status: ScanStatus
    ) -> RepositorySnapshot:
        snapshot = self.load(handle.bank_id)
        self._held(snapshot, handle)
        state, stream = change_stream_status(
            snapshot.state,
            self.get_stream(snapshot, stream_id),
            status=status,
            expected_revision=snapshot.state.revision,
            at=self._now(),
        )
        refs = dict(snapshot.catalog.streams)
        refs[stream.stream_id] = self._object(
            f"{self._base(handle.bank_id)}/streams/{stream.stream_id}", stream
        )
        return self._publish(
            snapshot, handle, state, _replace(snapshot.catalog, streams=refs)
        )

    def extend_plan(
        self, handle: LeaseHandle, plan_id: str, event: PlanExtensionEvent
    ) -> RepositorySnapshot:
        snapshot = self.load(handle.bank_id)
        self._held(snapshot, handle)
        old = self.get_plan(snapshot, plan_id)
        plan = extend_to_full(old, event)
        if plan == old:
            return snapshot
        refs = dict(snapshot.catalog.plans)
        refs[plan.plan_id] = self._object(
            f"{self._base(handle.bank_id)}/plans/{plan.plan_id}", plan
        )
        state = _replace(
            snapshot.state,
            revision=snapshot.state.revision + 1,
            updated_at=self._now(),
        )
        return self._publish(
            snapshot, handle, state, _replace(snapshot.catalog, plans=refs)
        )

    def _append(
        self,
        bank: BankKey,
        ledger_id: str,
        entries: Sequence[BaseModel],
        previous: LedgerReference | None = None,
    ) -> LedgerReference:
        node = _Node(
            previous=previous,
            entries=tuple(e.model_dump(mode="json") for e in entries),
        )
        ref = self._object(
            f"{self.layout.gcs_ingestion_ledgers_prefix}/"
            f"{bank.value}/{_id(ledger_id)}",
            node,
        )
        return LedgerReference(
            **ref.model_dump(),
            entry_count=len(entries)
            + (previous.entry_count if previous else 0),
        )

    def iter_ledger(self, ref: LedgerReference) -> Iterator[dict[str, Any]]:
        """All linked pages, no truncation/cache as proof of completeness."""
        seen = set()
        while ref:
            key = (ref.uri, ref.generation)
            if key in seen:
                raise IntegrityError("ledger cycle")
            seen.add(key)
            node = _Node.model_validate_json(self._read_ref(ref))
            if ref.entry_count != len(node.entries) + (
                node.previous.entry_count if node.previous else 0
            ):
                raise IntegrityError("ledger count mismatch")
            yield from node.entries
            ref = node.previous

    def write_review_ledger(
        self,
        bank: BankKey,
        ledger_id: str,
        entries: Sequence[ReviewLedgerEntry],
        *,
        page_size: int = 500,
    ) -> LedgerReference:
        _id(ledger_id)
        if type(page_size) is not int or page_size <= 0:
            raise ValueError("ledger page size must be positive")
        seen = set()
        for entry in entries:
            if (
                entry.event_id
                != compute_event_id(
                    bank, entry.review_id, entry.source_revision
                )
                or entry.event_id in seen
            ):
                raise ValueError("invalid or duplicate event identity")
            seen.add(entry.event_id)
        ref = None
        for start in range(0, len(entries), page_size):
            ref = self._append(
                bank, ledger_id, entries[start : start + page_size], ref
            )
        return ref or self._append(bank, ledger_id, [])

    def put_manifest(self, page: PageManifest) -> ObjectReference:
        name = (
            f"{self.layout.gcs_ingestion_manifests_prefix}/"
            f"{page.bank_id.value}/{_id(page.stream_id)}/{page.chain_epoch}/"
            f"{_id(page.page_id)}/{page.manifest_version}-"
            f"{_id(page.fetch_attempt_id)}.json"
        )
        return self._immutable(name, _dump(page))

    def put_receipt(self, receipt: ProcessingReceipt) -> ObjectReference:
        name = (
            f"{self.layout.gcs_processing_receipts_prefix}/"
            f"{receipt.bank_id.value}/{_id(receipt.page_id)}/"
            f"{_id(receipt.receipt_id)}.json"
        )
        return self._immutable(name, _dump(receipt))

    def get_manifest(self, ref: ObjectReference) -> PageManifest:
        return PageManifest.model_validate_json(self._read_ref(ref))

    def _index_key(self, stream_id: str, page_id: str) -> str:
        return _sha(json.dumps([stream_id, page_id]).encode())

    def _index_get(
        self, ref: ObjectReference | None, key: str
    ) -> ObjectReference | None:
        depth = 0
        while ref:
            node = _IndexNode.model_validate_json(self._read_ref(ref))
            if not node.children:
                return node.pages.get(key)
            if depth >= len(key):
                raise IntegrityError("manifest index depth exceeded")
            ref = node.children.get(key[depth])
            depth += 1
        return None

    def _index_put(
        self,
        bank: BankKey,
        ref: ObjectReference | None,
        key: str,
        value: ObjectReference,
        depth: int = 0,
    ) -> ObjectReference:
        node = (
            _IndexNode.model_validate_json(self._read_ref(ref))
            if ref
            else _IndexNode()
        )
        if node.children:
            children = dict(node.children)
            children[key[depth]] = self._index_put(
                bank, children.get(key[depth]), key, value, depth + 1
            )
            node = _IndexNode(children=children)
        else:
            pages = dict(node.pages)
            if key in pages and pages[key] != value:
                raise IntegrityError("page index conflict")
            pages[key] = value
            if len(pages) <= 128:
                node = _IndexNode(pages=pages)
            else:
                if depth >= 64:
                    raise IntegrityError("manifest index hash collision")
                children = {}
                for digit in set(k[depth] for k in pages):
                    group = {
                        k: v for k, v in pages.items() if k[depth] == digit
                    }
                    # Splitting a 129-entry leaf creates <=128-entry leaves,
                    # except one shared prefix; recurse for that rare case.
                    child = None
                    for k, v in group.items():
                        child = self._index_put(bank, child, k, v, depth + 1)
                    children[digit] = child
                node = _IndexNode(children=children)
        return self._object(f"{self._base(bank)}/page-index", node)

    def find_page(
        self, snapshot: RepositorySnapshot, stream_id: str, page_id: str
    ) -> PageManifest | None:
        _id(stream_id)
        _id(page_id)
        ref = self._index_get(
            snapshot.catalog.manifest_index,
            self._index_key(stream_id, page_id),
        )
        if ref is None:
            return None
        page = self.get_manifest(ref)
        if (page.bank_id, page.stream_id, page.page_id) != (
            snapshot.state.bank_id,
            stream_id,
            page_id,
        ):
            raise IntegrityError("manifest index identity mismatch")
        return page

    def commit_page(
        self,
        handle: LeaseHandle,
        page: PageManifest,
        *,
        expected_revision: int,
    ) -> RepositorySnapshot:
        snapshot = self.load(handle.bank_id)
        self._held(snapshot, handle)
        if snapshot.state.revision != expected_revision:
            raise StateConflict("stale logical revision")
        if page.run_id != handle.owner_run_id:
            raise ValueError("page run differs from lease owner")
        stream = self.get_stream(snapshot, page.stream_id)
        if stream.plan_id is None and (
            snapshot.state.incremental.stream_id != stream.stream_id
            or snapshot.state.incremental.active_run_id != handle.owner_run_id
        ):
            raise ValueError(
                "incremental run must be started before committing"
            )
        existing = self.find_page(snapshot, stream.stream_id, page.page_id)
        if existing:
            if existing != page:
                raise IntegrityError("conflicting committed page")
            return snapshot
        # Verify every reference before creating a new committed chain.
        entries = [
            ReviewLedgerEntry.model_validate(e)
            for e in self.iter_ledger(page.ledger)
        ]
        if len(entries) != page.valid_count or len(
            {e.event_id for e in entries}
        ) != len(entries):
            raise IntegrityError("page ledger count/identity mismatch")
        for entry in entries:
            if entry.event_id != compute_event_id(
                page.bank_id, entry.review_id, entry.source_revision
            ):
                raise IntegrityError("page ledger event mismatch")
        if entries and (
            min(e.reviewed_at for e in entries) < page.observed_min_at
            or max(e.reviewed_at for e in entries) > page.observed_max_at
        ):
            raise IntegrityError("ledger dates differ from page bounds")
        if page.discarded_count and page.discard_ledger is None:
            raise IntegrityError("discarded rows require a reason ledger")
        if page.discard_ledger is not None:
            discarded = list(self.iter_ledger(page.discard_ledger))
            if len(discarded) != page.discarded_count or any(
                set(d) != {"row_index", "review_id", "reason"}
                or d["reason"] != "NO_TEXT"
                for d in discarded
            ):
                raise IntegrityError("invalid discard ledger")
        backup = self.bucket.blob(self._name(page.backup_uri))
        try:
            backup.reload(
                if_generation_match=page.backup_generation,
                timeout=self.timeout_sec,
            )
        except (NotFound, PreconditionFailed):
            raise IntegrityError("raw backup missing or replaced") from None
        previous = (
            self.find_page(snapshot, stream.stream_id, stream.frontier_page_id)
            if stream.frontier_page_id
            else None
        )
        manifest_ref = self.put_manifest(page)
        ledger = self._append(
            handle.bank_id,
            "manifest-index",
            [manifest_ref],
            snapshot.state.manifest_ledger,
        )
        transition = commit_page(
            snapshot.state,
            stream,
            page,
            expected_revision=expected_revision,
            committed_at=self._now(),
            manifest_ledger=ledger,
            previous_page=previous,
        )
        refs = dict(snapshot.catalog.streams)
        refs[stream.stream_id] = self._object(
            f"{self._base(handle.bank_id)}/streams/{stream.stream_id}",
            transition.stream,
        )
        return self._publish(
            snapshot,
            handle,
            transition.state,
            _replace(
                snapshot.catalog,
                streams=refs,
                pending={
                    k: v
                    for k, v in snapshot.catalog.pending.items()
                    if k != page.page_id
                },
                manifest_index=self._index_put(
                    handle.bank_id,
                    snapshot.catalog.manifest_index,
                    self._index_key(page.stream_id, page.page_id),
                    manifest_ref,
                ),
            ),
        )

    def read_object(self, ref: ObjectReference) -> bytes:
        return self._read_ref(ref)

    def write_raw_backup(
        self,
        bank: BankKey,
        run_id: str,
        page_id: str,
        fetch_attempt_id: str,
        data: bytes,
    ) -> ObjectReference:
        name = (
            f"{self.layout.gcs_raw_staging_prefix}/{bank.value}/"
            f"{_id(run_id)}/{_id(page_id)}/{_id(fetch_attempt_id)}.jsonl.gz"
        )
        return self._immutable(name, data, content_type="application/gzip")

    def pending_capture(
        self, snapshot: RepositorySnapshot, page_id: str
    ) -> PendingCapture:
        return snapshot.catalog.pending[_id(page_id)]

    def stage_page(
        self,
        handle: LeaseHandle,
        page: PageManifest,
        backup: ObjectReference,
        mode: IngestionMode,
    ) -> RepositorySnapshot:
        snapshot = self.load(handle.bank_id)
        self._held(snapshot, handle)
        if page.bank_id != handle.bank_id or page.run_id != handle.owner_run_id:
            raise ValueError("capture identity differs from lease")
        if (page.backup_uri, page.backup_generation) != (
            backup.uri,
            backup.generation,
        ):
            raise IntegrityError("capture backup differs from manifest")
        stream = self.get_stream(snapshot, page.stream_id)
        if stream.plan_id is None and (
            mode != IngestionMode.INCREMENTAL
            or snapshot.state.incremental.active_run_id != page.run_id
            or snapshot.state.incremental.stream_id != page.stream_id
        ):
            raise ValueError("incremental capture requires active run")
        if stream.plan_id is not None:
            plan = self.get_plan(snapshot, stream.plan_id)
            expected_mode = (
                IngestionMode.BACKFILL
                if plan.requested_lower_at
                else IngestionMode.FULL_BACKFILL
            )
            if mode != expected_mode:
                raise ValueError("capture mode differs from historical plan")
        previous = (
            self.find_page(snapshot, stream.stream_id, stream.frontier_page_id)
            if stream.frontier_page_id
            else None
        )
        commit_page(
            snapshot.state,
            stream,
            _replace(
                page,
                published_count=page.valid_count,
                publication_status=PublicationStatus.PUBLISHED,
            ),
            expected_revision=snapshot.state.revision,
            committed_at=self._now(),
            manifest_ledger=page.ledger,
            previous_page=previous,
        )
        pending = dict(snapshot.catalog.pending)
        if page.page_id in pending:
            old_capture = pending[page.page_id]
            old = self.get_manifest(old_capture.manifest)
            if old == page and old_capture.backup == backup:
                return snapshot
            excluded = {
                "manifest_version",
                "published_count",
                "publication_status",
            }
            if (
                old.model_dump(exclude=excluded)
                != page.model_dump(exclude=excluded)
                or page.manifest_version <= old.manifest_version
                or old_capture.backup != backup
                or old_capture.mode != mode
                or old.publication_status == PublicationStatus.PUBLISHED
            ):
                raise IntegrityError("pending capture changed or regressed")
        elif page.manifest_version != 1:
            raise IntegrityError("new pending capture must start at version 1")
        pending[page.page_id] = PendingCapture(
            manifest=self.put_manifest(page), backup=backup, mode=mode
        )
        state = _replace(
            snapshot.state,
            revision=snapshot.state.revision + 1,
            updated_at=self._now(),
        )
        return self._publish(
            snapshot, handle, state, _replace(snapshot.catalog, pending=pending)
        )

    def record_audit(
        self, handle: LeaseHandle, event: IngestionRunAudit
    ) -> RepositorySnapshot:
        """Durable outbox linked from root; BQ availability cannot lose it."""
        snapshot = self.load(handle.bank_id)
        self._held(snapshot, handle)
        if (event.bank_id, event.run_id) != (
            handle.bank_id,
            handle.owner_run_id,
        ):
            raise ValueError("audit run/bank differs from lease")
        _id(event.audit_event_id)
        if (
            event.updated_at > self._now()
            or (
                event.state_revision is not None
                and event.state_revision > snapshot.state.revision
            )
            or (
                event.plan_id is not None
                and event.plan_id not in snapshot.catalog.plans
            )
            or (
                event.stream_id is not None
                and event.stream_id not in snapshot.catalog.streams
            )
        ):
            raise ValueError(
                "audit references unknown progress or future state"
            )
        if snapshot.catalog.audits:
            for entry in self.iter_ledger(snapshot.catalog.audits):
                old = IngestionRunAudit.model_validate(entry)
                if old.audit_event_id == event.audit_event_id:
                    if old != event:
                        raise IntegrityError(
                            "audit ID reused with other content"
                        )
                    return snapshot
        audits = self._append(
            handle.bank_id, "audit-outbox", [event], snapshot.catalog.audits
        )
        state = _replace(
            snapshot.state,
            revision=snapshot.state.revision + 1,
            updated_at=self._now(),
        )
        return self._publish(
            snapshot,
            handle,
            state,
            _replace(snapshot.catalog, audits=audits),
        )

    def iter_audits(
        self, snapshot: RepositorySnapshot
    ) -> Iterator[IngestionRunAudit]:
        if snapshot.catalog.audits:
            for entry in self.iter_ledger(snapshot.catalog.audits):
                yield IngestionRunAudit.model_validate(entry)

    def delivery_marker(self, event: IngestionRunAudit) -> str:
        return (
            f"{self._base(event.bank_id)}/audit-delivered/"
            f"{_id(event.audit_event_id)}.json"
        )

    def audit_delivered(self, event: IngestionRunAudit) -> bool:
        blob = self.bucket.blob(self.delivery_marker(event))
        try:
            blob.reload(timeout=self.timeout_sec)
        except NotFound:
            return False
        ref = ObjectReference(
            uri=f"gs://{self.bucket.name}/{blob.name}",
            generation=int(blob.generation),
            content_fingerprint=_sha(_dump(event)),
        )
        self._read_ref(ref)
        return True

    def mark_audit_delivered(self, event: IngestionRunAudit) -> None:
        self._immutable(self.delivery_marker(event), _dump(event))

    def progress(self, bank: BankKey) -> dict[str, Any]:
        """Public view: no tokens, raw records, lease owner, or object URIs."""
        snapshot = self.load(bank)
        state = snapshot.state
        streams = [self.get_stream(snapshot, sid) for sid in state.stream_ids]
        plans = [
            self.get_plan(snapshot, pid) for pid in state.historical_plan_ids
        ]
        return {
            "bank_id": bank.value,
            "app_id": state.app_id,
            "persisted": snapshot.generation != 0,
            "revision": state.revision,
            "updated_at": state.updated_at,
            "observed_min_at": state.observed_min_at,
            "observed_max_at": state.observed_max_at,
            "committed_high_at": state.incremental.committed_high_at,
            "coverage": state.coverage.value,
            "gaps_detected": state.coverage.value == "GAPS_DETECTED"
            or any(
                p.completion_evidence is not None
                and p.completion_evidence.gaps_detected
                for p in plans
            ),
            "uncertainty": (
                "Observed traversal does not prove catalog completeness"
            ),
            "pending_pages": [
                self.get_manifest(c.manifest).model_dump(
                    mode="json",
                    include={
                        "page_id",
                        "stream_id",
                        "fetched_at",
                        "publication_status",
                        "published_count",
                        "valid_count",
                        "discarded_count",
                    },
                )
                for c in snapshot.catalog.pending.values()
            ],
            "streams": [
                s.model_dump(
                    mode="json",
                    include={
                        "stream_id",
                        "plan_id",
                        "status",
                        "recovery_status",
                        "frontier_oldest_at",
                        "last_success_at",
                        "committed_pages",
                        "committed_reviews",
                        "chain_epoch",
                    },
                )
                for s in streams
            ],
            "plans": [
                p.model_dump(
                    mode="json",
                    include={
                        "plan_id",
                        "started_at",
                        "upper_anchor_at",
                        "requested_lower_at",
                        "stream_ids",
                        "status",
                    },
                )
                | {
                    "completion_evidence": (
                        p.completion_evidence.model_dump(
                            mode="json", exclude={"boundary_ledger"}
                        )
                        if p.completion_evidence
                        else None
                    )
                }
                for p in plans
            ],
        }
