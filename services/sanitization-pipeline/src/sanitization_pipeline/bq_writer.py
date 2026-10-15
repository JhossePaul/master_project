"""Upsert idempotente en `sanitized_reviews_tds` (EPIC-4 4.3).

Carga batch (FILE_LOADS) en una tabla efímera del mismo dataset y `MERGE`
ordenado por `(fecha, source_observed_at)`. Solo recibe registros ya
sanitizados; no usa Streaming Inserts ni job IDs deterministas (BigQuery
rechaza reutilizar un ID aunque el job haya fallado: la idempotencia es del
`MERGE`).
"""

import hashlib
import json
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery
from voc_common import SanitizedReviewEnvelope, SanitizedReviewRecord

TDS_TABLE = "sanitized_reviews_tds"
# Debe coincidir con `_SANITIZED` de infra/modules/storage_bq.py (17 columnas).
TDS_SCHEMA: tuple[tuple[str, str, str], ...] = (
    ("id_resena", "STRING", "REQUIRED"),
    ("bank_id", "STRING", "REQUIRED"),
    ("app_id", "STRING", "REQUIRED"),
    ("usuario_hash", "STRING", "REQUIRED"),
    ("titulo", "STRING", "NULLABLE"),
    ("texto_sanitizado", "STRING", "REQUIRED"),
    ("texto_limpio", "STRING", "REQUIRED"),
    ("conteo_palabras", "INTEGER", "REQUIRED"),
    ("pii_findings_count", "INTEGER", "REQUIRED"),
    ("estrellas", "INTEGER", "REQUIRED"),
    ("votos_utilidad", "INTEGER", "REQUIRED"),
    ("version_app", "STRING", "REQUIRED"),
    ("fecha", "TIMESTAMP", "REQUIRED"),
    ("texto_respuesta_sanitizado", "STRING", "NULLABLE"),
    ("fecha_respuesta", "TIMESTAMP", "NULLABLE"),
    ("sanitized_at", "TIMESTAMP", "REQUIRED"),
    ("source_observed_at", "TIMESTAMP", "REQUIRED"),
)
TDS_COLUMNS: tuple[str, ...] = tuple(name for name, _, _ in TDS_SCHEMA)
_KEYS = ("bank_id", "id_resena")
_PROJECT = re.compile(
    r"[a-z0-9][a-z0-9-]{4,61}[a-z0-9]|[A-Za-z0-9][A-Za-z0-9-]*"
)
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TABLE_ID = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9-]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*"
)


class TdsWriteError(RuntimeError):
    """Carga o MERGE fallidos: no hay recibos ni `ack` (reintento seguro)."""


@dataclass(frozen=True)
class TdsCommit:
    job_ids: tuple[str, ...]
    rows_merged: int


def record_to_bq_row(record: SanitizedReviewRecord) -> dict[str, Any]:
    """Exactamente las 17 columnas; fechas en UTC ISO-8601."""
    row = record.model_dump(mode="json")
    if set(row) != set(TDS_COLUMNS):
        raise ValueError("sanitized record differs from TDS schema")
    return {name: row[name] for name in TDS_COLUMNS}


