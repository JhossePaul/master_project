"""Calidad del modelo de sentimiento y de las familias → ``model_quality``.

Cada medición es una fila (sujeto × señal × periodo) que no se repite. Los
avisos se publican sin texto en ``voc-model-quality-topic`` y los revisa
quien opera el modelo. La única excepción es ``retrain`` con
``retrain_trigger = auto``: lanza el Job ``voc-ml-training`` si no hubo un
reentrenamiento en el trimestre ni hay uno en curso. El candidato se
re-predice, pero nunca se promueve solo.

* ``kappa_monitor``: κ del modelo contra la primera revisión humana de la
  muestra de concepto del último trimestre cerrado (``samples``), cuando
  toda la muestra está revisada. Pide reentrenar (``retrain``) si queda
  debajo de ``retrain_kappa_floor``.
* ``correction_rate``: proporción de revisiones de la cola (baja confianza y
  subidas por deriva) de las últimas 4 semanas que corrigen al modelo.
  ``warning`` si pasa de ``warn_correction_rate``.
* ``gemini_agreement``: cada semana, ``agreement_sample_weekly`` textos al
  azar que predijo el modelo en la semana cerrada se etiquetan con Gemini y
  el mismo prompt de la plata con que se entrenó el modelo. La fila guarda
  el acuerdo de esa semana (sin los textos que Gemini marca como no
  evaluables); el aviso se decide con el acuerdo combinado de las últimas 4
  semanas, contra ``warn_agreement_floor``.
* ``families_validation``: una vez por cada modelo y prompt de Gemini para
  familias, se etiquetan las 300 reseñas del oro de aspectos. Se rechaza si
  el acuerdo exacto queda debajo de ``families_exact_floor`` o si una
  familia con prevalencia ≥ ``families_min_prevalence`` queda con κ debajo
  del límite inferior de su intervalo de referencia (``FAMILY_BASELINE``,
  medido al elegir el prompt; ver ``docs/analytics/scale/scale_report.md``).

El texto que va a Gemini es ``texto_sanitizado`` y no sale de Vertex AI en el
proyecto.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import numpy as np
from voc_common.analytics_codes import (
    QualitySignal,
    QualityStatus,
    RetrainTrigger,
    RunKind,
)
from voc_common.operations_v3 import ModelQuality, ModelQualityMessage
from voc_common.policies import RiskPolicy
from voc_nlp.agreement import (
    cohen_kappa,
    exact_agreement,
    exact_agreement_ci,
    family_kappa,
)
from voc_nlp.sentiment_gemini import NOT_EVALUABLE

from ml_inference.bq_io import StagingMergeWriter, query_rows, render
from ml_inference.jobs import JobRunner
from ml_inference.monitor.samples import (
    last_closed_period,
    period_bounds,
    period_of,
)
from ml_inference.runs import running

log = logging.getLogger(__name__)

BOOT: Final = 2000
SEED: Final = 20261022
Z: Final = 1.959964
CORRECTION_WEEKS: Final = 4
AGREEMENT_WEEKS: Final = 4
GOLD_VERSION: Final = "gold_epic5_v1"
FAMILIES_SPLIT: Final = "aspects_gold_v2_1"
# Límite inferior del IC 95 % del κ por familia de gemini-3.6-flash con el
# prompt de familias vigente, contra la anotación humana de las mismas 300
# reseñas (docs/analytics/scale/model_monitor_v0_metrics.json).
FAMILY_BASELINE: Final[Mapping[str, float]] = {
    "AC": 0.5982,
    "TR": 0.5439,
    "DI": 0.2405,
    "PR": 0.4708,
    "AT": 0.4842,
    "FA": 0.4385,
    "LE": 0.7409,
    "CO": 0.6378,
    "DV": 0.5174,
    "UX": 0.6208,
    "OT": 0.0,
}
QUALITY_KEY: Final = (
    "model_version",
    "llm_model",
    "prompt_version",
    "signal",
    "period",
)


# -- Mediciones --------------------------------------------------------------


def _boot_kappa(
    a: Sequence[str], b: Sequence[str], n_boot: int
) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    x, y, n = np.asarray(a), np.asarray(b), len(a)
    ks = []
    for _ in range(n_boot):
        i = rng.integers(0, n, n)
        ks.append(cohen_kappa(list(x[i]), list(y[i])))
    return float(np.percentile(ks, 2.5)), float(np.percentile(ks, 97.5))


def kappa_monitor(
    predicted: Sequence[str],
    validated: Sequence[str],
    quarter: str,
    model_version: str,
    policy: RiskPolicy,
    now: datetime,
    n_boot: int = BOOT,
) -> ModelQuality:
    """κ del modelo en la muestra de concepto; ``retrain`` bajo el piso."""
    value = cohen_kappa(predicted, validated)
    low, high = _boot_kappa(predicted, validated, n_boot)
    floor = policy.retrain_kappa_floor
    return ModelQuality(
        model_version=model_version,
        signal=QualitySignal.KAPPA_MONITOR,
        period=quarter,
        value=value,
        n=len(predicted),
        ci_low=low,
        ci_high=high,
        threshold=floor,
        status=QualityStatus.RETRAIN if value < floor else QualityStatus.OK,
        risk_policy_version=policy.policy_version,
        computed_at=now,
    )


def correction_rate(
    corrected: Sequence[bool],
    period: str,
    model_version: str,
    policy: RiskPolicy,
    now: datetime,
) -> ModelQuality:
    """Proporción corregida en la cola; ``warning`` arriba del umbral."""
    n = len(corrected)
    value = float(np.mean(corrected))
    half = Z * (value * (1 - value) / n) ** 0.5
    limit = policy.warn_correction_rate
    return ModelQuality(
        model_version=model_version,
        signal=QualitySignal.CORRECTION_RATE,
        period=period,
        value=value,
        n=n,
        ci_low=max(value - half, 0.0),
        ci_high=min(value + half, 1.0),
        threshold=limit,
        status=QualityStatus.WARNING if value > limit else QualityStatus.OK,
        risk_policy_version=policy.policy_version,
        computed_at=now,
    )


def gemini_agreement(
    model_labels: Sequence[str],
    gemini_labels: Sequence[str],
    previous: Sequence[tuple[float, int]],
    week: str,
    model_version: str,
    policy: RiskPolicy,
    now: datetime,
) -> ModelQuality | None:
    """Acuerdo de la semana con Gemini; el aviso mira 4 semanas.

    ``previous`` son ``(acuerdo, n)`` de hasta 3 semanas anteriores. Los
    textos que Gemini marca como no evaluables no cuentan; sin textos
    evaluables no hay fila.
    """
    pairs = [
        (m, g)
        for m, g in zip(model_labels, gemini_labels, strict=True)
        if g != NOT_EVALUABLE
    ]
    if not pairs:
        return None
    n = len(pairs)
    value = sum(m == g for m, g in pairs) / n
    half = Z * (value * (1 - value) / n) ** 0.5
    weeks = [(value, n), *previous[: AGREEMENT_WEEKS - 1]]
    combined = sum(v * k for v, k in weeks) / sum(k for _, k in weeks)
    floor = policy.warn_agreement_floor
    return ModelQuality(
        model_version=model_version,
        signal=QualitySignal.GEMINI_AGREEMENT,
        period=week,
        value=value,
        n=n,
        ci_low=max(value - half, 0.0),
        ci_high=min(value + half, 1.0),
        threshold=floor,
        status=QualityStatus.WARNING if combined < floor else QualityStatus.OK,
        risk_policy_version=policy.policy_version,
        computed_at=now,
    )


def families_validation(
    gold: Sequence[frozenset[str]],
    gemini: Sequence[frozenset[str]],
    llm_model: str,
    prompt_version: str,
    policy: RiskPolicy,
    now: datetime,
    baseline: Mapping[str, float] = FAMILY_BASELINE,
    n_boot: int = BOOT,
) -> tuple[ModelQuality, list[str]]:
    """Revalidación de las familias; devuelve la fila y las que fallan."""
    value = exact_agreement(gold, gemini)
    low, high = exact_agreement_ci(gold, gemini, n_boot)
    failing = []
    for family, floor in sorted(baseline.items()):
        result = family_kappa(gold, gemini, family, n_boot)
        if (
            result.prevalence >= policy.families_min_prevalence
            and result.kappa < floor
        ):
            failing.append(family)
    rejected = value < policy.families_exact_floor or bool(failing)
    row = ModelQuality(
        llm_model=llm_model,
        prompt_version=prompt_version,
        signal=QualitySignal.FAMILIES_VALIDATION,
        period=now.date().isoformat(),
        value=value,
        n=len(gold),
        ci_low=low,
        ci_high=high,
        threshold=policy.families_exact_floor,
        status=QualityStatus.REJECTED if rejected else QualityStatus.OK,
        risk_policy_version=policy.policy_version,
        computed_at=now,
    )
    return row, failing


def iso_week(now: datetime) -> str:
    year, week, _ = now.astimezone(UTC).isocalendar()
    return f"{year}-W{week:02d}"


def last_closed_week(now: datetime) -> tuple[str, datetime, datetime]:
    """Semana ISO anterior a la de ``now``: nombre, inicio y fin (UTC)."""
    day = now.astimezone(UTC)
    monday = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(
        days=day.weekday()
    )
    start = monday - timedelta(weeks=1)
    return iso_week(start), start, monday


# -- Lectura y escritura -----------------------------------------------------

MEASURED_SQL: Final = """
SELECT model_version, llm_model, prompt_version, signal, period
FROM `${ds}.model_quality`
"""

SAMPLE_SQL: Final = """
SELECT i.item_id, r.predicted_label, r.validated_label
FROM `${ds}.hitl_items` AS i
LEFT JOIN `${ds}.hitl_reviews` AS r
  ON r.item_id = i.item_id AND r.review_round = 1
