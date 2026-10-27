"""Curaduría de tópicos de cada versión de BERTopic.

Una versión nueva de ``topic_model_versions`` vale (vista
``topic_model_current``) cuando todos sus tópicos emparejados con la versión
anterior tienen una decisión en ``curation_topics``. La última decisión de un
tópico gana, así que también se puede volver a curar la versión vigente.
"""

# ruff: noqa: S608
# Los nombres de tablas salen de ``qualified`` (lista cerrada); los valores
# viajan siempre como parámetros.

import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, ValidationError
from voc_common import AspectFamily, HitlTask, TopicAudience, TopicCuration

from api_backend.auth.deps import ROUTE_ROLES, Principal, Settings, require
from api_backend.auth.roles import Role
from api_backend.bq.deps import reader_for, writer_for
from api_backend.bq.names import qualified
from api_backend.bq.reader import BigQueryReader, Param
from api_backend.bq.writer import BigQueryWriter
from api_backend.errors import ApiError, ErrorCode
from api_backend.sections.hitl.repository import HitlRepository
from api_backend.sections.hitl.router import get_repository as get_hitl_repo
from api_backend.settings import ApiSettings

EXAMPLES = 5
EXAMPLE_CHARS = 600
# El catálogo, los tamaños y los ejemplos de una versión casi no cambian; las
# decisiones sí, y se leen siempre sin memoria.
CATALOG_CACHE_SECONDS = 900.0


# -- Modelos -----------------------------------------------------------------


class TopicVersionOut(BaseModel):
    topic_model_version: str
    fitted_at: datetime
    topics: int
    paired: int  # tópicos emparejados con la versión anterior
    decided: int  # de los emparejados, los que ya tienen decisión
    is_current: bool
    # Al decidir el último emparejado la versión pasa a ser la vigente (salvo
    # que otra más nueva ya esté completa).
    activates_on_completion: bool


class TopicVersionsResponse(BaseModel):
    versions: list[TopicVersionOut]


class DecisionOut(BaseModel):
    curated_name: str
    coherence_1_5: int
    audience: TopicAudience
    families: list[AspectFamily]
    is_new_theme: bool
    mapping_confirmed: bool
    curated_at: datetime


class PreviousTopicOut(BaseModel):
    topic_id: int
    centroid_similarity: float
    # La última curaduría de ese tópico en la versión anterior.
    curation: DecisionOut | None


class TopicOut(BaseModel):
    topic_id: int
    terms: list[str]
    size: int  # cláusulas asignadas
    previous: PreviousTopicOut | None
    decision: DecisionOut | None


class TopicVersionDetail(BaseModel):
    topic_model_version: str
    fitted_at: datetime
    is_current: bool
    topics: list[TopicOut]
    paired: int
    decided: int


class ExampleOut(BaseModel):
    text: str  # texto sanitizado del TDS, recortado


class ExamplesResponse(BaseModel):
    topic_id: int
    examples: list[ExampleOut]


class TopicCurationIn(BaseModel):
    curated_name: str = Field(min_length=1, max_length=80)
    coherence_1_5: int = Field(ge=1, le=5)
    audience: TopicAudience
    families: list[AspectFamily]
    is_new_theme: bool
    mapping_confirmed: bool


class TopicCurationOut(BaseModel):
    paired: int
    decided: int
    # La versión quedó completa con esta decisión.
    completed: bool


# -- Repositorio -------------------------------------------------------------


@dataclass(frozen=True)
class CatalogTopic:
    topic_id: int
    terms: tuple[str, ...]
    size: int
    previous_topic_id: int | None
    centroid_similarity: float | None


@dataclass(frozen=True)
class VersionStats:
    topic_model_version: str
    fitted_at: datetime
    topics: int
    paired: int
    decided: int


