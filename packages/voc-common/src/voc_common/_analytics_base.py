"""Base y tipos comunes de los contratos analíticos v3 (EPIC-6, 6.1).

Siguen el estilo de los contratos v2 (``_StateV2``): campos no declarados
prohibidos, instancias inmutables y fechas normalizadas a UTC. Cada modelo es
una fila de una tabla de solo inserción de ``bbva_voc_tds``.
"""

from datetime import date
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from voc_common.schemas import Digest, NonEmpty, StarRating, UtcDatetime

Probability = Annotated[float, Field(ge=0.0, le=1.0)]
Counter = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(ge=1)]

# Tolerancia de la suma de probabilidades y de ``confidence = max(p)``.
PROBABILITY_TOLERANCE = 1e-6
# MiniLM (``paraphrase-multilingual-MiniLM-L12-v2``), P8-6.
EMBEDDING_DIMENSIONS = 384
ELIGIBILITY_RULES_VERSION = "eligibility_rules_v1"


def _first_of_month(value: date) -> date:
    if value.day != 1:
        raise ValueError("month columns must be the first day of the month")
    return value


# Mes como ``DATE`` del día 1 (columnas ``mes`` y ``period`` mensuales).
MonthDate = Annotated[date, AfterValidator(_first_of_month)]


class _AnalyticsRecord(BaseModel):
    """Fila inmutable de una tabla del esquema v3."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def require_together(**values: object) -> None:
    """Falla si unos valores están presentes y otros no."""
    present = {name for name, value in values.items() if value is not None}
    if present and present != set(values):
        names = ", ".join(sorted(values))
        raise ValueError(f"{names} must be all present or all null")


__all__ = [
    "Counter",
    "Digest",
    "EMBEDDING_DIMENSIONS",
    "ELIGIBILITY_RULES_VERSION",
    "MonthDate",
    "NonEmpty",
    "PROBABILITY_TOLERANCE",
    "PositiveInt",
    "Probability",
    "StarRating",
    "UtcDatetime",
    "_AnalyticsRecord",
    "require_together",
]
