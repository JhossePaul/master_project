"""Recorrido reanudable por páginas con presupuestos y recuperación (3.4).

El ejecutor coordina cliente, publisher y repositorio. No decide cobertura
absoluta: confirma progreso solo por páginas respaldadas y publicadas, y cierra
fronteras con evidencia de traversal observado. Los SDK de GCS/Pub/Sub son
síncronos y se ejecutan en threadpool; heartbeat y commits se serializan en la
misma tarea.
"""

import asyncio
import hashlib
import logging
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol, TypeVar

from voc_common import (
    DEFAULT_USER_AGENTS,
    BankKey,
    CompletionEvidence,
    CoverageStatus,
    HistoricalPlan,
    IngestionExecutionConfig,
    IngestionMode,
    IngestionRunAudit,
    PageManifest,
    PlanExtensionEvent,
    RecoveryStatus,
    RunAuditStatus,
    ScanContext,
    ScanStatus,
    ScanStreamState,
)
from voc_common.schemas import StarRating, ensure_utc

from ingestion_worker.extractor import PlayStoreClient
from ingestion_worker.playstore_protocol import (
    PROTOCOL_VERSION,
    EmptyAmbiguousError,
    ProtocolError,
    RateLimitedError,
    RpcPageResult,
    TransportError,
)
from ingestion_worker.publisher import (
    BackupUnavailable,
    PublicationIncomplete,
    RawReviewBatchPublisher,
)
from ingestion_worker.watermark_store import (
    IntegrityError,
    LeaseConflict,
    LeaseHandle,
    RepositorySnapshot,
    ReviewLedgerEntry,
    StateConflict,
    WatermarkRepository,
)

T = TypeVar("T")
_LOG = logging.getLogger(__name__)
_TERMINAL = (ScanStatus.TARGET_REACHED, ScanStatus.SOURCE_EXHAUSTED_OBSERVED)


class ExtractionStatus(StrEnum):
    TARGET_REACHED = "TARGET_REACHED"
    SOURCE_EXHAUSTED_OBSERVED = "SOURCE_EXHAUSTED_OBSERVED"
    PARTIAL_RATE_LIMITED = "PARTIAL_RATE_LIMITED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    PAUSED_BACKLOG = "PAUSED_BACKLOG"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    PUBLICATION_INCOMPLETE = "PUBLICATION_INCOMPLETE"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    BLOCKED = "BLOCKED"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    LEASE_CONFLICT = "LEASE_CONFLICT"


_AUDIT_STATUS = {
    ExtractionStatus.TARGET_REACHED: RunAuditStatus.COMPLETED,
    ExtractionStatus.SOURCE_EXHAUSTED_OBSERVED: RunAuditStatus.COMPLETED,
    ExtractionStatus.PARTIAL_RATE_LIMITED: RunAuditStatus.PAUSED,
    ExtractionStatus.BUDGET_EXHAUSTED: RunAuditStatus.PAUSED,
    ExtractionStatus.PAUSED_BACKLOG: RunAuditStatus.PAUSED,
    ExtractionStatus.PUBLICATION_INCOMPLETE: RunAuditStatus.PAUSED,
    ExtractionStatus.RECOVERY_REQUIRED: RunAuditStatus.RECOVERY_REQUIRED,
    ExtractionStatus.PROTOCOL_ERROR: RunAuditStatus.FAILED,
    ExtractionStatus.BLOCKED: RunAuditStatus.FAILED,
    ExtractionStatus.TRANSPORT_ERROR: RunAuditStatus.FAILED,
}


class BacklogSignal(Protocol):
    """Presión de sanitización (EPIC-4); solo pausa el histórico."""

    def should_pause(self, bank_id: BankKey, mode: IngestionMode) -> bool: ...


class NoBacklogPressure:
    """Sin consumidor desplegado no hay señal: nunca pausa."""

    def should_pause(self, bank_id: BankKey, mode: IngestionMode) -> bool:
        return False


@dataclass(frozen=True)
class ExtractionRequest:
    bank_id: BankKey
    mode: IngestionMode
    # Histórico: reusar/extender un plan concreto; None elige el plan abierto.
    plan_id: str | None = None
    # Particiones para un plan nuevo; None es el stream global.
    star_filters: tuple[StarRating | None, ...] = (None,)
    # Límite blando: se completa la página validada que lo cruza.
    max_reviews: int | None = None
    run_id: str | None = None
    # Job histórico: continuar solo un stream del plan persistido.
    stream_id: str | None = None
    # False exige un plan persistido; el Job nunca crea ni extiende planes.
    create_plan: bool = True

    def __post_init__(self) -> None:
        if self.stream_id is not None and self.plan_id is None:
            raise ValueError("stream selection requires its plan")
        if not self.star_filters or len(set(self.star_filters)) != len(
            self.star_filters
        ):
            raise ValueError("partitions must be unique and non-empty")
        if any(
            s is not None and s not in range(1, 6) for s in self.star_filters
        ):
            raise ValueError("star partitions must be 1..5 or global")
        if self.max_reviews is not None and self.max_reviews <= 0:
            raise ValueError("review limit must be positive")


