"""Lecturas del cockpit: ``Protocol``, BigQuery y versión en memoria."""

# ruff: noqa: S608
# Los nombres de tablas salen de ``qualified`` (lista cerrada); los valores
# viajan siempre como parámetros.

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from api_backend.bq.names import qualified
from api_backend.bq.reader import BigQueryReader, Param
from api_backend.sections.kpis.schemas import (
    BANK_IDS,
    DailyPoint,
    ModelChange,
    PromptChange,
)
from api_backend.settings import ApiSettings

FAMILY_METRIC_PREFIX = "family_"
UPDATE_METRIC = "flag_update_share"
FAMILY_CODES = (
    "AC",
    "FA",
    "LE",
    "TR",
    "DI",
    "PR",
    "AT",
    "DV",
    "UX",
    "CO",
    "OT",
)
MATRIX_CLASSES = ("NEG", "NEU", "POS")


@dataclass(frozen=True)
class KpiRow:
    """Última corrida de un (métrica, banco, periodo, método)."""

    metric: str
    bank_id: str
    period: str
    method: str
    estimate: float
    ci_low: float | None
    ci_high: float | None
    n_gold: int | None
    n_unlabeled: int | None
    model_version: str
    gold_version: str | None


@dataclass(frozen=True)
class ThemeRow:
    """Un renglón de ``daily_topic_labels``."""

    bank_id: str
    dia: date
    n_neg: int
    tipo: str
    rango: int
    codigo: str
    nombre: str | None
    filas: int
    participacion: float
    habitual: float | None
    aspects_prompt_version: str | None
    topic_model_version: str | None


@dataclass(frozen=True)
class FamilyLevel:
    bank_id: str
    period: str
    family: str
    neg_count: int
    base: int


@dataclass(frozen=True)
class FamilyDrift:
    bank_id: str
    period: str
    metric: str
    z: float | None
    threshold: float | None
    alert: bool | None


@dataclass(frozen=True)
class TopicRow:
    bank_id: str
    period: str
    topic_id: int
    nombre: str
    audience: str
    families: list[str]
    filas: int
    base: int
    topic_model_version: str


@dataclass(frozen=True)
class VersionTotals:
    version_app: str | None
    filas: int
    neg: int
    neg_labeled: int
    neg_u: int
    first_seen: date
    last_seen: date


@dataclass(frozen=True)
class VersionFamily:
    version_app: str | None
    family: str
    n: int


@dataclass(frozen=True)
class VersionDayRaw:
    dia: date
    version_app: str | None
    n: int


class KpisRepository(Protocol):
    def kpi_rows(
        self, metrics: Sequence[str], banks: Sequence[str]
    ) -> list[KpiRow]: ...

    def open_alerts(self) -> dict[str, int]: ...

    def daily(
        self, banks: Sequence[str], date_from: date, date_to: date
    ) -> list[DailyPoint]: ...

    def daily_themes(self, bank: str, day: date) -> list[ThemeRow]: ...

    def family_levels(self, banks: Sequence[str]) -> list[FamilyLevel]: ...

    def family_drift(self, banks: Sequence[str]) -> list[FamilyDrift]: ...

    def prompt_changes(self) -> list[PromptChange]: ...

    def topic_months(self, banks: Sequence[str]) -> list[TopicRow]: ...

    def version_totals(self, bank: str) -> list[VersionTotals]: ...

    def version_families(self, bank: str) -> list[VersionFamily]: ...

    def model_changes(self) -> list[ModelChange]: ...

    def version_daily(
        self, bank: str, date_from: date, date_to: date, sentiment: str
    ) -> list[VersionDayRaw]: ...


# Última etiqueta de aspectos de cada reseña.
_LATEST_ASPECTS = (
    "SELECT id_resena, families, flag_update, prompt_version FROM {aspects} "
    "WHERE TRUE QUALIFY ROW_NUMBER() OVER "
    "(PARTITION BY id_resena ORDER BY labeled_at DESC) = 1"
)


