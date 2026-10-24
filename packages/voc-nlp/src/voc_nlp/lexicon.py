"""Léxico de una palabra ``lexicon_v1`` (EPIC-5, 5.2; D2 de EPIC-6).

151 formas con su etiqueta agregada (soporte ≥ 3 filas de plata y pureza
≥ 0.9). Es la excepción aprobada a la regla de datos: no son reseñas ni
etiquetas individuales. El JSON se valida con su SHA-256 al cargarse.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from voc_common.constants import SentimentLabel

LEXICON_PATH: Final = Path(__file__).parent / "data" / "lexicon_v1.json"
LEXICON_VERSION: Final = "lexicon_v1"
# SHA-256 de ``data/lexicon_v1.json``; el parquet de origen está en el JSON.
LEXICON_SHA256: Final = (
    "7e0580180894ba2d9e7453db1f0a9145c2d23ff304c80a6bfdd056d1d0bb4cd1"
)
# Etiqueta de las formas sin sentimiento: caen en ``TNSS_SINGLE_WORD``.
NO_LABEL: Final = "NA"

_NON_ALNUM = re.compile(r"[^a-z0-9ñ]+")
_REPEATS = re.compile(r"(.)\1+")


def form(text: str | None) -> str:
    """Forma normalizada de un texto, como ``voc_analytics.eda.eda_lexicon``.

    Minúsculas, NFKD sin marcas combinantes, solo ``[a-z0-9ñ]`` y sin letras
    repetidas. La ``ñ`` se descompone en NFKD, así que termina como ``n``.
    """
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = _NON_ALNUM.sub("", t)
    return _REPEATS.sub(r"\1", t)


@dataclass(frozen=True)
class Lexicon:
    """Formas con etiqueta de sentimiento (sin las ``NA``)."""

    version: str
    labels: dict[str, SentimentLabel]

    def label(self, text: str | None) -> SentimentLabel | None:
        return self.labels.get(form(text))


def load_lexicon(path: Path = LEXICON_PATH) -> Lexicon:
    """Carga el léxico congelado; falla si su SHA-256 no coincide."""
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != LEXICON_SHA256:
        raise ValueError(f"lexicon checksum mismatch: {digest}")
    payload = json.loads(raw)
    labels = {
        forma: SentimentLabel(label)
        for forma, label in payload["formas"].items()
        if label != NO_LABEL
    }
    return Lexicon(payload["version"], labels)
