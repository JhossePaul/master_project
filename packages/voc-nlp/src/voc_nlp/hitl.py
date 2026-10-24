"""Umbral HITL por apetito de riesgo (EPIC-5, 5.6; P7-6).

La ``risk_policy`` vigente fija la cobertura y su umbral. Mientras un banco
tiene una subida activa (``hitl_boosts``), su umbral sale de la curva de
cobertura y riesgo para la cobertura de la subida.
"""

from voc_common.policies import (
    CoveragePoint,
    HitlBoost,
    HitlCoverageCurve,
    RiskPolicy,
)


def threshold_for(
    policy: RiskPolicy, boost: HitlBoost | None, curve: HitlCoverageCurve
) -> float:
    """Umbral de ``prob_max`` para un banco.

    Sin subida es ``policy.hitl_threshold``. Con subida es el umbral del
    punto de la curva con la cobertura de la subida o, si no está, el del
    punto inmediato de menor cobertura (más revisión, nunca menos).
    """
    if boost is None:
        return policy.hitl_threshold
    if curve.model_version != policy.model_version:
        raise ValueError("curve and policy refer to different models")
    return _point_at(curve, boost.coverage).threshold


def requires_hitl(confidence: float | None, threshold: float) -> bool:
    """Va a revisión si la confianza calibrada queda debajo del umbral."""
    return confidence is not None and confidence < threshold


def _point_at(curve: HitlCoverageCurve, coverage: float) -> CoveragePoint:
    candidates = [p for p in curve.points if p.coverage <= coverage + 1e-9]
    if not candidates:
        raise ValueError(f"curve has no point at or below coverage {coverage}")
    return max(candidates, key=lambda p: p.coverage)
