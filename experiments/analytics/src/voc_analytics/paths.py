"""Rutas comunes de la experimentación de EPIC-5.

Todas se resuelven desde la ubicación del paquete, no desde el directorio de
trabajo. `data/` está fuera de git (texto de reseñas); `docs/analytics/` solo
recibe agregados.
"""

from pathlib import Path

# experiments/analytics (src/voc_analytics/paths.py → parents[2]).
ANALYTICS = Path(__file__).resolve().parents[2]
ROOT = ANALYTICS.parents[1]
DATA = ANALYTICS / "data"
LABELS = DATA / "labels"
MODELS = DATA / "models"
DOCS = ROOT / "docs" / "analytics"
