"""Modelos de la API de MLOps y AIOps.

Ninguno lleva texto de reseñas: son series de señales, versiones de modelos,
corridas y conteos. Los actores salen como hash corto.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field
from voc_common import (
    ModelStatus,
    PromotionVerdict,
    QualitySignal,
    QualityStatus,
    RunEnvironment,
    RunKind,
    RunStatus,
)

MIN_REASON = 10
MAX_REASON = 500
FORCE_WORD = "FORZAR"
# Memoria del Job del delta (infra): la línea de la gráfica de corridas.
DELTA_MEMORY_MIB = 4096


class Action(StrEnum):
    RETRAIN = "retrain"
    RESCORE = "rescore"
    PROMOTE = "promote"
    ROLLBACK = "rollback"
    TOPICS_REFIT = "topics_refit"


# -- Calidad del modelo ------------------------------------------------------


class QualityPoint(BaseModel):
    period: str
    value: float
    ci_low: float | None
    ci_high: float | None
    n: int
    threshold: float | None
    status: QualityStatus
    model_version: str | None
    llm_model: str | None
    prompt_version: str | None
    computed_at: datetime


class QualitySeries(BaseModel):
    signal: QualitySignal
    # Del más viejo al más reciente; vacía si el monitor aún no la midió.
    points: list[QualityPoint]


class QualityResponse(BaseModel):
    signals: list[QualitySeries]


# -- Deriva ------------------------------------------------------------------


class DriftCell(BaseModel):
    bank_id: str
    period: str  # "2026-09"
    value: float
    baseline: float | None
    z: float | None
    psi: float | None
    threshold: float | None
    alert: bool


class DriftResponse(BaseModel):
    metric: str
    # Series con umbral que existen en ``drift_metrics`` (sin las de tópicos).
    series: list[str]
    banks: list[str]
    cells: list[DriftCell]


class ContextSeries(BaseModel):
    metric: str
    cells: list[DriftCell]


class TopicsContextResponse(BaseModel):
    """Las series de tópicos, sin umbral, junto a las familias y la marca u."""

    topics: list[ContextSeries]
    families: list[ContextSeries]


# -- Registro de modelos -----------------------------------------------------


class StatusStep(BaseModel):
    status: ModelStatus
    at: datetime
    actor: str | None  # hash corto
    reason: str | None


class PromotionCheckOut(BaseModel):
    candidate_version: str
    current_version: str
    gold_version: str
    n: int
    kappa_diff: float
    kappa_ci_low: float
    kappa_ci_high: float
    macro_f1_diff: float
    macro_f1_ci_low: float
    macro_f1_ci_high: float
    verdict: PromotionVerdict
    computed_at: datetime


class ActionState(BaseModel):
    action: Action
    enabled: bool
    # Por qué está deshabilitada (o un aviso cuando sí se puede).
    reason: str | None
    # Fecha del siguiente re-ajuste programado (``scheduled``).
    next_date: date | None = None


class ModelOut(BaseModel):
    model_version: str
    status: ModelStatus
    current: bool
    ever_promoted: bool
    base_checkpoint: str
    training_data: str
    training_data_hash: str | None
    calibration_version: str
    calibration_t: float
    kappa_dev: float | None
    ece_dev: float | None
    aurc_dev: float | None
    license: str
    history: list[StatusStep]
    check: PromotionCheckOut | None
    # Acciones de la versión: ``rescore``, ``promote`` y ``rollback``.
    actions: list[ActionState]


class ModelsResponse(BaseModel):
    models: list[ModelOut]
    current_version: str | None
    # Acciones que no son de una versión: ``retrain`` y ``topics_refit``.
    actions: list[ActionState]
    force_word: str = FORCE_WORD


class ReliabilityBin(BaseModel):
    low: float
    high: float
    n: int
    weight: float
    confidence: float
    accuracy: float


class CalibrationOut(BaseModel):
    model_version: str
    source: Literal["manifest", "docs"]
    source_label: str
    temperature: float | None
    ece_raw: float | None
    ece_calibrated: float | None
    raw: list[ReliabilityBin]
    calibrated: list[ReliabilityBin]


# -- Pipeline ----------------------------------------------------------------


class RunOut(BaseModel):
    run_id: str
    kind: RunKind
    environment: RunEnvironment
    status: RunStatus
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: float | None
    reviews: int
    texts: int
    cost_usd: float | None
    peak_memory_mib: int | None
    model_version: str | None
    topic_model_version: str | None
    actor: str | None  # hash corto
    reason: str | None


class Freshness(BaseModel):
    last_ingestion_at: datetime | None
    last_delta_at: datetime | None
    # Se infiere de ``kpi_estimates``: el monitor no escribe en inference_runs.
    last_monitor_at: datetime | None


class RunsResponse(BaseModel):
    runs: list[RunOut]
    memory_limit_mib: int = DELTA_MEMORY_MIB
    freshness: Freshness


class IngestionRunOut(BaseModel):
    run_id: str
    bank_id: str
    mode: str
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    status: str
    reviews_extracted: int | None
    reviews_published: int | None
    reviews_discarded: int | None


class EligibilityRow(BaseModel):
    bank_id: str
    period: str
    code: str
    n: int


class ActionIn(BaseModel):
    reason: str = Field(min_length=MIN_REASON, max_length=MAX_REASON)
    model_version: str | None = None
    confirm_word: str | None = None


class ActionOut(BaseModel):
    action: Action
    job: str
    operation: str