class BigQueryKpisRepository:
    def __init__(self, reader: BigQueryReader, settings: ApiSettings) -> None:
        self._reader = reader
        self._project = settings.gcp_project_id
        self._dataset = settings.bq_dataset_id

    def _table(self, name: str) -> str:
        return qualified(name, self._project, self._dataset)

    def _rows(
        self, sql: str, params: Sequence[Param], name: str
    ) -> list[dict[str, object]]:
        return [
            dict(r)
            for r in self._reader.rows(sql, params, name=name, cache=True)
        ]

    def kpi_rows(
        self, metrics: Sequence[str], banks: Sequence[str]
    ) -> list[KpiRow]:
        sql = (
            "SELECT metric, bank_id, period, method, estimate, ci_low, "  # nosec B608
            "ci_high, n_gold, n_unlabeled, model_version, gold_version "
            f"FROM {self._table('kpi_estimates')} "
            "WHERE metric IN UNNEST(@metrics) AND bank_id IN UNNEST(@banks) "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY metric, bank_id, "
            "period, method ORDER BY computed_at DESC) = 1"
        )
        rows = self._rows(
            sql,
            [
                Param("metrics", "STRING", tuple(metrics), array=True),
                Param("banks", "STRING", tuple(banks), array=True),
            ],
            "kpis_estimates",
        )
        return [KpiRow(**r) for r in rows]  # type: ignore[arg-type]

    def open_alerts(self) -> dict[str, int]:
        sql = (
            "SELECT bank_id, COUNT(*) AS n FROM "  # nosec B608
            f"{self._table('drift_alerts_current')} "
            "WHERE status = 'open' GROUP BY bank_id"
        )
        return {
            str(r["bank_id"]): int(r["n"])  # type: ignore[call-overload]
            for r in self._rows(sql, [], "kpis_open_alerts")
        }

    def daily(
        self, banks: Sequence[str], date_from: date, date_to: date
    ) -> list[DailyPoint]:
        # El rango se compara con ``fecha`` sin envolverla en una función,
        # para que la tabla pueda podar particiones.
        sql = (
            "SELECT bank_id, DATE(fecha) AS dia, COUNT(*) AS filas, "  # nosec B608
            "COUNTIF(sentiment IN ('NEG', 'NEU', 'POS')) AS predichas, "
            "COUNTIF(sentiment = 'NEG') AS neg, "
            "COUNTIF(sentiment = 'NEU') AS neu, "
            "COUNTIF(sentiment = 'POS') AS pos, "
            "COUNTIF(sentiment = 'NO_PREDICTED') AS no_predichas, "
            "AVG(IF(sentiment IN ('NEG', 'NEU', 'POS'), "
            "estrellas - CASE sentiment WHEN 'NEG' THEN 1 WHEN 'NEU' THEN 3 "
            "ELSE 5 END, NULL)) AS gap_crudo, "
            "COUNTIF(texto_peor) AS texto_peor, "
            "COUNTIF(texto_mejor) AS texto_mejor, "
            "COUNTIF(sentiment = 'NEG' AND estrellas >= 4) AS neg_4_5 "
            f"FROM {self._table('review_predictions_current')} "
            "WHERE fecha >= TIMESTAMP(@date_from) "
            "AND fecha < TIMESTAMP(DATE_ADD(@date_to, INTERVAL 1 DAY)) "
            "AND bank_id IN UNNEST(@banks) "
            "GROUP BY bank_id, dia ORDER BY bank_id, dia"
        )
        rows = self._rows(
            sql,
            [
                Param("banks", "STRING", tuple(banks), array=True),
                Param("date_from", "DATE", date_from),
                Param("date_to", "DATE", date_to),
            ],
            "kpis_daily",
        )
        return [DailyPoint.model_validate(r) for r in rows]

    def daily_themes(self, bank: str, day: date) -> list[ThemeRow]:
        sql = (
            "SELECT bank_id, dia, n_neg, tipo, rango, codigo, nombre, filas, "  # nosec B608
            "participacion, habitual, aspects_prompt_version, "
            f"topic_model_version FROM {self._table('daily_topic_labels')} "
            "WHERE bank_id = @bank AND dia = @day ORDER BY tipo, rango"
        )
        rows = self._rows(
            sql,
            [Param("bank", "STRING", bank), Param("day", "DATE", day)],
            "kpis_daily_themes",
        )
        return [ThemeRow(**r) for r in rows]  # type: ignore[arg-type]

    def _negatives(self) -> str:
        return (
            "SELECT id_resena, bank_id, "  # nosec B608
            "FORMAT_DATE('%Y-%m', DATE(fecha)) AS period "
            f"FROM {self._table('review_predictions_current')} "
            "WHERE sentiment = 'NEG' AND palabras >= 2 "
            "AND bank_id IN UNNEST(@banks)"
        )

    def _aspects(self) -> str:
        return _LATEST_ASPECTS.format(aspects=self._table("review_aspects"))

    def family_levels(self, banks: Sequence[str]) -> list[FamilyLevel]:
        sql = (
            f"WITH neg AS ({self._negatives()}), "  # nosec B608
            f"aspects AS ({self._aspects()}), "
            "joined AS (SELECT n.bank_id, n.period, a.families, a.flag_update "
            "FROM neg AS n JOIN aspects AS a USING (id_resena)), "
            "totals AS (SELECT bank_id, period, COUNT(*) AS base, "
            "COUNTIF(flag_update) AS u FROM joined GROUP BY bank_id, period), "
            "fam AS (SELECT bank_id, period, family, COUNT(*) AS n "
            "FROM joined, UNNEST(families) AS family "
            "GROUP BY bank_id, period, family) "
            "SELECT f.bank_id, f.period, f.family, f.n AS neg_count, b.base "
            "FROM fam AS f JOIN totals AS b USING (bank_id, period) "
            "UNION ALL SELECT bank_id, period, 'u', u, base FROM totals"
        )
        rows = self._rows(
            sql,
            [Param("banks", "STRING", tuple(banks), array=True)],
            "kpis_family_levels",
        )
        return [FamilyLevel(**r) for r in rows]  # type: ignore[arg-type]

    def family_drift(self, banks: Sequence[str]) -> list[FamilyDrift]:
        sql = (
            "SELECT bank_id, SUBSTR(CAST(period AS STRING), 1, 7) AS period, "  # nosec B608
            "metric, z, threshold, alert "
            f"FROM {self._table('drift_metrics')} "
            f"WHERE (STARTS_WITH(metric, '{FAMILY_METRIC_PREFIX}') "
            f"OR metric = '{UPDATE_METRIC}') AND bank_id IN UNNEST(@banks) "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY bank_id, period, metric "
            "ORDER BY computed_at DESC) = 1"
        )
        rows = self._rows(
            sql,
            [Param("banks", "STRING", tuple(banks), array=True)],
            "kpis_family_drift",
        )
        return [FamilyDrift(**r) for r in rows]  # type: ignore[arg-type]

    def prompt_changes(self) -> list[PromptChange]:
        sql = (
            "SELECT prompt_version, MIN(labeled_at) AS first_labeled_at "  # nosec B608
            f"FROM {self._table('review_aspects')} "
            "GROUP BY prompt_version ORDER BY first_labeled_at"
        )
        return [
            PromptChange.model_validate(r)
            for r in self._rows(sql, [], "kpis_prompt_changes")
        ]

    def topic_months(self, banks: Sequence[str]) -> list[TopicRow]:
        sql = (
            "WITH tv AS (SELECT topic_model_version FROM "  # nosec B608
            f"{self._table('topic_model_current')}), "
            "useful AS (SELECT c.topic_id, c.curated_name, c.audience, "
            "c.families, c.topic_model_version FROM "
            f"{self._table('curation_topics')} AS c "
            "JOIN tv USING (topic_model_version) WHERE TRUE "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY c.topic_id "
            "ORDER BY c.curated_at DESC) = 1), "
            f"neg AS ({self._negatives()}), "
            "base AS (SELECT bank_id, period, COUNT(*) AS base FROM neg "
            "GROUP BY bank_id, period), "
            "counts AS (SELECT n.bank_id, n.period, t.topic_id, "
            "COUNT(DISTINCT n.id_resena) AS filas FROM "
            f"{self._table('topic_assignments')} AS t "
            "JOIN tv USING (topic_model_version) "
            "JOIN neg AS n USING (id_resena) "
            "GROUP BY n.bank_id, n.period, t.topic_id) "
            "SELECT c.bank_id, c.period, c.topic_id, u.curated_name AS nombre, "
            "u.audience, u.families, c.filas, b.base, "
            "u.topic_model_version FROM counts AS c "
            "JOIN useful AS u USING (topic_id) "
            "JOIN base AS b USING (bank_id, period) "
            "WHERE u.audience IN ('producto', 'ingenieria')"
        )
        rows = self._rows(
            sql,
            [Param("banks", "STRING", tuple(banks), array=True)],
            "kpis_topic_months",
        )
        return [
            TopicRow(**{**r, "families": list(r["families"])}) for r in rows
        ]  # type: ignore[arg-type, call-overload]

    def version_totals(self, bank: str) -> list[VersionTotals]:
        sql = (
            "SELECT p.version_app, "  # nosec B608
            "COUNTIF(p.sentiment IN ('NEG', 'NEU', 'POS')) AS filas, "
            "COUNTIF(p.sentiment = 'NEG') AS neg, "
            "COUNTIF(p.sentiment = 'NEG' AND p.palabras >= 2 "
            "AND a.flag_update IS NOT NULL) AS neg_labeled, "
            "COUNTIF(p.sentiment = 'NEG' AND p.palabras >= 2 "
            "AND a.flag_update) AS neg_u, "
            "MIN(DATE(p.fecha)) AS first_seen, "
            "MAX(DATE(p.fecha)) AS last_seen "
            f"FROM {self._table('review_predictions_current')} AS p "
            f"LEFT JOIN ({self._aspects()}) AS a USING (id_resena) "
            "WHERE p.bank_id = @bank GROUP BY p.version_app"
        )
        rows = self._rows(
            sql, [Param("bank", "STRING", bank)], "kpis_version_totals"
        )
        return [VersionTotals(**r) for r in rows]  # type: ignore[arg-type]

    def version_families(self, bank: str) -> list[VersionFamily]:
        sql = (
            "SELECT p.version_app, family, COUNT(*) AS n "  # nosec B608
            f"FROM {self._table('review_predictions_current')} AS p "
            f"JOIN ({self._aspects()}) AS a USING (id_resena), "
            "UNNEST(a.families) AS family "
            "WHERE p.bank_id = @bank AND p.sentiment = 'NEG' "
            "AND p.palabras >= 2 "
            "GROUP BY p.version_app, family"
        )
        rows = self._rows(
            sql, [Param("bank", "STRING", bank)], "kpis_version_families"
        )
        return [VersionFamily(**r) for r in rows]  # type: ignore[arg-type]

    def version_daily(
        self, bank: str, date_from: date, date_to: date, sentiment: str
    ) -> list[VersionDayRaw]:
        sql = (
            "SELECT DATE(fecha) AS dia, version_app, COUNT(*) AS n "  # nosec B608
            f"FROM {self._table('review_predictions_current')} "
            "WHERE bank_id = @bank AND fecha >= TIMESTAMP(@date_from) "
            "AND fecha < TIMESTAMP(DATE_ADD(@date_to, INTERVAL 1 DAY)) "
            "AND ((@sentiment = 'ALL' AND sentiment IN ('NEG', 'NEU', 'POS')) "
            "OR sentiment = @sentiment) "
            "GROUP BY dia, version_app"
        )
        rows = self._rows(
            sql,
            [
                Param("bank", "STRING", bank),
                Param("date_from", "DATE", date_from),
                Param("date_to", "DATE", date_to),
                Param("sentiment", "STRING", sentiment),
            ],
            "kpis_version_daily",
        )
        return [VersionDayRaw(**r) for r in rows]  # type: ignore[arg-type]

    def model_changes(self) -> list[ModelChange]:
        sql = (
            "SELECT model_version, promoted_at "  # nosec B608
            f"FROM {self._table('model_versions')} "
            "WHERE TRUE QUALIFY ROW_NUMBER() OVER (PARTITION BY "
            "model_version ORDER BY recorded_at DESC) = 1 "
            "AND promoted_at IS NOT NULL ORDER BY promoted_at"
        )
        return [
            ModelChange.model_validate(r)
            for r in self._rows(sql, [], "kpis_model_changes")
        ]


