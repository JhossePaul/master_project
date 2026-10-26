"""Explicaciones sintéticas: las reseñas del Explorador no traen ninguna."""

from datetime import UTC, datetime

from api_backend.sections.explanations.repository import (
    CurrentPrediction,
    InMemoryExplanationsRepository,
)
from api_backend.sections.reviews.sample import (
    MODEL,
)
from api_backend.sections.reviews.sample import (
    sample_repository as reviews,
)


def sample_repository() -> InMemoryExplanationsRepository:
    predictions: dict[tuple[str, str], CurrentPrediction] = {}
    texts: dict[tuple[str, str], str] = {}
    for item in reviews().reviews:
        row = item.row
        key = (row.bank_id, row.id_resena)
        predictions[key] = CurrentPrediction(
            MODEL,
            row.text_key,
            datetime(
                row.fecha.year, row.fecha.month, row.fecha.day, tzinfo=UTC
            ),
        )
        texts[key] = row.text
    return InMemoryExplanationsRepository(predictions, texts)
