"""Features 3.4–3.5: recorridos, recuperación, API y Job con fallos inyectados.

El origen simulado usa cursores por posición (la evidencia del experimento
mostró relecturas idénticas a +30 min) y emite un token distinto en cada
llamada. Nada de esto sale a internet.
"""

import asyncio
import copy
import json
from collections.abc import Coroutine
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed
from ingestion_worker import (
    PROTOCOL_VERSION,
    EmptyAmbiguousError,
    ExtractionRequest,
    ExtractionStatus,
    PageClassification,
    PlayStoreResilientExtractor,
    ProtocolError,
    RateLimitedError,
    RawReviewBatchPublisher,
    TransportError,
    WatermarkRepository,
    parse_batchexecute_response,
    select_user_agent,
)
from ingestion_worker.watermark_store import (
    IntegrityError,
    ObjectReference,
    StateConflict,
)
from voc_common import (
    DEFAULT_USER_AGENTS,
    PLAYSTORE_BANK_APPS,
    BankKey,
    IngestionExecutionConfig,
    IngestionMode,
    RecoveryStatus,
    RunAuditStatus,
    ScanStatus,
)

BANK = BankKey.BBVA
APP = PLAYSTORE_BANK_APPS[BANK]
T0 = datetime(2026, 10, 14, 12, tzinfo=UTC)
DAY = 86_400
T = TypeVar("T")


def run(coro: Coroutine[Any, Any, T]) -> T:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------- fake GCS
class FakeBlob:
    def __init__(self, bucket: "FakeBucket", name: str) -> None:
        self.bucket, self.name = bucket, name
        self._metadata: dict[str, str] | None = None
        self.generation: int | None = None

    @property
    def metadata(self):
        # Como google-cloud-storage 3.x: el getter devuelve una copia, así que
        # mutar `blob.metadata[k] = v` no persiste.
        return copy.deepcopy(self._metadata)

    @metadata.setter
    def metadata(self, value):
        self._metadata = copy.deepcopy(value)

    def _get(self, expected: int | None = None) -> dict[str, Any]:
        if self.name not in self.bucket.objects:
            raise NotFound("missing")
        record = self.bucket.objects[self.name]
        if expected is not None and record["generation"] != expected:
            raise PreconditionFailed("changed")
        return record

    def reload(self, *, if_generation_match=None, timeout=None) -> None:
        record = self._get(if_generation_match)
        self.generation = record["generation"]
        self.metadata = copy.deepcopy(record["metadata"])

    def download_as_bytes(self, *, if_generation_match=None, timeout=None):
        return self._get(if_generation_match)["data"]

    def upload_from_string(
        self, data, *, content_type, if_generation_match, timeout
    ) -> None:
        if self.bucket.before_upload:
            self.bucket.before_upload(self.name)
        record = self.bucket.objects.get(self.name)
        if (record["generation"] if record else 0) != if_generation_match:
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

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.counter = 0
        self.before_upload: Any = None

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)


class FakeStorage:
    def __init__(self) -> None:
        self.value = FakeBucket()

    def bucket(self, _: str) -> FakeBucket:
        return self.value


# --------------------------------------------------------- simulated source
@dataclass(frozen=True)
class Review:
    id: str
    ts: int
    score: int = 4
    text: str | None = "texto"
    votes: int = 0


def reviews(count: int, *, start: datetime, step: int, prefix: str = "r"):
    base = int(start.timestamp())
    return [
        Review(f"{prefix}{i}", base - i * step, score=1 + i % 5)
        for i in range(count)
    ]


def row(review: Review) -> list[Any]:
    return [
        review.id,
        ["user"],
        review.score,
        None,
        review.text,
        [review.ts],
        review.votes,
        None,
        None,
        None,
        "1.0",
        *[None] * 6,
    ]


class Source:
    """Cursor por posición (id/fecha); token nuevo en cada respuesta."""

    def __init__(self, items: list[Review]) -> None:
        self.items = list(items)
        self.tokens: dict[str, tuple[int, str]] = {}
        self.counter = 0
        self.calls: list[tuple[str | None, int | None]] = []
        self.errors: list[Exception | None] = []
        self.rejected: set[str] = set()
        self.reject_all = False
        self.shifted: set[str] = set()
        self.repeat = False
        self.on_fetch: Any = None

    def ordered(self, star: int | None) -> list[Review]:
        rows = [r for r in self.items if star is None or r.score == star]
        return sorted(rows, key=lambda r: (-r.ts, r.id))

    def edit(self, review_id: str, **changes: Any) -> None:
        self.items = [
            replace(r, **changes) if r.id == review_id else r
            for r in self.items
        ]

    async def fetch_page(self, bank, context, token=None):
        self.calls.append((token, context.star_filter))
        if self.on_fetch:
            self.on_fetch(len(self.calls))
        if self.errors:
            error = self.errors.pop(0)
            if error is not None:
                raise error
        if token is not None and (self.reject_all or token in self.rejected):
            raise TransportError("cursor rejected", 400)
        rows = self.ordered(context.star_filter)
        start = 0
        if token is not None:
            key = self.tokens[token]
            start = next(
                (i for i, r in enumerate(rows) if (-r.ts, r.id) > key),
                len(rows),
            )
            start += 1 if token in self.shifted else 0
        chunk = rows[start : start + context.page_size]
        next_token = None
        if start + len(chunk) < len(rows):
            if self.repeat and token is not None:
                next_token = token
            else:
                self.counter += 1
                next_token = f"tok-{self.counter}"
                last = chunk[-1]
                self.tokens[next_token] = (-last.ts, last.id)
        inner = [[row(r) for r in chunk], [None, next_token], None]
        body = json.dumps([["wrb.fr", "oCPfdb", json.dumps(inner)]]).encode()
        page = parse_batchexecute_response(
            body, bank_id=bank, app_id=PLAYSTORE_BANK_APPS[bank]
        )
        if page.classification == PageClassification.EMPTY_AMBIGUOUS:
            raise EmptyAmbiguousError(page)
        return page


