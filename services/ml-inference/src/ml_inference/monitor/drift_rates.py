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

from typing import Any, Final

from voc_nlp.drift_rates import CEILING, REFERENCE, TOLERANCE, Rate, rates

from ml_inference.bq_io import query_rows, render

__all__ = ["CEILING", "REFERENCE", "TOLERANCE", "Rate", "rates", "report"]

RATES_SQL: Final = """
SELECT bank_id, metric, COUNT(*) AS months, COUNTIF(alert) AS alerts
FROM `${ds}.drift_metrics`
WHERE threshold IS NOT NULL AND (z IS NOT NULL OR psi IS NOT NULL)
GROUP BY bank_id, metric
"""


def report(client: Any, dataset: str) -> list[Rate]:
    return rates(query_rows(client, render(RATES_SQL, ds=dataset)))
