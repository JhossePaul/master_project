"""Calidad del modelo y de las familias (P7-10, P7-11; D15) → ``model_quality``.

* ``kappa_monitor``: κ de RoBERTuito contra la primera revisión de la
  muestra de concepto del trimestre (``samples``); ``retrain`` debajo de
  ``retrain_kappa_floor``. Se mide cuando toda la muestra está revisada.
* ``correction_rate``: proporción de revisiones de la cola (``low_confidence``
  y ``drift_boost``) que corrigen al modelo en las últimas 4 semanas;
  ``warning`` arriba de ``warn_correction_rate``.
* ``families_validation``: al cambiar el modelo o el prompt de Gemini, se
  etiquetan las 300 reseñas de ``aspects_gold_v2_1``; ``rejected`` si el
  acuerdo exacto queda debajo de ``families_exact_floor`` o una familia con
  prevalencia ≥ ``families_min_prevalence`` queda con κ debajo del límite
  inferior de su IC de referencia (5.7, ``FAMILY_BASELINE``).
* ``agreement_m4_gemini`` espera el etiquetador de sentimiento con Gemini
  en ``voc-nlp`` (siguiente paso de 6.4).

Cada medición es una fila (clave: sujeto × señal × periodo) y no se repite.
Los avisos se publican sin texto en ``voc-model-quality-topic``; no disparan
nada solos (EPIC-7, 7.9).
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import numpy as np
from voc_common.analytics_codes import QualitySignal, QualityStatus
from voc_common.operations_v3 import ModelQuality, ModelQualityMessage
from voc_common.policies import RiskPolicy
from voc_nlp.agreement import (
    cohen_kappa,
    exact_agreement,
    exact_agreement_ci,
    family_kappa,
)

from ml_inference.bq_io import StagingMergeWriter, query_rows, render
from ml_inference.monitor.samples import last_closed_period

log = logging.getLogger(__name__)

BOOT: Final = 2000
SEED: Final = 20261022
Z: Final = 1.959964
CORRECTION_WEEKS: Final = 4
GOLD_VERSION: Final = "gold_epic5_v1"
FAMILIES_SPLIT: Final = "aspects_gold_v2_1"
# Límite inferior del IC 95 % del κ por familia de gemini-3.6-flash con
# aspects_v2_1 en muestra_v21 (5.7, model_monitor_v0_metrics.json).
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
    labeler: FamilyLabeler | None = None
    llm_model: str = "gemini-3.6-flash"
    prompt_version: str = "aspects_v2_1"
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
                self._families(policy, now),
            )
            if row is not None
        ]
        self.writer.write("model_quality", rows, list(QUALITY_KEY), self.run_id)
        for row in rows:
            if row.status is not QualityStatus.OK:
                self.publish(ModelQualityMessage.from_quality(row))
        log.info(
            "quality: %s", [(r.signal.value, r.status.value) for r in rows]
        )
        return rows

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

    def _families(
        self, policy: RiskPolicy, now: datetime
    ) -> ModelQuality | None:
        signal = QualitySignal.FAMILIES_VALIDATION
        if self.labeler is None or any(
            m[1:4] == (self.llm_model, self.prompt_version, signal.value)
            for m in self._measured
        ):
            return None
        gold = self._rows(
            FAMILIES_SQL, gold_version=GOLD_VERSION, split=FAMILIES_SPLIT
        )
        if not gold:
            log.warning("quality: sin oro de aspectos en gold_labels")
            return None
        labels = self.labeler(
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
