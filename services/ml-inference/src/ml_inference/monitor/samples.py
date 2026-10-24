"""Muestras humanas del monitor.

* **Muestra de concepto** (``monitor_sample``): ``monitor_sample_size``
  reseñas al azar entre las que predijo el modelo promovido en el último
  trimestre cerrado. Mide el κ de RoBERTuito (``quality.kappa_monitor``).
* **Doble revisión** (``agreement_sample``): ``human_agreement_sample_size``
  reseñas por periodo (``human_agreement_frequency``), revisadas por dos
  personas en la pantalla de revisión. Sin esos dos valores en la
  ``risk_policy`` no se
  crean casos.

Los dos casos son ``blind`` (la API no envía la predicción, que se guarda
para medir). La semilla sale del motivo y del periodo
(``sample_seed``), así que la muestra se puede reproducir; los candidatos se
ordenan por ``id_resena`` antes de sortear. Un periodo que ya tiene casos de
ese motivo no se vuelve a muestrear.
"""

import hashlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Final

import numpy as np
from voc_common.analytics_codes import (
    DisplayMode,
    HitlReason,
    HitlStatus,
    HitlTask,
)
from voc_common.hitl_v3 import HitlEvent, HitlItem
from voc_common.policies import RiskPolicy

from ml_inference.bq_io import StagingMergeWriter, query_rows, render

log = logging.getLogger(__name__)

# Se revisan antes que los de baja confianza (prioridad 1 − confianza ≤ 1).
SAMPLE_PRIORITY: Final = 1.0
FREQUENCIES: Final = ("monthly", "quarterly")


@dataclass(frozen=True)
class Candidate:
    """Reseña predicha por el modelo (sin texto)."""

    id_resena: str
    bank_id: str
    text_key: str
    sentiment: str | None
    p_neg: float | None
    p_neu: float | None
    p_pos: float | None
    model_version: str
    risk_policy_version: str | None


# -- Periodos ----------------------------------------------------------------


def period_of(day: date, frequency: str) -> str:
    """``2026Q2`` (trimestral) o ``2026-05`` (mensual)."""
    if frequency == "quarterly":
        return f"{day.year}Q{(day.month - 1) // 3 + 1}"
    if frequency == "monthly":
        return f"{day.year}-{day.month:02d}"
    raise ValueError(f"unsupported frequency: {frequency}")


