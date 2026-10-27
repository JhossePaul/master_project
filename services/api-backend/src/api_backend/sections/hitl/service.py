"""Reglas de la cola de revisión: tomar, saltar, soltar y guardar."""

import uuid
from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from voc_common import (
    AspectFamily,
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
    AspectsReviewIn,
    GuidelineOut,
    HitlCase,
    HitlSummary,
    ReviewOut,
    SentimentProposal,
    SentimentReviewIn,
)

# Tareas con cola en esta versión del portal.
IMPLEMENTED_TASKS = (HitlTask.SENTIMENT, HitlTask.ASPECTS)
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


def _predicted_aspects(
    entry: QueueEntry,
) -> tuple[frozenset[str], bool, bool] | None:
    """Familias y marcas ``u`` y ``s`` que guardó Gemini; ``None`` si faltan."""
    predicted = entry.item.predicted or {}
    families = predicted.get("families")
    update = predicted.get("flag_update")
    security = predicted.get("flag_security")
    valid = {f.value for f in AspectFamily}
    if (
        not isinstance(families, list)
        or not set(families) <= valid
        or not isinstance(update, bool)
        or not isinstance(security, bool)
    ):
        return None
    return frozenset(families), update, security


def _has_prediction(entry: QueueEntry) -> bool:
    if entry.item.task is HitlTask.ASPECTS:
        return _predicted_aspects(entry) is not None
    return _predicted_label(entry) is not None


