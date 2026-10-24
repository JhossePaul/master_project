"""Ciclo de vida del modelo de sentimiento: curva, política y promoción.

El orden es *re-scoring* → promoción (decisión del autor, 2026-10-24). La
vista ``review_predictions_current`` solo muestra la versión promovida, así
que un candidato se predice completo antes (``rescore``: sus filas entran a
``review_predictions`` sin verse) y la promoción cambia el cockpit y el
delta de una vez. Sin ese orden, entre promover y terminar el *re-scoring*
la vista quedaría vacía y el delta re-predeciría el corpus en CPU.

* **Curva** (``recompute_curve``): cobertura y riesgo del umbral de revisión
  sobre el oro *dev* aleatorio (``gold_labels``, pesos 1 / π), con la
  probabilidad máxima calibrada de la versión, como en la calibración
  (``docs/analytics/calibration/calibration_report.md``). Cada cobertura se
  traduce a revisiones y minutos por semana con el volumen real (textos
  únicos que predijo el modelo, media de las 8 semanas completas más
  recientes, por banco y en total) y la mediana de ``seconds_spent`` de las
  revisiones de sentimiento. En el oro, la T se ajustó con el mismo *dev*:
  la curva es algo optimista, como la de la calibración sin validación
  cruzada.
* **Política** (``propose_risk_policy``): la versión siguiente de la
  ``risk_policy`` vigente con el umbral equivalente a su cobertura en la
  curva nueva. Solo se inserta con quién y por qué (la promoción o el
  comando ``risk-policy``).
* **Regla de promoción** (``check_promotion``): la de la competencia de
  modelos (``docs/analytics/sentiment/sentiment_models_protocol.md``): un
  modelo más caro reemplaza a uno más barato si la diferencia pareada en κ
  o macro-F1 en el oro *dev* excluye el 0, o si iguala y el costo lo
  permite. Un reentrenamiento cuesta lo mismo, así que se promueve si es
  mejor o empata, y se niega si es significativamente peor en alguna de las
  dos (decisión del autor, 2026-10-24); ``force`` promueve igual. Métricas
  ponderadas por 1 / π, *bootstrap* estratificado por banco × periodo del
  oro con 2 000 réplicas.
* **Rollback:** promover una versión que ya estuvo promovida. Sus
  predicciones siguen en la tabla: no se re-predice ni se evalúa la regla.
"""

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

import numpy as np
from voc_common.operations_v3 import ModelVersion
from voc_common.policies import CoveragePoint, HitlCoverageCurve, RiskPolicy
from voc_nlp.agreement import cohen_kappa, macro_f1
from voc_nlp.selective import at_coverage, boot_risk, resample

from ml_inference import registry
from ml_inference.bq_io import StagingMergeWriter, query_rows, render
from ml_inference.config import InferenceSettings
from ml_inference.monitor.quality import GOLD_VERSION
from ml_inference.seed import SECONDS_PER_REVIEW

log = logging.getLogger(__name__)

CLASSES: Final = ("NEG", "NEU", "POS")
COVERAGES: Final = (0.8, 0.85, 0.9, 0.95, 0.98, 1.0)
WEEKS: Final = 8
# Revisiones mínimas para usar la mediana medida en lugar de la de partida.
MIN_TIMED_REVIEWS: Final = 30
RULE_BOOT: Final = 2000
RULE_SEED: Final = 20261019

Verdict = Literal["better", "tie", "worse"]


class PromotionRefused(RuntimeError):
    """El candidato es significativamente peor que la versión vigente."""


@dataclass(frozen=True)
class GoldPrediction:
    """Reseña del oro *dev* con la predicción de una versión (sin texto)."""

    id_resena: str
    label: str
    weight: float
    stratum: str
    predicted: str
    confidence: float | None
    """Probabilidad máxima calibrada; ``None`` si no la predijo el modelo."""


@dataclass(frozen=True)
class Difference:
    metric: str
    value: float
    ci: tuple[float, float]


@dataclass(frozen=True)
class PromotionCheck:
    n: int
    differences: tuple[Difference, ...]

    @property
    def verdict(self) -> Verdict:
        if any(d.ci[1] < 0 for d in self.differences):
            return "worse"
        if any(d.ci[0] > 0 for d in self.differences):
            return "better"
        return "tie"

    def describe(self) -> str:
        parts = [
            f"{d.metric} {d.value:+.4f} [{d.ci[0]:+.4f}, {d.ci[1]:+.4f}]"
            for d in self.differences
        ]
        return f"{self.verdict} (n={self.n}): " + "; ".join(parts)


