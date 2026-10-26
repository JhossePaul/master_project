"""Explicación por oclusión (extra ``[sentiment]``).

``occlusion_v2`` mide hacia dónde empuja cada palabra: ``d_c = p_c(texto) −
p_c(texto sin la palabra)`` para las tres clases, con las probabilidades
**calibradas** por la temperatura de la versión; ``d_neg > 0`` quiere decir
que la palabra empuja hacia ``NEG``. ``occlusion_v1`` (abajo) solo mide la
caída de la clase predicha y no se calibra.

``occlusion_v1``:

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

from voc_nlp.calibration import apply_temperature
from voc_nlp.sentiment_model import BATCH_SIZE, SentimentModel, predict_proba

METHOD: Final = "occlusion_v1"
METHOD_V2: Final = "occlusion_v2"
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


def occlusion_v2(
    model: SentimentModel,
    text: str,
    temperature: float,
    batch_size: int = BATCH_SIZE,
) -> list[TokenAttribution]:
    """Cambio de las tres probabilidades calibradas al quitar cada palabra."""
    spans = [(m.start(), m.end()) for m in _WORD.finditer(text)]
    if not spans:
        return []
    words = [text[start:end] for start, end in spans]
    variants = [text] + [
        " ".join(words[:i] + words[i + 1 :]) for i in range(len(words))
    ]
    proba = apply_temperature(
        predict_proba(model, variants, batch_size), temperature
    )
    delta = proba[0] - proba[1:]
    return [
        TokenAttribution(
            start=start,
            end=end,
            d_neg=float(delta[i, 0]),
            d_neu=float(delta[i, 1]),
            d_pos=float(delta[i, 2]),
        )
        for i, (start, end) in enumerate(spans)
    ]
