"""Datos sintéticos para diseñar y probar sin GCP (``PORTAL_DATA=fixtures``).

Los textos son inventados y cortos. Algunos llevan el **centinela**: un texto
que nunca debe llegar a un lector. Cada paso suma sus propios archivos a
``sample_data/`` y sus repositorios en memoria, que cumplen el mismo
``Protocol`` que su implementación de BigQuery.
"""

import json
from pathlib import Path

SENTINEL = "CENTINELA: este texto nunca debe llegar a un lector"
SAMPLE_DIR = Path(__file__).parent / "sample_data"


def load_sample(name: str) -> list[dict[str, object]]:
    """Filas de ``sample_data/<name>.json``."""
    path = SAMPLE_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))
