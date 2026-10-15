"""Protocol and HTTP tests; terminal/error cases are synthetic."""

import asyncio
import hashlib
import json
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from ingestion_worker import (
    PROTOCOL_VERSION,
    EmptyAmbiguousError,
    InvalidCursorError,
    PageClassification,
    PlayStoreClient,
    ProtocolError,
    RateLimitedError,
    TransportError,
    build_batchexecute_body,
    build_batchexecute_url,
    parse_batchexecute_response,
)
from voc_common import (
    PLAYSTORE_BANK_APPS,
    BankKey,
    RawReviewEvent,
    ScanContext,
)

APP = PLAYSTORE_BANK_APPS[BankKey.BBVA]
CURSOR = 'opaque+"\\&=ñ'
FIXTURES = Path(__file__).parent / "fixtures"
T = TypeVar("T")


def run(coro: Coroutine[Any, Any, T]) -> T:
    # Own only this loop; do not clear the loop used by Pulumi mocks.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def row() -> list[Any]:
    return [
        "id",
        ["user"],
        4,
        None,
        "texto",
        [1700000000],
        9,
        None,
        None,
        None,
        "1.0",
        None,
        None,
        None,
        None,
        None,
        None,
    ]


def frame(inner: Any) -> bytes:
    return json.dumps([["wrb.fr", "oCPfdb", json.dumps(inner)]]).encode()


def payload(
    rows: list[Any] | None = None, cursor: str | None = CURSOR
) -> bytes:
    return frame([rows if rows is not None else [row()], [None, cursor], None])


def parse(body: bytes):
    return parse_batchexecute_response(body, bank_id=BankKey.BBVA, app_id=APP)


def context(**kwargs: Any) -> ScanContext:
    return ScanContext(app_id=APP, protocol_version=PROTOCOL_VERSION, **kwargs)


def test_structural_encoding_preserves_opaque_input():
    body = build_batchexecute_body(
        APP,
        count=500,
        filter_score_with=2,
        filter_device_with="phone",
        page_token=CURSOR,
    )
    outer = json.loads(parse_qs(body.decode())["f.req"][0])
    assert outer[0][0][0] == "oCPfdb"
    inner = json.loads(outer[0][0][1])
    assert inner == [
        None,
        [
            2,
            2,
            [500, None, CURSOR],
            None,
            [None, 2, None, None, None, None, None, None, "phone"],
        ],
        [APP, 7],
    ]
    first = json.loads(
        json.loads(parse_qs(build_batchexecute_body(APP).decode())["f.req"][0])[
            0
        ][0][1]
    )
    assert first[1][2] == [500]
    assert parse_qs(urlsplit(build_batchexecute_url("es&x", "mx+")).query) == {
        "hl": ["es&x"],
        "gl": ["mx+"],
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"app_id": ""},
        {"count": 0},
        {"count": True},
        {"sort_order": True},
        {"sort_order": 1.0},
        {"sort_order": 9},
        {"filter_score_with": 0},
        {"filter_score_with": True},
        {"filter_device_with": []},
        {"filter_device_with": ""},
        {"page_token": ""},
        {"page_token": 123},
    ],
)
def test_invalid_request_arguments(kwargs):
    with pytest.raises(ValueError):
        build_batchexecute_body(**({"app_id": APP} | kwargs))


def test_invalid_cursor_and_locale():
    with pytest.raises(InvalidCursorError):
        build_batchexecute_body(APP, page_token="")
    with pytest.raises(ValueError):
        build_batchexecute_url("", "mx")


