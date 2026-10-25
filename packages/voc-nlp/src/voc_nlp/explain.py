"""Explicación por oclusión ``occlusion_v1`` (extra ``[sentiment]``).

Por cada palabra del texto (separada por espacios) se predice el texto sin
ella. La atribución es ``p(clase predicha | texto) − p(clase | texto sin la
palabra)``: positiva si la palabra empuja hacia la predicción y negativa si
la contradice (decisión del autor, 2026-10-24). Usa el mismo
preprocesamiento que la predicción. Las posiciones son caracteres de
``texto_sanitizado``, así que ``review_explanations`` no copia texto.
"""

import re
from typing import Final

import numpy as np
from voc_common.operations_v3 import TokenAttribution

from voc_nlp.sentiment_model import BATCH_SIZE, SentimentModel, predict_proba

METHOD: Final = "occlusion_v1"
_WORD = re.compile(r"\S+")


def occlusion(
    model: SentimentModel, text: str, batch_size: int = BATCH_SIZE
) -> list[TokenAttribution]:
    """Atribución de cada palabra a la clase predicha del texto completo."""
    spans = [(m.start(), m.end()) for m in _WORD.finditer(text)]
    if not spans:
        return []
    words = [text[start:end] for start, end in spans]
    variants = [text] + [
        " ".join(words[:i] + words[i + 1 :]) for i in range(len(words))
    ]
    proba = predict_proba(model, variants, batch_size)
    predicted = int(np.argmax(proba[0]))
    base = float(proba[0, predicted])
    return [
        TokenAttribution(
            start=start, end=end, weight=base - float(proba[i + 1, predicted])
        )
        for i, (start, end) in enumerate(spans)
    ]
