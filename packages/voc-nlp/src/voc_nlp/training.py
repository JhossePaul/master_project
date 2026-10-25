"""Ajuste de RoBERTuito con la plata de Gemini (extra ``[sentiment]``).

Port de ``voc_analytics.sentiment.models.finetune`` con la receta de CUDA de
``encoder.train_defaults`` (lote 32, sin acumulación ni embeddings
congelados) y de ``encoder.val_split``, sin constantes de proyecto:

* parte siempre del modelo base, no del vigente, y ajusta todos los pesos;
* el 5 % de los textos, agrupados por texto, queda como validación sobre la
  plata y elige la mejor época por macro-F1; el oro no interviene;
* AdamW (decaimiento 0.01), *warm-up* lineal del 6 % y decaimiento lineal,
  recorte de gradiente en 1.0 y fp16 automático en CUDA;
* lotes de longitudes parecidas: orden por longitud dentro de bloques de 50
  lotes y lotes barajados.

Recibe ids de tokens ya preparados (``sentiment_model.prepare`` y
``token_ids``), así que el texto no sale de GCP. El módulo solo usa numpy,
torch y ``agreement``, para que ``kernel_source`` lo copie tal cual al kernel
de Kaggle, que corre sin internet ni ``voc-nlp``.
"""

import copy
import hashlib
import inspect
import json
import random
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import asdict, dataclass
from typing import Any, Final

import numpy as np
import torch
from numpy.typing import NDArray

from voc_nlp.agreement import cohen_kappa, macro_f1

CLASSES: Final = ("NEG", "NEU", "POS")
BASE_MODEL: Final = "pysentimiento/robertuito-sentiment-analysis"
# Semilla de la partición de 5.4: con los mismos textos, la misma validación.
SPLIT_SEED: Final = 20261019
PREDICT_BATCH: Final = 64
# Bloque en el que se ordena por longitud antes de cortar lotes.
_CHUNK_BATCHES: Final = 50

# Archivos del dataset de Kaggle y de la salida del kernel.
TRAIN_FILE: Final = "train.parquet"  # input_ids, label, is_val
DEV_FILE: Final = "dev.parquet"  # key, input_ids
BASE_DIR: Final = "base"
MODEL_DIR: Final = "model"
DEV_PREDS_FILE: Final = "dev_preds.parquet"  # key, p_NEG, p_NEU, p_POS
LOG_FILE: Final = "train_log.json"


@dataclass(frozen=True)
class TrainParams:
    """La receta de 5.4; una semilla por reentrenamiento."""

    base: str = BASE_MODEL
    epochs: int = 2
    lr: float = 2e-5
    weight_decay: float = 0.01
    warmup: float = 0.06
    clip: float = 1.0
    batch: int = 32
    accum: int = 1
    max_length: int = 128
    seed: int = 1
    val_share: float = 0.05
    split_seed: int = SPLIT_SEED


@dataclass(frozen=True)
class EpochLog:
    epoch: int
    train_loss: float
    val_macro_f1: float
    val_kappa: float
    texts_per_second: float


@dataclass(frozen=True)
class TrainResult:
    """Historial por época; el modelo queda con los pesos de ``best_epoch``."""

    history: tuple[EpochLog, ...]
    best_epoch: int
    train_texts: int
    val_texts: int
    seconds: float
    device: str

    @property
    def best(self) -> EpochLog:
        return self.history[self.best_epoch - 1]


def val_split(
    groups: Sequence[str], share: float, seed: int
) -> NDArray[np.bool_]:
    """Máscara de validación agrupada por texto, determinista con ``seed``."""

    def bucket(group: str) -> float:
        digest = hashlib.sha256(f"{seed}|{group}".encode()).hexdigest()
        return int(digest[:8], 16) / 0xFFFFFFFF

    return np.array([bucket(g) < share for g in groups], dtype=np.bool_)


def batches(
    lengths: Sequence[int], size: int, shuffle: bool, rng: random.Random
) -> list[NDArray[np.int64]]:
    """Índices de lotes con longitudes parecidas."""
    order = np.arange(len(lengths))
    if shuffle:
        rng.shuffle(order)  # type: ignore[arg-type]
        chunk = size * _CHUNK_BATCHES
        order = np.concatenate(
            [
                sorted(order[i : i + chunk], key=lambda j: lengths[j])
                for i in range(0, len(order), chunk)
            ]
        )
    else:
        order = np.array(sorted(order, key=lambda j: lengths[j]))
    out = [order[i : i + size] for i in range(0, len(order), size)]
    if shuffle:
        rng.shuffle(out)
    return out


