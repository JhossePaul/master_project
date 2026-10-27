"""Reglas de administración: versiones nuevas, vistas previas y tasas.

Nada se edita ni se borra: cada cambio inserta una versión con quién (hash) y
por qué. El umbral de la ``risk_policy`` sale de la curva del modelo promovido
(``voc_nlp.policy``), no de lo que mande el portal.
"""

import re
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from voc_common import (
    DriftPolicy,
    DriftThresholds,
    GoldVersion,
    HitlCoverageCurve,
    RetrainTrigger,
    RiskPolicy,
)
from voc_nlp.drift_rates import Rate, rates
from voc_nlp.policy import next_risk_policy, point_for

from api_backend.auth.deps import Principal
from api_backend.errors import ApiError, ErrorCode
from api_backend.sections.admin.repository import (
    TIMING_WINDOW_DAYS,
    AdminRepository,
    DriftMonth,
    GoldRow,
)
from api_backend.sections.admin.schemas import (
    CONFIRM_WORD,
    CoverageCurveResponse,
    DriftPolicyResponse,
    DriftRatesResponse,
    FieldDiff,
    GoldCount,
    GoldCreateIn,
    GoldCriteria,
    GoldItem,
    GoldItemsResponse,
    GoldPreview,
    GoldVersionOut,
    RiskChangeIn,
    RiskPolicyResponse,
    RiskPreview,
    RiskSaveIn,
    SeriesRate,
)

LARGE_CHANGE = 0.05
# Campos que cambian en toda versión: no son un cambio de parámetros.
BOOKKEEPING = frozenset(
    {
        "policy_version",
        "drift_policy_version",
        "valid_from",
        "set_by_hash",
        "reason",
    }
)
SHORT_HASH = 8


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def diff(
    before: BaseModel, after: BaseModel, skip: frozenset[str] = BOOKKEEPING
) -> list[FieldDiff]:
    """Campo por campo, solo lo que cambió."""
    a, b = _dump(before), _dump(after)
    return [
        FieldDiff(field=name, before=a.get(name), after=b.get(name))
        for name in b
        if name not in skip and a.get(name) != b.get(name)
    ]


_P = TypeVar("_P", RiskPolicy, DriftPolicy)


def _current(policies: list[_P], now: datetime) -> _P | None:
    live = [p for p in policies if p.valid_from <= now]
    return live[-1] if live else None


# -- Apetito de riesgo -------------------------------------------------------


def _current_risk(repo: AdminRepository, now: datetime) -> RiskPolicy:
    current = _current(repo.risk_policies(), now)
    if current is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No hay una risk_policy vigente")
    return current


def risk_policy(repo: AdminRepository, now: datetime) -> RiskPolicyResponse:
    history = repo.risk_policies()
    return RiskPolicyResponse(current=_current_risk(repo, now), history=history)


def _promoted_curve(
    repo: AdminRepository, model_version: str | None
) -> HitlCoverageCurve:
    model = model_version or repo.promoted_model_version()
    curve = repo.curve(model) if model else None
    if curve is None:
        raise ApiError(
            ErrorCode.NOT_FOUND, "No hay una curva de cobertura para el modelo"
        )
    return curve


def coverage_curve(
    repo: AdminRepository, model_version: str | None, now: datetime
) -> CoverageCurveResponse:
    curve = _promoted_curve(repo, model_version)
    current = _current_risk(repo, now)
    try:
        point = point_for(curve, current.hitl_target_coverage)
    except ValueError:
        point = None
    median, n = repo.timing(TIMING_WINDOW_DAYS)
    return CoverageCurveResponse(
        curve=curve,
        current_point=point,
        median_seconds=median,
        timed_n=n,
        window_days=TIMING_WINDOW_DAYS,
        hitl_boosts_active=repo.active_boosts(),
    )


