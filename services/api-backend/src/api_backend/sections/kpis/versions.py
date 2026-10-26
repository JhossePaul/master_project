"""Normalización de ``version_app`` por banco y agrupación de versiones chicas.

Port a Python de ``voc_analytics.topics.versions.normalize`` (sin modificar el
original). Cada banco tiene su esquema de versiones:

* AZTECA: ``2.3.15`` sin cambio; las ``2.6.2 - BETA`` quedan nulas;
* BANORTE: ``7.0.9.45841`` → ``7.0.9`` (el 4.º componente es compilación);
* BBVA: ``11.33.210429`` → ``11.33`` (un 3.er componente de 6 dígitos es una
  fecha); ``10.90`` y ``25.60.10`` sin cambio;
* NUBANK: ``9.38.75-minApi28`` → ``9.38.75``;
* SANTANDER: ``5.54.8`` y ``5.30`` sin cambio.

``UNKNOWN``, las ``BETA`` y lo que no empieza con dígito quedan nulos y se
reportan como cobertura.
"""

import re
from collections.abc import Mapping

MIN_ROWS_PER_VERSION = 50
OTHER = "OTRAS"

_MIN_API = re.compile(r"-minApi\d+$")
_PREFIX = re.compile(r"^([\d.]+)")
_THREE = re.compile(r"^(\d+\.\d+\.\d+)")
_TWO = re.compile(r"^(\d+\.\d+)")
_DATE_THIRD = re.compile(r"^\d+\.\d+\.\d{6}$")


def normalize(bank_id: str, version_app: str | None) -> str | None:
    """``release`` de una reseña, o ``None`` si la versión no se reconoce."""
    if version_app is None:
        return None
    v = version_app.strip()
    if v == "UNKNOWN" or "beta" in v.lower() or not v[:1].isdigit():
        return None
    match = _PREFIX.match(_MIN_API.sub("", v))
    if match is None:  # pragma: no cover - ya empieza con dígito
        return None
    base = match.group(1).strip(".")
    if bank_id == "BANORTE":
        found = _THREE.match(base)
        return found.group(1) if found else None
    if bank_id == "BBVA" and _DATE_THIRD.match(base):
        found = _TWO.match(base)
        return found.group(1) if found else None
    return base


def group_small(
    counts: Mapping[str, int], n_min: int = MIN_ROWS_PER_VERSION
) -> dict[str, str]:
    """``OTRAS`` si la versión tiene menos de ``n_min`` reseñas."""
    return {
        release: OTHER if n < n_min else release
        for release, n in counts.items()
    }
