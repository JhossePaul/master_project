from typing import Annotated

from fastapi import APIRouter, Depends
from voc_common import HitlTask

from api_backend.auth.deps import ROUTE_ROLES, Principal, Settings, require
from api_backend.auth.roles import Role
from api_backend.sections.me.schemas import MeResponse

router = APIRouter(prefix="/api/v1", tags=["me"])

ROUTE_ROLES[("GET", "/api/v1/me")] = Role.LECTOR


@router.get("/me")
def me(
    principal: Annotated[Principal, Depends(require(Role.LECTOR))],
    settings: Settings,
) -> MeResponse:
    """Cualquier cuenta con rol (todos incluyen al lector)."""
    return MeResponse(
        email=principal.email,
        actor_hash=principal.actor_hash,
        roles=[r for r in Role if r in principal.roles],
        reviewer_tasks=[t for t in HitlTask if t in principal.reviewer_tasks],
        environment=settings.environment,
        commit=settings.build_commit,
    )