def _propose(
    repo: AdminRepository,
    principal: Principal,
    body: RiskChangeIn,
    reason: str,
    now: datetime,
) -> tuple[RiskPolicy, RiskPolicy]:
    """(vigente, propuesta). 409 si ``base_version`` ya no es la vigente."""
    current = _current_risk(repo, now)
    if body.base_version != current.policy_version:
        raise ApiError(
            ErrorCode.CONFLICT,
            f"La versión vigente es {current.policy_version}; vuelve a abrirla",
        )
    curve = _promoted_curve(repo, None)
    proposed = next_risk_policy(
        current, body.changes, curve, principal.actor_hash, reason, now
    )
    return current, proposed


def _validation_messages(exc: Exception) -> list[str]:
    if isinstance(exc, ValidationError):
        return [
            f"{'.'.join(str(p) for p in e['loc']) or 'política'}: {e['msg']}"
            for e in exc.errors()
        ]
    return [str(exc)]


def is_large_change(current: RiskPolicy, proposed: RiskPolicy) -> bool:
    delta = abs(proposed.hitl_target_coverage - current.hitl_target_coverage)
    return delta > LARGE_CHANGE + 1e-9


def _warnings(proposed: RiskPolicy, current: RiskPolicy) -> list[str]:
    out = []
    if (
        proposed.retrain_mode is RetrainTrigger.AUTO
        and current.retrain_mode is not RetrainTrigger.AUTO
    ):
        out.append(
            "En automático, el texto sale a Kaggle sin aprobación por "
            "corrida; guardar este cambio es esa aprobación."
        )
    if is_large_change(current, proposed):
        out.append(
            "La cobertura cambia más de 5 puntos: pide escribir CONFIRMAR."
        )
    return out


def preview_risk(
    repo: AdminRepository,
    principal: Principal,
    body: RiskChangeIn,
    now: datetime,
) -> RiskPreview:
    try:
        current, proposed = _propose(repo, principal, body, "vista previa", now)
    except (ValidationError, ValueError) as exc:
        return RiskPreview(
            proposed=None,
            diff=[],
            large_change=False,
            warnings=[],
            errors=_validation_messages(exc),
        )
    return RiskPreview(
        proposed=proposed,
        diff=diff(current, proposed),
        large_change=is_large_change(current, proposed),
        warnings=_warnings(proposed, current),
        errors=[],
    )


def save_risk(
    repo: AdminRepository,
    principal: Principal,
    body: RiskSaveIn,
    now: datetime,
) -> RiskPolicy:
    try:
        current, proposed = _propose(
            repo, principal, body, body.reason.strip(), now
        )
    except (ValidationError, ValueError) as exc:
        raise ApiError(
            ErrorCode.INVALID, "; ".join(_validation_messages(exc))
        ) from exc
    if is_large_change(current, proposed) and body.confirm_word != CONFIRM_WORD:
        raise ApiError(
            ErrorCode.INVALID,
            f"La cobertura cambia más de 5 puntos: escribe {CONFIRM_WORD}",
        )
    if not repo.add_risk_policy(proposed):
        raise ApiError(
            ErrorCode.CONFLICT, "Otra persona acaba de crear esa versión"
        )
    return proposed


# -- Deriva ------------------------------------------------------------------


def _current_drift(
    repo: AdminRepository, bank: str, now: datetime
) -> DriftPolicy:
    current = _current(repo.drift_policies(bank), now)
    if current is None:
        raise ApiError(
            ErrorCode.NOT_FOUND, f"El banco {bank} no tiene drift_policy"
        )
    return current


def drift_policy(
    repo: AdminRepository, bank: str, now: datetime
) -> DriftPolicyResponse:
    current = _current_drift(repo, bank, now)
    template = repo.drift_template(current.template_version)
    if template is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No existe la plantilla {current.template_version}",
        )
    return DriftPolicyResponse(
        current=current,
        template=template,
        history=repo.drift_policies(bank),
        diff_vs_template=_template_diff(current, template),
    )


