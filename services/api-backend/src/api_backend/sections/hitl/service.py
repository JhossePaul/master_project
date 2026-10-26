"""Reglas de la cola de revisión: tomar, saltar, soltar y guardar."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import ValidationError
from voc_common import (
    DisplayMode,
    Guideline,
    HitlEvent,
    HitlReason,
    HitlReview,
    HitlStatus,
    HitlTask,
    ReviewOutcome,
    log_event,
)
from voc_common.hitl_v3 import BLIND_REASONS

from api_backend.auth.deps import Principal
from api_backend.auth.roles import Role
from api_backend.dlp import CommentSanitizer
from api_backend.errors import ApiError, ErrorCode
from api_backend.sections.hitl.repository import (
    HitlRepository,
    QueueEntry,
    is_closed,
    public_id,
    text_matches,
)
from api_backend.sections.hitl.schemas import (
    GuidelineOut,
    HitlCase,
    HitlSummary,
    ReviewOut,
    SentimentProposal,
    SentimentReviewIn,
)

# Tareas con cola en esta versión del portal.
IMPLEMENTED_TASKS = (HitlTask.SENTIMENT,)
LOCK = timedelta(minutes=15)
MAX_TRIES = 25
# Textos que se traen de una vez: los del caso y los que siguen.
PREFETCH = 20
CONFLICT_MESSAGE = "El caso volvió a la cola; pide el siguiente"
PREDICTION_KEYS = ("label", "p_neg", "p_neu", "p_pos")


def ensure_task(principal: Principal, task: HitlTask) -> None:
    """403 si no es revisor de la tarea (el administrador solo si lo es)."""
    if (
        Role.REVISOR not in principal.roles
        or task not in principal.reviewer_tasks
        or task not in IMPLEMENTED_TASKS
    ):
        raise ApiError(ErrorCode.FORBIDDEN, "No tienes permiso para esta cola")


def _event(
    item_id: str, status: HitlStatus, actor: str | None, at: datetime
) -> HitlEvent:
    return HitlEvent(
        event_id=str(uuid.uuid4()),
        item_id=item_id,
        status=status,
        actor_hash=actor,
        at=at,
    )


def _predicted_label(entry: QueueEntry) -> str | None:
    predicted = entry.item.predicted or {}
    label = predicted.get("label")
    return label if label in ("NEG", "NEU", "POS") else None


def _proposal(entry: QueueEntry) -> SentimentProposal | None:
    """La propuesta solo existe si el caso es asistido y no puede ir al oro."""
    item = entry.item
    if item.display_mode is not DisplayMode.ASSISTED:
        return None
    if item.reason in BLIND_REASONS:
        return None
    predicted = item.predicted or {}
    return SentimentProposal.model_validate(
        {key: predicted.get(key) for key in PREDICTION_KEYS}
    )


def is_available(entry: QueueEntry, actor: str, now: datetime) -> bool:
    if is_closed(entry) or actor in entry.reviewers:
        return False
    if actor in entry.skipped_by:
        return False
    if _predicted_label(entry) is None:
        log_event("WARNING", "caso sin predicción", item=entry.item.item_id)
        return False
    locked = (
        entry.status is HitlStatus.IN_REVIEW
        and entry.status_at is not None
        and now - entry.status_at < LOCK
    )
    return not locked or entry.actor_hash == actor


def _own_open(entry: QueueEntry, actor: str, now: datetime) -> bool:
    return (
        entry.status is HitlStatus.IN_REVIEW
        and entry.actor_hash == actor
        and entry.status_at is not None
        and now - entry.status_at < LOCK
    )


def current_guideline(
    repo: HitlRepository, task: HitlTask, now: datetime
) -> Guideline:
    for guideline in repo.guidelines(task):  # la más reciente primero
        if guideline.valid_from <= now:
            return guideline
    raise ApiError(ErrorCode.NOT_FOUND, "No hay guía vigente para la tarea")


def take_next(
    repo: HitlRepository, principal: Principal, task: HitlTask, now: datetime
) -> HitlCase | None:
    ensure_task(principal, task)
    actor = principal.actor_hash
    guideline = current_guideline(repo, task, now)
    candidates = sorted(
        (e for e in repo.entries(task, now) if is_available(e, actor, now)),
        key=lambda e: (
            not _own_open(e, actor, now),  # primero el caso que ya tenía
            -e.item.priority,
            e.item.created_at,
            e.item.item_id,
        ),
    )
    repo.prefetch_texts(
        [(e.item.bank_id, e.item.id_resena) for e in candidates[:PREFETCH]]
    )
    for entry in candidates[:MAX_TRIES]:
        item = entry.item
        text = repo.review_text(item.bank_id, item.id_resena)
        if text is None or not text_matches(item.item_id, text):
            repo.add_event(_event(item.item_id, HitlStatus.EXPIRED, None, now))
            continue
        opened = entry.status_at if _own_open(entry, actor, now) else None
        if opened is None:
            repo.add_event(
                _event(item.item_id, HitlStatus.IN_REVIEW, actor, now)
            )
            mine = repo.entry(public_id(item.item_id), now)
            if (
                mine is None
                or mine.status is not HitlStatus.IN_REVIEW
                or mine.actor_hash != actor
                or mine.status_at is None
            ):
                continue  # otro revisor lo tomó al mismo tiempo
            if _already_reviewed(mine, actor):
                # La memoria iba atrasada: ya lo habían revisado. Se cierra de
                # nuevo para que el bloqueo vencido no lo devuelva a la cola.
                repo.add_event(
                    _event(item.item_id, HitlStatus.SUBMITTED, None, now)
                )
                continue
            opened = mine.status_at
        return HitlCase(
            item_id=public_id(item.item_id),
            task="sentiment",
            text=text,
            display_mode=item.display_mode.value,  # type: ignore[arg-type]
            proposal=_proposal(entry),
            guideline_version=guideline.guideline_version,
            opened_at=opened,
            review_round=min(len(entry.reviewers) + 1, 2),  # type: ignore[arg-type]
        )
    return None


def _already_reviewed(entry: QueueEntry, actor: str) -> bool:
    if entry.item.reason is HitlReason.AGREEMENT_SAMPLE:
        return actor in entry.reviewers or len(entry.reviewers) >= 2  # noqa: PLR2004
    return bool(entry.reviewers)


def _own_entry(
    repo: HitlRepository, principal: Principal, item_id: str, now: datetime
) -> QueueEntry:
    """El caso, si existe y el revisor puede trabajarlo."""
    entry = repo.entry(item_id, now)
    if entry is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No existe el caso")
    ensure_task(principal, entry.item.task)
    return entry


def _holds(entry: QueueEntry, principal: Principal) -> bool:
    return (
        entry.status is HitlStatus.IN_REVIEW
        and entry.actor_hash == principal.actor_hash
    )


def skip(
    repo: HitlRepository, principal: Principal, item_id: str, now: datetime
) -> None:
    entry = _own_entry(repo, principal, item_id, now)
    if not _holds(entry, principal):
        raise ApiError(ErrorCode.CONFLICT, CONFLICT_MESSAGE)
    repo.add_event(
        _event(
            entry.item.item_id, HitlStatus.SKIPPED, principal.actor_hash, now
        )
    )


def release(
    repo: HitlRepository, principal: Principal, item_id: str, now: datetime
) -> None:
    """Devuelve el caso a la cola; si ya no es del revisor, no hace nada."""
    entry = _own_entry(repo, principal, item_id, now)
    if _holds(entry, principal):
        repo.add_event(_event(entry.item.item_id, HitlStatus.QUEUED, None, now))


def save_review(  # noqa: PLR0913
    repo: HitlRepository,
    sanitizer: CommentSanitizer,
    principal: Principal,
    item_id: str,
    body: SentimentReviewIn,
    now: datetime,
) -> ReviewOut:
    with ThreadPoolExecutor(max_workers=2) as pool:
        guidelines = pool.submit(repo.guidelines, HitlTask.SENTIMENT)
        entry = _own_entry(repo, principal, item_id, now)
        known = guidelines.result()
    review_id = str(body.review_id)
    if not _holds(entry, principal):
        if repo.has_review(review_id):  # reintento de un guardado exitoso
            return ReviewOut(
                review_id=review_id, next=_next_after(repo, principal, now)
            )
        raise ApiError(ErrorCode.CONFLICT, CONFLICT_MESSAGE)
    item = entry.item
    task = item.task
    versions = {g.guideline_version for g in known}
    if body.guideline_version not in versions:
        raise ApiError(ErrorCode.INVALID, "La versión de la guía no existe")
    predicted = _predicted_label(entry)
    if predicted is None or entry.status_at is None:
        raise ApiError(ErrorCode.INTERNAL, "El caso no trae predicción")
    comment = (body.comment or "").strip()
    sanitized = sanitizer.sanitize(comment) if comment else None
    try:
        review = HitlReview(
            review_id=review_id,
            item_id=item.item_id,
            id_resena=item.id_resena,
            task=task,  # type: ignore[arg-type]
            predicted_label=predicted,  # type: ignore[arg-type]
            validated_label=body.validated_label,  # type: ignore[arg-type]
            outcome=(
                ReviewOutcome.CONFIRMED
                if body.validated_label == predicted
                else ReviewOutcome.CORRECTED
            ),
            display_mode=item.display_mode,
            review_round=min(len(entry.reviewers) + 1, 2),  # type: ignore[arg-type]
            flags=list(body.flags),
            guideline_version=body.guideline_version,
            model_version=item.model_version,
            risk_policy_version=item.risk_policy_version,
            reviewer_hash=principal.actor_hash,
            opened_at=entry.status_at,
            submitted_at=now,
            seconds_spent=max(0, int((now - entry.status_at).total_seconds())),
            comment=sanitized,
        )
    except ValidationError as exc:
        raise ApiError(ErrorCode.INVALID, "Revisión no válida") from exc
    submitted = HitlEvent(
        # Id fijo: un reintento con el mismo ``review_id`` no duplica el evento.
        event_id=f"{review_id}:submitted",
        item_id=item.item_id,
        status=HitlStatus.SUBMITTED,
        actor_hash=principal.actor_hash,
        at=now,
    )
    # Independientes y con clave propia: si una falla, el reintento completa.
    with ThreadPoolExecutor(max_workers=2) as pool:
        written = [
            pool.submit(repo.add_review, review),
            pool.submit(repo.add_event, submitted),
        ]
        for future in written:
            future.result()
    return ReviewOut(
        review_id=review_id, next=_next_after(repo, principal, now)
    )


def _next_after(
    repo: HitlRepository, principal: Principal, now: datetime
) -> HitlCase | None:
    """El siguiente caso, si se puede; el guardado ya ocurrió y no se pierde."""
    try:
        return take_next(repo, principal, HitlTask.SENTIMENT, now)
    except ApiError:
        log_event("WARNING", "no se pudo tomar el siguiente tras guardar")
        return None


def summary(
    repo: HitlRepository, principal: Principal, now: datetime
) -> HitlSummary:
    if Role.REVISOR not in principal.roles:
        raise ApiError(ErrorCode.FORBIDDEN, "No tienes permiso para esto")
    tasks = [t for t in IMPLEMENTED_TASKS if t in principal.reviewer_tasks]
    return HitlSummary(
        tasks=[repo.summary(t, principal.actor_hash, now) for t in tasks]
    )


def read_guideline(
    repo: HitlRepository,
    principal: Principal,
    task: HitlTask,
    base: Path,
    now: datetime,
) -> GuidelineOut:
    ensure_task(principal, task)
    guideline = current_guideline(repo, task, now)
    root = base.resolve()
    path = (root / guideline.content_uri).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No se encontró la guía {guideline.content_uri}",
        )
    return GuidelineOut(
        task=task,
        guideline_version=guideline.guideline_version,
        valid_from=guideline.valid_from,
        content=path.read_text(encoding="utf-8"),
    )
