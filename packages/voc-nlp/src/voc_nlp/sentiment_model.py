"""RoBERTuito ajustado para sentimiento (``[sentiment]``; M4 en EPIC-5, D11).

Port del kernel del backfill de 5.8 (``voc_analytics.scale.backfill``) y de
``voc_analytics.sentiment.encoder``: ``preprocess_tweet`` de ``pysentimiento``
(el modelo base se preentrenó con tweets y el ajuste de EPIC-5 lo aplicó),
tope de 128 tokens, orden estable por longitud y *softmax* de los logits. En
producción corre en CPU y en fp32: los pesos fp16 del registro se suben a
fp32 al cargarse (D4).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import torch
from numpy.typing import NDArray
from pysentimiento.preprocessing import preprocess_tweet
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    PreTrainedModel,
    PreTrainedTokenizerBase,
)

CLASSES: Final = ("NEG", "NEU", "POS")
MAX_LENGTH: Final = 128
BATCH_SIZE: Final = 64


@dataclass(frozen=True)
class SentimentModel:
    tokenizer: PreTrainedTokenizerBase
    model: PreTrainedModel


def load_sentiment_model(weights_dir: Path) -> SentimentModel:
    """Carga tokenizador y modelo locales en fp32 y CPU, sin red."""
    # Carpeta local de ml_artifacts/ (sin descarga de Hugging Face, B615).
    tokenizer = AutoTokenizer.from_pretrained(  # nosec B615
        weights_dir, local_files_only=True
    )
    model = AutoModelForSequenceClassification.from_pretrained(  # nosec B615
        weights_dir, dtype=torch.float32, local_files_only=True
    ).eval()
    labels = tuple(model.config.id2label[i] for i in range(len(CLASSES)))
    if labels != CLASSES:
        raise ValueError(f"unexpected id2label: {labels}")
    return SentimentModel(tokenizer, model)


def encode(model: SentimentModel, texts: Sequence[str]) -> list[list[int]]:
    """Ids de cada texto tras ``preprocess_tweet`` y el tope de 128 tokens."""
    prepared = [preprocess_tweet(text) for text in texts]
    encoded = model.tokenizer(prepared, truncation=True, max_length=MAX_LENGTH)
    return [list(ids) for ids in encoded["input_ids"]]


def predict_ids(
    model: SentimentModel,
    ids: Sequence[Sequence[int]],
    batch_size: int = BATCH_SIZE,
) -> NDArray[np.float32]:
    """Probabilidades ``(n, 3)`` sin calibrar, en el orden de entrada.

    Agrupa por longitud (orden estable) para rellenar poco y deshace el
    orden al escribir cada lote.
    """
    out = np.zeros((len(ids), len(CLASSES)), dtype=np.float32)
    if not ids:
        return out
    pad = model.tokenizer.pad_token_id
    if pad is None:
        raise ValueError("tokenizer has no pad token")
    order = np.argsort([len(x) for x in ids], kind="stable")
    with torch.inference_mode():
        for start in range(0, len(ids), batch_size):
            idx = order[start : start + batch_size]
            batch = [ids[j] for j in idx]
            width = max(map(len, batch))
            x = torch.full((len(batch), width), pad, dtype=torch.long)
            for row, item in enumerate(batch):
                x[row, : len(item)] = torch.tensor(item, dtype=torch.long)
            logits = model.model(input_ids=x, attention_mask=x != pad).logits
            out[idx] = torch.softmax(logits.float(), dim=-1).numpy()
    return out


def predict_proba(
    model: SentimentModel,
    texts: Sequence[str],
    batch_size: int = BATCH_SIZE,
) -> NDArray[np.float32]:
    """Probabilidades sin calibrar de ``texts`` (``NEG``, ``NEU``, ``POS``)."""
    return predict_ids(model, encode(model, texts), batch_size)
