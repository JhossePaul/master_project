"""Lista cerrada de tablas y vistas que la API puede consultar.

Los identificadores no se pueden parametrizar en SQL, así que ningún nombre
llega a una consulta sin pasar por ``qualified``.
"""

from typing import Final

from voc_common import ANALYTICS_V3_TABLES

# Las vistas del contrato v3; ``infra/modules/sql/`` tiene un archivo por vista.
ANALYTICS_V3_VIEWS: Final[tuple[str, ...]] = (
    "review_predictions_current",
    "risk_policy_current",
    "drift_policy_current",
    "hitl_boosts_active",
    "hitl_queue",
    "drift_alerts_current",
    "eligibility_counts",
    "topic_model_current",
    "daily_topic_labels",
    "inference_runs_current",
)
# Tablas de EPIC-4 que el portal lee.
TDS_TABLES: Final[tuple[str, ...]] = (
    "sanitized_reviews_tds",
    "ingestion_runs_log_v2",
)
ALLOWED_NAMES: Final[frozenset[str]] = frozenset(
    (*ANALYTICS_V3_TABLES, *ANALYTICS_V3_VIEWS, *TDS_TABLES)
)


def qualified(name: str, project: str, dataset: str) -> str:
    """``proyecto.dataset.nombre`` con comillas invertidas, o ``ValueError``."""
    if name not in ALLOWED_NAMES:
        raise ValueError(f"tabla o vista no permitida: {name!r}")
    return f"`{project}.{dataset}.{name}`"
