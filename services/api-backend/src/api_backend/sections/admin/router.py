from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from voc_common import DriftPolicy, RiskPolicy

from api_backend.auth.deps import ROUTE_ROLES, Principal, Settings, require
from api_backend.auth.roles import Role
from api_backend.bq.deps import reader_for, writer_for
from api_backend.sections.admin import service
from api_backend.sections.admin.repository import (
    AdminRepository,
    BigQueryAdminRepository,
)
from api_backend.sections.admin.sample import sample_repository
from api_backend.sections.admin.schemas import (
    CoverageCurveResponse,
    DriftPolicyResponse,
    DriftRatesIn,
    DriftRatesResponse,
    DriftSaveIn,
    GoldCreateIn,
    GoldCriteria,
    GoldItemsResponse,
    GoldPreview,
    GoldVersionOut,
    RiskChangeIn,
    RiskPolicyResponse,
    RiskPreview,
    RiskSaveIn,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

for _method, _route in (
    ("GET", "risk-policy"),
    ("GET", "coverage-curve"),
    ("POST", "risk-policy/preview"),
    ("POST", "risk-policy"),
    ("GET", "drift-policy"),
    ("POST", "drift-policy/rates"),
    ("POST", "drift-policy"),
    ("GET", "gold-versions"),
    ("POST", "gold-versions/preview"),
    ("POST", "gold-versions"),
    ("GET", "gold-versions/{gold_version}/items"),
):
    ROUTE_ROLES[(_method, f"/api/v1/admin/{_route}")] = Role.ADMINISTRADOR


def get_repository(request: Request, settings: Settings) -> AdminRepository:
    state = request.app.state
    repo = getattr(state, "admin_repository", None)
    if repo is None:
        if settings.portal_data == "fixtures":
            repo = sample_repository()
        else:
            repo = BigQueryAdminRepository(
                reader_for(request, settings),
                writer_for(request, settings),
                settings,
            )
        state.admin_repository = repo
    return repo


def now() -> datetime:
    return datetime.now(UTC)


Admin = Annotated[Principal, Depends(require(Role.ADMINISTRADOR))]
Repo = Annotated[AdminRepository, Depends(get_repository)]
Now = Annotated[datetime, Depends(now)]


@router.get("/risk-policy")
def risk_policy(_: Admin, repo: Repo, at: Now) -> RiskPolicyResponse:
    """La versión vigente y la tabla completa, por ``valid_from``."""
    return service.risk_policy(repo, at)


@router.get("/coverage-curve")
def coverage_curve(
    _: Admin,
    repo: Repo,
    at: Now,
    model_version: Annotated[str | None, Query()] = None,
) -> CoverageCurveResponse:
    """Curva del modelo promovido, su punto vigente y el tiempo medido."""
    return service.coverage_curve(repo, model_version, at)


@router.post("/risk-policy/preview")
def preview_risk_policy(
    body: RiskChangeIn, principal: Admin, repo: Repo, at: Now
) -> RiskPreview:
    """La versión propuesta y su diferencia, sin guardar nada."""
    return service.preview_risk(repo, principal, body, at)


@router.post("/risk-policy", status_code=201)
def save_risk_policy(
    body: RiskSaveIn, principal: Admin, repo: Repo, at: Now
) -> RiskPolicy:
    """Crea la versión siguiente (solo inserta)."""
    return service.save_risk(repo, principal, body, at)


@router.get("/drift-policy")
def drift_policy(
    _: Admin, repo: Repo, at: Now, bank: Annotated[str, Query()]
) -> DriftPolicyResponse:
    return service.drift_policy(repo, bank, at)


@router.post("/drift-policy/rates")
def drift_rates(
    body: DriftRatesIn, _: Admin, repo: Repo, at: Now
) -> DriftRatesResponse:
    """Meses de alerta al año con los umbrales propuestos y con los vigentes."""
    return service.drift_rates(repo, body.bank, body.thresholds, at)


@router.post("/drift-policy", status_code=201)
def save_drift_policy(
    body: DriftSaveIn, principal: Admin, repo: Repo, at: Now
) -> DriftPolicy:
    return service.save_drift(
        repo,
        principal,
        body.bank,
        body.base_version,
        body.changes,
        body.reason,
        at,
    )


@router.get("/gold-versions")
def gold_versions(_: Admin, repo: Repo) -> list[GoldVersionOut]:
    return service.gold_versions(repo)


@router.post("/gold-versions/preview")
def preview_gold(body: GoldCriteria, _: Admin, repo: Repo) -> GoldPreview:
    return service.preview_gold(repo, body)


@router.post("/gold-versions", status_code=201)
def create_gold(
    body: GoldCreateIn, principal: Admin, repo: Repo, at: Now
) -> GoldVersionOut:
    return service.create_gold(repo, principal, body, at)


@router.get("/gold-versions/{gold_version}/items")
def gold_items(gold_version: str, _: Admin, repo: Repo) -> GoldItemsResponse:
    return service.gold_items(repo, gold_version)