def _template_diff(
    current: DriftPolicy, template: BaseModel
) -> list[FieldDiff]:
    """Parámetros y umbral por serie que se apartan de la plantilla."""
    a, b = _dump(template), _dump(current)
    out = [
        FieldDiff(field=name, before=a.get(name), after=b.get(name))
        for name in (
            "baseline_months",
            "min_baseline_months",
            "min_rows_per_month",
            "entry_months",
        )
        if a.get(name) != b.get(name)
    ]
    for kind in ("z", "psi"):
        mine, base = b["thresholds"][kind], a["thresholds"][kind]
        out += [
            FieldDiff(
                field=f"thresholds.{kind}.{series}",
                before=base.get(series),
                after=mine.get(series),
            )
            for series in sorted(set(mine) | set(base))
            if mine.get(series) != base.get(series)
        ]
    return out


def _alerts(
    months: list[DriftMonth], thresholds: DriftThresholds
) -> list[Mapping[str, Any]]:
    """Filas ``(metric, months, alerts)`` para ``voc_nlp.drift_rates.rates``."""
    total: Counter[str] = Counter()
    alerts: Counter[str] = Counter()
    for m in months:
        total[m.series] += 1
        z_limit, psi_limit = (
            thresholds.z.get(m.series),
            thresholds.psi.get(m.series),
        )
        hit = (
            z_limit is not None and m.z is not None and abs(m.z) >= z_limit
        ) or (
            psi_limit is not None and m.psi is not None and m.psi >= psi_limit
        )
        alerts[m.series] += int(hit)
    return [
        {"metric": s, "months": n, "alerts": alerts[s]}
        for s, n in sorted(total.items())
    ]


def _alerts_on(thresholds: DriftThresholds, series: str) -> bool:
    """La serie tiene un umbral (z o PSI) con el que puede alertar."""
    return (
        thresholds.z.get(series) is not None
        or thresholds.psi.get(series) is not None
    )


def _rates(
    bank: str, months: list[DriftMonth], thresholds: DriftThresholds
) -> dict[str, Rate]:
    rows = [{**r, "bank_id": bank} for r in _alerts(months, thresholds)]
    return {r.series: r for r in rates(rows)}


def drift_rates(
    repo: AdminRepository,
    bank: str,
    thresholds: DriftThresholds,
    now: datetime,
) -> DriftRatesResponse:
    current = _current_drift(repo, bank, now)
    months = repo.drift_months(bank)
    proposed = _rates(bank, months, thresholds)
    live = _rates(bank, months, current.thresholds)
    series = []
    for name in sorted(set(proposed) | set(live)):
        if not (
            _alerts_on(thresholds, name) or _alerts_on(current.thresholds, name)
        ):
            continue  # se mide y nunca alerta: no tiene tasa
        p, c = proposed.get(name), live.get(name)
        base = p or c
        assert base is not None  # noqa: S101  # el nombre sale de una de las dos
        series.append(
            SeriesRate(
                series=name,
                months=base.months,
                proposed_alerts=p.alerts if p else 0,
                proposed_per_year=round(p.per_year, 2) if p else 0.0,
                current_alerts=c.alerts if c else 0,
                current_per_year=round(c.per_year, 2) if c else 0.0,
                reference=base.reference,
            )
        )
    return DriftRatesResponse(bank=bank, series=series)


