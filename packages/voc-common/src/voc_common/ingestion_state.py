"""Transiciones puras por página. No ejecuta GCS, publicaciones ni leases.

El repositorio proporciona manifiestos y referencias de ledger verificadas.
Persistir cada resultado con CAS/fencing antes de aceptar otro comando.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

from pydantic import BaseModel

from voc_common.constants import (
    CoverageStatus,
    PublicationStatus,
    RecoveryStatus,
    ScanStatus,
)
from voc_common.schemas import (
    CompletionEvidence,
    HistoricalPlan,
    IngestionWatermarkState,
    LedgerReference,
    PageManifest,
    PlanExtensionEvent,
    ScanStreamState,
    ensure_utc,
)

_Model = TypeVar("_Model", bound=BaseModel)


def _replace(model: _Model, **changes: Any) -> _Model:
    # model_copy(update=...) omite validadores Pydantic.
    return type(model).model_validate({**model.model_dump(), **changes})


@dataclass(frozen=True)
class PageTransition:
    state: IngestionWatermarkState
    stream: ScanStreamState
    manifest: PageManifest
    duplicate: bool = False


def _check(
    state: IngestionWatermarkState,
    stream: ScanStreamState,
    expected_revision: int,
    at: datetime,
) -> None:
    if state.revision != expected_revision:
        raise ValueError("stale state revision")
    if (stream.bank_id, stream.app_id) != (state.bank_id, state.app_id):
        raise ValueError("stream identity differs from root")
    if stream.stream_id not in state.stream_ids:
        raise ValueError("stream not registered in root")
    if stream.plan_id is not None and (
        stream.plan_id not in state.historical_plan_ids
    ):
        raise ValueError("historical plan not registered")
    if ensure_utc(at) < state.updated_at:
        raise ValueError("transition predates current state")


def _page_identity(stream: ScanStreamState, page: PageManifest) -> None:
    if (
        page.bank_id,
        page.app_id,
        page.stream_id,
        page.plan_id,
        page.chain_epoch,
        page.context.fingerprint,
    ) != (
        stream.bank_id,
        stream.app_id,
        stream.stream_id,
        stream.plan_id,
        stream.chain_epoch,
        stream.context.fingerprint,
    ):
        raise ValueError("page does not belong to stream/context/epoch")


def commit_page(
    state: IngestionWatermarkState,
    stream: ScanStreamState,
    page: PageManifest,
    *,
    expected_revision: int,
    committed_at: datetime,
    manifest_ledger: LedgerReference,
    previous_page: PageManifest | None = None,
    existing_commit: PageManifest | None = None,
) -> PageTransition:
    """Commit completo; existing_commit proviene del ledger, no de un caché."""
    _check(state, stream, expected_revision, committed_at)
    _page_identity(stream, page)
    if page.fetched_at > ensure_utc(committed_at):
        raise ValueError("commit precedes fetch")
    if page.publication_status != PublicationStatus.PUBLISHED:
        raise ValueError("page publication not fully confirmed")
    if existing_commit is not None:
        _page_identity(stream, existing_commit)
        # Reintentar un commit debe ser idéntico; el replay es otro comando.
        if existing_commit != page:
            raise ValueError(
                "conflicting commit; use anchor replay for new fetch"
            )
        return PageTransition(state, stream, page, duplicate=True)
    if stream.status not in (ScanStatus.NOT_STARTED, ScanStatus.RUNNING):
        raise ValueError("stream must be started/resumed before committing")
    if stream.frontier_page_id is None:
        if (
            previous_page is not None
            or page.previous_page_id is not None
            or page.ordinal != 0
            or page.input_token is not None
        ):
            raise ValueError("new chain must start at head without cursor")
    else:
        if previous_page is None:
            raise ValueError("previous manifest required for continuity")
        _page_identity(stream, previous_page)
        if (
            previous_page.page_id != stream.frontier_page_id
            or page.previous_page_id != previous_page.page_id
            or page.ordinal != previous_page.ordinal + 1
            or page.page_id == previous_page.page_id
            or stream.frontier_ordinal != previous_page.ordinal
            or previous_page.output_token is None
            or page.input_token != stream.output_token
            or previous_page.output_token != stream.output_token
        ):
            raise ValueError("broken chain: cannot mix old and fresh pages")
    if (
        page.raw_count == 0
        or page.observed_min_at is None
        or (page.valid_count == 0 and page.output_token is None)
    ):
        raise ValueError("empty/ambiguous page cannot advance frontier")
    incremental = state.incremental
    if incremental.stream_id == stream.stream_id:
        if incremental.active_run_id != page.run_id:
            raise ValueError("incremental run mismatch")
        dates = [
            x
            for x in (
                incremental.candidate_high_at,
                incremental.baseline_high_at,
                page.observed_max_at,
            )
            if x is not None
        ]
        incremental = _replace(incremental, candidate_high_at=max(dates))
    lows = [
        x
        for x in (state.observed_min_at, page.observed_min_at)
        if x is not None
    ]
    highs = [
        x
        for x in (state.observed_max_at, page.observed_max_at)
        if x is not None
    ]
    updated = _replace(
        state,
        revision=state.revision + 1,
        updated_at=ensure_utc(committed_at),
        observed_min_at=min(lows),
        observed_max_at=max(highs),
        incremental=incremental,
        manifest_ledger=manifest_ledger,
    )
    updated_stream = _replace(
        stream,
        status=ScanStatus.RUNNING,
        frontier_page_id=page.page_id,
        frontier_oldest_at=page.observed_min_at,
        anchor_page_id=page.page_id,
        frontier_ordinal=page.ordinal,
        input_token=page.input_token,
        output_token=page.output_token,
        last_success_at=page.fetched_at,
        committed_pages=stream.committed_pages + 1,
        committed_reviews=stream.committed_reviews + page.valid_count,
    )
    return PageTransition(updated, updated_stream, page)


def change_stream_status(
    state: IngestionWatermarkState,
    stream: ScanStreamState,
    *,
    status: ScanStatus,
    expected_revision: int,
    at: datetime,
) -> tuple[IngestionWatermarkState, ScanStreamState]:
    """Pausa/recuperación; recuperar requiere replay validado."""
    _check(state, stream, expected_revision, at)
    allowed = {
        ScanStatus.NOT_STARTED: {ScanStatus.RUNNING, ScanStatus.PAUSED},
        ScanStatus.RUNNING: {ScanStatus.PAUSED, ScanStatus.RECOVERY_REQUIRED},
        ScanStatus.PAUSED: {ScanStatus.RUNNING, ScanStatus.RECOVERY_REQUIRED},
    }
    if status not in allowed.get(stream.status, set()):
        raise ValueError("invalid stream transition")
    updated_stream = _replace(
        stream,
        status=status,
        recovery_status=(
            RecoveryStatus.ANCHOR_REPLAY
            if status == ScanStatus.RECOVERY_REQUIRED
            else stream.recovery_status
        ),
    )
    incremental = state.incremental
    if incremental.stream_id == stream.stream_id:
        incremental = _replace(incremental, status=status)
    return _replace(
        state,
        revision=state.revision + 1,
        updated_at=ensure_utc(at),
        incremental=incremental,
    ), updated_stream


def replay_anchor(
    state: IngestionWatermarkState,
    stream: ScanStreamState,
    anchor: PageManifest,
    replay: PageManifest,
    *,
    expected_revision: int,
    at: datetime,
    manifest_ledger: LedgerReference,
) -> PageTransition:
    """Mismo contenido, nueva continuación. No cuenta la página dos veces."""
    _check(state, stream, expected_revision, at)
    _page_identity(stream, anchor)
    _page_identity(stream, replay)
    if stream.status not in (
        ScanStatus.RUNNING,
        ScanStatus.PAUSED,
        ScanStatus.RECOVERY_REQUIRED,
    ):
        raise ValueError("stream is not replayable")
    if (
        anchor.page_id != stream.frontier_page_id
        or replay.page_id != anchor.page_id
        or replay.ordinal != anchor.ordinal
        or replay.previous_page_id != anchor.previous_page_id
        or replay.input_token != anchor.input_token
        or replay.content_fingerprint != anchor.content_fingerprint
        or replay.ledger.content_fingerprint
        != anchor.ledger.content_fingerprint
        or replay.valid_count != anchor.valid_count
        or replay.raw_count != anchor.raw_count
        or replay.observed_min_at != anchor.observed_min_at
        or replay.observed_max_at != anchor.observed_max_at
        or replay.publication_status != PublicationStatus.PUBLISHED
        or anchor.publication_status != PublicationStatus.PUBLISHED
        or replay.manifest_version <= anchor.manifest_version
        or replay.fetched_at < anchor.fetched_at
        or replay.fetched_at > ensure_utc(at)
    ):
        raise ValueError("anchor changed: reconciliation required")
    if (
        stream.output_token != anchor.output_token
        or stream.frontier_ordinal != anchor.ordinal
    ):
        raise ValueError("anchor is not current frontier version")
    updated_stream = _replace(
        stream,
        status=ScanStatus.RUNNING,
        recovery_status=RecoveryStatus.NONE,
        output_token=replay.output_token,
        last_success_at=replay.fetched_at,
    )
    incremental = state.incremental
    if incremental.stream_id == stream.stream_id:
        incremental = _replace(incremental, status=ScanStatus.RUNNING)
    updated = _replace(
        state,
        revision=state.revision + 1,
        updated_at=ensure_utc(at),
        incremental=incremental,
        manifest_ledger=manifest_ledger,
    )
    return PageTransition(updated, updated_stream, replay, duplicate=True)


def extend_to_full(
    plan: HistoricalPlan,
    event: PlanExtensionEvent,
) -> HistoricalPlan:
    """Conserva plan/T0/streams; los efectos CAS pertenecen al repositorio."""
    for previous in plan.extension_events:
        if previous.event_id == event.event_id:
            if previous != event:
                raise ValueError("conflicting extension event")
            return plan
    if plan.requested_lower_at is None:
        raise ValueError("plan is already FULL")
    if event.previous_lower_at != plan.requested_lower_at:
        raise ValueError("extension does not match original cutoff")
    if plan.status == ScanStatus.SOURCE_EXHAUSTED_OBSERVED:
        status = plan.status
    else:
        status = ScanStatus.PAUSED
    return _replace(
        plan,
        requested_lower_at=None,
        status=status,
        extension_events=(*plan.extension_events, event),
    )


def begin_incremental(
    state: IngestionWatermarkState,
    stream: ScanStreamState,
    *,
    run_id: str,
    expected_revision: int,
    at: datetime,
) -> IngestionWatermarkState:
    _check(state, stream, expected_revision, at)
    if (
        stream.plan_id is not None
        or state.incremental.active_run_id is not None
        or stream.status != ScanStatus.NOT_STARTED
    ):
        raise ValueError("incremental already active or stream is historical")
    return _replace(
        state,
        revision=state.revision + 1,
        updated_at=ensure_utc(at),
        incremental=_replace(
            state.incremental,
            active_run_id=run_id,
            stream_id=stream.stream_id,
            baseline_high_at=state.incremental.committed_high_at,
            candidate_high_at=None,
            status=ScanStatus.RUNNING,
        ),
    )


def finish_incremental(
    state: IngestionWatermarkState,
    *,
    expected_revision: int,
    at: datetime,
    run_id: str,
    evidence: CompletionEvidence,
    frontier_ledger: LedgerReference,
) -> IngestionWatermarkState:
    """El repositorio verifica que el ledger cubra TODOS los IDs de frontera."""
    progress = state.incremental
    if (
        state.revision != expected_revision
        or progress.active_run_id != run_id
        or progress.status != ScanStatus.RUNNING
        or ensure_utc(at) < state.updated_at
        or evidence.checked_at > ensure_utc(at)
        or evidence.checked_at < state.updated_at
        or evidence.boundary_ledger != frontier_ledger
        or evidence.coverage != CoverageStatus.TRAVERSAL_OBSERVED
        or progress.candidate_high_at is None
        or frontier_ledger.entry_count == 0
    ):
        raise ValueError("incremental closure lacks verified frontier/run")
    return _replace(
        state,
        revision=state.revision + 1,
        updated_at=ensure_utc(at),
        incremental=_replace(
            progress,
            committed_high_at=progress.candidate_high_at,
            frontier_ledger=frontier_ledger,
            active_run_id=None,
            status=ScanStatus.PAUSED,
        ),
    )


def finish_historical_plan(
    plan: HistoricalPlan,
    streams: tuple[ScanStreamState, ...],
    evidence: CompletionEvidence,
) -> HistoricalPlan:
    """Cierre lógico; persistir con CAS y conservar las páginas."""
    if (
        not streams
        or {s.stream_id for s in streams} != set(plan.stream_ids)
        or len(streams) != len(plan.stream_ids)
        or evidence.coverage != CoverageStatus.TRAVERSAL_OBSERVED
    ):
        raise ValueError("closure requires all plan streams and evidence")
    for stream in streams:
        if (
            (stream.bank_id, stream.app_id, stream.plan_id)
            != (plan.bank_id, plan.app_id, plan.plan_id)
            or stream.frontier_page_id not in evidence.manifest_ids
            or stream.frontier_oldest_at is None
            or stream.last_success_at is None
            or stream.last_success_at > evidence.checked_at
            or stream.status
            not in (
                ScanStatus.RUNNING,
                ScanStatus.PAUSED,
                ScanStatus.TARGET_REACHED,
                ScanStatus.SOURCE_EXHAUSTED_OBSERVED,
            )
        ):
            raise ValueError("inconsistent historical stream evidence")
    if evidence.source_exhausted_observed and all(
        s.output_token is None for s in streams
    ):
        status = ScanStatus.SOURCE_EXHAUSTED_OBSERVED
    elif plan.requested_lower_at is not None and all(
        s.frontier_oldest_at is not None
        and s.frontier_oldest_at <= plan.requested_lower_at
        for s in streams
    ):
        status = ScanStatus.TARGET_REACHED
    else:
        raise ValueError("historical target not reached")
    return _replace(plan, status=status, completion_evidence=evidence)


def reanchor(
    state: IngestionWatermarkState,
    stream: ScanStreamState,
    anchor: PageManifest,
    replay: PageManifest,
    *,
    expected_revision: int,
    at: datetime,
    manifest_ledger: LedgerReference,
    recovery: RecoveryStatus,
) -> PageTransition:
    """Continúa desde la relectura de una página comprometida de la cadena.

    El replay ocupa la misma posición (ordinal, página previa y cursor de
    entrada). Con contenido idéntico conserva page_id y sube de versión; si el
    origen cambió es una observación nueva con otro page_id. La frontera vuelve
    a la posición del ancla y continúa con el cursor devuelto por el replay.
    """
    _check(state, stream, expected_revision, at)
    _page_identity(stream, anchor)
    _page_identity(stream, replay)
    if stream.status not in (
        ScanStatus.RUNNING,
        ScanStatus.PAUSED,
        ScanStatus.RECOVERY_REQUIRED,
    ):
        raise ValueError("stream is not replayable")
    if recovery not in (
        RecoveryStatus.ANCHOR_REPLAY,
        RecoveryStatus.EARLIER_ANCHOR,
    ):
        raise ValueError("reanchor requires an anchor recovery step")
    frontier = stream.frontier_ordinal
    if frontier is None or anchor.ordinal > frontier:
        raise ValueError("anchor is outside the current chain")
    if recovery == RecoveryStatus.ANCHOR_REPLAY and (
        anchor.page_id != stream.frontier_page_id
    ):
        raise ValueError("anchor replay must use the current frontier")
    if recovery == RecoveryStatus.EARLIER_ANCHOR and anchor.ordinal >= frontier:
        raise ValueError("earlier anchor must precede the frontier")
    if (
        replay.ordinal != anchor.ordinal
        or replay.previous_page_id != anchor.previous_page_id
        or replay.input_token != anchor.input_token
        or replay.publication_status != PublicationStatus.PUBLISHED
        or anchor.publication_status != PublicationStatus.PUBLISHED
        or replay.fetched_at < anchor.fetched_at
        or replay.fetched_at > ensure_utc(at)
    ):
        raise ValueError("replay does not occupy the anchor position")
    same_page = replay.page_id == anchor.page_id
    if same_page and (
        replay.content_fingerprint != anchor.content_fingerprint
        or replay.manifest_version <= anchor.manifest_version
    ):
        raise ValueError("same page replay must keep content, new version")
    if (
        replay.raw_count == 0
        or replay.observed_min_at is None
        or replay.observed_max_at is None
        or (replay.valid_count == 0 and replay.output_token is None)
    ):
        raise ValueError("empty/ambiguous replay cannot anchor a chain")
    incremental = state.incremental
    if incremental.stream_id == stream.stream_id:
        if incremental.active_run_id != replay.run_id:
            raise ValueError("incremental run mismatch")
        dates = [
            x
            for x in (
                incremental.candidate_high_at,
                incremental.baseline_high_at,
                replay.observed_max_at,
            )
            if x is not None
        ]
        incremental = _replace(
            incremental,
            candidate_high_at=max(dates),
            status=ScanStatus.RUNNING,
        )
    lows = [
        x
        for x in (state.observed_min_at, replay.observed_min_at)
        if x is not None
    ]
    highs = [
        x
        for x in (state.observed_max_at, replay.observed_max_at)
        if x is not None
    ]
    updated = _replace(
        state,
        revision=state.revision + 1,
        updated_at=ensure_utc(at),
        observed_min_at=min(lows),
        observed_max_at=max(highs),
        incremental=incremental,
        manifest_ledger=manifest_ledger,
    )
    updated_stream = _replace(
        stream,
        status=ScanStatus.RUNNING,
        recovery_status=RecoveryStatus.NONE,
        frontier_page_id=replay.page_id,
        frontier_oldest_at=replay.observed_min_at,
        anchor_page_id=replay.page_id,
        frontier_ordinal=replay.ordinal,
        input_token=replay.input_token,
        output_token=replay.output_token,
        last_success_at=replay.fetched_at,
        committed_pages=stream.committed_pages + (0 if same_page else 1),
        committed_reviews=stream.committed_reviews
        + (0 if same_page else replay.valid_count),
    )
    return PageTransition(updated, updated_stream, replay, duplicate=same_page)


def restart_chain(
    state: IngestionWatermarkState,
    stream: ScanStreamState,
    *,
    expected_revision: int,
    at: datetime,
) -> tuple[IngestionWatermarkState, ScanStreamState]:
    """Abre un chain_epoch nuevo desde la cabeza; no traslada cursores.

    Las páginas comprometidas permanecen; la nueva cadena se recorre completa
    y no se presenta como continuación de la anterior.
    """
    _check(state, stream, expected_revision, at)
    if stream.status not in (
        ScanStatus.RUNNING,
        ScanStatus.PAUSED,
        ScanStatus.RECOVERY_REQUIRED,
    ):
        raise ValueError("stream cannot restart from this status")
    if stream.frontier_page_id is None:
        raise ValueError("stream has no chain to restart")
    updated_stream = _replace(
        stream,
        chain_epoch=stream.chain_epoch + 1,
        status=ScanStatus.RUNNING,
        recovery_status=RecoveryStatus.HEAD_RESCAN,
        frontier_page_id=None,
        frontier_oldest_at=None,
        anchor_page_id=None,
        frontier_ordinal=None,
        input_token=None,
        output_token=None,
    )
    incremental = state.incremental
    if incremental.stream_id == stream.stream_id:
        incremental = _replace(incremental, status=ScanStatus.RUNNING)
    return _replace(
        state,
        revision=state.revision + 1,
        updated_at=ensure_utc(at),
        incremental=incremental,
    ), updated_stream


def close_stream(
    state: IngestionWatermarkState,
    stream: ScanStreamState,
    *,
    status: ScanStatus,
    expected_revision: int,
    at: datetime,
) -> tuple[IngestionWatermarkState, ScanStreamState]:
    """Objetivo alcanzado, EOF observado o bloqueo; conserva los cursores."""
    _check(state, stream, expected_revision, at)
    if stream.status not in (ScanStatus.RUNNING, ScanStatus.PAUSED):
        raise ValueError("only an active stream can be closed")
    if status not in (
        ScanStatus.TARGET_REACHED,
        ScanStatus.SOURCE_EXHAUSTED_OBSERVED,
        ScanStatus.BLOCKED,
    ):
        raise ValueError("invalid terminal stream status")
    if status != ScanStatus.BLOCKED and stream.frontier_page_id is None:
        raise ValueError("terminal stream requires a committed frontier")
    updated_stream = _replace(stream, status=status)
    return _replace(
        state, revision=state.revision + 1, updated_at=ensure_utc(at)
    ), updated_stream


def reopen_stream(
    state: IngestionWatermarkState,
    stream: ScanStreamState,
    *,
    expected_revision: int,
    at: datetime,
) -> tuple[IngestionWatermarkState, ScanStreamState]:
    """FULL tras anual: el ancla y cursores se conservan; se exige replay."""
    _check(state, stream, expected_revision, at)
    if stream.plan_id is None or stream.status != ScanStatus.TARGET_REACHED:
        raise ValueError("only a historical target can be reopened")
    return _replace(
        state, revision=state.revision + 1, updated_at=ensure_utc(at)
    ), _replace(stream, status=ScanStatus.PAUSED)


def change_plan_status(
    plan: HistoricalPlan, status: ScanStatus
) -> HistoricalPlan:
    """Estados operativos; el cierre usa finish_historical_plan."""
    allowed = {
        ScanStatus.NOT_STARTED: {ScanStatus.RUNNING},
        ScanStatus.PAUSED: {ScanStatus.RUNNING},
        ScanStatus.RUNNING: {
            ScanStatus.PAUSED,
            ScanStatus.RECOVERY_REQUIRED,
            ScanStatus.BLOCKED,
        },
        ScanStatus.RECOVERY_REQUIRED: {ScanStatus.RUNNING, ScanStatus.PAUSED},
        ScanStatus.BLOCKED: {ScanStatus.PAUSED},
    }
    if plan.status == status:
        return plan
    if status not in allowed.get(plan.status, set()):
        raise ValueError("invalid plan transition")
    return _replace(plan, status=status)
