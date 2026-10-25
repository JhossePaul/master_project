"""Costo de la explicabilidad por oclusión en la cola HITL (5.7, P8-8).

Decisión del autor (2026-10-22): la explicabilidad queda acotada al HITL, y
antes de descartarla se estima cuánto costaría calcularla. La atribución por
oclusión quita una palabra a la vez y mide cuánto cambia la probabilidad de la
clase predicha: una pasada del modelo por palabra, más la del texto completo.

* **Cola simulada:** el 10 % de los textos de `ppi_v0` con menor confianza de
  M4 (la cobertura de 90 % de 5.6), de donde se toman 200 al azar.
* **Mide en el Mac** (1 hilo, fp32, lotes ordenados por longitud) el tiempo
  por texto y lo lleva a Cloud Run con la razón medida en el benchmark de 5.7
  entre el Mac y un Job de 1 vCPU (`benchmark_mac.json` y
  `benchmark_cloudrun-1cpu-2gi.json`).
* **Proyecta** el costo semanal con ~350 textos en la cola (5.6).

Escribe `docs/analytics/scale/explain_cost_v0_metrics.json`, solo agregados.

    uv run python -m voc_analytics.scale.explain_cost
"""

import json
import time
from datetime import UTC, datetime

import numpy as np
import polars as pl
import torch

from voc_analytics.paths import DOCS, LABELS, MODELS
from voc_analytics.scale.benchmark import encode, load, predict
from voc_analytics.sentiment.data import PREDS

M4 = "M4_robertuito_s1_ppi"
WEIGHTS = MODELS / "weights" / M4
OUT = DOCS / "scale" / "explain_cost_v0_metrics.json"
SAMPLE = 200
WEEKLY_QUEUE = 350
SEED = 20261022


def throughput(path: str, threads: int = 1) -> float:
    runs = json.loads((DOCS / "scale" / path).read_text())["corridas"]
    return next(
        r["textos_por_segundo"]
        for r in runs
        if r["hilos"] == threads and r["orden_por_longitud"] and not r["int8"]
    )


def main() -> None:
    torch.set_num_threads(1)
    texts = pl.read_parquet(LABELS / "ppi_v0" / "texts.parquet").select(
        "text_id", "texto_sanitizado"
    )
    preds = pl.read_parquet(PREDS / f"{M4}__ppi.parquet").with_columns(
        conf=pl.max_horizontal("p_NEG", "p_NEU", "p_POS")
    )
    cut = preds["conf"].quantile(0.10)
    queue = texts.join(
        preds.filter(pl.col("conf") <= cut).select("text_id"), on="text_id"
    ).sample(SAMPLE, seed=SEED)
    tok, model, _ = load(WEIGHTS, False)
    words_per_text, seconds = [], []
    for text in queue["texto_sanitizado"].to_list():
        words = text.split()
        variants = [text] + [
            " ".join(words[:i] + words[i + 1 :]) for i in range(len(words))
        ]
        start = time.perf_counter()
        predict(model, encode(tok, variants), tok.pad_token_id, True)
        seconds.append(time.perf_counter() - start)
        words_per_text.append(len(words))
    ratio = throughput("benchmark_mac.json") / throughput(
        "benchmark_cloudrun-1cpu-2gi.json"
    )
    mac = float(np.median(seconds))
    p90 = float(np.percentile(seconds, 90))
    weekly_mac = float(np.mean(seconds)) * WEEKLY_QUEUE
    result = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "modelo": M4,
        "textos": SAMPLE,
        "confianza_corte_10pct": round(float(cut), 4),
        "palabras_mediana": float(np.median(words_per_text)),
        "palabras_p90": float(np.percentile(words_per_text, 90)),
        "mac_1_hilo": {
            "segundos_por_texto_mediana": round(mac, 3),
            "segundos_por_texto_p90": round(p90, 3),
        },
        "razon_mac_cloudrun_1vcpu": round(ratio, 2),
        "cloudrun_1vcpu_estimado": {
            "segundos_por_texto_mediana": round(mac * ratio, 2),
            "segundos_por_texto_p90": round(p90 * ratio, 2),
            "minutos_por_semana": round(weekly_mac * ratio / 60, 1),
            "vcpu_segundos_por_mes": round(weekly_mac * ratio * 4.35),
        },
        "cola_semanal": WEEKLY_QUEUE,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
