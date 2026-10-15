"""Recibos inmutables y cierre de páginas en GCS (EPIC-4 4.3).

Rutas relativas a `GCS_PROCESSING_RECEIPTS_PREFIX`:

* `{bank}/{page_id}/{event_id}.json`: recibo del evento en esa página.
* `{bank}/_events/{event_id}.json`: primer recibo terminal del evento.
* `{bank}/_pages/{page_id}.json`: cierre `RESOLVED` / `GAPS_DETECTED`.

Toda escritura es condicional (`if_generation_match=0`); si el objeto existe,
gana el primero (los recibos terminales no se reescriben). El estado de la
ingesta solo se lee con `WatermarkRepository`, sin lease ni escrituras.
"""

import re
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Annotated, Self, TypeVar

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage
from ingestion_worker.watermark_store import (
    ReviewLedgerEntry,
    WatermarkRepository,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator
from voc_common import (
    BankKey,
    IngestionStorageLayout,
    ProcessingReceipt,
    ProcessingStatus,
    SanitizationStatus,
    SanitizedReviewEnvelope,
)
from voc_common.schemas import NonEmpty, UtcDatetime

from sanitization_pipeline.bq_writer import envelope_digest

TERMINAL = (
    ProcessingStatus.TDS_COMMITTED,
    ProcessingStatus.FILTERED_LENGTH,
    ProcessingStatus.QUARANTINED,
)
STAGING_EXPIRED = "STAGING_EXPIRED"
QUARANTINED = "QUARANTINED"
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
Counter = Annotated[int, Field(ge=0)]
Model = TypeVar("Model", bound=BaseModel)


class LedgerError(RuntimeError):
    """Recibo ilegible o con identidad distinta: no se infiere progreso."""


class PageClosure(BaseModel):
    """Cierre de cobertura TDS de una página; solo IDs y conteos."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    bank_id: BankKey
    page_id: NonEmpty
    stream_id: NonEmpty
    plan_id: NonEmpty | None = None
    status: SanitizationStatus
    reason: NonEmpty | None = None
    manifest_version: Counter
    content_fingerprint: NonEmpty
    tds_committed: Counter = 0
    filtered_length: Counter = 0
    quarantined: Counter = 0
    missing: Counter = 0
    quarantined_event_ids: tuple[NonEmpty, ...] = ()
    missing_event_ids: tuple[NonEmpty, ...] = ()
    closed_at: UtcDatetime

    @model_validator(mode="after")
    def _closure(self) -> Self:
        if self.status not in (
            SanitizationStatus.RESOLVED,
            SanitizationStatus.GAPS_DETECTED,
        ):
            raise ValueError("only terminal page states are persisted")
        gaps = self.quarantined or self.missing
        if self.status == SanitizationStatus.RESOLVED and (
            gaps or self.reason is not None
        ):
            raise ValueError("resolved page cannot carry gaps")
        if self.status == SanitizationStatus.GAPS_DETECTED and (
            not gaps or self.reason is None
        ):
            raise ValueError("gap closure requires gaps and a reason")
        if (
            len(self.quarantined_event_ids) != self.quarantined
            or len(self.missing_event_ids) != self.missing
        ):
            raise ValueError("gap counts must match their event IDs")
        return self


def _segment(value: str) -> str:
    if not _SAFE.fullmatch(value):
        raise ValueError("identifier must be a safe path segment")
    return value


def tds_committed_receipts(
    envelopes: Sequence[SanitizedReviewEnvelope],
    job_ids: tuple[str, ...],
    processed_at: datetime,
) -> list[ProcessingReceipt]:
    """Recibos TDS_COMMITTED, incluidas revisiones superadas en el lote."""
    if not job_ids:
        raise ValueError("TDS receipts require BigQuery job IDs")
    return [
        ProcessingReceipt(
            bank_id=e.bank_id,
            app_id=e.app_id,
            receipt_id=e.event_id,
            event_id=e.event_id,
            review_id=e.review_id,
            source_revision=e.source_revision,
            page_id=e.page_id,
            status=ProcessingStatus.TDS_COMMITTED,
            result_digest=envelope_digest(e),
            bigquery_job_ids=job_ids,
            processed_at=processed_at,
        )
        for e in envelopes
    ]


class ProcessingLedgerRepository:
    def __init__(
        self,
        client: storage.Client,
        bucket: str,
        ingestion: WatermarkRepository,
        *,
        layout: IngestionStorageLayout | None = None,
        timeout_sec: float = 30.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not bucket or "/" in bucket or timeout_sec <= 0:
            raise ValueError("invalid receipts bucket or timeout")
        self.bucket = client.bucket(bucket)
        self.ingestion = ingestion
        self.prefix = (
            layout or IngestionStorageLayout()
        ).gcs_processing_receipts_prefix
        self.timeout_sec = timeout_sec
        self.clock = clock

    # ------------------------------------------------------------- paths
    def receipt_path(self, bank: BankKey, page_id: str, event_id: str) -> str:
        return (
            f"{self.prefix}/{bank.value}/{_segment(page_id)}/"
            f"{_segment(event_id)}.json"
        )

    def event_index_path(self, bank: BankKey, event_id: str) -> str:
        return f"{self.prefix}/{bank.value}/_events/{_segment(event_id)}.json"

    def closure_path(self, bank: BankKey, page_id: str) -> str:
        return f"{self.prefix}/{bank.value}/_pages/{_segment(page_id)}.json"

    # ---------------------------------------------------------- objects
    def _read(self, name: str, model: type[Model]) -> Model | None:
        try:
            data = self.bucket.blob(name).download_as_bytes(
                timeout=self.timeout_sec
            )
        except NotFound:
            return None
        try:
            return model.model_validate_json(data)
        except ValueError:
            raise LedgerError("unreadable ledger object") from None

    def _create_or_keep(self, name: str, value: Model) -> Model:
        """Primer escritor gana; un reintento devuelve lo ya persistido."""
        data = value.model_dump_json().encode()
        try:
            self.bucket.blob(name).upload_from_string(
                data,
                content_type="application/json",
                if_generation_match=0,
                timeout=self.timeout_sec,
            )
            return value
        except PreconditionFailed:
            existing = self._read(name, type(value))
            if existing is None:
                raise LedgerError(
                    "ledger object changed during write"
                ) from None
            return existing

    # --------------------------------------------------------- receipts
    def write_event_receipts(
        self, receipts: Iterable[ProcessingReceipt]
    ) -> list[ProcessingReceipt]:
        stored: list[ProcessingReceipt] = []
        for receipt in receipts:
            if receipt.status not in TERMINAL:
                raise ValueError("only terminal receipts are persisted")
            if receipt.receipt_id != receipt.event_id:
                raise ValueError("receipt_id must be the event_id")
            # Primero el recibo de la página; el índice lo vuelve visible.
            kept = self._create_or_keep(
                self.receipt_path(
                    receipt.bank_id, receipt.page_id, receipt.event_id
                ),
                receipt,
            )
            self._create_or_keep(
                self.event_index_path(receipt.bank_id, receipt.event_id), kept
            )
            stored.append(kept)
        return stored

    def find_already_processed_event_ids(
        self, bank: BankKey, event_ids: Iterable[str]
    ) -> dict[str, ProcessingReceipt]:
        found: dict[str, ProcessingReceipt] = {}
        for event_id in sorted(set(event_ids)):
            receipt = self._read(
                self.event_index_path(bank, event_id), ProcessingReceipt
            )
            if receipt is None:
                continue
            if (receipt.bank_id, receipt.event_id) != (bank, event_id) or (
                receipt.status not in TERMINAL
            ):
                raise LedgerError("event index identity mismatch")
            found[event_id] = receipt
        return found

    def copy_receipt_for_page(
        self, receipt: ProcessingReceipt, page_id: str
    ) -> ProcessingReceipt:
        """Mismo resultado para otra página que referencia el evento."""
        return ProcessingReceipt.model_validate(
            receipt.model_dump()
            | {"page_id": _segment(page_id), "processed_at": self.clock()}
        )

    def page_receipt(
        self, bank: BankKey, page_id: str, event_id: str
    ) -> ProcessingReceipt | None:
        receipt = self._read(
            self.receipt_path(bank, page_id, event_id), ProcessingReceipt
        )
        if receipt is not None and (
            receipt.bank_id,
            receipt.page_id,
            receipt.event_id,
        ) != (bank, page_id, event_id):
            raise LedgerError("page receipt identity mismatch")
        return receipt

    # ---------------------------------------------------- page closure
    def page_closure(self, bank: BankKey, page_id: str) -> PageClosure | None:
        return self._read(self.closure_path(bank, page_id), PageClosure)

    def reconcile_page(
        self,
        bank: BankKey,
        stream_id: str,
        page_id: str,
        *,
        staging_expired: bool = False,
    ) -> SanitizationStatus:
        """Cierra la página si todos sus eventos son terminales.

        Lee el manifiesto comprometido y su ledger completo (sin truncar).
        Sin manifiesto (la ingesta aún no comprometió la página) o con
        eventos pendientes devuelve PENDING sin escribir. Con
        `staging_expired`, los eventos sin recibo son un hueco explícito.
        """
        existing = self.page_closure(bank, page_id)
        if existing is not None:
            return existing.status
        snapshot = self.ingestion.load(bank)
        if stream_id not in snapshot.catalog.streams:
            return SanitizationStatus.PENDING
        manifest = self.ingestion.find_page(snapshot, stream_id, page_id)
        if manifest is None:
            return SanitizationStatus.PENDING
        counts = {status: 0 for status in TERMINAL}
        quarantined: list[str] = []
        missing: list[str] = []
        for raw in self.ingestion.iter_ledger(manifest.ledger):
            event_id = ReviewLedgerEntry.model_validate(raw).event_id
            receipt = self.page_receipt(bank, page_id, event_id)
            if receipt is None:
                missing.append(event_id)
                continue
            counts[receipt.status] += 1
            if receipt.status == ProcessingStatus.QUARANTINED:
                quarantined.append(event_id)
        if missing and not staging_expired:
            return SanitizationStatus.PENDING
        reason = (
            STAGING_EXPIRED if missing else QUARANTINED if quarantined else None
        )
        closure = PageClosure(
            bank_id=bank,
            page_id=page_id,
            stream_id=stream_id,
            plan_id=manifest.plan_id,
            status=(
                SanitizationStatus.GAPS_DETECTED
                if reason
                else SanitizationStatus.RESOLVED
            ),
            reason=reason,
            manifest_version=manifest.manifest_version,
            content_fingerprint=manifest.content_fingerprint,
            tds_committed=counts[ProcessingStatus.TDS_COMMITTED],
            filtered_length=counts[ProcessingStatus.FILTERED_LENGTH],
            quarantined=len(quarantined),
            missing=len(missing),
            quarantined_event_ids=tuple(sorted(quarantined)),
            missing_event_ids=tuple(sorted(missing)),
            closed_at=self.clock(),
        )
        return self._create_or_keep(
            self.closure_path(bank, page_id), closure
        ).status