def gold_period(year: int) -> str:
    """Periodo del diseño del oro (estrato banco × periodo)."""
    if year <= 2019:
        return "<=2019"
    if year <= 2022:
        return "2020-2022"
    if year <= 2024:
        return "2023-2024"
    return "2025-2026"


# -- Curva -------------------------------------------------------------------


def curve_points(
    gold: Sequence[GoldPrediction],
    weekly_total: float,
    seconds_per_review: float,
    n_boot: int = 1000,
) -> list[CoveragePoint]:
    """Puntos de la curva en ``COVERAGES``; IC del riesgo salvo en 1.0."""
    scored = [g for g in gold if g.confidence is not None]
    if not scored:
        raise ValueError("no gold review has model probabilities")
    conf = np.array([g.confidence for g in scored], dtype=np.float64)
    err = np.array([g.predicted != g.label for g in scored], dtype=np.float64)
    w = np.array([g.weight for g in scored], dtype=np.float64)
    strata = np.array([g.stratum for g in scored])
    points = []
    for target in COVERAGES:
        point = at_coverage(conf, err, w, target)
        ci = (
            boot_risk(conf, err, w, strata, target, n_boot=n_boot)
            if target < 1.0
            else (None, None)
        )
        reviews = (1 - point.coverage) * weekly_total
        # Con pocos ítems, un percentil puede quedar del otro lado del punto;
        # el contrato pide que el intervalo lo contenga.
        points.append(
            CoveragePoint(
                coverage=point.coverage,
                risk=point.risk,
                risk_ci_low=None if ci[0] is None else min(ci[0], point.risk),
                risk_ci_high=None if ci[1] is None else max(ci[1], point.risk),
                threshold=point.threshold,
                errors_caught=point.errors_caught,
                reviews_per_week=round(reviews, 1),
                minutes_per_week=round(reviews * seconds_per_review / 60, 1),
            )
        )
    # Dos objetivos pueden caer en el mismo punto con pocos ítems.
    unique = {p.coverage: p for p in points}
    return [unique[c] for c in sorted(unique)]


def build_curve(
    model: ModelVersion,
    gold: Sequence[GoldPrediction],
    weekly_by_bank: Mapping[str, float],
    weekly_total: float,
    seconds_per_review: float,
    now: datetime,
    n_boot: int = 1000,
) -> HitlCoverageCurve:
    return HitlCoverageCurve(
        model_version=model.model_version,
        calibration_version=model.calibration_version,
        points=curve_points(gold, weekly_total, seconds_per_review, n_boot),
        weekly_volume_total=round(weekly_total),
        weekly_volume_by_bank={
            bank: round(v) for bank, v in sorted(weekly_by_bank.items())
        },
        computed_at=now,
    )


# -- Política ----------------------------------------------------------------


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


# -- Regla de promoción ------------------------------------------------------


def _metrics(
    y: np.ndarray, pred: np.ndarray, w: np.ndarray
) -> dict[str, float]:
    return {
        "kappa": cohen_kappa(list(y), list(pred), w),
        "macro_f1": macro_f1(list(y), list(pred), CLASSES, w),
    }


def check_promotion(
    current: Sequence[GoldPrediction],
    candidate: Sequence[GoldPrediction],
    n_boot: int = RULE_BOOT,
    seed: int = RULE_SEED,
) -> PromotionCheck:
    """Diferencia pareada candidato − vigente en κ y macro-F1 ponderados."""
    mine = {g.id_resena: g for g in candidate}
    pairs = [(c, mine[c.id_resena]) for c in current if c.id_resena in mine]
    if not pairs:
        raise ValueError("the versions share no gold review")
    y = np.array([c.label for c, _ in pairs], dtype=object)
    a = np.array([c.predicted for c, _ in pairs], dtype=object)
    b = np.array([d.predicted for _, d in pairs], dtype=object)
    w = np.array([c.weight for c, _ in pairs], dtype=np.float64)
    strata = np.array([c.stratum for c, _ in pairs])
    base, new = _metrics(y, a, w), _metrics(y, b, w)
    rng = np.random.default_rng(seed)
    boots: dict[str, list[float]] = {k: [] for k in base}
    for _ in range(n_boot):
        i = resample(strata, rng)
        mb, ma = _metrics(y[i], b[i], w[i]), _metrics(y[i], a[i], w[i])
        for k in boots:
            boots[k].append(mb[k] - ma[k])
    return PromotionCheck(
        n=len(pairs),
        differences=tuple(
            Difference(
                metric=k,
                value=new[k] - base[k],
                ci=(
                    float(np.percentile(v, 2.5)),
                    float(np.percentile(v, 97.5)),
                ),
            )
            for k, v in boots.items()
        ),
    )


