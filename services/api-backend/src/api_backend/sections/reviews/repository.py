"""Lecturas del Explorador: ``Protocol``, BigQuery y versión en memoria."""

# ruff: noqa: S608
# Los nombres de tablas salen de ``qualified`` (lista cerrada); los valores
# viajan siempre como parámetros.

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from api_backend.bq.names import qualified
from api_backend.bq.reader import BigQueryReader, Param
from api_backend.sections.reviews.filters import ReviewFilters, day_after
from api_backend.sections.reviews.schemas import (
    ExplanationRef,
    FacetCount,
    HitlReviewRef,
    ReviewRow,
    SortKey,
    TopicRef,
)
from api_backend.settings import ApiSettings

TOP_TOPICS = 20
MIN_VECTOR_POOL = 3
ROW_COLUMNS = (
    "id_resena, bank_id, text_key, fecha, version_app, estrellas, sentiment, "
    "p_neg, p_neu, p_pos, confidence, model_version, "
    "COALESCE(families, []) AS families, flag_update, flag_security, "
    "prompt_version, COALESCE(topic_ids, []) AS topic_ids, hitl_reviewed"
)
ORDER_BY: dict[str, str] = {
    "fecha_desc": "fecha DESC, id_resena",
    "confidence_asc": "confidence ASC NULLS LAST, fecha DESC, id_resena",
    "estrellas_asc": "estrellas ASC, fecha DESC, id_resena",
}


@dataclass(frozen=True)
class VectorHit:
    text_key: str
    bank_id: str
    distance: float


@dataclass(frozen=True)
class Group:
    """Reseñas con el mismo texto y banco en la ventana."""

    n_reviews: int
    example: ReviewRow


class ReviewsRepository(Protocol):
    def facets(
        self, f: ReviewFilters
    ) -> tuple[int, dict[str, list[FacetCount]]]: ...

    def page(
        self, f: ReviewFilters, sort: SortKey, page: int, page_size: int
    ) -> tuple[list[ReviewRow], int]: ...

    def detail(
        self, bank_id: str, id_resena: str
    ) -> tuple[ReviewRow, str | None] | None: ...

    def hitl_reviews(self, id_resena: str) -> list[HitlReviewRef]: ...

    def stored_explanation(self, text_key: str) -> ExplanationRef | None: ...

    def vector_search(
        self,
        embedding: Sequence[float],
        banks: Sequence[str],
        from_month: date,
        k: int,
        stats: dict[str, int],
    ) -> list[VectorHit]: ...

    def groups(
        self, hits: Sequence[VectorHit], date_from: date
    ) -> dict[tuple[str, str], Group]: ...