@dataclass
class InMemoryKpisRepository:
    """Doble de pruebas y de ``PORTAL_DATA=fixtures``."""

    kpis: list[KpiRow] = field(default_factory=list)
    alerts: dict[str, int] = field(default_factory=dict)
    daily_rows: list[DailyPoint] = field(default_factory=list)
    themes: list[ThemeRow] = field(default_factory=list)
    levels: list[FamilyLevel] = field(default_factory=list)
    drift: list[FamilyDrift] = field(default_factory=list)
    prompts: list[PromptChange] = field(default_factory=list)
    topics: list[TopicRow] = field(default_factory=list)
    totals: dict[str, list[VersionTotals]] = field(default_factory=dict)
    version_fams: dict[str, list[VersionFamily]] = field(default_factory=dict)
    models: list[ModelChange] = field(default_factory=list)
    version_days: dict[str, list[VersionDayRaw]] = field(default_factory=dict)

    def kpi_rows(
        self, metrics: Sequence[str], banks: Sequence[str]
    ) -> list[KpiRow]:
        return [
            r for r in self.kpis if r.metric in metrics and r.bank_id in banks
        ]

    def open_alerts(self) -> dict[str, int]:
        return dict(self.alerts)

    def daily(
        self, banks: Sequence[str], date_from: date, date_to: date
    ) -> list[DailyPoint]:
        return [
            r
            for r in self.daily_rows
            if r.bank_id in banks and date_from <= r.dia <= date_to
        ]

    def daily_themes(self, bank: str, day: date) -> list[ThemeRow]:
        return [t for t in self.themes if t.bank_id == bank and t.dia == day]

    def family_levels(self, banks: Sequence[str]) -> list[FamilyLevel]:
        return [r for r in self.levels if r.bank_id in banks]

    def family_drift(self, banks: Sequence[str]) -> list[FamilyDrift]:
        return [r for r in self.drift if r.bank_id in banks]

    def prompt_changes(self) -> list[PromptChange]:
        return list(self.prompts)

    def topic_months(self, banks: Sequence[str]) -> list[TopicRow]:
        return [r for r in self.topics if r.bank_id in banks]

    def version_totals(self, bank: str) -> list[VersionTotals]:
        return list(self.totals.get(bank, []))

    def version_families(self, bank: str) -> list[VersionFamily]:
        return list(self.version_fams.get(bank, []))

    def model_changes(self) -> list[ModelChange]:
        return list(self.models)

    def version_daily(
        self, bank: str, date_from: date, date_to: date, sentiment: str
    ) -> list[VersionDayRaw]:
        # Los datos de prueba no distinguen el sentimiento.
        return [
            r
            for r in self.version_days.get(bank, [])
            if date_from <= r.dia <= date_to
        ]


