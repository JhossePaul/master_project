"""Orquestación por microbatches (EPIC-4 4.4).

Orden por microbatch: deduplicar por `event_id` conservando todos los
`ack_ids` y páginas → confirmar de inmediato lo ya resuelto (copiando el
recibo a páginas nuevas) → DLP en Beam → `MERGE` → recibos → `ack` de
terminales → `nack` de reintentables → cierre de páginas tocadas. Ningún
`ack` precede a la persistencia en BigQuery y GCS.
"""

import json
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import apache_beam as beam
from google.api_core.exceptions import GoogleAPICallError
from ingestion_worker.publisher import BackupUnavailable, read_committed_capture
from ingestion_worker.watermark_store import (
    IntegrityError,
    ObjectReference,
    WatermarkRepository,
)
from pydantic import ValidationError
from voc_common import (
    BankKey,
    IngestionStorageLayout,
    PageManifest,
    ProcessingReceipt,
    RawReviewEnvelope,
    Settings,
)

from sanitization_pipeline.bq_writer import (
    BigQueryTdsUpsertManager,
    TdsWriteError,
)
from sanitization_pipeline.config import (
    SanitizationExecutionConfig,
    in_process_runner,
)
from sanitization_pipeline.dlp_transforms import (
    OUTPUT_TAG_FILTERED_LENGTH,
    OUTPUT_TAG_QUARANTINED,
    OUTPUT_TAG_RETRYABLE_ERROR,
    OUTPUT_TAG_SANITIZED_VALID,
    BatchCloudDlpDeidentifyDoFn,
    DlpConfigurationError,
    SanitizedBatch,
)
from sanitization_pipeline.processing_ledger import (
    LedgerError,
    ProcessingLedgerRepository,
    tds_committed_receipts,
)

EX_OK = 0
EX_USAGE = 64
EX_TEMPFAIL = 75
PULL_TIMEOUT_SEC = 60.0
# Fallos que no confirman nada: los mensajes vuelven a entregarse.
TRANSIENT = (LedgerError, IntegrityError, GoogleAPICallError, TimeoutError)


def log_json(severity: str, message: str, **fields: object) -> None:
    # Cloud Logging interpreta JSON de una línea; nunca textos ni PII.
    print(
        json.dumps(
            {"severity": severity, "message": message, **fields},
            default=str,
            ensure_ascii=False,
        ),
        flush=True,
    )


# ------------------------------------------------------------ Beam run
_SINK: dict[str, list[Any]] = {}


def _collect(element: Any, key: str) -> None:
    # Función de módulo: el runner en proceso la importa por referencia.
    _SINK[key].append(element)


def run_do_fn(
    do_fn: BatchCloudDlpDeidentifyDoFn,
    envelopes: Sequence[RawReviewEnvelope],
) -> SanitizedBatch:
    """Ejecuta el DoFn sobre un microbatch con el FnApiRunner en proceso."""
    tags = (
        OUTPUT_TAG_SANITIZED_VALID,
        OUTPUT_TAG_FILTERED_LENGTH,
        OUTPUT_TAG_QUARANTINED,
        OUTPUT_TAG_RETRYABLE_ERROR,
    )
    run_id = uuid.uuid4().hex
    keys = {tag: f"{run_id}-{tag}" for tag in tags}
    for key in keys.values():
        _SINK[key] = []
    try:
        with beam.Pipeline(runner=in_process_runner()) as pipeline:
            outputs = (
                pipeline
                | "Microbatch" >> beam.Create([list(envelopes)])
                | "Sanitize"
                >> beam.ParDo(do_fn).with_outputs(
                    OUTPUT_TAG_FILTERED_LENGTH,
                    OUTPUT_TAG_QUARANTINED,
                    OUTPUT_TAG_RETRYABLE_ERROR,
                    main=OUTPUT_TAG_SANITIZED_VALID,
                )
            )
            for tag, key in keys.items():
                _ = outputs[tag] | f"Collect-{tag}" >> beam.Map(_collect, key)
        return SanitizedBatch(
            valid=list(_SINK[keys[OUTPUT_TAG_SANITIZED_VALID]]),
            filtered=list(_SINK[keys[OUTPUT_TAG_FILTERED_LENGTH]]),
            quarantined=list(_SINK[keys[OUTPUT_TAG_QUARANTINED]]),
            retryable=list(_SINK[keys[OUTPUT_TAG_RETRYABLE_ERROR]]),
        )
    finally:
        for key in keys.values():
            _SINK.pop(key, None)


