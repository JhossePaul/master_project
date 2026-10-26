from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from voc_common import HitlTask

from api_backend.auth.deps import ROUTE_ROLES, Principal, Settings, require
from api_backend.auth.roles import Role
from api_backend.bq.deps import reader_for, writer_for
from api_backend.dlp import CommentSanitizer, build_sanitizer
from api_backend.fixtures import SAMPLE_DIR
from api_backend.sections.hitl import service
from api_backend.sections.hitl.repository import (
    BigQueryHitlRepository,
    CachedHitlRepository,
    HitlRepository,
)
from api_backend.sections.hitl.sample import sample_repository
from api_backend.sections.hitl.schemas import (
    GuidelineOut,
    HitlCase,
    HitlSummary,
    NextIn,
    ReviewOut,
    SentimentReviewIn,
)

router = APIRouter(prefix="/api/v1/hitl", tags=["hitl"])

for _method, _route in (
    ("GET", "summary"),
    ("POST", "next"),
    ("POST", "items/{item_id}/review"),
    ("POST", "items/{item_id}/skip"),
    ("POST", "items/{item_id}/release"),
    ("GET", "guidelines/{task}"),
):
    ROUTE_ROLES[(_method, f"/api/v1/hitl/{_route}")] = Role.REVISOR


def get_repository(request: Request, settings: Settings) -> HitlRepository:
    state = request.app.state
    repo = getattr(state, "hitl_repository", None)
    if repo is None:
        if settings.portal_data == "fixtures":
            repo = sample_repository()
        else:
            repo = CachedHitlRepository(
                BigQueryHitlRepository(
                    reader_for(request, settings),
                    writer_for(request, settings),
                    settings,
                )
            )
        state.hitl_repository = repo
    return repo


def get_sanitizer(request: Request, settings: Settings) -> CommentSanitizer:
    state = request.app.state
    if getattr(state, "comment_sanitizer", None) is None:
        state.comment_sanitizer = build_sanitizer(settings)
    return state.comment_sanitizer


def guidelines_dir(request: Request, settings: Settings) -> Path:
    override = getattr(request.app.state, "guidelines_dir", None)
    if override is not None:
        return Path(override)
    if settings.portal_data == "fixtures":
        return SAMPLE_DIR
    return Path(settings.guidelines_dir)


def now() -> datetime:
    return datetime.now(UTC)


Reviewer = Annotated[Principal, Depends(require(Role.REVISOR))]
Repo = Annotated[HitlRepository, Depends(get_repository)]
Now = Annotated[datetime, Depends(now)]


@router.get("/summary")
def summary(principal: Reviewer, repo: Repo, at: Now) -> HitlSummary:
    """Por cola permitida: solo conteos."""
    return service.summary(repo, principal, at)


@router.post(
    "/next",
    response_model=HitlCase,
    responses={204: {"description": "No hay casos pendientes"}},
)
def next_case(
    body: NextIn, principal: Reviewer, repo: Repo, at: Now
) -> HitlCase | Response:
    """Toma el siguiente caso: lo bloquea 15 minutos para el revisor."""
    case = service.take_next(repo, principal, HitlTask(body.task), at)
    return case if case is not None else Response(status_code=204)


@router.post("/items/{item_id}/review")
def review(  # noqa: PLR0913
    item_id: str,
    body: SentimentReviewIn,
    principal: Reviewer,
    repo: Repo,
    sanitizer: Annotated[CommentSanitizer, Depends(get_sanitizer)],
    at: Now,
) -> ReviewOut:
    return service.save_review(repo, sanitizer, principal, item_id, body, at)


@router.post("/items/{item_id}/skip", status_code=204)
def skip(item_id: str, principal: Reviewer, repo: Repo, at: Now) -> Response:
    service.skip(repo, principal, item_id, at)
    return Response(status_code=204)


@router.post("/items/{item_id}/release", status_code=204)
def release(item_id: str, principal: Reviewer, repo: Repo, at: Now) -> Response:
    """El portal lo llama al salir de la pantalla (``sendBeacon``)."""
    service.release(repo, principal, item_id, at)
    return Response(status_code=204)


@router.get("/guidelines/{task}")
def guideline(
    task: HitlTask,
    principal: Reviewer,
    repo: Repo,
    request: Request,
    settings: Settings,
    at: Now,
) -> GuidelineOut:
    return service.read_guideline(
        repo, principal, task, guidelines_dir(request, settings), at
    )
