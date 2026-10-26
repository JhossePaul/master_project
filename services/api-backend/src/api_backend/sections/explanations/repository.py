"""Explicaciones guardadas y lo que hace falta para calcular una."""

# ruff: noqa: S608
# Los nombres de tablas salen de ``qualified`` (lista cerrada); los valores
# viajan siempre como parámetros.

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from voc_common import ReviewExplanation
from voc_common.text_utils import text_key

from api_backend.bq.names import qualified
from api_backend.bq.reader import BigQueryReader, Param
from api_backend.bq.writer import BigQueryWriter
from api_backend.settings import ApiSettings


@dataclass(frozen=True)
class CurrentPrediction:
    model_version: str
    text_key: str
    fecha: datetime


class ExplanationsRepository(Protocol):
    def stored(
        self, text_key: str, model_version: str | None
    ) -> ReviewExplanation | None:
        """La de ``occlusion_v2`` si existe y, si no, la ``occlusion_v1``."""

    def prediction(
        self, bank_id: str, id_resena: str
    ) -> CurrentPrediction | None: ...

    def text(
        self, bank_id: str, id_resena: str, fecha: datetime
    ) -> str | None: ...

    def save(self, explanation: ReviewExplanation) -> bool: ...


class BigQueryExplanationsRepository:
    def __init__(
        self,
        reader: BigQueryReader,
        writer: BigQueryWriter,
        settings: ApiSettings,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._project = settings.gcp_project_id
        self._dataset = settings.bq_dataset_id

    def _table(self, name: str) -> str:
        return qualified(name, self._project, self._dataset)

    def stored(
        self, text_key: str, model_version: str | None
    ) -> ReviewExplanation | None:
        params = [Param("key", "STRING", text_key)]
        where = "text_key = @key"
        if model_version is not None:
            where += " AND model_version = @version"
            params.append(Param("version", "STRING", model_version))
        rows = self._reader.rows(
            "SELECT text_key, model_version, method, "  # nosec B608
            "TO_JSON_STRING(attributions) AS attributions, source, "
            f"computed_at FROM {self._table('review_explanations')} "
            f"WHERE {where} "
            "ORDER BY method = 'occlusion_v2' DESC, computed_at DESC LIMIT 1",
            params,
            name="explanation_stored",
        )
        if not rows:
            return None
        row = dict(rows[0])
        row["attributions"] = _attributions(str(row["attributions"]))
        return ReviewExplanation.model_validate(row)

    def prediction(
        self, bank_id: str, id_resena: str
    ) -> CurrentPrediction | None:
        rows = self._reader.rows(
            "SELECT model_version, text_key, fecha FROM "  # nosec B608
            f"{self._table('review_predictions_current')} "
            "WHERE bank_id = @bank AND id_resena = @id "
            "AND model_version IS NOT NULL LIMIT 1",
            [
                Param("bank", "STRING", bank_id),
                Param("id", "STRING", id_resena),
            ],
            name="explanation_prediction",
        )
        if not rows:
            return None
        r = rows[0]
        return CurrentPrediction(
            str(r["model_version"]),
            str(r["text_key"]),
            r["fecha"],  # type: ignore[arg-type]
        )

    def text(self, bank_id: str, id_resena: str, fecha: datetime) -> str | None:
        rows = self._reader.rows(
            "SELECT texto_sanitizado FROM "  # nosec B608
            f"{self._table('sanitized_reviews_tds')} "
            "WHERE fecha >= @fecha AND fecha < TIMESTAMP_ADD(@fecha, "
            "INTERVAL 1 DAY) AND bank_id = @bank AND id_resena = @id LIMIT 1",
            [
                Param("fecha", "TIMESTAMP", fecha),
                Param("bank", "STRING", bank_id),
                Param("id", "STRING", id_resena),
            ],
            name="explanation_text",
        )
        return str(rows[0]["texto_sanitizado"]) if rows else None

    def save(self, explanation: ReviewExplanation) -> bool:
        return self._writer.insert(
            "review_explanations",
            explanation,
            key=["text_key", "model_version", "method"],
        )


def _attributions(raw: str) -> list[dict[str, object]]:
    import json

    return list(json.loads(raw))


class InMemoryExplanationsRepository:
    """Doble de pruebas y de ``PORTAL_DATA=fixtures``."""

    def __init__(
        self,
        predictions: dict[tuple[str, str], CurrentPrediction] | None = None,
        texts: dict[tuple[str, str], str] | None = None,
        stored: list[ReviewExplanation] | None = None,
    ) -> None:
        self.predictions = dict(predictions or {})
        self.texts = dict(texts or {})
        self.explanations = list(stored or [])
        self.saved: list[ReviewExplanation] = []

    def stored(
        self, text_key: str, model_version: str | None
    ) -> ReviewExplanation | None:
        found = [
            e
            for e in self.explanations
            if e.text_key == text_key
            and (model_version is None or e.model_version == model_version)
        ]
        found.sort(
            key=lambda e: (e.method == "occlusion_v2", e.computed_at),
            reverse=True,
        )
        return found[0] if found else None

    def prediction(
        self, bank_id: str, id_resena: str
    ) -> CurrentPrediction | None:
        return self.predictions.get((bank_id, id_resena))

    def text(self, bank_id: str, id_resena: str, fecha: datetime) -> str | None:
        return self.texts.get((bank_id, id_resena))

    def save(self, explanation: ReviewExplanation) -> bool:
        key = (
            explanation.text_key,
            explanation.model_version,
            explanation.method,
        )
        if any(
            (e.text_key, e.model_version, e.method) == key
            for e in self.explanations
        ):
            return False
        self.explanations.append(explanation)
        self.saved.append(explanation)
        return True


def matches(text: str, key: str) -> bool:
    return text_key(text) == key