@dataclass
class ExtractionResult:
    run_id: str
    bank_id: BankKey
    mode: IngestionMode
    status: ExtractionStatus
    reason: str | None = None
    plan_id: str | None = None
    stream_ids: list[str] = field(default_factory=list)
    pages_committed: int = 0
    reviews_extracted: int = 0
    reviews_published: int = 0
    reviews_discarded: int = 0
    requests: int = 0
    response_bytes: int = 0
    recovery_requests: int = 0
    elapsed_sec: float = 0.0
    observed_min_at: datetime | None = None
    observed_max_at: datetime | None = None
    committed_high_at: datetime | None = None
    candidate_high_at: datetime | None = None
    recovery_actions: list[str] = field(default_factory=list)
    abandoned_captures: list[str] = field(default_factory=list)
    reconciliation_missing: int = 0
    audit_recorded: bool = False


class _Stop(Exception):  # noqa: N818 - control flow, never escapes the runner
    def __init__(self, status: ExtractionStatus, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


class _CursorRejected(Exception):  # noqa: N818
    """HTTP 4xx sobre un cursor: síntoma, no prueba de expiración."""


def select_user_agent(
    run_id: str, config: IngestionExecutionConfig
) -> str | None:
    """Rotación opcional y determinista por ejecución; nunca por bloqueo."""
    if not config.scraper_rotate_user_agent:
        return None
    digest = hashlib.sha256(run_id.encode()).digest()
    return DEFAULT_USER_AGENTS[digest[0] % len(DEFAULT_USER_AGENTS)]


def new_run_id(mode: IngestionMode, at: datetime) -> str:
    prefix = {
        IngestionMode.INCREMENTAL: "inc",
        IngestionMode.BACKFILL: "bf",
        IngestionMode.FULL_BACKFILL: "full",
    }[mode]
    return f"{prefix}-{at:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"


class _Budget:
    def __init__(
        self,
        config: IngestionExecutionConfig,
        monotonic: Callable[[], float],
    ) -> None:
        self.config = config
        self.monotonic = monotonic
        self.started = monotonic()
        self.requests = 0
        self.pages = 0
        self.bytes = 0
        self.recovery = 0

    def remaining_sec(self) -> float:
        return self.config.ingestion_max_runtime_sec - (
            self.monotonic() - self.started
        )

    def check(self, *, recovery: bool) -> None:
        cfg = self.config
        reason = (
            "requests"
            if self.requests >= cfg.ingestion_max_requests
            else "response_bytes"
            if self.bytes >= cfg.ingestion_max_response_bytes
            else "runtime"
            if self.remaining_sec() < cfg.scraper_timeout_sec
            else "recovery_requests"
            if recovery and self.recovery >= cfg.ingestion_max_recovery_requests
            else "pages"
            if not recovery and self.pages >= cfg.ingestion_max_pages
            else None
        )
        if reason:
            raise _Stop(ExtractionStatus.BUDGET_EXHAUSTED, reason)


class PlayStoreResilientExtractor:
    def __init__(
        self,
        repository: WatermarkRepository,
        publisher: RawReviewBatchPublisher,
        client: PlayStoreClient,
        config: IngestionExecutionConfig,
        *,
        backlog: BacklogSignal | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        if publisher.repository is not repository:
            raise ValueError("publisher must share the repository")
        self.repository = repository
        self.publisher = publisher
        self.client = client
        self.config = config
        self.backlog = backlog or NoBacklogPressure()
        self.clock = clock
        self.monotonic = monotonic
        self.sleep = sleep
        self.rng = rng or random.SystemRandom()

    async def run_extraction(
        self, request: ExtractionRequest
    ) -> ExtractionResult:
        return await _Run(self, request).execute()

    async def prepare_plan(self, request: ExtractionRequest) -> HistoricalPlan:
        """Persiste (crea o extiende a FULL) el plan sin consultar el origen.

        La API lo usa antes de lanzar el Job histórico, que solo continúa
        planes persistidos. LeaseConflict indica una corrida en curso.
        """
        if request.mode == IngestionMode.INCREMENTAL:
            raise ValueError("incremental runs have no historical plan")
        run = _Run(self, request)
        await run._acquire(new_run_id(request.mode, run._now()))
        try:
            plan = await run._plan()
            if request.mode == IngestionMode.FULL_BACKFILL:
                await run._extend(plan)
            elif plan.requested_lower_at is None:
                raise ValueError("plan is already FULL")
            return self.repository.get_plan(await run._load(), plan.plan_id)
        except _Stop as stop:
            raise ValueError(stop.reason) from None
        finally:
            await run._finish_session(audit=False)


class _Run:
    """Estado de una invocación; nada aquí es estado durable."""

    def __init__(
        self, owner: PlayStoreResilientExtractor, request: ExtractionRequest
    ) -> None:
        self.x = owner
        self.repo = owner.repository
        self.cfg = owner.config
        self.request = request
        self.bank = request.bank_id
        self.budget = _Budget(owner.config, owner.monotonic)
        self.failures = 0
        self.last_heartbeat = owner.monotonic()
        self.handle: LeaseHandle | None = None
        self.live: set[str] = set()
        self.fetches = 0
        self.rescan_from: dict[str, datetime] = {}
        self.result = ExtractionResult(
            run_id=request.run_id or "pending",
            bank_id=request.bank_id,
            mode=request.mode,
            status=ExtractionStatus.BUDGET_EXHAUSTED,
        )

    # ------------------------------------------------------------ plumbing
    async def _io(self, fn: Callable[..., T], *args: object, **kw: object) -> T:
        return await asyncio.to_thread(fn, *args, **kw)

    def _now(self) -> datetime:
        return ensure_utc(self.x.clock())

    async def _heartbeat(self, *, force: bool = False) -> None:
        if self.handle is None:
            return
        due = (
            self.x.monotonic() - self.last_heartbeat
            >= self.cfg.ingestion_heartbeat_interval_sec
        )
        if force or due:
            await self._io(self.repo.renew_lease, self.handle)
            self.last_heartbeat = self.x.monotonic()

    async def _pause(self, seconds: float) -> None:
        """Espera troceada para renovar el lease antes de su vencimiento."""
        if seconds > self.budget.remaining_sec() - self.cfg.scraper_timeout_sec:
            raise _Stop(ExtractionStatus.BUDGET_EXHAUSTED, "runtime")
        step = self.cfg.ingestion_heartbeat_interval_sec / 2
        while seconds > 0:
            chunk = min(seconds, step)
            await self.x.sleep(chunk)
            seconds -= chunk
            await self._heartbeat()

    async def _fetch(
        self,
        context: ScanContext,
        token: str | None,
        *,
        recovery: bool = False,
    ) -> RpcPageResult:
        retries = 0
        while True:
            self.budget.check(recovery=recovery)
            await self._heartbeat()
            if self.fetches and not retries:
                await self._pause(
                    self.cfg.scraper_base_delay_sec
                    + self.x.rng.uniform(0, self.cfg.scraper_max_jitter_sec)
                )
            self.fetches += 1
            self.budget.requests += 1
            if recovery:
                self.budget.recovery += 1
            retry_after: float | None = None
            limited = False
            try:
                page = await self.x.client.fetch_page(self.bank, context, token)
            except RateLimitedError as exc:
                limited, retry_after = True, exc.retry_after_sec
            except EmptyAmbiguousError:
                raise _Stop(
                    ExtractionStatus.PROTOCOL_ERROR, "empty_ambiguous"
                ) from None
            except ProtocolError:
                raise _Stop(
                    ExtractionStatus.PROTOCOL_ERROR, "protocol_shape"
                ) from None
            except TransportError as exc:
                code = exc.status_code
                if code == 403:
                    # Investigar antes de tratarlo como límite; sin evasión.
                    raise _Stop(ExtractionStatus.BLOCKED, "http_403") from None
                if code is not None and 400 <= code < 500 and code != 429:
                    if token is not None:
                        raise _CursorRejected(code) from None
                    raise _Stop(
                        ExtractionStatus.TRANSPORT_ERROR, f"http_{code}"
                    ) from None
                limited = code == 503
            else:
                self.failures = 0
                self.budget.bytes += len(page.raw_body)
                if not recovery:
                    self.budget.pages += 1
                return page
            failed = (
                ExtractionStatus.PARTIAL_RATE_LIMITED
                if limited
                else ExtractionStatus.TRANSPORT_ERROR
            )
            self.failures += 1
            retries += 1
            if self.failures >= self.cfg.ingestion_circuit_breaker_threshold:
                raise _Stop(failed, "circuit_open")
            if retries > self.cfg.scraper_max_retries:
                raise _Stop(failed, "retries_exhausted")
            delay = (
                retry_after
                if retry_after is not None
                else min(
                    self.cfg.ingestion_max_backoff_sec,
                    self.cfg.scraper_base_delay_sec * 2 ** (retries - 1),
                )
                + self.x.rng.uniform(0, self.cfg.scraper_max_jitter_sec)
            )
            if delay > self.cfg.ingestion_max_backoff_sec:
                raise _Stop(failed, "retry_after_exceeds_backoff")
            await self._pause(delay)

    def _account(self, page: PageManifest, *, published: bool) -> None:
        r = self.result
        r.pages_committed += 1
        r.reviews_extracted += page.raw_count
        r.reviews_discarded += page.discarded_count
        if published:
            r.reviews_published += page.valid_count
        if page.observed_min_at is not None and page.observed_max_at:
            lows = [page.observed_min_at, r.observed_min_at]
            highs = [page.observed_max_at, r.observed_max_at]
            r.observed_min_at = min(x for x in lows if x is not None)
            r.observed_max_at = max(x for x in highs if x is not None)

    async def _load(self) -> RepositorySnapshot:
        return await self._io(self.repo.load, self.bank)

    async def _stream(self, stream_id: str) -> ScanStreamState:
        snapshot = await self._load()
        return self.repo.get_stream(snapshot, stream_id)

    # ------------------------------------------------------------- lifecycle
    async def execute(self) -> ExtractionResult:
        started = self.x.monotonic()
        try:
            try:
                await self._dispatch()
            except _Stop as stop:
                self.result.status = stop.status
                self.result.reason = stop.reason
            except LeaseConflict:
                self._lease_lost("lease_lost")
            except StateConflict:
                self._lease_lost("state_conflict")
            r = self.result
            r.requests = self.budget.requests
            r.response_bytes = self.budget.bytes
            r.recovery_requests = self.budget.recovery
            r.elapsed_sec = self.x.monotonic() - started
            await self._finish_session(audit=True)
        finally:
            # Error inesperado: liberar sin auditar; el respaldo permite
            # reintentar.
            await self._finish_session(audit=False)
        return self.result

    def _lease_lost(self, reason: str) -> None:
        self.result.status = ExtractionStatus.LEASE_CONFLICT
        self.result.reason = reason
        self.handle = None

    async def _dispatch(self) -> None:
        snapshot = await self._load()
        pending_runs = {
            self.repo.get_manifest(c.manifest).run_id
            for c in snapshot.catalog.pending.values()
        }
        if len(pending_runs) > 1:
            raise _Stop(
                ExtractionStatus.RECOVERY_REQUIRED, "pending_from_many_runs"
            )
        mode = self.request.mode
        active = snapshot.state.incremental.active_run_id
        if mode == IngestionMode.INCREMENTAL and active:
            run_id = active  # Reanudar la corrida pendiente antes de otra.
        else:
            run_id = self.request.run_id or new_run_id(mode, self._now())
        self.result.run_id = run_id
        drain_run = next(iter(pending_runs), None)
        if drain_run is not None and drain_run != run_id:
            # Completar entregas desde GCS antes de consultar el origen.
            await self._acquire(drain_run)
            await self._drain()
            await self._finish_session(audit=False)
        await self._acquire(run_id)
        await self._audit(RunAuditStatus.STARTED)
        await self._drain()
        if mode == IngestionMode.INCREMENTAL:
            await self._incremental()
        else:
            await self._historical()

    async def _acquire(self, run_id: str) -> None:
        self.handle = await self._io(self.repo.acquire_lease, self.bank, run_id)
        self.last_heartbeat = self.x.monotonic()

    async def _finish_session(self, *, audit: bool) -> None:
        handle = self.handle
        if handle is None:
            return
        status = _AUDIT_STATUS.get(self.result.status)
        if audit and status is not None:
            await self._audit(status)
        self.handle = None
        try:
            await self._io(self.repo.release_lease, handle)
        except (LeaseConflict, StateConflict):
            _LOG.warning("Lease could not be released; it will expire")

    async def _audit(self, status: RunAuditStatus) -> None:
        handle = self.handle
        if handle is None:
            return
        r = self.result
        final = status != RunAuditStatus.STARTED
        try:
            snapshot = await self._load()
            event = IngestionRunAudit(
                bank_id=self.bank,
                app_id=snapshot.state.app_id,
                audit_event_id=(
                    f"{handle.owner_run_id}-e{handle.epoch}-"
                    f"{'end' if final else 'start'}"
                ),
                run_id=handle.owner_run_id,
                mode_executed=self.request.mode,
                status=status,
                updated_at=await self._io(self.repo._now),
                plan_id=r.plan_id,
                stream_id=r.stream_ids[0] if len(r.stream_ids) == 1 else None,
                reason=r.reason if final else None,
                state_revision=snapshot.state.revision,
                committed_high_at=snapshot.state.incremental.committed_high_at,
                observed_min_at=r.observed_min_at if final else None,
                observed_max_at=r.observed_max_at if final else None,
                pages_committed=r.pages_committed if final else None,
                reviews_extracted=r.reviews_extracted if final else None,
                reviews_published=r.reviews_published if final else None,
                reviews_discarded=r.reviews_discarded if final else None,
                recovery_requests=self.budget.recovery if final else None,
            )
            await self._io(self.repo.record_audit, handle, event)
            if final:
                r.audit_recorded = True
        except (LeaseConflict, StateConflict, IntegrityError, ValueError):
            # La cola de auditoría no confirma progreso; no se reintenta aquí.
            _LOG.warning("Run audit not recorded")

    # ------------------------------------------------------- durable replay
    async def _drain(self) -> None:
        handle = self._held()
        snapshot = await self._load()
        for page_id, capture in sorted(snapshot.catalog.pending.items()):
            manifest = self.repo.get_manifest(capture.manifest)
            if manifest.run_id != handle.owner_run_id:
                continue
            await self._heartbeat()
            try:
                await self._io(self.x.publisher.publish_page, handle, manifest)
            except PublicationIncomplete:
                raise _Stop(
                    ExtractionStatus.PUBLICATION_INCOMPLETE, "pending_capture"
                ) from None
            except BackupUnavailable:
                # Hueco observable: el frontier nunca avanzó por esta página;
                # el origen se vuelve a consultar desde su cursor de entrada.
                await self._io(self.repo.abandon_pending, handle, page_id)
                self.result.abandoned_captures.append(page_id)
                continue
            except (IntegrityError, ValueError):
                raise _Stop(
                    ExtractionStatus.RECOVERY_REQUIRED, "pending_unreconciled"
                ) from None
            self._account(manifest, published=True)

    def _held(self) -> LeaseHandle:
        if self.handle is None:
            raise LeaseConflict("no lease")
        return self.handle

    # ------------------------------------------------------------ traversal
    async def _traverse(
        self, stream_id: str, mode: IngestionMode, stop_at: datetime | None
    ) -> ScanStatus:
        """Avanza página a página hasta la cota, EOF observado o un _Stop."""
        handle = self._held()
        stream = await self._stream(stream_id)
        while True:
            if self._reached(stream, stop_at):
                return ScanStatus.TARGET_REACHED
            if stream.frontier_page_id is not None and (
                stream_id not in self.live or stream.output_token is None
            ):
                stream, eof = await self._recover(stream, mode)
                if eof:
                    return ScanStatus.SOURCE_EXHAUSTED_OBSERVED
                continue
            if (
                mode != IngestionMode.INCREMENTAL
                and self.x.backlog.should_pause(self.bank, mode)
            ):
                raise _Stop(ExtractionStatus.PAUSED_BACKLOG, "sanitization")
            limit = self.request.max_reviews
            if limit is not None and self.result.reviews_published >= limit:
                raise _Stop(ExtractionStatus.BUDGET_EXHAUSTED, "reviews")
            token = stream.output_token if stream.frontier_page_id else None
            try:
                page = await self._fetch(stream.context, token)
            except _CursorRejected:
                self.result.recovery_actions.append(
                    f"{stream_id}:CURSOR_REJECTED"
                )
                self.live.discard(stream_id)
                stream = await self._stream(stream_id)
                continue
            if token is not None and page.next_token == token:
                raise _Stop(
                    ExtractionStatus.RECOVERY_REQUIRED, "repeated_cursor"
                )
            fetched_at = self._now()
            attempt = uuid.uuid4().hex
            try:
                manifest = await self._io(
                    self.x.publisher.prepare_page,
                    handle,
                    stream,
                    page,
                    mode=mode,
                    fetched_at=fetched_at,
                    fetch_attempt_id=attempt,
                    input_token=token,
                )
                await self._io(self.x.publisher.publish_page, handle, manifest)
            except PublicationIncomplete:
                raise _Stop(
                    ExtractionStatus.PUBLICATION_INCOMPLETE, "page_publication"
                ) from None
            except ProtocolError:
                raise _Stop(
                    ExtractionStatus.PROTOCOL_ERROR, "page_rejected"
                ) from None
            except (IntegrityError, ValueError):
                raise _Stop(
                    ExtractionStatus.RECOVERY_REQUIRED, "chain_rejected_page"
                ) from None
            previous = stream.frontier_page_id
            stream = await self._stream(stream_id)
            if stream.frontier_page_id in (None, previous):
                raise _Stop(ExtractionStatus.RECOVERY_REQUIRED, "no_progress")
            self.live.add(stream_id)
            self._account(manifest, published=True)
            self._rescan_connected(stream)

    def _reached(
        self, stream: ScanStreamState, stop_at: datetime | None
    ) -> bool:
        return (
            stop_at is not None
            and stream.frontier_oldest_at is not None
            and stream.frontier_oldest_at <= stop_at
        )

    def _rescan_connected(self, stream: ScanStreamState) -> None:
        target = self.rescan_from.get(stream.stream_id)
        if (
            target is not None
            and stream.frontier_oldest_at is not None
            and stream.frontier_oldest_at <= target
        ):
            del self.rescan_from[stream.stream_id]
            self.result.recovery_actions.append(
                f"{stream.stream_id}:HEAD_RESCAN_CONNECTED"
            )

    async def _anchors(self, stream: ScanStreamState) -> list[PageManifest]:
        snapshot = await self._load()
        anchors: list[PageManifest] = []
        page_id = stream.frontier_page_id
        while (
            page_id and len(anchors) <= self.cfg.ingestion_recovery_max_anchors
        ):
            page = self.repo.find_page(snapshot, stream.stream_id, page_id)
            if page is None:
                raise _Stop(
                    ExtractionStatus.RECOVERY_REQUIRED,
                    "anchor_manifest_missing",
                )
            anchors.append(page)
            page_id = page.previous_page_id
        return anchors

    def _same_position(
        self, anchor: PageManifest, page: RpcPageResult, ids: set[str]
    ) -> bool:
        """Mismos IDs/forma en la posición; revisiones pueden diferir."""
        observed = {r.id_resena for r in page.reviews}
        return (
            page.raw_count == anchor.raw_count
            and len(page.discarded) == anchor.discarded_count
            and observed == ids
        )

    async def _recover(
        self, stream: ScanStreamState, mode: IngestionMode
    ) -> tuple[ScanStreamState, bool]:
        """Replay del ancla, anclas anteriores y, al final, nueva cadena."""
        handle = self._held()
        sid = stream.stream_id
        eof_check = stream.output_token is None and sid in self.live
        anchors = await self._anchors(stream)
        if eof_check:
            anchors = anchors[:1]
        for index, anchor in enumerate(anchors):
            recovery = (
                RecoveryStatus.ANCHOR_REPLAY
                if index == 0
                else RecoveryStatus.EARLIER_ANCHOR
            )
            try:
                page = await self._fetch(
                    stream.context, anchor.input_token, recovery=True
                )
            except _CursorRejected:
                self.result.recovery_actions.append(
                    f"{sid}:{recovery}:REJECTED"
                )
                continue
            except _Stop as stop:
                if stop.reason == "recovery_requests":
                    await self._mark_recovery_required(sid)
                    raise _Stop(
                        ExtractionStatus.RECOVERY_REQUIRED, "recovery_budget"
                    ) from None
                raise
            ids = {
                ReviewLedgerEntry.model_validate(e).review_id
                for e in self.repo.iter_ledger(anchor.ledger)
            }
            if not self._same_position(anchor, page, ids):
                self.result.recovery_actions.append(f"{sid}:{recovery}:DRIFT")
                continue
            if eof_check and page.next_token is None:
                await self._io(
                    self.repo.close_stream,
                    handle,
                    sid,
                    ScanStatus.SOURCE_EXHAUSTED_OBSERVED,
                )
                self.result.recovery_actions.append(f"{sid}:EOF_CONFIRMED")
                return await self._stream(sid), True
            current = await self._stream(sid)
            try:
                manifest, committed = await self._io(
                    self.x.publisher.capture_replay,
                    handle,
                    current,
                    anchor,
                    page,
                    mode=mode,
                    fetched_at=self._now(),
                    fetch_attempt_id=uuid.uuid4().hex,
                    recovery=recovery,
                )
                if committed is None:
                    await self._io(
                        self.x.publisher.publish_page, handle, manifest
                    )
                    self._account(manifest, published=True)
            except PublicationIncomplete:
                raise _Stop(
                    ExtractionStatus.PUBLICATION_INCOMPLETE,
                    "replay_publication",
                ) from None
            except (IntegrityError, ValueError, ProtocolError):
                self.result.recovery_actions.append(f"{sid}:{recovery}:INVALID")
                continue
            self.result.recovery_actions.append(f"{sid}:{recovery}:OK")
            self.live.add(sid)
            return await self._stream(sid), False
        if eof_check:
            # El EOF no se confirmó: tratarlo como recuperación ordinaria.
            self.live.discard(sid)
            return await self._stream(sid), False
        # Ninguna ancla sirve: nueva cadena desde la cabeza, sin saltos.
        if stream.frontier_oldest_at is not None:
            self.rescan_from[sid] = stream.frontier_oldest_at
        await self._io(self.repo.restart_chain, handle, sid)
        self.result.recovery_actions.append(f"{sid}:HEAD_RESCAN")
        self.live.add(sid)
        return await self._stream(sid), False

    async def _mark_recovery_required(self, stream_id: str) -> None:
        stream = await self._stream(stream_id)
        if stream.status in (ScanStatus.RUNNING, ScanStatus.PAUSED):
            await self._io(
                self.repo.set_stream_status,
                self._held(),
                stream_id,
                ScanStatus.RECOVERY_REQUIRED,
            )

    def _unconnected(self, stop: _Stop) -> _Stop:
        if (
            self.rescan_from
            and stop.status == ExtractionStatus.BUDGET_EXHAUSTED
        ):
            return _Stop(ExtractionStatus.RECOVERY_REQUIRED, "head_rescan_open")
        return stop

    # ----------------------------------------------------------- incremental
    async def _incremental(self) -> None:
        handle = self._held()
        snapshot = await self._load()
        progress = snapshot.state.incremental
        if progress.active_run_id is None:
            stream_id = f"inc-{handle.owner_run_id}"
            stream = ScanStreamState(
                bank_id=self.bank,
                app_id=snapshot.state.app_id,
                stream_id=stream_id,
                context=self._context(snapshot.state.app_id, None),
            )
            await self._io(self.repo.register, handle, [stream])
            await self._io(self.repo.start_incremental, handle, stream_id)
            snapshot = await self._load()
            progress = snapshot.state.incremental
        stream_id = progress.stream_id
        if stream_id is None:
            raise _Stop(
                ExtractionStatus.RECOVERY_REQUIRED, "incremental_stream"
            )
        self.result.stream_ids = [stream_id]
        baseline = progress.baseline_high_at
        cut_at = await self._incremental_cut(stream_id, baseline)
        try:
            outcome = await self._traverse(
                stream_id, IngestionMode.INCREMENTAL, cut_at
            )
        except _Stop as stop:
            raise self._unconnected(stop) from None
        finally:
            state = (await self._load()).state
            self.result.candidate_high_at = state.incremental.candidate_high_at
            self.result.committed_high_at = state.incremental.committed_high_at
        await self._close_incremental(stream_id, baseline, cut_at, outcome)

    async def _incremental_cut(
        self, stream_id: str, baseline: datetime | None
    ) -> datetime:
        """Ventana conservadora; la fecha nunca se envía al endpoint."""
        if baseline is not None:
            return baseline - timedelta(
                seconds=self.cfg.ingestion_incremental_revisit_window_sec
            )
        # Bootstrap: ventana explícita anclada a la primera página de la
        # corrida, estable entre reanudaciones. No representa el histórico.
        chain = await self._chain(stream_id)
        start = chain[-1].fetched_at if chain else self._now()
        return start - timedelta(
            seconds=self.cfg.ingestion_bootstrap_window_sec
        )

    async def _chain(self, stream_id: str) -> list[PageManifest]:
        snapshot = await self._load()
        stream = self.repo.get_stream(snapshot, stream_id)
        pages: list[PageManifest] = []
        page_id = stream.frontier_page_id
        while page_id:
            page = self.repo.find_page(snapshot, stream_id, page_id)
            if page is None:
                raise _Stop(
                    ExtractionStatus.RECOVERY_REQUIRED, "chain_manifest_missing"
                )
            pages.append(page)
            page_id = page.previous_page_id
        return pages

    async def _close_incremental(
        self,
        stream_id: str,
        baseline: datetime | None,
        cut_at: datetime,
        outcome: ScanStatus,
    ) -> None:
        handle = self._held()
        chain = await self._chain(stream_id)
        entries: dict[str, ReviewLedgerEntry] = {}
        for page in chain:
            for raw in self.repo.iter_ledger(page.ledger):
                entry = ReviewLedgerEntry.model_validate(raw)
                entries[entry.event_id] = entry
        if not entries:
            raise _Stop(ExtractionStatus.RECOVERY_REQUIRED, "empty_frontier")
        frontier = await self._io(
            self.repo.write_review_ledger,
            self.bank,
            f"inc-frontier-{handle.owner_run_id}",
            sorted(entries.values(), key=lambda e: (e.reviewed_at, e.event_id)),
        )
        snapshot = await self._load()
        previous = snapshot.state.incremental.frontier_ledger
        if previous is not None:
            # Reconciliación por ID estable: evidencia, no prueba de borrado.
            seen = {e.review_id for e in entries.values()}
            self.result.reconciliation_missing = sum(
                1
                for raw in self.repo.iter_ledger(previous)
                if (entry := ReviewLedgerEntry.model_validate(raw)).reviewed_at
                >= cut_at
                and entry.review_id not in seen
            )
        evidence = CompletionEvidence(
            coverage=CoverageStatus.TRAVERSAL_OBSERVED,
            checked_at=await self._io(self.repo._now),
            manifest_ids=tuple(p.page_id for p in reversed(chain)),
            boundary_ledger=frontier,
            source_exhausted_observed=(
                outcome == ScanStatus.SOURCE_EXHAUSTED_OBSERVED
            ),
            continuity_checked=True,
        )
        await self._io(self.repo.finish_incremental, handle, evidence, frontier)
        if outcome == ScanStatus.TARGET_REACHED:
            await self._io(self.repo.close_stream, handle, stream_id, outcome)
        state = (await self._load()).state
        self.result.committed_high_at = state.incremental.committed_high_at
        self.result.status = ExtractionStatus(outcome.value)
        self.result.reason = "bootstrap_window" if baseline is None else None

    # ------------------------------------------------------------ historical
    def _context(self, app_id: str, star: StarRating | None) -> ScanContext:
        return ScanContext(
            app_id=app_id,
            star_filter=star,
            page_size=self.cfg.scraper_page_size,
            protocol_version=PROTOCOL_VERSION,
        )

    async def _historical(self) -> None:
        handle = self._held()
        mode = self.request.mode
        plan = await self._plan()
        self.result.plan_id = plan.plan_id
        self.result.stream_ids = list(plan.stream_ids)
        if mode == IngestionMode.FULL_BACKFILL and plan.requested_lower_at:
            await self._extend(plan)
            plan = self.repo.get_plan(await self._load(), plan.plan_id)
        elif mode == IngestionMode.BACKFILL and plan.requested_lower_at is None:
            raise _Stop(ExtractionStatus.RECOVERY_REQUIRED, "plan_is_full")
        selected = plan.stream_ids
        if self.request.stream_id is not None:
            if self.request.stream_id not in plan.stream_ids:
                raise _Stop(
                    ExtractionStatus.RECOVERY_REQUIRED, "unknown_stream"
                )
            selected = (self.request.stream_id,)
            self.result.stream_ids = [self.request.stream_id]
        if plan.status in _TERMINAL:
            self.result.status = ExtractionStatus(plan.status.value)
            return
        await self._io(
            self.repo.set_plan_status, handle, plan.plan_id, ScanStatus.RUNNING
        )
        try:
            for stream_id in selected:
                stream = await self._stream(stream_id)
                if stream.status in _TERMINAL:
                    continue
                outcome = await self._traverse(
                    stream_id, mode, plan.requested_lower_at
                )
                if outcome == ScanStatus.TARGET_REACHED:
                    await self._io(
                        self.repo.close_stream, handle, stream_id, outcome
                    )
        except _Stop as stop:
            stop = self._unconnected(stop)
            await self._io(
                self.repo.set_plan_status,
                handle,
                plan.plan_id,
                ScanStatus.RECOVERY_REQUIRED
                if stop.status == ExtractionStatus.RECOVERY_REQUIRED
                else ScanStatus.PAUSED,
            )
            raise stop from None
        await self._close_plan(plan)

    async def _plan(self) -> HistoricalPlan:
        handle = self._held()
        snapshot = await self._load()
        if self.request.plan_id is None and not self.request.create_plan:
            raise _Stop(ExtractionStatus.RECOVERY_REQUIRED, "no_open_plan")
        if self.request.plan_id is not None:
            if self.request.plan_id not in snapshot.catalog.plans:
                raise _Stop(ExtractionStatus.RECOVERY_REQUIRED, "unknown_plan")
            return self.repo.get_plan(snapshot, self.request.plan_id)
        plans = [
            self.repo.get_plan(snapshot, pid)
            for pid in snapshot.state.historical_plan_ids
        ]
        full = self.request.mode == IngestionMode.FULL_BACKFILL
        candidates = [
            p
            for p in plans
            if p.status not in _TERMINAL
            or (full and p.status == ScanStatus.TARGET_REACHED)
        ]
        if candidates:
            return max(candidates, key=lambda p: p.started_at)
        if not self.request.create_plan:
            raise _Stop(ExtractionStatus.RECOVERY_REQUIRED, "no_open_plan")
        started = await self._io(self.repo._now)
        plan_id = f"plan-{self.bank.value.lower()}-{started:%Y%m%dT%H%M%SZ}"
        streams = [
            ScanStreamState(
                bank_id=self.bank,
                app_id=snapshot.state.app_id,
                stream_id=f"{plan_id}-{'all' if star is None else f's{star}'}",
                plan_id=plan_id,
                context=self._context(snapshot.state.app_id, star),
            )
            for star in self.request.star_filters
        ]
        plan = HistoricalPlan(
            bank_id=self.bank,
            app_id=snapshot.state.app_id,
            plan_id=plan_id,
            started_at=started,
            upper_anchor_at=started,
            requested_lower_at=(
                None
                if full
                else started
                - timedelta(days=365)  # Cota fijada una sola vez en T0.
            ),
            stream_ids=tuple(s.stream_id for s in streams),
        )
        await self._io(self.repo.register, handle, streams, plan=plan)
        return plan

    async def _extend(self, plan: HistoricalPlan) -> None:
        """FULL con el mismo contexto: mismo plan, T0, páginas y anclas."""
        handle = self._held()
        lower = plan.requested_lower_at
        if lower is None:
            return
        event = PlanExtensionEvent(
            event_id=f"full-{plan.plan_id}",
            extended_at=await self._io(self.repo._now),
            previous_lower_at=lower,
        )
        await self._io(self.repo.extend_plan, handle, plan.plan_id, event)
        for stream_id in plan.stream_ids:
            stream = await self._stream(stream_id)
            if stream.status == ScanStatus.TARGET_REACHED:
                await self._io(self.repo.reopen_stream, handle, stream_id)
        self.result.recovery_actions.append(f"{plan.plan_id}:EXTENDED_TO_FULL")

    async def _close_plan(self, plan: HistoricalPlan) -> None:
        handle = self._held()
        snapshot = await self._load()
        streams = [self.repo.get_stream(snapshot, s) for s in plan.stream_ids]
        pending = [s for s in streams if s.status not in _TERMINAL]
        if pending:
            # Ejecución por stream: el plan sigue abierto hasta que todos
            # sus streams terminen.
            await self._io(
                self.repo.set_plan_status,
                handle,
                plan.plan_id,
                ScanStatus.PAUSED,
            )
            done = {s.stream_id: s.status for s in streams}
            last = done[self.result.stream_ids[-1]]
            self.result.status = ExtractionStatus(last.value)
            self.result.reason = "plan_streams_pending"
            return
        exhausted = all(
            s.status == ScanStatus.SOURCE_EXHAUSTED_OBSERVED for s in streams
        )
        evidence = CompletionEvidence(
            coverage=CoverageStatus.TRAVERSAL_OBSERVED,
            checked_at=await self._io(self.repo._now),
            manifest_ids=tuple(
                s.frontier_page_id for s in streams if s.frontier_page_id
            ),
            source_exhausted_observed=exhausted,
            continuity_checked=True,
        )
        try:
            await self._io(
                self.repo.finish_plan, handle, plan.plan_id, evidence
            )
        except ValueError:
            # Mezcla de EOF y cota en un plan anual: no se certifica cierre.
            await self._io(
                self.repo.set_plan_status,
                handle,
                plan.plan_id,
                ScanStatus.PAUSED,
            )
            raise _Stop(
                ExtractionStatus.RECOVERY_REQUIRED, "plan_mixed_terminal"
            ) from None
        self.result.status = (
            ExtractionStatus.SOURCE_EXHAUSTED_OBSERVED
            if exhausted
            else ExtractionStatus.TARGET_REACHED
        )