def _months_back(today: date, n: int) -> list[str]:
    out, year, month = [], today.year, today.month
    for _ in range(n):
        month -= 1
        if month == 0:
            year, month = year - 1, 12
        out.append(f"{year}-{month:02d}")
    return sorted(out)


def sample_repository(now: datetime | None = None) -> InMemoryKpisRepository:
    """Datos sintéticos (sin texto de reseñas) relativos a la fecha actual."""
    now = now or datetime.now(UTC)
    today = now.date()
    rng = random.Random(7)  # noqa: S311  # nosec B311
    repo = InMemoryKpisRepository(alerts={"AZTECA": 1, "NUBANK": 2})
    months = _months_back(today, 14)
    levels = {b: 0.12 + 0.03 * i for i, b in enumerate(BANK_IDS)}

    for bank in BANK_IDS:
        base_neg = levels[bank]
        for k, period in enumerate(months):
            neg = base_neg + 0.01 * rng.uniform(-1, 1)
            gap = -(0.2 + base_neg) + 0.05 * rng.uniform(-1, 1)
            cells = _sample_matrix(neg)
            metrics = {
                "neg": neg,
                "gap_estrellas": gap,
                "texto_peor": 0.2 + neg / 3,
                "texto_mejor": 0.1 + neg / 6,
                **cells,
            }
            for metric, value in metrics.items():
                spread = 0.05 if metric == "gap_estrellas" else 0.015
                common = {
                    "metric": metric,
                    "bank_id": bank,
                    "period": period,
                    "model_version": "sintetico_v1",
                    "gold_version": "gold_sintetico",
                }
                repo.kpis.append(
                    KpiRow(
                        method="ppi",
                        estimate=value,
                        ci_low=value - spread,
                        ci_high=value + spread,
                        n_gold=1200,
                        n_unlabeled=18_000,
                        **common,  # type: ignore[arg-type]
                    )
                )
                repo.kpis.append(
                    KpiRow(
                        method="raw",
                        estimate=value * 1.05,
                        ci_low=None,
                        ci_high=None,
                        n_gold=None,
                        n_unlabeled=18_000,
                        **common,  # type: ignore[arg-type]
                    )
                )
            shares = _sample_shares(rng, k)
            for family, share in shares.items():
                repo.levels.append(
                    FamilyLevel(bank, period, family, round(share * 800), 800)
                )
                repo.drift.append(
                    FamilyDrift(
                        bank,
                        period,
                        UPDATE_METRIC
                        if family == "u"
                        else FAMILY_METRIC_PREFIX + family,
                        rng.uniform(-1.5, 2.5)
                        + (
                            4.5
                            if (bank, k, family) == ("AZTECA", 12, "AC")
                            else 0
                        ),
                        4.0 if k >= 7 else None,
                        False,
                    )
                )
            for topic_id, (name, audience) in enumerate(_SAMPLE_TOPICS):
                repo.topics.append(
                    TopicRow(
                        bank,
                        period,
                        topic_id,
                        name,
                        audience,
                        ["FA"],
                        round(
                            800
                            * (0.04 + 0.01 * topic_id)
                            * rng.uniform(0.8, 1.2)
                        ),
                        800,
                        "topics_sintetico",
                    )
                )
        for offset in range(120, 0, -1):
            day = today - timedelta(days=offset)
            predicted = rng.randint(80, 140)
            neg = round(predicted * (base_neg + rng.uniform(-0.03, 0.03)))
            neu = round(predicted * 0.1)
            repo.daily_rows.append(
                DailyPoint(
                    bank_id=bank,
                    dia=day,
                    filas=predicted + 3,
                    predichas=predicted,
                    neg=neg,
                    neu=neu,
                    pos=predicted - neg - neu,
                    no_predichas=3,
                    gap_crudo=-(0.2 + base_neg) + rng.uniform(-0.1, 0.1),
                    texto_peor=round(predicted * 0.2),
                    texto_mejor=round(predicted * 0.1),
                    neg_4_5=round(neg * 0.1),
                )
            )
            repo.themes.extend(_sample_themes(rng, bank, day, neg))
        repo.version_days[bank] = _sample_version_days(bank, today)
        repo.totals[bank], repo.version_fams[bank] = _sample_versions(
            bank, today
        )
    repo.prompts = [
        PromptChange(
            prompt_version="aspects_v2",
            first_labeled_at=now - timedelta(days=330),
        ),
        PromptChange(
            prompt_version="aspects_v2_1",
            first_labeled_at=now - timedelta(days=150),
        ),
    ]
    repo.models = [
        ModelChange(
            model_version="sintetico_v1", promoted_at=now - timedelta(days=60)
        )
    ]
    return repo