# ------------------------------------------------------------------ harness
class Harness:
    def __init__(self, items: list[Review], **config: Any) -> None:
        self.storage = FakeStorage()
        self.bucket = self.storage.value
        self.now = [T0]
        self.mono = [0.0]
        self.repo = WatermarkRepository(
            self.storage, "test-bucket", clock=lambda: self.now[0]
        )
        self.pubsub = Mock()
        self.published: list[str] = []
        self.fail_publish = 0
        self.pubsub.publish.side_effect = self._publish
        self.publisher = RawReviewBatchPublisher(
            self.repo, self.pubsub, "projects/test/topics/raw"
        )
        self.source = Source(items)
        self.config = IngestionExecutionConfig(
            **(
                {
                    "scraper_page_size": 50,
                    "scraper_base_delay_sec": 0.0,
                    "scraper_max_jitter_sec": 0.0,
                }
                | config
            )
        )
        self.backlog = Mock()
        self.backlog.should_pause.return_value = False
        self.sleeps: list[float] = []

    def _publish(self, topic, data, **attrs):
        future = Mock()
        if self.fail_publish:
            self.fail_publish -= 1
            future.result.side_effect = TimeoutError("not confirmed")
        else:
            future.result.return_value = "message-id"
            self.published.append(attrs["event_id"])
        return future

    async def _sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        self.mono[0] += seconds
        self.now[0] += timedelta(seconds=seconds)

    def extractor(self, **kwargs: Any) -> PlayStoreResilientExtractor:
        return PlayStoreResilientExtractor(
            self.repo,
            self.publisher,
            self.source,  # type: ignore[arg-type]
            self.config,
            backlog=self.backlog,
            clock=lambda: self.now[0],
            monotonic=lambda: self.mono[0],
            sleep=self._sleep,
            **kwargs,
        )

    def run(self, mode=IngestionMode.INCREMENTAL, **kwargs: Any):
        self.advance(60)
        request = ExtractionRequest(bank_id=BANK, mode=mode, **kwargs)
        return run(self.extractor().run_extraction(request))

    def snapshot(self):
        return self.repo.load(BANK)

    def stream(self, stream_id: str):
        return self.repo.get_stream(self.snapshot(), stream_id)

    def plan(self, plan_id: str):
        return self.repo.get_plan(self.snapshot(), plan_id)

    def audits(self):
        # La cola enlazada se recorre desde el último evento.
        return list(reversed(list(self.repo.iter_audits(self.snapshot()))))


def ten_days(count: int = 300) -> list[Review]:
    # 300 reseñas cada ~48 min: unos 10 días hacia atrás desde T0.
    return reviews(count, start=T0, step=2_880)


# ------------------------------------------------------------- incremental
def test_bootstrap_confirms_only_an_explicit_recent_window():
    h = Harness(ten_days())
    result = h.run()
    assert result.status == ExtractionStatus.TARGET_REACHED
    assert result.reason == "bootstrap_window"
    state = h.snapshot().state
    assert state.incremental.active_run_id is None
    assert state.incremental.committed_high_at == T0
    assert result.committed_high_at == T0
    # 7 días a 48 min/reseña => 210 reseñas; páginas completas de 50.
    assert result.pages_committed == 5
    assert result.reviews_published == len(set(h.published)) == 250
    stream = h.stream(result.stream_ids[0])
    assert stream.status == ScanStatus.TARGET_REACHED
    assert stream.frontier_oldest_at <= T0 - timedelta(days=7)
    assert [a.status for a in h.audits()] == [
        RunAuditStatus.STARTED,
        RunAuditStatus.COMPLETED,
    ]
    assert result.audit_recorded
    assert result.requests == 5 and result.recovery_requests == 0


def test_incremental_stops_at_revisit_window_and_reconciles():
    h = Harness(ten_days())
    h.run()
    h.source.items = (
        reviews(20, start=T0 + timedelta(hours=10), step=1_800, prefix="n")
        + h.source.items
    )
    result = h.run()
    assert result.status == ExtractionStatus.TARGET_REACHED
    assert result.reason is None
    assert result.committed_high_at == T0 + timedelta(hours=10)
    # Ventana de 72 h bajo el high anterior: 20 nuevas + ~90 revisitadas.
    assert result.pages_committed == 3
    assert result.reconciliation_missing == 0
    # Una reseña que el origen deja de exponer se reporta, no se borra.
    h.source.items = [r for r in h.source.items if r.id != "n0"]
    third = h.run()
    assert third.status == ExtractionStatus.TARGET_REACHED
    assert third.reconciliation_missing == 1


def test_failure_after_page_one_keeps_confirmed_high_and_resumes_run():
    h = Harness(ten_days())
    h.run()
    high = h.snapshot().state.incremental.committed_high_at
    h.source.items = (
        reviews(120, start=T0 + timedelta(days=2), step=1_200, prefix="n")
        + h.source.items
    )
    base = len(h.source.calls)
    h.source.on_fetch = lambda n: setattr(
        h, "fail_publish", 1 if n == base + 2 else 0
    )
    first = h.run()
    assert first.status == ExtractionStatus.PUBLICATION_INCOMPLETE
    state = h.snapshot().state
    assert state.incremental.committed_high_at == high
    assert state.incremental.candidate_high_at == T0 + timedelta(days=2)
    assert h.snapshot().catalog.pending
    h.source.on_fetch = None
    second = h.run()
    assert second.run_id == first.run_id
    assert second.status == ExtractionStatus.TARGET_REACHED
    assert not h.snapshot().catalog.pending
    assert second.committed_high_at == T0 + timedelta(days=2)
    # La página 2 se entregó desde GCS antes de consultar el origen.
    assert second.recovery_actions[0].endswith("ANCHOR_REPLAY:OK")


def test_ties_beyond_500_and_unsorted_pages_close_with_full_ledger():
    tied = [Review(f"t{i:03d}", int(T0.timestamp())) for i in range(520)]
    older = reviews(60, start=T0 - timedelta(days=8), step=60, prefix="o")
    h = Harness(tied + older, scraper_page_size=199)
    result = h.run()
    assert result.status == ExtractionStatus.TARGET_REACHED
    ledger = h.snapshot().state.incremental.frontier_ledger
    assert ledger.entry_count == 580
    ids = {e["review_id"] for e in h.repo.iter_ledger(ledger)}
    assert {f"t{i:03d}" for i in range(520)} <= ids


def test_unsorted_dates_inside_page_are_processed_whole():
    items = ten_days(120)
    late = replace(items[10], ts=items[100].ts - 10)
    h = Harness(items[:10] + [late] + items[11:])
    result = h.run()
    # Cuatro días de origen: termina por EOF observado, no por la ventana.
    assert result.status == ExtractionStatus.SOURCE_EXHAUSTED_OBSERVED
    assert result.reviews_published == 120


# -------------------------------------------------------------- historical
def year_and_half() -> list[Review]:
    # ~550 días con una reseña cada 2 días.
    return reviews(275, start=T0, step=2 * DAY)


