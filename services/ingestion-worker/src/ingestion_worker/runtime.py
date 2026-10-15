"""Cableado de Settings a clientes reales; compartido por la API y el Job.

Los clientes de GCP se crean una sola vez por proceso. El cliente HTTP del
origen vive solo durante una invocación y se reutiliza entre páginas.
"""

import asyncio
import hashlib
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from google.api_core.exceptions import GoogleAPICallError
from voc_common import (
    BankKey,
    IngestionExecutionConfig,
    IngestionStorageLayout,
    Settings,
)

from ingestion_worker.audit import AuditDeliveryError, BigQueryAuditWriter
from ingestion_worker.extractor import PlayStoreClient
from ingestion_worker.publisher import RawReviewBatchPublisher
from ingestion_worker.runner import (
    BacklogSignal,
    PlayStoreResilientExtractor,
    select_user_agent,
)
from ingestion_worker.watermark_store import WatermarkRepository

_LOG = logging.getLogger(__name__)
_JOB_NAME = re.compile(r"projects/[^/]+/locations/[^/]+/jobs/[^/]+")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
# Contenedor del Job declarado en EPIC-2 (infra/modules/cloud_run.py).
HISTORICAL_CONTAINER = "historical-ingestion"


def execution_config(
    settings: IngestionExecutionConfig, **changes: Any
) -> IngestionExecutionConfig:
    """Perfil puro validado, sin campos ajenos a la ejecución."""
    values = {
        key: getattr(settings, key)
        for key in IngestionExecutionConfig.model_fields
    }
    return IngestionExecutionConfig.model_validate(values | changes)


def storage_layout(settings: Settings) -> IngestionStorageLayout:
    return IngestionStorageLayout.model_validate(
        {
            key: getattr(settings, key)
            for key in IngestionStorageLayout.model_fields
        }
    )


def topic_path(settings: Settings) -> str:
    topic = settings.pubsub_raw_reviews_topic
    if topic.startswith("projects/"):
        return topic
    return f"projects/{settings.gcp_project_id}/topics/{topic}"


class LaunchError(RuntimeError):
    """La solicitud a Cloud Run falló; no se expone su cuerpo."""


class JobLauncher(Protocol):
    def launch(
        self, bank: BankKey, plan_id: str, stream_id: str | None
    ) -> dict[str, str | None]: ...


class CloudRunJobLauncher:
    """`jobs.run` con overrides limitados a identificadores validados."""

    def __init__(
        self,
        job_name: str,
        session: Any,
        *,
        timeout_sec: float = 30.0,
    ) -> None:
        if not _JOB_NAME.fullmatch(job_name):
            raise ValueError("job name must be the full Cloud Run resource")
        self.job_name = job_name
        self.session = session
        self.timeout_sec = timeout_sec

    @classmethod
    def from_settings(cls, settings: Settings) -> "CloudRunJobLauncher":
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        settings.require_ingestion_v2(historical=True)
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        job_name = settings.ingestion_history_job_name or ""
        return cls(job_name, AuthorizedSession(credentials))

    def launch(
        self, bank: BankKey, plan_id: str, stream_id: str | None
    ) -> dict[str, str | None]:
        if not _SAFE_ID.fullmatch(plan_id) or (
            stream_id is not None and not _SAFE_ID.fullmatch(stream_id)
        ):
            raise ValueError("plan and stream must be validated identifiers")
        env = [
            {"name": "INGESTION_BANK_ID", "value": bank.value},
            {"name": "INGESTION_PLAN_ID", "value": plan_id},
            {"name": "INGESTION_STREAM_ID", "value": stream_id or ""},
        ]
        body = {
            "overrides": {
                "containerOverrides": [
                    {"name": HISTORICAL_CONTAINER, "env": env}
                ]
            }
        }
        try:
            response = self.session.post(
                f"https://run.googleapis.com/v2/{self.job_name}:run",
                json=body,
                timeout=self.timeout_sec,
            )
        except Exception:
            raise LaunchError("Cloud Run job launch failed") from None
        if not 200 <= response.status_code < 300:
            raise LaunchError(
                f"Cloud Run job launch rejected ({response.status_code})"
            )
        operation = response.json()
        metadata = operation.get("metadata") or {}
        return {
            "operation": operation.get("name"),
            "execution": metadata.get("name"),
        }


def playstore_client(
    http: httpx.AsyncClient,
    config: IngestionExecutionConfig,
    user_agent: str | None,
) -> PlayStoreClient:
    return PlayStoreClient(
        http, timeout_sec=config.scraper_timeout_sec, user_agent=user_agent
    )


@dataclass
class IngestionRuntime:
    """Dependencias de proceso; los tests inyectan dobles locales."""

    settings: Settings
    repository: WatermarkRepository
    publisher: RawReviewBatchPublisher
    audit_writer: BigQueryAuditWriter | None = None
    launcher: JobLauncher | None = None
    backlog: BacklogSignal | None = None
    http_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient
    client_factory: Callable[
        [httpx.AsyncClient, IngestionExecutionConfig, str | None], Any
    ] = playstore_client
    extractor_options: dict[str, Any] = field(default_factory=dict)
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    monotonic: Callable[[], float] = time.monotonic

    @classmethod
    def from_settings(cls, settings: Settings) -> "IngestionRuntime":
        from google.cloud import bigquery, pubsub_v1, storage

        settings.require_ingestion_v2()
        repository = WatermarkRepository(
            storage.Client(project=settings.gcp_project_id),
            settings.gcs_raw_datalake_bucket,
            layout=storage_layout(settings),
            lease_duration_sec=settings.ingestion_lease_duration_sec,
        )
        publisher = RawReviewBatchPublisher(
            repository, pubsub_v1.PublisherClient(), topic_path(settings)
        )
        return cls(
            settings=settings,
            repository=repository,
            publisher=publisher,
            audit_writer=BigQueryAuditWriter.from_settings(
                bigquery.Client(project=settings.gcp_project_id), settings
            ),
        )

    @asynccontextmanager
    async def extractor(
        self, config: IngestionExecutionConfig | None = None
    ) -> AsyncIterator[PlayStoreResilientExtractor]:
        """Un cliente HTTP por invocación; proxy y User-Agent opcionales."""
        config = config or execution_config(self.settings)
        seed = uuid.uuid4().hex
        proxies = self.settings.scraper_proxy_pool_urls
        options: dict[str, Any] = {"follow_redirects": False}
        if proxies:
            index = hashlib.sha256(seed.encode()).digest()[0] % len(proxies)
            options["proxy"] = proxies[index]
        async with self.http_factory(**options) as http:
            client = self.client_factory(
                http, config, select_user_agent(seed, config)
            )
            yield PlayStoreResilientExtractor(
                self.repository,
                self.publisher,
                client,
                config,
                backlog=self.backlog,
                **self.extractor_options,
            )

    async def flush_audits(self, bank: BankKey) -> int | None:
        """Entrega best-effort; la cola GCS conserva lo no entregado."""
        writer = self.audit_writer
        if writer is None:
            return None
        try:
            return await asyncio.to_thread(writer.flush, self.repository, bank)
        except (AuditDeliveryError, GoogleAPICallError):
            _LOG.warning("Audit outbox delivery deferred")
            return None
