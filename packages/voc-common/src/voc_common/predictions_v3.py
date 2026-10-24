"""Salidas del modelo v3: sentimiento, familias, embeddings y tópicos.

Una clase por tabla de ``bbva_voc_tds`` (contrato
``docs/contracts/analytics_outputs_v3.md``). Las tablas son de solo inserción:
el *re-scoring* agrega filas con otra versión y las vistas toman la vigente.
Ninguna copia texto de reseñas; lo leen del TDS por ``id_resena``.
"""

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from voc_common._analytics_base import (
    EMBEDDING_DIMENSIONS,
    PROBABILITY_TOLERANCE,
    Counter,
    Digest,
    MonthDate,
    NonEmpty,
    Probability,
    StarRating,
    UtcDatetime,
    _AnalyticsRecord,
    require_together,
)
from voc_common.analytics_codes import (
    AspectFamily,
    EligibilityCode,
    LabelSource,
    SentimentValue,
    TopicAudience,
)

# BERTopic asigna -1 a los segmentos que no caen en ningún tópico.
TopicId = int


def _unique_families(families: list[AspectFamily]) -> None:
    if len(set(families)) != len(families):
        raise ValueError("families must not repeat")


class ReviewPrediction(_AnalyticsRecord):
    """Fila de ``review_predictions``: una reseña × versión de modelo."""

    id_resena: NonEmpty
    bank_id: NonEmpty
    text_key: Digest
    fecha: UtcDatetime
    version_app: str | None
    estrellas: StarRating
    # Palabras de ``texto_limpio`` (``count_words`` de las reglas v1).
    palabras: Counter
    eligibility_rules_version: Literal["eligibility_rules_v1"]
    # Nulo solo si las reglas todavía no se evaluaron.
    eligibility_code: EligibilityCode | None
    label_source: LabelSource
    # Nulo solo si las reglas todavía no se evaluaron.
    sentiment: SentimentValue | None
    p_neg: Probability | None = None
    p_neu: Probability | None = None
    p_pos: Probability | None = None
    confidence: Probability | None = None
    model_version: NonEmpty | None = None
    calibration_version: NonEmpty | None = None
    risk_policy_version: NonEmpty | None = None
    hitl_boost_id: NonEmpty | None = None
    requires_hitl: bool
    run_id: NonEmpty
    predicted_at: UtcDatetime

    @model_validator(mode="after")
    def _schema_rules(self) -> Self:
        self._check_eligibility()
        self._check_probabilities()
        if self.requires_hitl and self.label_source is not LabelSource.MODEL:
            raise ValueError("requires_hitl must be false without a model")
        if self.hitl_boost_id is not None and self.risk_policy_version is None:
            raise ValueError("hitl_boost_id requires risk_policy_version")
        return self

    def _check_eligibility(self) -> None:
        if self.eligibility_code is None:
            # Sin evaluar: nada predicho todavía.
            if (
                self.label_source is not LabelSource.NO_PREDICTED
                or self.sentiment is not None
            ):
                raise ValueError(
                    "unevaluated rows must be NO_PREDICTED with null sentiment"
                )
            return
        excluded = self.eligibility_code is not EligibilityCode.ELEGIBLE
        no_source = self.label_source is LabelSource.NO_PREDICTED
        no_sentiment = self.sentiment is SentimentValue.NO_PREDICTED
        if not excluded == no_source == no_sentiment:
            raise ValueError(
                "eligibility_code != ELEGIBLE, label_source = NO_PREDICTED and "
                "sentiment = NO_PREDICTED must hold together"
            )
        if (
            self.eligibility_code is EligibilityCode.TNSS_EMPTY
            and self.palabras
        ):
            raise ValueError("TNSS_EMPTY requires palabras = 0")
        single_word = (
            self.eligibility_code is EligibilityCode.TNSS_SINGLE_WORD
            or self.label_source is LabelSource.RULE_BASED
        )
        if single_word and self.palabras != 1:
            raise ValueError(
                "TNSS_SINGLE_WORD and RULE_BASED require palabras = 1"
            )

    def _check_probabilities(self) -> None:
        probabilities = (self.p_neg, self.p_neu, self.p_pos, self.confidence)
        if self.label_source is not LabelSource.MODEL:
            if any(value is not None for value in probabilities):
                raise ValueError("probabilities require label_source = MODEL")
            return
        if any(value is None for value in probabilities):
            raise ValueError("label_source = MODEL requires probabilities")
        if self.model_version is None or self.calibration_version is None:
            raise ValueError(
                "label_source = MODEL requires model and calibration versions"
            )
        p = (self.p_neg or 0.0, self.p_neu or 0.0, self.p_pos or 0.0)
        if abs(sum(p) - 1.0) > PROBABILITY_TOLERANCE:
            raise ValueError("probabilities must sum to 1")
        if abs((self.confidence or 0.0) - max(p)) > PROBABILITY_TOLERANCE:
            raise ValueError("confidence must equal the largest probability")