def lr_factor(steps: int, warmup: float) -> Callable[[int], float]:
    """*Warm-up* lineal y decaimiento lineal hasta 0 en ``steps``."""
    warm = int(warmup * steps)
    return lambda s: min(
        (s + 1) / max(warm, 1), max(0.0, (steps - s) / max(steps - warm, 1))
    )


def _collate(
    ids: Sequence[Sequence[int]], idx: NDArray[np.int64], pad: int, device: Any
) -> tuple[torch.Tensor, torch.Tensor]:
    rows = [ids[i] for i in idx]
    width = max(len(r) for r in rows)
    input_ids = torch.full((len(rows), width), pad, dtype=torch.long)
    mask = torch.zeros((len(rows), width), dtype=torch.long)
    for k, row in enumerate(rows):
        input_ids[k, : len(row)] = torch.tensor(row, dtype=torch.long)
        mask[k, : len(row)] = 1
    return input_ids.to(device), mask.to(device)


def _autocast(device: torch.device) -> AbstractContextManager[Any]:
    if device.type != "cuda":
        return nullcontext()
    return torch.autocast("cuda", dtype=torch.float16)


def _pad_id(model: Any) -> int:
    pad = model.config.pad_token_id
    if pad is None:
        raise ValueError("model config has no pad_token_id")
    return int(pad)


def _seed_all(seed: int) -> None:
    random.seed(seed)  # noqa: S311  # nosec B311
    np.random.seed(seed)  # noqa: NPY002
    torch.manual_seed(seed)


@torch.no_grad()
def predict(
    model: Any, ids: Sequence[Sequence[int]], batch: int = PREDICT_BATCH
) -> NDArray[np.float32]:
    """Probabilidades ``(n, 3)`` sin calibrar, en el orden de entrada."""
    device = next(model.parameters()).device
    model.eval()
    proba = np.zeros((len(ids), len(CLASSES)), dtype=np.float32)
    lengths = [len(x) for x in ids]
    order = random.Random(0)  # noqa: S311  # nosec B311 - sin barajar
    for idx in batches(lengths, batch, shuffle=False, rng=order):
        input_ids, mask = _collate(ids, idx, _pad_id(model), device)
        with _autocast(device):
            logits = model(input_ids=input_ids, attention_mask=mask).logits
        proba[idx] = torch.softmax(logits.float(), dim=-1).cpu().numpy()
    return proba


def _epochs(
    model: Any,
    ids: Sequence[Sequence[int]],
    labels: NDArray[np.int64],
    params: TrainParams,
    device: torch.device,
) -> Iterator[tuple[float, float]]:
    """Entrena época por época; da la pérdida media y los textos por segundo."""
    rng = random.Random(params.seed)  # noqa: S311  # nosec B311 - muestreo
    steps = params.epochs * -(-len(ids) // (params.batch * params.accum))
    opt = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=params.lr,
        weight_decay=params.weight_decay,
    )
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lr_factor(steps, params.warmup)
    )
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    lengths = [len(x) for x in ids]
    pad = _pad_id(model)
    for _ in range(params.epochs):
        model.train()
        start, seen, total = time.perf_counter(), 0, 0.0
        for step, idx in enumerate(batches(lengths, params.batch, True, rng)):
            input_ids, mask = _collate(ids, idx, pad, device)
            target = torch.from_numpy(labels[idx]).to(device)
            with _autocast(device):
                logits = model(input_ids=input_ids, attention_mask=mask).logits
            loss = torch.nn.functional.cross_entropy(logits.float(), target)
            scaler.scale(loss / params.accum).backward()
            if (step + 1) % params.accum == 0:
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(model.parameters(), params.clip)
                scaler.step(opt)
                scaler.update()
                sched.step()
                opt.zero_grad()
            seen += len(idx)
            total += loss.item() * len(idx)
        yield total / seen, seen / (time.perf_counter() - start)