def _proposal(entry: QueueEntry) -> SentimentProposal | None:
    """La propuesta solo existe si el caso es asistido y no puede ir al oro.

    Las muestras de aspectos son siempre a ciegas: nunca hay propuesta.
    """
    item = entry.item
    if item.task is not HitlTask.SENTIMENT:
        return None
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
    if not _has_prediction(entry):
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
    repo: HitlRepository,
    principal: Principal,
    task: HitlTask,
    now: datetime,
    exclude: Collection[str] = (),
) -> HitlCase | None:
    ensure_task(principal, task)
    actor = principal.actor_hash
    guideline = current_guideline(repo, task, now)
    candidates = sorted(
        (
            e
            for e in repo.entries(task, now)
            if public_id(e.item.item_id) not in exclude
            and is_available(e, actor, now)
        ),
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
    for cached in candidates[:MAX_TRIES]:
        # La lista puede venir de la memoria: el estado de este caso, no.
        entry = repo.entry(public_id(cached.item.item_id), now)
        if entry is None or not is_available(entry, actor, now):
            continue
        item = entry.item
        text = repo.review_text(item.bank_id, item.id_resena)
        if text is None or not text_matches(item.item_id, text, item.task):
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
            task=item.task.value,  # type: ignore[arg-type]
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


def _open_for_save(  # noqa: PLR0913
    repo: HitlRepository,
    principal: Principal,
    item_id: str,
    task: HitlTask,
    review_id: str,
    guideline_version: str,
    claim_next: bool,
    now: datetime,
) -> tuple[QueueEntry | None, ReviewOut | None]:
    """El caso listo para guardar, o la respuesta de un reintento."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        guidelines = pool.submit(repo.guidelines, task)
        entry = _own_entry(repo, principal, item_id, now)
        known = guidelines.result()
    if entry.item.task is not task:
        raise ApiError(ErrorCode.INVALID, "El caso es de otra cola")
    if not _holds(entry, principal):
        if repo.has_review(review_id):  # reintento de un guardado exitoso
            return None, ReviewOut(
                review_id=review_id,
                next=_next_after(repo, principal, task, now, claim_next),
            )
        raise ApiError(ErrorCode.CONFLICT, CONFLICT_MESSAGE)
    if guideline_version not in {g.guideline_version for g in known}:
        raise ApiError(ErrorCode.INVALID, "La versión de la guía no existe")
    if entry.status_at is None:
        raise ApiError(ErrorCode.INTERNAL, "El caso no trae predicción")
    return entry, None


def _sanitized(sanitizer: CommentSanitizer, comment: str | None) -> str | None:
    text = (comment or "").strip()
    return sanitizer.sanitize(text) if text else None


def _commit(
    repo: HitlRepository,
    principal: Principal,
    entry: QueueEntry,
    review: HitlReview,
    claim_next: bool,
    now: datetime,
) -> ReviewOut:
    submitted = HitlEvent(
        # Id fijo: un reintento con el mismo ``review_id`` no duplica el evento.
        event_id=f"{review.review_id}:submitted",
        item_id=entry.item.item_id,
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
        review_id=review.review_id,
        next=_next_after(repo, principal, entry.item.task, now, claim_next),
    )


def _build_review(
    entry: QueueEntry,
    principal: Principal,
    now: datetime,
    review_id: str,
    guideline_version: str,
    comment: str | None,
    **decision: Any,
) -> HitlReview:
    item = entry.item
    assert entry.status_at is not None  # noqa: S101  # lo asegura _open_for_save
    try:
        return HitlReview(
            review_id=review_id,
            item_id=item.item_id,
            id_resena=item.id_resena,
            task=item.task,  # type: ignore[arg-type]
            display_mode=item.display_mode,
            review_round=min(len(entry.reviewers) + 1, 2),  # type: ignore[arg-type]
            guideline_version=guideline_version,
            model_version=item.model_version,
            risk_policy_version=item.risk_policy_version,
            reviewer_hash=principal.actor_hash,
            opened_at=entry.status_at,
            submitted_at=now,
            seconds_spent=max(0, int((now - entry.status_at).total_seconds())),
            comment=comment,
            **decision,
        )
    except ValidationError as exc:
        raise ApiError(ErrorCode.INVALID, "Revisión no válida") from exc


def save_review(  # noqa: PLR0913
    repo: HitlRepository,
    sanitizer: CommentSanitizer,
    principal: Principal,
    item_id: str,
    body: SentimentReviewIn,
    now: datetime,
) -> ReviewOut:
    review_id = str(body.review_id)
    entry, retry = _open_for_save(
        repo,
        principal,
        item_id,
        HitlTask.SENTIMENT,
        review_id,
        body.guideline_version,
        body.claim_next,
        now,
    )
    if entry is None:
        assert retry is not None  # noqa: S101
        return retry
    predicted = _predicted_label(entry)
    if predicted is None:
        raise ApiError(ErrorCode.INTERNAL, "El caso no trae predicción")
    review = _build_review(
        entry,
        principal,
        now,
        review_id,
        body.guideline_version,
        _sanitized(sanitizer, body.comment),
        predicted_label=predicted,
        validated_label=body.validated_label,
        outcome=(
            ReviewOutcome.CONFIRMED
            if body.validated_label == predicted
            else ReviewOutcome.CORRECTED
        ),
        flags=list(body.flags),
    )
    return _commit(repo, principal, entry, review, body.claim_next, now)


def save_aspects_review(  # noqa: PLR0913
    repo: HitlRepository,
    sanitizer: CommentSanitizer,
    principal: Principal,
    item_id: str,
    body: AspectsReviewIn,
    now: datetime,
) -> ReviewOut:
    review_id = str(body.review_id)
    entry, retry = _open_for_save(
        repo,
        principal,
        item_id,
        HitlTask.ASPECTS,
        review_id,
        body.guideline_version,
        body.claim_next,
        now,
    )
    if entry is None:
        assert retry is not None  # noqa: S101
        return retry
    predicted = _predicted_aspects(entry)
    if predicted is None:
        raise ApiError(ErrorCode.INTERNAL, "El caso no trae predicción")
    families, update, security = predicted
    same = (
        families == frozenset(body.families)
        and update == body.flag_update
        and security == body.flag_security
    )
    review = _build_review(
        entry,
        principal,
        now,
        review_id,
        body.guideline_version,
        _sanitized(sanitizer, body.comment),
        # Se guardan en el orden del contrato, no en el que llegaron.
        predicted_families=sorted(families),
        validated_families=sorted(body.families),
        predicted_flag_update=update,
        validated_flag_update=body.flag_update,
        predicted_flag_security=security,
        validated_flag_security=body.flag_security,
        outcome=ReviewOutcome.CONFIRMED if same else ReviewOutcome.CORRECTED,
    )
    return _commit(repo, principal, entry, review, body.claim_next, now)


def _next_after(
    repo: HitlRepository,
    principal: Principal,
    task: HitlTask,
    now: datetime,
    claim: bool,
) -> HitlCase | None:
    """El siguiente caso, si se pide y se puede; el guardado no se pierde."""
    if not claim:
        return None
    try:
        return take_next(repo, principal, task, now)
    except ApiError:
        log_event("WARNING", "no se pudo tomar el siguiente tras guardar")
        return None


def summary(
    repo: HitlRepository, principal: Principal, now: datetime
) -> HitlSummary:
    if Role.REVISOR not in principal.roles:
        raise ApiError(ErrorCode.FORBIDDEN, "No tienes permiso para esto")
    tasks = [t for t in IMPLEMENTED_TASKS if t in principal.reviewer_tasks]
    if len(tasks) < 2:  # noqa: PLR2004
        return HitlSummary(
            tasks=[repo.summary(t, principal.actor_hash, now) for t in tasks]
        )
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        return HitlSummary(
            tasks=list(
                pool.map(
                    lambda t: repo.summary(t, principal.actor_hash, now), tasks
                )
            )
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
