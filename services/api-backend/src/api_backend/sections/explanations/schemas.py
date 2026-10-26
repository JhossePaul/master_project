from datetime import datetime

from pydantic import BaseModel


class Attribution(BaseModel):
    """Posiciones en ``texto_sanitizado``; sin copiar texto."""

    start: int
    end: int
    # ``occlusion_v1``: cuánto sostiene la palabra la clase predicha.
    weight: float | None = None
    # ``occlusion_v2``: cambio de cada probabilidad calibrada al quitarla.
    d_neg: float | None = None
    d_neu: float | None = None
    d_pos: float | None = None


class ExplanationOut(BaseModel):
    text_key: str
    model_version: str
    method: str
    source: str
    computed_at: datetime
    attributions: list[Attribution]


class ExplainIn(BaseModel):
    bank_id: str
    id_resena: str