# -- Lectura -----------------------------------------------------------------

# Última fila por reseña de la versión, sin pasar por la vista (que solo
# muestra la promovida).
GOLD_SQL: Final = """
SELECT g.id_resena, g.label, g.weight, p.bank_id, p.fecha, p.sentiment,
  p.label_source, p.p_neg, p.p_neu, p.p_pos
FROM `${ds}.gold_labels` AS g
JOIN (
  SELECT * FROM `${ds}.review_predictions`
  WHERE model_version = @model_version
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY id_resena ORDER BY fecha DESC, predicted_at DESC
  ) = 1
) AS p USING (id_resena)
WHERE g.gold_version = @gold_version AND g.split = 'dev'
  AND g.task = 'sentiment' AND g.label IS NOT NULL
"""

VOLUME_SQL: Final = """
SELECT bank_id, DATE_TRUNC(DATE(fecha), ISOWEEK) AS week,
  COUNT(DISTINCT text_key) AS texts
FROM `${ds}.review_predictions_current`
WHERE label_source = 'MODEL' AND fecha >= @start AND fecha < @end
GROUP BY GROUPING SETS ((bank_id, week), (week))
"""

SECONDS_SQL: Final = """
SELECT APPROX_QUANTILES(seconds_spent, 2)[OFFSET(1)] AS median,
  COUNT(*) AS n
FROM `${ds}.hitl_reviews`
WHERE task = 'sentiment' AND submitted_at >= @start AND submitted_at < @end
"""


def gold_predictions(
    rows: Iterable[Mapping[str, Any]],
) -> list[GoldPrediction]:
    out = []
    for r in rows:
        probs = [r.get(k) for k in ("p_neg", "p_neu", "p_pos")]
        scored = r.get("label_source") == "MODEL" and None not in probs
        predicted = r["sentiment"]
        fecha = r["fecha"]
        year = (
            fecha.year if isinstance(fecha, datetime) else int(str(fecha)[:4])
        )
        out.append(
            GoldPrediction(
                id_resena=r["id_resena"],
                label=r["label"],
                weight=float(r["weight"]),
                stratum=f"{r['bank_id']}|{gold_period(year)}",
                # Sin una de las tres clases cuenta como NEU, como al
                # evaluar los modelos.
                predicted=predicted if predicted in CLASSES else "NEU",
                confidence=max(float(x) for x in probs) if scored else None,
            )
        )
    return out


def week_window(now: datetime) -> tuple[datetime, datetime]:
    """Las ``WEEKS`` semanas ISO completas antes de ``now``."""
    day = now.astimezone(UTC).date()
    monday = day - timedelta(days=day.weekday())
    end = datetime(monday.year, monday.month, monday.day, tzinfo=UTC)
    return end - timedelta(weeks=WEEKS), end


def weekly_volume(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, float], float]:
    """Media semanal de textos únicos por banco y total (fila sin banco)."""
    by_bank: dict[str, float] = {}
    total = 0.0
    for r in rows:
        if r["bank_id"] is None:
            total += int(r["texts"]) / WEEKS
        else:
            bank = r["bank_id"]
            by_bank[bank] = by_bank.get(bank, 0.0) + int(r["texts"]) / WEEKS
    return by_bank, total


