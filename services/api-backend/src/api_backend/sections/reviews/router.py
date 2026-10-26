from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field

from api_backend.auth.deps import ROUTE_ROLES, Settings, require
from api_backend.auth.roles import Role
from api_backend.bq.deps import reader_for
from api_backend.online import OnlineClient, build_online_client
from api_backend.sections.kpis.schemas import BANK_IDS, BankId
from api_backend.sections.reviews import service
from api_backend.sections.reviews.repository import (
    BigQueryReviewsRepository,
    ReviewsRepository,
)
from api_backend.sections.reviews.sample import sample_repository
from api_backend.sections.reviews.schemas import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    Facets,
    ReviewDetail,
    ReviewPage,
    SearchIn,
    SearchResponse,
    SentimentValue,
    SortKey,
)

router = APIRouter(
    prefix="/api/v1/reviews",
    tags=["reviews"],
    dependencies=[Depends(require(Role.ANALISTA))],
)

for _method, _route in (
    ("GET", ""),
    ("GET", "/facets"),
    ("GET", "/{bank_id}/{id_resena}"),
    ("POST", "/search"),
):
    ROUTE_ROLES[(_method, f"/api/v1/reviews{_route}")] = Role.ANALISTA


def get_repository(request: Request, settings: Settings) -> ReviewsRepository:
    state = request.app.state
    repo = getattr(state, "reviews_repository", None)
    if repo is None:
        if settings.portal_data == "fixtures":
            repo = sample_repository()
        else:
            repo = BigQueryReviewsRepository(
                reader_for(request, settings), settings
            )
        state.reviews_repository = repo
    return repo


def get_online(request: Request, settings: Settings) -> OnlineClient:
    state = request.app.state
    if getattr(state, "online_client", None) is None:
        state.online_client = build_online_client(
            settings.online_service_url, settings.portal_data
        )
    return state.online_client


Repo = Annotated[ReviewsRepository, Depends(get_repository)]


class FilterParams:
    """Filtros comunes como parámetros de la URL (una lista por repetición)."""

    def __init__(  # noqa: PLR0913
        self,
        banks: Annotated[list[BankId] | None, Query()] = None,
        date_from: date | None = None,
        date_to: date | None = None,
        sentiment: Annotated[list[SentimentValue] | None, Query()] = None,
        families: Annotated[list[str] | None, Query()] = None,
        flag_update: bool | None = None,
        flag_security: bool | None = None,
        topic_id: Annotated[int | None, Query(ge=0)] = None,
        stars: Annotated[
            list[Annotated[int, Field(ge=1, le=5)]] | None, Query()
        ] = None,
        version: Annotated[str | None, Query(max_length=40)] = None,
        hitl_reviewed: bool | None = None,
    ) -> None:
        self.banks: list[str] = list(banks or BANK_IDS)
        self.date_from = date_from
        self.date_to = date_to
        self.sentiment: list[str] = list(sentiment or [])
        self.families = list(families or [])
        self.flag_update = flag_update
        self.flag_security = flag_security
        self.topic_id = topic_id
        self.stars = list(stars or [])
        self.version = version
        self.hitl_reviewed = hitl_reviewed


Filters = Annotated[FilterParams, Depends()]


def _filters(p: FilterParams, settings: Settings):  # noqa: ANN202
    return service.build_filters(
        today=service.today_utc(),
        months=settings.review_window_months,
        banks=p.banks,
        date_from=p.date_from,
        date_to=p.date_to,
        sentiment=p.sentiment,
        families=p.families,
        flag_update=p.flag_update,
        flag_security=p.flag_security,
        topic_id=p.topic_id,
        stars=p.stars,
        version=p.version,
        hitl_reviewed=p.hitl_reviewed,
    )


@router.get("/facets")
def facets(repo: Repo, params: Filters, settings: Settings) -> Facets:
    """Conteos con los filtros aplicados; solo agregados."""
    f, window = _filters(params, settings)
    return service.facets(repo, f, window)


@router.get("")
def reviews(  # noqa: PLR0913
    repo: Repo,
    params: Filters,
    settings: Settings,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE)
    ] = DEFAULT_PAGE_SIZE,
    sort: SortKey = "fecha_desc",
) -> ReviewPage:
    """Reseñas sanitizadas dentro de la ventana, con paginación del servidor."""
    f, window = _filters(params, settings)
    return service.page(repo, f, window, sort, page, page_size)


@router.post("/search")
def search(
    body: SearchIn,
    repo: Repo,
    online: Annotated[OnlineClient, Depends(get_online)],
    settings: Settings,
) -> SearchResponse:
    """Búsqueda semántica; la consulta no se guarda ni se registra."""
    return service.search(
        repo,
        online,
        body,
        today=service.today_utc(),
        window_months=settings.review_window_months,
        all_banks=list(BANK_IDS),
    )


@router.get("/{bank_id}/{id_resena}")
def detail(bank_id: BankId, id_resena: str, repo: Repo) -> ReviewDetail:
    """La ficha de una reseña (sin ventana)."""
    return service.detail(repo, bank_id, id_resena)
