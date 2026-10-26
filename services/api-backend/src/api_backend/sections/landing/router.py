from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from api_backend.auth.deps import ROUTE_ROLES, Principal, Settings, require
from api_backend.auth.roles import Role
from api_backend.bq.deps import reader_for
from api_backend.sections.landing.repository import (
    BigQueryLandingRepository,
    LandingRepository,
    sample_repository,
)
from api_backend.sections.landing.schemas import LandingResponse
from api_backend.sections.landing.service import build_landing

router = APIRouter(prefix="/api/v1", tags=["landing"])

ROUTE_ROLES[("GET", "/api/v1/landing")] = Role.LECTOR


def get_repository(request: Request, settings: Settings) -> LandingRepository:
    state = request.app.state
    repo = getattr(state, "landing_repository", None)
    if repo is None:
        if settings.portal_data == "fixtures":
            repo = sample_repository()
        else:
            repo = BigQueryLandingRepository(
                reader_for(request, settings), settings
            )
        state.landing_repository = repo
    return repo


@router.get("/landing")
def landing(
    principal: Annotated[Principal, Depends(require(Role.LECTOR))],
    repo: Annotated[LandingRepository, Depends(get_repository)],
) -> LandingResponse:
    """Frescura, KPI con PPI por banco, alertas abiertas y casos pendientes."""
    return build_landing(repo, principal, datetime.now(UTC).date())
