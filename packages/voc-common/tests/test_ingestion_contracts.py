"""Aceptación feature 1.6: contratos, sin efectos GCS ni reducer."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import voc_common as vc
from pydantic import ValidationError

T0 = datetime(2026, 10, 14, 18, tzinfo=UTC)
APP = vc.PLAYSTORE_BANK_APPS[vc.BankKey.BBVA]
IDENTITY = {"bank_id": vc.BankKey.BBVA, "app_id": APP}
DIGEST = "a" * 64
OPAQUE_CURSOR = "not-base64!?+/="
FIRST_CURSOR = "fixture-first-cursor"
NEXT_CURSOR = "fixture-next-cursor"
OTHER_CURSOR = "fixture-other-cursor"


def ledger(count: int = 1200) -> vc.LedgerReference:
    return vc.LedgerReference(
        uri="gs://state/ledger/index.json",
        generation=1,
        entry_count=count,
        content_fingerprint=DIGEST,
    )


def context(**kwargs: Any) -> vc.ScanContext:
    return vc.ScanContext(app_id=APP, protocol_version="probe-v1", **kwargs)


def plan(**kwargs: Any) -> vc.HistoricalPlan:
    data = dict(
        **IDENTITY,
        plan_id="annual",
        started_at=T0,
        upper_anchor_at=T0,
        requested_lower_at=T0 - timedelta(days=365),
    )
    data.update(kwargs)
    return vc.HistoricalPlan(**data)


def page(**kwargs: Any) -> vc.PageManifest:
    data = dict(
        **IDENTITY,
        page_id="p1",
        fetch_attempt_id="fetch1",
        run_id="run",
        stream_id="stream",
        chain_epoch=0,
        ordinal=0,
        context=context(),
        fetched_at=T0,
        observed_min_at=T0 - timedelta(days=2),
        observed_max_at=T0 - timedelta(days=1),
        ledger=ledger(199),
        raw_count=200,
        valid_count=199,
        discarded_count=1,
        content_fingerprint=DIGEST,
        backup_uri="gs://raw/raw_staging/p1.gz",
        backup_generation=1,
    )
    data.update(kwargs)
    return vc.PageManifest(**data)


def evidence(**kwargs: Any) -> vc.CompletionEvidence:
    data = dict(
        checked_at=T0,
        coverage=vc.CoverageStatus.TRAVERSAL_OBSERVED,
        manifest_ids=("p1",),
        continuity_checked=True,
    )
    data.update(kwargs)
    return vc.CompletionEvidence(**data)


def test_public_models_roundtrip() -> None:
    models = [
        ledger(),
        context(),
        plan(),
        page(),
        evidence(),
        vc.IngestionWatermarkState(**IDENTITY),
        vc.IncrementalProgress(),
        vc.ScanStreamState(**IDENTITY, stream_id="s", context=context()),
        vc.PlanExtensionEvent(
            event_id="e",
            extended_at=T0,
            previous_lower_at=T0 - timedelta(days=365),
        ),
        vc.ProcessingReceipt(
            **IDENTITY,
            receipt_id="receipt",
            event_id=vc.compute_event_id(vc.BankKey.BBVA, "r", DIGEST),
            review_id="r",
            source_revision=DIGEST,
            page_id="p1",
            status=vc.ProcessingStatus.PENDING,
            processed_at=T0,
        ),
    ]
    for model in models:
        assert type(model).model_validate_json(model.model_dump_json()) == model
        assert json.loads(model.model_dump_json())["schema_version"] == 2
        with pytest.raises(ValidationError):
            type(model).model_validate(dict(model.model_dump(), typo=True))
        with pytest.raises(ValidationError):
            type(model).model_validate(
                dict(model.model_dump(), schema_version=3)
            )


@pytest.mark.parametrize(
    "change",
    [
        {"lang": "en"},
        {"country": "us"},
        {"sort_order": 1},
        {"star_filter": 1},
        {"device_filter": "tablet"},
        {"page_size": 500},
    ],
)
def test_context_fingerprint_changes_for_each_query_parameter(
    change: dict[str, Any],
) -> None:
    assert context().fingerprint != context(**change).fingerprint
    assert context().fingerprint == context().fingerprint
    with pytest.raises(ValidationError):
        context().page_size = 500


def test_context_protocol_app_and_opaque_tokens() -> None:
    ctx = context()
    for key in ("protocol_version", "app_id"):
        data = ctx.model_dump()
        data[key] += "-changed"
        assert vc.ScanContext(**data).fingerprint != ctx.fingerprint
    stream = vc.ScanStreamState(
        **IDENTITY,
        stream_id="s",
        context=ctx,
        status=vc.ScanStatus.PAUSED,
        input_token=OPAQUE_CURSOR,
    )
    assert stream.input_token == OPAQUE_CURSOR
    assert "not-base64" not in repr(stream)
    assert "fingerprint" not in ctx.model_dump()


def test_large_frontier_is_referenced_and_not_truncated() -> None:
    root = vc.IngestionWatermarkState(
        **IDENTITY,
        observed_min_at=T0 - timedelta(days=365),
        observed_max_at=T0,
        incremental=vc.IncrementalProgress(
            committed_high_at=T0,
            frontier_ledger=ledger(1200),
        ),
    )
    assert root.incremental.frontier_ledger is not None
    assert root.incremental.frontier_ledger.entry_count == 1200
    assert len(root.model_dump_json()) < 1000
    assert root.coverage == vc.CoverageStatus.UNVERIFIED
    assert root.historical_plan_ids == ()


def test_annual_and_full_share_plan_identity_without_moving_incremental() -> (
    None
):
    annual = plan(stream_ids=("s",))
    full = plan(
        stream_ids=("s",),
        requested_lower_at=None,
        extension_events=(
            vc.PlanExtensionEvent(
                event_id="extend",
                extended_at=T0 + timedelta(days=10),
                previous_lower_at=annual.requested_lower_at,
            ),
        ),
    )
    assert (full.plan_id, full.started_at, full.upper_anchor_at) == (
        annual.plan_id,
        annual.started_at,
        annual.upper_anchor_at,
    )
    assert full.requested_lower_at is None
    done = plan(
        stream_ids=("s",),
        status=vc.ScanStatus.TARGET_REACHED,
        completion_evidence=evidence(),
    )
    assert done.completion_evidence is not None
    exhausted = plan(
        stream_ids=("s",),
        requested_lower_at=None,
        status=vc.ScanStatus.SOURCE_EXHAUSTED_OBSERVED,
        completion_evidence=evidence(source_exhausted_observed=True),
    )
    assert exhausted.status != done.status


@pytest.mark.parametrize(
    "change",
    [
        {"app_id": "different"},
        {"upper_anchor_at": T0 + timedelta(days=1)},
        {"requested_lower_at": T0 - timedelta(days=364)},
        {"stream_ids": ("s", "s")},
        {"status": vc.ScanStatus.TARGET_REACHED},
        {
            "requested_lower_at": None,
            "stream_ids": ("s",),
            "status": vc.ScanStatus.TARGET_REACHED,
            "completion_evidence": evidence(),
        },
        {
            "stream_ids": ("s",),
            "status": vc.ScanStatus.SOURCE_EXHAUSTED_OBSERVED,
            "completion_evidence": evidence(),
        },
        {
            "extension_events": (
                vc.PlanExtensionEvent(
                    event_id="e",
                    extended_at=T0,
                    previous_lower_at=T0 - timedelta(days=365),
                ),
            )
        },
        {
            "requested_lower_at": None,
            "extension_events": (
                vc.PlanExtensionEvent(
                    event_id="e",
                    extended_at=T0,
                    previous_lower_at=T0 - timedelta(days=360),
                ),
            ),
        },
    ],
)
def test_reject_inconsistent_plans(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        plan(**change)


@pytest.mark.parametrize(
    "change",
    [
        {"committed_high_at": T0},
        {"frontier_ledger": ledger()},
        {"replay_from_at": T0},
        {"baseline_high_at": T0, "candidate_high_at": T0 - timedelta(days=1)},
        {"status": vc.ScanStatus.RUNNING},
    ],
)
def test_reject_inconsistent_incremental(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        vc.IncrementalProgress(**change)


def test_explicit_start_pause_and_eof_with_same_null_cursor() -> None:
    for status in (
        vc.ScanStatus.NOT_STARTED,
        vc.ScanStatus.PAUSED,
        vc.ScanStatus.SOURCE_EXHAUSTED_OBSERVED,
    ):
        stream = vc.ScanStreamState(
            **IDENTITY,
            context=context(),
            stream_id="s",
            status=status,
            last_success_at=(
                T0 if status != vc.ScanStatus.NOT_STARTED else None
            ),
        )
        assert stream.output_token is None
        assert stream.status == status
    running = vc.IncrementalProgress(
        status=vc.ScanStatus.RUNNING,
        active_run_id="run",
        stream_id="s",
    )
    assert running.committed_high_at is None


@pytest.mark.parametrize(
    "change",
    [
        {"context": vc.ScanContext(app_id="wrong", protocol_version="v1")},
        {"frontier_page_id": "p1"},
        {"input_token": "token"},
        {"status": vc.ScanStatus.SOURCE_EXHAUSTED_OBSERVED},
        {
            "status": vc.ScanStatus.SOURCE_EXHAUSTED_OBSERVED,
            "last_success_at": T0,
            "output_token": "token",
        },
    ],
)
def test_reject_inconsistent_stream(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        vc.ScanStreamState.model_validate(
            {**IDENTITY, "stream_id": "s", "context": context(), **change}
        )


@pytest.mark.parametrize(
    "change",
    [
        {"context": vc.ScanContext(app_id="wrong", protocol_version="v1")},
        {"raw_count": 199},
        {"ledger": ledger(10)},
        {"published_count": 200},
        {"published_count": 1},
        {"publication_status": vc.PublicationStatus.PUBLISHED},
        {"publication_status": vc.PublicationStatus.PARTIAL},
        {"observed_min_at": None},
        {"observed_min_at": T0},
        {"observed_min_at": None, "observed_max_at": None},
        {"backup_generation": 0},
        {"raw_count": -1},
    ],
)
def test_reject_inconsistent_pages(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        page(**change)


def test_page_versions_hide_tokens_and_separate_publication_from_tds() -> None:
    first = page(input_token=FIRST_CURSOR, output_token=NEXT_CURSOR)
    data = first.model_dump()
    data.update(
        manifest_version=2,
        output_token=OTHER_CURSOR,
        publication_status=vc.PublicationStatus.PUBLISHED,
        published_count=199,
    )
    published = vc.PageManifest(**data)
    assert published.page_id == first.page_id
    assert published.content_fingerprint == first.content_fingerprint
    assert published.sanitization_status == vc.SanitizationStatus.PENDING
    assert FIRST_CURSOR not in repr(first)
    with pytest.raises(ValidationError):
        first.output_token = OTHER_CURSOR
    assert (
        page(
            publication_status=vc.PublicationStatus.PARTIAL, published_count=50
        ).published_count
        == 50
    )


@pytest.mark.parametrize(
    "change",
    [
        {"observed_min_at": T0},
        {"observed_min_at": T0, "observed_max_at": T0 - timedelta(days=1)},
        {"historical_plan_ids": ("p", "p")},
        {"stream_ids": ("s", "s")},
        {"coverage": vc.CoverageStatus.TRAVERSAL_OBSERVED},
        {"incremental": vc.IncrementalProgress(stream_id="missing")},
    ],
)
def test_reject_inconsistent_root(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        vc.IngestionWatermarkState(**IDENTITY, **change)


def test_receipts_require_durable_tds_and_coded_failures() -> None:
    data = dict(
        **IDENTITY,
        receipt_id="receipt",
        event_id=vc.compute_event_id(vc.BankKey.BBVA, "r", DIGEST),
        review_id="r",
        source_revision=DIGEST,
        page_id="p",
        processed_at=T0,
    )
    for status in (
        vc.ProcessingStatus.TDS_COMMITTED,
        vc.ProcessingStatus.QUARANTINED,
        vc.ProcessingStatus.RETRYABLE_ERROR,
    ):
        with pytest.raises(ValidationError):
            vc.ProcessingReceipt(**data, status=status)
    receipt = vc.ProcessingReceipt(
        **data,
        status=vc.ProcessingStatus.TDS_COMMITTED,
        result_digest=DIGEST,
        bigquery_job_ids=("merge-job",),
    )
    assert receipt.result_digest == DIGEST
    filtered = vc.ProcessingReceipt(
        **data,
        status=vc.ProcessingStatus.FILTERED_LENGTH,
    )
    assert filtered.bigquery_job_ids == ()


def test_evidence_and_dates_are_validated_and_normalized() -> None:
    for changes in (
        {"continuity_checked": False},
        {"manifest_ids": ()},
        {"gaps_detected": True},
        {"coverage": vc.CoverageStatus.GAPS_DETECTED},
    ):
        with pytest.raises(ValidationError):
            evidence(**changes)
    with pytest.raises(ValidationError):
        vc.PlanExtensionEvent(
            event_id="e",
            extended_at=T0,
            previous_lower_at=T0 + timedelta(days=1),
        )
    root = vc.IngestionWatermarkState(
        **IDENTITY, updated_at="2026-10-14T12:00:00-06:00"
    )
    assert root.updated_at == T0
    assert (
        vc.IngestionWatermarkState(
            **IDENTITY,
            manifest_ledger=ledger(),
            coverage=vc.CoverageStatus.TRAVERSAL_OBSERVED,
        ).coverage
        == vc.CoverageStatus.TRAVERSAL_OBSERVED
    )
