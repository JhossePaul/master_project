"""Arma ``LandingResponse`` desde el repositorio."""

from datetime import date

from api_backend.auth.deps import Principal
from api_backend.auth.roles import Role
from api_backend.sections.landing.repository import KpiRow, LandingRepository
from api_backend.sections.landing.schemas import (
    BankHeadline,
    Estimate,
    Freshness,
    LandingResponse,
)


def _estimate(row: KpiRow) -> Estimate:
    return Estimate(
        estimate=row.estimate,
        ci_low=row.ci_low,
        ci_high=row.ci_high,
        method="ppi",
        n_gold=row.n_gold,
        n_unlabeled=row.n_unlabeled,
    )


def headlines(rows: list[KpiRow], today: date) -> list[BankHeadline]:
    """Por banco, el último mes cerrado que tenga las dos métricas con PPI."""
    current = today.strftime("%Y-%m")
    by_cell: dict[tuple[str, str], dict[str, KpiRow]] = {}
    for row in rows:
        if row.period < current:
            by_cell.setdefault((row.bank_id, row.period), {})[row.metric] = row
    best: dict[str, str] = {}
    for bank, period in by_cell:
        cell = by_cell[(bank, period)]
        if "neg" in cell and "gap_estrellas" in cell:
            best[bank] = max(best.get(bank, period), period)
    out = []
    for bank in sorted(best):
        cell = by_cell[(bank, best[bank])]
        neg = cell["neg"]
        out.append(
            BankHeadline(
                bank_id=bank,
                period=best[bank],
                neg=_estimate(neg),
                gap_estrellas=_estimate(cell["gap_estrellas"]),
                model_version=neg.model_version,
                gold_version=neg.gold_version,
            )
        )
    return out


def build_landing(
    repo: LandingRepository, principal: Principal, today: date
) -> LandingResponse:
    pending = (
        repo.hitl_pending(sorted(principal.reviewer_tasks))
        if Role.REVISOR in principal.roles
        else None
    )
    return LandingResponse(
        freshness=Freshness(
            last_ingestion_at=repo.last_ingestion_at(),
            last_delta=repo.last_delta(),
            last_monitor_at=repo.last_monitor_at(),
            data_until=repo.data_until(),
        ),
        open_alerts=repo.open_alerts(),
        banks=headlines(repo.ppi_kpis(), today),
        hitl_pending=pending,
    )
