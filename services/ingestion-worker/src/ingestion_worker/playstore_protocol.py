"""Adaptador oCPfdb versionado. Ninguna clasificación equivale a EOF probado."""

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlencode

from pydantic import ValidationError
from voc_common import (
    DEFAULT_PLAYSTORE_COUNTRY,
    DEFAULT_PLAYSTORE_LANG,
    PLAYSTORE_BANK_APPS,
    PLAYSTORE_BATCHEXECUTE_URL,
    PLAYSTORE_DEFAULT_PAGE_SIZE,
    PLAYSTORE_REVIEWS_RPC_ID,
    BankKey,
    PlayStoreSortOrder,
    RawReviewEvent,
    RawReviewSnapshot,
)

PROTOCOL_VERSION = "ocpfdb-2026-10-15.1"


class ProtocolError(ValueError):
    """Forma no reconocida; no interpretar como fin del origen."""


class InvalidCursorError(ProtocolError):
    """Cursor inválido localmente; HTTP 400 no demuestra expiración."""


class TransportError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RateLimitedError(TransportError):
    def __init__(self, retry_after_sec: float | None = None) -> None:
        super().__init__("Google Play rate limited the request", 429)
        self.retry_after_sec = retry_after_sec


class PageClassification(StrEnum):
    PAGE_WITH_CURSOR = "PAGE_WITH_CURSOR"
    END_CANDIDATE = "END_CANDIDATE"
    EMPTY_WITH_CURSOR = "EMPTY_WITH_CURSOR"
    EMPTY_AMBIGUOUS = "EMPTY_AMBIGUOUS"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"


@dataclass(frozen=True)
class RowDiscard:
    row_index: int
    review_id: str
    reason: str = "NO_TEXT"


@dataclass(frozen=True)
class RpcEvidence:
    xssi: bool
    length_markers: bool
    response_sha256: str
    terminal_confirmed: bool = False


@dataclass(frozen=True)
class RpcPageResult:
    reviews: tuple[RawReviewSnapshot, ...] = field(repr=False)
    raw_count: int
    discarded: tuple[RowDiscard, ...]
    next_token: str | None = field(repr=False)
    classification: PageClassification
    evidence: RpcEvidence
    descending: bool
    raw_body: bytes = field(repr=False)
    protocol_version: str = PROTOCOL_VERSION
    observed_min_at: datetime | None = None
    observed_max_at: datetime | None = None


class EmptyAmbiguousError(ProtocolError):
    def __init__(self, page: RpcPageResult) -> None:
        super().__init__("Empty response is not evidence of source exhaustion")
        self.page = page


def build_batchexecute_body(
    app_id: str,
    sort_order: PlayStoreSortOrder = PlayStoreSortOrder.NEWEST,
    count: int = PLAYSTORE_DEFAULT_PAGE_SIZE,
    filter_score_with: int | None = None,
    filter_device_with: str | int | None = None,
    page_token: str | None = None,
) -> bytes:
    """Solo JSON + urlencode; ni tokens ni filtros se interpolan como código."""
    if not isinstance(app_id, str) or not app_id.strip():
        raise ValueError("app_id must be nonempty")
    if type(count) is not int or count < 1:
        raise ValueError("count must be a positive integer")
    if filter_score_with is not None and (
        type(filter_score_with) is not int
        or filter_score_with not in range(1, 6)
    ):
        raise ValueError("star filter must be in 1..5")
    if filter_device_with is not None and (
        type(filter_device_with) not in (str, int) or filter_device_with == ""
    ):
        raise ValueError("device filter must be a scalar")
    if page_token is not None and (
        not isinstance(page_token, str) or not page_token
    ):
        raise InvalidCursorError("cursor must be a nonempty opaque string")
    if type(sort_order) is not int and not isinstance(
        sort_order, PlayStoreSortOrder
    ):
        raise ValueError("invalid sort order")
    order = PlayStoreSortOrder(sort_order)
    pagination = [count] if page_token is None else [count, None, page_token]
    filters = [
        None,
        filter_score_with,
        None,
        None,
        None,
        None,
        None,
        None,
        filter_device_with,
    ]
    inner = [
        None,
        [2, int(order.value), pagination, None, filters],
        [app_id, 7],
    ]
    outer = [[[PLAYSTORE_REVIEWS_RPC_ID, json.dumps(inner), None, "generic"]]]
    return urlencode({"f.req": json.dumps(outer)}).encode("utf-8")


def build_batchexecute_url(
    lang: str = DEFAULT_PLAYSTORE_LANG,
    country: str = DEFAULT_PLAYSTORE_COUNTRY,
) -> str:
    if not lang or not country:
        raise ValueError("language and country must be nonempty")
    return (
        PLAYSTORE_BATCHEXECUTE_URL
        + "?"
        + urlencode({"hl": lang, "gl": country})
    )


def _frames(value: Any) -> list[list[Any]]:
    result = []
    pending = [value]
    while pending:
        current = pending.pop()
        if not isinstance(current, list):
            continue
        if len(current) >= 2 and current[:2] == [
            "wrb.fr",
            PLAYSTORE_REVIEWS_RPC_ID,
        ]:
            result.append(current)
        else:
            pending.extend(current)
    return result