def envelope_digest(envelope: SanitizedReviewEnvelope) -> str:
    """Digest del resultado persistido, para `ProcessingReceipt`."""
    canonical = json.dumps(
        envelope.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def latest_revisions(
    envelopes: Sequence[SanitizedReviewEnvelope],
) -> list[SanitizedReviewEnvelope]:
    """Una fila por reseña: mayor (fecha, source_observed_at, revisión)."""
    best: dict[tuple[str, str], SanitizedReviewEnvelope] = {}
    for envelope in envelopes:
        record = envelope.record
        key = (record.bank_id.value, record.id_resena)
        current = best.get(key)
        rank = (
            record.fecha,
            record.source_observed_at,
            envelope.source_revision,
        )
        if current is None or rank > (
            current.record.fecha,
            current.record.source_observed_at,
            current.source_revision,
        ):
            best[key] = envelope
    return list(best.values())


def merge_statement(target: str, staging: str) -> str:
    # BigQuery no parametriza identificadores: se validan antes de componer.
    if not (_TABLE_ID.fullmatch(target) and _TABLE_ID.fullmatch(staging)):
        raise ValueError("invalid BigQuery table identifier")
    updates = ",\n    ".join(
        f"{name} = S.{name}" for name in TDS_COLUMNS if name not in _KEYS
    )
    columns = ", ".join(TDS_COLUMNS)
    values = ", ".join(f"S.{name}" for name in TDS_COLUMNS)
    # Un replay anterior (o con igual fecha y captura previa) nunca gana.
    # Solo identificadores validados y columnas fijas (S608/B608 revisados).
    return (
        f"MERGE `{target}` T\n"  # noqa: S608  # nosec B608
        f"USING `{staging}` S\n"
        "ON T.bank_id = S.bank_id AND T.id_resena = S.id_resena\n"
        "WHEN MATCHED AND (S.fecha > T.fecha OR (S.fecha = T.fecha AND "
        "S.source_observed_at >= T.source_observed_at)) THEN UPDATE SET\n"
        f"    {updates}\n"
        f"WHEN NOT MATCHED THEN INSERT ({columns}) VALUES ({values})"
    )


class BigQueryTdsUpsertManager:
    def __init__(
        self,
        client: bigquery.Client,
        *,
        project: str,
        dataset: str,
        table: str = TDS_TABLE,
        staging_ttl: timedelta = timedelta(hours=1),
        timeout_sec: float = 300.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not _PROJECT.fullmatch(project) or not all(
            _IDENT.fullmatch(part) for part in (dataset, table)
        ):
            raise ValueError("invalid BigQuery TDS destination")
        if staging_ttl <= timedelta(0) or timeout_sec <= 0:
            raise ValueError("staging TTL and timeout must be positive")
        self.client = client
        self.project = project
        self.dataset = dataset
        self.table = f"{project}.{dataset}.{table}"
        self.staging_ttl = staging_ttl
        self.timeout_sec = timeout_sec
        self.clock = clock

    @staticmethod
    def schema() -> list[bigquery.SchemaField]:
        return [
            bigquery.SchemaField(name, kind, mode=mode)
            for name, kind, mode in TDS_SCHEMA
        ]

    def _staging_id(self, envelopes: Sequence[SanitizedReviewEnvelope]) -> str:
        digest = hashlib.sha256(
            "\n".join(sorted(e.event_id for e in envelopes)).encode()
        ).hexdigest()[:16]
        # Sufijo aleatorio: un reintento nunca choca con una tabla huérfana.
        suffix = uuid.uuid4().hex[:8]
        name = f"_staging_sanitized_{digest}_{suffix}"
        return f"{self.project}.{self.dataset}.{name}"

    def upsert_sanitized_batch(
        self, envelopes: Sequence[SanitizedReviewEnvelope]
    ) -> TdsCommit:
        rows = latest_revisions(envelopes)
        if not rows:
            return TdsCommit((), 0)
        staging_id = self._staging_id(rows)
        staging = bigquery.Table(staging_id, schema=self.schema())
        staging.expires = self.clock() + self.staging_ttl
        try:
            self.client.create_table(staging, timeout=self.timeout_sec)
            load = self.client.load_table_from_json(
                [record_to_bq_row(e.record) for e in rows],
                staging_id,
                job_id_prefix="voc_tds_load_",
                job_config=bigquery.LoadJobConfig(
                    schema=self.schema(),
                    source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                    write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                ),
                timeout=self.timeout_sec,
            )
            load.result(timeout=self.timeout_sec)
            if load.errors:
                raise TdsWriteError("staging load reported errors")
            merge = self.client.query(
                merge_statement(self.table, staging_id),
                job_id_prefix="voc_tds_merge_",
                timeout=self.timeout_sec,
            )
            merge.result(timeout=self.timeout_sec)
            if merge.errors:
                raise TdsWriteError("TDS MERGE reported errors")
            return TdsCommit((load.job_id, merge.job_id), len(rows))
        except (GoogleAPICallError, TimeoutError):
            # Los errores de BigQuery pueden citar datos: no se propagan.
            raise TdsWriteError("BigQuery TDS upsert failed") from None
        finally:
            try:
                self.client.delete_table(
                    staging_id, not_found_ok=True, timeout=self.timeout_sec
                )
            except (GoogleAPICallError, TimeoutError):
                # La expiración de 1 h limpia la tabla si el borrado falla.
                pass
