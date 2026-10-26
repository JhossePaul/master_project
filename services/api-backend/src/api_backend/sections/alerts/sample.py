"""Alertas sintéticas para diseñar el portal sin GCP.

Tres alertas: una abierta con subida activa, una confirmada y una descartada.
La nota de la confirmada lleva el centinela: ninguna ruta de lector debe
devolverla. Los datos van pegados a la fecha de hoy para que la serie de 24
meses termine en el mes de la alerta.
"""

from datetime import UTC, date, datetime, timedelta

from voc_common import (
    AlertStatus,
    DriftAlert,
    DriftAlertEvent,
    DriftMetric,
    HitlBoost,
)

from api_backend.fixtures import SENTINEL
from api_backend.sections.alerts.repository import InMemoryAlertRepository

POLICY = "drift_v2"
ANALYST = "a" * 64


def _months(last: date, count: int) -> list[date]:
    out = []
    for back in range(count - 1, -1, -1):
        index = last.year * 12 + last.month - 1 - back
        out.append(date(index // 12, index % 12 + 1, 1))
    return out


def _metrics(
    bank: str, series: str, last: date, peak: float, now: datetime
) -> list[DriftMetric]:
    rows = []
    months = _months(last, 24)
    for n, period in enumerate(months):
        is_alert = period == last
        value = peak if is_alert else 0.15 + 0.01 * (n % 3)
        rows.append(
            DriftMetric(
                bank_id=bank,
                period=period,
                metric=series,
                value=value,
                baseline=0.16,
                z=4.6 if is_alert else 0.3 * (n % 5) - 0.6,
                threshold=4.0,
                alert=is_alert,
                drift_policy_version=POLICY,
                computed_at=now,
            )
        )
    return rows


def sample_repository(now: datetime | None = None) -> InMemoryAlertRepository:
    now = now or datetime.now(UTC)
    last = date(now.year, now.month, 1)
    previous = _months(last, 2)[0]
    older = _months(last, 3)[0]
    specs = (
        ("NUBANK", "neg_share", previous, 0.31, "boost_open"),
        ("AZTECA", "mean_words", older, 7.4, None),
        ("BBVA", "family_AC", older, 0.22, None),
    )
    alerts, events, metrics, boosts = [], [], [], []
    for bank, series, period, value, boost in specs:
        alert_id = f"drift_{bank}_{period:%Y-%m}_{series}"
        alerts.append(
            DriftAlert(
                alert_id=alert_id,
                bank_id=bank,
                period=period,
                series=series,
                value=value,
                threshold=4.0,
                drift_policy_version=POLICY,
                hitl_boost_id=boost,
                created_at=now - timedelta(days=9),
            )
        )
        events.append(
            DriftAlertEvent(
                event_id=f"{alert_id}_open",
                alert_id=alert_id,
                status=AlertStatus.OPEN,
                at=now - timedelta(days=9),
            )
        )
        metrics += _metrics(bank, series, period, value, now)
    boosts.append(
        HitlBoost(
            boost_id="boost_open",
            bank_id="NUBANK",
            alert_id=alerts[0].alert_id,
            risk_policy_version="rp1",
            coverage=0.85,
            weekly_cap=200,
            starts_at=now - timedelta(days=9),
            ends_at=now + timedelta(days=5),
        )
    )
    events.append(
        DriftAlertEvent(
            event_id="syn-confirmed",
            alert_id=alerts[1].alert_id,
            status=AlertStatus.CONFIRMED,
            actor_hash=ANALYST,
            at=now - timedelta(days=3),
            note=SENTINEL,
            ticket="VOC-12",
        )
    )
    events.append(
        DriftAlertEvent(
            event_id="syn-dismissed",
            alert_id=alerts[2].alert_id,
            status=AlertStatus.DISMISSED,
            actor_hash=ANALYST,
            at=now - timedelta(days=2),
            note="Cambio de versión de la app, ya explicado.",
        )
    )
    return InMemoryAlertRepository(alerts, events, metrics, boosts)
