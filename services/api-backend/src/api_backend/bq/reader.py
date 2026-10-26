"""Lectura parametrizada de BigQuery con tope de bytes y caché de agregados."""

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from cachetools import TTLCache
from google.api_core.exceptions import BadRequest, GoogleAPICallError
from google.cloud import bigquery
from voc_common import log_event

from api_backend.errors import ApiError, ErrorCode
from api_backend.settings import ApiSettings

ParamType = Literal["STRING", "INT64", "FLOAT64", "BOOL", "DATE", "TIMESTAMP"]
BYTES_LIMIT_REASON = "bytesBilledLimitExceeded"
CACHE_MAX_ENTRIES = 256


@dataclass(frozen=True)
class Param:
    name: str
    type: ParamType
    value: object
    array: bool = False


def query_parameter(
    param: Param,
) -> bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter:
    if param.array:
        values = list(param.value)  # type: ignore[call-overload]
        return bigquery.ArrayQueryParameter(param.name, param.type, values)
    return bigquery.ScalarQueryParameter(param.name, param.type, param.value)


def too_expensive(exc: Exception) -> bool:
    if not isinstance(exc, BadRequest):
        return False
    reasons = [str(error.get("reason", "")) for error in exc.errors or []]
    return BYTES_LIMIT_REASON in reasons or "bytes billed" in str(exc)


def to_api_error(exc: GoogleAPICallError) -> ApiError:
    if too_expensive(exc):
        return ApiError(
            ErrorCode.QUERY_TOO_EXPENSIVE,
            "La consulta supera el tope de bytes; acota el rango",
        )
    return ApiError(ErrorCode.UPSTREAM, "BigQuery no pudo responder")


class BigQueryReader:
    def __init__(self, client: bigquery.Client, settings: ApiSettings) -> None:
        self._client = client
        self._settings = settings
        self._cache: TTLCache[tuple[Any, ...], list[Mapping[str, object]]] = (
            TTLCache(
                maxsize=CACHE_MAX_ENTRIES,
                ttl=max(settings.cache_ttl_seconds, 1),
            )
        )

    def rows(
        self,
        sql: str,
        params: Sequence[Param],
        *,
        name: str = "query",
        cache: bool = False,
        max_bytes: int | None = None,
    ) -> list[Mapping[str, object]]:
        """Ejecuta ``sql`` con ``params``; ``cache`` solo para agregados."""
        key = (sql, *(_cache_part(p) for p in params))
        if cache and key in self._cache:
            return self._cache[key]
        config = bigquery.QueryJobConfig(
            query_parameters=[query_parameter(p) for p in params],
            maximum_bytes_billed=max_bytes
            or self._settings.bq_max_bytes_billed,
            use_query_cache=True,
        )
        started = time.monotonic()
        try:
            job = self._client.query(sql, job_config=config)
            result = [dict(row.items()) for row in job.result()]
        except GoogleAPICallError as exc:
            log_event("WARNING", "consulta rechazada", query=name)
            raise to_api_error(exc) from exc
        log_event(
            "INFO",
            "consulta",
            query=name,
            bytes_billed=job.total_bytes_billed,
            seconds=round(time.monotonic() - started, 3),
            rows=len(result),
        )
        if cache:
            self._cache[key] = result
        return result


def _cache_part(param: Param) -> tuple[Any, ...]:
    value = tuple(param.value) if param.array else param.value  # type: ignore[call-overload]
    return (param.name, param.type, param.array, value)