def period_bounds(period: str) -> tuple[datetime, datetime]:
    """Inicio (incluido) y fin (excluido) del periodo, en UTC."""
    if "Q" in period:
        year, q = period.split("Q")
        first = (int(year), 3 * (int(q) - 1) + 1)
        months = 3
    else:
        y, m = period.split("-")
        first, months = (int(y), int(m)), 1
    y, m = first
    end_m = m + months
    end = (y + (end_m - 1) // 12, (end_m - 1) % 12 + 1)
    return (
        datetime(y, m, 1, tzinfo=UTC),
        datetime(end[0], end[1], 1, tzinfo=UTC),
    )


def last_closed_period(now: datetime, frequency: str) -> str:
    """Periodo anterior al que contiene ``now``."""
    start, _ = period_bounds(period_of(now.astimezone(UTC).date(), frequency))
    previous = date.fromordinal(start.date().toordinal() - 1)
    return period_of(previous, frequency)


def sample_seed(reason: HitlReason, period: str) -> int:
    """Semilla reproducible del sorteo: 64 bits del SHA-256 del motivo."""
    digest = hashlib.sha256(f"{reason.value}:{period}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


# -- Sorteo ------------------------------------------------------------------


def draw(
    candidates: Sequence[Candidate],
    size: int,
    reason: HitlReason,
    period: str,
) -> list[Candidate]:
    """``size`` candidatos sin reemplazo (todos si hay menos)."""
    pool = sorted(candidates, key=lambda c: (c.id_resena, c.text_key))
    if len(pool) <= size:
        return pool
    rng = np.random.default_rng(sample_seed(reason, period))
    idx = rng.choice(len(pool), size=size, replace=False)
    return [pool[i] for i in sorted(idx)]


def items_for(
    sample: Sequence[Candidate],
    reason: HitlReason,
    period: str,
    now: datetime,
) -> list[HitlItem]:
    return [
        HitlItem(
            item_id=(
                f"{reason.value}:{period}:{c.id_resena}:"
                f"{c.text_key[:16]}:{c.model_version}"
            ),
            id_resena=c.id_resena,
            bank_id=c.bank_id,
            task=HitlTask.SENTIMENT,
            reason=reason,
            display_mode=DisplayMode.BLIND,
            model_version=c.model_version,
            risk_policy_version=c.risk_policy_version,
            predicted={
                "label": c.sentiment,
                "p_neg": c.p_neg,
                "p_neu": c.p_neu,
                "p_pos": c.p_pos,
            },
            priority=SAMPLE_PRIORITY,
            created_at=now,
        )
        for c in sample
    ]


def create_monitor_sample(
    candidates: Sequence[Candidate], quarter: str, size: int, now: datetime
) -> list[HitlItem]:
    """Muestra de concepto del trimestre, siempre ``blind``."""
    reason = HitlReason.MONITOR_SAMPLE
    return items_for(
        draw(candidates, size, reason, quarter), reason, quarter, now
    )


def create_agreement_sample(
    candidates: Sequence[Candidate],
    policy: RiskPolicy,
    now: datetime,
) -> list[HitlItem]:
    """Doble revisión del último periodo cerrado; nada si no se configuró."""
    size = policy.human_agreement_sample_size
    frequency = policy.human_agreement_frequency
    if not size or frequency is None:
        return []
    reason = HitlReason.AGREEMENT_SAMPLE
    period = last_closed_period(now, frequency)
    return items_for(
        draw(candidates, size, reason, period), reason, period, now
    )


# -- Lectura y escritura -----------------------------------------------------

CANDIDATES_SQL: Final = """
SELECT id_resena, bank_id, text_key, sentiment, p_neg, p_neu, p_pos,
  model_version, risk_policy_version
FROM `${ds}.review_predictions_current`
WHERE label_source = 'MODEL'
  AND model_version = @model_version
  AND fecha >= @start AND fecha < @end
"""

EXISTING_SQL: Final = """
SELECT COUNT(*) AS n
FROM `${ds}.hitl_items`
WHERE reason = @reason AND STARTS_WITH(item_id, @prefix)
"""


@dataclass
class SampleJob:
    client: Any
    writer: StagingMergeWriter
    dataset: str
    run_id: str

    def _rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        return query_rows(self.client, render(sql, ds=self.dataset), params)

    def _exists(self, reason: HitlReason, period: str) -> bool:
        rows = self._rows(
            EXISTING_SQL,
            reason=reason.value,
            prefix=f"{reason.value}:{period}:",
        )
        return int(rows[0]["n"]) > 0

    def _candidates(self, model_version: str, period: str) -> list[Candidate]:
        start, end = period_bounds(period)
        return [
            Candidate(**_pick(r))
            for r in self._rows(
                CANDIDATES_SQL,
                model_version=model_version,
                start=start,
                end=end,
            )
        ]

    def _write(self, items: list[HitlItem], now: datetime) -> int:
        added = self.writer.write("hitl_items", items, ["item_id"], self.run_id)
        events = [
            HitlEvent(
                event_id=f"{i.item_id}:queued",
                item_id=i.item_id,
                status=HitlStatus.QUEUED,
                at=now,
            )
            for i in items
        ]
        self.writer.write("hitl_events", events, ["event_id"], self.run_id)
        return added

    def run(
        self, policy: RiskPolicy | None, model_version: str, now: datetime
    ) -> dict[str, int]:
        """Crea las muestras que falten (casos nuevos por motivo)."""
        out = {"monitor_sample": 0, "agreement_sample": 0}
        if policy is None:
            log.warning("samples: sin risk_policy vigente")
            return out
        if policy.monitor_frequency != "quarterly":
            log.warning(
                "samples: monitor_frequency %r no soportada",
                policy.monitor_frequency,
            )
        else:
            quarter = last_closed_period(now, "quarterly")
            if not self._exists(HitlReason.MONITOR_SAMPLE, quarter):
                items = create_monitor_sample(
                    self._candidates(model_version, quarter),
                    quarter,
                    policy.monitor_sample_size,
                    now,
                )
                out["monitor_sample"] = self._write(items, now)
        frequency = policy.human_agreement_frequency
        if policy.human_agreement_sample_size and frequency is not None:
            if frequency not in FREQUENCIES:
                log.warning(
                    "samples: human_agreement_frequency %r no soportada",
                    frequency,
                )
                return out
            period = last_closed_period(now, frequency)
            if not self._exists(HitlReason.AGREEMENT_SAMPLE, period):
                items = create_agreement_sample(
                    self._candidates(model_version, period), policy, now
                )
                out["agreement_sample"] = self._write(items, now)
        log.info("samples: %s", out)
        return out


def _pick(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: row[k] for k in Candidate.__dataclass_fields__}
