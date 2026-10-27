"""Muestras de aspectos: el administrador crea los casos de la cola de aspectos.

Ningún Job crea casos ``task = aspects``. Cada muestra es un lote de reseñas
negativas de dos palabras o más con fila en ``review_aspects``, al azar y con
cuota igual por banco. Los casos son siempre a ciegas: lo que codificó Gemini
va en ``predicted`` solo para comparar en el servidor.
"""

# ruff: noqa: S608
# Los nombres de tablas salen de ``qualified`` (lista cerrada); los valores
# viajan siempre como parámetros.

import hashlib
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, Field
from voc_common import (
    DisplayMode,
    HitlEvent,
    HitlItem,
    HitlReason,
    HitlStatus,
    HitlTask,
    log_event,
)

from api_backend.auth.deps import Principal
from api_backend.bq.names import qualified
from api_backend.bq.reader import BigQueryReader, Param
from api_backend.bq.writer import BigQueryWriter
from api_backend.errors import ApiError, ErrorCode
from api_backend.settings import ApiSettings

MIN_REASON = 10
SAMPLE_PRIORITY = 1.0
DAYS_PER_MONTH = 30
LOTS_LIMIT = 50


class AspectsSampleIn(BaseModel):
    size: int = Field(default=50, ge=1, le=300)
    months: int = Field(default=3, ge=1, le=12)
    reason: str = Field(min_length=MIN_REASON, max_length=300)


class SampleBatchOut(BaseModel):
    batch: str
    task: HitlTask
    created_at: datetime
    size: int
    reviewed: int


class SampleCreatedOut(BaseModel):
    batch: str
    created: int
    per_bank: dict[str, int]


class SamplesResponse(BaseModel):
    batches: list[SampleBatchOut]


@dataclass(frozen=True)
class AspectCandidate:
    id_resena: str
    bank_id: str
    text_key: str
    predicted: dict[str, Any]


class SamplesRepository(Protocol):
    def candidates(
        self, since: datetime, size: int, seed: str
    ) -> list[AspectCandidate]:
        """Negativas con aspectos y sin caso previo, al azar por banco."""

    def add(
        self, items: Sequence[HitlItem], events: Sequence[HitlEvent]
    ) -> None: ...

    def batches(self) -> list[SampleBatchOut]: ...


def rank_key(seed: str, candidate: AspectCandidate) -> str:
    return hashlib.sha256(f"{seed}:{candidate.id_resena}".encode()).hexdigest()


def draw(
    candidates: Sequence[AspectCandidate], size: int, seed: str
) -> list[AspectCandidate]:
    """``size`` casos con cuota igual por banco (los que alcance cada banco)."""
    by_bank: dict[str, list[AspectCandidate]] = defaultdict(list)
    for candidate in sorted(candidates, key=lambda c: rank_key(seed, c)):
        by_bank[candidate.bank_id].append(candidate)
    chosen: list[AspectCandidate] = []
    depth = 0
    # Una vuelta por banco, de la más aleatoria a la menos: reparte parejo y,
    # si un banco se queda corto, el resto completa con los demás.
    while len(chosen) < size and any(len(v) > depth for v in by_bank.values()):
        for bank in sorted(by_bank):
            if depth < len(by_bank[bank]) and len(chosen) < size:
                chosen.append(by_bank[bank][depth])
        depth += 1
    return chosen


def create_aspects_sample(
    repo: SamplesRepository,
    principal: Principal,
    body: AspectsSampleIn,
    now: datetime,
) -> SampleCreatedOut:
    batch = uuid.uuid4().hex[:8]
    since = now - timedelta(days=DAYS_PER_MONTH * body.months)
    # Los bancos con muchas reseñas no sesgan el sorteo: el lote es la semilla.
    chosen = draw(repo.candidates(since, body.size, batch), body.size, batch)
    if not chosen:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "No hay reseñas negativas con aspectos en la ventana",
        )
    items = [
        HitlItem(
            item_id=(f"aspects:manual:{batch}:{c.id_resena}:{c.text_key[:16]}"),
            id_resena=c.id_resena,
            bank_id=c.bank_id,
            task=HitlTask.ASPECTS,
            reason=HitlReason.MANUAL,
            display_mode=DisplayMode.BLIND,
            predicted=c.predicted,
            priority=SAMPLE_PRIORITY,
            created_at=now,
        )
        for c in chosen
    ]
    events = [
        HitlEvent(
            event_id=f"{item.item_id}:queued",
            item_id=item.item_id,
            status=HitlStatus.QUEUED,
            actor_hash=None,
            at=now,
        )
        for item in items
    ]
    repo.add(items, events)
    per_bank: dict[str, int] = defaultdict(int)
    for c in chosen:
        per_bank[c.bank_id] += 1
    log_event(
        "INFO",
        "muestra de aspectos creada",
        batch=batch,
        size=len(items),
        actor=principal.actor_hash,
        reason=body.reason.strip(),
    )
    return SampleCreatedOut(
        batch=batch, created=len(items), per_bank=dict(sorted(per_bank.items()))
    )