class TopicsRepository(Protocol):
    def versions(self) -> list[VersionStats]:
        """Versiones desde la vigente en adelante (la más nueva primero)."""

    def current_version(self) -> str | None: ...

    def previous_version(self, version: str) -> str | None:
        """La versión anterior por ``fitted_at``."""

    def catalog(self, version: str) -> list[CatalogTopic]: ...

    def decisions(
        self, versions: Sequence[str]
    ) -> dict[tuple[str, int], DecisionOut]:
        """La última decisión de cada tópico de las versiones."""

    def example_ids(
        self, version: str, topic_id: int, n: int
    ) -> list[tuple[str, str]]:
        """``(bank_id, id_resena)`` al azar con semilla fija por tópico."""

    def add(self, row: TopicCuration) -> bool: ...


def seed_for(version: str, topic_id: int) -> str:
    return hashlib.sha256(f"{version}:{topic_id}".encode()).hexdigest()[:16]


def _decision(row: Mapping[str, Any]) -> DecisionOut:
    return DecisionOut(
        curated_name=str(row["curated_name"]),
        coherence_1_5=int(row["coherence_1_5"]),
        audience=TopicAudience(row["audience"]),
        families=[AspectFamily(f) for f in row.get("families") or ()],
        is_new_theme=bool(row["is_new_theme"]),
        mapping_confirmed=bool(row["mapping_confirmed"]),
        curated_at=row["curated_at"],
    )