@dataclass
class Lifecycle:
    client: Any
    writer: StagingMergeWriter
    dataset: str
    gold_version: str = GOLD_VERSION

    def _rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        return query_rows(self.client, render(sql, ds=self.dataset), params)

    def gold(self, model_version: str) -> list[GoldPrediction]:
        return gold_predictions(
            self._rows(
                GOLD_SQL,
                model_version=model_version,
                gold_version=self.gold_version,
            )
        )

    def seconds_per_review(self, now: datetime) -> float:
        start, end = week_window(now)
        rows = self._rows(SECONDS_SQL, start=start, end=end)
        if not rows or int(rows[0]["n"] or 0) < MIN_TIMED_REVIEWS:
            return SECONDS_PER_REVIEW
        return float(rows[0]["median"])

    def recompute_curve(
        self,
        model: ModelVersion,
        now: datetime,
        gold: Sequence[GoldPrediction] | None = None,
    ) -> HitlCoverageCurve:
        """Recalcula la curva de ``model`` y la guarda."""
        gold = self.gold(model.model_version) if gold is None else gold
        start, end = week_window(now)
        by_bank, total = weekly_volume(
            self._rows(VOLUME_SQL, start=start, end=end)
        )
        curve = build_curve(
            model, gold, by_bank, total, self.seconds_per_review(now), now
        )
        self.writer.write(
            "hitl_coverage_curves",
            [curve],
            ["model_version", "calibration_version", "computed_at"],
            f"curve-{model.model_version}",
        )
        log.info(
            "curva de %s: %d puntos, %d textos por semana",
            model.model_version,
            len(curve.points),
            curve.weekly_volume_total,
        )
        return curve

    def current_policy(self) -> RiskPolicy | None:
        rows = self._rows("SELECT * FROM `${ds}.risk_policy_current`")
        return RiskPolicy.model_validate(rows[0]) if rows else None

    def write_policy(self, policy: RiskPolicy) -> None:
        self.writer.write(
            "risk_policy",
            [policy],
            ["policy_version"],
            f"policy-{policy.policy_version}",
        )

    def set_coverage(
        self,
        model: ModelVersion,
        coverage: float,
        actor_hash: str,
        reason: str,
        now: datetime,
    ) -> RiskPolicy:
        """Nueva ``risk_policy`` con otra cobertura, sobre la última curva."""
        current = self.current_policy()
        if current is None:
            raise LookupError("risk_policy has no current version")
        rows = self._rows(
            "SELECT * FROM `${ds}.hitl_coverage_curves` "
            "WHERE model_version = @mv AND calibration_version = @cv "
            "ORDER BY computed_at DESC LIMIT 1",
            mv=model.model_version,
            cv=model.calibration_version,
        )
        if not rows:
            raise LookupError(f"{model.model_version} has no coverage curve")
        curve = HitlCoverageCurve.model_validate(rows[0])
        policy = propose_risk_policy(
            curve, current, actor_hash, reason, now, coverage
        )
        self.write_policy(policy)
        return policy


def promote_version(
    settings: InferenceSettings,
    lifecycle: Lifecycle,
    *,
    model_version: str,
    actor_hash: str,
    reason: str,
    now: datetime,
    force: bool = False,
) -> ModelVersion:
    """Regla, curva, alias y política de una promoción o un *rollback*."""
    versions = registry.latest_versions(lifecycle.client, lifecycle.dataset)
    if model_version not in versions:
        raise LookupError(f"{model_version} is not in model_versions")
    target = versions[model_version]
    if target.status.value == "promoted":
        raise ValueError(f"{model_version} is already promoted")
    current = next(
        (v for v in versions.values() if v.status.value == "promoted"), None
    )
    gold = lifecycle.gold(model_version)
    if not gold:
        raise LookupError(
            f"{model_version} has no predictions on the dev gold: "
            "run rescore before promoting"
        )
    rollback = target.promoted_at is not None
    if current is not None and not rollback:
        check = check_promotion(lifecycle.gold(current.model_version), gold)
        log.info("regla de promoción: %s", check.describe())
        if check.verdict == "worse":
            if not force:
                raise PromotionRefused(check.describe())
            log.warning("promoción forzada por %s: %s", actor_hash, reason)
    curve = lifecycle.recompute_curve(target, now, gold)
    policy = lifecycle.current_policy()
    promoted = registry.promote(
        settings,
        lifecycle.writer,
        lifecycle.client,
        model_version=model_version,
        actor_hash=actor_hash,
        reason=reason,
        now=now,
    )
    if policy is None:
        log.warning("promote: sin risk_policy vigente; no se propone otra")
    else:
        lifecycle.write_policy(
            propose_risk_policy(curve, policy, actor_hash, reason, now)
        )
    return promoted