_SAMPLE_TOPICS = [
    ("Inicio de sesión que falla", "ingenieria"),
    ("Transferencias que no llegan", "producto"),
    ("Lentitud al abrir la app", "ingenieria"),
    ("Cargos no reconocidos", "producto"),
    ("Cambios en la pantalla de inicio", "producto"),
]


def _sample_matrix(neg: float) -> dict[str, float]:
    weights = {
        ("NEG", "NEG"): 0.9 * neg,
        ("NEG", "NEU"): 0.03,
        ("NEG", "POS"): 0.01,
        ("NEU", "NEG"): 0.04,
        ("NEU", "NEU"): 0.05,
        ("NEU", "POS"): 0.02,
        ("POS", "NEG"): 0.1 * neg + 0.01,
        ("POS", "NEU"): 0.1,
        ("POS", "POS"): 0.0,
    }
    weights[("POS", "POS")] = 1 - sum(
        v for k, v in weights.items() if k != ("POS", "POS")
    )
    return {f"estrellas_{a}_texto_{b}": v for (a, b), v in weights.items()}


def _sample_shares(rng: random.Random, k: int) -> dict[str, float]:
    shares = {
        code: 0.02 + 0.02 * ((i * 7 + k) % 5) + rng.uniform(0, 0.01)
        for i, code in enumerate(
            ("AC", "FA", "LE", "TR", "DI", "PR", "AT", "DV", "UX", "CO", "OT")
        )
    }
    shares["u"] = 0.15 + rng.uniform(-0.02, 0.02)
    return shares


