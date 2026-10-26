"""Lecturas y escrituras del HITL: ``Protocol``, BigQuery y memoria."""

# ruff: noqa: S608
# Los nombres de tablas salen de ``qualified`` (lista cerrada); los valores
# viajan siempre como parámetros.

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Protocol

from voc_common import (
    DisplayMode,
    Guideline,
    HitlEvent,
    HitlItem,
    HitlReason,
    HitlReview,
    HitlStatus,
    HitlTask,
)
from voc_common.text_utils import text_key

from api_backend.bq.names import qualified
from api_backend.bq.reader import BigQueryReader, Param
from api_backend.bq.writer import BigQueryWriter
from api_backend.sections.hitl.schemas import TaskSummary
from api_backend.settings import ApiSettings

SKIP_DAYS = 7
MEDIAN_DAYS = 30
# Un trimestre de muestra de monitoreo cabe en esta ventana de creación.
MONITOR_WINDOW_DAYS = 200
QUEUE_LIMIT = 500
PUBLIC_ID_LENGTH = 32
# Memoria del proceso: una revisión dura más de 15 s, así que la cola debe
# sobrevivir entre dos peticiones del mismo revisor. Los textos del TDS casi
# no cambian (la edición se detecta al tomar un caso).
QUEUE_CACHE_SECONDS = 300.0
TEXT_CACHE_SECONDS = 900.0


@dataclass(frozen=True)
class QueueEntry:
    """Un caso con su último estado. Interno: nunca se serializa tal cual."""

    item: HitlItem
    status: HitlStatus | None  # ``None``: aún sin eventos
    actor_hash: str | None
    status_at: datetime | None
    skipped_by: frozenset[str]  # quienes lo saltaron en los últimos 7 días
    reviewers: tuple[str, ...]  # ``reviewer_hash`` por ronda


class HitlRepository(Protocol):
    def entries(self, task: HitlTask, now: datetime) -> list[QueueEntry]:
        """Casos abiertos de la tarea (sin los expirados ni los cerrados)."""

    def entry(self, ref: str, now: datetime) -> QueueEntry | None:
        """El caso cuyo ``public_id`` es ``ref``."""

    def review_text(self, bank_id: str, id_resena: str) -> str | None: ...

    def review_texts(
        self, pairs: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], str]:
        """Los textos que existan, en una sola consulta."""

    def prefetch_texts(self, pairs: Sequence[tuple[str, str]]) -> None:
        """Trae de una vez los textos de los casos que siguen."""

    def guidelines(self, task: HitlTask) -> list[Guideline]: ...

    def add_event(self, event: HitlEvent) -> None: ...

    def add_review(self, review: HitlReview) -> bool: ...

    def has_review(self, review_id: str) -> bool: ...

    def summary(
        self, task: HitlTask, actor_hash: str, now: datetime
    ) -> TaskSummary: ...


def public_id(item_id: str) -> str:
    """Identificador que ve el portal.

    El ``item_id`` real empieza por el motivo del caso (``monitor_sample:…``),
    y el revisor no debe poder distinguir la muestra de un caso de baja
    confianza; el portal solo conoce este resumen.
    """
    return hashlib.sha256(item_id.encode("utf-8")).hexdigest()[
        :PUBLIC_ID_LENGTH
    ]


def text_matches(item_id: str, text: str) -> bool:
    """``item_id`` lleva los 16 primeros caracteres del ``text_key``."""
    parts = item_id.split(":")
    return len(parts) >= 2 and text_key(text).startswith(parts[-2])


def week_start(now: datetime) -> datetime:
    """Lunes 00:00 UTC de la semana de ``now``."""
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


