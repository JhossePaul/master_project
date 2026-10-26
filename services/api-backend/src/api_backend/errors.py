"""Errores de la API con código estable y el formato de su respuesta."""

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorCode(StrEnum):
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    INVALID = "invalid"
    QUERY_TOO_EXPENSIVE = "query_too_expensive"
    UPSTREAM = "upstream"
    INTERNAL = "internal"


STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.INVALID: 422,
    ErrorCode.QUERY_TOO_EXPENSIVE: 503,
    ErrorCode.UPSTREAM: 502,
    ErrorCode.INTERNAL: 500,
}
_CODE_BY_STATUS = {
    401: ErrorCode.UNAUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
}
UNKNOWN_REQUEST_ID = "-"


class ApiError(Exception):
    """Error esperado: el manejador lo convierte en la respuesta JSON."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def status_code(self) -> int:
        return STATUS_BY_CODE[self.code]


def error_body(
    code: ErrorCode, message: str, request_id: str
) -> dict[str, Any]:
    return {
        "error": {
            "code": code.value,
            "message": message,
            "request_id": request_id,
        }
    }


def request_id_of(request: Request) -> str:
    return str(getattr(request.state, "request_id", UNKNOWN_REQUEST_ID))


def error_response(
    request: Request, code: ErrorCode, message: str, status: int | None = None
) -> JSONResponse:
    return JSONResponse(
        error_body(code, message, request_id_of(request)),
        status_code=status or STATUS_BY_CODE[code],
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc.code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = _CODE_BY_STATUS.get(exc.status_code, ErrorCode.INVALID)
        return error_response(request, code, str(exc.detail), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields = sorted(
            {".".join(str(p) for p in e["loc"][1:]) for e in exc.errors()}
        )
        return error_response(
            request,
            ErrorCode.INVALID,
            "Petición no válida: " + ", ".join(fields),
        )
