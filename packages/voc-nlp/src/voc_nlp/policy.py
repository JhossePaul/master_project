"""Versiones de la ``risk_policy``: la lógica que comparten el ciclo de vida del
modelo y la pantalla de administración del portal.

Vive aquí (y no en ``ml-inference``) porque importarla desde ahí arrastra
BigQuery, Gemini y pyarrow. Es el mismo criterio de siempre: un cambio crea
una versión nueva, con quién y por qué, y si cambia la cobertura el umbral sale
de la curva del modelo promovido.
"""

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from voc_common.policies import CoveragePoint, HitlCoverageCurve, RiskPolicy

# Campos que fija el sistema al crear la versión; ``changes`` no los toca.
MANAGED_FIELDS = frozenset(
    {
        "policy_version",
        "valid_from",
        "hitl_signal",
        "hitl_threshold",
        "model_version",
        "set_by_hash",
        "reason",
    }
)


def next_policy_version(current: str) -> str:
    """``risk_policy_v1`` → ``risk_policy_v2``."""
    match = re.fullmatch(r"(.*_v)(\d+)", current)
    if match is None:
        return f"{current}_v2"
    return f"{match[1]}{int(match[2]) + 1}"


def point_for(curve: HitlCoverageCurve, coverage: float) -> CoveragePoint:
    """Primer punto de la curva con cobertura ≥ ``coverage``."""
    for point in curve.points:
        if point.coverage >= coverage - 1e-9:
            return point
    raise ValueError(f"the curve does not reach coverage {coverage}")


def propose_risk_policy(
    curve: HitlCoverageCurve,
    current: RiskPolicy,
    actor_hash: str,
    reason: str,
    now: datetime,
    coverage: float | None = None,
) -> RiskPolicy:
    """Siguiente versión con el umbral de ``coverage`` en ``curve``.

    Sin ``coverage`` se conserva la cobertura objetivo vigente. Los demás
    parámetros no cambian.
    """
    target = current.hitl_target_coverage if coverage is None else coverage
    point = point_for(curve, target)
    return current.model_copy(
        update={
            "policy_version": next_policy_version(current.policy_version),
            "valid_from": now,
            "hitl_target_coverage": target,
            "hitl_threshold": point.threshold,
            "model_version": curve.model_version,
            "set_by_hash": actor_hash,
            "reason": reason,
        }
    )


def next_risk_policy(
    current: RiskPolicy,
    changes: Mapping[str, Any],
    curve: HitlCoverageCurve,
    actor_hash: str,
    reason: str,
    now: datetime,
) -> RiskPolicy:
    """Siguiente versión con ``changes`` aplicados y validados por el modelo.

    El umbral se recalcula con ``point_for`` solo si cambia la cobertura
    objetivo (y entonces ``model_version`` es el de la curva); si no, se
    conservan el umbral y el modelo vigentes. Los grupos incompletos (subida
    por deriva, doble revisión) los rechaza el propio ``RiskPolicy``.
    """
    managed = MANAGED_FIELDS & set(changes)
    if managed:
        raise ValueError(f"fields set by the system: {sorted(managed)}")
    unknown = set(changes) - set(RiskPolicy.model_fields)
    if unknown:
        raise ValueError(f"unknown fields: {sorted(unknown)}")
    data = {**current.model_dump(), **changes}
    coverage = data["hitl_target_coverage"]
    if coverage != current.hitl_target_coverage:
        data["hitl_threshold"] = point_for(curve, coverage).threshold
        data["model_version"] = curve.model_version
    data.update(
        policy_version=next_policy_version(current.policy_version),
        valid_from=now,
        set_by_hash=actor_hash,
        reason=reason,
    )
    return RiskPolicy.model_validate(data)