class BigQueryHitlRepository:
    def __init__(
        self,
        reader: BigQueryReader,
        writer: BigQueryWriter,
        settings: ApiSettings,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._project = settings.gcp_project_id
        self._dataset = settings.bq_dataset_id

    def _table(self, name: str) -> str:
        return qualified(name, self._project, self._dataset)

    def _entries_sql(self, where: str) -> str:
        # ``WHERE TRUE``: las tablas de eventos y revisiones exigen filtro de
        # partición, y el de los casos cerrados no es una fecha.
        return (
            "WITH skips AS ("  # nosec B608
            "SELECT item_id, ARRAY_AGG(DISTINCT actor_hash IGNORE NULLS) "
            "AS skipped_by "
            f"FROM {self._table('hitl_events')} "
            "WHERE TRUE AND status = 'skipped' "
            "AND `at` >= TIMESTAMP_SUB(@now, INTERVAL @skip_days DAY) "
            "GROUP BY item_id), "
            "revs AS (SELECT item_id, "
            "ARRAY_AGG(reviewer_hash ORDER BY review_round) AS reviewers "
            f"FROM {self._table('hitl_reviews')} "
            "WHERE TRUE GROUP BY item_id) "
            "SELECT q.item_id, q.id_resena, q.bank_id, q.task, q.reason, "
            "q.boost_id, q.display_mode, q.model_version, "
            "q.risk_policy_version, TO_JSON_STRING(q.predicted) AS predicted, "
            "q.priority, q.created_at, q.status, q.actor_hash, q.status_at, "
            "COALESCE(s.skipped_by, []) AS skipped_by, "
            "COALESCE(r.reviewers, []) AS reviewers "
            f"FROM {self._table('hitl_queue')} AS q "
            "LEFT JOIN skips AS s USING (item_id) "
            "LEFT JOIN revs AS r USING (item_id) "
            f"WHERE {where}"
        )

    def _params(self, now: datetime, *extra: Param) -> list[Param]:
        return [
            Param("now", "TIMESTAMP", now),
            Param("skip_days", "INT64", SKIP_DAYS),
            *extra,
        ]

    def entries(self, task: HitlTask, now: datetime) -> list[QueueEntry]:
        sql = (
            self._entries_sql(
                "q.task = @task AND COALESCE(q.status, 'queued') != 'expired' "
                "AND (COALESCE(q.status, 'queued') != 'submitted' "
                "OR q.reason = 'agreement_sample') "
                "AND NOT (q.reason = 'agreement_sample' "
                "AND ARRAY_LENGTH(r.reviewers) >= 2)"
            )
            + f" ORDER BY q.priority DESC, q.created_at LIMIT {QUEUE_LIMIT}"
        )
        rows = self._reader.rows(
            sql,
            self._params(now, Param("task", "STRING", task.value)),
            name="hitl_entries",
        )
        return [_entry(row) for row in rows]

    def entry(self, ref: str, now: datetime) -> QueueEntry | None:
        rows = self._reader.rows(
            self._entries_sql(
                f"LEFT(TO_HEX(SHA256(q.item_id)), {PUBLIC_ID_LENGTH}) = @ref"
            ),
            self._params(now, Param("ref", "STRING", ref)),
            name="hitl_entry",
        )
        return _entry(rows[0]) if rows else None

    def review_text(self, bank_id: str, id_resena: str) -> str | None:
        sql = (
            "SELECT texto_sanitizado FROM "  # nosec B608
            f"{self._table('sanitized_reviews_tds')} "
            "WHERE bank_id = @bank AND id_resena = @id LIMIT 1"
        )
        rows = self._reader.rows(
            sql,
            [
                Param("bank", "STRING", bank_id),
                Param("id", "STRING", id_resena),
            ],
            name="hitl_text",
        )
        return str(rows[0]["texto_sanitizado"]) if rows else None

    def review_texts(
        self, pairs: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], str]:
        if not pairs:
            return {}
        # Banco e id filtran por separado para aprovechar la agrupación de la
        # tabla; la pareja exacta se escoge después (el producto cruzado trae
        # a lo sumo unas filas de más).
        sql = (
            "SELECT bank_id, id_resena, texto_sanitizado FROM "  # nosec B608
            f"{self._table('sanitized_reviews_tds')} "
            "WHERE bank_id IN UNNEST(@banks) "
            "AND id_resena IN UNNEST(@ids)"
        )
        rows = self._reader.rows(
            sql,
            [
                Param(
                    "banks",
                    "STRING",
                    sorted({bank for bank, _ in pairs}),
                    array=True,
                ),
                Param(
                    "ids",
                    "STRING",
                    sorted({id_ for _, id_ in pairs}),
                    array=True,
                ),
            ],
            name="hitl_texts",
        )
        wanted = set(pairs)
        found = {
            (str(r["bank_id"]), str(r["id_resena"])): str(r["texto_sanitizado"])
            for r in rows
        }
        return {pair: text for pair, text in found.items() if pair in wanted}

    def prefetch_texts(self, pairs: Sequence[tuple[str, str]]) -> None:
        """Sin memoria no hay nada que precargar."""

    def guidelines(self, task: HitlTask) -> list[Guideline]:
        sql = (
            "SELECT guideline_version, task, content_uri, valid_from, "  # nosec B608
            f"published_by_hash FROM {self._table('guidelines')} "
            "WHERE task = @task ORDER BY valid_from DESC"
        )
        rows = self._reader.rows(
            sql, [Param("task", "STRING", task.value)], name="hitl_guidelines"
        )
        return [Guideline.model_validate(row) for row in rows]

    def add_event(self, event: HitlEvent) -> None:
        self._writer.insert("hitl_events", event, key=["event_id"])

    def add_review(self, review: HitlReview) -> bool:
        return self._writer.insert("hitl_reviews", review, key=["review_id"])

    def has_review(self, review_id: str) -> bool:
        sql = (
            "SELECT 1 AS v FROM "  # nosec B608
            f"{self._table('hitl_reviews')} "
            "WHERE TRUE AND review_id = @id LIMIT 1"
        )
        return bool(
            self._reader.rows(
                sql, [Param("id", "STRING", review_id)], name="hitl_has_review"
            )
        )

    def summary(
        self, task: HitlTask, actor_hash: str, now: datetime
    ) -> TaskSummary:
        pending = self._reader.rows(
            "SELECT COUNT(*) AS n FROM "  # nosec B608
            f"{self._table('hitl_queue')} AS q "
            "LEFT JOIN (SELECT item_id, COUNT(*) AS n FROM "
            f"{self._table('hitl_reviews')} WHERE TRUE GROUP BY item_id) "
            "AS r USING (item_id) "
            "WHERE q.task = @task "
            "AND COALESCE(q.status, 'queued') != 'expired' "
            "AND (COALESCE(q.status, 'queued') != 'submitted' "
            "OR (q.reason = 'agreement_sample' AND COALESCE(r.n, 0) < 2))",
            [Param("task", "STRING", task.value)],
            name="hitl_pending",
        )
        week = self._reader.rows(
            "SELECT COUNTIF(reviewer_hash = @actor) AS mine, "  # nosec B608
            "COUNT(*) AS team FROM "
            f"{self._table('hitl_reviews')} "
            "WHERE task = @task AND submitted_at >= @since",
            [
                Param("task", "STRING", task.value),
                Param("actor", "STRING", actor_hash),
                Param("since", "TIMESTAMP", week_start(now)),
            ],
            name="hitl_week",
        )
        median = self._reader.rows(
            "SELECT APPROX_QUANTILES(seconds_spent, 2)[OFFSET(1)] AS m FROM "  # nosec B608
            f"{self._table('hitl_reviews')} "
            "WHERE task = @task AND submitted_at >= @since",
            [
                Param("task", "STRING", task.value),
                Param("since", "TIMESTAMP", now - timedelta(days=MEDIAN_DAYS)),
            ],
            name="hitl_median",
        )
        monitor = self._reader.rows(
            "WITH s AS (SELECT item_id, SPLIT(item_id, ':')[SAFE_OFFSET(1)] "  # nosec B608
            f"AS quarter FROM {self._table('hitl_items')} "
            "WHERE task = @task AND reason = 'monitor_sample' "
            "AND created_at >= @items_since), "
            "last AS (SELECT MAX(quarter) AS quarter FROM s), "
            "done AS (SELECT DISTINCT item_id FROM "
            f"{self._table('hitl_reviews')} "
            "WHERE task = @task AND review_round = 1 "
            "AND submitted_at >= @items_since) "
            "SELECT COUNT(*) AS target, "
            "COUNTIF(d.item_id IS NOT NULL) AS done "
            "FROM s JOIN last USING (quarter) "
            "LEFT JOIN done AS d USING (item_id)",
            [
                Param("task", "STRING", task.value),
                Param(
                    "items_since",
                    "TIMESTAMP",
                    now - timedelta(days=MONITOR_WINDOW_DAYS),
                ),
            ],
            name="hitl_monitor_progress",
        )
        return TaskSummary(
            task=task,
            pending=int(pending[0]["n"]),  # type: ignore[call-overload]
            mine_this_week=int(week[0]["mine"] or 0),  # type: ignore[call-overload]
            team_this_week=int(week[0]["team"] or 0),  # type: ignore[call-overload]
            median_seconds=_float(median[0]["m"]) if median else None,
            monitor_done=int(monitor[0]["done"] or 0),  # type: ignore[call-overload]
            monitor_target=int(monitor[0]["target"] or 0),  # type: ignore[call-overload]
        )