# ------------------------------------------------------------ processor
PageKey = tuple[BankKey, str, str]


@dataclass
class MicrobatchOutcome:
    terminal: set[str] = field(default_factory=set)
    retryable: set[str] = field(default_factory=set)
    pages: set[PageKey] = field(default_factory=set)
    already_processed: int = 0
    tds_committed: int = 0
    filtered_length: int = 0
    quarantined: int = 0
    bigquery_jobs: list[str] = field(default_factory=list)


class MicrobatchProcessor:
    def __init__(
        self,
        ledger: ProcessingLedgerRepository,
        upsert: BigQueryTdsUpsertManager,
        sanitize: Callable[[Sequence[RawReviewEnvelope]], SanitizedBatch],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.ledger = ledger
        self.upsert = upsert
        self.sanitize = sanitize
        self.clock = clock

    def process(
        self, envelopes: Iterable[RawReviewEnvelope]
    ) -> MicrobatchOutcome:
        out = MicrobatchOutcome()
        by_event: dict[str, list[RawReviewEnvelope]] = {}
        for envelope in envelopes:
            pages = by_event.setdefault(envelope.event_id, [])
            if envelope.page_id not in {e.page_id for e in pages}:
                pages.append(envelope)
            out.pages.add(
                (envelope.bank_id, envelope.stream_id, envelope.page_id)
            )
        if not by_event:
            return out
        processed: dict[str, ProcessingReceipt] = {}
        by_bank: dict[BankKey, list[str]] = {}
        for event_id, pages in by_event.items():
            by_bank.setdefault(pages[0].bank_id, []).append(event_id)
        for bank, ids in by_bank.items():
            processed |= self.ledger.find_already_processed_event_ids(bank, ids)
        receipts: list[ProcessingReceipt] = []
        for event_id, receipt in processed.items():
            # Redelivery o el mismo evento desde otra página: sin DLP ni BQ.
            receipts.extend(
                self.ledger.copy_receipt_for_page(receipt, e.page_id)
                for e in by_event[event_id]
            )
        out.already_processed = len(processed)
        fresh = [
            pages[0] for eid, pages in by_event.items() if eid not in processed
        ]
        if fresh:
            batch = self.sanitize(fresh)
            committed: list[ProcessingReceipt] = []
            if batch.valid:
                try:
                    commit = self.upsert.upsert_sanitized_batch(batch.valid)
                    committed = tds_committed_receipts(
                        batch.valid, commit.job_ids, self.clock()
                    )
                    out.bigquery_jobs.extend(commit.job_ids)
                except TdsWriteError:
                    # Sin MERGE no hay recibo ni ack: reintento seguro.
                    out.retryable.update(e.event_id for e in batch.valid)
            terminal = [*committed, *batch.filtered, *batch.quarantined]
            for receipt in terminal:
                receipts.append(receipt)
                receipts.extend(
                    self.ledger.copy_receipt_for_page(receipt, e.page_id)
                    for e in by_event[receipt.event_id][1:]
                )
            out.retryable.update(r.event_id for r in batch.retryable)
            out.tds_committed = len(committed)
            out.filtered_length = len(batch.filtered)
            out.quarantined = len(batch.quarantined)
        stored = self.ledger.write_event_receipts(receipts)
        out.terminal = {r.event_id for r in stored} - out.retryable
        # Lo que no quedó terminal nunca se confirma.
        out.retryable |= set(by_event) - out.terminal
        return out

    def reconcile(self, pages: Iterable[PageKey]) -> dict[str, int]:
        """Cierre idempotente; un fallo no bloquea el ack (se repite)."""
        counts: dict[str, int] = {}
        for bank, stream_id, page_id in sorted(pages):
            try:
                status = self.ledger.reconcile_page(bank, stream_id, page_id)
            except TRANSIENT:
                status_name = "ERROR"
            else:
                status_name = status.value
            counts[status_name] = counts.get(status_name, 0) + 1
        return counts


# ------------------------------------------------------------ ack lease
class AckDeadlineRenewer:
    """Extiende el ack deadline de un microbatch hasta que termine."""

    def __init__(
        self,
        subscriber: Any,
        subscription: str,
        ack_ids: Sequence[str],
        *,
        interval_sec: float,
        deadline_sec: int,
    ) -> None:
        self.subscriber = subscriber
        self.subscription = subscription
        self.ack_ids = list(ack_ids)
        self.interval_sec = interval_sec
        self.deadline_sec = deadline_sec
        self.renewals = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_sec):
            try:
                self.subscriber.modify_ack_deadline(
                    request={
                        "subscription": self.subscription,
                        "ack_ids": self.ack_ids,
                        "ack_deadline_seconds": self.deadline_sec,
                    }
                )
                self.renewals += 1
            except GoogleAPICallError:
                # Sin renovación el mensaje puede reentregarse: es seguro.
                log_json("WARNING", "Ack deadline renewal failed")

    def __enter__(self) -> "AckDeadlineRenewer":
        if self.ack_ids:
            self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join()


