"""KPI del cockpit por banco y mes con PPI → ``kpi_estimates``.

Cada KPI (``voc_nlp.ppi.targets``: ``neg``, ``gap_estrellas``,
``texto_peor``, ``texto_mejor`` y las 9 celdas de la matriz estrellas ×
texto) se guarda dos veces por banco y mes:

* ``raw``: la media de la predicción vigente en las reseñas del mes;
* ``ppi``: la misma media corregida con el oro *dev* aleatorio
  (``gold_labels``, pesos 1 / π) y su intervalo del 95 %.

El oro tiene ~200 reseñas por banco repartidas en toda su historia, así que
casi no hay oro dentro de un mes. La corrección (y − λ·f) se estima con
todo el oro *dev* del banco y se aplica a las predicciones del mes
(decisión del autor, 2026-10-24): supone que el sesgo del modelo en un banco
es estable en el tiempo, lo que vigilan el κ trimestral (``quality``) y la
deriva (``drift_job``). Con la escala de 1 a 5 del *gap* y el PPI de la
calibración (``docs/analytics/calibration/calibration_report.md``).

* **Evaluables:** en el corpus, solo reseñas con predicción ``NEG``, ``NEU``
  o ``POS``. En el oro, una reseña sin predicción de esas clases cuenta como
  ``NEU`` (como en la evaluación del modelo). Las reseñas del oro no entran
  al corpus.
* **Meses:** el mes en curso y el anterior en cada corrida, más los meses
  a los que les falta alguna serie del modelo (``raw`` o la ``ppi`` de una
  versión del oro): el primer monitor llena la historia. Cada corrida
  escribe filas nuevas con su ``computed_at``: el cockpit lee la última.
* **Versiones del oro:** cada ``gold_version`` del *dev* da su serie ``ppi``
  (el oro de los experimentos y, cuando existan, las versiones con
  revisiones del HITL).
"""

import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import numpy as np
from voc_common.analytics_codes import KpiMethod
from voc_common.operations_v3 import KpiEstimate
from voc_nlp.ppi import SCORE, Estimate, ppi_mean, targets

from ml_inference.bq_io import StagingMergeWriter, query_rows, render
from ml_inference.monitor.samples import last_closed_period, period_of

log = logging.getLogger(__name__)

CLASSES: Final = tuple(SCORE)
# La predicción que no es una de las tres clases cuenta como NEU en el oro.
FALLBACK_CLASS: Final = "NEU"
METRICS: Final = tuple(targets([3], [FALLBACK_CLASS]))
KPI_KEY: Final = (
    "metric",
    "bank_id",
    "period",
    "method",
    "model_version",
    "gold_version",
    "computed_at",
)

GOLD_SQL: Final = """
SELECT g.gold_version, g.label, g.weight, p.bank_id, p.estrellas,
  p.sentiment
FROM `${ds}.gold_labels` AS g
JOIN `${ds}.review_predictions_current` AS p USING (id_resena)
WHERE g.split = 'dev' AND g.task = 'sentiment'
  AND g.label IS NOT NULL AND g.weight IS NOT NULL
"""

# Conteos por banco × mes × estrellas × clase: sin filas por reseña.
CORPUS_SQL: Final = """
SELECT p.bank_id, FORMAT_TIMESTAMP('%Y-%m', p.fecha, 'UTC') AS period,
  p.estrellas, p.sentiment, COUNT(*) AS n
FROM `${ds}.review_predictions_current` AS p
WHERE p.sentiment IN ('NEG', 'NEU', 'POS')
  AND p.id_resena NOT IN (
    SELECT id_resena FROM `${ds}.gold_labels`
    WHERE split = 'dev' AND id_resena IS NOT NULL
  )
GROUP BY 1, 2, 3, 4
"""

DONE_SQL: Final = """
SELECT DISTINCT bank_id, period, method, gold_version
FROM `${ds}.kpi_estimates`
WHERE model_version = @model_version
"""


@dataclass(frozen=True)
class GoldRow:
    """Reseña del oro *dev* con su predicción vigente (sin texto)."""

    bank_id: str
    stars: int
    label: str
    predicted: str
    weight: float


@dataclass(frozen=True)
class CorpusCell:
    """Reseñas predichas de un banco en un mes, como conteos."""

    stars: tuple[int, ...]
    predicted: tuple[str, ...]
    counts: tuple[int, ...]

    def expand(self) -> tuple[list[int], list[str]]:
        stars = np.repeat(np.array(self.stars), self.counts).tolist()
        pred = np.repeat(np.array(self.predicted), self.counts).tolist()
        return stars, pred

    @property
    def size(self) -> int:
        return sum(self.counts)


Series = tuple[str, str, str, str | None]
"""(banco, mes, método, versión del oro) de una serie de ``kpi_estimates``."""


def expected_series(
    corpus: Mapping[tuple[str, str], CorpusCell],
    gold: Mapping[str, Sequence[GoldRow]],
) -> set[Series]:
    """Series que deben existir: ``raw`` siempre, ``ppi`` si hay oro."""
    banks = {
        version: {g.bank_id for g in rows} for version, rows in gold.items()
    }
    out: set[Series] = set()
    for (bank, period), cell in corpus.items():
        if not cell.size:
            continue
        out.add((bank, period, KpiMethod.RAW.value, None))
        out |= {
            (bank, period, KpiMethod.PPI.value, version)
            for version, with_gold in banks.items()
            if bank in with_gold
        }
    return out