def test_annual_plan_keeps_crossing_page_then_full_reuses_anchor():
    h = Harness(year_and_half())
    annual = h.run(IngestionMode.BACKFILL)
    assert annual.status == ExtractionStatus.TARGET_REACHED
    plan = h.plan(annual.plan_id)
    assert plan.status == ScanStatus.TARGET_REACHED
    cutoff = plan.requested_lower_at
    stream = h.stream(plan.stream_ids[0])
    assert stream.status == ScanStatus.TARGET_REACHED
    # La página que cruza la cota se guarda completa, con filas más viejas.
    assert stream.frontier_oldest_at < cutoff
    older = [r for r in h.source.items if r.ts < cutoff.timestamp()]
    assert any(
        e in h.published
        for e in h.repo.iter_ledger(
            h.repo.find_page(
                h.snapshot(), stream.stream_id, stream.frontier_page_id
            ).ledger
        )
        for e in [e["event_id"]]
    )
    assert older
    calls_before = len(h.source.calls)
    full = h.run(IngestionMode.FULL_BACKFILL)
    assert full.status == ExtractionStatus.SOURCE_EXHAUSTED_OBSERVED
    assert full.plan_id == annual.plan_id
    plan = h.plan(annual.plan_id)
    assert plan.status == ScanStatus.SOURCE_EXHAUSTED_OBSERVED
    assert plan.started_at == T0 + timedelta(seconds=60)
    assert [e.event_id for e in plan.extension_events] == [
        f"full-{plan.plan_id}"
    ]
    # No se vuelve a recorrer el año: el primer request es el replay del ancla.
    full_calls = [token for token, _ in h.source.calls[calls_before:]]
    assert full_calls[0] is not None
    assert None not in full_calls
    assert f"{plan.stream_ids[0]}:EOF_CONFIRMED" in full.recovery_actions
    assert len(set(h.published)) == 275


def test_budget_pause_resumes_with_identical_anchor_replay():
    h = Harness(year_and_half(), ingestion_max_pages=2)
    first = h.run(IngestionMode.FULL_BACKFILL)
    assert first.status == ExtractionStatus.BUDGET_EXHAUSTED
    assert first.reason == "pages"
    plan = h.plan(first.plan_id)
    assert plan.status == ScanStatus.PAUSED
    stream = h.stream(plan.stream_ids[0])
    second = h.run(IngestionMode.FULL_BACKFILL)
    assert second.recovery_actions[0] == f"{stream.stream_id}:ANCHOR_REPLAY:OK"
    resumed = h.stream(stream.stream_id)
    assert resumed.frontier_ordinal == stream.frontier_ordinal + 2
    assert resumed.committed_pages == stream.committed_pages + 2


def test_changed_anchor_is_new_observation_and_continues():
    h = Harness(year_and_half(), ingestion_max_pages=2)
    first = h.run(IngestionMode.FULL_BACKFILL)
    stream = h.stream(h.plan(first.plan_id).stream_ids[0])
    page = h.repo.find_page(
        h.snapshot(), stream.stream_id, stream.frontier_page_id
    )
    edited = next(h.repo.iter_ledger(page.ledger))["review_id"]
    h.source.edit(edited, votes=99)
    second = h.run(IngestionMode.FULL_BACKFILL)
    assert second.recovery_actions[0].endswith("ANCHOR_REPLAY:OK")
    after = h.stream(stream.stream_id)
    # Nueva observación del ancla + dos páginas de presupuesto.
    assert after.committed_pages == stream.committed_pages + 3
    assert after.frontier_ordinal == stream.frontier_ordinal + 2
    replaced = h.repo.find_page(h.snapshot(), stream.stream_id, page.page_id)
    assert replaced == page  # La observación anterior se conserva.


def test_drifted_frontier_uses_earlier_anchor():
    h = Harness(year_and_half(), ingestion_max_pages=3)
    first = h.run(IngestionMode.FULL_BACKFILL)
    stream = h.stream(h.plan(first.plan_id).stream_ids[0])
    h.source.shifted.add(stream.input_token)
    second = h.run(IngestionMode.FULL_BACKFILL)
    sid = stream.stream_id
    assert second.recovery_actions[:2] == [
        f"{sid}:ANCHOR_REPLAY:DRIFT",
        f"{sid}:EARLIER_ANCHOR:OK",
    ]
    assert second.recovery_requests == 2
    assert h.stream(sid).chain_epoch == 0


def test_all_anchors_invalid_rescans_from_head_until_connected():
    h = Harness(
        year_and_half(),
        ingestion_max_pages=3,
        ingestion_recovery_max_anchors=1,
    )
    first = h.run(IngestionMode.FULL_BACKFILL)
    sid = h.plan(first.plan_id).stream_ids[0]
    h.source.rejected.update(h.source.tokens)
    h.config = IngestionExecutionConfig(
        **(h.config.model_dump() | {"ingestion_max_pages": 2})
    )
    second = h.run(IngestionMode.FULL_BACKFILL, star_filters=(None,))
    assert f"{sid}:HEAD_RESCAN" in second.recovery_actions
    assert h.stream(sid).chain_epoch == 1
    # Presupuesto agotado antes de reconectar: no se declara cobertura.
    assert second.status == ExtractionStatus.RECOVERY_REQUIRED
    assert second.reason == "head_rescan_open"
    assert h.plan(first.plan_id).status == ScanStatus.RECOVERY_REQUIRED
    h.config = IngestionExecutionConfig(
        **(h.config.model_dump() | {"ingestion_max_pages": 100})
    )
    third = h.run(IngestionMode.FULL_BACKFILL)
    assert third.status == ExtractionStatus.SOURCE_EXHAUSTED_OBSERVED


def test_head_rescan_reports_connection_within_run():
    h = Harness(
        year_and_half(),
        ingestion_max_pages=2,
        ingestion_recovery_max_anchors=0,
    )
    first = h.run(IngestionMode.FULL_BACKFILL)
    sid = h.plan(first.plan_id).stream_ids[0]
    h.source.rejected.update(h.source.tokens)
    h.config = IngestionExecutionConfig(
        **(h.config.model_dump() | {"ingestion_max_pages": 4})
    )
    second = h.run(IngestionMode.FULL_BACKFILL)
    assert f"{sid}:HEAD_RESCAN_CONNECTED" in second.recovery_actions
    assert second.status == ExtractionStatus.BUDGET_EXHAUSTED


def test_recovery_budget_marks_stream_recovery_required():
    h = Harness(
        year_and_half(),
        ingestion_max_pages=2,
        ingestion_max_recovery_requests=1,
    )
    first = h.run(IngestionMode.FULL_BACKFILL)
    sid = h.plan(first.plan_id).stream_ids[0]
    h.source.shifted.update(h.source.tokens)
    second = h.run(IngestionMode.FULL_BACKFILL)
    assert second.status == ExtractionStatus.RECOVERY_REQUIRED
    assert second.reason == "recovery_budget"
    assert h.stream(sid).status == ScanStatus.RECOVERY_REQUIRED
    assert second.recovery_requests == 1


def test_star_partitions_close_plan_per_stream_eof():
    items = reviews(100, start=T0, step=DAY)
    h = Harness(items, scraper_page_size=10)
    result = h.run(IngestionMode.FULL_BACKFILL, star_filters=(1, 2, 3, 4, 5))
    assert result.status == ExtractionStatus.SOURCE_EXHAUSTED_OBSERVED
    assert len(result.stream_ids) == 5
    for sid in result.stream_ids:
        assert h.stream(sid).status == ScanStatus.SOURCE_EXHAUSTED_OBSERVED
    stars = {star for _, star in h.source.calls}
    assert stars == {1, 2, 3, 4, 5}
    assert len(set(h.published)) == 100