class BigQueryTopicsRepository:
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

    def versions(self) -> list[VersionStats]:
        sql = (
            "WITH cur AS (SELECT fitted_at FROM "  # nosec B608
            f"{self._table('topic_model_current')}), "
            "decided AS (SELECT DISTINCT topic_model_version, topic_id FROM "
            f"{self._table('curation_topics')}), "
            "stats AS (SELECT c.topic_model_version, COUNT(*) AS topics, "
            "COUNTIF(c.previous_topic_id IS NOT NULL) AS paired, "
            "COUNTIF(c.previous_topic_id IS NOT NULL "
            "AND d.topic_id IS NOT NULL) AS decided FROM "
            f"{self._table('topic_catalog')} AS c "
            "LEFT JOIN decided AS d USING (topic_model_version, topic_id) "
            "GROUP BY c.topic_model_version) "
            "SELECT v.topic_model_version, v.fitted_at, s.topics, s.paired, "
            "s.decided FROM "
            f"{self._table('topic_model_versions')} AS v "
            "JOIN stats AS s USING (topic_model_version) "
            "WHERE v.fitted_at >= (SELECT fitted_at FROM cur) "
            "ORDER BY v.fitted_at DESC"
        )
        rows = self._reader.rows(sql, [], name="topics_versions")
        return [
            VersionStats(
                topic_model_version=str(r["topic_model_version"]),
                fitted_at=r["fitted_at"],  # type: ignore[arg-type]
                topics=int(r["topics"]),  # type: ignore[call-overload]
                paired=int(r["paired"]),  # type: ignore[call-overload]
                decided=int(r["decided"]),  # type: ignore[call-overload]
            )
            for r in rows
        ]

    def current_version(self) -> str | None:
        rows = self._reader.rows(
            "SELECT topic_model_version FROM "  # nosec B608
            f"{self._table('topic_model_current')}",
            [],
            name="topics_current",
        )
        return str(rows[0]["topic_model_version"]) if rows else None

    def previous_version(self, version: str) -> str | None:
        rows = self._reader.rows(
            "SELECT topic_model_version FROM "  # nosec B608
            f"{self._table('topic_model_versions')} "
            "WHERE fitted_at < (SELECT fitted_at FROM "
            f"{self._table('topic_model_versions')} "
            "WHERE topic_model_version = @v) "
            "ORDER BY fitted_at DESC LIMIT 1",
            [Param("v", "STRING", version)],
            name="topics_previous",
        )
        return str(rows[0]["topic_model_version"]) if rows else None

    def catalog(self, version: str) -> list[CatalogTopic]:
        params = [Param("v", "STRING", version)]
        topics = self._reader.rows(
            "SELECT topic_id, terms, previous_topic_id, centroid_similarity "  # nosec B608
            f"FROM {self._table('topic_catalog')} "
            "WHERE topic_model_version = @v ORDER BY topic_id",
            params,
            name="topics_catalog",
        )
        sizes = self._reader.rows(
            "SELECT topic_id, COUNT(*) AS n FROM "  # nosec B608
            f"{self._table('topic_assignments')} "
            "WHERE TRUE AND topic_model_version = @v GROUP BY topic_id",
            params,
            name="topics_sizes",
        )
        size_of = {int(r["topic_id"]): int(r["n"]) for r in sizes}  # type: ignore[call-overload]
        return [
            CatalogTopic(
                topic_id=int(r["topic_id"]),  # type: ignore[call-overload]
                terms=tuple(r.get("terms") or ()),
                size=size_of.get(int(r["topic_id"]), 0),  # type: ignore[call-overload]
                previous_topic_id=(
                    None
                    if r.get("previous_topic_id") is None
                    else int(r["previous_topic_id"])  # type: ignore[call-overload]
                ),
                centroid_similarity=(
                    None
                    if r.get("centroid_similarity") is None
                    else float(r["centroid_similarity"])  # type: ignore[arg-type]
                ),
            )
            for r in topics
        ]

    def decisions(
        self, versions: Sequence[str]
    ) -> dict[tuple[str, int], DecisionOut]:
        rows = self._reader.rows(
            "SELECT topic_model_version, topic_id, curated_name, "  # nosec B608
            "coherence_1_5, audience, families, is_new_theme, "
            "mapping_confirmed, curated_at FROM "
            f"{self._table('curation_topics')} "
            "WHERE topic_model_version IN UNNEST(@versions) "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY topic_model_version, "
            "topic_id ORDER BY curated_at DESC) = 1",
            [Param("versions", "STRING", list(versions), array=True)],
            name="topics_decisions",
        )
        return {
            (str(r["topic_model_version"]), int(r["topic_id"])): _decision(r)  # type: ignore[call-overload]
            for r in rows
        }

    def example_ids(
        self, version: str, topic_id: int, n: int
    ) -> list[tuple[str, str]]:
        rows = self._reader.rows(
            "SELECT bank_id, id_resena FROM "  # nosec B608
            f"{self._table('topic_assignments')} "
            "WHERE TRUE AND topic_model_version = @v AND topic_id = @t "
            "GROUP BY bank_id, id_resena "
            "ORDER BY FARM_FINGERPRINT(CONCAT(@seed, id_resena)) LIMIT @n",
            [
                Param("v", "STRING", version),
                Param("t", "INT64", topic_id),
                Param("seed", "STRING", seed_for(version, topic_id)),
                Param("n", "INT64", n),
            ],
            name="topics_examples",
        )
        return [(str(r["bank_id"]), str(r["id_resena"])) for r in rows]

    def add(self, row: TopicCuration) -> bool:
        return self._writer.insert(
            "curation_topics",
            row,
            key=["topic_model_version", "topic_id", "curated_at"],
        )


