"""Utilidades comunes para ajustar encoders en el Mac (EPIC-5, feature 5.4).

Las usan M4 (`finetune.py`) y M8 (`delora.py`).

* **Checkpoints de partida:** los de `pysentimiento` en español, que ya traen
  una cabeza de 3 clases `NEG`/`NEU`/`POS` en ese orden. Se aplica su
  preprocesamiento (`preprocess_tweet`) antes de tokenizar.
* **Longitud:** `max_length = 128` cubre el 99.8–99.9 % de los textos de
  entrenamiento (medido con los dos tokenizadores).
* **Lotes por longitud:** se ordena por longitud dentro de bloques y se barajan
  los lotes. Así se reduce el relleno sin perder aleatoriedad.
* **Dispositivo:** CUDA (Kaggle) con fp16 automático, o MPS (Mac) en fp32.
  `train_defaults` fija el lote por dispositivo: en el Mac de 8 GB, lote 8
  con acumulación ×4 y embeddings congelados; en CUDA, lote 32 sin
  acumulación y sin congelar.
"""

import contextlib
import random
import time

import numpy as np
import torch

from voc_analytics.sentiment.data import CLASSES

ENCODERS = {
    "robertuito": "pysentimiento/robertuito-sentiment-analysis",
    "beto": "finiteautomata/beto-sentiment-analysis",
}
MAX_LENGTH = 128
SEED = 20261019


def device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("mps" if torch.backends.mps.is_available() else "cpu")


def train_defaults(dev: torch.device) -> dict:
    """Lote, acumulación y congelado de embeddings según el dispositivo."""
    if dev.type == "cuda":
        return {"batch": 32, "accum": 1, "freeze_embeddings": False}
    return {"batch": 8, "accum": 4, "freeze_embeddings": True}


class Amp:
    """fp16 automático con escalado de gradiente en CUDA; sin efecto en MPS."""

    def __init__(self, dev: torch.device):
        self.on = dev.type == "cuda"
        self.scaler = torch.amp.GradScaler("cuda", enabled=self.on)

    def autocast(self):
        if not self.on:
            return contextlib.nullcontext()
        return torch.autocast("cuda", dtype=torch.float16)

    def backward(self, loss) -> None:
        self.scaler.scale(loss).backward()

    def step(self, opt, params, clip: float = 1.0) -> None:
        self.scaler.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(params, clip)
        self.scaler.step(opt)
        self.scaler.update()


def empty_cache(dev: torch.device) -> None:
    if dev.type == "mps":
        torch.mps.empty_cache()
    elif dev.type == "cuda":
        torch.cuda.empty_cache()


def seed_all(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def load(encoder: str):
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    name = ENCODERS[encoder]
    tok = AutoTokenizer.from_pretrained(name)
    model = AutoModelForSequenceClassification.from_pretrained(name)
    if [model.config.id2label[i] for i in range(3)] != CLASSES:
        raise ValueError(f"{name}: orden de clases inesperado")
    return tok, model


def freeze_embeddings(model) -> None:
    """Congela la capa de embeddings (ahorra memoria del optimizador en MPS)."""
    for p in model.base_model.embeddings.parameters():
        p.requires_grad = False


def encode(tok, texts: list[str]) -> list[list[int]]:
    from pysentimiento.preprocessing import preprocess_tweet

    return tok(
        [preprocess_tweet(t) for t in texts],
        truncation=True,
        max_length=MAX_LENGTH,
    )["input_ids"]


def batches(
    ids: list[list[int]], size: int, shuffle: bool, rng: random.Random
) -> list[np.ndarray]:
    """Índices de lotes con longitudes parecidas."""
    order = np.arange(len(ids))
    if shuffle:
        rng.shuffle(order)
        chunk = size * 50
        order = np.concatenate(
            [
                sorted(order[i : i + chunk], key=lambda j: len(ids[j]))
                for i in range(0, len(order), chunk)
            ]
        )
    else:
        order = np.array(sorted(order, key=lambda j: len(ids[j])))
    out = [order[i : i + size] for i in range(0, len(order), size)]
    if shuffle:
        rng.shuffle(out)
    return out


def collate(ids: list[list[int]], idx: np.ndarray, pad_id: int, dev):
    rows = [ids[i] for i in idx]
    width = max(len(r) for r in rows)
    input_ids = torch.full((len(rows), width), pad_id, dtype=torch.long)
    mask = torch.zeros((len(rows), width), dtype=torch.long)
    for k, r in enumerate(rows):
        input_ids[k, : len(r)] = torch.tensor(r)
        mask[k, : len(r)] = 1
    return input_ids.to(dev), mask.to(dev)


@torch.no_grad()
def predict_proba(model, tok, ids, size: int = 64) -> tuple[np.ndarray, dict]:
    dev = next(model.parameters()).device
    model.eval()
    proba = np.zeros((len(ids), len(CLASSES)), dtype=np.float32)
    start = time.perf_counter()
    for idx in batches(ids, size, shuffle=False, rng=random.Random(0)):  # noqa: S311 - orden, no criptografía
        input_ids, mask = collate(ids, idx, tok.pad_token_id, dev)
        with Amp(dev).autocast():
            logits = model(input_ids=input_ids, attention_mask=mask).logits
        proba[idx] = torch.softmax(logits.float(), dim=-1).cpu().numpy()
    secs = time.perf_counter() - start
    return proba, {
        "textos": len(ids),
        "segundos": round(secs, 1),
        "textos_por_segundo": round(len(ids) / secs, 1),
    }


def val_split(claves: np.ndarray, share: float = 0.05) -> np.ndarray:
    """Máscara de validación agrupada por `clave` (determinista)."""
    import hashlib

    def bucket(c: str) -> float:
        h = hashlib.sha256(f"{SEED}|{c}".encode()).hexdigest()
        return int(h[:8], 16) / 0xFFFFFFFF

    return np.array([bucket(c) < share for c in claves])
