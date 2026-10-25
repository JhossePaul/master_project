"""Monitor de deriva por banco.

Cada semana, por banco y con su ``drift_policy`` vigente, calcula los meses
cerrados que faltan en ``drift_metrics`` desde su mes de entrada (excluido,
como en el análisis histórico). Cada serie que nombra la política se mide
con z robusto contra
sus ``baseline_months`` previos o con PSI contra su suma; una serie con
umbral nulo se guarda como contexto y nunca alerta (familias, ``u`` y las
dos de tópicos).

Series de tópicos, de la versión vigente y sobre las negativas de dos
palabras o más con asignación (contexto hasta tener trimestres de datos):

* ``topic_noise_share``: cláusulas que ningún tópico asigna (``-1``) entre
  las asignadas;
* ``topic_unaligned_share``: negativas con algún tópico (sin contar el
  ruido) cuyos tópicos no tienen ninguna familia en la curaduría vigente.

Solo el último mes cerrado alerta (decisión del autor, 2026-10-24): la
primera corrida llena la historia, y sus meses anteriores quedan en
``drift_metrics`` con su marca ``alert`` (con ella se miden las tasas
históricas), sin abrir alertas, publicar ni crear subidas.

Una alerta (``|z|`` o PSI ≥ umbral) se escribe en ``drift_alerts`` con su
evento ``open``, se publica sin texto en ``voc-incident-alerts-topic`` y, si
la ``risk_policy`` vigente configura la subida, abre una en
``hitl_boosts`` solo para ese banco; si el banco ya tiene una activa, la
alerta la cita y no se abre otra. Los identificadores son deterministas y
las métricas se escriben al final: si la corrida falla, la siguiente repite
el mes sin duplicar filas (el mensaje puede llegar dos veces).

``close_boosts`` inserta la fila de cierre de cada subida vencida
(``expired``) o cuya alerta se descartó (``alert_closed``); nunca edita.
"""

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final, Protocol

import numpy as np
from voc_common.analytics_codes import (
    AlertStatus,
    AspectFamily,
    BoostEndReason,
    EligibilityCode,
)
from voc_common.operations_v3 import (
    DriftAlert,
    DriftAlertEvent,
    DriftAlertMessage,
    DriftMetric,
)
from voc_common.policies import DriftPolicy, HitlBoost, RiskPolicy
from voc_nlp.drift import BINS, entry_month, psi, robust_z

from ml_inference.bq_io import StagingMergeWriter, query_rows, render
from ml_inference.config import InferenceSettings
from ml_inference.vocab import stage_vocab

log = logging.getLogger(__name__)

HISTOGRAM: Final = "length_distribution"
_CODE = re.compile(r"[A-Z]{2}")


@dataclass(frozen=True)
class MonthlyInput:
    """Agregados de un banco × mes (``period`` es ``YYYY-MM``)."""

    bank_id: str
    period: str
    rows: int
    values: Mapping[str, float | None]
    histogram: Sequence[int] = ()


@dataclass(frozen=True)
class DriftOutcome:
    metrics: list[DriftMetric]
    alerts: list[DriftAlert]


# -- Cálculo ---------------------------------------------------------------


