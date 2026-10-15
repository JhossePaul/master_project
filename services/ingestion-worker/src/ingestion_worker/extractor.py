"""Fetch acotado de una página; recorridos y checkpoints quedan pendientes."""

import asyncio
import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
from voc_common import PLAYSTORE_BANK_APPS, BankKey, ScanContext

from ingestion_worker.playstore_protocol import (
    PROTOCOL_VERSION,
    EmptyAmbiguousError,
    PageClassification,
    ProtocolError,
    RateLimitedError,
    RpcPageResult,
    TransportError,
    build_batchexecute_body,
    build_batchexecute_url,
    parse_batchexecute_response,
)


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            seconds = (date - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(seconds, 0.0) if math.isfinite(seconds) else None


class PlayStoreClient:
    """Reutiliza el cliente inyectado sin cerrar su conexión compartida."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        timeout_sec: float = 30.0,
        max_response_bytes: int = 2_000_000,
    ) -> None:
        if not math.isfinite(timeout_sec) or timeout_sec <= 0:
            raise ValueError("timeout must be positive and finite")
        if type(max_response_bytes) is not int or max_response_bytes < 1:
            raise ValueError("response budget must be a positive integer")
        self.client = client
        self.timeout_sec = timeout_sec
        self.max_response_bytes = max_response_bytes

    async def fetch_page(
        self,
        bank_id: BankKey,
        context: ScanContext,
        page_token: str | None = None,
    ) -> RpcPageResult:
        if PLAYSTORE_BANK_APPS[bank_id] != context.app_id:
            raise ValueError("bank and application differ")
        if context.protocol_version != PROTOCOL_VERSION:
            raise ProtocolError("Unsupported adapter version")
        body = build_batchexecute_body(
            context.app_id,
            context.sort_order,
            context.page_size,
            context.star_filter,
            context.device_filter,
            page_token,
        )
        url = build_batchexecute_url(context.lang, context.country)
        try:
            async with asyncio.timeout(self.timeout_sec):
                async with self.client.stream(
                    "POST",
                    url,
                    content=body,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded"
                    },
                    timeout=self.timeout_sec,
                    follow_redirects=False,
                ) as response:
                    if response.status_code == 429:
                        raise RateLimitedError(
                            _retry_after(response.headers.get("Retry-After"))
                        )
                    if not 200 <= response.status_code < 300:
                        raise TransportError(
                            "Google Play HTTP error", response.status_code
                        )
                    if (
                        "text/html"
                        in response.headers.get("Content-Type", "").lower()
                    ):
                        raise ProtocolError("HTML response is not an RPC page")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > self.max_response_bytes:
                            raise TransportError(
                                "RPC response exceeds byte budget"
                            )
                        data.extend(chunk)
        except (httpx.RequestError, TimeoutError):
            raise TransportError(
                "Google Play request failed or timed out"
            ) from None
        page = parse_batchexecute_response(
            bytes(data), bank_id=bank_id, app_id=context.app_id
        )
        if page.classification == PageClassification.EMPTY_AMBIGUOUS:
            raise EmptyAmbiguousError(page)
        return page