def train(
    model: Any,
    ids: Sequence[Sequence[int]],
    labels: NDArray[np.int64],
    is_val: NDArray[np.bool_],
    params: TrainParams,
    device: str | None = None,
    log: Callable[[str], None] = print,
) -> TrainResult:
    """Ajusta ``model`` y lo deja con la mejor época por macro-F1 de validación.

    ``labels`` son índices de ``CLASSES`` e ``is_val`` la máscara de
    ``val_split``. ``device`` es ``cuda`` si hay GPU y ``cpu`` si no.
    """
    labels = np.asarray(labels, dtype=np.int64)
    is_val = np.asarray(is_val, dtype=np.bool_)
    if not len(ids) == len(labels) == len(is_val):
        raise ValueError("ids, labels and is_val must align")
    if not is_val.any() or is_val.all():
        raise ValueError("training and validation need texts")
    if any(len(x) > params.max_length for x in ids):
        raise ValueError(f"token ids longer than {params.max_length}")
    _seed_all(params.seed)
    dev = torch.device(
        device or ("cuda" if torch.cuda.is_available() else "cpu")
    )
    model.to(dev)
    tr_idx, va_idx = np.flatnonzero(~is_val), np.flatnonzero(is_val)
    tr_ids = [ids[i] for i in tr_idx]
    va_ids = [ids[i] for i in va_idx]
    truth = [CLASSES[i] for i in labels[va_idx]]
    history: list[EpochLog] = []
    best, best_state = -1.0, None
    start = time.perf_counter()
    epochs = _epochs(model, tr_ids, labels[tr_idx], params, dev)
    for epoch, (loss, speed) in enumerate(epochs, 1):
        pred = [CLASSES[i] for i in predict(model, va_ids).argmax(axis=1)]
        f1 = macro_f1(truth, pred, CLASSES)
        history.append(
            EpochLog(
                epoch=epoch,
                train_loss=round(loss, 4),
                val_macro_f1=round(f1, 4),
                val_kappa=round(cohen_kappa(truth, pred), 4),
                texts_per_second=round(speed, 1),
            )
        )
        log(json.dumps(asdict(history[-1])))
        if f1 > best:
            best = f1
            best_state = copy.deepcopy(
                {k: v.detach().cpu() for k, v in model.state_dict().items()}
            )
    if best_state is not None:
        model.load_state_dict(best_state)
    return TrainResult(
        history=tuple(history),
        best_epoch=max(history, key=lambda h: h.val_macro_f1).epoch,
        train_texts=len(tr_ids),
        val_texts=len(va_ids),
        seconds=round(time.perf_counter() - start, 1),
        device=str(dev),
    )


# -- Kernel de Kaggle --------------------------------------------------------

_KERNEL_MAIN: Final = """
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from transformers import AutoModelForSequenceClassification, AutoTokenizer

src = next(Path(INPUT).rglob(TRAIN_FILE)).parent
work = Path(WORK)
table = pq.read_table(src / TRAIN_FILE)
base = src / BASE_DIR
model = AutoModelForSequenceClassification.from_pretrained(
    base, dtype=torch.float32, local_files_only=True)
assert tuple(model.config.id2label[i] for i in range(3)) == CLASSES
result = train(
    model,
    table["input_ids"].to_pylist(),
    np.asarray(table["label"].to_pylist(), dtype=np.int64),
    np.asarray(table["is_val"].to_pylist(), dtype=np.bool_),
    PARAMS,
)
dev = pq.read_table(src / DEV_FILE)
proba = predict(model, dev["input_ids"].to_pylist())
pq.write_table(
    pa.table({"key": dev["key"], **{f"p_{c}": proba[:, i]
                                    for i, c in enumerate(CLASSES)}}),
    work / DEV_PREDS_FILE, compression="zstd")
out = work / MODEL_DIR
shutil.rmtree(out, ignore_errors=True)
model.half().save_pretrained(out, safe_serialization=True)
AutoTokenizer.from_pretrained(base, local_files_only=True).save_pretrained(out)
(work / LOG_FILE).write_text(json.dumps(
    {"run": RUN, "params": asdict(PARAMS), **asdict(result)}))
"""


def kernel_source(
    run: str,
    params: TrainParams,
    input_dir: str = "/kaggle/input",
    work_dir: str = "/kaggle/working",
) -> str:
    """Script del kernel: este módulo y ``agreement``, sin ``voc-nlp``.

    Lee del dataset ``TRAIN_FILE``, ``DEV_FILE`` y el modelo base en
    ``BASE_DIR``; escribe en ``work_dir`` los pesos fp16 con su tokenizador
    (``MODEL_DIR``), las probabilidades del oro *dev* sin calibrar
    (``DEV_PREDS_FILE``) y el historial con ``run`` (``LOG_FILE``).
    """
    own = inspect.getsource(sys.modules[__name__])
    own = own.replace(
        "from voc_nlp.agreement import cohen_kappa, macro_f1\n", ""
    )
    header = (
        f'"""Reentrenamiento en Kaggle (lo genera voc_nlp.training)."""\n'
        f"RUN = {run!r}\nINPUT = {input_dir!r}\nWORK = {work_dir!r}\n"
    )
    return (
        header
        + inspect.getsource(sys.modules[cohen_kappa.__module__])
        + own
        + f"\nPARAMS = TrainParams(**{asdict(params)!r})\n"
        + _KERNEL_MAIN
    )