def test_star_edit_moves_review_without_losing_new_revision():
    items = reviews(20, start=T0, step=DAY)
    h = Harness(items, scraper_page_size=10)
    h.run(IngestionMode.FULL_BACKFILL, star_filters=(1, 2))
    before = set(h.published)
    h.source.edit("r0", score=2, text="cambió")
    plan = h.run(IngestionMode.FULL_BACKFILL)
    assert plan.status == ExtractionStatus.SOURCE_EXHAUSTED_OBSERVED
    second = h.run(IngestionMode.FULL_BACKFILL, star_filters=(1, 2))
    assert second.plan_id != plan.plan_id
    assert set(h.published) - before  # La revisión nueva no se deduplica.


def test_repeated_cursor_is_not_treated_as_progress():
    h = Harness(year_and_half())
    h.source.repeat = True
    result = h.run(IngestionMode.FULL_BACKFILL)
    assert result.status == ExtractionStatus.RECOVERY_REQUIRED
    assert result.reason == "repeated_cursor"


def test_backfill_request_cannot_shrink_full_plan_and_unknown_plan():
    h = Harness(year_and_half(), ingestion_max_pages=1)
    full = h.run(IngestionMode.FULL_BACKFILL)
    result = h.run(IngestionMode.BACKFILL)
    assert (result.status, result.reason) == (
        ExtractionStatus.RECOVERY_REQUIRED,
        "plan_is_full",
    )
    unknown = h.run(IngestionMode.FULL_BACKFILL, plan_id="missing")
    assert unknown.reason == "unknown_plan"
    explicit = h.run(IngestionMode.FULL_BACKFILL, plan_id=full.plan_id)
    assert explicit.plan_id == full.plan_id


def test_completed_plan_is_reported_without_requests():
    h = Harness(reviews(20, start=T0, step=DAY), scraper_page_size=10)
    first = h.run(IngestionMode.FULL_BACKFILL)
    calls = len(h.source.calls)
    again = h.run(IngestionMode.FULL_BACKFILL, plan_id=first.plan_id)
    assert again.status == ExtractionStatus.SOURCE_EXHAUSTED_OBSERVED
    assert len(h.source.calls) == calls


def test_backlog_pauses_historical_but_not_incremental():
    h = Harness(year_and_half())
    h.backlog.should_pause.return_value = True
    result = h.run(IngestionMode.BACKFILL)
    assert result.status == ExtractionStatus.PAUSED_BACKLOG
    assert h.plan(result.plan_id).status == ScanStatus.PAUSED
    assert not h.source.calls
    incremental = h.run()
    assert incremental.status == ExtractionStatus.TARGET_REACHED


# ---------------------------------------------------------- budgets / HTTP
def test_soft_review_limit_processes_whole_page():
    h = Harness(year_and_half(), scraper_page_size=199)
    result = h.run(IngestionMode.FULL_BACKFILL, max_reviews=5)
    assert result.status == ExtractionStatus.BUDGET_EXHAUSTED
    assert result.reason == "reviews"
    assert result.reviews_published == 199


@pytest.mark.parametrize(
    ("config", "reason"),
    [
        (
            {"ingestion_max_requests": 2, "ingestion_max_recovery_requests": 1},
            "requests",
        ),
        ({"ingestion_max_response_bytes": 1}, "response_bytes"),
        ({"ingestion_max_runtime_sec": 100}, "runtime"),
    ],
)
def test_execution_budgets(config, reason):
    h = Harness(year_and_half(), **config)
    if reason == "runtime":
        h.source.on_fetch = lambda n: h.advance(40)
    result = h.run(IngestionMode.FULL_BACKFILL)
    assert (result.status, result.reason) == (
        ExtractionStatus.BUDGET_EXHAUSTED,
        reason,
    )
    assert result.pages_committed >= 1


def test_rate_limit_honours_retry_after_then_continues():
    h = Harness(reviews(60, start=T0, step=DAY))
    h.source.errors = [RateLimitedError(7.0), None]
    result = h.run(IngestionMode.FULL_BACKFILL)
    assert result.status == ExtractionStatus.SOURCE_EXHAUSTED_OBSERVED
    assert 7.0 in h.sleeps


@pytest.mark.parametrize(
    ("errors", "status", "reason"),
    [
        (
            [RateLimitedError(None)] * 3,
            ExtractionStatus.PARTIAL_RATE_LIMITED,
            "circuit_open",
        ),
        (
            [TransportError("busy", 503)] * 3,
            ExtractionStatus.PARTIAL_RATE_LIMITED,
            "circuit_open",
        ),
        (
            [RateLimitedError(3_600.0)],
            ExtractionStatus.PARTIAL_RATE_LIMITED,
            "retry_after_exceeds_backoff",
        ),
        (
            [TransportError("down", 500)] * 3,
            ExtractionStatus.TRANSPORT_ERROR,
            "circuit_open",
        ),
        (
            [TransportError("forbidden", 403)],
            ExtractionStatus.BLOCKED,
            "http_403",
        ),
        (
            [TransportError("gone", 404)],
            ExtractionStatus.TRANSPORT_ERROR,
            "http_404",
        ),
        (
            [ProtocolError("html")],
            ExtractionStatus.PROTOCOL_ERROR,
            "protocol_shape",
        ),
    ],
)
def test_http_failures_stop_without_false_progress(errors, status, reason):
    h = Harness(year_and_half())
    h.source.errors = list(errors)
    result = h.run(IngestionMode.FULL_BACKFILL)
    assert (result.status, result.reason) == (status, reason)
    assert result.pages_committed == 0
    assert [a.status for a in h.audits()][-1] in (
        RunAuditStatus.PAUSED,
        RunAuditStatus.FAILED,
    )


def test_retries_are_bounded_per_request():
    h = Harness(
        year_and_half(),
        scraper_max_retries=1,
        ingestion_circuit_breaker_threshold=5,
    )
    h.source.errors = [TransportError("down", 500)] * 2
    result = h.run(IngestionMode.FULL_BACKFILL)
    assert result.reason == "retries_exhausted"


def test_empty_ambiguous_page_is_protocol_error():
    h = Harness([])
    result = h.run(IngestionMode.FULL_BACKFILL)
    assert (result.status, result.reason) == (
        ExtractionStatus.PROTOCOL_ERROR,
        "empty_ambiguous",
    )


def test_pacing_and_heartbeat_keep_lease_during_long_runs():
    h = Harness(
        year_and_half(),
        scraper_base_delay_sec=40.0,
        ingestion_max_pages=4,
    )
    result = h.run(IngestionMode.FULL_BACKFILL)
    assert result.status == ExtractionStatus.BUDGET_EXHAUSTED
    assert sum(h.sleeps) == pytest.approx(120.0)
    assert result.audit_recorded


