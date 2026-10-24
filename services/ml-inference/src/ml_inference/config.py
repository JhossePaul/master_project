"""Configuración del servicio desde variables de entorno.

Usa los mismos nombres que el resto de las cargas de Cloud Run (``infra``):
``GCP_PROJECT_ID``, ``BQ_DATASET_ID``, ``GCS_RAW_DATALAKE_BUCKET``…
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class InferenceSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    gcp_project_id: str = Field(min_length=1)
    gcp_region: str = "us-central1"
    bq_dataset_id: str = "bbva_voc_tds"
    bq_sanitized_tds_table: str = "sanitized_reviews_tds"
    gcs_raw_datalake_bucket: str = Field(min_length=1)
    # Pesos de RoBERTuito, modelo de tópicos y MiniLM (D11).
    ml_artifacts_prefix: str = "ml_artifacts"
    artifacts_dir: Path = Path("/tmp/ml_artifacts")  # noqa: S108  # nosec B108
    # Tope de reseñas por corrida del delta; lo que sobra entra al siguiente.
    max_reviews_per_run: int = Field(default=20_000, ge=1)
    sentiment_batch_size: int = Field(default=64, ge=1)
    aspects_batch_size: int = Field(default=100, ge=1)
    gemini_model: str = "gemini-3.6-flash"
    gemini_location: str = "global"
    torch_threads: int = Field(default=1, ge=1)
    # Tópico de las alertas de deriva (nombre heredado de EPIC-2).
    drift_topic: str = "voc-incident-alerts-topic"
    # Avisos de model_quality (D15).
    quality_topic: str = "voc-model-quality-topic"

    @property
    def dataset(self) -> str:
        return f"{self.gcp_project_id}.{self.bq_dataset_id}"

    @property
    def tds_table(self) -> str:
        return f"{self.dataset}.{self.bq_sanitized_tds_table}"
