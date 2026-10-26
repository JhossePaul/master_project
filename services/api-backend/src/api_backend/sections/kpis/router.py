from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from api_backend.auth.deps import ROUTE_ROLES, Settings, require
from api_backend.auth.roles import Role
from api_backend.bq.deps import reader_for
from api_backend.errors import ApiError, ErrorCode
from api_backend.sections.kpis import service
from api_backend.sections.kpis.repository import (
    BigQueryKpisRepository,
    KpisRepository,
    sample_repository,
)
from api_backend.sections.kpis.schemas import (
    BANK_IDS,
    BankCard,
    BankId,
    DailyPoint,
    DailyTopics,
    FamiliesResponse,
    MatrixCell,
    ModelChange,
    MonthlyKpi,
    TopicMonth,
    VersionsResponse,
)

DEFAULT_DAYS = 90
MAX_DAYS = 800
PERIOD = r"^\d{4}-(0[1-9]|1[0-2])$"

router = APIRouter(
    prefix="/api/v1/kpis",
    tags=["kpis"],
    dependencies=[Depends(require(Role.LECTOR))],
)

for _route in (
    "cards",
    "daily",
    "daily-topics",
    "monthly",
    "families",
    "topics",
    "matrix",
    "versions",
    "model-changes",
):
    ROUTE_ROLES[("GET", f"/api/v1/kpis/{_route}")] = Role.LECTOR


def get_repository(request: Request, settings: Settings) -> KpisRepository:
    state = request.app.state
    repo = getattr(state, "kpis_repository", None)
    if repo is None:
        if settings.portal_data == "fixtures":
            repo = sample_repository()
        else:
            repo = BigQueryKpisRepository(
                reader_for(request, settings), settings
            )
        state.kpis_repository = repo
    return repo


Repo = Annotated[KpisRepository, Depends(get_repository)]
Banks = Annotated[list[BankId] | None, Query()]


def _banks(banks: list[BankId] | None) -> list[BankId]:
    return list(banks) if banks else list(BANK_IDS)


@router.get("/cards")
def cards(
    repo: Repo,
    banks: Banks = None,
    period: Annotated[str | None, Query(pattern=PERIOD)] = None,
) -> list[BankCard]:
    """Tarjetas por banco con PPI, el mismo mes del año anterior y alertas."""
    return service.cards(repo, _banks(banks), period)


@router.get("/daily")
def daily(
    repo: Repo,
    banks: Banks = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[DailyPoint]:
    """Serie diaria cruda (sin PPI) por banco y día UTC."""
    end = date_to or datetime.now(UTC).date()
    start = date_from or end - timedelta(days=DEFAULT_DAYS)
    if start > end or (end - start).days > MAX_DAYS:
        raise ApiError(ErrorCode.INVALID, "Rango de fechas no válido")
    return repo.daily(_banks(banks), start, end)


@router.get("/daily-topics")
def daily_topics(repo: Repo, bank: BankId, day: date) -> DailyTopics:
    """Familias y tópicos de las negativas de un día, con su participación."""
    return service.daily_topics(repo, bank, day)


@router.get("/monthly")
def monthly(
    repo: Repo,
    banks: Banks = None,
    metrics: str = ",".join(service.MONTHLY_METRICS),
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[MonthlyKpi]:
    """KPI mensuales con PPI y la proporción cruda al lado."""
    chosen = [m.strip() for m in metrics.split(",") if m.strip()]
    if not chosen or not set(chosen) <= set(service.MONTHLY_METRICS):
        raise ApiError(ErrorCode.INVALID, "Métrica no admitida")
    return service.monthly(repo, _banks(banks), chosen, date_from, date_to)


@router.get("/families")
def families(repo: Repo, banks: Banks = None) -> FamiliesResponse:
    """Negativas por familia y marca ``u``, en nivel y en anomalía (z)."""
    return service.families(repo, _banks(banks))


@router.get("/topics")
def topics(repo: Repo, banks: Banks = None) -> list[TopicMonth]:
    """Tópicos útiles de la versión vigente, por banco y mes."""
    return service.topics(repo, _banks(banks))


@router.get("/matrix")
def matrix(
    repo: Repo,
    banks: Banks = None,
    period: Annotated[str | None, Query(pattern=PERIOD)] = None,
) -> list[MatrixCell]:
    """Matriz estrellas × texto de un mes."""
    return service.matrix(repo, _banks(banks), period)


@router.get("/versions")
def versions(repo: Repo, bank: BankId) -> VersionsResponse:
    """Proporción de negativas por versión de la app, con IC de Wilson."""
    return service.versions(repo, bank)


@router.get("/model-changes")
def model_changes(repo: Repo) -> list[ModelChange]:
    """Versiones del modelo de sentimiento promovidas, para anotar la serie."""
    return repo.model_changes()
