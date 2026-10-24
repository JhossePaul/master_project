"""Configuración centralizada de BBVA VoC Analyzer.

Los nombres de los campos coinciden (sin distinguir mayúsculas) con las
variables de entorno inyectadas por Pulumi en Cloud Run (Épica 2), p. ej.
``GCP_PROJECT_ID``, ``SCRAPER_PAGE_SIZE`` o ``DLP_INSPECT_TEMPLATE_ID``.
"""

import json
from functools import lru_cache
from typing import Annotated, Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from voc_common.constants import (
    PLAYSTORE_DEFAULT_PAGE_SIZE,
    PLAYSTORE_PAGE_SIZE_POLICY_LIMIT,
)

DEV_USER_HASH_SALT = "dev-only-salt-override-in-prod"
PRODUCTION_ENVIRONMENTS = frozenset({"prod", "production"})


class IngestionStorageLayout(BaseModel):
    """Prefijos de IaC/runtime, sin leer .env ni variables del host."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Almacenamiento (Cloud Storage Data Lake & Watermarks)
    gcs_watermark_prefix: str = "state/watermarks"
    gcs_raw_staging_prefix: str = "raw_staging"
    gcs_ingestion_state_prefix: str = "state/ingestion"
    gcs_ingestion_manifests_prefix: str = "state/ingestion/manifests"
    gcs_ingestion_ledgers_prefix: str = "state/ingestion/ledgers"
    gcs_processing_receipts_prefix: str = "state/ingestion/receipts"

    @field_validator(
        "gcs_watermark_prefix",
        "gcs_raw_staging_prefix",
        "gcs_ingestion_state_prefix",
        "gcs_ingestion_manifests_prefix",
        "gcs_ingestion_ledgers_prefix",
        "gcs_processing_receipts_prefix",
    )
    @classmethod
    def _relative_prefix(cls, value: str) -> str:
        if any(part in ("", ".", "..") for part in value.split("/")) or (
            value != value.strip() or ":" in value
        ):
            raise ValueError("GCS prefixes must be canonical relative paths")
        return value

    @model_validator(mode="after")
    def _storage_layout(self) -> Self:
        children = (
            self.gcs_ingestion_manifests_prefix,
            self.gcs_ingestion_ledgers_prefix,
            self.gcs_processing_receipts_prefix,
        )
        for prefix in children:
            if not prefix.startswith(self.gcs_ingestion_state_prefix + "/"):
                raise ValueError(
                    "metadata prefixes must be under ingestion state"
                )

        def overlaps(a: str, b: str) -> bool:
            return a == b or a.startswith(b + "/") or b.startswith(a + "/")

        for index, prefix in enumerate(children):
            if any(overlaps(prefix, other) for other in children[index + 1 :]):
                raise ValueError("manifest/ledger/receipt prefixes overlap")
        if overlaps(self.gcs_watermark_prefix, self.gcs_ingestion_state_prefix):
            raise ValueError(
                "watermark and ingestion metadata prefixes overlap"
            )
        for prefix in (
            self.gcs_watermark_prefix,
            self.gcs_ingestion_state_prefix,
        ):
            if any(
                overlaps(prefix, ephemeral)
                for ephemeral in (
                    self.gcs_raw_staging_prefix,
                    "temp_beam",
                )
            ):
                raise ValueError("durable state overlaps ephemeral lifecycle")
        return self


class IngestionExecutionConfig(BaseModel):
    """Perfil de ejecución puro, compartido por Settings y Pulumi."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    scraper_rotate_proxy_every_n_batches: int = Field(default=5, ge=1)
    scraper_page_size: int = Field(
        default=PLAYSTORE_DEFAULT_PAGE_SIZE,
        ge=1,
        le=PLAYSTORE_PAGE_SIZE_POLICY_LIMIT,
    )
    scraper_base_delay_sec: float = Field(default=1.5, ge=0.0)
    scraper_max_jitter_sec: float = Field(default=2.0, ge=0.0)
    scraper_max_retries: int = Field(default=5, ge=0)
    scraper_timeout_sec: float = Field(default=30.0, gt=0.0)

    # Presupuestos por ejecución, independientes del límite lógico de reseñas.
    ingestion_max_requests: int = Field(default=100, gt=0)
    ingestion_max_response_bytes: int = Field(default=20_000_000, gt=0)
    ingestion_max_runtime_sec: int = Field(default=780, gt=0)
    ingestion_container_timeout_sec: int = Field(default=900, gt=0)
    ingestion_checkpoint_margin_sec: int = Field(default=60, gt=0)
    ingestion_lease_duration_sec: int = Field(default=120, gt=0)
    ingestion_heartbeat_interval_sec: int = Field(default=30, gt=0)
    # Valores conservadores; no derivan de límites del origen.
    ingestion_max_pages: int = Field(default=100, gt=0)
    ingestion_max_recovery_requests: int = Field(default=10, ge=0)
    ingestion_recovery_max_anchors: int = Field(default=3, ge=0)
    ingestion_max_backoff_sec: float = Field(default=60.0, gt=0.0)
    ingestion_circuit_breaker_threshold: int = Field(default=3, gt=0)
    # Ventana de revisita del incremental: reduce riesgo, no prueba ediciones.
    ingestion_incremental_revisit_window_sec: int = Field(default=259_200, ge=0)
    # Bootstrap: ventana reciente explícita; no representa el histórico.
    ingestion_bootstrap_window_sec: int = Field(default=604_800, gt=0)
    # Rotación opcional por ejecución; nunca como reacción a un bloqueo.
    scraper_rotate_user_agent: bool = False

    @model_validator(mode="after")
    def _ingestion_limits(self) -> Self:
        if (
            self.ingestion_max_runtime_sec
            + self.ingestion_checkpoint_margin_sec
            > (self.ingestion_container_timeout_sec)
        ):
            raise ValueError("execution budget must leave checkpoint margin")
        if self.ingestion_checkpoint_margin_sec < self.scraper_timeout_sec:
            raise ValueError(
                "checkpoint margin must cover an in-flight request"
            )
        if (
            self.ingestion_heartbeat_interval_sec
            >= self.ingestion_lease_duration_sec
        ):
            raise ValueError("heartbeat must precede lease expiration")
        if self.ingestion_max_recovery_requests > self.ingestion_max_requests:
            raise ValueError("recovery budget cannot exceed request budget")
        if self.ingestion_max_backoff_sec >= self.ingestion_max_runtime_sec:
            raise ValueError("backoff must fit inside the execution budget")
        return self