WHERE i.reason = 'monitor_sample'
  AND STARTS_WITH(i.item_id, @prefix)
  AND i.model_version = @model_version
"""

CORRECTIONS_SQL: Final = """
SELECT r.outcome
FROM `${ds}.hitl_reviews` AS r
JOIN `${ds}.hitl_items` AS i USING (item_id)
WHERE i.reason IN ('low_confidence', 'drift_boost')
  AND r.task = 'sentiment'
  AND r.review_round = 1
  AND i.model_version = @model_version
  AND r.submitted_at >= @since AND r.submitted_at < @until
"""

FAMILIES_SQL: Final = """
SELECT g.text_key, g.families, t.texto_sanitizado
FROM `${ds}.gold_labels` AS g
JOIN (
  SELECT DISTINCT TO_HEX(SHA256(texto_sanitizado)) AS text_key,
    texto_sanitizado
  FROM `${tds}`
) AS t USING (text_key)
WHERE g.gold_version = @gold_version AND g.split = @split
  AND g.task = 'aspects'
"""

# Sorteo reproducible en BigQuery: solo salen los textos elegidos.
AGREEMENT_SQL: Final = """
SELECT p.text_key, ANY_VALUE(p.sentiment) AS sentiment,
  ANY_VALUE(t.texto_sanitizado) AS texto_sanitizado
