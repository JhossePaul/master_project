"""Escritura de solo inserción, idempotente por clave."""

import json
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery
from pydantic import BaseModel
from voc_common import ANALYTICS_V3_TABLES
from voc_common.bq_schema import bq_schema

from api_backend.bq.names import qualified
from api_backend.bq.reader import Param, query_parameter, to_api_error
from api_backend.settings import ApiSettings


def param_value(kind: str, mode: str, value: Any) -> Any:
    """Valor de un campo en JSON, listo para ser parámetro de BigQuery."""
    if value is None:
        return None
    if mode == "REPEATED":
        return [param_value(kind, "NULLABLE", item) for item in value]
    if kind == "JSON":
        return json.dumps(value, ensure_ascii=False)
    if kind == "TIMESTAMP":
        return datetime.fromisoformat(value)
    if kind == "DATE":
        return date.fromisoformat(value)
    return value


def _expression(name: str, kind: str, mode: str, suffix: str = "") -> str:
    ref = f"@{name}{suffix}"
    if kind != "JSON":
        return ref
    if mode == "REPEATED":
        # BigQuery no admite parámetros ARRAY<JSON>: viajan como texto.
        return f"ARRAY(SELECT PARSE_JSON(v) FROM UNNEST({ref}) AS v)"  # noqa: S608  # nosec B608
    return f"PARSE_JSON({ref})"


def insert_statement(
    target: str,
    columns: Sequence[tuple[str, str, str]],
    key: Sequence[str],
    rows: int = 1,
) -> str:
    """``INSERT … SELECT … WHERE NOT EXISTS`` con las columnas por nombre.

    Van entre comillas invertidas porque algunas son palabras reservadas
    (``at``); por nombre, porque ``INSERT`` por posición falló en 6.6 con las
    columnas que se agregan al final de una tabla ya creada.
    """
    by_name = {name: mode for name, _, mode in columns}
    if not key or any(k not in by_name for k in key):
        raise ValueError("la clave debe ser columnas de la tabla")
    names = ", ".join(f"`{name}`" for name, _, _ in columns)
    # Con varias filas los parámetros llevan el sufijo ``__<fila>``.
    selects = []
    for i in range(rows):
        suffix = f"__{i}" if rows > 1 else ""
        values = ", ".join(
            _expression(name, kind, mode, suffix)
            for name, kind, mode in columns
        )
        match = " AND ".join(
            f"(`{k}` = @{k}{suffix} "
            f"OR (`{k}` IS NULL AND @{k}{suffix} IS NULL))"
            if by_name[k] == "NULLABLE"
            else f"`{k}` = @{k}{suffix}"
            for k in key
        )
        selects.append(
            f"SELECT {values} FROM (SELECT 1) "  # noqa: S608  # nosec B608
            f"WHERE NOT EXISTS (SELECT 1 FROM {target} WHERE {match})"
        )
    # Columnas del modelo y tabla de la lista cerrada; los valores, parámetros.
    return f"INSERT INTO {target} ({names}) " + " UNION ALL ".join(selects)  # noqa: S608  # nosec B608


class BigQueryWriter:
    def __init__(self, client: bigquery.Client, settings: ApiSettings) -> None:
        self._client = client
        self._settings = settings

    def insert(self, table: str, row: BaseModel, key: Sequence[str]) -> bool:
        """Inserta una fila de un modelo de voc-common.

        Devuelve ``False`` si la clave ya existía (un reintento).
        """
        return self.insert_many(table, [row], key) > 0

    def insert_many(
        self, table: str, rows: Sequence[BaseModel], key: Sequence[str]
    ) -> int:
        """Inserta varias filas en una sola sentencia; devuelve las nuevas.

        Una sola consulta en vez de una por fila: cada ``INSERT`` de BigQuery
        tarda segundos. Las filas cuya clave ya existía se omiten.
        """
        model = ANALYTICS_V3_TABLES.get(table)
        if model is None or any(not isinstance(row, model) for row in rows):
            raise TypeError(f"la fila no es de la tabla {table!r}")
        if not rows:
            return 0
        columns = bq_schema(model)
        target = qualified(
            table, self._settings.gcp_project_id, self._settings.bq_dataset_id
        )
        many = len(rows) > 1
        params = []
        for n, row in enumerate(rows):
            data = row.model_dump(mode="json")
            params.extend(
                Param(
                    f"{name}__{n}" if many else name,
                    "STRING" if kind == "JSON" else kind,  # type: ignore[arg-type]
                    param_value(kind, mode, data[name]),
                    array=mode == "REPEATED",
                )
                for name, kind, mode in columns
            )
        config = bigquery.QueryJobConfig(
            query_parameters=[query_parameter(p) for p in params],
            maximum_bytes_billed=self._settings.bq_max_bytes_billed,
        )
        try:
            job = self._client.query(
                insert_statement(target, columns, key, len(rows)),
                job_config=config,
            )
            job.result()
        except GoogleAPICallError as exc:
            raise to_api_error(exc) from exc
        return int(job.num_dml_affected_rows or 0)
