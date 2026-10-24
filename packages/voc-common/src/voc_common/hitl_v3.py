"""HITL del esquema v3: casos, transiciones, revisiones, guías y oro.

El estado de un caso es su última transición en ``hitl_events``; nada se
edita. Una segunda revisión del mismo caso es otra fila de ``hitl_reviews``.
"""

from typing import Any, Literal, Self

from pydantic import model_validator

from voc_common._analytics_base import (
    Counter,
    Digest,
    NonEmpty,
    UtcDatetime,
    _AnalyticsRecord,
)
from voc_common.analytics_codes import (
    AspectFamily,
    DisplayMode,
    HitlReason,
    HitlStatus,
    HitlTask,
    ReviewFlag,
    ReviewOutcome,
)
from voc_common.constants import SentimentLabel

# Casos que pueden entrar al oro: siempre sin la predicción, para que el
# revisor no se ancle en ella.
BLIND_REASONS = frozenset(
    {HitlReason.MONITOR_SAMPLE, HitlReason.AGREEMENT_SAMPLE}
)


class HitlItem(_AnalyticsRecord):
    """Fila de ``hitl_items``: reseña × tarea, al entrar a la cola."""

    item_id: NonEmpty
    id_resena: NonEmpty
    bank_id: NonEmpty
    task: HitlTask
    reason: HitlReason
    boost_id: NonEmpty | None = None
    display_mode: DisplayMode
    model_version: NonEmpty | None = None
    risk_policy_version: NonEmpty | None = None
    # Lo que predijo el sistema; la API no lo envía si el caso es ``blind``.
    predicted: dict[str, Any] | None = None
    priority: float
    created_at: UtcDatetime

    @model_validator(mode="after")
    def _reason_rules(self) -> Self:
        if (
            self.reason in BLIND_REASONS
            and self.display_mode is not DisplayMode.BLIND
        ):
            raise ValueError(f"{self.reason} items must be blind")
        if (self.reason is HitlReason.DRIFT_BOOST) != (
            self.boost_id is not None
        ):
            raise ValueError(
                "boost_id is required for, and only for, drift_boost"
            )
        return self


class HitlEvent(_AnalyticsRecord):
    """Fila de ``hitl_events``: transición de estado de un caso."""

    event_id: NonEmpty
    item_id: NonEmpty
    status: HitlStatus
    # Nulo = el sistema (``queued``, ``expired``).
    actor_hash: Digest | None = None
    at: UtcDatetime


class HitlReview(_AnalyticsRecord):
    """Fila de ``hitl_reviews``: decisión humana inmutable.

    Las curadurías de tópicos van a ``curation_topics``, porque su grano es el
    tópico y no la reseña.
    """

    review_id: NonEmpty
    item_id: NonEmpty
    id_resena: NonEmpty
    task: Literal[HitlTask.SENTIMENT, HitlTask.ASPECTS]
    predicted_label: SentimentLabel | None = None
    validated_label: SentimentLabel | None = None
    predicted_families: list[AspectFamily] = []
    validated_families: list[AspectFamily] = []
    predicted_flag_update: bool | None = None
    validated_flag_update: bool | None = None
    predicted_flag_security: bool | None = None
    validated_flag_security: bool | None = None
    outcome: ReviewOutcome
    display_mode: DisplayMode
    review_round: Literal[1, 2]
    flags: list[ReviewFlag] = []
    guideline_version: NonEmpty
    model_version: NonEmpty | None = None
    risk_policy_version: NonEmpty | None = None
    reviewer_hash: Digest
    opened_at: UtcDatetime
    submitted_at: UtcDatetime
    seconds_spent: Counter
    # Sanitizado antes de guardarse: puede traer datos personales.
    comment: str | None = None
    ticket: str | None = None

    @model_validator(mode="after")
    def _decision(self) -> Self:
        if self.submitted_at < self.opened_at:
            raise ValueError("submitted_at must not precede opened_at")
        if len(set(self.flags)) != len(self.flags):
            raise ValueError("flags must not repeat")
        predicted, validated = (
            self._sentiment()
            if self.task is HitlTask.SENTIMENT
            else self._aspects()
        )
        same = predicted == validated
        if same != (self.outcome is ReviewOutcome.CONFIRMED):
            raise ValueError(
                "outcome = confirmed iff validated equals predicted"
            )
        return self

    def _sentiment(self) -> tuple[object, object]:
        aspects = (
            self.predicted_families,
            self.validated_families,
        )
        flags = (
            self.predicted_flag_update,
            self.validated_flag_update,
            self.predicted_flag_security,
            self.validated_flag_security,
        )
        if any(aspects) or any(flag is not None for flag in flags):
            raise ValueError("sentiment reviews carry no aspects")
        if self.predicted_label is None or self.validated_label is None:
            raise ValueError(
                "sentiment reviews require predicted and validated label"
            )
        return self.predicted_label, self.validated_label

    def _aspects(self) -> tuple[object, object]:
        if self.predicted_label is not None or self.validated_label is not None:
            raise ValueError("aspects reviews carry no sentiment label")
        flags = (
            self.predicted_flag_update,
            self.validated_flag_update,
            self.predicted_flag_security,
            self.validated_flag_security,
        )
        if any(flag is None for flag in flags):
            raise ValueError("aspects reviews require the u and s flags")
        for families in (self.predicted_families, self.validated_families):
            if len(set(families)) != len(families):
                raise ValueError("families must not repeat")
        return (
            (
                frozenset(self.predicted_families),
                self.predicted_flag_update,
                self.predicted_flag_security,
            ),
            (
                frozenset(self.validated_families),
                self.validated_flag_update,
                self.validated_flag_security,
            ),
        )


class Guideline(_AnalyticsRecord):
    """Fila de ``guidelines``: la vigente de cada tarea es la última."""

    guideline_version: NonEmpty
    task: HitlTask
    content_uri: NonEmpty
    valid_from: UtcDatetime
    published_by_hash: Digest


class GoldVersion(_AnalyticsRecord):
    """Fila de ``gold_versions``: qué revisiones HITL entran a una versión."""

    gold_version: NonEmpty
    # ``reason``, periodo y ``guideline_version`` aplicados a ``hitl_reviews``.
    criteria: dict[str, Any]
    cutoff_at: UtcDatetime
    items: Counter
    created_by_hash: Digest
    created_at: UtcDatetime