@pytest.mark.parametrize(
    "name", ["observed_014.txt", "observed_015.txt", "observed_016.txt"]
)
def test_observed_fixtures_match_shared_factory_and_provenance(name):
    body = (FIXTURES / name).read_bytes()
    page = parse(body)
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    evidence = next(f for f in provenance["fixtures"] if f["file"] == name)
    assert hashlib.sha256(body).hexdigest() == evidence["fixture_sha256"]
    assert page.protocol_version == provenance["protocol_version"]
    assert page.raw_body == body
    assert page.evidence.response_sha256 == evidence["fixture_sha256"]
    assert page.evidence.xssi
    assert not page.evidence.terminal_confirmed
    assert page.classification == PageClassification.PAGE_WITH_CURSOR
    inner = json.loads(json.loads(body.decode().split("\n", 1)[1])[0][2])
    assert page.raw_count == len(inner[0]) == len(evidence["projected_indices"])
    for actual, entry in zip(page.reviews, inner[0], strict=True):
        expected = RawReviewEvent.from_batchexecute_entry(
            entry, BankKey.BBVA, APP
        )
        assert actual.model_dump(exclude={"ingested_at"}) == (
            expected.model_dump(exclude={"ingested_at"})
        )
        assert actual.votos_utilidad == entry[6]
    assert "fixture-next-cursor" not in repr(page)
    assert "problema de transferencia" not in repr(page)


def test_multiple_frames_length_markers_and_xssi():
    body = b")]}'\n\n123\n" + json.dumps([["di", 1]]).encode()
    body += b"\n456\n" + payload()
    page = parse(body)
    assert page.evidence.length_markers and page.evidence.xssi


@pytest.mark.parametrize(
    ("rows", "cursor", "classification"),
    [
        ([row()], CURSOR, PageClassification.PAGE_WITH_CURSOR),
        ([row()], None, PageClassification.END_CANDIDATE),
        ([], CURSOR, PageClassification.EMPTY_WITH_CURSOR),
        ([], None, PageClassification.EMPTY_AMBIGUOUS),
    ],
)
def test_synthetic_classifications_never_confirm_eof(
    rows, cursor, classification
):
    page = parse(payload(rows, cursor))
    assert page.classification == classification
    assert not page.evidence.terminal_confirmed


def test_discard_nontext_and_detect_unsorted_whole_page():
    missing = row()
    missing[4] = "  "
    newer = row()
    newer[0], newer[5] = "newer", [1800000000]
    page = parse(payload([missing, newer]))
    assert page.raw_count == 2
    assert len(page.reviews) == 1
    assert page.discarded[0].row_index == 0
    assert page.discarded[0].reason == "NO_TEXT"
    assert not page.descending
    assert parse(payload([missing])).classification == (
        PageClassification.EMPTY_WITH_CURSOR
    )
    assert parse(frame([])).classification == PageClassification.EMPTY_AMBIGUOUS


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"\xff",
        b")]}'oops\n[]",
        b")]}'",
        b"<html>blocked</html>",
        b"[",
        b"{}",
        b"[]",
        payload() + payload(),
        frame({}),
        frame([[], [None, ""], None]),
        frame([[], [None, 123], None]),
        frame([[], ["unexpected", CURSOR], None]),
        frame([[], None, CURSOR]),
        frame([[], [None, None], "unknown"]),
        b'[["wrb.fr","oCPfdb",null]]',
        b'[["wrb.fr","oCPfdb","{"]]',
    ],
)
def test_malformed_or_ambiguous_payload_is_never_empty_success(body):
    with pytest.raises(ProtocolError):
        parse(body)


@pytest.mark.parametrize(
    ("slot", "value"),
    [
        (0, ""),
        (2, True),
        (2, 6),
        (5, []),
        (5, [True]),
        (5, [float("nan")]),
        (5, [float("inf")]),
        (5, [10**400]),
        (6, True),
        (6, -1),
        (7, []),
        (7, [None, 12, None]),
        (7, [None, "reply", []]),
        (7, [None, "reply", [True]]),
        (1, []),
        (4, 12),
    ],
)
def test_invalid_row_fields_fail_explicitly(slot, value):
    entry = row()
    entry[slot] = value
    with pytest.raises(ProtocolError):
        parse(payload([entry]))


def test_short_row_and_wrong_bank():
    with pytest.raises(ProtocolError):
        parse(payload([["id"]]))
    with pytest.raises(ValueError):
        parse_batchexecute_response(
            payload(), bank_id=BankKey.NUBANK, app_id=APP
        )


