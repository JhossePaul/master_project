"""Operación del esquema v3: modelos, corridas, deriva, KPI, calidad y oro.

Una clase por tabla de ``bbva_voc_tds`` más el mensaje de Pub/Sub de las
alertas de deriva (``DriftAlertMessage``), que reemplaza a la alerta de
incidentes de EPIC-1 y no lleva texto ni PII.
"""

from typing import Literal, Self

from pydantic import model_validator

from voc_common._analytics_base import (
    Counter,
    Digest,
    MonthDate,
    NonEmpty,
    UtcDatetime,
    _AnalyticsRecord,
    require_together,
)
from voc_common.analytics_codes import (
    AlertStatus,
    AspectFamily,
    ExplanationSource,
    GoldSplit,
    HitlTask,
    KpiMethod,
    ModelStatus,
    QualitySignal,
    QualityStatus,
    RunEnvironment,
    RunKind,
    RunStatus,
)
from voc_common.constants import SentimentLabel


class ModelVersion(_AnalyticsRecord):
    """Fila de ``model_versions``; cada cambio de estado es una fila nueva."""

    model_version: NonEmpty
    # Vertex Model Registry o GCS (P7-3).
    registry_uri: NonEmpty
    base_checkpoint: NonEmpty
    training_data: NonEmpty
    training_data_hash: Digest | None = None
    calibration_version: NonEmpty
    calibration_t: float
    kappa_dev: float | None = None
    ece_dev: float | None = None
    aurc_dev: float | None = None
    license: NonEmpty
    status: ModelStatus
    promoted_at: UtcDatetime | None = None
    promoted_by_hash: Digest | None = None
    # Orden de las filas de una misma versión (la vigente es la última).
    recorded_at: UtcDatetime

    @model_validator(mode="after")
    def _promotion(self) -> Self:
        if self.calibration_t <= 0:
            raise ValueError("calibration_t must be positive")
        require_together(
            promoted_at=self.promoted_at, promoted_by_hash=self.promoted_by_hash
        )
        if self.status is ModelStatus.PROMOTED and self.promoted_at is None:
            raise ValueError(
                "promoted versions require promoted_at and its actor"
            )
        return self


class InferenceRun(_AnalyticsRecord):
    """Fila de ``inference_runs``: una corrida terminada."""

    run_id: NonEmpty
    kind: RunKind
    environment: RunEnvironment
    model_version: NonEmpty | None
    started_at: UtcDatetime
    ended_at: UtcDatetime
    reviews: Counter
    texts: Counter
    status: RunStatus
    cost_usd: float | None = None
    peak_memory_mib: Counter | None = None

    @model_validator(mode="after")
    def _times(self) -> Self:
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must not precede started_at")
        if self.cost_usd is not None and self.cost_usd < 0:
            raise ValueError("cost_usd must not be negative")
        return self


class DriftMetric(_AnalyticsRecord):
    """Fila de ``drift_metrics``: banco × mes × serie."""

    bank_id: NonEmpty
    period: MonthDate
    metric: NonEmpty
    value: float
    baseline: float | None = None
    z: float | None = None
    psi: float | None = None
    # Nulo = serie de contexto que nunca alerta (familias y ``u``, D8).
    threshold: float | None = None
    alert: bool
    drift_policy_version: NonEmpty
    computed_at: UtcDatetime

    @model_validator(mode="after")
    def _statistic(self) -> Self:
        if self.z is not None and self.psi is not None:
            raise ValueError("a series uses z or psi, not both")
        if self.alert and self.threshold is None:
            raise ValueError("series without threshold never alert")
        return self


class DriftAlert(_AnalyticsRecord):
    """Fila de ``drift_alerts``; su estado vigente es el último evento."""

    alert_id: NonEmpty
    bank_id: NonEmpty
    period: MonthDate
    series: NonEmpty
    value: float
    threshold: float
    drift_policy_version: NonEmpty
    hitl_boost_id: NonEmpty | None = None
    created_at: UtcDatetime


class DriftAlertEvent(_AnalyticsRecord):
    """Fila de ``drift_alert_events``: transición de una alerta (7.8)."""

    event_id: NonEmpty
    alert_id: NonEmpty
    status: AlertStatus
    # Nulo = el monitor (``open``); las personas se guardan como hash.
    actor_hash: Digest | None = None
    at: UtcDatetime
    # Sanitizada antes de guardarse (FMEA F-21).
    note: str | None = None
    ticket: str | None = None


