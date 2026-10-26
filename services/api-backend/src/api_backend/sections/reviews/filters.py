"""Filtros comunes del Explorador y la ventana de fechas."""

from dataclasses import dataclass
from datetime import date, timedelta

from api_backend.sections.reviews.schemas import WindowApplied


@dataclass(frozen=True)
class ReviewFilters:
    """Filtros ya resueltos: fechas inclusivas dentro de la ventana."""

    banks: tuple[str, ...]
    date_from: date
    date_to: date
    sentiment: tuple[str, ...] = ()
    families: tuple[str, ...] = ()
    flag_update: bool | None = None
    flag_security: bool | None = None
    topic_id: int | None = None
    stars: tuple[int, ...] = ()
    version: str | None = None
    hitl_reviewed: bool | None = None


def months_back(today: date, months: int) -> date:
    """Primer día del mes que está ``months`` meses antes de ``today``."""
    index = today.year * 12 + (today.month - 1) - months
    return date(index // 12, index % 12 + 1, 1)


def resolve_window(
    today: date,
    months: int,
    date_from: date | None,
    date_to: date | None,
) -> tuple[date, date, WindowApplied]:
    """Recorta el rango a la ventana de ``months`` meses y lo informa."""
    floor = months_back(today, months)
    start = date_from or floor
    end = date_to or today
    clipped = start < floor or end > today
    start = max(start, floor)
    end = min(end, today)
    if end < start:
        end = start
    return (
        start,
        end,
        WindowApplied(
            date_from=start, date_to=end, clipped=clipped, months=months
        ),
    )


def day_after(day: date) -> date:
    return day + timedelta(days=1)