async def fetch(handler, *, body_context=None, **kwargs):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        result = await PlayStoreClient(client, **kwargs).fetch_page(
            BankKey.BBVA, body_context or context(), CURSOR
        )
        assert not client.is_closed
        return result


def test_http_fetch_sends_one_structural_post():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "POST"
        assert request.headers["content-type"] == (
            "application/x-www-form-urlencoded"
        )
        assert request.content == build_batchexecute_body(
            APP, page_token=CURSOR
        )
        assert dict(request.url.params) == {"hl": "es", "gl": "mx"}
        return httpx.Response(200, content=payload())

    page = run(fetch(handler))
    assert page.raw_count == 1
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("status", "headers", "retry"),
    [
        (429, {"Retry-After": "20"}, 20.0),
        (429, {"Retry-After": "invalid"}, None),
        (429, {"Retry-After": "nan"}, None),
        (429, {}, None),
        (429, {"Retry-After": "-1"}, 0.0),
    ],
)
def test_rate_limit_is_explicit_and_not_retried(status, headers, retry):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers=headers)

    with pytest.raises(RateLimitedError) as caught:
        run(fetch(handler))
    assert caught.value.retry_after_sec == retry
    assert caught.value.status_code == 429
    assert len(calls) == 1


def test_http_date_retry_after():
    future = format_datetime(datetime.now(UTC) + timedelta(minutes=5))
    with pytest.raises(RateLimitedError) as caught:
        run(
            fetch(
                lambda _: httpx.Response(429, headers={"Retry-After": future})
            )
        )
    assert caught.value.retry_after_sec is not None
    assert 290 < caught.value.retry_after_sec <= 300


@pytest.mark.parametrize("status", [302, 400, 403, 500])
def test_http_errors_are_not_cursor_expiry(status):
    with pytest.raises(TransportError) as caught:
        run(fetch(lambda _: httpx.Response(status)))
    assert caught.value.status_code == status
    assert not isinstance(caught.value, InvalidCursorError)


def test_network_errors_do_not_disclose_request_or_retry():
    def handler(request):
        raise httpx.ConnectError("secret upstream detail", request=request)

    with pytest.raises(TransportError) as caught:
        run(fetch(handler))
    assert "secret" not in str(caught.value)
    assert caught.value.__suppress_context__


def test_total_timeout_and_response_budget():
    async def slow(_):
        await asyncio.sleep(0.05)
        return httpx.Response(200, content=payload())

    with pytest.raises(TransportError, match="timed out"):
        run(fetch(slow, timeout_sec=0.001))
    with pytest.raises(TransportError, match="byte budget"):
        run(
            fetch(
                lambda _: httpx.Response(200, content=payload()),
                max_response_bytes=10,
            )
        )


def test_html_and_ambiguous_empty_fail_but_empty_cursor_continues():
    with pytest.raises(ProtocolError, match="HTML"):
        run(
            fetch(
                lambda _: httpx.Response(
                    200,
                    headers={"Content-Type": "text/html"},
                    content=b"blocked",
                )
            )
        )
    with pytest.raises(EmptyAmbiguousError) as caught:
        run(fetch(lambda _: httpx.Response(200, content=payload([], None))))
    assert caught.value.page.raw_count == 0
    page = run(fetch(lambda _: httpx.Response(200, content=payload([]))))
    assert page.next_token == CURSOR


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout_sec": 0},
        {"timeout_sec": float("inf")},
        {"max_response_bytes": 0},
        {"max_response_bytes": True},
    ],
)
def test_invalid_client_budgets(kwargs):
    async def check():
        async with httpx.AsyncClient() as client:
            with pytest.raises(ValueError):
                PlayStoreClient(client, **kwargs)

    run(check())


def test_context_mismatch_fails_before_network():
    def handler(_):
        pytest.fail("must reject context before network")

    with pytest.raises(ProtocolError, match="version"):
        run(
            fetch(
                handler,
                body_context=ScanContext(
                    app_id=APP, protocol_version="unknown"
                ),
            )
        )

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(ValueError, match="application"):
                await PlayStoreClient(client).fetch_page(
                    BankKey.NUBANK, context()
                )

    run(check())