# --------------------------------------------------------------- report
@dataclass
class RunReport:
    mode: str
    messages: int = 0
    poison: int = 0
    # Entregas repetidas del mismo evento en un microbatch (mismo ack final).
    duplicate_messages: int = 0
    events_terminal: int = 0
    events_retryable: int = 0
    already_processed: int = 0
    tds_committed: int = 0
    filtered_length: int = 0
    quarantined: int = 0
    pages: dict[str, int] = field(default_factory=dict)
    expired_captures: int = 0
    bigquery_jobs: int = 0
    stop_reason: str = "drained"
    transient_failure: bool = False
    elapsed_sec: float = 0.0

    def add(self, outcome: MicrobatchOutcome) -> None:
        self.events_terminal += len(outcome.terminal)
        self.events_retryable += len(outcome.retryable)
        self.already_processed += outcome.already_processed
        self.tds_committed += outcome.tds_committed
        self.filtered_length += outcome.filtered_length
        self.quarantined += outcome.quarantined
        self.bigquery_jobs += len(outcome.bigquery_jobs)

    def add_pages(self, counts: dict[str, int]) -> None:
        for status, count in counts.items():
            self.pages[status] = self.pages.get(status, 0) + count

    def exit_code(self) -> int:
        failed = self.transient_failure or self.events_retryable
        return EX_TEMPFAIL if failed else EX_OK


# ---------------------------------------------------------- Pub/Sub mode
def _parse(message: Any) -> RawReviewEnvelope | None:
    """Sobre válido y coherente con sus atributos, o None (mensaje veneno)."""
    try:
        envelope = RawReviewEnvelope.model_validate_json(message.data)
    except (ValidationError, ValueError):
        return None
    attributes = dict(message.attributes or {})
    expected = {
        "event_id": envelope.event_id,
        "page_id": envelope.page_id,
        "source_revision": envelope.source_revision,
        "bank_id": envelope.bank_id.value,
        "schema_version": "2",
    }
    if any(attributes.get(k) != v for k, v in expected.items()):
        return None
    return envelope


