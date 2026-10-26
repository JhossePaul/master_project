from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel
from voc_common import RunKind, RunStatus


class RunSummary(BaseModel):
    run_id: str
    kind: RunKind
    status: RunStatus
    started_at: datetime
    ended_at: datetime | None
    model_version: str | None


class Freshness(BaseModel):
    last_ingestion_at: datetime | None
    last_delta: RunSummary | None
    last_monitor_at: datetime | None
    data_until: date | None


class Estimate(BaseModel):
    estimate: float
    ci_low: float | None
    ci_high: float | None
    method: Literal["ppi", "raw"]
    n_gold: int | None
    n_unlabeled: int | None


class BankHeadline(BaseModel):
    bank_id: str
    period: str
    neg: Estimate
    gap_estrellas: Estimate
    model_version: str
    gold_version: str | None


class LandingResponse(BaseModel):
    freshness: Freshness
    open_alerts: dict[str, int]
    banks: list[BankHeadline]
    hitl_pending: int | None
