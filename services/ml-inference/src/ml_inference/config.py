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
    # Pesos de RoBERTuito, modelo de tópicos y MiniLM.
    ml_artifacts_prefix: str = "ml_artifacts"
    artifacts_dir: Path = Path("/tmp/ml_artifacts")  # noqa: S108  # nosec B108
    # Tope de reseñas por corrida del delta; lo que sobra entra al siguiente.
    max_reviews_per_run: int = Field(default=20_000, ge=1)
    sentiment_batch_size: int = Field(default=64, ge=1)
    aspects_batch_size: int = Field(default=100, ge=1)
    gemini_model: str = "gemini-3.6-flash"
    gemini_location: str = "global"
    # Costo medido de Gemini por 1 000 textos en el backfill de los
    # experimentos ($60.61 por 659 316), para estimar aspects-backfill.
    gemini_usd_per_1000: float = Field(default=0.092, gt=0)
    torch_threads: int = Field(default=1, ge=1)
    # Tópico de las alertas de deriva (conserva su nombre original).
    drift_topic: str = "voc-incident-alerts-topic"
    # Avisos de model_quality, que llegan por correo.
    quality_topic: str = "voc-model-quality-topic"
    # Tiempo máximo del kernel de Kaggle del re-scoring (el Job tiene 3 h).
    rescore_kernel_timeout_sec: int = Field(default=9000, ge=60)
    # Job que re-asigna el histórico al activarse una versión de tópicos.
    topics_backfill_job: str = "voc-ml-topics-backfill"

    @property
    def dataset(self) -> str:
        return f"{self.gcp_project_id}.{self.bq_dataset_id}"

    @property
    def tds_table(self) -> str:
        return f"{self.dataset}.{self.bq_sanitized_tds_table}"
