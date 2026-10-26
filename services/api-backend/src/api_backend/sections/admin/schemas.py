"""Modelos de la API de administración (rol administrador).

Nada lleva texto de reseñas: las políticas son parámetros, la curva son
agregados y los ítems del oro son identificadores con la etiqueta validada.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from voc_common import (
    DriftPolicy,
    DriftPolicyTemplate,
    DriftThresholds,
    GoldVersion,
    HitlBoost,
    HitlCoverageCurve,
    ReviewFlag,
    RiskPolicy,
)
from voc_common.policies import CoveragePoint

MIN_REASON = 10
CONFIRM_WORD = "CONFIRMAR"


# -- Apetito de riesgo -------------------------------------------------------


class RiskPolicyResponse(BaseModel):
    current: RiskPolicy
    history: list[RiskPolicy]  # ordenada por ``valid_from``


class CoverageCurveResponse(BaseModel):
    curve: HitlCoverageCurve
    # Punto de la curva para la cobertura objetivo vigente.
    current_point: CoveragePoint | None
    # Tiempo medido en ``hitl_reviews`` de sentimiento de la ventana.
    median_seconds: float | None
    timed_n: int
    window_days: int
    hitl_boosts_active: list[HitlBoost]


class RiskChangeIn(BaseModel):
    base_version: str
    changes: dict[str, Any]


class RiskSaveIn(RiskChangeIn):
    reason: str = Field(min_length=MIN_REASON)
    confirm_word: str | None = None


class FieldDiff(BaseModel):
    field: str
    before: Any
    after: Any


class RiskPreview(BaseModel):
    # Nula si los cambios no pasan la validación (``errors`` dice por qué).
    proposed: RiskPolicy | None
    diff: list[FieldDiff]
    large_change: bool
    warnings: list[str]
    errors: list[str]


# -- Deriva ------------------------------------------------------------------


class DriftPolicyResponse(BaseModel):
    current: DriftPolicy
    template: DriftPolicyTemplate
    history: list[DriftPolicy]
    diff_vs_template: list[FieldDiff]


class DriftRatesIn(BaseModel):
    bank: str
    thresholds: DriftThresholds


class SeriesRate(BaseModel):
    series: str
    months: int
    proposed_alerts: int
    proposed_per_year: float
    current_alerts: int
    current_per_year: float
    # Meses de alerta al año del análisis de escala; nulo si no se midió.
    reference: float | None


class DriftRatesResponse(BaseModel):
    bank: str
    series: list[SeriesRate]


class DriftSaveIn(BaseModel):
    bank: str
    base_version: str
    # ``thresholds`` y los parámetros de entrada (línea base, filas mínimas…).
    changes: dict[str, Any]
    reason: str = Field(min_length=MIN_REASON)


# -- Oro ---------------------------------------------------------------------


class GoldCriteria(BaseModel):
    reason: Literal["monitor_sample"] = "monitor_sample"
    submitted_from: date
    submitted_to: date
    guideline_version: str  # una sola guía por versión del oro
    review_round: Literal[1] = 1
    exclude_flags: list[ReviewFlag] = [ReviewFlag.NO_EVALUABLE]


class GoldCount(BaseModel):
    key: str
    n: int


class GoldPreview(BaseModel):
    total: int
    by_bank: list[GoldCount]
    by_label: list[GoldCount]


class GoldCreateIn(BaseModel):
    criteria: GoldCriteria
    reason: str = Field(min_length=MIN_REASON)


class GoldVersionOut(BaseModel):
    version: GoldVersion
    reason: str | None = None


class GoldItem(BaseModel):
    item_id: str
    id_resena: str
    validated_label: str | None
    submitted_at: datetime
    reviewer: str  # primeros 8 caracteres del hash


class GoldItemsResponse(BaseModel):
    gold_version: str
    cutoff_at: datetime
    items: list[GoldItem]
