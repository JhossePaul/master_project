"""Reglas de las alertas: lectura, transiciones y cierre de la subida."""

import calendar
from collections.abc import Sequence
from datetime import date, datetime
from typing import Final

from voc_common import (
    AlertStatus,
    BoostEndReason,
    DriftAlertEvent,
    DriftMetric,
    HitlBoost,
)

from api_backend.auth.deps import Principal
from api_backend.dlp import CommentSanitizer
from api_backend.errors import ApiError, ErrorCode
from api_backend.sections.alerts.repository import (
    AlertRecord,
    AlertRepository,
)
from api_backend.sections.alerts.schemas import (
    AlertDetail,
    AlertEventIn,
    AlertEventOut,
    AlertRow,
    AlertSummary,
    BoostOut,
    ExplorerHint,
    SeriesPoint,
)

SERIES_MONTHS: Final = 24
SHORT_HASH: Final = 8
# Desde cada estado, a cuáles se puede pasar (reabrir incluido).
TRANSITIONS: Final[dict[AlertStatus, frozenset[AlertStatus]]] = {
    AlertStatus.OPEN: frozenset({AlertStatus.CONFIRMED, AlertStatus.DISMISSED}),
    AlertStatus.CONFIRMED: frozenset({AlertStatus.DISMISSED, AlertStatus.OPEN}),
    AlertStatus.DISMISSED: frozenset({AlertStatus.OPEN}),
}


def is_active(boost: HitlBoost, now: datetime) -> bool:
    """Misma definición que la vista ``hitl_boosts_active``."""
    return boost.ended_reason is None and boost.starts_at <= now < boost.ends_at


def _boost_out(boost: HitlBoost | None, now: datetime) -> BoostOut | None:
    if boost is None:
        return None
    return BoostOut(
        boost_id=boost.boost_id,
        active=is_active(boost, now),
        coverage=boost.coverage,
        starts_at=boost.starts_at,
        ends_at=boost.ends_at,
        ended_reason=boost.ended_reason,
    )


def _row(
    record: AlertRecord, boosts: dict[str, HitlBoost], now: datetime
) -> AlertRow:
    alert = record.alert
    boost = boosts.get(alert.hitl_boost_id) if alert.hitl_boost_id else None
    return AlertRow(
        alert_id=alert.alert_id,
        bank_id=alert.bank_id,
        period=alert.period.strftime("%Y-%m"),
        series=alert.series,
        value=alert.value,
        threshold=alert.threshold,
        status=record.status,
        status_at=record.status_at,
        drift_policy_version=alert.drift_policy_version,
        created_at=alert.created_at,
        boost=_boost_out(boost, now),
    )


def list_alerts(
    repo: AlertRepository,
    status: AlertStatus | None,
    banks: Sequence[str],
    now: datetime,
) -> list[AlertRow]:
    records = repo.alerts(status, banks)
    ids = sorted(
        {r.alert.hitl_boost_id for r in records if r.alert.hitl_boost_id}
    )
    boosts = repo.boosts(ids)
    return [_row(r, boosts, now) for r in records]


def summary(repo: AlertRepository) -> AlertSummary:
    return AlertSummary(open_by_bank=repo.open_by_bank())


def _month_back(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)


def _point(metric: DriftMetric) -> SeriesPoint:
    return SeriesPoint(
        period=metric.period.strftime("%Y-%m"),
        value=metric.value,
        baseline=metric.baseline,
        z=metric.z,
        psi=metric.psi,
        threshold=metric.threshold,
        alert=metric.alert,
    )


def _event_out(event: DriftAlertEvent) -> AlertEventOut:
    return AlertEventOut(
        event_id=event.event_id,
        status=event.status,
        at=event.at,
        actor=event.actor_hash[:SHORT_HASH] if event.actor_hash else None,
        note=event.note,
        ticket=event.ticket,
    )


def _find(repo: AlertRepository, alert_id: str) -> AlertRecord:
    record = repo.alert(alert_id)
    if record is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No existe la alerta")
    return record


def _detail(
    repo: AlertRepository,
    record: AlertRecord,
    events: list[DriftAlertEvent],
    now: datetime,
) -> AlertDetail:
    alert = record.alert
    boosts = repo.boosts([alert.hitl_boost_id] if alert.hitl_boost_id else [])
    last_day = calendar.monthrange(alert.period.year, alert.period.month)[1]
    metrics = repo.metrics(
        alert.bank_id,
        alert.series,
        _month_back(alert.period, SERIES_MONTHS - 1),
        alert.period,
    )
    return AlertDetail(
        alert=_row(record, boosts, now),
        events=[_event_out(e) for e in events],
        series=[_point(m) for m in metrics],
        explorer=ExplorerHint(
            bank_id=alert.bank_id,
            start=alert.period,
            end=alert.period.replace(day=last_day),
        ),
    )


def detail(repo: AlertRepository, alert_id: str, now: datetime) -> AlertDetail:
    record = _find(repo, alert_id)
    return _detail(repo, record, repo.events(alert_id), now)


def _close_boost(
    repo: AlertRepository, record: AlertRecord, now: datetime
) -> None:
    """Descartar la alerta cierra su subida activa; confirmarla no."""
    boost_id = record.alert.hitl_boost_id
    if boost_id is None:
        return
    boost = repo.boosts([boost_id]).get(boost_id)
    if boost is not None and is_active(boost, now):
        repo.close_boost(
            boost.model_copy(
                update={"ended_reason": BoostEndReason.ALERT_CLOSED}
            )
        )


def add_event(  # noqa: PLR0913
    repo: AlertRepository,
    sanitizer: CommentSanitizer,
    principal: Principal,
    alert_id: str,
    body: AlertEventIn,
    now: datetime,
) -> AlertDetail:
    record = _find(repo, alert_id)
    events = repo.events(alert_id)
    event_id = str(body.event_id)
    if any(e.event_id == event_id for e in events):
        # Reintento de un envío que sí llegó. Si fue un descarte, la subida
        # puede haber quedado abierta por un fallo a medias: se vuelve a cerrar.
        if body.status is AlertStatus.DISMISSED:
            _close_boost(repo, record, now)
        return _detail(repo, record, events, now)
    if body.status not in TRANSITIONS[record.status]:
        raise ApiError(
            ErrorCode.CONFLICT,
            f"La alerta ya está {record.status.value}; recarga la página",
        )
    # Si DLP falla, 502 y no se escribe nada.
    note = sanitizer.sanitize(body.note)
    event = DriftAlertEvent(
        event_id=event_id,
        alert_id=alert_id,
        status=body.status,
        actor_hash=principal.actor_hash,
        at=now,
        note=note,
        ticket=body.ticket,
    )
    if not repo.add_event(event):
        raise ApiError(ErrorCode.CONFLICT, "El evento ya existe; recarga")
    if body.status is AlertStatus.DISMISSED:
        _close_boost(repo, record, now)
    updated = _find(repo, alert_id)
    return _detail(repo, updated, repo.events(alert_id), now)