def test_cursor_rejected_mid_run_triggers_recovery():
    h = Harness(year_and_half(), ingestion_max_pages=3)
    h.source.on_fetch = lambda n: (
        h.source.rejected.update(h.source.tokens) if n == 2 else None
    )
    result = h.run(IngestionMode.FULL_BACKFILL)
    sid = result.stream_ids[0]
    assert result.recovery_actions[:2] == [
        f"{sid}:CURSOR_REJECTED",
        f"{sid}:ANCHOR_REPLAY:OK",
    ]
    assert result.status == ExtractionStatus.BUDGET_EXHAUSTED


# ----------------------------------------------------- leases / durability
def test_active_lease_blocks_second_worker_without_requests():
    h = Harness(ten_days())
    h.repo.acquire_lease(BANK, "other-run")
    result = h.run()
    assert result.status == ExtractionStatus.LEASE_CONFLICT
    assert not h.source.calls and not h.published


def test_lease_lost_mid_run_stops_before_commit():
    h = Harness(ten_days())

    def takeover(n):
        if n == 2:
            h.advance(500)
            h.repo.acquire_lease(BANK, "other-run")

    h.source.on_fetch = takeover
    result = h.run()
    assert result.status == ExtractionStatus.LEASE_CONFLICT
    assert result.pages_committed == 1
    assert h.snapshot().lease.owner_run_id == "other-run"


def test_cas_conflict_stops_as_state_conflict():
    h = Harness(ten_days())

    def race(name):
        if name.startswith("state/watermarks") and len(h.source.calls) == 2:
            h.bucket.before_upload = None
            record = h.bucket.objects[name]
            record["generation"] += 1000
            h.bucket.counter += 1000

    h.source.on_fetch = lambda n: setattr(
        h.bucket, "before_upload", race if n == 2 else None
    )
    result = h.run()
    assert (result.status, result.reason) == (
        ExtractionStatus.LEASE_CONFLICT,
        "state_conflict",
    )


def test_expired_staging_is_abandoned_and_refetched():
    h = Harness(ten_days())
    h.source.on_fetch = lambda n: setattr(
        h, "fail_publish", 50 if n == 1 else 0
    )
    first = h.run()
    assert first.status == ExtractionStatus.PUBLICATION_INCOMPLETE
    for name in [n for n in h.bucket.objects if n.startswith("raw_staging/")]:
        del h.bucket.objects[name]
    h.source.on_fetch = None
    second = h.run()
    assert len(second.abandoned_captures) == 1
    assert second.status == ExtractionStatus.TARGET_REACHED
    assert not h.snapshot().catalog.pending


def test_pending_from_other_run_is_drained_first():
    h = Harness(year_and_half(), ingestion_max_pages=2)
    h.source.on_fetch = lambda n: setattr(
        h, "fail_publish", 50 if n == 2 else 0
    )
    first = h.run(IngestionMode.FULL_BACKFILL)
    assert first.status == ExtractionStatus.PUBLICATION_INCOMPLETE
    h.source.on_fetch = None
    calls = len(h.source.calls)
    second = h.run(IngestionMode.FULL_BACKFILL)
    assert second.run_id != first.run_id
    assert not h.snapshot().catalog.pending
    assert second.pages_committed >= 2
    assert len(h.source.calls) > calls


def test_pending_from_many_runs_requires_recovery(monkeypatch):
    h = Harness(ten_days())
    snapshot = h.snapshot()
    capture = Mock()
    monkeypatch.setattr(
        type(snapshot.catalog),
        "pending",
        property(lambda self: {"a": capture, "b": capture}),
        raising=False,
    )
    manifests = iter([Mock(run_id="one"), Mock(run_id="two")])
    monkeypatch.setattr(h.repo, "get_manifest", lambda ref: next(manifests))
    result = h.run()
    assert (result.status, result.reason) == (
        ExtractionStatus.RECOVERY_REQUIRED,
        "pending_from_many_runs",
    )


def test_audit_failure_never_upgrades_result(monkeypatch):
    h = Harness(ten_days())

    def broken(handle, event):
        raise StateConflict("audit table write lost")

    monkeypatch.setattr(h.repo, "record_audit", broken)
    result = h.run()
    assert result.status == ExtractionStatus.TARGET_REACHED
    assert not result.audit_recorded


# ------------------------------------------------------------- small units
def test_requests_validate_partitions_and_limits():
    with pytest.raises(ValueError):
        ExtractionRequest(
            bank_id=BANK, mode=IngestionMode.BACKFILL, star_filters=()
        )
    with pytest.raises(ValueError):
        ExtractionRequest(
            bank_id=BANK, mode=IngestionMode.BACKFILL, star_filters=(1, 1)
        )
    with pytest.raises(ValueError):
        ExtractionRequest(
            bank_id=BANK, mode=IngestionMode.BACKFILL, star_filters=(6,)
        )
    with pytest.raises(ValueError):
        ExtractionRequest(
            bank_id=BANK, mode=IngestionMode.BACKFILL, max_reviews=0
        )


def test_publisher_must_share_repository():
    h = Harness([])
    other = WatermarkRepository(FakeStorage(), "test-bucket")
    with pytest.raises(ValueError):
        PlayStoreResilientExtractor(
            other,
            h.publisher,
            h.source,
            h.config,  # type: ignore[arg-type]
        )


def test_user_agent_rotation_is_optional_and_stable():
    config = IngestionExecutionConfig()
    assert select_user_agent("run", config) is None
    rotating = IngestionExecutionConfig(scraper_rotate_user_agent=True)
    agent = select_user_agent("run", rotating)
    assert agent in DEFAULT_USER_AGENTS
    assert select_user_agent("run", rotating) == agent
    assert PROTOCOL_VERSION


# ------------------------------------------------------ replay edge cases
def test_changed_replay_partially_published_is_drained_as_replacement():
    h = Harness(year_and_half(), ingestion_max_pages=2)
    first = h.run(IngestionMode.FULL_BACKFILL)
    sid = h.plan(first.plan_id).stream_ids[0]
    stream = h.stream(sid)
    page = h.repo.find_page(h.snapshot(), sid, stream.frontier_page_id)
    edited = next(h.repo.iter_ledger(page.ledger))["review_id"]
    h.source.edit(edited, votes=7)
    h.fail_publish = 1
    second = h.run(IngestionMode.FULL_BACKFILL)
    assert (second.status, second.reason) == (
        ExtractionStatus.PUBLICATION_INCOMPLETE,
        "replay_publication",
    )
    capture = next(iter(h.snapshot().catalog.pending.values()))
    assert capture.replaces is not None
    assert h.stream(sid).frontier_page_id == page.page_id
    third = h.run(IngestionMode.FULL_BACKFILL)
    assert not h.snapshot().catalog.pending
    resumed = h.stream(sid)
    assert resumed.frontier_ordinal >= page.ordinal
    assert third.status == ExtractionStatus.BUDGET_EXHAUSTED


