"""Pruebas de transiciones con fuente mutable y fallos parciales."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import voc_common as vc

T0 = datetime(2026, 10, 14, tzinfo=UTC)
IDENTITY = dict(
    bank_id=vc.BankKey.BBVA, app_id=vc.PLAYSTORE_BANK_APPS[vc.BankKey.BBVA]
)
CURSOR = "opaque+/cursor"
NEW_CURSOR = "opaque-new-cursor"


def ref(count: int = 1, digest: str = "a") -> vc.LedgerReference:
    return vc.LedgerReference(
        uri="gs://state/index",
        generation=1,
        entry_count=count,
        content_fingerprint=digest * 64,
    )


def replace(model: Any, **changes: Any) -> Any:
    return type(model).model_validate({**model.model_dump(), **changes})


def setup(
    historical: bool = False,
) -> tuple[
    vc.IngestionWatermarkState,
    vc.ScanStreamState,
    vc.PageManifest,
]:
    ctx = vc.ScanContext(app_id=IDENTITY["app_id"], protocol_version="v1")
    root = vc.IngestionWatermarkState(
        **IDENTITY,
        updated_at=T0,
        stream_ids=("s",),
        historical_plan_ids=(("plan",) if historical else ()),
    )
    stream = vc.ScanStreamState(
        **IDENTITY,
        stream_id="s",
        context=ctx,
        plan_id="plan" if historical else None,
    )
    page = vc.PageManifest(
        **IDENTITY,
        page_id="p0",
        fetch_attempt_id="f0",
        run_id="run",
        stream_id="s",
        plan_id=stream.plan_id,
        chain_epoch=0,
        ordinal=0,
        context=ctx,
        fetched_at=T0,
        observed_min_at=T0 - timedelta(days=366),
        observed_max_at=T0,
        ledger=ref(199),
        raw_count=199,
        valid_count=199,
        discarded_count=0,
        published_count=199,
        publication_status=vc.PublicationStatus.PUBLISHED,
        content_fingerprint="a" * 64,
        backup_uri="gs://raw/raw_staging/p0",
        backup_generation=1,
        output_token=CURSOR,
    )
    return root, stream, page


def commit(
    root: vc.IngestionWatermarkState,
    stream: vc.ScanStreamState,
    page: vc.PageManifest,
    **kwargs: Any,
) -> vc.PageTransition:
    return vc.commit_page(
        root,
        stream,
        page,
        expected_revision=root.revision,
        committed_at=T0,
        manifest_ledger=ref(),
        **kwargs,
    )


def test_commit_is_atomic_pure_and_idempotent() -> None:
    root, stream, page = setup()
    result = commit(root, stream, page)
    assert root.revision == 0 and stream.committed_pages == 0
    assert result.stream.committed_reviews == 199
    assert result.state.observed_min_at == page.observed_min_at
    assert result.state.incremental.committed_high_at is None
    again = commit(result.state, result.stream, page, existing_commit=page)
    assert again.duplicate and again.state == result.state
    assert again.stream.committed_reviews == 199
    with pytest.raises(ValueError):
        commit(
            result.state,
            result.stream,
            replace(page, fetch_attempt_id="conflict"),
            existing_commit=page,
        )
    with pytest.raises(ValueError):
        commit(result.state, result.stream, page)


@pytest.mark.parametrize(
    "publication", [vc.PublicationStatus.PENDING, vc.PublicationStatus.PARTIAL]
)
def test_partial_publication_does_not_advance(publication: Any) -> None:
    root, stream, page = setup()
    pending = replace(
        page,
        publication_status=publication,
        published_count=0 if publication.value == "PENDING" else 5,
    )
    with pytest.raises(ValueError, match="not fully confirmed"):
        commit(root, stream, pending)
    assert root.observed_max_at is None and stream.output_token is None


def test_context_revision_and_sequence_guards() -> None:
    root, stream, page = setup()
    cases = [
        replace(page, context=replace(page.context, page_size=500)),
        replace(page, chain_epoch=1),
        replace(page, ordinal=1),
        replace(page, input_token=CURSOR),
        replace(page, fetched_at=T0 + timedelta(seconds=1)),
    ]
    for bad in cases:
        with pytest.raises(ValueError):
            commit(root, stream, bad)
    with pytest.raises(ValueError):
        vc.commit_page(
            root,
            stream,
            page,
            expected_revision=5,
            committed_at=T0,
            manifest_ledger=ref(),
        )
    for bad_root in (
        replace(root, stream_ids=()),
        replace(root, updated_at=T0 + timedelta(days=1)),
        replace(
            root,
            bank_id=vc.BankKey.NUBANK,
            app_id=vc.PLAYSTORE_BANK_APPS[vc.BankKey.NUBANK],
        ),
    ):
        with pytest.raises(ValueError):
            commit(bad_root, stream, page)
    histroot, histstream, histpage = setup(True)
    with pytest.raises(ValueError):
        commit(replace(histroot, historical_plan_ids=()), histstream, histpage)


def test_new_head_cannot_be_stitched_to_old_second_page() -> None:
    root, stream, first = setup()
    old = commit(root, stream, first)
    fresh = replace(
        first,
        page_id="fresh",
        fetch_attempt_id="fresh-fetch",
        output_token=NEW_CURSOR,
        content_fingerprint="b" * 64,
    )
    current = commit(root, stream, fresh)
    old_second = replace(
        first,
        page_id="p1",
        ordinal=1,
        previous_page_id=first.page_id,
        input_token=CURSOR,
        output_token=None,
    )
    with pytest.raises(ValueError, match="broken chain"):
        commit(current.state, current.stream, old_second, previous_page=fresh)
    with pytest.raises(ValueError):
        commit(old.state, old.stream, old_second)
    second = commit(old.state, old.stream, old_second, previous_page=first)
    assert second.stream.output_token is None  # explicit clearing, not EOF
    assert second.stream.status == vc.ScanStatus.RUNNING
    assert second.stream.committed_pages == 2
    assert root.coverage == vc.CoverageStatus.UNVERIFIED
    # Fuente mutable: conservar cabecera antigua o reconciliar sus IDs.
    old_head = tuple(range(199))
    old_page2 = tuple(range(199, 398))
    fresh_head = (-2, -1, *old_head[:-2])
    fresh_page2 = (*old_head[-2:], *old_page2[:-2])
    missing = set(old_head) - set(fresh_head) - set(old_page2)
    assert missing == {197, 198}
    assert missing <= set(fresh_page2)
    assert set(old_head) <= set(fresh_head) | set(fresh_page2)


def test_pause_recovery_and_same_content_new_token_replay() -> None:
    root, stream, page = setup()
    result = commit(root, stream, page)
    paused_root, paused = vc.change_stream_status(
        result.state,
        result.stream,
        status=vc.ScanStatus.PAUSED,
        expected_revision=1,
        at=T0,
    )
    with pytest.raises(ValueError):
        commit(paused_root, paused, page)
    recovery_root, recovery = vc.change_stream_status(
        paused_root,
        paused,
        status=vc.ScanStatus.RECOVERY_REQUIRED,
        expected_revision=2,
        at=T0,
    )
    with pytest.raises(ValueError):
        vc.change_stream_status(
            recovery_root,
            recovery,
            status=vc.ScanStatus.RUNNING,
            expected_revision=3,
            at=T0,
        )
    replay = replace(
        page, manifest_version=2, fetch_attempt_id="f1", output_token=NEW_CURSOR
    )
    replayed = vc.replay_anchor(
        recovery_root,
        recovery,
        page,
        replay,
        expected_revision=3,
        at=T0,
        manifest_ledger=ref(2),
    )
    assert replayed.duplicate and replayed.stream.committed_pages == 1
    assert replayed.stream.output_token == NEW_CURSOR
    assert replayed.stream.recovery_status == vc.RecoveryStatus.NONE
    assert replayed.manifest.fetch_attempt_id == "f1"
    assert replayed.state.manifest_ledger == ref(2)
    for bad in (
        replace(replay, content_fingerprint="c" * 64),
        replace(replay, ledger=ref(199, "b")),
        page,
    ):
        with pytest.raises(ValueError):
            vc.replay_anchor(
                result.state,
                result.stream,
                page,
                bad,
                expected_revision=1,
                at=T0,
                manifest_ledger=ref(2),
            )


def test_annual_page_is_preserved_and_full_extension_is_idempotent() -> None:
    root, stream, page = setup(True)
    result = commit(root, stream, page)
    plan = vc.HistoricalPlan(
        **IDENTITY,
        plan_id="plan",
        started_at=T0,
        upper_anchor_at=T0,
        requested_lower_at=T0 - timedelta(days=365),
        stream_ids=("s",),
    )
    evidence = vc.CompletionEvidence(
        checked_at=T0,
        coverage=vc.CoverageStatus.TRAVERSAL_OBSERVED,
        continuity_checked=True,
        manifest_ids=(page.page_id,),
    )
    complete = vc.finish_historical_plan(plan, (result.stream,), evidence)
    assert complete.status == vc.ScanStatus.TARGET_REACHED
    assert result.stream.committed_reviews == 199  # no cutoff truncation
    event = vc.PlanExtensionEvent(
        event_id="e", extended_at=T0, previous_lower_at=plan.requested_lower_at
    )
    full = vc.extend_to_full(complete, event)
    assert full.plan_id == plan.plan_id and full.started_at == T0
    assert full.stream_ids == plan.stream_ids
    assert full.requested_lower_at is None
    assert vc.extend_to_full(full, event) == full
    with pytest.raises(ValueError):
        vc.extend_to_full(
            full, replace(event, extended_at=T0 + timedelta(days=1))
        )
    with pytest.raises(ValueError):
        vc.extend_to_full(full, replace(event, event_id="another"))
    with pytest.raises(ValueError):
        vc.finish_historical_plan(full, (result.stream,), evidence)
    exhausted_stream = replace(result.stream, output_token=None)
    exhausted = vc.finish_historical_plan(
        full,
        (exhausted_stream,),
        replace(evidence, source_exhausted_observed=True),
    )
    assert exhausted.status == vc.ScanStatus.SOURCE_EXHAUSTED_OBSERVED
    with pytest.raises(ValueError):
        vc.finish_historical_plan(plan, (), evidence)


def test_incremental_baseline_and_large_frontier() -> None:
    root, stream, page = setup()
    baseline = T0 - timedelta(days=1)
    root = replace(
        root,
        incremental=vc.IncrementalProgress(
            committed_high_at=baseline,
            frontier_ledger=ref(1200),
        ),
    )
    started = vc.begin_incremental(
        root, stream, run_id="run", expected_revision=0, at=T0
    )
    result = commit(started, stream, page)
    assert result.state.incremental.baseline_high_at == baseline
    assert result.state.incremental.committed_high_at == baseline
    assert result.state.incremental.candidate_high_at == T0
    evidence = vc.CompletionEvidence(
        checked_at=T0,
        coverage=vc.CoverageStatus.TRAVERSAL_OBSERVED,
        continuity_checked=True,
        manifest_ids=(page.page_id,),
        boundary_ledger=ref(1500),
    )
    finished = vc.finish_incremental(
        result.state,
        expected_revision=2,
        at=T0,
        run_id="run",
        evidence=evidence,
        frontier_ledger=ref(1500),
    )
    assert finished.incremental.committed_high_at == T0
    assert finished.incremental.frontier_ledger == ref(1500)
    assert finished.incremental.active_run_id is None
    with pytest.raises(ValueError):
        vc.finish_incremental(
            result.state,
            expected_revision=0,
            at=T0,
            run_id="run",
            evidence=evidence,
            frontier_ledger=ref(1500),
        )
    with pytest.raises(ValueError):
        vc.begin_incremental(
            started, stream, run_id="other", expected_revision=1, at=T0
        )
    with pytest.raises(ValueError):
        commit(started, stream, replace(page, run_id="wrong"))


def test_empty_page_and_false_completion_do_not_advance() -> None:
    root, stream, page = setup(True)
    empty = replace(
        page,
        raw_count=0,
        valid_count=0,
        published_count=0,
        ledger=ref(0),
        observed_min_at=None,
        observed_max_at=None,
    )
    with pytest.raises(ValueError, match="empty/ambiguous"):
        commit(root, stream, empty)
    result = commit(root, stream, page)
    plan = vc.HistoricalPlan(
        **IDENTITY,
        plan_id="plan",
        started_at=T0,
        upper_anchor_at=T0,
        requested_lower_at=None,
        stream_ids=("s",),
    )
    evidence = vc.CompletionEvidence(
        checked_at=T0,
        coverage=vc.CoverageStatus.TRAVERSAL_OBSERVED,
        continuity_checked=True,
        manifest_ids=("wrong-page",),
    )
    with pytest.raises(ValueError):
        vc.finish_historical_plan(plan, (result.stream,), evidence)
    changed = replace(plan, requested_lower_at=T0 - timedelta(days=365))
    bad_event = vc.PlanExtensionEvent(
        event_id="e",
        extended_at=T0,
        previous_lower_at=T0 - timedelta(days=364),
    )
    with pytest.raises(ValueError):
        vc.extend_to_full(changed, bad_event)
    exhausted = vc.finish_historical_plan(
        plan,
        (replace(result.stream, output_token=None),),
        replace(
            evidence,
            manifest_ids=(page.page_id,),
            source_exhausted_observed=True,
        ),
    )
    # A finite plan already exhausted stays exhausted when extended.
    annual_exhausted = replace(
        exhausted, requested_lower_at=T0 - timedelta(days=365)
    )
    extended = vc.extend_to_full(
        annual_exhausted,
        replace(
            bad_event, previous_lower_at=annual_exhausted.requested_lower_at
        ),
    )
    assert extended.status == vc.ScanStatus.SOURCE_EXHAUSTED_OBSERVED


def test_incremental_recovery_resumes_without_moving_frozen_baseline() -> None:
    root, stream, page = setup()
    started = vc.begin_incremental(
        root, stream, run_id="run", expected_revision=0, at=T0
    )
    result = commit(started, stream, page)
    paused_root, paused = vc.change_stream_status(
        result.state,
        result.stream,
        status=vc.ScanStatus.PAUSED,
        expected_revision=2,
        at=T0,
    )
    assert paused_root.incremental.status == vc.ScanStatus.PAUSED
    resumed_root, resumed = vc.change_stream_status(
        paused_root,
        paused,
        status=vc.ScanStatus.RUNNING,
        expected_revision=3,
        at=T0,
    )
    replayed = vc.replay_anchor(
        resumed_root,
        resumed,
        page,
        replace(
            page,
            manifest_version=2,
            output_token=NEW_CURSOR,
            fetch_attempt_id="f2",
        ),
        expected_revision=4,
        at=T0,
        manifest_ledger=ref(2),
    )
    assert replayed.state.incremental.baseline_high_at is None
    assert replayed.state.incremental.status == vc.ScanStatus.RUNNING
    with pytest.raises(ValueError):
        vc.replay_anchor(
            replace(root, revision=2),
            stream,
            page,
            page,
            expected_revision=2,
            at=T0,
            manifest_ledger=ref(),
        )
    with pytest.raises(ValueError):
        vc.replay_anchor(
            result.state,
            replace(result.stream, frontier_ordinal=10),
            page,
            replace(page, manifest_version=2),
            expected_revision=2,
            at=T0,
            manifest_ledger=ref(),
        )
    with pytest.raises(ValueError):
        vc.begin_incremental(
            result.state,
            result.stream,
            run_id="new",
            expected_revision=2,
            at=T0,
        )
