"""Replay rápido: capturas de GCS al TDS con cierre por página (EPIC-4).

El camino por Pub/Sub deja un recibo por reseña (dos escrituras y varias
lecturas en GCS por evento), que domina el tiempo y el costo de una carga
histórica. Este modo lee las capturas que la ingesta ya guardó, sanea en
memoria, carga lotes grandes con un solo `MERGE` y deja **un cierre por
página**, que se compara contra el ledger que la ingesta comprometió:

* `RESOLVED`: todos los eventos del ledger de la página llegaron al TDS.
* `GAPS_DETECTED`: faltan o se pusieron en cuarentena (con sus IDs y motivo).

No hace falta `ack`; los mensajes que sigan en Pub/Sub se descartan con un
`seek` de la suscripción. La idempotencia es la del `MERGE`, y repetir el modo
es seguro porque las páginas con cierre se saltan.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from ingestion_worker.publisher import (
    BackupUnavailable,
    CaptureUnreadable,
    read_committed_capture,
)
from ingestion_worker.watermark_store import IntegrityError, WatermarkRepository
from voc_common import (
    BankKey,
    PageManifest,
    RawReviewEnvelope,
    SanitizedReviewEnvelope,
    Settings,
)

from sanitization_pipeline.bq_writer import (
    BigQueryTdsUpsertManager,
    TdsWriteError,
)
from sanitization_pipeline.config import (
    PreflightError,
    SanitizationExecutionConfig,
)
from sanitization_pipeline.dlp_transforms import BatchSanitizer
from sanitization_pipeline.orchestrator import (
    BATCH_TIME_MARGIN,
    EX_USAGE,
    LedgerError,
    RunReport,
    Services,
    ServicesFactory,
    _execution,
    _finish,
    _latest_manifests,
    build_services,
    log_json,
)
from sanitization_pipeline.processing_ledger import (
    INCOMPLETE_CAPTURE,
    QUARANTINED,
    STAGING_EXPIRED,
    ProcessingLedgerRepository,
)

MODE = "GCS_FAST_REPLAY"


class _Unreadable:
    """Captura presente pero ilegible con este código (no es expiración)."""


UNREADABLE = _Unreadable()


@dataclass
class _Page:
    manifest: PageManifest
    captured: bool = True
    valid: list[SanitizedReviewEnvelope] = field(default_factory=list)
    quarantined: list[str] = field(default_factory=list)
    retryable: int = 0


class FastReplay:
    def __init__(
        self,
        ingestion: WatermarkRepository,
        ledger: ProcessingLedgerRepository,
        upsert: BigQueryTdsUpsertManager,
        sanitizer: BatchSanitizer,
        config: SanitizationExecutionConfig,
        *,
        banks: Sequence[BankKey] = tuple(BankKey),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ingestion = ingestion
        self.ledger = ledger
        self.upsert = upsert
        self.sanitizer = sanitizer
        self.config = config
        self.banks = banks
        self.monotonic = monotonic

    def run(self) -> RunReport:
        report = RunReport(mode=MODE)
        log_json(
            "INFO",
            "Sanitization run started",
            run_id=report.run_id,
            mode=MODE,
            upsert_batch_rows=self.config.upsert_batch_rows,
            max_runtime_sec=self.config.max_runtime_sec,
            io_workers=self.ledger.io_workers,
            **_execution(),
        )
        started = self.monotonic()
        try:
            self._replay(report, started)
        finally:
            report.elapsed_sec = round(self.monotonic() - started, 3)
        return report

    # ------------------------------------------------------------- bancos
    def _replay(self, report: RunReport, started: float) -> None:
        for bank in self.banks:
            try:
                manifests = _latest_manifests(
                    self.ingestion, bank, self.ledger.io_workers
                )
                pending = self.ledger.pending_pages(bank, manifests)
            except (ValueError, IntegrityError, LedgerError) as exc:
                report.bank_errors[bank.value] = type(exc).__name__
                log_json(
                    "ERROR",
                    "Bank state unreadable; skipping bank",
                    run_id=report.run_id,
                    bank_id=bank.value,
                    error=type(exc).__name__,
                )
                continue
            if not self._bank(bank, pending, report, started):
                return

    def _bank(
        self,
        bank: BankKey,
        pending: list[PageManifest],
        report: RunReport,
        started: float,
    ) -> bool:
        """Procesa las pendientes; False si hay que detener la corrida."""
        group = max(self.ledger.io_workers * 2, 1)
        buffer: list[_Page] = []
        rows = 0
        last_flush = 0.0
        for start in range(0, len(pending), group):
            elapsed = self.monotonic() - started
            if elapsed + last_flush * BATCH_TIME_MARGIN >= (
                self.config.max_runtime_sec
            ):
                report.stop_reason = "runtime_budget"
                if buffer:
                    # Lo ya leído y saneado se carga antes de parar.
                    self._flush(bank, buffer, report)
                return False
            phase = self.monotonic()
            window = pending[start : start + group]
            captures = self.ledger.parallel_map(self._read, window)
            report.add_time("capture_read_s", self.monotonic() - phase)
            phase = self.monotonic()
            for manifest, envelopes in zip(window, captures, strict=True):
                page = self._sanitize(manifest, envelopes, report)
                buffer.append(page)
                rows += len(page.valid)
            report.add_time("sanitize_s", self.monotonic() - phase)
            if rows >= self.config.upsert_batch_rows:
                flushed = self.monotonic()
                if not self._flush(bank, buffer, report):
                    return False
                last_flush = self.monotonic() - flushed
                buffer, rows = [], 0
        if buffer:
            return self._flush(bank, buffer, report)
        return True

    # -------------------------------------------------------------- páginas
    def _read(
        self, manifest: PageManifest
    ) -> list[RawReviewEnvelope] | _Unreadable | None:
        try:
            return read_committed_capture(self.ingestion, manifest)
        except CaptureUnreadable:
            return UNREADABLE
        except BackupUnavailable:
            return None

    def _sanitize(
        self,
        manifest: PageManifest,
        envelopes: list[RawReviewEnvelope] | _Unreadable | None,
        report: RunReport,
    ) -> _Page:
        if isinstance(envelopes, _Unreadable):
            # El cierre es irreversible (el primero gana): una captura que
            # existe pero no se entiende queda abierta hasta tener lector.
            log_json(
                "ERROR",
                "Capture unreadable; page stays open",
                run_id=report.run_id,
                bank_id=manifest.bank_id.value,
                page_id=manifest.page_id,
            )
            return _Page(manifest, retryable=max(manifest.valid_count, 1))
        if envelopes is None:
            report.expired_captures += 1
            return _Page(manifest, captured=False)
        report.messages += len(envelopes)
        result = self.sanitizer.sanitize(envelopes)
        return _Page(
            manifest,
            valid=result.valid,
            quarantined=[r.event_id for r in result.quarantined],
            retryable=len(result.retryable),
        )

    def _flush(
        self, bank: BankKey, buffer: list[_Page], report: RunReport
    ) -> bool:
        valid = [env for page in buffer for env in page.valid]
        began = self.monotonic()
        batch_rows = len(valid)
        try:
            commit = self.upsert.upsert_sanitized_batch(valid)
        except TdsWriteError:
            report.transient_failure = True
            report.stop_reason = "transient_failure"
            log_json(
                "ERROR",
                "Fast replay batch failed; its pages stay open",
                run_id=report.run_id,
                bank_id=bank.value,
                pages=len(buffer),
                rows=batch_rows,
            )
            return False
        report.add_time("bigquery_s", self.monotonic() - began)
        report.bigquery_jobs += len(commit.job_ids)
        report.tds_committed += batch_rows
        began = self.monotonic()
        counts: dict[str, int] = {}
        for page in buffer:
            status = self._close(page, report)
            if status is not None:
                counts[status] = counts.get(status, 0) + 1
        report.add_pages(counts)
        report.add_time("closure_s", self.monotonic() - began)
        log_json(
            "INFO",
            "Fast replay batch finished",
            run_id=report.run_id,
            bank_id=bank.value,
            pages=counts,
            rows=batch_rows,
            rows_merged=commit.rows_merged,
        )
        return True

    def _close(self, page: _Page, report: RunReport) -> str | None:
        manifest = page.manifest
        if page.retryable:
            # Sin cierre: la página se reintenta en la siguiente corrida.
            report.events_retryable += page.retryable
            return None
        expected = self.ledger.expected_event_ids(manifest)
        done = {e.event_id for e in page.valid} | set(page.quarantined)
        missing = [e for e in expected if e not in done]
        if not page.captured:
            reason = STAGING_EXPIRED
        elif missing:
            reason = INCOMPLETE_CAPTURE
        else:
            reason = QUARANTINED
        report.quarantined += len(page.quarantined)
        status = self.ledger.close_page(
            manifest,
            committed=len(page.valid),
            quarantined=page.quarantined,
            missing=missing,
            reason=reason,
        )
        if status.value != "RESOLVED":
            log_json(
                "WARNING",
                "Page closed",
                run_id=report.run_id,
                bank_id=manifest.bank_id.value,
                page_id=manifest.page_id,
                status=status.value,
                reason=reason,
                missing=len(missing),
                quarantined=len(page.quarantined),
            )
        return status.value


def run_fast_replay(
    config: SanitizationExecutionConfig,
    settings: Settings,
    parent: str,
    services_factory: ServicesFactory = build_services,
) -> int:
    if config.use_cloud_dlp_api:
        raise PreflightError("GCS_FAST_REPLAY uses local regex only")
    services: Services = services_factory(settings, config, parent)
    sanitizer = BatchSanitizer(user_hash_salt=settings.user_hash_salt)
    replay = FastReplay(
        services.ingestion,
        services.ledger,
        services.upsert,
        sanitizer,
        config,
    )
    return _finish(replay.run())


__all__ = ["EX_USAGE", "FastReplay", "run_fast_replay"]
