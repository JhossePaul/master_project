"""Explicación guardada o calculada bajo pedido en ``voc-ml-online``."""

from datetime import datetime

from voc_common import ExplanationSource, ReviewExplanation

from api_backend.errors import ApiError, ErrorCode
from api_backend.online import OnlineClient
from api_backend.sections.explanations.repository import (
    ExplanationsRepository,
    matches,
)
from api_backend.sections.explanations.schemas import (
    Attribution,
    ExplanationOut,
)

CHANGED = "La reseña cambió desde la predicción; no se puede explicar"


def _out(e: ReviewExplanation) -> ExplanationOut:
    return ExplanationOut(
        text_key=e.text_key,
        model_version=e.model_version,
        method=e.method,
        source=e.source.value,
        computed_at=e.computed_at,
        attributions=[
            Attribution.model_validate(a.model_dump()) for a in e.attributions
        ],
    )


def get(
    repo: ExplanationsRepository, text_key: str, model_version: str | None
) -> ExplanationOut:
    found = repo.stored(text_key, model_version)
    if found is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No hay explicación guardada")
    return _out(found)


def compute(
    repo: ExplanationsRepository,
    online: OnlineClient,
    text_key: str,
    bank_id: str,
    id_resena: str,
    now: datetime,
) -> ExplanationOut:
    prediction = repo.prediction(bank_id, id_resena)
    if prediction is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No existe la reseña")
    if prediction.text_key != text_key:
        raise ApiError(ErrorCode.CONFLICT, CHANGED)
    text = repo.text(bank_id, id_resena, prediction.fecha)
    if text is None or not matches(text, text_key):
        raise ApiError(ErrorCode.CONFLICT, CHANGED)
    existing = repo.stored(text_key, prediction.model_version)
    if existing is not None and existing.method == "occlusion_v2":
        return _out(existing)  # ya existía para el modelo promovido
    result = online.explain(text, prediction.model_version)
    explanation = ReviewExplanation(
        text_key=text_key,
        model_version=prediction.model_version,
        method=result.method,  # type: ignore[arg-type]
        attributions=result.attributions,
        source=ExplanationSource.ON_DEMAND,
        computed_at=now,
    )
    repo.save(explanation)
    return _out(explanation)
