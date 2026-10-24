"""Benchmark de inferencia de M4 en CPU (5.7, decisiones P7-1 y P7-2).

Mide la velocidad y la memoria de M4 RoBERTuito en CPU, en el Mac (proxy de
Cloud Run) y dentro de un Cloud Run Job (decisión del autor, 2026-10-22: E1,
medir en Cloud Run; E2, medir la cuantización int8).

* **Variantes:** fp32 y cuantización dinámica int8 de las capas lineales
  (`torch.ao.quantization.quantize_dynamic`); con y sin orden por longitud
  (lotes de textos de longitud parecida, menos relleno); 1, 2 y 4 hilos.
* **Mide:** tiempo de carga del modelo, textos por segundo y memoria pico del
  proceso (RSS máximo). Cada configuración corre en su propio subproceso,
  para que la memoria pico no se acumule entre corridas.
* **Calidad de int8** (`--gold`, solo en el Mac): κ y acuerdo con fp32 sobre
  el oro *dev* aleatorio; el oro *test* no se toca.

El módulo no importa `voc_analytics` salvo para `--gold`, así que la imagen de
Cloud Run solo copia este archivo, los pesos y la muestra de textos.

    uv run python -m voc_analytics.scale.benchmark \\
        --weights data/models/weights/M4_robertuito_s1_ppi \\
        --texts data/labels/ppi_v0/texts.parquet --env mac --gold \\
        --out ../../docs/analytics/scale/benchmark_mac.json
"""

import argparse
import json
import os
import platform
import resource
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl
import torch

SAMPLE = 5000
SEED = 20261022
BATCH = 64
MAX_LEN = 128


def peak_rss_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reporta bytes; Linux, kilobytes.
    return rss / 1e6 if sys.platform == "darwin" else rss / 1e3


def load(weights: Path, int8: bool):
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    start = time.perf_counter()
    tok = AutoTokenizer.from_pretrained(weights)
    model = AutoModelForSequenceClassification.from_pretrained(
        weights, dtype=torch.float32
    ).eval()
    if int8:
        # fbgemm en x86 (Cloud Run); qnnpack en ARM (el Mac).
        engines = torch.backends.quantized.supported_engines
        torch.backends.quantized.engine = (
            "fbgemm" if "fbgemm" in engines else "qnnpack"
        )
        model = torch.ao.quantization.quantize_dynamic(
            model, {torch.nn.Linear}, dtype=torch.qint8
        )
    return tok, model, time.perf_counter() - start


def encode(tok, texts: list[str]) -> list[list[int]]:
    return tok(texts, truncation=True, max_length=MAX_LEN)["input_ids"]


def predict(model, ids: list[list[int]], pad: int, sort: bool) -> np.ndarray:
    order = (
        np.argsort([len(x) for x in ids], kind="stable")
        if sort
        else np.arange(len(ids))
    )
    out = np.zeros((len(ids), 3), dtype=np.float32)
    with torch.inference_mode():
        for i in range(0, len(ids), BATCH):
            idx = order[i : i + BATCH]
            batch = [ids[j] for j in idx]
            width = max(map(len, batch))
            x = torch.tensor([b + [pad] * (width - len(b)) for b in batch])
            logits = model(input_ids=x, attention_mask=(x != pad).long()).logits
            out[idx] = torch.softmax(logits.float(), dim=-1).numpy()
    return out


def run(
    weights: Path, texts: list[str], threads: int, sort: bool, int8: bool
) -> dict:
    torch.set_num_threads(threads)
    tok, model, load_s = load(weights, int8)
    ids = encode(tok, texts)
    start = time.perf_counter()
    predict(model, ids, tok.pad_token_id, sort)
    secs = time.perf_counter() - start
    return {
        "hilos": threads,
        "orden_por_longitud": sort,
        "int8": int8,
        "textos": len(texts),
        "segundos": round(secs, 2),
        "textos_por_segundo": round(len(texts) / secs, 1),
        "carga_modelo_s": round(load_s, 2),
        "rss_pico_mb": round(peak_rss_mb(), 1),
    }


def gold_quality(weights: Path) -> dict:
    from sklearn.metrics import cohen_kappa_score

    from voc_analytics.sentiment.data import CLASSES, gold

    dev = gold().filter(
        (pl.col("particion") == "dev")
        & (pl.col("bloque_oro") == "aleatorio")
        & (pl.col("oro") != "NA")
    )
    y = dev["oro"].to_numpy()
    preds = {}
    for int8 in (False, True):
        tok, model, _ = load(weights, int8)
        proba = predict(
            model,
            encode(tok, dev["texto_sanitizado"].to_list()),
            tok.pad_token_id,
            True,
        )
        preds[int8] = np.asarray(CLASSES)[proba.argmax(axis=1)]
    return {
        "n": int(dev.height),
        "kappa_fp32": round(float(cohen_kappa_score(y, preds[False])), 4),
        "kappa_int8": round(float(cohen_kappa_score(y, preds[True])), 4),
        "acuerdo_int8_fp32": round(
            float(np.mean(preds[True] == preds[False])), 4
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", type=Path, required=True)
    ap.add_argument("--texts", type=Path, required=True)
    ap.add_argument("--env", required=True, help="mac o cloudrun-<vcpu>")
    ap.add_argument("--threads", default="1,2,4")
    ap.add_argument("--sample", type=int, default=SAMPLE)
    ap.add_argument("--gold", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--single", help="uso interno: hilos,int8,orden")
    args = ap.parse_args()
    frame = pl.read_parquet(args.texts)
    texts = frame.sample(min(args.sample, frame.height), seed=SEED)[
        "texto_sanitizado"
    ].to_list()
    if args.single:
        threads, int8, sort = args.single.split(",")
        r = run(args.weights, texts, int(threads), sort == "1", int8 == "1")
        print("CORRIDA " + json.dumps(r), flush=True)
        return
    runs = []
    for threads in args.threads.split(","):
        for int8 in ("0", "1"):
            for sort in ("0", "1"):
                cmd = [
                    sys.executable,
                    __file__,
                    "--weights",
                    str(args.weights),
                    "--texts",
                    str(args.texts),
                    "--env",
                    args.env,
                    "--sample",
                    str(args.sample),
                    "--single",
                    f"{threads},{int8},{sort}",
                ]
                done = subprocess.run(  # noqa: S603 - comando propio
                    cmd, capture_output=True, text=True, check=True
                )
                line = next(
                    x
                    for x in done.stdout.splitlines()
                    if x.startswith("CORRIDA ")
                )
                r = json.loads(line.removeprefix("CORRIDA "))
                print(json.dumps(r), flush=True)
                runs.append(r)
    result = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "entorno": args.env,
        "cpus_visibles": os.cpu_count(),
        "plataforma": platform.platform(),
        "torch": torch.__version__,
        "corridas": runs,
    }
    if args.gold:
        result["calidad_int8"] = gold_quality(args.weights)
    print("RESULTADO " + json.dumps(result), flush=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )


if __name__ == "__main__":
    main()