def month_range(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    out = []
    while (key := f"{y:04d}-{m:02d}") <= last:
        out.append(key)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def last_closed_month(now: datetime) -> str:
    first = now.astimezone(UTC).date().replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


def _period_date(period: str) -> date:
    return date.fromisoformat(f"{period}-01")


def evaluate_bank(
    policy: DriftPolicy,
    months: Sequence[MonthlyInput],
    done: set[tuple[str, str]],
    last_closed: str,
    now: datetime,
) -> DriftOutcome:
    """Métricas y alertas que faltan de un banco.

    ``done`` son los pares (mes, serie) ya guardados: una serie que no se
    pudo medir (sin vocabulario, sin tópicos) se mide en cuanto tenga datos,
    aunque el mes ya tenga otras series.
    """
    if not months:
        return DriftOutcome([], [])
    by_period = {m.period: m for m in months}
    entry = entry_month(
        {m.period: m.rows for m in months},
        policy.min_rows_per_month,
        policy.entry_months,
    )
    if entry is None:
        return DriftOutcome([], [])
    periods = month_range(min(by_period), last_closed)
    todo = [p for p in periods if p > entry]
    metrics: list[DriftMetric] = []
    alerts: list[DriftAlert] = []
    for period in todo:
        i = periods.index(period)
        window = periods[max(0, i - policy.baseline_months) : i + 1]
        for series, threshold in policy.thresholds.z.items():
            if (period, series) in done:
                continue
            values = [_value(by_period.get(p), series) for p in window]
            metric = _z_metric(policy, series, threshold, values, period, now)
            if metric:
                metrics.append(metric)
        for series, threshold in policy.thresholds.psi.items():
            if (period, series) in done:
                continue
            metric = _psi_metric(
                policy, series, threshold, window, by_period, now
            )
            if metric:
                metrics.append(metric)
    live = _period_date(last_closed)
    for metric in metrics:
        if metric.alert and metric.period == live:
            alerts.append(_alert(metric, now))
    return DriftOutcome(metrics, alerts)


def _value(month: MonthlyInput | None, series: str) -> float | None:
    return None if month is None else month.values.get(series)


def _z_metric(
    policy: DriftPolicy,
    series: str,
    threshold: float | None,
    values: list[float | None],
    period: str,
    now: datetime,
) -> DriftMetric | None:
    value = values[-1]
    if value is None:
        return None
    z = robust_z(values, policy.baseline_months, policy.min_baseline_months)
    hist = [v for v in values[:-1] if v is not None]
    return DriftMetric(
        bank_id=policy.bank_id,
        period=_period_date(period),
        metric=series,
        value=value,
        baseline=float(np.median(hist)) if hist else None,
        z=z,
        threshold=threshold,
        alert=threshold is not None and z is not None and abs(z) >= threshold,
        drift_policy_version=policy.drift_policy_version,
        computed_at=now,
    )


def _psi_metric(
    policy: DriftPolicy,
    series: str,
    threshold: float | None,
    window: list[str],
    by_period: Mapping[str, MonthlyInput],
    now: datetime,
) -> DriftMetric | None:
    if series != HISTOGRAM or len(window) <= policy.baseline_months:
        return None
    empty = [0] * (len(BINS) - 1)
    hists = [
        list(by_period[p].histogram or empty) if p in by_period else empty
        for p in window
    ]
    current = hists[-1]
    reference = np.sum(hists[:-1], axis=0).tolist()
    if not sum(current) or not sum(reference):
        return None
    value = psi(current, reference)
    return DriftMetric(
        bank_id=policy.bank_id,
        period=_period_date(window[-1]),
        metric=series,
        value=value,
        psi=value,
        threshold=threshold,
        alert=threshold is not None and value >= threshold,
        drift_policy_version=policy.drift_policy_version,
        computed_at=now,
    )


def _alert(metric: DriftMetric, now: datetime) -> DriftAlert:
    period = metric.period.strftime("%Y-%m")
    assert metric.threshold is not None  # noqa: S101  # nosec B101
    return DriftAlert(
        alert_id=f"drift_{metric.bank_id}_{period}_{metric.metric}",
        bank_id=metric.bank_id,
        period=metric.period,
        series=metric.metric,
        value=metric.value,
        threshold=metric.threshold,
        drift_policy_version=metric.drift_policy_version,
        created_at=now,
    )


def boost_for(
    alert: DriftAlert, policy: RiskPolicy | None, now: datetime
) -> HitlBoost | None:
    """Subida HITL de la alerta, o ``None`` si la política no la configura."""
    if (
        policy is None
        or policy.drift_boost_coverage is None
        or policy.drift_boost_days is None
        or policy.drift_boost_weekly_cap is None
    ):
        return None
    return HitlBoost(
        boost_id=f"boost_{alert.alert_id}",
        bank_id=alert.bank_id,
        alert_id=alert.alert_id,
        risk_policy_version=policy.policy_version,
        coverage=policy.drift_boost_coverage,
        weekly_cap=policy.drift_boost_weekly_cap,
        starts_at=now,
        ends_at=now + timedelta(days=policy.drift_boost_days),
    )


def message_for(alert: DriftAlert, now: datetime) -> DriftAlertMessage:
    return DriftAlertMessage(
        alert_id=alert.alert_id,
        bank_id=alert.bank_id,
        period=alert.period.strftime("%Y-%m"),
        series=alert.series,
        value=alert.value,
        threshold=alert.threshold,
        drift_policy_version=alert.drift_policy_version,
        hitl_boost_id=alert.hitl_boost_id,
        triggered_at=now,
    )


def closing_rows(
    boosts: Sequence[HitlBoost],
    dismissed_alerts: set[str],
    now: datetime,
) -> list[HitlBoost]:
    """Filas de cierre de las subidas abiertas que terminaron."""
    out = []
    for boost in boosts:
        if boost.ended_reason is not None:
            continue
        if boost.alert_id is not None and boost.alert_id in dismissed_alerts:
            reason = BoostEndReason.ALERT_CLOSED
        elif boost.ends_at <= now:
            reason = BoostEndReason.EXPIRED
        else:
            continue
        out.append(boost.model_copy(update={"ended_reason": reason}))
    return out


# -- Lectura y escritura -----------------------------------------------------


class DriftSource(Protocol):
    def policies(self) -> list[DriftPolicy]: ...
    def risk_policy(self) -> RiskPolicy | None: ...
    def monthly(self, before: datetime) -> list[MonthlyInput]: ...
    def done(self) -> dict[str, set[tuple[str, str]]]: ...
    def open_boosts(self) -> list[HitlBoost]: ...
    def dismissed_alerts(self) -> set[str]: ...


def _bins_sql() -> str:
    edges = BINS[1:-1]
    parts = [f"COUNTIF(palabras <= {edges[0]}) AS b0"]
    for i, (lo, hi) in enumerate(zip(edges, edges[1:], strict=False), 1):
        parts.append(f"COUNTIF(palabras > {lo} AND palabras <= {hi}) AS b{i}")
    parts.append(f"COUNTIF(palabras > {edges[-1]}) AS b{len(edges)}")
    return ",\n  ".join(parts)


def _families_sql() -> str:
    codes = [f.value for f in AspectFamily]
    if not all(_CODE.fullmatch(c) for c in codes):
        raise ValueError("unexpected family code")
    return ",\n  ".join(
        f"AVG(IF('{c}' IN UNNEST(families), 1, 0)) AS family_{c}" for c in codes
    )


_NOT_PREDICTED_OK: Final = (
    EligibilityCode.ELEGIBLE.value,
    EligibilityCode.TNSS_SINGLE_WORD.value,
)

# Las columnas generadas salen de constantes validadas (``BINS`` y los
# códigos de familia); los valores van como parámetros.
_INPUT_TEMPLATE: Final = """
SELECT
  bank_id,
  FORMAT_TIMESTAMP('%Y-%m', fecha) AS period,
  COUNT(*) AS n_rows,
  AVG(palabras) AS mean_words,
  AVG(IF(palabras = 1, 1, 0)) AS single_word_share,
  AVG(IF(palabras > 60, 1, 0)) AS over_60_words_share,
  AVG(IF(eligibility_code IS NOT NULL
         AND eligibility_code NOT IN UNNEST(@predictable), 1, 0))
    AS not_predicted_share,
  SAFE_DIVIDE(COUNTIF(sentiment = 'NEG'), COUNTIF(sentiment IS NOT NULL))
    AS neg_share,
  @@bins@@
FROM `${ds}.review_predictions_current`
WHERE fecha < @before
GROUP BY bank_id, period
"""
INPUT_SQL: Final = _INPUT_TEMPLATE.replace("@@bins@@", _bins_sql())

_ASPECTS_TEMPLATE: Final = """
SELECT
  bank_id,
  FORMAT_TIMESTAMP('%Y-%m', fecha) AS period,
  AVG(IF(flag_update, 1, 0)) AS flag_update_share,
  @@families@@
FROM (
  SELECT bank_id, fecha, flag_update, families
  FROM `${ds}.review_aspects`
  WHERE fecha < @before
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY id_resena ORDER BY labeled_at DESC
  ) = 1
)
GROUP BY bank_id, period
"""
ASPECTS_SQL: Final = _ASPECTS_TEMPLATE.replace("@@families@@", _families_sql())


# Fracción de tokens (``texto_sanitizado`` en minúsculas, separado por espacio,
# como en el análisis histórico) que no están en el vocabulario de
# entrenamiento del modelo.
OOV_SQL: Final = """
SELECT
  p.bank_id,
  FORMAT_TIMESTAMP('%Y-%m', p.fecha) AS period,
  AVG(IF(v.word IS NULL, 1, 0)) AS out_of_vocabulary_share
FROM `${ds}.review_predictions_current` AS p
JOIN `${tds}` AS t
  ON t.id_resena = p.id_resena
  AND TO_HEX(SHA256(t.texto_sanitizado)) = p.text_key
CROSS JOIN UNNEST(SPLIT(LOWER(t.texto_sanitizado), ' ')) AS token
LEFT JOIN `${vocab}` AS v ON v.word = token
WHERE p.fecha < @before
GROUP BY bank_id, period
"""


TOPIC_SERIES: Final = ("topic_noise_share", "topic_unaligned_share")

TOPICS_SQL: Final = """
WITH version AS (
  SELECT topic_model_version FROM `${ds}.topic_model_current`
),
neg AS (
  SELECT id_resena, text_key, bank_id, fecha
  FROM `${ds}.review_predictions_current`
  WHERE sentiment = 'NEG' AND palabras >= 2 AND fecha < @before
),
assigned AS (
  SELECT n.bank_id, FORMAT_TIMESTAMP('%Y-%m', n.fecha) AS period,
    a.id_resena, a.topic_id
  FROM neg AS n
  JOIN `${ds}.topic_assignments` AS a
    ON a.id_resena = n.id_resena AND a.text_key = n.text_key
  JOIN version AS v ON v.topic_model_version = a.topic_model_version
),
curated AS (
  SELECT c.topic_id, ARRAY_LENGTH(c.families) > 0 AS aligned
  FROM `${ds}.curation_topics` AS c
  JOIN version USING (topic_model_version)
  WHERE TRUE
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY c.topic_id ORDER BY c.curated_at DESC
  ) = 1
),
by_review AS (
  SELECT s.bank_id, s.period, s.id_resena,
    COUNTIF(s.topic_id = -1) AS noise,
    COUNT(*) AS clauses,
    COUNTIF(s.topic_id != -1) AS topics,
    LOGICAL_OR(s.topic_id != -1 AND COALESCE(c.aligned, FALSE)) AS aligned
  FROM assigned AS s
  LEFT JOIN curated AS c USING (topic_id)
  GROUP BY s.bank_id, s.period, s.id_resena
)
SELECT bank_id, period,
  SAFE_DIVIDE(SUM(noise), SUM(clauses)) AS topic_noise_share,
  SAFE_DIVIDE(COUNTIF(topics > 0 AND NOT aligned), COUNTIF(topics > 0))
    AS topic_unaligned_share
FROM by_review
GROUP BY bank_id, period
"""


def _clean(row: Mapping[str, Any], model: type) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k in model.model_fields}