def test_unconfirmed_eof_falls_back_to_recovery_ladder():
    h = Harness(reviews(60, start=T0, step=DAY))
    base = len(h.source.calls)

    def drift(n):
        if n == base + 3:
            h.source.items = [r for r in h.source.items if r.id != "r55"]

    h.source.on_fetch = drift
    result = h.run(IngestionMode.FULL_BACKFILL)
    sid = result.stream_ids[0]
    assert result.status == ExtractionStatus.SOURCE_EXHAUSTED_OBSERVED
    assert result.recovery_actions[:3] == [
        f"{sid}:ANCHOR_REPLAY:DRIFT",
        f"{sid}:ANCHOR_REPLAY:DRIFT",
        f"{sid}:EARLIER_ANCHOR:OK",
    ]
    assert result.recovery_actions[-1] == f"{sid}:EOF_CONFIRMED"


def test_partition_eof_before_annual_cut_is_not_certified():
    recent = [
        Review(f"a{i}", int(T0.timestamp()) - i * DAY, 1) for i in range(5)
    ]
    old = [
        Review(f"b{i}", int(T0.timestamp()) - i * 4 * DAY, 2)
        for i in range(120)
    ]
    h = Harness(recent + old, scraper_page_size=20)
    result = h.run(IngestionMode.BACKFILL, star_filters=(1, 2))
    assert (result.status, result.reason) == (
        ExtractionStatus.RECOVERY_REQUIRED,
        "plan_mixed_terminal",
    )
    plan = h.plan(result.plan_id)
    assert plan.status == ScanStatus.PAUSED
    statuses = {h.stream(s).status for s in plan.stream_ids}
    assert statuses == {
        ScanStatus.SOURCE_EXHAUSTED_OBSERVED,
        ScanStatus.TARGET_REACHED,
    }


def test_repository_replay_guards():
    h = Harness(year_and_half(), ingestion_max_pages=2)
    first = h.run(IngestionMode.FULL_BACKFILL)
    sid = h.plan(first.plan_id).stream_ids[0]
    snapshot = h.snapshot()
    stream = h.repo.get_stream(snapshot, sid)
    anchor = h.repo.find_page(snapshot, sid, stream.frontier_page_id)
    handle = h.repo.acquire_lease(BANK, "guard-run")
    replay = type(anchor).model_validate(
        anchor.model_dump() | {"manifest_version": 2, "run_id": "guard-run"}
    )
    revision = snapshot.state.revision
    with pytest.raises(StateConflict):
        h.repo.reanchor_page(
            handle,
            anchor,
            replay,
            recovery=RecoveryStatus.ANCHOR_REPLAY,
            expected_revision=revision - 1,
        )
    with pytest.raises(ValueError, match="run differs"):
        h.repo.reanchor_page(
            handle,
            anchor,
            anchor,
            recovery=RecoveryStatus.ANCHOR_REPLAY,
            expected_revision=revision,
        )
    stale = type(anchor).model_validate(
        anchor.model_dump() | {"fetch_attempt_id": "other"}
    )
    with pytest.raises(IntegrityError, match="committed version"):
        h.repo.reanchor_page(
            handle,
            stale,
            replay,
            recovery=RecoveryStatus.ANCHOR_REPLAY,
            expected_revision=revision,
        )
    backup = ObjectReference(
        uri=anchor.backup_uri,
        generation=anchor.backup_generation,
        content_fingerprint="0" * 64,
    )
    with pytest.raises(ValueError, match="anchor and recovery"):
        h.repo.stage_page(
            handle, replay, backup, IngestionMode.FULL_BACKFILL, replaces=anchor
        )
    with pytest.raises(IntegrityError, match="not committed"):
        h.repo.stage_page(
            handle,
            replay,
            backup,
            IngestionMode.FULL_BACKFILL,
            replaces=stale,
            recovery=RecoveryStatus.ANCHOR_REPLAY,
        )
    assert h.repo.abandon_pending(handle, "missing").state.revision == revision


# ===================================================================
# Feature 3.5: API, Job histórico y cableado de runtime.
# ===================================================================
JOB = "projects/test/locations/us-central1/jobs/voc-ingestion-history-job"


class FakeHttp:
    """Sustituye httpx.AsyncClient; registra opciones (proxy, redirects)."""

    created: list[dict[str, Any]] = []

    def __init__(self, **options: Any) -> None:
        FakeHttp.created.append(options)

    async def __aenter__(self) -> "FakeHttp":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None


def service(h: Harness, **settings: Any):
    from ingestion_worker.runtime import IngestionRuntime
    from voc_common import Settings

    values = {
        "ingestion_v2_enabled": True,
        "ingestion_history_job_name": JOB,
        "gcp_project_id": "test",
    } | {
        key: getattr(h.config, key)
        for key in IngestionExecutionConfig.model_fields
    }
    launcher = Mock()
    launcher.launch.return_value = {
        "operation": "projects/test/locations/us-central1/operations/op",
        "execution": f"{JOB}/executions/e1",
    }
    writer = Mock()
    writer.flush.return_value = 1
    return IngestionRuntime(
        settings=Settings(_env_file=None, **(values | settings)),
        repository=h.repo,
        publisher=h.publisher,
        audit_writer=writer,
        launcher=launcher,
        backlog=h.backlog,
        http_factory=FakeHttp,
        client_factory=lambda http, config, agent: h.source,
        extractor_options={
            "clock": lambda: h.now[0],
            "monotonic": lambda: h.mono[0],
            "sleep": h._sleep,
        },
        sleep=h._sleep,
        monotonic=lambda: h.mono[0],
    )


def call(app, method: str, url: str, body: Any = None):
    import httpx

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(method, url, json=body)

    return run(request())


def api(h: Harness, **settings: Any):
    from ingestion_worker.main import create_app

    rt = service(h, **settings)
    return create_app(runtime=rt), rt