class InMemoryTopicsRepository:
    """Doble de pruebas y de ``PORTAL_DATA=fixtures``."""

    def __init__(
        self,
        versions: Sequence[tuple[str, datetime]] = (),
        catalog: Mapping[str, Sequence[CatalogTopic]] | None = None,
        examples: Mapping[tuple[str, int], Sequence[tuple[str, str]]]
        | None = None,
    ) -> None:
        self._versions = sorted(versions, key=lambda v: v[1], reverse=True)
        self._catalog = {k: list(v) for k, v in (catalog or {}).items()}
        self._examples = dict(examples or {})
        self.rows: list[TopicCuration] = []

    def _decided(self, version: str) -> dict[int, TopicCuration]:
        latest: dict[int, TopicCuration] = {}
        for row in sorted(self.rows, key=lambda r: r.curated_at):
            if row.topic_model_version == version:
                latest[row.topic_id] = row
        return latest

    def _stats(self, version: str, fitted_at: datetime) -> VersionStats:
        topics = self._catalog.get(version, [])
        decided = self._decided(version)
        paired = [t for t in topics if t.previous_topic_id is not None]
        return VersionStats(
            topic_model_version=version,
            fitted_at=fitted_at,
            topics=len(topics),
            paired=len(paired),
            decided=sum(t.topic_id in decided for t in paired),
        )

    def _all(self) -> list[VersionStats]:
        return [self._stats(v, at) for v, at in self._versions]

    def current_version(self) -> str | None:
        # Como la vista: la más reciente con todos sus pares decididos.
        for stats in self._all():
            if stats.decided == stats.paired:
                return stats.topic_model_version
        return None

    def versions(self) -> list[VersionStats]:
        current = self.current_version()
        out: list[VersionStats] = []
        for stats in self._all():
            out.append(stats)
            if stats.topic_model_version == current:
                break
        return out

    def previous_version(self, version: str) -> str | None:
        ordered = [v for v, _ in self._versions]
        i = ordered.index(version) if version in ordered else -1
        return ordered[i + 1] if 0 <= i < len(ordered) - 1 else None

    def catalog(self, version: str) -> list[CatalogTopic]:
        return list(self._catalog.get(version, []))

    def decisions(
        self, versions: Sequence[str]
    ) -> dict[tuple[str, int], DecisionOut]:
        return {
            (v, topic_id): DecisionOut(
                curated_name=row.curated_name,
                coherence_1_5=row.coherence_1_5,
                audience=row.audience,
                families=list(row.families),
                is_new_theme=row.is_new_theme,
                mapping_confirmed=row.mapping_confirmed,
                curated_at=row.curated_at,
            )
            for v in versions
            for topic_id, row in self._decided(v).items()
        }

    def example_ids(
        self, version: str, topic_id: int, n: int
    ) -> list[tuple[str, str]]:
        pool = sorted(
            self._examples.get((version, topic_id), []),
            key=lambda p: hashlib.sha256(
                f"{seed_for(version, topic_id)}{p[1]}".encode()
            ).hexdigest(),
        )
        return pool[:n]

    def add(self, row: TopicCuration) -> bool:
        self.rows.append(row)
        return True