class BigQuerySamplesRepository:
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

    def candidates(
        self, since: datetime, size: int, seed: str
    ) -> list[AspectCandidate]:
        # Cada banco aporta a lo sumo ``size`` filas, ordenadas al azar por la
        # semilla; la cuota igual la reparte ``draw``. A la API solo llegan
        # identificadores y las marcas de Gemini, sin texto.
        sql = (
            "WITH neg AS (SELECT id_resena, bank_id FROM "  # nosec B608
            f"{self._table('review_predictions_current')} "
            "WHERE sentiment = 'NEG' AND palabras >= 2 AND fecha >= @since), "
            "latest AS (SELECT id_resena, bank_id, text_key, families, "
            "flag_update, flag_security, praise, prompt_version FROM "
            f"{self._table('review_aspects')} WHERE fecha >= @since "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY id_resena "
            "ORDER BY labeled_at DESC) = 1), "
            "used AS (SELECT DISTINCT id_resena FROM "
            f"{self._table('hitl_items')} WHERE task = 'aspects'), "
            "pool AS (SELECT l.* FROM latest AS l "
            "JOIN neg AS n USING (id_resena, bank_id) "
            "LEFT JOIN used AS u USING (id_resena) WHERE u.id_resena IS NULL), "
            "ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY bank_id "
            "ORDER BY FARM_FINGERPRINT(CONCAT(@seed, id_resena))) AS rnk "
            "FROM pool) SELECT * EXCEPT (rnk) FROM ranked WHERE rnk <= @size"
        )
        rows = self._reader.rows(
            sql,
            [
                Param("since", "TIMESTAMP", since),
                Param("seed", "STRING", seed),
                Param("size", "INT64", size),
            ],
            name="admin_aspects_candidates",
        )
        return [_candidate(row) for row in rows]

    def add(
        self, items: Sequence[HitlItem], events: Sequence[HitlEvent]
    ) -> None:
        # Una sentencia por tabla (cada ``INSERT`` de BigQuery tarda segundos),
        # primero los casos: un evento sin caso no aparece en ``hitl_queue``.
        self._writer.insert_many("hitl_items", items, key=["item_id"])
        self._writer.insert_many("hitl_events", events, key=["event_id"])

    def batches(self) -> list[SampleBatchOut]:
        sql = (
            "WITH s AS (SELECT item_id, task, created_at, "  # nosec B608
            "SPLIT(item_id, ':')[SAFE_OFFSET(2)] AS batch FROM "
            f"{self._table('hitl_items')} "
            "WHERE reason = 'manual' AND task = 'aspects'), "
            "done AS (SELECT DISTINCT item_id FROM "
            f"{self._table('hitl_reviews')} "
            "WHERE TRUE AND task = 'aspects') "
            "SELECT s.batch, ANY_VALUE(s.task) AS task, "
            "MIN(s.created_at) AS created_at, COUNT(*) AS size, "
            "COUNTIF(d.item_id IS NOT NULL) AS reviewed "
            "FROM s LEFT JOIN done AS d USING (item_id) "
            f"GROUP BY s.batch ORDER BY created_at DESC LIMIT {LOTS_LIMIT}"
        )
        rows = self._reader.rows(sql, [], name="admin_sample_batches")
        return [_batch(row) for row in rows]


def _candidate(row: Mapping[str, Any]) -> AspectCandidate:
    return AspectCandidate(
        id_resena=str(row["id_resena"]),
        bank_id=str(row["bank_id"]),
        text_key=str(row["text_key"]),
        predicted={
            "families": sorted(row.get("families") or ()),
            "flag_update": bool(row["flag_update"]),
            "flag_security": bool(row["flag_security"]),
            "praise": bool(row["praise"]),
            "prompt_version": str(row["prompt_version"]),
        },
    )


def _batch(row: Mapping[str, Any]) -> SampleBatchOut:
    return SampleBatchOut(
        batch=str(row["batch"]),
        task=HitlTask(row["task"]),
        created_at=row["created_at"],
        size=int(row["size"]),
        reviewed=int(row["reviewed"] or 0),
    )


class InMemorySamplesRepository:
    """Doble de pruebas y de ``PORTAL_DATA=fixtures``."""

    def __init__(self, pool: Sequence[AspectCandidate] = ()) -> None:
        self.pool = list(pool)
        self.items: list[HitlItem] = []
        self.events: list[HitlEvent] = []
        self.reviewed: set[str] = set()

    def candidates(
        self, since: datetime, size: int, seed: str
    ) -> list[AspectCandidate]:
        used = {i.id_resena for i in self.items}
        free = [c for c in self.pool if c.id_resena not in used]
        by_bank: dict[str, list[AspectCandidate]] = defaultdict(list)
        for c in sorted(free, key=lambda c: rank_key(seed, c)):
            if len(by_bank[c.bank_id]) < size:
                by_bank[c.bank_id].append(c)
        return [c for rows in by_bank.values() for c in rows]

    def add(
        self, items: Sequence[HitlItem], events: Sequence[HitlEvent]
    ) -> None:
        self.items.extend(items)
        self.events.extend(events)

    def batches(self) -> list[SampleBatchOut]:
        grouped: dict[str, list[HitlItem]] = defaultdict(list)
        for item in self.items:
            grouped[item.item_id.split(":")[2]].append(item)
        return sorted(
            (
                SampleBatchOut(
                    batch=batch,
                    task=HitlTask.ASPECTS,
                    created_at=min(i.created_at for i in items),
                    size=len(items),
                    reviewed=sum(i.item_id in self.reviewed for i in items),
                )
                for batch, items in grouped.items()
            ),
            key=lambda b: b.created_at,
            reverse=True,
        )


def sample_samples_repository() -> InMemorySamplesRepository:
    pool = [
        AspectCandidate(
            id_resena=f"syn-asp-{n:03d}",
            bank_id=bank,
            text_key=hashlib.sha256(f"asp-{n}".encode()).hexdigest(),
            predicted={
                "families": ["AC"] if n % 2 else ["TR", "UX"],
                "flag_update": n % 3 == 0,
                "flag_security": False,
                "praise": False,
                "prompt_version": "aspects_v2_1",
            },
        )
        for n, bank in enumerate(("BANCO_A", "BANCO_B") * 30)
    ]
    return InMemorySamplesRepository(pool)
