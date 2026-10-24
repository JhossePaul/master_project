"""Políticas del esquema v3: apetito de riesgo (global) y deriva (por banco).

``risk_policy`` dice cuánto error del modelo se acepta sin revisión humana;
``drift_policy`` configura el detector de deriva de cada banco. Las dos son de
solo inserción: la vigente es la última versión con ``valid_from`` ≤ ahora.
"""

from typing import Literal, Self

from pydantic import Field, model_validator

from voc_common._analytics_base import (
    Counter,
    Digest,
    NonEmpty,
    PositiveInt,
    Probability,
    UtcDatetime,
    _AnalyticsRecord,
    require_together,
)
from voc_common.analytics_codes import BoostEndReason


class RiskPolicy(_AnalyticsRecord):
    """Fila de ``risk_policy`` (global): el apetito de riesgo.

    Todos los valores son parámetros que fijan el revisor y el dueño de
    negocio en la pantalla de administración. El tope semanal, la subida por
    deriva y la doble revisión no tienen evidencia en los experimentos: son
    nulos hasta que se configuran (sin tope, sin subida automática y sin doble
    revisión).
    """

    policy_version: NonEmpty
    valid_from: UtcDatetime
    # Probabilidad máxima de RoBERTuito calibrado.
    hitl_signal: Literal["prob_max"]
    hitl_target_coverage: Probability
    hitl_threshold: Probability
    # Modelo para el que ``hitl_threshold`` equivale a la cobertura.
    model_version: NonEmpty
    hitl_weekly_cap: PositiveInt | None = None
    drift_boost_coverage: Probability | None = None
    drift_boost_days: PositiveInt | None = None
    drift_boost_weekly_cap: PositiveInt | None = None
    monitor_sample_size: PositiveInt
    monitor_frequency: NonEmpty
    topic_refit_frequency: NonEmpty
    retrain_kappa_floor: Probability
    human_agreement_sample_size: Counter | None = None
    human_agreement_frequency: NonEmpty | None = None
    warn_correction_rate: Probability
    warn_agreement_floor: Probability
    agreement_sample_weekly: Counter
    families_exact_floor: Probability
    families_min_prevalence: Probability
    set_by_hash: Digest
    reason: NonEmpty

    @model_validator(mode="after")
    def _configured_together(self) -> Self:
        require_together(
            drift_boost_coverage=self.drift_boost_coverage,
            drift_boost_days=self.drift_boost_days,
            drift_boost_weekly_cap=self.drift_boost_weekly_cap,
        )
        require_together(
            human_agreement_sample_size=self.human_agreement_sample_size,
            human_agreement_frequency=self.human_agreement_frequency,
        )
        return self


class HitlBoost(_AnalyticsRecord):
    """Fila de ``hitl_boosts``: subida temporal de la revisión de un banco.

    La fila de cierre repite el ``boost_id`` con ``ended_reason``; no se edita.
    """

    boost_id: NonEmpty
    bank_id: NonEmpty
    # Alerta de deriva que la disparó; nulo en una subida manual.
    alert_id: NonEmpty | None = None
    risk_policy_version: NonEmpty
    coverage: Probability
    weekly_cap: PositiveInt
    starts_at: UtcDatetime
    ends_at: UtcDatetime
    ended_reason: BoostEndReason | None = None

    @model_validator(mode="after")
    def _window(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must follow starts_at")
        return self


class DriftThresholds(_AnalyticsRecord):
    """JSON ``thresholds`` de la política: umbral por serie.

    Un umbral nulo es una serie que se mide y nunca alerta (familias y
    ``u``). Una serie usa z o PSI, no los dos.
    """

    z: dict[NonEmpty, float | None] = Field(default_factory=dict)
    psi: dict[NonEmpty, float | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _values(self) -> Self:
        shared = set(self.z) & set(self.psi)
        if shared:
            raise ValueError(f"series with both z and psi: {sorted(shared)}")
        for value in (*self.z.values(), *self.psi.values()):
            if value is not None and value < 0:
                raise ValueError("thresholds must be non-negative or null")
        return self


class _DriftPolicyBody(_AnalyticsRecord):
    valid_from: UtcDatetime
    thresholds: DriftThresholds
    baseline_months: PositiveInt
    min_baseline_months: PositiveInt
    min_rows_per_month: PositiveInt
    # Meses seguidos con ``min_rows_per_month`` para que el banco entre.
    entry_months: PositiveInt
    set_by_hash: Digest
    reason: NonEmpty

    @model_validator(mode="after")
    def _baseline(self) -> Self:
        if self.min_baseline_months > self.baseline_months:
            raise ValueError(
                "min_baseline_months must not exceed baseline_months"
            )
        return self


class DriftPolicyTemplate(_DriftPolicyBody):
    """Fila de ``drift_policy_template``; cambiarla no cambia a ningún banco."""

    template_version: NonEmpty


class DriftPolicy(_DriftPolicyBody):
    """Fila de ``drift_policy`` (por banco)."""

    drift_policy_version: NonEmpty
    bank_id: NonEmpty
    template_version: NonEmpty


class CoveragePoint(_AnalyticsRecord):
    """Un punto de la curva de cobertura y riesgo (5.6)."""

    coverage: Probability
    risk: Probability
    # Nulos donde no se midió el intervalo (cobertura 1.0).
    risk_ci_low: Probability | None = None
    risk_ci_high: Probability | None = None
    threshold: Probability
    # Fracción de los errores del modelo que caen en la revisión.
    errors_caught: Probability
    reviews_per_week: float = Field(ge=0.0)
    minutes_per_week: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _interval(self) -> Self:
        require_together(
            risk_ci_low=self.risk_ci_low, risk_ci_high=self.risk_ci_high
        )
        low, high = self.risk_ci_low, self.risk_ci_high
        if (
            low is not None
            and high is not None
            and not low <= self.risk <= high
        ):
            raise ValueError("risk must lie inside its interval")
        return self


class HitlCoverageCurve(_AnalyticsRecord):
    """Fila de ``hitl_coverage_curves``: modelo × calibración × cálculo."""

    model_version: NonEmpty
    calibration_version: NonEmpty
    points: list[CoveragePoint] = Field(min_length=1)
    weekly_volume_total: Counter
    weekly_volume_by_bank: dict[NonEmpty, Counter]
    computed_at: UtcDatetime

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        coverages = [point.coverage for point in self.points]
        if coverages != sorted(set(coverages)):
            raise ValueError("points must have increasing, unique coverage")
        return self
