"""Reglas de MLOps: señales, registro de modelos y acciones sobre el modelo.

Las acciones lanzan un Job de EPIC-6 con argumentos que arma el servidor. Cada
una se revisa aquí, no en el portal: el portal solo pinta lo que dice
``GET /mlops/models``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final

import requests
from google.auth.exceptions import GoogleAuthError
from voc_common import (
    InferenceRun,
    ModelQuality,
    ModelStatus,
    ModelVersion,
    PromotionCheckResult,
    PromotionVerdict,
    QualitySignal,
    QualityStatus,
    RetrainTrigger,
    RiskPolicy,
    RunKind,
    RunStatus,
    TopicRefitTrigger,
)

from api_backend.auth.deps import Principal
from api_backend.errors import ApiError, ErrorCode
from api_backend.jobs import JobRunner
from api_backend.sections.mlops.repository import MlopsRepository
from api_backend.sections.mlops.schemas import (
    FORCE_WORD,
    Action,
    ActionIn,
    ActionOut,
    ActionState,
    ContextSeries,
    DriftCell,
    DriftResponse,
    EligibilityRow,
    Freshness,
    IngestionRunOut,
    ModelOut,
    ModelsResponse,
    PromotionCheckOut,
    QualityPoint,
    QualityResponse,
    QualitySeries,
    RunOut,
    RunsResponse,
    StatusStep,
    TopicsContextResponse,
)

SHORT_HASH: Final = 8
DRIFT_MONTHS: Final = 24
TOPIC_PREFIX: Final = "topic_"
FAMILY_PREFIX: Final = "family_"
USAGE_SERIES: Final = "flag_update_share"
# Tiempo máximo de cada Job (infra): una fila ``running`` más vieja es de una
# corrida que murió sin registrarse y no cuenta como en curso.
MAX_AGE: Final[dict[RunKind, timedelta]] = {
    RunKind.TRAINING: timedelta(seconds=14400),
    RunKind.RESCORING: timedelta(seconds=10800),
    RunKind.TOPIC_REFIT: timedelta(seconds=3600),
}
JOB_BY_ACTION: Final[dict[Action, str]] = {
    Action.RETRAIN: "voc-ml-training",
    Action.RESCORE: "voc-ml-rescoring",
    Action.PROMOTE: "voc-ml-promote",
    Action.ROLLBACK: "voc-ml-promote",
    Action.TOPICS_REFIT: "voc-ml-topics-refit",
}
VERSION_ACTIONS: Final = (Action.RESCORE, Action.PROMOTE, Action.ROLLBACK)


def _short(digest: str | None) -> str | None:
    return digest[:SHORT_HASH] if digest else None


def _period(day: date) -> str:
    return f"{day:%Y-%m}"


# -- Señales -----------------------------------------------------------------


def _point(row: ModelQuality) -> QualityPoint:
    return QualityPoint(
        period=row.period,
        value=row.value,
        ci_low=row.ci_low,
        ci_high=row.ci_high,
        n=row.n,
        threshold=row.threshold,
        status=row.status,
        model_version=row.model_version,
        llm_model=row.llm_model,
        prompt_version=row.prompt_version,
        computed_at=row.computed_at,
    )


def quality(repo: MlopsRepository) -> QualityResponse:
    rows = repo.quality()
    return QualityResponse(
        signals=[
            QualitySeries(
                signal=signal,
                points=[_point(r) for r in rows if r.signal is signal],
            )
            for signal in QualitySignal
        ]
    )


def _cell(row: object) -> DriftCell:
    return DriftCell(
        bank_id=row.bank_id,  # type: ignore[attr-defined]
        period=_period(row.period),  # type: ignore[attr-defined]
        value=row.value,  # type: ignore[attr-defined]
        baseline=row.baseline,  # type: ignore[attr-defined]
        z=row.z,  # type: ignore[attr-defined]
        psi=row.psi,  # type: ignore[attr-defined]
        threshold=row.threshold,  # type: ignore[attr-defined]
        alert=row.alert,  # type: ignore[attr-defined]
    )


def _window(now: datetime) -> tuple[date, date]:
    index = now.year * 12 + now.month - 1
    first = index - (DRIFT_MONTHS - 1)
    return date(first // 12, first % 12 + 1, 1), date(now.year, now.month, 1)


def drift(
    repo: MlopsRepository, metric: str | None, now: datetime
) -> DriftResponse:
    series = [m for m in repo.drift_series() if not m.startswith(TOPIC_PREFIX)]
    if metric is None:
        metric = series[0] if series else ""
    elif metric not in series:
        raise ApiError(ErrorCode.NOT_FOUND, f"No hay una serie {metric!r}")
    first, last = _window(now)
    rows = repo.drift(first, last, names=(metric,)) if metric else []
    return DriftResponse(
        metric=metric,
        series=series,
        banks=sorted({r.bank_id for r in rows}),
        cells=[_cell(r) for r in rows],
    )


def _by_metric(rows: Sequence[object]) -> list[ContextSeries]:
    metrics = sorted({r.metric for r in rows})  # type: ignore[attr-defined]
    return [
        ContextSeries(
            metric=metric,
            cells=[_cell(r) for r in rows if r.metric == metric],  # type: ignore[attr-defined]
        )
        for metric in metrics
    ]


def topics_context(
    repo: MlopsRepository, now: datetime
) -> TopicsContextResponse:
    first, last = _window(now)
    topics = repo.drift(first, last, prefix=TOPIC_PREFIX)
    families = repo.drift(
        first, last, names=(USAGE_SERIES,), prefix=FAMILY_PREFIX
    )
    return TopicsContextResponse(
        topics=_by_metric(topics), families=_by_metric(families)
    )


# -- Registro de modelos y acciones -----------------------------------------


def _current_policy(repo: MlopsRepository, now: datetime) -> RiskPolicy | None:
    live = [p for p in repo.risk_policies() if p.valid_from <= now]
    return live[-1] if live else None


def _quarter_start(day: date) -> date:
    return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)


def _next_quarter(day: date) -> date:
    start = _quarter_start(day)
    index = start.year * 12 + start.month - 1 + 3
    return date(index // 12, index % 12 + 1, 1)


@dataclass(frozen=True)
class Registry:
    """Lo que las reglas de las acciones necesitan, leído una vez."""

    policy: RiskPolicy | None
    rows: dict[str, list[ModelVersion]]
    checks: dict[str, PromotionCheckResult]
    retrain_notice: bool
    running: frozenset[RunKind]
    last_topic_fit: datetime | None

    def latest(self, version: str) -> ModelVersion:
        return self.rows[version][-1]

    @property
    def current(self) -> str | None:
        return _current_of(self.rows)

    def ever_promoted(self, version: str) -> bool:
        return any(r.status is ModelStatus.PROMOTED for r in self.rows[version])


def _current_of(rows: dict[str, list[ModelVersion]]) -> str | None:
    """La versión promovida más reciente (la última fila de cada versión)."""
    promoted = [
        history[-1]
        for history in rows.values()
        if history[-1].status is ModelStatus.PROMOTED
    ]
    if not promoted:
        return None
    return max(
        promoted, key=lambda r: r.promoted_at or r.recorded_at
    ).model_version


def _registry(repo: MlopsRepository, now: datetime) -> Registry:
    rows: dict[str, list[ModelVersion]] = {}
    for row in repo.model_versions():
        rows.setdefault(row.model_version, []).append(row)
    running = frozenset(
        run.kind
        for run in repo.runs(now - max(MAX_AGE.values()))
        if run.status is RunStatus.RUNNING
        and run.kind in MAX_AGE
        and now - run.started_at < MAX_AGE[run.kind]
    )
    return Registry(
        policy=_current_policy(repo, now),
        rows=rows,
        checks={c.candidate_version: c for c in repo.promotion_checks()},
        retrain_notice=_retrain_notice(repo.quality(), _current_of(rows)),
        running=running,
        last_topic_fit=repo.last_topic_fit(),
    )


def _retrain_notice(rows: Sequence[ModelQuality], current: str | None) -> bool:
    """El κ del último periodo del modelo vigente está en ``retrain``."""
    kappa = [
        r
        for r in rows
        if r.signal is QualitySignal.KAPPA_MONITOR
        and (current is None or r.model_version == current)
    ]
    if not kappa:
        return False
    last = max(kappa, key=lambda r: (r.period, r.computed_at))
    return last.status is QualityStatus.RETRAIN


def _state(
    action: Action, reason: str | None, enabled: bool = False
) -> ActionState:
    return ActionState(action=action, enabled=enabled, reason=reason)


def retrain_state(reg: Registry) -> ActionState:
    policy = reg.policy
    if policy is None:
        return _state(Action.RETRAIN, "No hay una risk_policy vigente")
    if policy.retrain_mode == RetrainTrigger.AUTO:
        return _state(
            Action.RETRAIN,
            "El reentrenamiento es automático: lo lanza el monitor cuando "
            "el κ baja del piso",
        )
    if not reg.retrain_notice:
        return _state(Action.RETRAIN, "No hay aviso de reentrenamiento vigente")
    if RunKind.TRAINING in reg.running:
        return _state(Action.RETRAIN, "Hay un entrenamiento en curso")
    return _state(
        Action.RETRAIN,
        "Cuesta unos $1 de Gemini (tope $2) y el texto sale a Kaggle",
        enabled=True,
    )


def topics_refit_state(reg: Registry, now: datetime) -> ActionState:
    policy = reg.policy
    if policy is None:
        return _state(Action.TOPICS_REFIT, "No hay una risk_policy vigente")
    if policy.topic_refit_mode == TopicRefitTrigger.SCHEDULED:
        today = now.date()
        fitted = reg.last_topic_fit
        done = fitted is not None and fitted.date() >= _quarter_start(today)
        when = _next_quarter(today) if done else today
        return ActionState(
            action=Action.TOPICS_REFIT,
            enabled=False,
            reason=(
                f"Re-ajuste programado: próxima fecha {when:%Y-%m-%d}. Para "
                "lanzarlo a mano, cambia el modo en Administración"
            ),
            next_date=when,
        )
    if RunKind.TOPIC_REFIT in reg.running:
        return _state(Action.TOPICS_REFIT, "Hay un re-ajuste en curso")
    return _state(
        Action.TOPICS_REFIT,
        "Sin costo de Gemini; el texto no sale de GCP",
        enabled=True,
    )


def version_state(reg: Registry, action: Action, version: str) -> ActionState:
    latest = reg.latest(version)
    check = reg.checks.get(version)
    candidate = latest.status is ModelStatus.CANDIDATE
    if action is Action.RESCORE:
        if not candidate:
            return _state(action, "Solo se re-puntúan las candidatas")
        if check is not None:
            return _state(
                action, "Ya tiene su verificación de re-scoring en el registro"
            )
        if RunKind.RESCORING in reg.running:
            return _state(action, "Hay un re-scoring en curso")
        return _state(action, "El texto sale a Kaggle", enabled=True)
    if action is Action.PROMOTE:
        if not candidate:
            return _state(
                action,
                "Solo se promueven candidatas; para volver a una versión "
                "anterior usa rollback",
            )
        if check is None:
            return _state(action, "Falta el re-scoring de esta candidata")
        if check.current_version != reg.current:
            return _state(
                action,
                "La verificación se hizo contra otra versión vigente: "
                "vuelve a re-puntuar",
            )
        if check.verdict is PromotionVerdict.WORSE:
            return _state(
                action,
                f"El veredicto es peor: para promover hay que escribir "
                f"{FORCE_WORD}",
                enabled=True,
            )
        return _state(action, None, enabled=True)
    # rollback
    if version == reg.current:
        return _state(action, "Es la versión vigente")
    if not reg.ever_promoted(version):
        return _state(action, "Esta versión nunca estuvo promovida")
    return _state(action, None, enabled=True)


def _check_out(check: PromotionCheckResult | None) -> PromotionCheckOut | None:
    if check is None:
        return None
    return PromotionCheckOut.model_validate(check.model_dump())


def _step(row: ModelVersion) -> StatusStep:
    return StatusStep(
        status=row.status,
        at=row.recorded_at,
        actor=_short(row.promoted_by_hash),
        reason=row.reason,
    )


def models(repo: MlopsRepository, now: datetime) -> ModelsResponse:
    reg = _registry(repo, now)
    current = reg.current
    out = []
    for version, rows in reg.rows.items():
        latest = rows[-1]
        out.append(
            ModelOut(
                model_version=version,
                status=latest.status,
                current=version == current,
                ever_promoted=reg.ever_promoted(version),
                base_checkpoint=latest.base_checkpoint,
                training_data=latest.training_data,
                training_data_hash=latest.training_data_hash,
                calibration_version=latest.calibration_version,
                calibration_t=latest.calibration_t,
                kappa_dev=latest.kappa_dev,
                ece_dev=latest.ece_dev,
                aurc_dev=latest.aurc_dev,
                license=latest.license,
                history=[_step(r) for r in rows],
                check=_check_out(reg.checks.get(version)),
                actions=[
                    version_state(reg, action, version)
                    for action in VERSION_ACTIONS
                ],
            )
        )
    out.sort(
        key=lambda m: (not m.current, -m.history[-1].at.timestamp()),
    )
    return ModelsResponse(
        models=out,
        current_version=current,
        actions=[retrain_state(reg), topics_refit_state(reg, now)],
    )


# -- Corridas ----------------------------------------------------------------


def _run_out(run: InferenceRun) -> RunOut:
    duration = (
        None
        if run.ended_at is None
        else (run.ended_at - run.started_at).total_seconds()
    )
    return RunOut(
        run_id=run.run_id,
        kind=run.kind,
        environment=run.environment,
        status=run.status,
        started_at=run.started_at,
        ended_at=run.ended_at,
        duration_seconds=duration,
        reviews=run.reviews,
        texts=run.texts,
        cost_usd=run.cost_usd,
        peak_memory_mib=run.peak_memory_mib,
        model_version=run.model_version,
        topic_model_version=run.topic_model_version,
        actor=_short(run.actor_hash),
        reason=run.reason,
    )


def runs(
    repo: MlopsRepository, kind: RunKind | None, days: int, now: datetime
) -> RunsResponse:
    since = now - timedelta(days=days)
    rows = repo.runs(since, kind)
    delta = [
        r.started_at
        for r in repo.runs(since, RunKind.DELTA)
        if r.status is RunStatus.SUCCEEDED
    ]
    return RunsResponse(
        runs=[_run_out(r) for r in rows],
        freshness=Freshness(
            last_ingestion_at=repo.last_ingestion_at(),
            last_delta_at=max(delta, default=None),
            last_monitor_at=repo.last_monitor_at(),
        ),
    )


def ingestion(
    repo: MlopsRepository, days: int, now: datetime
) -> list[IngestionRunOut]:
    return [
        IngestionRunOut(
            run_id=r.run_id,
            bank_id=r.bank_id,
            mode=r.mode,
            started_at=r.started_at,
            ended_at=r.ended_at,
            duration_seconds=(r.ended_at - r.started_at).total_seconds(),
            status=r.status,
            reviews_extracted=r.reviews_extracted,
            reviews_published=r.reviews_published,
            reviews_discarded=r.reviews_discarded,
        )
        for r in repo.ingestion(now - timedelta(days=days))
    ]


def eligibility(repo: MlopsRepository) -> list[EligibilityRow]:
    return [
        EligibilityRow(
            bank_id=r.bank_id, period=_period(r.period), code=r.code, n=r.n
        )
        for r in repo.eligibility()
    ]


# -- Ejecución ---------------------------------------------------------------


def _arguments(
    action: Action,
    principal: Principal,
    body: ActionIn,
    version: str | None,
    force: bool,
) -> list[str]:
    who = [f"--actor-hash={principal.actor_hash}", f"--reason={body.reason}"]
    match action:
        case Action.RETRAIN:
            return ["train", *who]
        case Action.RESCORE:
            return ["rescore", f"--model-version={version}", *who]
        case Action.PROMOTE | Action.ROLLBACK:
            return [
                "promote",
                f"--model-version={version}",
                *who,
                *(["--force"] if force else []),
            ]
        case Action.TOPICS_REFIT:
            return ["topics-refit", "--force", *who]
    raise AssertionError(action)  # pragma: no cover


def execute(  # noqa: PLR0913
    repo: MlopsRepository,
    jobs: JobRunner,
    principal: Principal,
    action: Action,
    body: ActionIn,
    now: datetime,
) -> ActionOut:
    """Revisa que la acción esté habilitada y lanza su Job."""
    reg = _registry(repo, now)
    version: str | None = None
    if action in VERSION_ACTIONS:
        version = body.model_version
        if not version:
            raise ApiError(ErrorCode.INVALID, "Falta la versión del modelo")
        if version not in reg.rows:
            raise ApiError(ErrorCode.NOT_FOUND, f"No hay una versión {version}")
        state = version_state(reg, action, version)
    elif action is Action.RETRAIN:
        state = retrain_state(reg)
    else:
        state = topics_refit_state(reg, now)
    if not state.enabled:
        raise ApiError(ErrorCode.CONFLICT, state.reason or "No disponible")
    force = False
    if action is Action.PROMOTE and version is not None:
        check = reg.checks[version]
        if check.verdict is PromotionVerdict.WORSE:
            if body.confirm_word != FORCE_WORD:
                raise ApiError(
                    ErrorCode.INVALID,
                    f"El candidato es peor: escribe {FORCE_WORD} para forzar",
                )
            force = True
    job = JOB_BY_ACTION[action]
    try:
        operation = jobs.execute(
            job, _arguments(action, principal, body, version, force)
        )
    except (requests.RequestException, GoogleAuthError) as exc:
        raise ApiError(
            ErrorCode.UPSTREAM, f"No se pudo lanzar el Job {job}"
        ) from exc
    return ActionOut(action=action, job=job, operation=operation)
