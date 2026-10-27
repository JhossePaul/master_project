from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from voc_common import RunKind

from api_backend.auth.deps import ROUTE_ROLES, Principal, Settings, require
from api_backend.auth.roles import Role
from api_backend.bq.deps import reader_for
from api_backend.errors import ApiError, ErrorCode
from api_backend.jobs import CloudRunJobs, JobRunner
from api_backend.sections.admin import service as admin_service
from api_backend.sections.admin.router import Repo as AdminRepo
from api_backend.sections.admin.schemas import CoverageCurveResponse
from api_backend.sections.mlops import calibration as calibration_source
from api_backend.sections.mlops import service
from api_backend.sections.mlops.repository import (
    BigQueryMlopsRepository,
    MlopsRepository,
)
from api_backend.sections.mlops.sample import sample_repository
from api_backend.sections.mlops.schemas import (
    Action,
    ActionIn,
    ActionOut,
    CalibrationOut,
    DriftResponse,
    EligibilityRow,
    IngestionRunOut,
    ModelsResponse,
    QualityResponse,
    RunsResponse,
    TopicsContextResponse,
)

router = APIRouter(prefix="/api/v1/mlops", tags=["mlops"])

for _route in (
    "quality",
    "coverage-curve",
    "drift",
    "topics-context",
    "models",
    "models/{model_version}/calibration",
    "runs",
    "ingestion",
    "eligibility",
):
    ROUTE_ROLES[("GET", f"/api/v1/mlops/{_route}")] = Role.ANALISTA
ROUTE_ROLES[("POST", "/api/v1/mlops/actions/{action}")] = Role.ADMINISTRADOR


def get_repository(request: Request, settings: Settings) -> MlopsRepository:
    state = request.app.state
    repo = getattr(state, "mlops_repository", None)
    if repo is None:
        if settings.portal_data == "fixtures":
            repo = sample_repository()
        else:
            repo = BigQueryMlopsRepository(
                reader_for(request, settings), settings
            )
        state.mlops_repository = repo
    return repo


def get_jobs(request: Request, settings: Settings) -> JobRunner:
    state = request.app.state
    if getattr(state, "job_runner", None) is None:
        state.job_runner = CloudRunJobs(
            settings.gcp_project_id, settings.region
        )
    return state.job_runner


def get_manifests(
    request: Request, settings: Settings
) -> calibration_source.ManifestSource:
    state = request.app.state
    if getattr(state, "manifest_source", None) is None:
        if settings.portal_data == "fixtures" or not (
            settings.gcs_raw_datalake_bucket
        ):
            state.manifest_source = calibration_source.NoManifests()
        else:
            from google.cloud import storage

            state.manifest_source = calibration_source.GcsManifests(
                storage.Client(project=settings.gcp_project_id),
                settings.gcs_raw_datalake_bucket,
                settings.ml_artifacts_prefix,
            )
    return state.manifest_source


def now() -> datetime:
    return datetime.now(UTC)


Analyst = Annotated[Principal, Depends(require(Role.ANALISTA))]
Admin = Annotated[Principal, Depends(require(Role.ADMINISTRADOR))]
Repo = Annotated[MlopsRepository, Depends(get_repository)]
Jobs = Annotated[JobRunner, Depends(get_jobs)]
Manifests = Annotated[calibration_source.ManifestSource, Depends(get_manifests)]
Now = Annotated[datetime, Depends(now)]


@router.get("/quality")
def quality(_: Analyst, repo: Repo) -> QualityResponse:
    """Serie de cada señal de ``model_quality`` con su umbral y estado."""
    return service.quality(repo)


@router.get("/coverage-curve")
def coverage_curve(
    _: Analyst,
    repo: AdminRepo,
    at: Now,
    model_version: Annotated[str | None, Query()] = None,
) -> CoverageCurveResponse:
    """La curva del modelo promovido (o de una candidata), de solo lectura."""
    return admin_service.coverage_curve(repo, model_version, at)


@router.get("/drift")
def drift(
    _: Analyst, repo: Repo, at: Now, metric: str | None = None
) -> DriftResponse:
    return service.drift(repo, metric, at)


@router.get("/topics-context")
def topics_context(_: Analyst, repo: Repo, at: Now) -> TopicsContextResponse:
    return service.topics_context(repo, at)


@router.get("/models")
def models(_: Analyst, repo: Repo, at: Now) -> ModelsResponse:
    """Versiones, su historia y qué acciones están habilitadas."""
    return service.models(repo, at)


@router.get("/models/{model_version}/calibration")
def calibration(
    model_version: str,
    _: Analyst,
    manifests: Manifests,
    settings: Settings,
) -> CalibrationOut:
    found = calibration_source.calibration_of(
        model_version, manifests, Path(settings.calibration_docs_path)
    )
    if found is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No hay calibración guardada para {model_version}",
        )
    return found


@router.get("/runs")
def runs(
    _: Analyst,
    repo: Repo,
    at: Now,
    kind: RunKind | None = None,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> RunsResponse:
    return service.runs(repo, kind, days, at)


@router.get("/ingestion")
def ingestion(
    _: Analyst,
    repo: Repo,
    at: Now,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> list[IngestionRunOut]:
    return service.ingestion(repo, days, at)


@router.get("/eligibility")
def eligibility(_: Analyst, repo: Repo) -> list[EligibilityRow]:
    return service.eligibility(repo)


@router.post("/actions/{action}")
def run_action(  # noqa: PLR0913
    action: Action,
    body: ActionIn,
    principal: Admin,
    repo: Repo,
    jobs: Jobs,
    at: Now,
) -> ActionOut:
    """Lanza el Job de la acción; 409 si no está habilitada."""
    return service.execute(repo, jobs, principal, action, body, at)