class ReviewAspects(_AnalyticsRecord):
    """Fila de ``review_aspects``: reseña negativa elegible × prompt."""

    id_resena: NonEmpty
    bank_id: NonEmpty
    text_key: Digest
    fecha: UtcDatetime
    # Vacío = sin problema concreto.
    families: list[AspectFamily]
    flag_update: bool
    flag_security: bool
    praise: bool
    prompt_version: NonEmpty
    llm_model: NonEmpty
    guideline_version: NonEmpty
    # El modelo cuyo ``NEG`` hizo elegible a la reseña (``TOPIC_NOT_NEGATIVE``).
    sentiment_model_version: NonEmpty
    run_id: NonEmpty
    labeled_at: UtcDatetime

    @model_validator(mode="after")
    def _families(self) -> Self:
        _unique_families(self.families)
        return self


class TextEmbedding(_AnalyticsRecord):
    """Fila de ``text_embeddings``: texto × banco × mes (búsqueda semántica)."""

    text_key: Digest
    bank_id: NonEmpty
    mes: MonthDate
    embedding: list[float] = Field(
        min_length=EMBEDDING_DIMENSIONS, max_length=EMBEDDING_DIMENSIONS
    )
    embedding_model: NonEmpty
    created_at: UtcDatetime


# ---------------------------------------------------------------------------
# Tópicos
# ---------------------------------------------------------------------------


class TopicModelVersion(_AnalyticsRecord):
    """Fila de ``topic_model_versions``: un ajuste de BERTopic."""

    topic_model_version: NonEmpty
    fitted_at: UtcDatetime
    embedding_model: NonEmpty
    # Segmentador de cláusulas (``clauses_v0``).
    segmenter: NonEmpty
    # ``min_cluster_size``, ``min_samples`` y el resto de parámetros.
    params: dict[str, Any]
    # Descripción o hash de la muestra de ajuste.
    fit_sample: NonEmpty


class TopicCatalogEntry(_AnalyticsRecord):
    """Fila de ``topic_catalog``: tópico × versión."""

    topic_model_version: NonEmpty
    topic_id: TopicId = Field(ge=-1)
    terms: list[str]
    previous_topic_id: TopicId | None = Field(default=None, ge=-1)
    centroid_similarity: float | None = Field(default=None, ge=-1.0, le=1.0)

    @model_validator(mode="after")
    def _previous(self) -> Self:
        require_together(
            previous_topic_id=self.previous_topic_id,
            centroid_similarity=self.centroid_similarity,
        )
        return self


class TopicAssignment(_AnalyticsRecord):
    """Fila de ``topic_assignments``: segmento de una reseña × versión."""

    id_resena: NonEmpty
    bank_id: NonEmpty
    text_key: Digest
    fecha: UtcDatetime
    segment_index: Counter
    topic_model_version: NonEmpty
    topic_id: TopicId = Field(ge=-1)


class TopicCuration(_AnalyticsRecord):
    """Fila de ``curation_topics``: tópico × versión × decisión del curador."""

    topic_model_version: NonEmpty
    topic_id: TopicId = Field(ge=-1)
    curated_name: NonEmpty
    coherence_1_5: int = Field(ge=1, le=5)
    audience: TopicAudience
    families: list[AspectFamily]
    is_new_theme: bool
    # El curador confirmó el emparejamiento con el tópico de la versión previa.
    mapping_confirmed: bool
    curator_hash: Digest
    curated_at: UtcDatetime

    @model_validator(mode="after")
    def _families(self) -> Self:
        _unique_families(self.families)
        return self
