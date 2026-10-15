"""At-least-once BigQuery audit delivery from the committed GCS outbox."""

import re

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery
from voc_common import BankKey, Settings

from ingestion_worker.watermark_store import WatermarkRepository


class AuditDeliveryError(RuntimeError):
    """Outbox remains durable; retry with the same audit_event_id."""


class BigQueryAuditWriter:
    def __init__(
        self,
        client: bigquery.Client,
        *,
        project: str,
        dataset: str,
        table: str,
        timeout_sec: float = 30,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", project) or any(
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part)
            for part in (dataset, table)
        ):
            raise ValueError("invalid BigQuery audit destination")
        if timeout_sec <= 0:
            raise ValueError("audit timeout must be positive")
        self.client = client
        self.table = f"{project}.{dataset}.{table}"
        self.timeout_sec = timeout_sec

    @classmethod
    def from_settings(
        cls, client: bigquery.Client, settings: Settings
    ) -> "BigQueryAuditWriter":
        settings.require_ingestion_v2()
        return cls(
            client,
            project=settings.gcp_project_id,
            dataset=settings.bq_dataset_id,
            table=settings.bq_ingestion_runs_log_table,
        )

    def flush(
        self,
        repository: WatermarkRepository,
        bank: BankKey,
        *,
        max_events: int = 100,
    ) -> int:
        if type(max_events) is not int or max_events <= 0:
            raise ValueError("audit delivery budget must be positive")
        snapshot = repository.load(bank)
        delivered = 0
        for event in repository.iter_audits(snapshot):
            if repository.audit_delivered(event):
                continue
            try:
                errors = self.client.insert_rows_json(
                    self.table,
                    [event.model_dump(mode="json")],
                    row_ids=[event.audit_event_id],
                    timeout=self.timeout_sec,
                    retry=None,
                )
            except (GoogleAPICallError, TimeoutError):
                raise AuditDeliveryError(
                    "BigQuery audit request failed"
                ) from None
            if errors:
                # Server errors may contain supplied data; never echo them.
                raise AuditDeliveryError("BigQuery rejected audit row")
            # A crash here can duplicate BQ rows; insertId is best-effort only.
            repository.mark_audit_delivered(event)
            delivered += 1
            if delivered >= max_events:
                break
        return delivered