def test_health_and_incremental_endpoint():
    h = Harness(ten_days())
    app, rt = api(h)
    assert call(app, "GET", "/health").json() == {"status": "ok"}
    h.advance(60)
    response = call(
        app,
        "POST",
        "/api/v1/ingest",
        {"bank_id": "BBVA", "page_size": 50, "max_reviews_per_run": 5000},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "TARGET_REACHED"
    assert body["committed_high_at"].startswith("2026-10-14T12:00")
    assert "tok-" not in response.text and "gs://" not in response.text
    rt.audit_writer.flush.assert_called_once_with(h.repo, BANK)
    assert FakeHttp.created[-1] == {"follow_redirects": False}
    progress = call(app, "GET", "/api/v1/watermarks/BBVA").json()
    assert progress["committed_high_at"] is not None


def test_ingest_rejects_changed_page_size_and_reports_lease_conflict():
    h = Harness(ten_days())
    app, _ = api(h)
    changed = call(app, "POST", "/api/v1/ingest", {"bank_id": "BBVA"})
    assert changed.status_code == 422
    h.repo.acquire_lease(BANK, "other-run")
    busy = call(
        app, "POST", "/api/v1/ingest", {"bank_id": "BBVA", "page_size": 50}
    )
    assert busy.status_code == 409
    assert busy.json()["status"] == "LEASE_CONFLICT"
    assert not h.source.calls


def test_historical_request_persists_plan_and_launches_job():
    h = Harness(year_and_half())
    app, rt = api(h)
    h.advance(60)
    body = {"bank_id": "BBVA", "mode": "BACKFILL", "page_size": 50}
    response = call(app, "POST", "/api/v1/ingest", body)
    assert response.status_code == 202
    launched = response.json()
    plan_id = launched["plan_id"]
    assert launched["launched"] is True
    assert launched["execution"].endswith("/executions/e1")
    rt.launcher.launch.assert_called_once_with(BANK, plan_id, None)
    plan = h.plan(plan_id)
    assert plan.status == ScanStatus.NOT_STARTED
    assert not h.source.calls  # La API nunca recorre el histórico.
    again = call(app, "POST", "/api/v1/ingest", body).json()
    assert again["plan_id"] == plan_id
    full = call(
        app, "POST", "/api/v1/ingest", body | {"mode": "FULL_BACKFILL"}
    ).json()
    assert full["plan_id"] == plan_id
    assert full["requested_lower_at"] is None
    assert len(h.plan(plan_id).extension_events) == 1
    shrink = call(app, "POST", "/api/v1/ingest", body)
    assert shrink.status_code == 409
    stars = call(
        app, "POST", "/api/v1/ingest", body | {"partition_by_stars": True}
    )
    assert stars.status_code == 422


def test_historical_launch_failures_and_configuration():
    from ingestion_worker.runtime import LaunchError

    h = Harness(reviews(20, start=T0, step=DAY), scraper_page_size=10)
    app, rt = api(h, scraper_page_size=10)
    body = {"bank_id": "BBVA", "mode": "FULL_BACKFILL", "page_size": 10}
    rt.launcher.launch.side_effect = LaunchError("rejected")
    assert call(app, "POST", "/api/v1/ingest", body).status_code == 502
    h.repo.acquire_lease(BANK, "job-run")
    assert call(app, "POST", "/api/v1/ingest", body).status_code == 409
    h.advance(600)
    finished = h.run(IngestionMode.FULL_BACKFILL)
    assert finished.status == ExtractionStatus.SOURCE_EXHAUSTED_OBSERVED
    # Un plan cerrado no se reabre: una nueva solicitud crea otro plan.
    rt.launcher.launch.side_effect = None
    fresh = call(app, "POST", "/api/v1/ingest", body)
    assert fresh.status_code == 202
    assert fresh.json()["plan_id"] != finished.plan_id
    unconfigured, _ = api(h, ingestion_history_job_name=None)
    assert call(unconfigured, "POST", "/api/v1/ingest", body).status_code == 503


def test_sequential_endpoint_shares_budget_and_rejects_historical():
    h = Harness(ten_days())
    app, _ = api(h)
    historical = call(app, "POST", "/api/v1/ingest/all", {"mode": "BACKFILL"})
    assert historical.status_code == 422
    response = call(
        app,
        "POST",
        "/api/v1/ingest/all",
        {
            "banks": ["BBVA", "NUBANK", "BBVA"],
            "max_reviews_per_bank": 1000,
            "inter_bank_delay_sec": 5,
        },
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert [r["bank_id"] for r in results] == ["BBVA", "NUBANK"]
    assert results[0]["status"] == "TARGET_REACHED"
    assert 5 in h.sleeps
    h.source.on_fetch = lambda n: h.advance(10_000)
    starved = call(
        app,
        "POST",
        "/api/v1/ingest/all",
        {"banks": ["BBVA", "NUBANK"], "inter_bank_delay_sec": 1},
    ).json()["results"]
    assert starved[-1] == {"bank_id": "NUBANK", "status": "SKIPPED_BUDGET"}


def test_runtime_unavailable_when_v2_disabled(monkeypatch):
    from ingestion_worker import main
    from voc_common import Settings

    monkeypatch.setattr(main, "Settings", lambda: Settings(_env_file=None))
    main._runtime.cache_clear()
    try:
        app = main.create_app()
        response = call(app, "POST", "/api/v1/ingest", {"bank_id": "BBVA"})
        assert response.status_code == 503
    finally:
        main._runtime.cache_clear()


# ------------------------------------------------------------------- job
def prepared_plan(h: Harness, mode=IngestionMode.FULL_BACKFILL, **kwargs):
    rt = service(h)

    async def prepare():
        async with rt.extractor() as extractor:
            return await extractor.prepare_plan(
                ExtractionRequest(bank_id=BANK, mode=mode, **kwargs)
            )

    h.advance(60)
    return rt, run(prepare())


def test_job_continues_persisted_plan_until_budget_then_completes(capsys):
    from ingestion_worker.job import EX_OK, run_job

    h = Harness(year_and_half(), ingestion_max_pages=3)
    rt, plan = prepared_plan(h)
    assert plan.requested_lower_at is None
    assert run(run_job(rt, BANK, plan.plan_id)) == EX_OK
    assert h.plan(plan.plan_id).status == ScanStatus.PAUSED
    log = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert log["status"] == "BUDGET_EXHAUSTED"
    assert "tok-" not in json.dumps(log)
    rt = service(h, ingestion_max_pages=100)
    assert run(run_job(rt, BANK, plan.plan_id)) == EX_OK
    assert h.plan(plan.plan_id).status == ScanStatus.SOURCE_EXHAUSTED_OBSERVED
    rt.audit_writer.flush.assert_called_with(h.repo, BANK)


def test_job_never_creates_plans_and_selects_streams():
    from ingestion_worker.job import EX_FAILED, EX_OK, EX_USAGE, run_job

    h = Harness(reviews(40, start=T0, step=DAY), scraper_page_size=10)
    rt = service(h)
    assert run(run_job(rt, BANK, "missing-plan")) == EX_USAGE
    assert not h.snapshot().state.historical_plan_ids
    rt, plan = prepared_plan(h, star_filters=(1, 2))
    first, second = plan.stream_ids
    assert run(run_job(rt, BANK, plan.plan_id, first)) == EX_OK
    assert h.plan(plan.plan_id).status == ScanStatus.PAUSED
    assert {star for _, star in h.source.calls} == {1}
    assert run(run_job(rt, BANK, plan.plan_id, second)) == EX_OK
    assert h.plan(plan.plan_id).status == ScanStatus.SOURCE_EXHAUSTED_OBSERVED
    assert run(run_job(rt, BANK, plan.plan_id, "other")) == EX_FAILED


def test_job_annual_plan_uses_backfill_mode():
    from ingestion_worker.job import EX_OK, run_job

    h = Harness(year_and_half())
    rt, plan = prepared_plan(h, mode=IngestionMode.BACKFILL)
    assert plan.requested_lower_at is not None
    assert run(run_job(rt, BANK, plan.plan_id)) == EX_OK
    assert h.plan(plan.plan_id).status == ScanStatus.TARGET_REACHED


def test_job_sigterm_cancellation_is_best_effort():
    from ingestion_worker.job import EX_TERMINATED, run_job

    h = Harness(year_and_half())
    rt, plan = prepared_plan(h)

    def cancel(n):
        raise asyncio.CancelledError

    h.source.on_fetch = cancel
    assert run(run_job(rt, BANK, plan.plan_id)) == EX_TERMINATED


def test_job_exit_codes_cover_every_status():
    from ingestion_worker.job import EXIT_CODES

    assert set(EXIT_CODES) == set(ExtractionStatus)


def test_job_main_validates_overrides(monkeypatch):
    from ingestion_worker import job
    from voc_common import Settings

    # asyncio.run anula el loop global que usan los mocks de Pulumi.
    monkeypatch.setattr(job.asyncio, "run", run)
    assert job.main([]) == job.EX_USAGE
    assert job.main(["--bank", "NOPE", "--plan-id", "p"]) == job.EX_USAGE
    monkeypatch.setattr(job, "Settings", lambda: Settings(_env_file=None))
    assert job.main(["--bank", "BBVA", "--plan-id", "p"]) == job.EX_USAGE
    h = Harness([])
    rt = service(h)
    monkeypatch.setattr(job, "Settings", lambda: rt.settings)
    monkeypatch.setattr(
        job.IngestionRuntime, "from_settings", classmethod(lambda cls, s: rt)
    )
    monkeypatch.setenv("INGESTION_BANK_ID", "BBVA")
    monkeypatch.setenv("INGESTION_PLAN_ID", "absent")
    monkeypatch.setenv("INGESTION_STREAM_ID", "")
    assert job.main([]) == job.EX_USAGE


# --------------------------------------------------------------- runtime
def test_cloud_run_launcher_sends_only_validated_identifiers():
    from ingestion_worker.runtime import CloudRunJobLauncher, LaunchError

    with pytest.raises(ValueError):
        CloudRunJobLauncher("voc-ingestion-history-job", Mock())
    session = Mock()
    session.post.return_value = Mock(
        status_code=200,
        json=lambda: {
            "name": "projects/test/operations/op",
            "metadata": {"name": f"{JOB}/executions/e1"},
        },
    )
    launcher = CloudRunJobLauncher(JOB, session)
    assert launcher.launch(BANK, "plan-1", None) == {
        "operation": "projects/test/operations/op",
        "execution": f"{JOB}/executions/e1",
    }
    url = session.post.call_args.args[0]
    sent = session.post.call_args.kwargs["json"]
    assert url == f"https://run.googleapis.com/v2/{JOB}:run"
    (override,) = sent["overrides"]["containerOverrides"]
    assert override["name"] == "historical-ingestion"
    assert {e["name"] for e in override["env"]} == {
        "INGESTION_BANK_ID",
        "INGESTION_PLAN_ID",
        "INGESTION_STREAM_ID",
    }
    assert "args" not in override and "commands" not in override
    with pytest.raises(ValueError):
        launcher.launch(BANK, "../plan", None)
    session.post.return_value = Mock(status_code=403)
    with pytest.raises(LaunchError):
        launcher.launch(BANK, "plan-1", "stream-1")
    session.post.side_effect = OSError("network")
    with pytest.raises(LaunchError):
        launcher.launch(BANK, "plan-1", None)


def test_runtime_factories_use_settings(monkeypatch):
    import google.auth
    import google.auth.transport.requests as transport
    from google.cloud import bigquery, pubsub_v1, storage
    from ingestion_worker.runtime import (
        CloudRunJobLauncher,
        IngestionRuntime,
        execution_config,
        playstore_client,
        topic_path,
    )
    from voc_common import Settings

    settings = Settings(
        _env_file=None,
        ingestion_v2_enabled=True,
        ingestion_history_job_name=JOB,
        gcp_project_id="test",
        scraper_proxy_pool_urls=["http://proxy-a:8080", "http://proxy-b:8080"],
        scraper_rotate_user_agent=True,
    )
    assert topic_path(settings) == (
        "projects/test/topics/voc-raw-reviews-topic"
    )
    full = Settings(
        _env_file=None, pubsub_raw_reviews_topic="projects/x/topics/raw"
    )
    assert topic_path(full) == "projects/x/topics/raw"
    profile = execution_config(settings, ingestion_max_pages=7)
    assert type(profile) is IngestionExecutionConfig
    assert profile.ingestion_max_pages == 7
    monkeypatch.setattr(storage, "Client", lambda **_: FakeStorage())
    monkeypatch.setattr(pubsub_v1, "PublisherClient", Mock)
    monkeypatch.setattr(bigquery, "Client", lambda **_: Mock())
    rt = IngestionRuntime.from_settings(settings)
    assert rt.publisher.topic == topic_path(settings)
    assert rt.audit_writer.table.endswith(".ingestion_runs_log_v2")
    monkeypatch.setattr(google.auth, "default", lambda scopes: (Mock(), "test"))
    monkeypatch.setattr(transport, "AuthorizedSession", lambda creds: Mock())
    assert CloudRunJobLauncher.from_settings(settings).job_name == JOB
    captured: list[Any] = []
    rt.http_factory = FakeHttp

    def factory(http, config, agent):
        captured.append(playstore_client(http, config, agent))
        return h_source

    h_source = Source([])
    rt.client_factory = factory

    async def open_extractor():
        async with rt.extractor() as extractor:
            return extractor

    run(open_extractor())
    assert FakeHttp.created[-1]["proxy"] in settings.scraper_proxy_pool_urls
    assert captured[0].headers["User-Agent"] in DEFAULT_USER_AGENTS


def test_audit_flush_failures_are_deferred():
    from ingestion_worker.audit import AuditDeliveryError

    h = Harness([])
    rt = service(h)
    rt.audit_writer.flush.side_effect = AuditDeliveryError("bq down")
    assert run(rt.flush_audits(BANK)) is None
    rt.audit_writer = None
    assert run(rt.flush_audits(BANK)) is None


def test_prepare_plan_and_stream_selection_guards():
    h = Harness([])
    rt = service(h)

    async def prepare(request):
        async with rt.extractor() as extractor:
            return await extractor.prepare_plan(request)

    with pytest.raises(ValueError):
        run(
            prepare(
                ExtractionRequest(bank_id=BANK, mode=IngestionMode.INCREMENTAL)
            )
        )
    with pytest.raises(ValueError):
        ExtractionRequest(
            bank_id=BANK, mode=IngestionMode.BACKFILL, stream_id="orphan"
        )
    with pytest.raises(ValueError, match="unknown_plan"):
        run(
            prepare(
                ExtractionRequest(
                    bank_id=BANK, mode=IngestionMode.BACKFILL, plan_id="nope"
                )
            )
        )
    result = h.run(IngestionMode.BACKFILL, create_plan=False)
    assert (result.status, result.reason) == (
        ExtractionStatus.RECOVERY_REQUIRED,
        "no_open_plan",
    )