def months_to_compute(
    now: datetime, expected: Iterable[Series], done: Iterable[Series]
) -> list[str]:
    """Mes en curso, el anterior y los meses a los que les falta una serie."""
    today = now.astimezone(UTC).date()
    recent = {period_of(today, "monthly"), last_closed_period(now, "monthly")}
    expected = set(expected)
    available = {period for _, period, _, _ in expected}
    missing = {period for _, period, _, _ in expected - set(done)}
    return sorted((available & recent) | missing)


def _row(
    metric: str,
    bank_id: str,
    period: str,
    method: KpiMethod,
    estimate: float,
    n_unlabeled: int,
    model_version: str,
    now: datetime,
    ppi: Estimate | None = None,
    gold_version: str | None = None,
) -> KpiEstimate:
    ci = (None, None) if ppi is None else ppi.ci
    return KpiEstimate(
        metric=metric,
        bank_id=bank_id,
        period=period,
        method=method,
        estimate=estimate,
        ci_low=ci[0],
        ci_high=ci[1],
        n_gold=None if ppi is None else ppi.n_gold,
        n_unlabeled=n_unlabeled,
        model_version=model_version,
        gold_version=gold_version,
        computed_at=now,
    )


def raw_kpis(
    bank_id: str,
    period: str,
    cell: CorpusCell,
    model_version: str,
    now: datetime,
) -> list[KpiEstimate]:
    """Medias crudas de la predicción en el mes."""
    values = targets(*cell.expand())
    return [
        _row(
            metric,
            bank_id,
            period,
            KpiMethod.RAW,
            float(values[metric].mean()),
            cell.size,
            model_version,
            now,
        )
        for metric in METRICS
    ]


def ppi_kpis(
    bank_id: str,
    period: str,
    gold: Sequence[GoldRow],
    cell: CorpusCell,
    model_version: str,
    gold_version: str,
    now: datetime,
) -> list[KpiEstimate]:
    """PPI del mes con la corrección del oro *dev* del banco."""
    stars = [g.stars for g in gold]
    y = targets(stars, [g.label for g in gold])
    f = targets(stars, [g.predicted for g in gold])
    fu = targets(*cell.expand())
    w = np.array([g.weight for g in gold], dtype=np.float64)
    rows = []
    for metric in METRICS:
        est = ppi_mean(y[metric], f[metric], fu[metric], w)
        rows.append(
            _row(
                metric,
                bank_id,
                period,
                KpiMethod.PPI,
                est.value,
                cell.size,
                model_version,
                now,
                ppi=est,
                gold_version=gold_version,
            )
        )
    return rows


def compute_kpis(
    months: Sequence[str],
    gold: Mapping[str, Sequence[GoldRow]],
    corpus: Mapping[tuple[str, str], CorpusCell],
    model_version: str,
    now: datetime,
) -> list[KpiEstimate]:
    """KPI crudos y con PPI de cada banco en ``months``.

    ``gold`` agrupa el oro por ``gold_version`` y ``corpus`` va por
    ``(bank_id, mes)``. Un banco sin oro en una versión solo tiene ``raw``.
    """
    wanted = set(months)
    rows: list[KpiEstimate] = []
    for (bank_id, period), cell in sorted(corpus.items()):
        if period not in wanted or not cell.size:
            continue
        rows += raw_kpis(bank_id, period, cell, model_version, now)
        for gold_version, version_rows in sorted(gold.items()):
            bank_gold = [g for g in version_rows if g.bank_id == bank_id]
            if not bank_gold:
                log.warning(
                    "kpis: %s sin oro de %s; solo raw", bank_id, gold_version
                )
                continue
            rows += ppi_kpis(
                bank_id,
                period,
                bank_gold,
                cell,
                model_version,
                gold_version,
                now,
            )
    return rows


# -- Lectura y escritura -----------------------------------------------------


def gold_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[GoldRow]]:
    out: dict[str, list[GoldRow]] = defaultdict(list)
    for r in rows:
        predicted = r["sentiment"]
        out[r["gold_version"]].append(
            GoldRow(
                bank_id=r["bank_id"],
                stars=int(r["estrellas"]),
                label=r["label"],
                predicted=predicted if predicted in CLASSES else FALLBACK_CLASS,
                weight=float(r["weight"]),
            )
        )
    return dict(out)


def corpus_cells(
    rows: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str], CorpusCell]:
    grouped: dict[tuple[str, str], list[tuple[int, str, int]]] = defaultdict(
        list
    )
    for r in rows:
        grouped[(r["bank_id"], r["period"])].append(
            (int(r["estrellas"]), r["sentiment"], int(r["n"]))
        )
    return {
        key: CorpusCell(
            stars=tuple(s for s, _, _ in sorted(values)),
            predicted=tuple(p for _, p, _ in sorted(values)),
            counts=tuple(n for _, _, n in sorted(values)),
        )
        for key, values in grouped.items()
    }


@dataclass
class KpiJob:
    client: Any
    writer: StagingMergeWriter
    dataset: str
    run_id: str

    def _rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        return query_rows(self.client, render(sql, ds=self.dataset), params)

    def run(self, model_version: str, now: datetime) -> int:
        """Calcula y escribe los KPI que tocan; devuelve las filas nuevas."""
        gold = gold_rows(self._rows(GOLD_SQL))
        if not gold:
            log.warning("kpis: sin oro dev en gold_labels; solo raw")
        corpus = corpus_cells(self._rows(CORPUS_SQL))
        done = {
            (r["bank_id"], r["period"], r["method"], r["gold_version"])
            for r in self._rows(DONE_SQL, model_version=model_version)
        }
        months = months_to_compute(now, expected_series(corpus, gold), done)
        rows = compute_kpis(months, gold, corpus, model_version, now)
        added = self.writer.write(
            "kpi_estimates", rows, list(KPI_KEY), self.run_id
        )
        log.info("kpis: %d meses, %d filas", len(months), added)
        return added
