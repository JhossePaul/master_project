"""Modelos de la API de alertas de deriva.

Ninguno lleva texto de reseñas: solo cifras de series, estados y las notas de
los analistas (ya sanitizadas). ``GET /alerts/summary`` no trae ni las notas.
"""

from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator
from voc_common import AlertStatus, BoostEndReason

MIN_NOTE = 10
MAX_NOTE = 500
MAX_TICKET = 100


class BoostOut(BaseModel):
    """Subida de revisión que disparó la alerta."""

    boost_id: str
    active: bool
    coverage: float
    starts_at: datetime
    ends_at: datetime
    ended_reason: BoostEndReason | None


class AlertRow(BaseModel):
    alert_id: str
    bank_id: str
    period: str  # "2026-09"
    series: str
    value: float
    threshold: float
    status: AlertStatus
    status_at: datetime | None
    drift_policy_version: str
    created_at: datetime
    boost: BoostOut | None


class AlertEventOut(BaseModel):
    event_id: str
    status: AlertStatus
    at: datetime
    # Primeros caracteres del hash; ``None`` es el monitor.
    actor: str | None
    note: str | None
    ticket: str | None


class SeriesPoint(BaseModel):
    period: str
    value: float
    baseline: float | None
    z: float | None
    psi: float | None
    threshold: float | None
    alert: bool


class ExplorerHint(BaseModel):
    """Banco y mes de la alerta, para abrir el Explorador."""

    bank_id: str
    start: date
    end: date


class AlertDetail(BaseModel):
    alert: AlertRow
    events: list[AlertEventOut]
    series: list[SeriesPoint]  # 24 meses hasta el de la alerta
    explorer: ExplorerHint


class AlertEventIn(BaseModel):
    event_id: UUID  # lo genera el portal al abrir el diálogo (idempotencia)
    status: AlertStatus
    note: str = Field(max_length=MAX_NOTE)
    ticket: str | None = Field(default=None, max_length=MAX_TICKET)

    @field_validator("note", "ticket", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _clean(self) -> Self:
        if len(self.note) < MIN_NOTE:
            raise ValueError(f"note needs at least {MIN_NOTE} characters")
        if self.ticket == "":
            object.__setattr__(self, "ticket", None)
        return self


class AlertSummary(BaseModel):
    open_by_bank: dict[str, int]
