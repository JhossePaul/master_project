from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from api_backend.sections.landing.schemas import Estimate

BankId = Literal["BBVA", "AZTECA", "SANTANDER", "NUBANK", "BANORTE"]
BANK_IDS: tuple[BankId, ...] = (
    "BBVA",
    "AZTECA",
    "SANTANDER",
    "NUBANK",
    "BANORTE",
)
StarsClass = Literal["NEG", "NEU", "POS"]
TextClass = Literal["NEG", "NEU", "POS"]


class CardValues(BaseModel):
    period: str
    neg: Estimate | None
    gap_estrellas: Estimate | None
    quejas_4_5: Estimate | None


class BankCard(BaseModel):
    bank_id: str
    period: str | None
    neg: Estimate | None
    gap_estrellas: Estimate | None
    quejas_4_5: Estimate | None
    previous_year: CardValues | None
    model_version: str | None
    gold_version: str | None
    open_alerts: int


class DailyPoint(BaseModel):
    bank_id: str
    dia: date
    filas: int
    predichas: int
    neg: int
    neu: int
    pos: int
    no_predichas: int
    gap_crudo: float | None
    texto_peor: int
    texto_mejor: int
    neg_4_5: int


class DailyTheme(BaseModel):
    codigo: str
    nombre: str | None
    filas: int
    participacion: float
    habitual: float | None


class DailyTopics(BaseModel):
    bank_id: str
    dia: date
    n_neg: int
    familias: list[DailyTheme]
    topicos: list[DailyTheme]
    aspects_prompt_version: str | None
    topic_model_version: str | None


class MonthlyKpi(BaseModel):
    bank_id: str
    period: str
    metric: str
    ppi: Estimate | None
    raw: Estimate | None
    model_version: str


class FamilyMonth(BaseModel):
    bank_id: str
    period: str
    family: str
    neg_count: int
    share: float
    z: float | None
    threshold: float | None
    alert: bool | None


class PromptChange(BaseModel):
    prompt_version: str
    first_labeled_at: datetime


class FamiliesResponse(BaseModel):
    series: list[FamilyMonth]
    prompt_changes: list[PromptChange]


class TopicMonth(BaseModel):
    bank_id: str
    period: str
    topic_id: int
    nombre: str
    audience: str
    families: list[str]
    filas: int
    share: float
    topic_model_version: str


class MatrixCell(BaseModel):
    bank_id: str
    period: str
    stars_class: StarsClass
    text_class: TextClass
    ppi: Estimate | None
    raw: Estimate | None


class VersionRow(BaseModel):
    release: str
    first_seen: date
    last_seen: date
    filas: int
    neg: int
    neg_share: float
    neg_ci_low: float
    neg_ci_high: float
    u_share: float
    families: dict[str, float]


class VersionsResponse(BaseModel):
    bank_id: str
    rows: list[VersionRow]
    coverage: float
    median_neg_share: float | None
    median_u_share: float | None


class ModelChange(BaseModel):
    model_version: str
    promoted_at: datetime
