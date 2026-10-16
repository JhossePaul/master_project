"""Durable captures and at-least-once page publication; no cloud transaction."""

import base64
import gzip
import io
import json
import logging
import math
import time
import zlib
from dataclasses import asdict
from datetime import datetime
from typing import Any

from google.cloud import pubsub_v1
from pydantic import BaseModel, ConfigDict
from voc_common import (
    IngestionMode,
    PageManifest,
    PublicationStatus,
    RawReviewEnvelope,
    RecoveryStatus,
    SanitizationStatus,
    ScanStreamState,
)
from voc_common.schemas import ensure_utc

from ingestion_worker.playstore_protocol import (
    PageClassification,
    ProtocolError,
    RpcPageResult,
    _decode_frames,
    parse_batchexecute_response,
)
from ingestion_worker.watermark_store import (
    IntegrityError,
    LeaseHandle,
    RepositorySnapshot,
    ReviewLedgerEntry,
    WatermarkRepository,
    _sha,
)


class PublicationIncomplete(RuntimeError):
    def __init__(self, manifest: PageManifest) -> None:
        super().__init__("Page publication incomplete; replay durable capture")
        self.manifest = manifest


class BackupUnavailable(IntegrityError):
    """Pending capture cannot be replayed: record gap/recover source in 3.4."""


class CaptureUnreadable(BackupUnavailable):
    """La captura existe pero no se puede interpretar con este código.

    A diferencia de una captura ausente o reemplazada (expirada), puede
    resolverse desplegando un lector compatible: quien cierra páginas no debe
    tratarla como hueco definitivo.
    """


class _Discard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    row_index: int
    review_id: str
    reason: str


def _json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _fingerprint(page: RpcPageResult, events: list[RawReviewEnvelope]) -> str:
    return _sha(
        _json(
            {
                "events": [e.event_id for e in events],
                "discards": [asdict(d) for d in page.discarded],
                "raw_count": page.raw_count,
                "raw_rows": _decode_frames(page.raw_body)[0][0],
            }
        )
    )


def compute_page_id(
    stream: ScanStreamState,
    input_token: str | None,
    content_fingerprint: str,
) -> str:
    return _sha(
        _json(
            [
                stream.bank_id.value,
                stream.stream_id,
                stream.context.fingerprint,
                stream.chain_epoch,
                input_token,
                content_fingerprint,
            ]
        )
    )


def restore_capture(
    manifest: PageManifest,
    compressed: bytes,
    *,
    mode: IngestionMode | None = None,
    max_bytes: int = 40_000_000,
) -> list[RawReviewEnvelope]:
    """Valida una captura JSONL.gz contra su manifiesto y devuelve sus sobres.

    `mode=None` acepta el modo registrado en la captura (lectores como la
    sanitización, que no conocen el modo de la corrida que la escribió).
    """
    try:
        # Bound decompression; never materialize an unbounded gzip payload.
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
            data = stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("backup exceeds decompression budget")
        lines = data.splitlines()
        header = json.loads(lines[0])
        events = [
            RawReviewEnvelope.model_validate_json(line) for line in lines[1:]
        ]
        page = parse_batchexecute_response(
            base64.b64decode(header["raw_rpc_base64"], validate=True),
            bank_id=manifest.bank_id,
            app_id=manifest.app_id,
        )
        expected = [
            RawReviewEnvelope.from_raw(
                r,
                page_id=manifest.page_id,
                stream_id=manifest.stream_id,
                plan_id=manifest.plan_id,
            )
            for r in page.reviews
        ]
        if (
            header["page_id"] != manifest.page_id
            or header["schema_version"] != 2
            or header["mode"]
            != (mode.value if mode else IngestionMode(header["mode"]).value)
            or header["discarded"] != [asdict(d) for d in page.discarded]
            or header["protocol_version"] != manifest.context.protocol_version
            or page.next_token != manifest.output_token
            or page.raw_count != manifest.raw_count
            or len(events) != manifest.valid_count
            or _fingerprint(page, events) != manifest.content_fingerprint
            or header["content_fingerprint"] != manifest.content_fingerprint
            or [e.model_dump(exclude={"raw"}) for e in events]
            != [e.model_dump(exclude={"raw"}) for e in expected]
            or any(
                a.raw.model_dump(exclude={"ingested_at"})
                != b.raw.model_dump(exclude={"ingested_at"})
                for a, b in zip(events, expected, strict=True)
            )
        ):
            raise ValueError("capture differs from manifest")
        return events
    except (
        ValueError,
        KeyError,
        IndexError,
        OSError,
        EOFError,
        zlib.error,
    ):
        raise CaptureUnreadable(
            "Durable capture invalid; recover source"
        ) from None