def _float(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def _entry(row: Mapping[str, Any]) -> QueueEntry:
    predicted = row.get("predicted")
    item = HitlItem(
        item_id=row["item_id"],
        id_resena=row["id_resena"],
        bank_id=row["bank_id"],
        task=HitlTask(row["task"]),
        reason=HitlReason(row["reason"]),
        boost_id=row.get("boost_id"),
        display_mode=DisplayMode(row["display_mode"]),
        model_version=row.get("model_version"),
        risk_policy_version=row.get("risk_policy_version"),
        predicted=json.loads(predicted) if predicted else None,
        priority=row["priority"],
        created_at=row["created_at"],
    )
    status = row.get("status")
    return QueueEntry(
        item=item,
        status=HitlStatus(status) if status else None,
        actor_hash=row.get("actor_hash"),
        status_at=row.get("status_at"),
        skipped_by=frozenset(row.get("skipped_by") or ()),
        reviewers=tuple(row.get("reviewers") or ()),
    )


class InMemoryHitlRepository:
    """Doble de pruebas y de ``PORTAL_DATA=fixtures``; sigue la misma lógica."""

    def __init__(
        self,
        items: list[HitlItem] | None = None,
        texts: dict[tuple[str, str], str] | None = None,
        guidelines: list[Guideline] | None = None,
    ) -> None:
        self.items: list[HitlItem] = list(items or [])
        self.texts = dict(texts or {})
        self._guidelines = list(guidelines or [])
        self.events: list[HitlEvent] = []
        self.reviews: list[HitlReview] = []

    def _entry(self, item: HitlItem, now: datetime) -> QueueEntry:
        events = sorted(
            (e for e in self.events if e.item_id == item.item_id),
            key=lambda e: e.at,
        )
        last = events[-1] if events else None
        since = now - timedelta(days=SKIP_DAYS)
        reviews = sorted(
            (r for r in self.reviews if r.item_id == item.item_id),
            key=lambda r: r.review_round,
        )
        return QueueEntry(
            item=item,
            status=last.status if last else None,
            actor_hash=last.actor_hash if last else None,
            status_at=last.at if last else None,
            skipped_by=frozenset(
                e.actor_hash
                for e in events
                if e.status is HitlStatus.SKIPPED
                and e.at >= since
                and e.actor_hash
            ),
            reviewers=tuple(r.reviewer_hash for r in reviews),
        )

    def entries(self, task: HitlTask, now: datetime) -> list[QueueEntry]:
        found = [
            e
            for e in (self._entry(i, now) for i in self.items if i.task is task)
            if not is_closed(e)
        ]
        found.sort(key=lambda e: (-e.item.priority, e.item.created_at))
        return found[:QUEUE_LIMIT]

    def entry(self, ref: str, now: datetime) -> QueueEntry | None:
        item = next(
            (i for i in self.items if public_id(i.item_id) == ref), None
        )
        return self._entry(item, now) if item else None

    def review_text(self, bank_id: str, id_resena: str) -> str | None:
        return self.texts.get((bank_id, id_resena))

    def review_texts(
        self, pairs: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], str]:
        return {p: self.texts[p] for p in pairs if p in self.texts}

    def prefetch_texts(self, pairs: Sequence[tuple[str, str]]) -> None:
        """Todo está en memoria."""

    def guidelines(self, task: HitlTask) -> list[Guideline]:
        return sorted(
            (g for g in self._guidelines if g.task is task),
            key=lambda g: g.valid_from,
            reverse=True,
        )

    def add_event(self, event: HitlEvent) -> None:
        if all(e.event_id != event.event_id for e in self.events):
            self.events.append(event)

    def add_review(self, review: HitlReview) -> bool:
        if self.has_review(review.review_id):
            return False
        self.reviews.append(review)
        return True

    def has_review(self, review_id: str) -> bool:
        return any(r.review_id == review_id for r in self.reviews)

    def summary(
        self, task: HitlTask, actor_hash: str, now: datetime
    ) -> TaskSummary:
        since = week_start(now)
        week = [
            r
            for r in self.reviews
            if r.task is task and r.submitted_at >= since
        ]
        recent = sorted(
            r.seconds_spent
            for r in self.reviews
            if r.task is task
            and r.submitted_at >= now - timedelta(days=MEDIAN_DAYS)
        )
        samples = [
            i
            for i in self.items
            if i.task is task and i.reason is HitlReason.MONITOR_SAMPLE
        ]
        quarter = max((_quarter(i.item_id) for i in samples), default=None)
        latest = [i for i in samples if _quarter(i.item_id) == quarter]
        done = {
            r.item_id
            for r in self.reviews
            if r.review_round == 1 and r.task is task
        }
        return TaskSummary(
            task=task,
            pending=len(self.entries(task, now)),
            mine_this_week=sum(r.reviewer_hash == actor_hash for r in week),
            team_this_week=len(week),
            median_seconds=float(recent[len(recent) // 2]) if recent else None,
            monitor_done=sum(i.item_id in done for i in latest),
            monitor_target=len(latest),
        )


class CachedHitlRepository:
    """Memoria del proceso delante del repositorio de BigQuery.

    Guarda la cola de cada tarea unos segundos y los textos del TDS unos
    minutos, y mantiene la cola al día con lo que este proceso escribe. Lo que
    otras instancias escriban se ve al vencer el tiempo; el estado de un caso
    que se va a tomar o a guardar se relee sin memoria (``entry``).
    """

    def __init__(
        self,
        inner: HitlRepository,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._clock = clock
        self._queues: dict[HitlTask, tuple[float, list[QueueEntry]]] = {}
        self._texts: dict[tuple[str, str], tuple[float, str | None]] = {}

    def entries(self, task: HitlTask, now: datetime) -> list[QueueEntry]:
        cached = self._queues.get(task)
        if cached and self._clock() - cached[0] < QUEUE_CACHE_SECONDS:
            return list(cached[1])
        found = self._inner.entries(task, now)
        self._queues[task] = (self._clock(), found)
        return list(found)

    def entry(self, ref: str, now: datetime) -> QueueEntry | None:
        """Siempre fresco; de paso corrige la cola guardada."""
        fresh = self._inner.entry(ref, now)
        if fresh is not None:
            for task, (loaded, entries) in list(self._queues.items()):
                self._queues[task] = (
                    loaded,
                    [
                        fresh
                        for e in entries
                        if e.item.item_id == fresh.item.item_id
                        and not is_closed(fresh)
                    ]
                    + [
                        e
                        for e in entries
                        if e.item.item_id != fresh.item.item_id
                    ],
                )
        return fresh

    def _text(self, key: tuple[str, str]) -> tuple[bool, str | None]:
        hit = self._texts.get(key)
        if hit and self._clock() - hit[0] < TEXT_CACHE_SECONDS:
            return True, hit[1]
        return False, None

    def review_text(self, bank_id: str, id_resena: str) -> str | None:
        key = (bank_id, id_resena)
        found, text = self._text(key)
        if found:
            return text
        text = self._inner.review_text(bank_id, id_resena)
        self._texts[key] = (self._clock(), text)
        return text

    def review_texts(
        self, pairs: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], str]:
        return self._inner.review_texts(pairs)

    def prefetch_texts(self, pairs: Sequence[tuple[str, str]]) -> None:
        missing = [p for p in pairs if not self._text(p)[0]]
        if not missing:
            return
        found = self._inner.review_texts(missing)
        now = self._clock()
        for pair in missing:
            self._texts[pair] = (now, found.get(pair))

    def guidelines(self, task: HitlTask) -> list[Guideline]:
        return self._inner.guidelines(task)

    def has_review(self, review_id: str) -> bool:
        return self._inner.has_review(review_id)

    def summary(
        self, task: HitlTask, actor_hash: str, now: datetime
    ) -> TaskSummary:
        return self._inner.summary(task, actor_hash, now)

    def add_event(self, event: HitlEvent) -> None:
        self._inner.add_event(event)
        for task, (loaded, entries) in list(self._queues.items()):
            self._queues[task] = (
                loaded,
                [
                    patched
                    for e in entries
                    if (patched := _after_event(e, event)) is not None
                ],
            )

    def add_review(self, review: HitlReview) -> bool:
        added = self._inner.add_review(review)
        if added:
            for task, (loaded, entries) in list(self._queues.items()):
                self._queues[task] = (
                    loaded,
                    [
                        replace(
                            e, reviewers=(*e.reviewers, review.reviewer_hash)
                        )
                        if e.item.item_id == review.item_id
                        else e
                        for e in entries
                    ],
                )
        return added


def _after_event(entry: QueueEntry, event: HitlEvent) -> QueueEntry | None:
    """La entrada de la cola tras un evento; ``None`` si el caso ya se cerró."""
    if entry.item.item_id != event.item_id:
        return entry
    if event.status is HitlStatus.EXPIRED:
        return None
    skipped = entry.skipped_by
    if event.status is HitlStatus.SKIPPED and event.actor_hash:
        skipped = skipped | {event.actor_hash}
    updated = replace(
        entry,
        status=event.status,
        actor_hash=event.actor_hash,
        status_at=event.at,
        skipped_by=skipped,
    )
    return None if is_closed(updated) else updated


def _quarter(item_id: str) -> str:
    parts = item_id.split(":")
    return parts[1] if len(parts) > 1 else ""


def is_closed(entry: QueueEntry) -> bool:
    """Expirado, o ya revisado (dos veces en la doble revisión)."""
    if entry.status is HitlStatus.EXPIRED:
        return True
    if entry.item.reason is HitlReason.AGREEMENT_SAMPLE:
        return len(entry.reviewers) >= 2  # noqa: PLR2004
    return entry.status is HitlStatus.SUBMITTED


__all__ = [
    "BigQueryHitlRepository",
    "CachedHitlRepository",
    "HitlRepository",
    "InMemoryHitlRepository",
    "QueueEntry",
    "public_id",
    "is_closed",
    "text_matches",
]