def _sample_themes(
    rng: random.Random, bank: str, day: date, n_neg: int
) -> list[ThemeRow]:
    rows: list[ThemeRow] = []
    names = {
        "AC": "Acceso y autenticación",
        "FA": "Falla general de la app",
        "LE": "Lentitud general",
        "TR": "Transferencias y pagos",
        "DI": "Dinero y cargos",
    }
    for rango, (codigo, nombre) in enumerate(names.items(), start=1):
        share = max(0.02, 0.3 - 0.05 * rango + rng.uniform(-0.03, 0.03))
        rows.append(
            ThemeRow(
                bank,
                day,
                n_neg,
                "familia",
                rango,
                codigo,
                nombre,
                round(share * n_neg),
                share,
                0.3 - 0.05 * rango,
                "aspects_v2_1",
                None,
            )
        )
    for rango, (name, _) in enumerate(_SAMPLE_TOPICS, start=1):
        share = max(0.02, 0.25 - 0.04 * rango + rng.uniform(-0.03, 0.03))
        rows.append(
            ThemeRow(
                bank,
                day,
                n_neg,
                "topico",
                rango,
                str(rango - 1),
                name,
                round(share * n_neg),
                share,
                0.25 - 0.04 * rango,
                None,
                "topics_sintetico",
            )
        )
    return rows


