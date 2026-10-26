from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from voc_common import AlertStatus

from api_backend.auth.deps import ROUTE_ROLES, Principal, Settings, require
from api_backend.auth.roles import Role
from api_backend.bq.deps import reader_for, writer_for
from api_backend.dlp import CommentSanitizer, build_sanitizer
from api_backend.sections.alerts import service
from api_backend.sections.alerts.repository import (
    AlertRepository,
    BigQueryAlertRepository,
)
from api_backend.sections.alerts.sample import sample_repository
from api_backend.sections.alerts.schemas import (
    AlertDetail,
    AlertEventIn,
    AlertRow,
    AlertSummary,
)

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])

ROUTE_ROLES[("GET", "/api/v1/alerts/summary")] = Role.LECTOR
for _method, _route in (
    ("GET", ""),
    ("GET", "/{alert_id}"),
    ("POST", "/{alert_id}/events"),
):
    ROUTE_ROLES[(_method, f"/api/v1/alerts{_route}")] = Role.ANALISTA


def get_repository(request: Request, settings: Settings) -> AlertRepository:
    state = request.app.state
    repo = getattr(state, "alert_repository", None)
    if repo is None:
        if settings.portal_data == "fixtures":
            repo = sample_repository()
        else:
            repo = BigQueryAlertRepository(
                reader_for(request, settings),
                writer_for(request, settings),
                settings,
            )
        state.alert_repository = repo
    return repo


def get_sanitizer(request: Request, settings: Settings) -> CommentSanitizer:
    state = request.app.state
    if getattr(state, "comment_sanitizer", None) is None:
        state.comment_sanitizer = build_sanitizer(settings)
    return state.comment_sanitizer


def now() -> datetime:
    return datetime.now(UTC)


Analyst = Annotated[Principal, Depends(require(Role.ANALISTA))]
Reader = Annotated[Principal, Depends(require(Role.LECTOR))]
Repo = Annotated[AlertRepository, Depends(get_repository)]
Now = Annotated[datetime, Depends(now)]


# ``/summary`` va antes de ``/{alert_id}``: si no, lo tomaría como un id.
@router.get("/summary")
def summary(principal: Reader, repo: Repo) -> AlertSummary:
    """Solo conteos por banco: la usa la landing."""
    return service.summary(repo)


@router.get("")
def list_alerts(
    principal: Analyst,
    repo: Repo,
    at: Now,
    status: AlertStatus | None = None,
    bank: Annotated[list[str] | None, Query()] = None,
) -> list[AlertRow]:
    """Las alertas con su estado vigente, de la más reciente a la más vieja."""
    return service.list_alerts(repo, status, bank or [], at)


@router.get("/{alert_id}")
def alert_detail(
    alert_id: str, principal: Analyst, repo: Repo, at: Now
) -> AlertDetail:
    return service.detail(repo, alert_id, at)


@router.post("/{alert_id}/events")
def add_event(  # noqa: PLR0913
    alert_id: str,
    body: AlertEventIn,
    principal: Analyst,
    repo: Repo,
    sanitizer: Annotated[CommentSanitizer, Depends(get_sanitizer)],
    at: Now,
) -> AlertDetail:
    """Confirma, descarta o reabre; 409 si el estado ya cambió."""
    return service.add_event(repo, sanitizer, principal, alert_id, body, at)
