"""Reglas del Explorador: ventana, filtros, búsqueda y ficha."""

from datetime import UTC, date, datetime

from api_backend.errors import ApiError, ErrorCode
from api_backend.online import OnlineClient
from api_backend.sections.reviews.filters import (
    ReviewFilters,
    months_back,
    resolve_window,
)
from api_backend.sections.reviews.repository import ReviewsRepository
from api_backend.sections.reviews.schemas import (
    Facets,
    ReviewDetail,
    ReviewPage,
    SearchHit,
    SearchIn,
    SearchResponse,
    SortKey,
    WindowApplied,
)

NO_TEXT = ""


def build_filters(  # noqa: PLR0913
    *,
    today: date,
    months: int,
    banks: list[str],
    date_from: date | None,
    date_to: date | None,
    sentiment: list[str],
    families: list[str],
    flag_update: bool | None,
    flag_security: bool | None,
    topic_id: int | None,
    stars: list[int],
    version: str | None,
    hitl_reviewed: bool | None,
) -> tuple[ReviewFilters, WindowApplied]:
    if date_from and date_to and date_from > date_to:
        raise ApiError(ErrorCode.INVALID, "Rango de fechas no válido")
    start, end, window = resolve_window(today, months, date_from, date_to)
    return (
        ReviewFilters(
            banks=tuple(banks),
            date_from=start,
            date_to=end,
            sentiment=tuple(sentiment),
            families=tuple(families),
            flag_update=flag_update,
            flag_security=flag_security,
            topic_id=topic_id,
            stars=tuple(stars),
            version=version,
            hitl_reviewed=hitl_reviewed,
        ),
        window,
    )


def facets(
    repo: ReviewsRepository, f: ReviewFilters, window: WindowApplied
) -> Facets:
    total, by = repo.facets(f)
    return Facets(
        total=total,
        by_bank=by.get("bank", []),
        by_month=by.get("month", []),
        by_sentiment=by.get("sentiment", []),
        by_stars=by.get("stars", []),
        by_family=by.get("family", []),
        by_flag_update=by.get("flag_update", []),
        by_flag_security=by.get("flag_security", []),
        by_topic=by.get("topic", []),
        by_hitl=by.get("hitl", []),
        window_applied=window,
    )


def page(  # noqa: PLR0913
    repo: ReviewsRepository,
    f: ReviewFilters,
    window: WindowApplied,
    sort: SortKey,
    number: int,
    size: int,
) -> ReviewPage:
    rows, total = repo.page(f, sort, number, size)
    return ReviewPage(
        rows=rows,
        total=total,
        page=number,
        page_size=size,
        window_applied=window,
    )


def detail(
    repo: ReviewsRepository, bank_id: str, id_resena: str
) -> ReviewDetail:
    found = repo.detail(bank_id, id_resena)
    if found is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No existe la reseña")
    row, prompt = found
    return ReviewDetail(
        row=row,
        aspects_prompt_version=prompt,
        hitl_reviews=repo.hitl_reviews(id_resena),
        explanation=repo.stored_explanation(row.text_key),
    )


def search(
    repo: ReviewsRepository,
    online: OnlineClient,
    body: SearchIn,
    *,
    today: date,
    window_months: int,
    all_banks: list[str],
) -> SearchResponse:
    months = body.months or window_months
    if months > window_months:
        raise ApiError(
            ErrorCode.INVALID,
            f"La búsqueda abarca como máximo {window_months} meses",
        )
    banks = list(body.banks) if body.banks else all_banks
    embedding = online.embed(
        body.query
    )  # la consulta no se guarda ni se registra
    from_month = months_back(today, months)
    stats: dict[str, int] = {}
    hits = repo.vector_search(
        embedding.embedding, banks, from_month, body.k, stats
    )
    groups = repo.groups(hits, from_month)
    out = [
        SearchHit(
            text_key=h.text_key,
            bank_id=h.bank_id,
            distance=h.distance,
            n_reviews=groups[(h.text_key, h.bank_id)].n_reviews,
            example=groups[(h.text_key, h.bank_id)].example,
        )
        for h in hits
        if (h.text_key, h.bank_id) in groups
    ]
    return SearchResponse(
        hits=out,
        embedding_model=embedding.embedding_model,
        months_searched=months,
        bytes_billed=stats.get("bytes_billed", 0),
    )


def today_utc() -> date:
    return datetime.now(UTC).date()