def _sample_versions(
    bank: str, today: date
) -> tuple[list[VersionTotals], list[VersionFamily]]:
    totals: list[VersionTotals] = []
    families: list[VersionFamily] = []
    releases = ["5.1.0", "5.2.0", "5.3.1", "5.4.0", "5.5.2", "5.6.0"]
    for i, release in enumerate(releases):
        filas = 2000 - 150 * i
        neg = round(filas * (0.15 + 0.01 * i))
        first = today - timedelta(days=30 * (len(releases) - i) + 20)
        totals.append(
            VersionTotals(
                release,
                filas,
                neg,
                neg,
                round(neg * 0.18),
                first,
                first + timedelta(days=28),
            )
        )
        families.append(VersionFamily(release, "FA", round(neg * 0.3)))
        families.append(VersionFamily(release, "AC", round(neg * 0.2)))
        families.append(VersionFamily(release, "LE", round(neg * 0.1)))
    totals.append(
        VersionTotals(
            "5.0.9",
            120,
            20,
            20,
            3,
            today - timedelta(days=300),
            today - timedelta(days=290),
        )
    )
    totals.append(
        VersionTotals(
            None,
            150,
            30,
            30,
            5,
            today - timedelta(days=200),
            today - timedelta(days=10),
        )
    )
    totals.append(
        VersionTotals(
            "2.6.2 - BETA",
            30,
            5,
            5,
            1,
            today - timedelta(days=100),
            today - timedelta(days=90),
        )
    )
    del bank
    return totals, families


def _sample_version_days(bank: str, today: date) -> list[VersionDayRaw]:
    """Cuatro versiones que se relevan cada ~25 días, más versiones chicas."""
    rows: list[VersionDayRaw] = []
    releases = ["5.1.0", "5.2.0", "5.3.1", "5.4.0"]
    for offset in range(120, 0, -1):
        day = today - timedelta(days=offset)
        current = releases[min((120 - offset) // 30, len(releases) - 1)]
        rows.append(VersionDayRaw(day, current, 30))
        rows.append(VersionDayRaw(day, "5.0.9", 4))
        rows.append(VersionDayRaw(day, "UNKNOWN", 2))
    del bank
    return rows