@dataclass
class BqDriftSource:
    """Lecturas del monitor en el dataset ``proyecto.dataset``."""

    client: Any
    dataset: str
    # Sin vocabulario (``training_vocab.txt`` del modelo), la serie
    # ``out_of_vocabulary_share`` no se calcula.
    tds: str | None = None
    vocab: frozenset[str] | None = None
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def _rows(
        self, sql: str, tables: Mapping[str, str] | None = None, **params: Any
    ) -> list[dict[str, Any]]:
        sql = render(sql, ds=self.dataset, **(tables or {}))
        return query_rows(self.client, sql, params)

    def _oov(self, before: datetime) -> dict[tuple[str, str], float]:
        if self.vocab is None or self.tds is None:
            log.warning(
                "drift: sin vocabulario, out_of_vocabulary_share omitida"
            )
            return {}
        table = stage_vocab(self.client, self.dataset, self.vocab, self.clock())
        try:
            rows = self._rows(
                OOV_SQL, {"tds": self.tds, "vocab": table}, before=before
            )
        finally:
            self.client.delete_table(table, not_found_ok=True)
        return {
            (r["bank_id"], r["period"]): float(r["out_of_vocabulary_share"])
            for r in rows
        }

    def policies(self) -> list[DriftPolicy]:
        return [
            DriftPolicy.model_validate(_clean(r, DriftPolicy))
            for r in self._rows("SELECT * FROM `${ds}.drift_policy_current`")
        ]

    def risk_policy(self) -> RiskPolicy | None:
        rows = self._rows("SELECT * FROM `${ds}.risk_policy_current`")
        return (
            RiskPolicy.model_validate(_clean(rows[0], RiskPolicy))
            if rows
            else None
        )

    def monthly(self, before: datetime) -> list[MonthlyInput]:
        aspects = {
            (r["bank_id"], r["period"]): r
            for r in self._rows(ASPECTS_SQL, before=before)
        }
        oov = self._oov(before)
        topics = {
            (r["bank_id"], r["period"]): r
            for r in self._rows(TOPICS_SQL, before=before)
        }
        out = []
        for r in self._rows(
            INPUT_SQL, before=before, predictable=list(_NOT_PREDICTED_OK)
        ):
            key = (r["bank_id"], r["period"])
            values = {
                k: (None if v is None else float(v))
                for k, v in r.items()
                if k not in {"bank_id", "period", "n_rows"}
                and not re.fullmatch(r"b\d", k)
            }
            if key in oov:
                values["out_of_vocabulary_share"] = oov[key]
            extra = aspects.get(key, {})
            values |= {
                k: (None if v is None else float(v))
                for k, v in extra.items()
                if k not in {"bank_id", "period"}
            }
            shares = topics.get(key, {})
            values |= {
                k: (None if shares[k] is None else float(shares[k]))
                for k in TOPIC_SERIES
                if k in shares
            }
            hist = [int(r[f"b{i}"]) for i in range(len(BINS) - 1)]
            out.append(
                MonthlyInput(key[0], key[1], int(r["n_rows"]), values, hist)
            )
        return out

    def done(self) -> dict[str, set[tuple[str, str]]]:
        out: dict[str, set[tuple[str, str]]] = {}
        for r in self._rows(
            "SELECT DISTINCT bank_id, FORMAT_DATE('%Y-%m', period) AS period, "
            "metric FROM `${ds}.drift_metrics`"
        ):
            out.setdefault(r["bank_id"], set()).add((r["period"], r["metric"]))
        return out

    def open_boosts(self) -> list[HitlBoost]:
        rows = self._rows(
            "SELECT b.* FROM `${ds}.hitl_boosts` b "
            "WHERE b.ended_reason IS NULL AND NOT EXISTS "
            "(SELECT 1 FROM `${ds}.hitl_boosts` c "
            "WHERE c.boost_id = b.boost_id AND c.ended_reason IS NOT NULL)"
        )
        return [HitlBoost.model_validate(_clean(r, HitlBoost)) for r in rows]

    def dismissed_alerts(self) -> set[str]:
        rows = self._rows(
            "SELECT alert_id FROM `${ds}.drift_alerts_current` "
            "WHERE status = @dismissed",
            dismissed=AlertStatus.DISMISSED.value,
        )
        return {r["alert_id"] for r in rows}


