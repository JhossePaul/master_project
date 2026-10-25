"""Esquema de BigQuery derivado de los contratos v3 (EPIC-6, 6.1).

``infra/`` crea las tablas con ``bq_schema(modelo)``, así que las columnas se
declaran una sola vez, en el modelo. El orden de las columnas es el de los
campos del modelo.
"""

import types
from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

from voc_common.hitl_v3 import (
    GoldVersion,
    Guideline,
    HitlEvent,
    HitlItem,
    HitlReview,
)
from voc_common.operations_v3 import (
    DriftAlert,
    DriftAlertEvent,
    DriftMetric,
    GoldLabel,
    InferenceRun,
    KpiEstimate,
    ModelQuality,
    ModelVersion,
    PromotionCheckResult,
    ReviewExplanation,
)
from voc_common.policies import (
    DriftPolicy,
    DriftPolicyTemplate,
    HitlBoost,
    HitlCoverageCurve,
    RiskPolicy,
)
from voc_common.predictions_v3 import (
    ReviewAspects,
    ReviewPrediction,
    SegmentEmbedding,
    TextEmbedding,
    TopicAssignment,
    TopicCatalogEntry,
    TopicCuration,
    TopicModelVersion,
)

BqField = tuple[str, str, str]  # (nombre, tipo, modo), como storage_bq._schema

# Tabla de ``bbva_voc_tds`` → modelo que define sus columnas.
ANALYTICS_V3_TABLES: Mapping[str, type[BaseModel]] = {
    "review_predictions": ReviewPrediction,
    "review_aspects": ReviewAspects,
    "text_embeddings": TextEmbedding,
    "topic_model_versions": TopicModelVersion,
    "topic_catalog": TopicCatalogEntry,
    "topic_assignments": TopicAssignment,
    "curation_topics": TopicCuration,
    "model_versions": ModelVersion,
    "inference_runs": InferenceRun,
    "drift_metrics": DriftMetric,
    "drift_alerts": DriftAlert,
    "drift_alert_events": DriftAlertEvent,
    "kpi_estimates": KpiEstimate,
    "review_explanations": ReviewExplanation,
    "model_quality": ModelQuality,
    "risk_policy": RiskPolicy,
    "hitl_boosts": HitlBoost,
    "drift_policy": DriftPolicy,
    "drift_policy_template": DriftPolicyTemplate,
    "hitl_coverage_curves": HitlCoverageCurve,
    "hitl_items": HitlItem,
    "hitl_events": HitlEvent,
    "hitl_reviews": HitlReview,
    "guidelines": Guideline,
    "gold_versions": GoldVersion,
    "gold_labels": GoldLabel,
    "promotion_checks": PromotionCheckResult,
    "segment_embeddings": SegmentEmbedding,
}

# ``bool`` antes que ``int`` y ``datetime`` antes que ``date``: son subclases.
_SCALARS: tuple[tuple[type, str], ...] = (
    (bool, "BOOL"),
    (int, "INT64"),
    (float, "FLOAT64"),
    (str, "STRING"),
    (datetime, "TIMESTAMP"),
    (date, "DATE"),
)


def _strip_annotated(annotation: Any) -> Any:
    while get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    return annotation


def _split_optional(annotation: Any) -> tuple[Any, bool]:
    annotation = _strip_annotated(annotation)
    if get_origin(annotation) in (Union, types.UnionType):
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(args) != 1:
            raise TypeError(f"unsupported union {annotation!r}")
        return _strip_annotated(args[0]), True
    return annotation, False


def _scalar_type(annotation: Any, name: str) -> str:
    if get_origin(annotation) is Literal:
        kinds = {type(value) for value in get_args(annotation)}
        if len(kinds) != 1:
            raise TypeError(f"{name}: Literal values must share one type")
        annotation = kinds.pop()
    if annotation is dict or get_origin(annotation) is dict:
        return "JSON"
    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            return "JSON"
        if issubclass(annotation, Enum) and not issubclass(annotation, str):
            raise TypeError(f"{name}: only str enums are supported")
        for python_type, bq_type in _SCALARS:
            if issubclass(annotation, python_type):
                return bq_type
    raise TypeError(f"{name}: unsupported type {annotation!r}")


def _field(name: str, annotation: Any) -> BqField:
    inner, optional = _split_optional(annotation)
    if get_origin(inner) in (list, tuple):
        if optional:
            raise TypeError(f"{name}: arrays cannot be nullable in BigQuery")
        args = [arg for arg in get_args(inner) if arg is not Ellipsis]
        if len(args) != 1:
            raise TypeError(f"{name}: arrays need one element type")
        element, element_optional = _split_optional(args[0])
        if element_optional or get_origin(element) in (list, tuple):
            raise TypeError(f"{name}: array elements cannot be null or arrays")
        return name, _scalar_type(element, name), "REPEATED"
    return (
        name,
        _scalar_type(inner, name),
        "NULLABLE" if optional else "REQUIRED",
    )


def bq_schema(model: type[BaseModel]) -> tuple[BqField, ...]:
    """Columnas de BigQuery de ``model`` en el orden de sus campos.

    ``str`` (y sus enums) → ``STRING``, ``int`` → ``INT64``, ``float`` →
    ``FLOAT64``, ``bool`` → ``BOOL``, ``datetime`` → ``TIMESTAMP``, ``date`` →
    ``DATE``, ``list[...]`` → ``REPEATED``, submodelos y ``dict`` → ``JSON``;
    ``Optional`` → ``NULLABLE``. Cualquier otro tipo levanta ``TypeError``.
    """
    return tuple(
        _field(name, info.annotation)
        for name, info in model.model_fields.items()
    )
