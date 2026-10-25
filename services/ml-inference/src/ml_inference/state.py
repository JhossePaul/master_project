"""Estado de servicio leído de BigQuery: modelo, política, curva y subidas."""

from dataclasses import dataclass, field
from typing import Any

from voc_common.operations_v3 import ModelVersion
from voc_common.policies import HitlBoost, HitlCoverageCurve, RiskPolicy

from ml_inference.bq_io import query_rows, render


@dataclass(frozen=True)
class ServingState:
    model: ModelVersion
    policy: RiskPolicy | None
    curve: HitlCoverageCurve | None
    # Subida activa por banco (la más reciente si hubiera varias).
    boosts: dict[str, HitlBoost] = field(default_factory=dict)
    topic_model_version: str | None = None

    @property
    def policy_for_model(self) -> RiskPolicy | None:
        """La política solo vale para el modelo con que se midió su umbral."""
        if (
            self.policy
            and self.policy.model_version == self.model.model_version
        ):
            return self.policy
        return None


class NoPromotedModel(RuntimeError):
    pass


def _clean(row: dict[str, Any], model: type) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k in model.model_fields}


def load_state(client: Any, dataset: str) -> ServingState:
    def rows(template: str, **params: Any) -> list[dict[str, Any]]:
        return query_rows(client, render(template, ds=dataset), params)

    models = rows(
        "SELECT * FROM `${ds}.model_versions` WHERE TRUE "
        "QUALIFY ROW_NUMBER() OVER "
        "(PARTITION BY model_version ORDER BY recorded_at DESC) = 1",
    )
    promoted = sorted(
        (ModelVersion.model_validate(r) for r in models),
        key=lambda m: m.promoted_at or m.recorded_at,
    )
    promoted = [m for m in promoted if m.status.value == "promoted"]
    if not promoted:
        raise NoPromotedModel("model_versions has no promoted model")
    model = promoted[-1]
    policies = rows("SELECT * FROM `${ds}.risk_policy_current`")
    policy = RiskPolicy.model_validate(policies[0]) if policies else None
    curves = rows(
        "SELECT * FROM `${ds}.hitl_coverage_curves` "
        "WHERE model_version = @mv AND calibration_version = @cv "
        "ORDER BY computed_at DESC LIMIT 1",
        mv=model.model_version,
        cv=model.calibration_version,
    )
    curve = HitlCoverageCurve.model_validate(curves[0]) if curves else None
    boosts: dict[str, HitlBoost] = {}
    for row in rows(
        "SELECT * FROM `${ds}.hitl_boosts_active` ORDER BY starts_at",
    ):
        boost = HitlBoost.model_validate(_clean(row, HitlBoost))
        boosts[boost.bank_id] = boost
    # La versión nueva asigna cuando su curaduría está completa.
    topics = rows(
        "SELECT topic_model_version FROM `${ds}.topic_model_current`",
    )
    return ServingState(
        model,
        policy,
        curve,
        boosts,
        topics[0]["topic_model_version"] if topics else None,
    )