class PubSubDrainer:
    def __init__(
        self,
        subscriber: Any,
        subscription: str,
        processor: MicrobatchProcessor,
        config: SanitizationExecutionConfig,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        renew_interval_sec: float | None = None,
    ) -> None:
        self.subscriber = subscriber
        self.subscription = subscription
        self.processor = processor
        self.config = config
        self.monotonic = monotonic
        self.renew_interval_sec = (
            renew_interval_sec or config.ack_renew_interval_sec
        )

    def _ack(self, ack_ids: Sequence[str]) -> None:
        if ack_ids:
            self.subscriber.acknowledge(
                request={
                    "subscription": self.subscription,
                    "ack_ids": list(ack_ids),
                }
            )

    def _nack(self, ack_ids: Sequence[str]) -> None:
        if ack_ids:
            self.subscriber.modify_ack_deadline(
                request={
                    "subscription": self.subscription,
                    "ack_ids": list(ack_ids),
                    "ack_deadline_seconds": 0,
                }
            )

    def run(self) -> RunReport:
        report = RunReport(mode="BATCH_PULL_SERVERLESS")
        started = self.monotonic()
        try:
            self._drain(report, started)
        finally:
            report.elapsed_sec = round(self.monotonic() - started, 3)
        return report

    def _drain(self, report: RunReport, started: float) -> None:
        while report.messages < self.config.max_messages:
            if self.monotonic() - started >= self.config.max_runtime_sec:
                report.stop_reason = "runtime_budget"
                break
            size = min(
                self.config.microbatch_size,
                self.config.max_messages - report.messages,
            )
            response = self.subscriber.pull(
                request={
                    "subscription": self.subscription,
                    "max_messages": size,
                },
                timeout=PULL_TIMEOUT_SEC,
            )
            received = list(response.received_messages)
            if not received:
                break
            report.messages += len(received)
            envelopes: list[RawReviewEnvelope] = []
            acks: dict[str, list[str]] = {}
            poison: list[str] = []
            for item in received:
                envelope = _parse(item.message)
                if envelope is None:
                    poison.append(item.ack_id)
                    log_json(
                        "WARNING",
                        "Unparseable raw review message acknowledged",
                        message_id=getattr(item.message, "message_id", None),
                    )
                    continue
                envelopes.append(envelope)
                acks.setdefault(envelope.event_id, []).append(item.ack_id)
            # Un mensaje veneno no es reintentable: se confirma sin texto.
            self._ack(poison)
            report.poison += len(poison)
            report.duplicate_messages += sum(len(a) - 1 for a in acks.values())
            ack_ids = [a for ids in acks.values() for a in ids]
            try:
                with AckDeadlineRenewer(
                    self.subscriber,
                    self.subscription,
                    ack_ids,
                    interval_sec=self.renew_interval_sec,
                    deadline_sec=self.config.ack_deadline_sec,
                ):
                    outcome = self.processor.process(envelopes)
            except TRANSIENT:
                self._nack(ack_ids)
                report.transient_failure = True
                report.stop_reason = "transient_failure"
                break
            except BaseException:
                self._nack(ack_ids)
                raise
            self._ack([a for e in outcome.terminal for a in acks.get(e, [])])
            self._nack([a for e in outcome.retryable for a in acks.get(e, [])])
            report.add(outcome)
            report.add_pages(self.processor.reconcile(outcome.pages))
        else:
            report.stop_reason = "message_budget"


# ------------------------------------------------------- manifest replay
def _latest_manifests(
    ingestion: WatermarkRepository, bank: BankKey
) -> list[PageManifest]:
    snapshot = ingestion.load(bank)
    ledger = snapshot.state.manifest_ledger
    if ledger is None:
        return []
    latest: dict[tuple[str, str], PageManifest] = {}
    for raw in ingestion.iter_ledger(ledger):
        manifest = ingestion.get_manifest(ObjectReference.model_validate(raw))
        key = (manifest.stream_id, manifest.page_id)
        current = latest.get(key)
        if (
            current is None
            or manifest.manifest_version > current.manifest_version
        ):
            latest[key] = manifest
    return sorted(latest.values(), key=lambda m: (m.fetched_at, m.page_id))


