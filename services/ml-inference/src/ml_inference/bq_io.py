"""Escritura idempotente en las tablas v3 (generaliza la de la ingesta).

Tabla temporal con expiración de 1 h → ``load_table_from_json`` → ``MERGE …
WHEN NOT MATCHED THEN INSERT ROW`` → borrado de la temporal en ``finally``.
Las tablas son de solo inserción: la clave hace idempotente la escritura y
una segunda corrida no inserta nada.
"""

import re
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from string import Template
from typing import Any

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery
from pydantic import BaseModel
from voc_common.bq_schema import ANALYTICS_V3_TABLES, bq_schema

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


# Proyecto, dataset y tabla (los proyectos admiten guiones).
_TABLE_REF = re.compile(r"[A-Za-z0-9_.-]+")


def render(template: str, **tables: str) -> str:
    """Inserta identificadores de tabla validados en ``${nombre}``.

    Los valores de las consultas van siempre como parámetros (``@nombre``);
    aquí solo entran nombres de proyecto, dataset y tabla.
    """
    for name, value in tables.items():
        if not _TABLE_REF.fullmatch(value):
            raise ValueError(f"invalid table reference for {name}")
    return Template(template).substitute(tables)


class BqWriteError(RuntimeError):
    """Falla de escritura; no cita datos de las filas."""


def schema_fields(model: type[BaseModel]) -> list[bigquery.SchemaField]:
    return [
        bigquery.SchemaField(name, kind, mode=mode)
        for name, kind, mode in bq_schema(model)
    ]


def merge_statement(target: str, staging: str, key: Sequence[str]) -> str:
    """``MERGE`` de solo inserción por ``key`` (dos nulos son iguales)."""
    if not key or not all(_IDENT.fullmatch(k) for k in key):
        raise ValueError("invalid merge key")
    on = " AND ".join(
        f"(T.{k} = S.{k} OR (T.{k} IS NULL AND S.{k} IS NULL))" for k in key
    )
    return render(
        "MERGE `${target}` T USING `${staging}` S ON ",
        target=target,
        staging=staging,
    ) + Template("$on WHEN NOT MATCHED THEN INSERT ROW").substitute(on=on)


@dataclass
class StagingMergeWriter:
    client: bigquery.Client
    dataset: str  # ``proyecto.dataset``
    staging_ttl: timedelta = timedelta(hours=1)
    timeout_sec: float = 600.0
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def table_id(self, table: str) -> str:
        if not _IDENT.fullmatch(table):
            raise ValueError("invalid table name")
        return f"{self.dataset}.{table}"

    def write(
        self,
        table: str,
        rows: Sequence[BaseModel],
        key: Sequence[str],
        run_id: str,
    ) -> int:
        """Inserta las filas cuya clave no existe; devuelve cuántas entraron."""
        if not rows:
            return 0
        model = ANALYTICS_V3_TABLES[table]
        if not all(isinstance(row, model) for row in rows):
            raise TypeError(f"rows must be {model.__name__}")
        run = re.sub(r"[^A-Za-z0-9_]", "_", run_id)[:40]
        staging = self.table_id(
            f"_staging_{table}_{run}_{uuid.uuid4().hex[:8]}"
        )
        schema = schema_fields(model)
        temp = bigquery.Table(staging, schema=schema)
        temp.expires = self.clock() + self.staging_ttl
        try:
            self.client.create_table(temp, timeout=self.timeout_sec)
            load = self.client.load_table_from_json(
                [row.model_dump(mode="json") for row in rows],
                staging,
                job_id_prefix=f"voc_{table}_load_",
                job_config=bigquery.LoadJobConfig(
                    schema=schema,
                    source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                    write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                ),
                timeout=self.timeout_sec,
            )
            load.result(timeout=self.timeout_sec)
            merge = self.client.query(
                merge_statement(self.table_id(table), staging, key),
                job_id_prefix=f"voc_{table}_merge_",
                timeout=self.timeout_sec,
            )
            merge.result(timeout=self.timeout_sec)
            return int(merge.num_dml_affected_rows or 0)
        except (GoogleAPICallError, TimeoutError):
            raise BqWriteError(f"BigQuery write to {table} failed") from None
        finally:
            try:
                self.client.delete_table(
                    staging, not_found_ok=True, timeout=self.timeout_sec
                )
            except (GoogleAPICallError, TimeoutError):
                pass  # La expiración de 1 h limpia la tabla.


def query_rows(
    client: bigquery.Client,
    sql: str,
    params: Mapping[str, Any] | None = None,
    timeout_sec: float = 600.0,
) -> list[dict[str, Any]]:
    """Ejecuta una consulta con parámetros nombrados y devuelve dicts."""
    config = bigquery.QueryJobConfig(
        query_parameters=[_param(k, v) for k, v in (params or {}).items()]
    )
    job = client.query(sql, job_config=config, timeout=timeout_sec)
    return [dict(row.items()) for row in job.result(timeout=timeout_sec)]


def iter_rows(
    client: bigquery.Client,
    sql: str,
    params: Mapping[str, Any] | None = None,
    page_size: int = 10_000,
    timeout_sec: float = 3600.0,
) -> Iterator[dict[str, Any]]:
    """Como ``query_rows``, pero lee el resultado por páginas, sin cargarlo
    entero en memoria."""
    config = bigquery.QueryJobConfig(
        query_parameters=[_param(k, v) for k, v in (params or {}).items()]
    )
    job = client.query(sql, job_config=config, timeout=timeout_sec)
    for row in job.result(timeout=timeout_sec, page_size=page_size):
        yield dict(row.items())


def _param(name: str, value: Any) -> Any:
    if isinstance(value, list | tuple):
        kind = "INT64" if value and isinstance(value[0], int) else "STRING"
        return bigquery.ArrayQueryParameter(name, kind, list(value))
    kinds = {
        bool: "BOOL",
        int: "INT64",
        float: "FLOAT64",
        datetime: "TIMESTAMP",
    }
    kind = next((k for t, k in kinds.items() if isinstance(value, t)), "STRING")
    return bigquery.ScalarQueryParameter(name, kind, value)


def load_parquet(
    client: bigquery.Client,
    path: str,
    table_id: str,
    *,
    ttl: timedelta = timedelta(hours=6),
    timeout_sec: float = 7200.0,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:
    """Carga un parquet local en una tabla temporal (expira en ``ttl``)."""
    config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        parquet_options=_list_inference(),
    )
    with open(path, "rb") as handle:  # noqa: PTH123
        job = client.load_table_from_file(
            handle, table_id, job_config=config, timeout=timeout_sec
        )
    job.result(timeout=timeout_sec)
    table = client.get_table(table_id)
    table.expires = clock() + ttl
    client.update_table(table, ["expires"])
    return table_id


def _list_inference() -> Any:
    options = bigquery.ParquetOptions()
    options.enable_list_inference = True
    return options


def run_dml(
    client: bigquery.Client,
    sql: str,
    params: Mapping[str, Any] | None = None,
    timeout_sec: float = 3600.0,
) -> int:
    """Ejecuta un ``MERGE``/``INSERT`` y devuelve las filas afectadas."""
    config = bigquery.QueryJobConfig(
        query_parameters=[_param(k, v) for k, v in (params or {}).items()]
    )
    job = client.query(sql, job_config=config, timeout=timeout_sec)
    job.result(timeout=timeout_sec)
    return int(job.num_dml_affected_rows or 0)