class CachedTopicsRepository:
    """Memoria del proceso para lo que no cambia con una decisión."""

    def __init__(
        self,
        inner: TopicsRepository,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._clock = clock
        self._catalogs: dict[str, tuple[float, list[CatalogTopic]]] = {}
        self._examples: dict[
            tuple[str, int], tuple[float, list[tuple[str, str]]]
        ] = {}

    def versions(self) -> list[VersionStats]:
        return self._inner.versions()

    def current_version(self) -> str | None:
        return self._inner.current_version()

    def previous_version(self, version: str) -> str | None:
        return self._inner.previous_version(version)

    def catalog(self, version: str) -> list[CatalogTopic]:
        hit = self._catalogs.get(version)
        if hit and self._clock() - hit[0] < CATALOG_CACHE_SECONDS:
            return list(hit[1])
        found = self._inner.catalog(version)
        self._catalogs[version] = (self._clock(), found)
        return list(found)

    def decisions(
        self, versions: Sequence[str]
    ) -> dict[tuple[str, int], DecisionOut]:
        return self._inner.decisions(versions)

    def example_ids(
        self, version: str, topic_id: int, n: int
    ) -> list[tuple[str, str]]:
        key = (version, topic_id)
        hit = self._examples.get(key)
        if hit and self._clock() - hit[0] < CATALOG_CACHE_SECONDS:
            return list(hit[1])
        found = self._inner.example_ids(version, topic_id, n)
        self._examples[key] = (self._clock(), found)
        return list(found)

    def add(self, row: TopicCuration) -> bool:
        return self._inner.add(row)


# -- Servicio ----------------------------------------------------------------


def ensure_topic_reviewer(principal: Principal) -> None:
    if (
        Role.REVISOR not in principal.roles
        or HitlTask.TOPIC not in principal.reviewer_tasks
    ):
        raise ApiError(ErrorCode.FORBIDDEN, "No tienes permiso para esta cola")


def versions(
    repo: TopicsRepository, principal: Principal
) -> TopicVersionsResponse:
    ensure_topic_reviewer(principal)
    stats = repo.versions()
    current = repo.current_version()
    complete = [s for s in stats if s.decided == s.paired]
    newest_complete = complete[0].fitted_at if complete else None
    return TopicVersionsResponse(
        versions=[
            TopicVersionOut(
                topic_model_version=s.topic_model_version,
                fitted_at=s.fitted_at,
                topics=s.topics,
                paired=s.paired,
                decided=s.decided,
                is_current=s.topic_model_version == current,
                activates_on_completion=(
                    newest_complete is None or s.fitted_at >= newest_complete
                ),
            )
            for s in stats
        ]
    )


def _stats_of(repo: TopicsRepository, version: str) -> VersionStats:
    for stats in repo.versions():
        if stats.topic_model_version == version:
            return stats
    raise ApiError(ErrorCode.NOT_FOUND, "No existe la versión de tópicos")


def detail(
    repo: TopicsRepository, principal: Principal, version: str
) -> TopicVersionDetail:
    ensure_topic_reviewer(principal)
    stats = _stats_of(repo, version)
    catalog = repo.catalog(version)
    previous = repo.previous_version(version)
    wanted = [version, *([previous] if previous else [])]
    decisions = repo.decisions(wanted)
    topics = []
    for t in catalog:
        pair = None
        if t.previous_topic_id is not None and previous is not None:
            pair = PreviousTopicOut(
                topic_id=t.previous_topic_id,
                centroid_similarity=t.centroid_similarity or 0.0,
                curation=decisions.get((previous, t.previous_topic_id)),
            )
        topics.append(
            TopicOut(
                topic_id=t.topic_id,
                terms=list(t.terms),
                size=t.size,
                previous=pair,
                decision=decisions.get((version, t.topic_id)),
            )
        )
    return TopicVersionDetail(
        topic_model_version=version,
        fitted_at=stats.fitted_at,
        is_current=version == repo.current_version(),
        topics=topics,
        paired=stats.paired,
        decided=stats.decided,
    )


def _ensure_topic(
    repo: TopicsRepository, version: str, topic_id: int
) -> CatalogTopic:
    for topic in repo.catalog(version):
        if topic.topic_id == topic_id:
            return topic
    raise ApiError(ErrorCode.NOT_FOUND, "No existe el tópico")


def examples(
    repo: TopicsRepository,
    texts: HitlRepository,
    principal: Principal,
    version: str,
    topic_id: int,
    n: int,
) -> ExamplesResponse:
    ensure_topic_reviewer(principal)
    _ensure_topic(repo, version, topic_id)
    ids = repo.example_ids(version, topic_id, n)
    # Una sola consulta al TDS para todos; el banco y el id nunca salen.
    found = texts.review_texts(ids)
    return ExamplesResponse(
        topic_id=topic_id,
        examples=[
            ExampleOut(text=found[pair][:EXAMPLE_CHARS])
            for pair in ids
            if pair in found
        ],
    )


def curate(  # noqa: PLR0913
    repo: TopicsRepository,
    principal: Principal,
    version: str,
    topic_id: int,
    body: TopicCurationIn,
    now: datetime,
) -> TopicCurationOut:
    ensure_topic_reviewer(principal)
    _ensure_topic(repo, version, topic_id)
    try:
        row = TopicCuration(
            topic_model_version=version,
            topic_id=topic_id,
            curated_name=body.curated_name.strip(),
            coherence_1_5=body.coherence_1_5,
            audience=body.audience,
            families=body.families,
            is_new_theme=body.is_new_theme,
            mapping_confirmed=body.mapping_confirmed,
            curator_hash=principal.actor_hash,
            curated_at=now,
        )
    except ValidationError as exc:
        raise ApiError(ErrorCode.INVALID, "Curaduría no válida") from exc
    repo.add(row)
    stats = _stats_of(repo, version)
    return TopicCurationOut(
        paired=stats.paired,
        decided=stats.decided,
        completed=stats.paired > 0 and stats.decided == stats.paired,
    )


# -- Rutas -------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/hitl/topics", tags=["hitl"])

for _method, _route in (
    ("GET", "versions"),
    ("GET", "{version}"),
    ("GET", "{version}/{topic_id}/examples"),
    ("POST", "{version}/{topic_id}"),
):
    ROUTE_ROLES[(_method, f"/api/v1/hitl/topics/{_route}")] = Role.REVISOR


def get_topics_repository(
    request: Request, settings: Settings
) -> TopicsRepository:
    state = request.app.state
    repo = getattr(state, "topics_repository", None)
    if repo is None:
        if settings.portal_data == "fixtures":
            repo = sample_topics_repository()
        else:
            repo = CachedTopicsRepository(
                BigQueryTopicsRepository(
                    reader_for(request, settings),
                    writer_for(request, settings),
                    settings,
                )
            )
        state.topics_repository = repo
    return repo


def now() -> datetime:
    return datetime.now(UTC)


Reviewer = Annotated[Principal, Depends(require(Role.REVISOR))]
Repo = Annotated[TopicsRepository, Depends(get_topics_repository)]
Texts = Annotated[HitlRepository, Depends(get_hitl_repo)]
Now = Annotated[datetime, Depends(now)]


@router.get("/versions")
def list_versions(principal: Reviewer, repo: Repo) -> TopicVersionsResponse:
    """Versiones desde la vigente en adelante, con su avance de curaduría."""
    return versions(repo, principal)


@router.get("/{version}")
def version_detail(
    version: str, principal: Reviewer, repo: Repo
) -> TopicVersionDetail:
    return detail(repo, principal, version)


@router.get("/{version}/{topic_id}/examples")
def topic_examples(  # noqa: PLR0913
    version: str,
    topic_id: int,
    principal: Reviewer,
    repo: Repo,
    texts: Texts,
    n: Annotated[int, Query(ge=1, le=10)] = EXAMPLES,
) -> ExamplesResponse:
    return examples(repo, texts, principal, version, topic_id, n)


@router.post("/{version}/{topic_id}", status_code=201)
def curate_topic(  # noqa: PLR0913
    version: str,
    topic_id: int,
    body: TopicCurationIn,
    principal: Reviewer,
    repo: Repo,
    at: Now,
) -> TopicCurationOut:
    return curate(repo, principal, version, topic_id, body, at)


# -- Datos sintéticos --------------------------------------------------------


def sample_topics_repository() -> InMemoryTopicsRepository:
    t0 = datetime(2026, 7, 1, tzinfo=UTC)
    t1 = datetime(2026, 10, 1, tzinfo=UTC)
    old = [
        CatalogTopic(0, ("token", "codigo", "sms"), 120, None, None),
        CatalogTopic(1, ("transferencia", "spei", "falla"), 90, None, None),
    ]
    new = [
        CatalogTopic(0, ("token", "codigo", "verificacion"), 140, 0, 0.93),
        CatalogTopic(1, ("spei", "transferencia", "error"), 95, 1, 0.88),
        CatalogTopic(
            2, ("actualizacion", "version", "forzosa"), 60, None, None
        ),
    ]
    sample = InMemoryTopicsRepository(
        versions=[("model_v0", t0), ("model_v1", t1)],
        catalog={"model_v0": old, "model_v1": new},
        examples={
            ("model_v1", 0): [
                ("BANCO_A", f"syn-hitl-000{n}") for n in range(1, 7)
            ],
        },
    )
    sample.rows.extend(
        TopicCuration(
            topic_model_version="model_v0",
            topic_id=t.topic_id,
            curated_name=name,
            coherence_1_5=4,
            audience=TopicAudience.PRODUCTO,
            families=[AspectFamily.AC if t.topic_id == 0 else AspectFamily.TR],
            is_new_theme=False,
            mapping_confirmed=True,
            curator_hash="a" * 64,
            curated_at=t0,
        )
        for t, name in zip(
            old, ("Códigos de acceso", "Falla en transferencias"), strict=True
        )
    )
    return sample
