"""Configuración del servicio desde variables de entorno.

Usa los mismos nombres que el resto de las cargas de Cloud Run (``infra``):
``GCP_PROJECT_ID``, ``BQ_DATASET_ID``, ``GCS_RAW_DATALAKE_BUCKET``…
"""

from datetime import date
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
    # Job de reentrenamiento que lanza el monitor en modo auto.
    training_job: str = "voc-ml-training"
    # Job del re-scoring, que el entrenamiento lanza en modo auto.
    rescoring_job: str = "voc-ml-rescoring"
    # Tiempo máximo del kernel de entrenamiento (el Job tiene 4 h).
    training_kernel_timeout_sec: int = Field(default=10800, ge=60)
    # Imagen de ml-inference (la exige el registro de modelos de Vertex).
    serving_image: str | None = None
    # Plata reciente de cada reentrenamiento: textos posteriores a la plata
    # de los experimentos (su partición de entrenamiento termina antes del
    # 2026-04-01), etiquetados con el prompt de la plata y con tope de costo.
    recent_silver_texts: int = Field(default=20_000, ge=0)
    recent_silver_since: date = date(2026, 4, 1)
    recent_silver_max_usd: float = Field(default=2.0, ge=0)
    # Costo medido del prompt de la plata por 1 000 textos.
    recent_silver_usd_per_1000: float = Field(default=0.048, gt=0)

    @property
    def dataset(self) -> str:
        return f"{self.gcp_project_id}.{self.bq_dataset_id}"

    @property
    def tds_table(self) -> str:
        return f"{self.dataset}.{self.bq_sanitized_tds_table}"