def read_committed_capture(
    repository: WatermarkRepository,
    manifest: PageManifest,
    *,
    max_bytes: int = 40_000_000,
) -> list[RawReviewEnvelope]:
    """Lectura pública de la captura de un manifiesto comprometido.

    Lee el objeto por URI y generación del manifiesto (nunca por glob).
    Ausente, reemplazado o inválido => BackupUnavailable (hueco explícito).
    """
    try:
        compressed = repository.read_backup(manifest)
    except IntegrityError:
        raise BackupUnavailable(
            "Durable capture missing; recover source"
        ) from None
    return restore_capture(manifest, compressed, max_bytes=max_bytes)


class RawReviewBatchPublisher:
    def __init__(
        self,
        repository: WatermarkRepository,
        publisher: pubsub_v1.PublisherClient,
        topic: str,
        *,
        confirmation_timeout_sec: float = 30,
        max_backup_bytes: int = 40_000_000,
    ) -> None:
        if (
            not math.isfinite(confirmation_timeout_sec)
            or confirmation_timeout_sec <= 0
        ):
            raise ValueError("confirmation timeout must be positive and finite")
        if type(max_backup_bytes) is not int or max_backup_bytes <= 0:
            raise ValueError("backup budget must be positive")
        if not topic.startswith("projects/") or "/topics/" not in topic:
            raise ValueError("use a fully qualified Pub/Sub topic")
        self.repository = repository
        self.publisher = publisher
        self.topic = topic
        self.timeout = confirmation_timeout_sec
        self.max_backup_bytes = max_backup_bytes

    def prepare_page(
        self,
        handle: LeaseHandle,
        stream: ScanStreamState,
        page: RpcPageResult,
        *,
        mode: IngestionMode,
        fetched_at: datetime,
        fetch_attempt_id: str,
        input_token: str | None = None,
    ) -> PageManifest:
        """Prepare a fetch; resume by persisted page_id after a crash."""
        return self._prepare(
            handle,
            stream,
            page,
            mode=mode,
            fetched_at=fetched_at,
            fetch_attempt_id=fetch_attempt_id,
            input_token=input_token,
        )

    def capture_replay(
        self,
        handle: LeaseHandle,
        stream: ScanStreamState,
        anchor: PageManifest,
        page: RpcPageResult,
        *,
        mode: IngestionMode,
        fetched_at: datetime,
        fetch_attempt_id: str,
        recovery: RecoveryStatus,
    ) -> tuple[PageManifest, RepositorySnapshot | None]:
        """Persist an anchor replay as a new observation.

        Identical content keeps the page_id: its events were already
        confirmed, so the replay is committed at once with a fresh backup
        carrying the new cursor. Changed content is a new pending capture that
        must be published before it can replace the anchor (publish_page).
        """
        manifest = self._prepare(
            handle,
            stream,
            page,
            mode=mode,
            fetched_at=fetched_at,
            fetch_attempt_id=fetch_attempt_id,
            input_token=anchor.input_token,
            replaces=anchor,
            recovery=recovery,
        )
        if manifest.page_id != anchor.page_id:
            return manifest, None
        repo = self.repository
        events, _, fingerprint = self._events(stream, page, fetched_at)
        backup = repo.write_raw_backup(
            stream.bank_id,
            handle.owner_run_id,
            anchor.page_id,
            fetch_attempt_id,
            self._capture(anchor.page_id, mode, page, events, fingerprint),
        )
        replay = PageManifest.model_validate(
            anchor.model_dump()
            | {
                "manifest_version": max(
                    anchor.manifest_version + 1, time.time_ns()
                ),
                "fetch_attempt_id": fetch_attempt_id,
                "run_id": handle.owner_run_id,
                "fetched_at": ensure_utc(fetched_at),
                "output_token": page.next_token,
                "backup_uri": backup.uri,
                "backup_generation": backup.generation,
            }
        )
        snapshot = repo.reanchor_page(
            handle,
            anchor,
            replay,
            recovery=recovery,
            expected_revision=repo.load(handle.bank_id).state.revision,
        )
        return replay, snapshot

    def _events(
        self,
        stream: ScanStreamState,
        page: RpcPageResult,
        fetched_at: datetime,
    ) -> tuple[list[RawReviewEnvelope], RpcPageResult, str]:
        observed = parse_batchexecute_response(
            page.raw_body, bank_id=stream.bank_id, app_id=stream.app_id
        )
        # Freeze ingestion time to the capture timestamp for stable gzip.
        reviews = [
            type(r).model_validate(
                r.model_dump() | {"ingested_at": ensure_utc(fetched_at)}
            )
            for r in observed.reviews
        ]
        events = [
            RawReviewEnvelope.from_raw(
                r,
                page_id="capture",
                stream_id=stream.stream_id,
                plan_id=stream.plan_id,
            )
            for r in reviews
        ]
        return events, observed, _fingerprint(observed, events)

    def _capture(
        self,
        page_id: str,
        mode: IngestionMode,
        page: RpcPageResult,
        events: list[RawReviewEnvelope],
        fingerprint: str,
    ) -> bytes:
        events = [
            RawReviewEnvelope.model_validate(
                e.model_dump() | {"page_id": page_id}
            )
            for e in events
        ]
        header = {
            "record_type": "capture",
            "schema_version": 2,
            "page_id": page_id,
            "mode": mode.value,
            "protocol_version": page.protocol_version,
            "raw_rpc_base64": base64.b64encode(page.raw_body).decode("ascii"),
            "discarded": [asdict(d) for d in page.discarded],
            "content_fingerprint": fingerprint,
        }
        data = (
            b"\n".join(
                [
                    _json(header),
                    *[_json(e.model_dump(mode="json")) for e in events],
                ]
            )
            + b"\n"
        )
        if len(data) > self.max_backup_bytes:
            raise ValueError("capture exceeds uncompressed backup budget")
        return gzip.compress(data, mtime=0)

    def _prepare(
        self,
        handle: LeaseHandle,
        stream: ScanStreamState,
        page: RpcPageResult,
        *,
        mode: IngestionMode,
        fetched_at: datetime,
        fetch_attempt_id: str,
        input_token: str | None,
        replaces: PageManifest | None = None,
        recovery: RecoveryStatus | None = None,
    ) -> PageManifest:
        repo = self.repository
        snapshot = repo.load(handle.bank_id)
        repo._held(snapshot, handle)
        if stream.context.protocol_version != page.protocol_version:
            raise ProtocolError("page protocol differs from stream")
        # Never trust a caller-created result that contradicts its raw evidence.
        observed = parse_batchexecute_response(
            page.raw_body, bank_id=stream.bank_id, app_id=stream.app_id
        )
        if (
            observed.raw_count != page.raw_count
            or observed.discarded != page.discarded
            or observed.next_token != page.next_token
            or observed.evidence != page.evidence
            or [r.model_dump(exclude={"ingested_at"}) for r in observed.reviews]
            != [r.model_dump(exclude={"ingested_at"}) for r in page.reviews]
        ):
            raise IntegrityError("page result contradicts raw evidence")
        page = observed
        if (
            not page.raw_count
            or (not page.reviews and page.next_token is None)
            or page.classification == PageClassification.PROTOCOL_ERROR
        ):
            raise ProtocolError("ambiguous page cannot advance a stream")
        fetched_at = ensure_utc(fetched_at)
        if fetched_at > repo._now():
            raise ValueError("fetch cannot be in the future")
        events, page, fingerprint = self._events(stream, page, fetched_at)
        page_id = compute_page_id(stream, input_token, fingerprint)
        existing = repo.find_page(snapshot, stream.stream_id, page_id)
        if existing:
            return existing
        if repo.get_stream(snapshot, stream.stream_id) != stream:
            raise ValueError("stale stream snapshot")
        if page_id in snapshot.catalog.pending:
            capture = repo.pending_capture(snapshot, page_id)
            pending = repo.get_manifest(capture.manifest)
            if (
                pending.fetch_attempt_id != fetch_attempt_id
                or pending.fetched_at != fetched_at
                or pending.output_token != page.next_token
                or pending.run_id != handle.owner_run_id
            ):
                raise IntegrityError(
                    "same page has a different pending capture"
                )
            return pending
        compressed = self._capture(page_id, mode, page, events, fingerprint)
        events = [
            RawReviewEnvelope.model_validate(
                e.model_dump() | {"page_id": page_id}
            )
            for e in events
        ]
        backup = repo.write_raw_backup(
            stream.bank_id,
            handle.owner_run_id,
            page_id,
            fetch_attempt_id,
            compressed,
        )
        ledger = repo.write_review_ledger(
            stream.bank_id,
            page_id,
            [
                ReviewLedgerEntry(
                    review_id=e.review_id,
                    source_revision=e.source_revision,
                    event_id=e.event_id,
                    reviewed_at=e.raw.fecha,
                )
                for e in events
            ],
        )
        discards = repo._append(
            stream.bank_id,
            page_id + "-discards",
            [_Discard(**asdict(d)) for d in page.discarded],
        )
        manifest = PageManifest(
            bank_id=stream.bank_id,
            app_id=stream.app_id,
            page_id=page_id,
            fetch_attempt_id=fetch_attempt_id,
            run_id=handle.owner_run_id,
            plan_id=stream.plan_id,
            stream_id=stream.stream_id,
            chain_epoch=stream.chain_epoch,
            ordinal=(
                replaces.ordinal
                if replaces is not None
                else stream.frontier_ordinal + 1
                if stream.frontier_ordinal is not None
                else 0
            ),
            previous_page_id=(
                replaces.previous_page_id
                if replaces is not None
                else stream.frontier_page_id
            ),
            context=stream.context,
            input_token=input_token,
            output_token=page.next_token,
            fetched_at=fetched_at,
            observed_min_at=page.observed_min_at,
            observed_max_at=page.observed_max_at,
            ledger=ledger,
            discard_ledger=discards,
            raw_count=page.raw_count,
            valid_count=len(events),
            discarded_count=len(page.discarded),
            content_fingerprint=fingerprint,
            backup_uri=backup.uri,
            backup_generation=backup.generation,
        )
        repo.stage_page(
            handle,
            manifest,
            backup,
            mode,
            replaces=replaces,
            recovery=recovery,
        )
        return manifest

    def _restore(
        self, manifest: PageManifest, compressed: bytes, mode: IngestionMode
    ) -> list[RawReviewEnvelope]:
        return restore_capture(
            manifest, compressed, mode=mode, max_bytes=self.max_backup_bytes
        )

    def publish_page(
        self, handle: LeaseHandle, manifest: PageManifest
    ) -> RepositorySnapshot:
        repo = self.repository
        snapshot = repo.load(handle.bank_id)
        repo._held(snapshot, handle)
        committed = repo.find_page(
            snapshot, manifest.stream_id, manifest.page_id
        )
        if committed:
            if committed.content_fingerprint != manifest.content_fingerprint:
                raise IntegrityError("committed capture differs")
            return snapshot
        capture = repo.pending_capture(snapshot, manifest.page_id)
        current = repo.get_manifest(capture.manifest)
        if (
            current.run_id != handle.owner_run_id
            or current.bank_id != handle.bank_id
        ):
            raise ValueError("pending capture belongs to a different run")
        if current.content_fingerprint != manifest.content_fingerprint:
            raise IntegrityError("pending capture differs")
        try:
            compressed = repo.read_object(capture.backup)
        except IntegrityError:
            raise BackupUnavailable(
                "Durable capture missing; recover source"
            ) from None
        events = self._restore(current, compressed, capture.mode)
        replaces = (
            repo.get_manifest(capture.replaces) if capture.replaces else None
        )
        replay = {"replaces": replaces, "recovery": capture.recovery}
        repo.stage_page(handle, current, capture.backup, capture.mode, **replay)
        if current.publication_status != PublicationStatus.PUBLISHED:
            # Re-send the whole page: a timed-out future may still succeed.
            repo._held(repo.load(handle.bank_id), handle)
            deadline = time.monotonic() + self.timeout
            futures = []
            failures = 0
            for event in events:
                try:
                    futures.append(
                        self.publisher.publish(
                            self.topic,
                            _json(event.model_dump(mode="json")),
                            event_id=event.event_id,
                            page_id=event.page_id,
                            source_revision=event.source_revision,
                            bank_id=event.bank_id.value,
                            mode=capture.mode.value,
                            schema_version="2",
                        )
                    )
                except Exception:
                    failures += 1
            confirmed = 0
            for future in futures:
                try:
                    message_id = future.result(
                        timeout=max(0.0, deadline - time.monotonic())
                    )
                    if not isinstance(message_id, str) or not message_id:
                        raise ValueError("missing publish confirmation")
                    confirmed += 1
                except Exception:
                    failures += 1
            if failures:
                logging.getLogger(__name__).warning(
                    "Page publication incomplete; durable replay required"
                )
            status = (
                PublicationStatus.PUBLISHED
                if confirmed == len(events)
                else PublicationStatus.PARTIAL
                if confirmed
                else PublicationStatus.PENDING
            )
            current = PageManifest.model_validate(
                current.model_dump()
                | {
                    "manifest_version": max(
                        current.manifest_version + 1, time.time_ns()
                    ),
                    "published_count": confirmed,
                    "publication_status": status,
                    "sanitization_status": SanitizationStatus.PENDING,
                }
            )
            repo.stage_page(
                handle, current, capture.backup, capture.mode, **replay
            )
            if status != PublicationStatus.PUBLISHED:
                raise PublicationIncomplete(current)
        if replaces is not None and capture.recovery is not None:
            return repo.reanchor_page(
                handle,
                replaces,
                current,
                recovery=capture.recovery,
                expected_revision=repo.load(handle.bank_id).state.revision,
            )
        return repo.commit_page(
            handle,
            current,
            expected_revision=repo.load(handle.bank_id).state.revision,
        )
