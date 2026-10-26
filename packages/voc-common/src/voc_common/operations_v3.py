"""Operación del esquema v3: modelos, corridas, deriva, KPI, calidad y oro.

Una clase por tabla de ``bbva_voc_tds`` más el mensaje de Pub/Sub de las
alertas de deriva (``DriftAlertMessage``), que reemplaza a la alerta de
incidentes del primer diseño y no lleva texto ni PII.
"""

from typing import Literal, Self

from pydantic import model_validator

from voc_common._analytics_base import (
    Counter,
    Digest,
    MonthDate,
    NonEmpty,
    PositiveInt,
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
    PromotionVerdict,
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
    # Vertex Model Registry o GCS.
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
    # Motivo del cambio de estado (promoción, rollback o promoción forzada).
    reason: str | None = None
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
    """Fila de ``inference_runs``: el inicio (``running``) o el cierre de una
    corrida. Clave: ``run_id`` y ``status``."""

    run_id: NonEmpty
    kind: RunKind
    environment: RunEnvironment
    model_version: NonEmpty | None
    # Versión de tópicos con que corrió (delta y backfill de tópicos).
    topic_model_version: NonEmpty | None = None
    started_at: UtcDatetime
    # Nulo solo en la fila de inicio.
    ended_at: UtcDatetime | None
    reviews: Counter
    texts: Counter
    status: RunStatus
    cost_usd: float | None = None
    peak_memory_mib: Counter | None = None
    # Quién la lanzó a mano y por qué (botones de MLOps o la CLI); nulos en
    # las corridas programadas.
    actor_hash: Digest | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _times(self) -> Self:
        if (self.ended_at is None) != (self.status is RunStatus.RUNNING):
            raise ValueError("only a running row has no ended_at")
        if self.ended_at is not None and self.ended_at < self.started_at:
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
    # Nulo = serie de contexto que nunca alerta (los tópicos).
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
    # Sanitizada antes de guardarse: puede traer datos personales.
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
    """Peso de un token por posición en ``texto_sanitizado``, sin texto.

    ``occlusion_v1`` trae ``weight`` (cuánto sostiene la palabra la clase
    predicha). ``occlusion_v2`` trae ``d_neg``, ``d_neu`` y ``d_pos``: el
    cambio de cada probabilidad calibrada al quitar la palabra; ``d_neg > 0``
    quiere decir que la palabra empuja hacia ``NEG``.
    """

    start: Counter
    end: Counter
    weight: float | None = None
    d_neg: float | None = None
    d_neu: float | None = None
    d_pos: float | None = None

    @model_validator(mode="after")
    def _span(self) -> Self:
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        deltas = (self.d_neg, self.d_neu, self.d_pos)
        if self.weight is None:
            if any(d is None for d in deltas):
                raise ValueError("weight or all of d_neg, d_neu, d_pos")
        elif any(d is not None for d in deltas):
            raise ValueError("weight excludes d_neg, d_neu, d_pos")
        return self


class ReviewExplanation(_AnalyticsRecord):
    """Fila de ``review_explanations``: texto × versión de modelo × método."""

    text_key: Digest
    model_version: NonEmpty
    method: Literal["occlusion_v1", "occlusion_v2"]
    attributions: list[TokenAttribution]
    source: ExplanationSource
    computed_at: UtcDatetime

    @model_validator(mode="after")
    def _shape(self) -> Self:
        directed = self.method == "occlusion_v2"
        if any((a.weight is None) != directed for a in self.attributions):
            raise ValueError(
                f"{self.method} attributions have the wrong fields"
            )
        return self


class ModelQuality(_AnalyticsRecord):
    """Fila de ``model_quality``: modelo × periodo × señal."""

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


class ModelQualityMessage(_AnalyticsRecord):
    """Payload de ``voc-model-quality-topic``; sin texto ni PII.

    Solo se publican los avisos (``warning``, ``retrain``, ``rejected``); no
    disparan nada solos: los revisa quien opera el modelo.
    """

    signal: QualitySignal
    status: QualityStatus
    model_version: NonEmpty | None = None
    llm_model: NonEmpty | None = None
    prompt_version: NonEmpty | None = None
    period: NonEmpty
    value: float
    threshold: float | None = None
    n: Counter
    risk_policy_version: NonEmpty | None = None
    computed_at: UtcDatetime

    @model_validator(mode="after")
    def _notice(self) -> Self:
        if self.status is QualityStatus.OK:
            raise ValueError("only warnings are published")
        return self

    @classmethod
    def from_quality(cls, row: "ModelQuality") -> "ModelQualityMessage":
        return cls.model_validate(row.model_dump(exclude={"ci_low", "ci_high"}))


class PromotionCheckResult(_AnalyticsRecord):
    """Fila de ``promotion_checks``: la regla de promoción de un candidato.

    Diferencias pareadas candidato − vigente en el oro *dev*, ponderadas por
    1/π, con su IC del 95 % por *bootstrap*. Se guarda al verificar el
    *re-scoring* del candidato, para que la pantalla de promoción la muestre
    sin recalcularla. El veredicto sigue la regla: peor si algún IC queda
    entero bajo 0; mejor si alguno queda entero sobre 0; si no, empate.
    """

    candidate_version: NonEmpty
    current_version: NonEmpty
    gold_version: NonEmpty
    n: PositiveInt
    kappa_diff: float
    kappa_ci_low: float
    kappa_ci_high: float
    macro_f1_diff: float
    macro_f1_ci_low: float
    macro_f1_ci_high: float
    verdict: PromotionVerdict
    run_id: NonEmpty
    computed_at: UtcDatetime

    @model_validator(mode="after")
    def _rule(self) -> Self:
        if self.candidate_version == self.current_version:
            raise ValueError("candidate must differ from the current version")
        intervals = (
            (self.kappa_ci_low, self.kappa_diff, self.kappa_ci_high),
            (self.macro_f1_ci_low, self.macro_f1_diff, self.macro_f1_ci_high),
        )
        if any(not low <= diff <= high for low, diff, high in intervals):
            raise ValueError("each difference must lie inside its interval")
        if any(high < 0 for _, _, high in intervals):
            expected = PromotionVerdict.WORSE
        elif any(low > 0 for low, _, _ in intervals):
            expected = PromotionVerdict.BETTER
        else:
            expected = PromotionVerdict.TIE
        if self.verdict is not expected:
            raise ValueError(
                f"verdict must be {expected.value} for these intervals"
            )
        return self


class GoldLabel(_AnalyticsRecord):
    """Fila de ``gold_labels``: oro *dev* y ``aspects_gold_v2_1``.

    El oro *dev* aleatorio es una muestra estratificada: ``weight`` (1/π) da
    cifras poblacionales en la curva HITL y en PPI. El oro de aspectos es por
    texto único, así que no tiene ``id_resena`` ni peso.
    """

    gold_version: NonEmpty
    split: GoldSplit
    task: HitlTask
    id_resena: NonEmpty | None = None
    text_key: Digest
    label: SentimentLabel | None = None
    families: list[AspectFamily] = []
    flag_update: bool | None = None
    flag_security: bool | None = None
    praise: bool | None = None
    weight: float | None = None
    guideline_version: NonEmpty
    loaded_at: UtcDatetime

    @model_validator(mode="after")
    def _task_fields(self) -> Self:
        if self.weight is not None and self.weight <= 0:
            raise ValueError("weight must be positive")
        flags = (self.flag_update, self.flag_security, self.praise)
        if self.task is HitlTask.SENTIMENT:
            if (
                self.label is None
                or self.families
                or any(flag is not None for flag in flags)
            ):
                raise ValueError("sentiment gold has a label and no aspects")
            if self.id_resena is None or self.weight is None:
                raise ValueError("sentiment gold needs id_resena and weight")
        elif self.task is HitlTask.ASPECTS:
            if self.label is not None or any(flag is None for flag in flags):
                raise ValueError(
                    "aspects gold has flags and no sentiment label"
                )
            if len(set(self.families)) != len(self.families):
                raise ValueError("families must not repeat")
            if self.weight is not None:
                raise ValueError("aspects gold has no design weight")
        else:
            raise ValueError("gold_labels holds sentiment or aspects only")
        expected = {GoldSplit.DEV: HitlTask.SENTIMENT}.get(
            self.split, HitlTask.ASPECTS
        )
        if self.task is not expected:
            raise ValueError(f"split {self.split} holds {expected} labels")
        return self