class ManifestBackfill:
    """Reprocesa páginas comprometidas sin cierre, leyendo su captura."""

    def __init__(
        self,
        ingestion: WatermarkRepository,
        processor: MicrobatchProcessor,
        config: SanitizationExecutionConfig,
        *,
        banks: Sequence[BankKey] = tuple(BankKey),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ingestion = ingestion
        self.processor = processor
        self.config = config
        self.banks = banks
        self.monotonic = monotonic

    def run(self) -> RunReport:
        report = RunReport(mode="GCS_BACKFILL_MANIFESTS")
        started = self.monotonic()
        try:
            self._replay(report, started)
        finally:
            report.elapsed_sec = round(self.monotonic() - started, 3)
        return report

    def _replay(self, report: RunReport, started: float) -> None:
        ledger = self.processor.ledger
        for bank in self.banks:
            for manifest in _latest_manifests(self.ingestion, bank):
                if report.messages >= self.config.max_messages:
                    report.stop_reason = "message_budget"
                    return
                if self.monotonic() - started >= self.config.max_runtime_sec:
                    report.stop_reason = "runtime_budget"
                    return
                if ledger.page_closure(bank, manifest.page_id) is not None:
                    continue
                key = (bank, manifest.stream_id, manifest.page_id)
                try:
                    envelopes = read_committed_capture(self.ingestion, manifest)
                except BackupUnavailable:
                    report.expired_captures += 1
                    status = ledger.reconcile_page(*key, staging_expired=True)
                    report.add_pages({status.value: 1})
                    continue
                report.messages += len(envelopes)
                for start in range(
                    0, len(envelopes), self.config.microbatch_size
                ):
                    chunk = envelopes[
                        start : start + self.config.microbatch_size
                    ]
                    try:
                        outcome = self.processor.process(chunk)
                    except TRANSIENT:
                        report.transient_failure = True
                        report.stop_reason = "transient_failure"
                        return
                    report.add(outcome)
                report.add_pages(self.processor.reconcile([key]))


# --------------------------------------------------------------- wiring
@dataclass
class Services:
    ingestion: WatermarkRepository
    ledger: ProcessingLedgerRepository
    upsert: BigQueryTdsUpsertManager
    do_fn: Callable[[], BatchCloudDlpDeidentifyDoFn]
    subscriber: Any = None
    subscription: str = ""

    def processor(self) -> MicrobatchProcessor:
        return MicrobatchProcessor(
            self.ledger,
            self.upsert,
            lambda batch: run_do_fn(self.do_fn(), batch),
        )


def subscription_path(settings: Settings) -> str:
    name = settings.pubsub_raw_subscription
    if name.startswith("projects/"):
        return name
    return f"projects/{settings.gcp_project_id}/subscriptions/{name}"


def build_services(
    settings: Settings, config: SanitizationExecutionConfig, parent: str
) -> Services:
    from google.cloud import bigquery, pubsub_v1, storage

    client = storage.Client(project=settings.gcp_project_id)
    layout = IngestionStorageLayout.model_validate(
        {k: getattr(settings, k) for k in IngestionStorageLayout.model_fields}
    )
    ingestion = WatermarkRepository(
        client, settings.gcs_raw_datalake_bucket, layout=layout
    )
    ledger = ProcessingLedgerRepository(
        client, settings.gcs_raw_datalake_bucket, ingestion, layout=layout
    )
    upsert = BigQueryTdsUpsertManager(
        bigquery.Client(project=settings.gcp_project_id),
        project=settings.gcp_project_id,
        dataset=settings.bq_dataset_id,
        table=settings.bq_sanitized_tds_table,
    )

    def do_fn() -> BatchCloudDlpDeidentifyDoFn:
        return BatchCloudDlpDeidentifyDoFn(
            user_hash_salt=settings.user_hash_salt,
            parent=parent,
            inspect_template=settings.dlp_inspect_template_id,
            deidentify_template=settings.dlp_deidentify_template_id,
            use_cloud_dlp_api=config.use_cloud_dlp_api,
            max_rows=config.dlp_max_rows,
            max_bytes=config.dlp_max_bytes,
        )

    return Services(
        ingestion=ingestion,
        ledger=ledger,
        upsert=upsert,
        do_fn=do_fn,
        subscriber=pubsub_v1.SubscriberClient(),
        subscription=subscription_path(settings),
    )


ServicesFactory = Callable[
    [Settings, SanitizationExecutionConfig, str], Services
]


def _finish(report: RunReport) -> int:
    code = report.exit_code()
    log_json(
        "INFO" if code == EX_OK else "WARNING",
        "Sanitization run finished",
        exit_code=code,
        **{k: v for k, v in vars(report).items()},
    )
    return code


def _guarded(run: Callable[[], RunReport]) -> int:
    try:
        return _finish(run())
    except DlpConfigurationError:
        # Permisos o plantillas: detener sin ack (los mensajes vuelven).
        log_json("ERROR", "Cloud DLP configuration rejected the request")
        return EX_USAGE


def run_batch_pull(
    config: SanitizationExecutionConfig,
    settings: Settings,
    parent: str,
    services_factory: ServicesFactory = build_services,
) -> int:
    services = services_factory(settings, config, parent)
    drainer = PubSubDrainer(
        services.subscriber,
        services.subscription,
        services.processor(),
        config,
    )
    return _guarded(drainer.run)


def run_manifest_backfill(
    config: SanitizationExecutionConfig,
    settings: Settings,
    parent: str,
    services_factory: ServicesFactory = build_services,
) -> int:
    services = services_factory(settings, config, parent)
    backfill = ManifestBackfill(
        services.ingestion, services.processor(), config
    )
    return _guarded(backfill.run)