class DriftAlertMessage(_AnalyticsRecord):
    """Payload de ``voc-incident-alerts-topic``; sin texto ni PII."""

    alert_id: NonEmpty
    bank_id: NonEmpty
    # Mes de la serie, ``YYYY-MM``.
    period: str
    series: NonEmpty
    value: float
    threshold: float
    drift_policy_version: NonEmpty
    hitl_boost_id: NonEmpty | None = None
    triggered_at: UtcDatetime

    @model_validator(mode="after")
    def _period(self) -> Self:
        year, _, month = self.period.partition("-")
        if not (len(year) == 4 and year.isdigit() and month in _MONTHS):
            raise ValueError("period must be YYYY-MM")
        return self


_MONTHS = frozenset(f"{month:02d}" for month in range(1, 13))


class KpiEstimate(_AnalyticsRecord):
    """Fila de ``kpi_estimates``: banco × periodo × métrica × corrida."""

    metric: NonEmpty
    bank_id: NonEmpty
    period: NonEmpty
    method: KpiMethod
    estimate: float
    ci_low: float | None = None
    ci_high: float | None = None
    n_gold: Counter | None = None
    n_unlabeled: Counter
    model_version: NonEmpty
    gold_version: NonEmpty | None = None
    computed_at: UtcDatetime

    @model_validator(mode="after")
    def _interval(self) -> Self:
        require_together(ci_low=self.ci_low, ci_high=self.ci_high)
        if self.method is KpiMethod.PPI and None in (
            self.ci_low,
            self.n_gold,
            self.gold_version,
        ):
            raise ValueError(
                "ppi estimates require ci, n_gold and gold_version"
            )
        if self.ci_low is not None and not (
            self.ci_low <= self.estimate <= (self.ci_high or 0.0)
        ):
            raise ValueError("estimate must lie inside its interval")
        return self


class TokenAttribution(_AnalyticsRecord):
    """Peso de un token por posición en ``texto_sanitizado``, sin texto."""

    start: Counter
    end: Counter
    weight: float

    @model_validator(mode="after")
    def _span(self) -> Self:
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class ReviewExplanation(_AnalyticsRecord):
    """Fila de ``review_explanations``: texto × versión de modelo (P8-8)."""

    text_key: Digest
    model_version: NonEmpty
    method: Literal["occlusion_v1"]
    attributions: list[TokenAttribution]
    source: ExplanationSource
    computed_at: UtcDatetime


class ModelQuality(_AnalyticsRecord):
    """Fila de ``model_quality``: modelo × periodo × señal (P7-10, P7-11)."""

    model_version: NonEmpty | None = None
    llm_model: NonEmpty | None = None
    prompt_version: NonEmpty | None = None
    signal: QualitySignal
    period: NonEmpty
    value: float
    n: Counter
    ci_low: float | None = None
    ci_high: float | None = None
    threshold: float | None = None
    status: QualityStatus
    risk_policy_version: NonEmpty | None = None
    computed_at: UtcDatetime

    @model_validator(mode="after")
    def _subject(self) -> Self:
        require_together(ci_low=self.ci_low, ci_high=self.ci_high)
        if self.signal is QualitySignal.FAMILIES_VALIDATION:
            if self.llm_model is None or self.prompt_version is None:
                raise ValueError(
                    "families_validation requires llm_model and prompt"
                )
        elif self.model_version is None:
            raise ValueError(f"{self.signal} requires model_version")
        return self


class GoldLabel(_AnalyticsRecord):
    """Fila de ``gold_labels`` (D10): oro *dev* y ``aspects_gold_v2_1``."""

    gold_version: NonEmpty
    split: GoldSplit
    task: HitlTask
    id_resena: NonEmpty
    text_key: Digest
    label: SentimentLabel | None = None
    families: list[AspectFamily] = []
    flag_update: bool | None = None
    flag_security: bool | None = None
    praise: bool | None = None
    guideline_version: NonEmpty
    loaded_at: UtcDatetime

    @model_validator(mode="after")
    def _task_fields(self) -> Self:
        flags = (self.flag_update, self.flag_security, self.praise)
        if self.task is HitlTask.SENTIMENT:
            if (
                self.label is None
                or self.families
                or any(flag is not None for flag in flags)
            ):
                raise ValueError("sentiment gold has a label and no aspects")
        elif self.task is HitlTask.ASPECTS:
            if self.label is not None or any(flag is None for flag in flags):
                raise ValueError(
                    "aspects gold has flags and no sentiment label"
                )
            if len(set(self.families)) != len(self.families):
                raise ValueError("families must not repeat")
        else:
            raise ValueError("gold_labels holds sentiment or aspects only")
        expected = {GoldSplit.DEV: HitlTask.SENTIMENT}.get(
            self.split, HitlTask.ASPECTS
        )
        if self.task is not expected:
            raise ValueError(f"split {self.split} holds {expected} labels")
        return self
