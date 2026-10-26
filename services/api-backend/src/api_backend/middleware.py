"""Id de petición, registro estructurado y encabezados de seguridad (ASGI)."""

import json
import time
import uuid
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send
from voc_common import log_event

from api_backend.errors import ErrorCode, error_body

TRACE_HEADER = b"x-cloud-trace-context"
REQUEST_ID_HEADER = b"x-request-id"
API_PREFIX = "/api/"
SECURITY_HEADERS: dict[bytes, bytes] = {
    b"content-security-policy": (
        b"default-src 'self'; img-src 'self' data:; "
        b"style-src 'self' 'unsafe-inline'; font-src 'self'; "
        b"connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    ),
    b"x-content-type-options": b"nosniff",
    b"referrer-policy": b"no-referrer",
}


def request_id_from(headers: list[tuple[bytes, bytes]]) -> str:
    """Id del ``X-Cloud-Trace-Context`` (``TRAZA/SPAN;o=1``) o un UUID."""
    for name, value in headers:
        if name.lower() == TRACE_HEADER:
            trace = value.decode("latin-1").split("/")[0].strip()
            if trace:
                return trace
    return uuid.uuid4().hex


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = request_id_from(scope["headers"])
        state: dict[str, Any] = scope.setdefault("state", {})
        state["request_id"] = request_id
        path: str = scope["path"]
        started = time.monotonic()
        status = 500
        sent_start = False

        async def send_with_headers(message: Message) -> None:
            nonlocal status, sent_start
            if message["type"] == "http.response.start":
                sent_start = True
                status = message["status"]
                headers = [
                    (k, v)
                    for k, v in message["headers"]
                    if k.lower() not in {REQUEST_ID_HEADER, *SECURITY_HEADERS}
                ]
                headers.append((REQUEST_ID_HEADER, request_id.encode()))
                headers.extend(SECURITY_HEADERS.items())
                if path.startswith(API_PREFIX):
                    headers = [
                        (k, v)
                        for k, v in headers
                        if k.lower() != b"cache-control"
                    ]
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            log_event(
                "ERROR",
                "error no controlado",
                request_id=request_id,
                route=_route_of(scope),
            )
            if sent_start:
                raise
            await _internal_error(request_id, send_with_headers)
        finally:
            severity = "ERROR" if status >= 500 else "INFO"
            log_event(
                severity,
                "petición",
                request_id=request_id,
                route=_route_of(scope),
                status=status,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                actor_hash=state.get("actor_hash"),
            )


def _route_of(scope: Scope) -> str:
    route = scope.get("route")
    return str(getattr(route, "path", "sin_ruta"))


async def _internal_error(request_id: str, send: Send) -> None:
    body = json.dumps(
        error_body(ErrorCode.INTERNAL, "Error interno", request_id)
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 500,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
