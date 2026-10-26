"""Modelos del Explorador de reseñas (rol analista)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from api_backend.sections.kpis.schemas import BankId

SentimentValue = Literal["NEG", "NEU", "POS", "NO_PREDICTED"]
SortKey = Literal["fecha_desc", "confidence_asc", "estrellas_asc"]
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50
MAX_K = 50


class TopicRef(BaseModel):
    topic_id: int
    name: str | None


class ReviewRow(BaseModel):
    id_resena: str
    bank_id: str
    text_key: str
    fecha: date
    version_app: str | None
    estrellas: int
    text: str  # texto_sanitizado; vacío si la reseña cambió desde la predicción
    sentiment: str
    p_neg: float | None
    p_neu: float | None
    p_pos: float | None
    confidence: float | None
    model_version: str | None
    families: list[str]
    flag_update: bool | None
    flag_security: bool | None
    topics: list[TopicRef]
    hitl_reviewed: bool


class WindowApplied(BaseModel):
    date_from: date
    date_to: date
    # La ventana por defecto recortó el rango pedido.
    clipped: bool
    months: int


class FacetCount(BaseModel):
    key: str
    n: int
    label: str | None = None


class Facets(BaseModel):
    """Solo agregados: ningún campo trae texto de reseñas."""

    total: int
    by_bank: list[FacetCount]
    by_month: list[FacetCount]
    by_sentiment: list[FacetCount]
    by_stars: list[FacetCount]
    by_family: list[FacetCount]
    by_flag_update: list[FacetCount]
    by_flag_security: list[FacetCount]
    by_topic: list[FacetCount]
    by_hitl: list[FacetCount]
    window_applied: WindowApplied


class ReviewPage(BaseModel):
    rows: list[ReviewRow]
    total: int
    page: int
    page_size: int
    window_applied: WindowApplied


class HitlReviewRef(BaseModel):
    """Lo que se ve de una revisión humana: nunca quién la hizo."""

    outcome: str
    validated_label: str | None
    review_round: int
    submitted_at: datetime


class ExplanationRef(BaseModel):
    method: str
    model_version: str
    source: str


class ReviewDetail(BaseModel):
    row: ReviewRow
    aspects_prompt_version: str | None
    hitl_reviews: list[HitlReviewRef]
    explanation: ExplanationRef | None


class SearchIn(BaseModel):
    query: str = Field(min_length=3, max_length=300)
    banks: list[BankId] | None = None
    months: int | None = Field(default=None, ge=1)
    k: int = Field(default=10, ge=1, le=MAX_K)


class SearchHit(BaseModel):
    text_key: str
    bank_id: str
    distance: float  # coseno: 0 es idéntico
    n_reviews: int  # reseñas con ese texto en la ventana
    example: ReviewRow  # la reseña más reciente con ese texto


class SearchResponse(BaseModel):
    hits: list[SearchHit]
    embedding_model: str
    months_searched: int
    bytes_billed: int