class Settings(BaseSettings, IngestionStorageLayout, IngestionExecutionConfig):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        allow_inf_nan=False,
        frozen=False,
    )

    # Entorno y Proyecto GCP
    environment: str = "dev"
    free_tier_mode: bool = True
    gcp_project_id: str = "bbva-voc-analyzer-dev"
    gcp_region: str = "us-central1"

    gcs_raw_datalake_bucket: str = "voc-datalake-bbva-voc-analyzer-dev"

    # BigQuery (Trusted Data Source - TDS)
    bq_dataset_id: str = "bbva_voc_tds"
    bq_sanitized_tds_table: str = "sanitized_reviews_tds"
    bq_ingestion_runs_log_table: str = Field(
        default="ingestion_runs_log_v2", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"
    )

    # Cloud Pub/Sub
    pubsub_raw_reviews_topic: str = "voc-raw-reviews-topic"
    pubsub_raw_subscription: str = "voc-raw-reviews-sub"
    pubsub_alerts_topic: str = "voc-incident-alerts-topic"

    # Cloud DLP (Ethics by Design)
    dlp_inspect_template_id: str | None = None
    dlp_deidentify_template_id: str | None = None
    user_hash_salt: str = Field(default=DEV_USER_HASH_SALT, min_length=16)

    # Scraper Propio (batchexecute) y Anti-Throttling
    # NoDecode: acepta JSON (["a","b"]) o CSV (a,b) desde la variable de
    # entorno; una cadena vacía produce lista vacía.
    scraper_proxy_pool_urls: Annotated[list[str], NoDecode] = Field(
        default_factory=list
    )
    # Recursos v2: activar solo después de aprovisionar EPIC-2 (2.7–2.9).
    ingestion_v2_enabled: bool = False
    ingestion_history_job_name: str | None = Field(default=None, min_length=1)

    @field_validator(
        "dlp_inspect_template_id",
        "dlp_deidentify_template_id",
        "ingestion_history_job_name",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("scraper_proxy_pool_urls", mode="before")
    @classmethod
    def _parse_proxy_pool(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            return json.loads(stripped)
        return [url.strip() for url in stripped.split(",") if url.strip()]

    def require_ingestion_v2(self, *, historical: bool = False) -> None:
        """Preflight local; no comprueba existencia de recursos en GCP."""
        if not self.ingestion_v2_enabled:
            raise ValueError("ingestion v2 is not enabled")
        if historical and self.ingestion_history_job_name is None:
            raise ValueError(
                "historical ingestion requires the Pulumi Job output"
            )

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in PRODUCTION_ENVIRONMENTS

    @field_validator("user_hash_salt")
    @classmethod
    def _validate_salt(cls, value: str) -> str:
        if len(value.strip()) < 16:
            raise ValueError("USER_HASH_SALT requiere al menos 16 caracteres")
        return value

    @model_validator(mode="after")
    def _forbid_dev_salt_in_production(self) -> Self:
        if (
            self.is_production
            and self.user_hash_salt.strip() == DEV_USER_HASH_SALT
        ):
            raise ValueError(
                "USER_HASH_SALT debe sobreescribirse en producción; "
                "la sal de desarrollo no es válida."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
