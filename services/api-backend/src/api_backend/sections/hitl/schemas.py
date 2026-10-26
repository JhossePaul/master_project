"""Modelos de la API del HITL.

Ninguno lleva banco, estrellas, fecha, motivo del caso ni explicación: así el
revisor no distingue un caso de la muestra de uno de baja confianza.
"""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from voc_common import HitlTask, ReviewFlag


class SentimentProposal(BaseModel):
    label: Literal["NEG", "NEU", "POS"]
    p_neg: float
    p_neu: float
    p_pos: float


class HitlCase(BaseModel):
    item_id: str
    task: Literal["sentiment"]
    text: str  # texto_sanitizado del TDS
    display_mode: Literal["blind", "assisted"]
    # Solo si ``assisted``: nunca en la muestra de monitoreo ni en el oro.
    proposal: SentimentProposal | None
    guideline_version: str
    opened_at: datetime  # el ``at`` del evento in_review
    review_round: Literal[1, 2]


class NextIn(BaseModel):
    task: Literal["sentiment"]
    # Casos que el revisor ya tiene abiertos (``item_id`` del portal): al
    # precargar el siguiente no se le vuelve a dar el que está revisando.
    exclude: list[str] = Field(default_factory=list, max_length=10)


class SentimentReviewIn(BaseModel):
    review_id: UUID  # lo genera el portal al abrir el caso (idempotencia)
    # Nulo solo con la marca ``no_evaluable``.
    validated_label: Literal["NEG", "NEU", "POS"] | None
    flags: list[ReviewFlag]
    comment: str | None = Field(default=None, max_length=500)
    guideline_version: str  # la que se mostró
    # ``False`` si el portal ya tiene el siguiente caso precargado: guardar no
    # toma otro.
    claim_next: bool = True

    @model_validator(mode="after")
    def _label_and_flags(self) -> Self:
        if len(set(self.flags)) != len(self.flags):
            raise ValueError("flags must not repeat")
        if (self.validated_label is None) != (
            ReviewFlag.NO_EVALUABLE in self.flags
        ):
            raise ValueError(
                "validated_label is null if and only if no_evaluable"
            )
        return self


class ReviewOut(BaseModel):
    review_id: str
    # El siguiente caso ya tomado, para no esperar otra ronda; ``None`` si no
    # quedan o no se pudo tomar (el portal pide ``next``).
    next: HitlCase | None


class TaskSummary(BaseModel):
    task: HitlTask
    pending: int
    mine_this_week: int
    team_this_week: int
    median_seconds: float | None  # 30 días, todo el equipo
    monitor_done: int
    monitor_target: int


class HitlSummary(BaseModel):
    tasks: list[TaskSummary]


class GuidelineOut(BaseModel):
    task: HitlTask
    guideline_version: str
    valid_from: datetime
    content: str  # Markdown