def save_drift(
    repo: AdminRepository,
    principal: Principal,
    bank: str,
    base_version: str,
    changes: Mapping[str, Any],
    reason: str,
    now: datetime,
) -> DriftPolicy:
    current = _current_drift(repo, bank, now)
    if base_version != current.drift_policy_version:
        raise ApiError(
            ErrorCode.CONFLICT,
            f"La versión vigente es {current.drift_policy_version}; "
            "vuelve a abrirla",
        )
    allowed = {
        "thresholds",
        "baseline_months",
        "min_baseline_months",
        "min_rows_per_month",
        "entry_months",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise ApiError(
            ErrorCode.INVALID, f"Campos no editables: {sorted(unknown)}"
        )
    try:
        proposed = DriftPolicy.model_validate(
            {
                **current.model_dump(),
                **changes,
                "drift_policy_version": next_drift_version(
                    current.drift_policy_version
                ),
                "valid_from": now,
                "set_by_hash": principal.actor_hash,
                "reason": reason.strip(),
            }
        )
    except ValidationError as exc:
        raise ApiError(
            ErrorCode.INVALID, "; ".join(_validation_messages(exc))
        ) from exc
    if not repo.add_drift_policy(proposed):
        raise ApiError(
            ErrorCode.CONFLICT, "Otra persona acaba de crear esa versión"
        )
    return proposed


def next_drift_version(current: str) -> str:
    """``drift_policy_v1_BBVA`` → ``drift_policy_v2_BBVA``.

    Conserva el resto del id tal cual (en dev el banco va en minúscula:
    ``drift_policy_v2_nubank``).
    """
    match = re.fullmatch(r"(.*_v)(\d+)(_.*)?", current)
    if match is None:
        return f"{current}_v2"
    return f"{match[1]}{int(match[2]) + 1}{match[3] or ''}"


# -- Oro ---------------------------------------------------------------------


def _counts(rows: list[GoldRow], attr: str) -> list[GoldCount]:
    counter = Counter(str(getattr(r, attr)) for r in rows)
    return [GoldCount(key=k, n=n) for k, n in sorted(counter.items())]


def gold_versions(repo: AdminRepository) -> list[GoldVersionOut]:
    return [
        GoldVersionOut(version=v, reason=v.criteria.get("created_reason"))
        for v in repo.gold_versions()
    ]


def preview_gold(repo: AdminRepository, criteria: GoldCriteria) -> GoldPreview:
    _check_range(criteria)
    rows = repo.gold_rows(criteria, None)
    return GoldPreview(
        total=len(rows),
        by_bank=_counts(rows, "bank_id"),
        by_label=_counts(rows, "validated_label"),
    )


def _check_range(criteria: GoldCriteria) -> None:
    if criteria.submitted_to < criteria.submitted_from:
        raise ApiError(ErrorCode.INVALID, "El periodo termina antes de empezar")


def next_gold_version(existing: list[GoldVersion]) -> str:
    numbers = [
        int(g.gold_version.rsplit("_v", 1)[1])
        for g in existing
        if g.gold_version.startswith("gold_hitl_v")
        and g.gold_version.rsplit("_v", 1)[1].isdigit()
    ]
    return f"gold_hitl_v{max(numbers, default=0) + 1}"


def create_gold(
    repo: AdminRepository,
    principal: Principal,
    body: GoldCreateIn,
    now: datetime,
) -> GoldVersionOut:
    _check_range(body.criteria)
    rows = repo.gold_rows(body.criteria, now)
    if not rows:
        raise ApiError(
            ErrorCode.INVALID, "Con esos criterios no entra ninguna revisión"
        )
    version = GoldVersion(
        gold_version=next_gold_version(repo.gold_versions()),
        criteria={
            **body.criteria.model_dump(mode="json"),
            "created_reason": body.reason.strip(),
        },
        cutoff_at=now,
        items=len(rows),
        created_by_hash=principal.actor_hash,
        created_at=now,
    )
    if not repo.add_gold_version(version):
        raise ApiError(
            ErrorCode.CONFLICT, "Otra persona acaba de crear esa versión"
        )
    return GoldVersionOut(version=version, reason=body.reason.strip())


def gold_items(repo: AdminRepository, gold_version: str) -> GoldItemsResponse:
    version = next(
        (g for g in repo.gold_versions() if g.gold_version == gold_version),
        None,
    )
    if version is None:
        raise ApiError(ErrorCode.NOT_FOUND, f"No existe {gold_version}")
    criteria = GoldCriteria.model_validate(version.criteria)
    rows = repo.gold_rows(criteria, version.cutoff_at)
    return GoldItemsResponse(
        gold_version=gold_version,
        cutoff_at=version.cutoff_at,
        items=[
            GoldItem(
                item_id=r.item_id,
                id_resena=r.id_resena,
                validated_label=r.validated_label,
                submitted_at=r.submitted_at,
                reviewer=r.reviewer_hash[:SHORT_HASH],
            )
            for r in rows
        ],
    )