def _decode_frames(body: bytes) -> tuple[list[Any], bool, bool]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise ProtocolError("RPC response is not UTF-8") from None
    xssi = text.startswith(")]}'")
    if xssi:
        prefix, separator, text = text.partition("\n")
        if prefix != ")]}'" or not separator:
            raise ProtocolError("Invalid XSSI prefix")
    frames: list[list[Any]] = []
    length_markers = False
    decoder = json.JSONDecoder()
    while text.strip():
        text = text.lstrip()
        first, separator, remainder = text.partition("\n")
        if first.isdecimal() and separator:
            length_markers = True
            text = remainder
            continue
        try:
            root, end = decoder.raw_decode(text)
        except (json.JSONDecodeError, RecursionError):
            raise ProtocolError("Invalid or truncated RPC framing") from None
        if not isinstance(root, list):
            raise ProtocolError("Unexpected RPC envelope")
        frames.extend(_frames(root))
        text = text[end:]
    if (
        len(frames) != 1
        or len(frames[0]) < 3
        or not isinstance(frames[0][2], str)
    ):
        raise ProtocolError("Expected exactly one oCPfdb payload frame")
    try:
        inner = json.loads(frames[0][2])
    except (json.JSONDecodeError, RecursionError):
        raise ProtocolError("Invalid inner RPC JSON") from None
    if not isinstance(inner, list):
        raise ProtocolError("Unexpected inner RPC payload")
    return inner, xssi, length_markers


def _timestamp(value: Any) -> None:
    if type(value) not in (int, float):
        raise ProtocolError("Invalid review timestamp")
    try:
        if not math.isfinite(value):
            raise ValueError("nonfinite timestamp")
        datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, ValueError, OSError):
        raise ProtocolError("Review timestamp out of range") from None


def _review(
    row: Any, bank_id: BankKey, app_id: str
) -> RawReviewSnapshot | None:
    if not isinstance(row, list) or len(row) < 11:
        raise ProtocolError("Unexpected review row shape")
    if (
        not isinstance(row[0], str)
        or not row[0]
        or type(row[2]) is not int
        or row[2] not in range(1, 6)
        or not isinstance(row[5], list)
        or not row[5]
    ):
        raise ProtocolError("Invalid review identity, score or date")
    _timestamp(row[5][0])
    if row[6] is not None and (type(row[6]) is not int or row[6] < 0):
        raise ProtocolError("Votes slot [6] must be a nonnegative integer")
    if row[7] is not None:
        reply = row[7]
        if not isinstance(reply, list) or len(reply) < 3:
            raise ProtocolError("Unexpected reply structure")
        if reply[1] is not None and not isinstance(reply[1], str):
            raise ProtocolError("Unexpected reply text")
        if reply[2] is not None:
            if not isinstance(reply[2], list) or not reply[2]:
                raise ProtocolError("Unexpected reply date structure")
            _timestamp(reply[2][0])
    if row[4] is None or (isinstance(row[4], str) and not row[4].strip()):
        return None
    try:
        raw = RawReviewEvent.from_batchexecute_entry(row, bank_id, app_id)
        return RawReviewSnapshot.model_validate(raw.model_dump())
    except (ValidationError, ValueError, TypeError):
        raise ProtocolError(
            "Review fields do not match shared contract"
        ) from None


def parse_batchexecute_response(
    body: bytes,
    *,
    bank_id: BankKey,
    app_id: str,
) -> RpcPageResult:
    if PLAYSTORE_BANK_APPS[bank_id] != app_id:
        raise ValueError("bank and application differ")
    inner, xssi, lengths = _decode_frames(body)
    if not inner:
        rows, token = [], None
    else:
        # La última página del histórico (observada en NUBANK, 204 filas)
        # llega sin bloque de paginación: `inner[1]` es null, no [null, null].
        # Solo se acepta con filas; una página vacía sin cursor sigue siendo
        # un error de protocolo.
        terminal = (
            len(inner) == 3
            and isinstance(inner[0], list)
            and bool(inner[0])
            and inner[1] is None
        )
        if (
            len(inner) != 3
            or not isinstance(inner[0], list)
            or not (terminal or isinstance(inner[1], list))
            or (not terminal and len(inner[1]) != 2)
            or (not terminal and inner[1][0] is not None)
            or (
                inner[2] is not None
                and inner[2] != [[None, [[1800], None, [72000]]]]
            )
        ):
            raise ProtocolError(
                "Unrecognized pagination shape; adapter review required"
            )
        rows, token = inner[0], None if terminal else inner[1][1]
        if token is not None and (not isinstance(token, str) or not token):
            raise ProtocolError("Unrecognized continuation cursor")
    reviews, discarded, dates = [], [], []
    for index, row in enumerate(rows):
        review = _review(row, bank_id, app_id)
        dates.append(row[5][0])
        if review is None:
            discarded.append(RowDiscard(index, row[0]))
        else:
            reviews.append(review)
    classification = (
        PageClassification.PAGE_WITH_CURSOR
        if reviews and token is not None
        else PageClassification.END_CANDIDATE
        if reviews
        else PageClassification.EMPTY_WITH_CURSOR
        if token is not None
        else PageClassification.EMPTY_AMBIGUOUS
    )
    return RpcPageResult(
        tuple(reviews),
        len(rows),
        tuple(discarded),
        token,
        classification,
        RpcEvidence(xssi, lengths, hashlib.sha256(body).hexdigest()),
        all(a >= b for a, b in zip(dates, dates[1:], strict=False)),
        body,
        observed_min_at=datetime.fromtimestamp(min(dates), UTC)
        if dates
        else None,
        observed_max_at=datetime.fromtimestamp(max(dates), UTC)
        if dates
        else None,
    )
