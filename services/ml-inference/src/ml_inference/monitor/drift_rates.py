"""Meses de alerta al año por serie y banco, contra la línea base histórica.

Verifica que el monitor de deriva, corrido sobre el histórico, reproduce las
tasas del análisis de escala (``docs/analytics/scale/scale_report.md``,
sección 2, z ≥ 4 y PSI ≥ 0.25 desde el mes de entrada de cada banco). Lee
``drift_metrics`` (la primera corrida del monitor guarda el histórico con su
marca ``alert``) y no escribe nada.

La referencia se midió sobre la misma historia pero con otra fuente para
algunas series (``NEG`` de RoBERTuito sobre una muestra; aquí, sobre el
corpus completo), así que se compara con una tolerancia, no por igualdad.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from ml_inference.bq_io import query_rows, render

# Meses de alerta al año del análisis de escala (tabla de la sección 2).
REFERENCE: Final[dict[str, dict[str, float]]] = {
    "mean_words": {
        "AZTECA": 0.6,
        "BANORTE": 1.1,
        "BBVA": 1.0,
        "NUBANK": 0.4,
        "SANTANDER": 1.1,
    },
    "single_word_share": {
        "AZTECA": 0.7,
        "BANORTE": 0.8,
        "BBVA": 0.9,
        "NUBANK": 0.0,
        "SANTANDER": 0.5,
    },
    "over_60_words_share": {
        "AZTECA": 0.1,
        "BANORTE": 1.4,
        "BBVA": 0.8,
        "NUBANK": 0.4,
        "SANTANDER": 0.4,
    },
    "not_predicted_share": {
        "AZTECA": 0.0,
        "BANORTE": 0.2,
        "BBVA": 0.4,
        "NUBANK": 0.0,
        "SANTANDER": 0.1,
    },
    "out_of_vocabulary_share": {
        "AZTECA": 0.5,
        "BANORTE": 0.1,
        "BBVA": 0.8,
        "NUBANK": 0.0,
        "SANTANDER": 0.0,
    },
    "neg_share": {
        "AZTECA": 0.8,
        "BANORTE": 0.8,
        "BBVA": 1.1,
        "NUBANK": 0.6,
        "SANTANDER": 0.8,
    },
    "length_distribution": {
        "AZTECA": 0.1,
        "BANORTE": 0.4,
        "BBVA": 0.3,
        "NUBANK": 0.4,
        "SANTANDER": 0.0,
    },
}
TOLERANCE: Final = 0.5
# Techo del análisis: con z ≥ 4, ninguna serie pasó de 1.4 meses al año.
CEILING: Final = 1.4

RATES_SQL: Final = """
SELECT bank_id, metric, COUNT(*) AS months, COUNTIF(alert) AS alerts
FROM `${ds}.drift_metrics`
WHERE threshold IS NOT NULL AND (z IS NOT NULL OR psi IS NOT NULL)
GROUP BY bank_id, metric
"""


@dataclass(frozen=True)
class Rate:
    series: str
    bank_id: str
    months: int
    alerts: int
    reference: float | None

    @property
    def per_year(self) -> float:
        return 12 * self.alerts / self.months if self.months else 0.0

    @property
    def ok(self) -> bool:
        if self.reference is None:
            return self.per_year <= CEILING + TOLERANCE
        return abs(self.per_year - self.reference) <= TOLERANCE


def rates(rows: Iterable[Mapping[str, Any]]) -> list[Rate]:
    """Una tasa por serie × banco, con su referencia si existe."""
    totals: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        key = (r["metric"], r["bank_id"])
        totals[key][0] += int(r["months"])
        totals[key][1] += int(r["alerts"])
    return [
        Rate(
            series,
            bank,
            months,
            alerts,
            REFERENCE.get(series, {}).get(bank),
        )
        for (series, bank), (months, alerts) in sorted(totals.items())
    ]


def report(client: Any, dataset: str) -> list[Rate]:
    return rates(query_rows(client, render(RATES_SQL, ds=dataset)))
