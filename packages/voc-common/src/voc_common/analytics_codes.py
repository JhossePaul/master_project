"""Códigos y enumeraciones del esquema de salidas analíticas v3 (EPIC-6, 6.1).

Los valores son los del contrato ``docs/contracts/analytics_outputs_v3.md`` y,
para la elegibilidad, los de ``docs/analytics/eda/eligibility_rules.md``
(``eligibility_rules_v1``). Se guardan tal cual en BigQuery, así que cambiar un
valor es un cambio de contrato.
"""

from enum import StrEnum

# ---------------------------------------------------------------------------
# Elegibilidad y etiquetas (``review_predictions``, ``review_aspects``)
# ---------------------------------------------------------------------------


class EligibilityCode(StrEnum):
    """Resultado de las reglas TNSS de ``eligibility_rules_v1``.

    Gana la primera regla que coincide, en el orden de declaración.
    """

    ELEGIBLE = "ELEGIBLE"
    TNSS_EMPTY = "TNSS_EMPTY"
    TNSS_NO_TEXT_CONTENT = "TNSS_NO_TEXT_CONTENT"
    TNSS_TIME_OUTLIER = "TNSS_TIME_OUTLIER"
    TNSS_SINGLE_WORD = "TNSS_SINGLE_WORD"


class TopicEligibilityCode(StrEnum):
    """Reglas de familias y tópicos (k = 1 en ``TOPIC_TOO_SHORT``)."""

    ELEGIBLE = "ELEGIBLE"
    TOPIC_TNSS_NOT_PREDICTED = "TOPIC_TNSS_NOT_PREDICTED"
    TOPIC_NOT_NEGATIVE = "TOPIC_NOT_NEGATIVE"
    TOPIC_TOO_SHORT = "TOPIC_TOO_SHORT"


class LabelSource(StrEnum):
    """Quién produjo la etiqueta de sentimiento."""

    MODEL = "MODEL"
    # Léxico de una palabra (``lexicon_v1``).
    RULE_BASED = "RULE_BASED"
    NO_PREDICTED = "NO_PREDICTED"


class SentimentValue(StrEnum):
    """Valor de ``review_predictions.sentiment``.

    ``SentimentLabel`` (``constants``) se queda para las tres clases del
    modelo; aquí se suma el valor explícito de la reseña no elegible.
    """

    NEG = "NEG"
    NEU = "NEU"
    POS = "POS"
    NO_PREDICTED = "NO_PREDICTED"


class AspectFamily(StrEnum):
    """Las 11 familias de ``aspects_v2_1`` (guía ``v2.1``)."""

    AC = "AC"
    TR = "TR"
    DI = "DI"
    PR = "PR"
    AT = "AT"
    FA = "FA"
    LE = "LE"
    CO = "CO"
    DV = "DV"
    UX = "UX"
    OT = "OT"


class TopicAudience(StrEnum):
    """Audiencia de un tópico curado."""

    PRODUCTO = "producto"
    INGENIERIA = "ingenieria"
    SIN_VALOR = "sin_valor"


# ---------------------------------------------------------------------------
# HITL (``hitl_items``, ``hitl_events``, ``hitl_reviews``, ``guidelines``)
# ---------------------------------------------------------------------------


class HitlTask(StrEnum):
    SENTIMENT = "sentiment"
    ASPECTS = "aspects"
    TOPIC = "topic"


class HitlReason(StrEnum):
    LOW_CONFIDENCE = "low_confidence"
    # Subida automática por una alerta de deriva; exige ``boost_id``.
    DRIFT_BOOST = "drift_boost"
    # Muestra aleatoria de concepto; siempre ``blind``.
    MONITOR_SAMPLE = "monitor_sample"
    # Doble revisión para medir el acuerdo entre personas; siempre ``blind``.
    AGREEMENT_SAMPLE = "agreement_sample"
    MANUAL = "manual"


class DisplayMode(StrEnum):
    BLIND = "blind"
    ASSISTED = "assisted"


class HitlStatus(StrEnum):
    QUEUED = "queued"
    ASSIGNED = "assigned"
    IN_REVIEW = "in_review"
    SUBMITTED = "submitted"
    SKIPPED = "skipped"
    EXPIRED = "expired"


class ReviewOutcome(StrEnum):
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"


class ReviewFlag(StrEnum):
    """Marcas del revisor de sentimiento (guía ``v2.2``)."""

    MENCIONA_FALLA = "menciona_falla"
    DUDA = "duda"
    NO_EVALUABLE = "no_evaluable"
    NOMBRE_PERSONA = "nombre_persona"


class GoldSplit(StrEnum):
    """Partición del oro cargado en ``gold_labels``."""

    DEV = "dev"
    # 300 reseñas con las familias de la guía v2.1, anotadas por el autor.
    ASPECTS_GOLD_V2_1 = "aspects_gold_v2_1"


# ---------------------------------------------------------------------------
# Operación (``inference_runs``, ``model_versions``, deriva, calidad, KPI)
# ---------------------------------------------------------------------------


class RunKind(StrEnum):
    BACKFILL = "backfill"
    DELTA = "delta"
    RESCORING = "rescoring"


class RunEnvironment(StrEnum):
    KAGGLE = "kaggle"
    CLOUDRUN = "cloudrun"
    # Tópicos y embeddings históricos, calculados en la máquina del autor.
    LOCAL = "local"


class RunStatus(StrEnum):
    """Estado final con que se registra una corrida (solo inserción)."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ModelStatus(StrEnum):
    CANDIDATE = "candidate"
    PROMOTED = "promoted"
    RETIRED = "retired"


class AlertStatus(StrEnum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class BoostEndReason(StrEnum):
    EXPIRED = "expired"
    ALERT_CLOSED = "alert_closed"
    MANUAL = "manual"


class QualitySignal(StrEnum):
    KAPPA_MONITOR = "kappa_monitor"
    CORRECTION_RATE = "correction_rate"
    GEMINI_AGREEMENT = "gemini_agreement"
    FAMILIES_VALIDATION = "families_validation"


class QualityStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    RETRAIN = "retrain"
    REJECTED = "rejected"


class KpiMethod(StrEnum):
    PPI = "ppi"
    RAW = "raw"


class ExplanationSource(StrEnum):
    PRECOMPUTED_HITL = "precomputed_hitl"
    ON_DEMAND = "on_demand"