def _ts(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


class BigQueryReviewsRepository:
    def __init__(self, reader: BigQueryReader, settings: ApiSettings) -> None:
        self._reader = reader
        self._project = settings.gcp_project_id
        self._dataset = settings.bq_dataset_id

    def _table(self, name: str) -> str:
        return qualified(name, self._project, self._dataset)

    # -- consulta base -----------------------------------------------------

    def _base(
        self, f: ReviewFilters, extra: str = ""
    ) -> tuple[str, list[Param]]:
        """CTE ``base``: predicciones vigentes con aspectos, tópicos y HITL.

        Los rangos de fecha van sin función sobre ``fecha`` para podar
        particiones; el texto no entra aquí (se trae solo de la página).
        """
        params = [
            Param("from_ts", "TIMESTAMP", _ts(f.date_from)),
            Param("to_ts", "TIMESTAMP", _ts(day_after(f.date_to))),
            Param("banks", "STRING", list(f.banks), array=True),
        ]
        where = [
            "p.fecha >= @from_ts",
            "p.fecha < @to_ts",
            "p.bank_id IN UNNEST(@banks)",
        ]
        if f.sentiment:
            where.append("p.sentiment IN UNNEST(@sentiment)")
            params.append(
                Param("sentiment", "STRING", list(f.sentiment), array=True)
            )
        if f.stars:
            where.append("p.estrellas IN UNNEST(@stars)")
            params.append(Param("stars", "INT64", list(f.stars), array=True))
        if f.version is not None:
            where.append("p.version_app = @version")
            params.append(Param("version", "STRING", f.version))
        if f.families:
            where.append(
                "EXISTS (SELECT 1 FROM UNNEST(a.families) AS fam "
                "WHERE fam IN UNNEST(@families))"
            )
            params.append(
                Param("families", "STRING", list(f.families), array=True)
            )
        if f.flag_update is not None:
            where.append("a.flag_update = @flag_update")
            params.append(Param("flag_update", "BOOL", f.flag_update))
        if f.flag_security is not None:
            where.append("a.flag_security = @flag_security")
            params.append(Param("flag_security", "BOOL", f.flag_security))
        if f.topic_id is not None:
            where.append("@topic_id IN UNNEST(t.topic_ids)")
            params.append(Param("topic_id", "INT64", f.topic_id))
        if f.hitl_reviewed is not None:
            where.append("(h.id_resena IS NOT NULL) = @hitl")
            params.append(Param("hitl", "BOOL", f.hitl_reviewed))
        if extra:
            where.append(extra)
        sql = (
            "WITH a AS (SELECT id_resena, families, flag_update, "  # nosec B608
            "flag_security, prompt_version "
            f"FROM {self._table('review_aspects')} "
            "WHERE fecha >= @from_ts AND fecha < @to_ts "
            "AND bank_id IN UNNEST(@banks) "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY id_resena "
            "ORDER BY labeled_at DESC) = 1), "
            "t AS (SELECT x.id_resena, ARRAY_AGG(DISTINCT x.topic_id) "
            "AS topic_ids "
            f"FROM {self._table('topic_assignments')} AS x "
            f"JOIN {self._table('topic_model_current')} AS v "
            "USING (topic_model_version) "
            "WHERE x.fecha >= @from_ts AND x.fecha < @to_ts "
            "AND x.bank_id IN UNNEST(@banks) AND x.topic_id >= 0 "
            "GROUP BY x.id_resena), "
            "h AS (SELECT DISTINCT id_resena "
            f"FROM {self._table('hitl_reviews')} "
            "WHERE TRUE AND task = 'sentiment'), "
            "base AS (SELECT p.id_resena, p.bank_id, p.text_key, p.fecha, "
            "p.version_app, p.estrellas, p.sentiment, p.p_neg, p.p_neu, "
            "p.p_pos, p.confidence, p.model_version, a.families, "
            "a.flag_update, a.flag_security, a.prompt_version, t.topic_ids, "
            "h.id_resena IS NOT NULL AS hitl_reviewed "
            f"FROM {self._table('review_predictions_current')} AS p "
            "LEFT JOIN a USING (id_resena) LEFT JOIN t USING (id_resena) "
            "LEFT JOIN h USING (id_resena) "
            f"WHERE {' AND '.join(where)}) "
        )
        return sql, params

    # -- apoyo ---------------------------------------------------------------

    def topic_names(self) -> dict[int, str]:
        sql = (
            "SELECT c.topic_id, c.curated_name "  # nosec B608
            f"FROM {self._table('curation_topics')} AS c "
            f"JOIN {self._table('topic_model_current')} "
            "USING (topic_model_version) WHERE TRUE "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY c.topic_id "
            "ORDER BY c.curated_at DESC) = 1"
        )
        rows = self._reader.rows(
            sql, [], name="reviews_topic_names", cache=True
        )
        return {int(r["topic_id"]): str(r["curated_name"]) for r in rows}  # type: ignore[call-overload]

    def _texts(
        self, rows: Sequence[Mapping[str, Any]]
    ) -> dict[tuple[str, str], str]:
        """Texto de las reseñas de una página, con la fecha acotada.

        Solo cuenta el texto cuyo hash es el ``text_key`` de la predicción: si
        la reseña cambió desde entonces, el campo queda vacío.
        """
        if not rows:
            return {}
        first = min(r["fecha"] for r in rows)
        last = max(r["fecha"] for r in rows)
        sql = (
            "SELECT id_resena, bank_id, texto_sanitizado, "  # nosec B608
            "TO_HEX(SHA256(texto_sanitizado)) AS text_key "
            f"FROM {self._table('sanitized_reviews_tds')} "
            "WHERE fecha >= @first AND fecha < @after "
            "AND bank_id IN UNNEST(@banks) AND id_resena IN UNNEST(@ids)"
        )
        found = self._reader.rows(
            sql,
            [
                Param("first", "TIMESTAMP", first),
                Param("after", "TIMESTAMP", last + timedelta(seconds=1)),
                Param(
                    "banks",
                    "STRING",
                    sorted({str(r["bank_id"]) for r in rows}),
                    array=True,
                ),
                Param(
                    "ids",
                    "STRING",
                    sorted({str(r["id_resena"]) for r in rows}),
                    array=True,
                ),
            ],
            name="reviews_texts",
        )
        wanted = {(str(r["id_resena"]), str(r["text_key"])) for r in rows}
        return {
            (str(r["bank_id"]), str(r["id_resena"])): str(r["texto_sanitizado"])
            for r in found
            if (str(r["id_resena"]), str(r["text_key"])) in wanted
        }

    def _rows(self, raw: Sequence[Mapping[str, Any]]) -> list[ReviewRow]:
        names = self.topic_names() if any(r["topic_ids"] for r in raw) else {}
        texts = self._texts(raw)
        return [_row(r, texts, names) for r in raw]

    # -- consultas -------------------------------------------------------------

    def facets(
        self, f: ReviewFilters
    ) -> tuple[int, dict[str, list[FacetCount]]]:
        base, params = self._base(f)
        sql = (
            base + "SELECT dim, k, COUNT(*) AS n FROM ("  # nosec B608
            "SELECT 'bank' AS dim, bank_id AS k FROM base UNION ALL "
            "SELECT 'month', FORMAT_DATE('%Y-%m', DATE(fecha)) FROM base "
            "UNION ALL SELECT 'sentiment', sentiment FROM base UNION ALL "
            "SELECT 'stars', CAST(estrellas AS STRING) FROM base UNION ALL "
            "SELECT 'family', fam FROM base, UNNEST(families) AS fam "
            "UNION ALL SELECT 'flag_update', "
            "IF(flag_update, 'si', 'no') FROM base WHERE flag_update "
            "IS NOT NULL UNION ALL SELECT 'flag_security', "
            "IF(flag_security, 'si', 'no') FROM base WHERE flag_security "
            "IS NOT NULL UNION ALL SELECT 'topic', CAST(tp AS STRING) "
            "FROM base, UNNEST(topic_ids) AS tp UNION ALL "
            "SELECT 'hitl', IF(hitl_reviewed, 'si', 'no') FROM base "
            "UNION ALL SELECT 'total', '' FROM base) GROUP BY dim, k"
        )
        rows = self._reader.rows(sql, params, name="reviews_facets", cache=True)
        names = self.topic_names()
        by: dict[str, list[FacetCount]] = {}
        total = 0
        for r in rows:
            dim, key, n = str(r["dim"]), str(r["k"]), int(r["n"])  # type: ignore[call-overload]
            if dim == "total":
                total = n
                continue
            label = names.get(int(key)) if dim == "topic" else None
            by.setdefault(dim, []).append(FacetCount(key=key, n=n, label=label))
        return total, _ordered(by)

    def page(
        self, f: ReviewFilters, sort: SortKey, page: int, page_size: int
    ) -> tuple[list[ReviewRow], int]:
        base, params = self._base(f)
        sql = (
            base + f"SELECT {ROW_COLUMNS}, COUNT(*) OVER () AS total FROM base "  # nosec B608
            f"ORDER BY {ORDER_BY[sort]} LIMIT @size OFFSET @offset"
        )
        rows = self._reader.rows(
            sql,
            [
                *params,
                Param("size", "INT64", page_size),
                Param("offset", "INT64", (page - 1) * page_size),
            ],
            name="reviews_page",
        )
        if not rows:
            count = self._reader.rows(
                base + "SELECT COUNT(*) AS total FROM base",  # nosec B608
                params,
                name="reviews_count",
            )
            return [], int(count[0]["total"])  # type: ignore[call-overload]
        return self._rows(rows), int(rows[0]["total"])  # type: ignore[call-overload]

    def detail(
        self, bank_id: str, id_resena: str
    ) -> tuple[ReviewRow, str | None] | None:
        # Sin ventana: la ficha abre cualquier reseña a la que llegue un enlace.
        found = self._reader.rows(
            "SELECT fecha FROM "  # nosec B608
            f"{self._table('review_predictions_current')} "
            "WHERE bank_id = @bank AND id_resena = @id LIMIT 1",
            [
                Param("bank", "STRING", bank_id),
                Param("id", "STRING", id_resena),
            ],
            name="reviews_detail_date",
        )
        if not found:
            return None
        day = found[0]["fecha"].date()  # type: ignore[union-attr]
        f = ReviewFilters(banks=(bank_id,), date_from=day, date_to=day)
        base, params = self._base(f, "p.id_resena = @id")
        rows = self._reader.rows(
            base + f"SELECT {ROW_COLUMNS} FROM base",  # nosec B608
            [*params, Param("id", "STRING", id_resena)],
            name="reviews_detail",
        )
        if not rows:
            return None
        return self._rows(rows)[0], rows[0]["prompt_version"]  # type: ignore[return-value]

    def hitl_reviews(self, id_resena: str) -> list[HitlReviewRef]:
        rows = self._reader.rows(
            "SELECT outcome, validated_label, review_round, submitted_at "  # nosec B608
            f"FROM {self._table('hitl_reviews')} "
            "WHERE TRUE AND id_resena = @id AND task = 'sentiment' "
            "ORDER BY submitted_at",
            [Param("id", "STRING", id_resena)],
            name="reviews_hitl",
        )
        return [HitlReviewRef.model_validate(r) for r in rows]

    def stored_explanation(self, text_key: str) -> ExplanationRef | None:
        rows = self._reader.rows(
            "SELECT method, model_version, source "  # nosec B608
            f"FROM {self._table('review_explanations')} "
            "WHERE text_key = @key "
            "ORDER BY method = 'occlusion_v2' DESC, computed_at DESC LIMIT 1",
            [Param("key", "STRING", text_key)],
            name="reviews_explanation_ref",
        )
        return ExplanationRef.model_validate(rows[0]) if rows else None

    def vector_search(
        self,
        embedding: Sequence[float],
        banks: Sequence[str],
        from_month: date,
        k: int,
        stats: dict[str, int],
    ) -> list[VectorHit]:
        # La subconsulta sobre ``mes`` poda particiones: acota el costo. Hay
        # una fila por texto, banco y mes: se pide de más y se deduplica.
        sql = (
            "SELECT base.text_key AS text_key, base.bank_id AS bank_id, "  # nosec B608
            "distance FROM VECTOR_SEARCH("
            "(SELECT text_key, bank_id, mes, embedding "
            f"FROM {self._table('text_embeddings')} "
            "WHERE mes >= @from_month AND bank_id IN UNNEST(@banks)), "
            "'embedding', (SELECT @query_embedding AS embedding), "
            "top_k => @k_raw, distance_type => 'COSINE') "
            "ORDER BY distance"
        )
        rows = self._reader.rows(
            sql,
            [
                Param("from_month", "DATE", from_month),
                Param("banks", "STRING", list(banks), array=True),
                Param(
                    "query_embedding", "FLOAT64", list(embedding), array=True
                ),
                Param("k_raw", "INT64", k * MIN_VECTOR_POOL),
            ],
            name="reviews_search",
            stats=stats,
        )
        seen: set[tuple[str, str]] = set()
        hits: list[VectorHit] = []
        for r in rows:
            key = (str(r["text_key"]), str(r["bank_id"]))
            if key in seen:
                continue
            seen.add(key)
            hits.append(VectorHit(key[0], key[1], float(r["distance"])))  # type: ignore[arg-type]
        return hits[:k]

    def groups(
        self, hits: Sequence[VectorHit], date_from: date
    ) -> dict[tuple[str, str], Group]:
        if not hits:
            return {}
        f = ReviewFilters(
            banks=tuple(sorted({h.bank_id for h in hits})),
            date_from=date_from,
            date_to=datetime.now(UTC).date(),
        )
        base, params = self._base(f, "p.text_key IN UNNEST(@keys)")
        sql = (
            base + f"SELECT {ROW_COLUMNS}, "  # nosec B608
            "COUNT(*) OVER (PARTITION BY text_key, bank_id) AS n_reviews "
            "FROM base QUALIFY ROW_NUMBER() OVER "
            "(PARTITION BY text_key, bank_id ORDER BY fecha DESC) = 1"
        )
        raw = self._reader.rows(
            sql,
            [
                *params,
                Param(
                    "keys",
                    "STRING",
                    sorted({h.text_key for h in hits}),
                    array=True,
                ),
            ],
            name="reviews_search_groups",
        )
        rows = self._rows(raw)
        return {
            (r.text_key, r.bank_id): Group(int(x["n_reviews"]), r)  # type: ignore[call-overload]
            for r, x in zip(rows, raw, strict=True)
        }


def _ordered(by: dict[str, list[FacetCount]]) -> dict[str, list[FacetCount]]:
    out: dict[str, list[FacetCount]] = {}
    for dim, items in by.items():
        if dim == "month":
            out[dim] = sorted(items, key=lambda c: c.key)
        elif dim == "stars":
            out[dim] = sorted(items, key=lambda c: int(c.key))
        elif dim == "topic":
            out[dim] = sorted(items, key=lambda c: (-c.n, int(c.key)))[
                :TOP_TOPICS
            ]
        else:
            out[dim] = sorted(items, key=lambda c: (-c.n, c.key))
    return out


def _row(
    r: Mapping[str, Any],
    texts: Mapping[tuple[str, str], str],
    names: Mapping[int, str],
) -> ReviewRow:
    fecha = r["fecha"]
    return ReviewRow(
        id_resena=r["id_resena"],
        bank_id=r["bank_id"],
        text_key=r["text_key"],
        fecha=fecha.date() if isinstance(fecha, datetime) else fecha,
        version_app=r["version_app"],
        estrellas=r["estrellas"],
        text=texts.get((r["bank_id"], r["id_resena"]), ""),
        sentiment=r["sentiment"],
        p_neg=r["p_neg"],
        p_neu=r["p_neu"],
        p_pos=r["p_pos"],
        confidence=r["confidence"],
        model_version=r["model_version"],
        families=list(r["families"]),
        flag_update=r["flag_update"],
        flag_security=r["flag_security"],
        topics=[
            TopicRef(topic_id=int(t), name=names.get(int(t)))
            for t in sorted(r["topic_ids"])
        ],
        hitl_reviewed=bool(r["hitl_reviewed"]),
    )


# -- en memoria ------------------------------------------------------------


@dataclass
class SampleReview:
    """Reseña sintética con lo que la API junta de varias tablas."""

    row: ReviewRow
    prompt_version: str | None = None
    embedding: list[float] | None = None
    hitl: list[HitlReviewRef] | None = None


class InMemoryReviewsRepository:
    """Doble de pruebas y de ``PORTAL_DATA=fixtures``; sigue la misma lógica."""

    def __init__(
        self,
        reviews: Sequence[SampleReview] = (),
        explanations: Mapping[str, ExplanationRef] | None = None,
    ) -> None:
        self.reviews = list(reviews)
        self.explanations = dict(explanations or {})
        self.bytes_billed = 2_000_000

    def _filtered(self, f: ReviewFilters) -> list[ReviewRow]:
        out = []
        for item in self.reviews:
            r = item.row
            if not f.date_from <= r.fecha <= f.date_to:
                continue
            checks = [
                r.bank_id in f.banks,
                not f.sentiment or r.sentiment in f.sentiment,
                not f.stars or r.estrellas in f.stars,
                f.version is None or r.version_app == f.version,
                not f.families or bool(set(r.families) & set(f.families)),
                f.flag_update is None or r.flag_update == f.flag_update,
                f.flag_security is None or r.flag_security == f.flag_security,
                f.topic_id is None
                or any(t.topic_id == f.topic_id for t in r.topics),
                f.hitl_reviewed is None or r.hitl_reviewed == f.hitl_reviewed,
            ]
            if all(checks):
                out.append(r)
        return out

    def facets(
        self, f: ReviewFilters
    ) -> tuple[int, dict[str, list[FacetCount]]]:
        rows = self._filtered(f)
        counters: dict[str, Counter[str]] = {
            d: Counter()
            for d in (
                "bank",
                "month",
                "sentiment",
                "stars",
                "family",
                "flag_update",
                "flag_security",
                "topic",
                "hitl",
            )
        }
        labels: dict[str, str | None] = {}
        for r in rows:
            counters["bank"][r.bank_id] += 1
            counters["month"][r.fecha.strftime("%Y-%m")] += 1
            counters["sentiment"][r.sentiment] += 1
            counters["stars"][str(r.estrellas)] += 1
            counters["family"].update(r.families)
            if r.flag_update is not None:
                counters["flag_update"]["si" if r.flag_update else "no"] += 1
            if r.flag_security is not None:
                counters["flag_security"][
                    "si" if r.flag_security else "no"
                ] += 1
            for t in r.topics:
                counters["topic"][str(t.topic_id)] += 1
                labels[str(t.topic_id)] = t.name
            counters["hitl"]["si" if r.hitl_reviewed else "no"] += 1
        by = {
            dim: [
                FacetCount(
                    key=k, n=n, label=labels.get(k) if dim == "topic" else None
                )
                for k, n in c.items()
            ]
            for dim, c in counters.items()
            if c
        }
        return len(rows), _ordered(by)

    def page(
        self, f: ReviewFilters, sort: SortKey, page: int, page_size: int
    ) -> tuple[list[ReviewRow], int]:
        rows = self._filtered(f)
        keys: dict[str, Any] = {
            "fecha_desc": lambda r: (-r.fecha.toordinal(), r.id_resena),
            "confidence_asc": lambda r: (
                r.confidence is None,
                r.confidence or 0,
                -r.fecha.toordinal(),
                r.id_resena,
            ),
            "estrellas_asc": lambda r: (
                r.estrellas,
                -r.fecha.toordinal(),
                r.id_resena,
            ),
        }
        rows.sort(key=keys[sort])
        start = (page - 1) * page_size
        return rows[start : start + page_size], len(rows)

    def detail(
        self, bank_id: str, id_resena: str
    ) -> tuple[ReviewRow, str | None] | None:
        for item in self.reviews:
            if item.row.bank_id == bank_id and item.row.id_resena == id_resena:
                return item.row, item.prompt_version
        return None

    def hitl_reviews(self, id_resena: str) -> list[HitlReviewRef]:
        for item in self.reviews:
            if item.row.id_resena == id_resena:
                return list(item.hitl or [])
        return []

    def stored_explanation(self, text_key: str) -> ExplanationRef | None:
        return self.explanations.get(text_key)

    def vector_search(
        self,
        embedding: Sequence[float],
        banks: Sequence[str],
        from_month: date,
        k: int,
        stats: dict[str, int],
    ) -> list[VectorHit]:
        stats["bytes_billed"] = self.bytes_billed
        best: dict[tuple[str, str], float] = {}
        for item in self.reviews:
            r = item.row
            if (
                item.embedding is None
                or r.bank_id not in banks
                or r.fecha < from_month
            ):
                continue
            key = (r.text_key, r.bank_id)
            d = _cosine_distance(embedding, item.embedding)
            best[key] = min(d, best.get(key, 2.0))
        ranked = sorted(best.items(), key=lambda kv: (kv[1], kv[0]))
        return [VectorHit(t, b, d) for (t, b), d in ranked[:k]]

    def groups(
        self, hits: Sequence[VectorHit], date_from: date
    ) -> dict[tuple[str, str], Group]:
        out: dict[tuple[str, str], Group] = {}
        for h in hits:
            same = sorted(
                (
                    i.row
                    for i in self.reviews
                    if i.row.text_key == h.text_key
                    and i.row.bank_id == h.bank_id
                    and i.row.fecha >= date_from
                ),
                key=lambda r: r.fecha,
                reverse=True,
            )
            if same:
                out[(h.text_key, h.bank_id)] = Group(len(same), same[0])
        return out


def _cosine_distance(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return 1.0 - dot / norm if norm else 1.0
