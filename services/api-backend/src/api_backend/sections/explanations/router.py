from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from api_backend.auth.deps import ROUTE_ROLES, Settings, require
from api_backend.auth.roles import Role
from api_backend.bq.deps import reader_for, writer_for
from api_backend.online import OnlineClient
from api_backend.sections.explanations import service
from api_backend.sections.explanations.repository import (
    BigQueryExplanationsRepository,
    ExplanationsRepository,
)
from api_backend.sections.explanations.sample import sample_repository
from api_backend.sections.explanations.schemas import ExplainIn, ExplanationOut
from api_backend.sections.reviews.router import get_online

router = APIRouter(
    prefix="/api/v1/explanations",
    tags=["explanations"],
    dependencies=[Depends(require(Role.ANALISTA))],
)

for _method in ("GET", "POST"):
    ROUTE_ROLES[(_method, "/api/v1/explanations/{text_key}")] = Role.ANALISTA


def get_repository(
    request: Request, settings: Settings
) -> ExplanationsRepository:
    state = request.app.state
    repo = getattr(state, "explanations_repository", None)
    if repo is None:
        if settings.portal_data == "fixtures":
            repo = sample_repository()
        else:
            repo = BigQueryExplanationsRepository(
                reader_for(request, settings),
                writer_for(request, settings),
                settings,
            )
        state.explanations_repository = repo
    return repo


def now() -> datetime:
    return datetime.now(UTC)


Repo = Annotated[ExplanationsRepository, Depends(get_repository)]


@router.get("/{text_key}")
def get_explanation(
    text_key: str,
    repo: Repo,
    model_version: Annotated[str | None, Query(max_length=100)] = None,
) -> ExplanationOut:
    """La explicación guardada (``occlusion_v2`` si existe), o 404."""
    return service.get(repo, text_key, model_version)


@router.post("/{text_key}")
def compute_explanation(
    text_key: str,
    body: ExplainIn,
    repo: Repo,
    online: Annotated[OnlineClient, Depends(get_online)],
    at: Annotated[datetime, Depends(now)],
) -> ExplanationOut:
    """Calcula la explicación en ``voc-ml-online`` y la guarda."""
    return service.compute(
        repo, online, text_key, body.bank_id, body.id_resena, at
    )