FROM `${ds}.review_predictions_current` AS p
JOIN `${tds}` AS t
  ON t.id_resena = p.id_resena
  AND TO_HEX(SHA256(t.texto_sanitizado)) = p.text_key
WHERE p.label_source = 'MODEL'
  AND p.model_version = @model_version
  AND p.fecha >= @start AND p.fecha < @end
GROUP BY p.text_key
ORDER BY FARM_FINGERPRINT(CONCAT(@seed, p.text_key))
LIMIT @size
"""

PREVIOUS_AGREEMENT_SQL: Final = """
SELECT value, n
FROM `${ds}.model_quality`
WHERE signal = 'gemini_agreement' AND model_version = @model_version
  AND period < @week
ORDER BY period DESC
LIMIT @weeks
"""

# ``(key, texto)`` → ``{key: etiqueta}``; los textos sin etiqueta faltan.
SentimentLabeler = Callable[[Sequence[tuple[str, str]]], Mapping[str, str]]

# Reentrenamientos registrados desde el inicio del trimestre en curso.
TRAININGS_SQL: Final = """
SELECT COUNT(*) AS trainings FROM `${ds}.inference_runs`
WHERE kind = 'training' AND started_at >= @since
"""

# ``(key, texto)`` → ``{key: familias}``; los textos sin etiqueta faltan.
FamilyLabeler = Callable[
    [Sequence[tuple[str, str]]], Mapping[str, frozenset[str]]
]


@dataclass
class QualityJob:
    client: Any
    writer: StagingMergeWriter
    dataset: str
    tds: str
    publish: Callable[[ModelQualityMessage], None]
    run_id: str
    family_labeler: FamilyLabeler | None = None
    sentiment_labeler: SentimentLabeler | None = None
    llm_model: str = "gemini-3.6-flash"
    prompt_version: str = "aspects_v2_1"
    # Sin él, un ``retrain`` en modo ``auto`` solo se avisa.
    jobs: JobRunner | None = None
    training_job: str = "voc-ml-training"
    # Tiempo máximo del Job de entrenamiento: una fila ``running`` más
    # vieja es de una corrida muerta.
    training_timeout_sec: int = 14_400
    gold_version: str = GOLD_VERSION
    _measured: set[tuple[Any, ...]] = field(default_factory=set)

    def _rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        sql = render(sql, ds=self.dataset, tds=self.tds)
        return query_rows(self.client, sql, params)

    def _done(self, **subject: Any) -> bool:
        return tuple(subject.get(k) for k in QUALITY_KEY) in self._measured

    def run(
        self, policy: RiskPolicy | None, model_version: str, now: datetime
    ) -> list[ModelQuality]:
        """Mide las señales que faltan, escribe y publica los avisos."""
        if policy is None:
            log.warning("quality: sin risk_policy vigente")
            return []
        self._measured = {
            tuple(r.get(k) for k in QUALITY_KEY)
            for r in self._rows(MEASURED_SQL)
        }
        rows = [
            row
            for row in (
                self._kappa(policy, model_version, now),
                self._corrections(policy, model_version, now),
                self._agreement(policy, model_version, now),
                self._families(policy, now),
            )
            if row is not None
        ]
        self.writer.write("model_quality", rows, list(QUALITY_KEY), self.run_id)
        for row in rows:
            if row.status is not QualityStatus.OK:
                self.publish(ModelQualityMessage.from_quality(row))
        if any(r.status is QualityStatus.RETRAIN for r in rows):
            self._retrain(policy, now)
        log.info(
            "quality: %s", [(r.signal.value, r.status.value) for r in rows]
        )
        return rows

    def _retrain(self, policy: RiskPolicy, now: datetime) -> str | None:
        """Lanza el reentrenamiento en ``auto``, uno por trimestre."""
        if policy.retrain_mode is not RetrainTrigger.AUTO:
            log.info("quality: retrain en modo manual, solo se avisa")
            return None
        if self.jobs is None:
            log.warning("quality: retrain en auto sin lanzador de Jobs")
            return None
        since, _ = period_bounds(
            period_of(now.astimezone(UTC).date(), "quarterly")
        )
        rows = self._rows(TRAININGS_SQL, since=since)
        if rows and int(rows[0]["trainings"]):
            log.info("quality: ya hubo un reentrenamiento este trimestre")
            return None
        in_progress = running(
            self.client,
            self.dataset,
            RunKind.TRAINING,
            now,
            timedelta(seconds=self.training_timeout_sec),
        )
        if in_progress:
            log.info("quality: %s ya está en curso", self.training_job)
            return None
        operation = self.jobs.execute(
            self.training_job,
            ["train", "--reason=retrain automático: κ trimestral bajo el piso"],
        )
        log.info("quality: lanzado %s (%s)", self.training_job, operation)
        return operation

    def _kappa(
        self, policy: RiskPolicy, model_version: str, now: datetime
    ) -> ModelQuality | None:
        quarter = last_closed_period(now, "quarterly")
        signal = QualitySignal.KAPPA_MONITOR
        if self._done(
            model_version=model_version, signal=signal, period=quarter
        ):
            return None
        rows = self._rows(
            SAMPLE_SQL,
            prefix=f"monitor_sample:{quarter}:",
            model_version=model_version,
        )
        reviewed = [r for r in rows if r["validated_label"] is not None]
        if not rows or len(reviewed) < len(rows):
            log.info(
                "quality: muestra %s con %d de %d revisiones",
                quarter,
                len(reviewed),
                len(rows),
            )
            return None
        return kappa_monitor(
            [r["predicted_label"] for r in reviewed],
            [r["validated_label"] for r in reviewed],
            quarter,
            model_version,
            policy,
            now,
        )

    def _corrections(
        self, policy: RiskPolicy, model_version: str, now: datetime
    ) -> ModelQuality | None:
        week = iso_week(now)
        signal = QualitySignal.CORRECTION_RATE
        if self._done(model_version=model_version, signal=signal, period=week):
            return None
        rows = self._rows(
            CORRECTIONS_SQL,
            model_version=model_version,
            since=now - timedelta(weeks=CORRECTION_WEEKS),
            until=now,
        )
        if not rows:
            return None
        return correction_rate(
            [r["outcome"] != "confirmed" for r in rows],
            week,
            model_version,
            policy,
            now,
        )

    def _agreement(
        self, policy: RiskPolicy, model_version: str, now: datetime
    ) -> ModelQuality | None:
        week, start, end = last_closed_week(now)
        signal = QualitySignal.GEMINI_AGREEMENT
        if self.sentiment_labeler is None or self._done(
            model_version=model_version, signal=signal, period=week
        ):
            return None
        rows = self._rows(
            AGREEMENT_SQL,
            model_version=model_version,
            start=start,
            end=end,
            seed=f"{signal.value}:{week}",
            size=policy.agreement_sample_weekly,
        )
        if not rows:
            return None
        labels = self.sentiment_labeler(
            [(r["text_key"], r["texto_sanitizado"]) for r in rows]
        )
        kept = [r for r in rows if r["text_key"] in labels]
        previous = [
            (float(r["value"]), int(r["n"]))
            for r in self._rows(
                PREVIOUS_AGREEMENT_SQL,
                model_version=model_version,
                week=week,
                weeks=AGREEMENT_WEEKS - 1,
            )
        ]
        return gemini_agreement(
            [r["sentiment"] for r in kept],
            [labels[r["text_key"]] for r in kept],
            previous,
            week,
            model_version,
            policy,
            now,
        )

    def _families(
        self, policy: RiskPolicy, now: datetime
    ) -> ModelQuality | None:
        signal = QualitySignal.FAMILIES_VALIDATION
        if self.family_labeler is None or any(
            m[1:4] == (self.llm_model, self.prompt_version, signal.value)
            for m in self._measured
        ):
            return None
        gold = self._rows(
            FAMILIES_SQL, gold_version=self.gold_version, split=FAMILIES_SPLIT
        )
        if not gold:
            log.warning("quality: sin oro de aspectos en gold_labels")
            return None
        labels = self.family_labeler(
            [(g["text_key"], g["texto_sanitizado"]) for g in gold]
        )
        if len(labels) < len(gold):
            log.warning(
                "quality: Gemini etiquetó %d de %d; se repite en la próxima",
                len(labels),
                len(gold),
            )
            return None
        row, failing = families_validation(
            [frozenset(g["families"]) for g in gold],
            [labels[g["text_key"]] for g in gold],
            self.llm_model,
            self.prompt_version,
            policy,
            now,
        )
        if failing:
            log.warning("quality: familias bajo su referencia: %s", failing)
        return row