@dataclass
class MonitorClients:
    source: DriftSource
    writer: StagingMergeWriter
    publish: Callable[[DriftAlertMessage], None]
    run_id: str = field(default="monitor")


def run_drift(
    settings: InferenceSettings, clients: MonitorClients, now: datetime
) -> list[DriftAlert]:
    """Calcula los meses que faltan, alerta y escribe; devuelve las alertas."""
    del settings  # Las tablas salen del ``writer`` y la ``source``.
    source, writer = clients.source, clients.writer
    last = last_closed_month(now)
    # Inicio del mes en curso: solo entran meses cerrados.
    before = datetime.combine(
        now.astimezone(UTC).date().replace(day=1), datetime.min.time(), UTC
    )
    months: dict[str, list[MonthlyInput]] = {}
    for m in source.monthly(before):
        months.setdefault(m.bank_id, []).append(m)
    done = source.done()
    risk = source.risk_policy()
    active = {
        b.bank_id: b
        for b in sorted(source.open_boosts(), key=lambda b: b.starts_at)
        if b.starts_at <= now < b.ends_at
    }
    metrics: list[DriftMetric] = []
    alerts: list[DriftAlert] = []
    boosts: list[HitlBoost] = []
    for policy in source.policies():
        outcome = evaluate_bank(
            policy,
            months.get(policy.bank_id, []),
            done.get(policy.bank_id, set()),
            last,
            now,
        )
        metrics += outcome.metrics
        for alert in outcome.alerts:
            boost = active.get(alert.bank_id)
            if boost is None and (boost := boost_for(alert, risk, now)):
                active[alert.bank_id] = boost
                boosts.append(boost)
            alerts.append(
                alert.model_copy(
                    update={"hitl_boost_id": boost.boost_id if boost else None}
                )
            )
    events = [
        DriftAlertEvent(
            event_id=f"{a.alert_id}_open",
            alert_id=a.alert_id,
            status=AlertStatus.OPEN,
            at=now,
        )
        for a in alerts
    ]
    run = clients.run_id
    writer.write("hitl_boosts", boosts, ["boost_id", "ended_reason"], run)
    writer.write("drift_alerts", alerts, ["alert_id"], run)
    writer.write("drift_alert_events", events, ["event_id"], run)
    for alert in alerts:
        clients.publish(message_for(alert, now))
    # Al final: un mes con métricas ya no se recalcula.
    writer.write(
        "drift_metrics",
        metrics,
        ["bank_id", "period", "metric", "drift_policy_version"],
        run,
    )
    log.info(
        "drift: %d metrics, %d alerts, %d boosts",
        len(metrics),
        len(alerts),
        len(boosts),
    )
    return alerts


def close_boosts(clients: MonitorClients, now: datetime) -> list[HitlBoost]:
    """Inserta la fila de cierre de cada subida vencida o descartada."""
    rows = closing_rows(
        clients.source.open_boosts(), clients.source.dismissed_alerts(), now
    )
    clients.writer.write(
        "hitl_boosts", rows, ["boost_id", "ended_reason"], clients.run_id
    )
    return rows
