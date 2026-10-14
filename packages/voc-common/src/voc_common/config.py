"""Configuración centralizada de BBVA VoC Analyzer.

Los nombres de los campos coinciden (sin distinguir mayúsculas) con las
variables de entorno inyectadas por Pulumi en Cloud Run (Épica 2), p. ej.
``GCP_PROJECT_ID``, ``SCRAPER_PAGE_SIZE`` o ``DLP_INSPECT_TEMPLATE_ID``.
"""

import json
from functools import lru_cache
from typing import Annotated, Any, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from voc_common.constants import PLAYSTORE_MAX_PAGE_SIZE

DEV_USER_HASH_SALT = "dev-only-salt-override-in-prod"
PRODUCTION_ENVIRONMENTS = frozenset({"prod", "production"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Entorno y Proyecto GCP
    environment: str = "dev"
    free_tier_mode: bool = True
    gcp_project_id: str = "bbva-voc-analyzer-dev"
    gcp_region: str = "us-central1"

    # Almacenamiento (Cloud Storage Data Lake & Watermarks)
    gcs_raw_datalake_bucket: str = "voc-datalake-bbva-voc-analyzer-dev"
    gcs_watermark_prefix: str = "state/watermarks"
    gcs_raw_staging_prefix: str = "raw_staging"

    # BigQuery (Trusted Data Source - TDS)
    bq_dataset_id: str = "bbva_voc_tds"
    bq_sanitized_tds_table: str = "sanitized_reviews_tds"
    bq_predictions_table: str = "delora_predictions"
    bq_watermarks_log_table: str = "ingestion_watermarks_log"
    bq_hitl_audit_table: str = "hitl_triage_audit_log"

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
    scraper_rotate_proxy_every_n_batches: int = Field(default=5, ge=1)
    scraper_page_size: int = Field(
        default=PLAYSTORE_MAX_PAGE_SIZE, ge=1, le=PLAYSTORE_MAX_PAGE_SIZE
    )
    scraper_base_delay_sec: float = Field(default=1.5, ge=0.0)
    scraper_max_jitter_sec: float = Field(default=2.0, ge=0.0)
    scraper_max_retries: int = Field(default=5, ge=0)
    scraper_timeout_sec: float = Field(default=30.0, gt=0.0)

    # Parámetros MLOps y HITL
    hitl_entropy_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    enable_dedicated_vertex_endpoints: bool = False

    @field_validator(
        "dlp_inspect_template_id", "dlp_deidentify_template_id", mode="before"
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

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in PRODUCTION_ENVIRONMENTS

    @model_validator(mode="after")
    def _forbid_dev_salt_in_production(self) -> Self:
        if self.is_production and self.user_hash_salt == DEV_USER_HASH_SALT:
            raise ValueError(
                "USER_HASH_SALT debe sobreescribirse en producción; "
                "la sal de desarrollo no es válida."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
