"""Vía B a escala: familias `aspects_v2_1` en las negativas de la plata (5.5).

Aprobado por el autor (2026-10-22): codificar con Gemini (Vertex AI dentro de
GCP) los textos `NEG` únicos del conjunto de trabajo (`working_set`), con el
prompt y la configuración de 5.2 (`eda/prompts/aspects_v2_1.md`, temperatura
0, lotes de 100). Reutiliza sin modificarlos `label_batch`
(`labeling.label_gemini`) y el lector de salida de `eda.eda_aspects_v2`.

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.topics.aspects_scale label \\
        [--workers 8 --max-cost 5 --solo-faltantes]
    uv run python -m voc_analytics.topics.aspects_scale summary

* **label:** etiqueta por lotes en paralelo y guarda cada lote terminado en
  `checkpoint.jsonl`. Con `--solo-faltantes` omite los lotes ya terminados sin
  error (por ejemplo, tras un lote fallido) y solo pide el resto. `--max-cost`
  limita el gasto de cada corrida; la meta da también el total real.

* **summary:** costo real, reproducibilidad contra las etiquetas de 5.2 de
  los mismos textos (mismo prompt, otros lotes) y proporciones poblacionales
  por familia (filas `NEG` ponderadas por 1 / π).

Escribe en `data/topics/aspects_scale_v0/` (fuera de git): etiquetas por texto
(`labels_aspects_v2_1.parquet`, columnas `text_id`, `codes`, `actualizacion`,
`seguridad` y `elogio`, como en 5.2) y la meta de la corrida; solo agregados
en `docs/analytics/topics/topics_aspects_scale_v0_metrics.json`.
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

import polars as pl
from google import genai
from google.genai import types

from voc_analytics.eda.eda_aspects_v2 import BATCH, PROMPTS, parse
from voc_analytics.labeling.label_gemini import (
    LOCATION,
    MODEL,
    PRICE_IN,
    PRICE_OUT,
    PROJECT,
    THINKING,
    label_batch,
)
from voc_analytics.paths import DATA, DOCS
from voc_analytics.topics.working_set import OUT as WORKING

PROMPT = "aspects_v2_1"
CODES = ["AC", "TR", "DI", "PR", "AT", "FA", "LE", "CO", "DV", "UX", "OT"]
EDA_LABELS = (
    DATA / "eda" / "aspects_v2" / "labels_aspects_v2_1_extracciones.parquet"
)
METRICS = DOCS / "topics" / "topics_aspects_scale_v0_metrics.json"
OUT = DATA / "topics" / "aspects_scale_v0"
CHECKPOINT = OUT / "checkpoint.jsonl"
SCHEMA = {
    "text_id": pl.UInt32,
    "codes": pl.String,
    "actualizacion": pl.Boolean,
    "seguridad": pl.Boolean,
    "elogio": pl.Boolean,
}


def cost_of(usage: dict) -> float:
    return (
        usage["prompt"] * PRICE_IN
        + (usage["output"] + usage["thoughts"]) * PRICE_OUT
    ) / 1e6


def label(workers: int, max_cost: float, missing: bool) -> None:
    frame = pl.read_parquet(
        WORKING / "texts.parquet", columns=["text_id", "texto_sanitizado"]
    ).sort("text_id")
    ids, texts = frame["text_id"].to_list(), frame["texto_sanitizado"].to_list()
    slices = {
        n: (ids[s : s + BATCH], texts[s : s + BATCH])
        for n, s in enumerate(range(0, len(ids), BATCH))
    }
    OUT.mkdir(parents=True, exist_ok=True)
    records: dict[int, dict] = {}
    if CHECKPOINT.exists():
        if not missing:
            raise SystemExit(
                f"{CHECKPOINT} ya existe: usa --solo-faltantes para completar"
            )
        for line in CHECKPOINT.read_text().splitlines():
            r = json.loads(line)
            if (
                r["batch"] in slices
                and r["ids"] == slices[r["batch"]][0]
                and not r["usage"]["error"]
            ):
                records[r["batch"]] = r
    config = {
        "parse": parse,
        "config": types.GenerateContentConfig(
            system_instruction=(PROMPTS / f"{PROMPT}.md").read_text(),
            temperature=0,
            response_mime_type="text/plain",
            thinking_config=THINKING,
            max_output_tokens=4096,
        ),
    }
    client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
    run = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    def work(n: int) -> dict:
        batch_ids, batch_texts = slices[n]
        batch = pl.DataFrame(
            {"pilot_id": range(len(batch_ids)), "texto_sanitizado": batch_texts}
        )
        items, usage = label_batch(client, batch, config)
        out = [
            {
                "text_id": batch_ids[x["i"]],
                "codes": x["codes"],
                "actualizacion": x["u"],
                "seguridad": x["s"],
                "elogio": x["m"],
            }
            for x in items
        ]
        return {"batch": n, "ids": batch_ids, "items": out, "usage": usage}

    # El tope aplica al gasto de esta corrida; el total real se recalcula del
    # checkpoint (incluye los lotes fallidos, que también se pagan).
    spent = 0.0
    pending = [n for n in slices if n not in records]
    stopped = None
    with (
        CHECKPOINT.open("a") as sink,
        ThreadPoolExecutor(max_workers=workers) as pool,
    ):
        futures = [pool.submit(work, n) for n in pending]
        for future in as_completed(futures):
            r = future.result()
            records[r["batch"]] = r
            spent += cost_of(r["usage"])
            sink.write(json.dumps(r, ensure_ascii=False) + "\n")
            sink.flush()
            print(
                json.dumps(
                    {
                        "batch": r["batch"],
                        "error": r["usage"]["error"],
                        "spent_usd": round(spent, 4),
                        "done": len(records),
                        "of": len(slices),
                    }
                ),
                flush=True,
            )
            ok = sum(1 for x in records.values() if not x["usage"]["error"])
            if r["usage"]["error"] and ok == 0:
                stopped = f"primer lote fallido: {r['usage']['error']}"
            elif spent > max_cost:
                stopped = f"tope de gasto ({max_cost} USD) alcanzado"
            if stopped:
                pool.shutdown(wait=True, cancel_futures=True)
                break
    if stopped:
        print(f"Corrida detenida: {stopped}")

    good = {n: r for n, r in records.items() if not r["usage"]["error"]}
    labels = pl.DataFrame(
        [item for r in good.values() for item in r["items"]], schema=SCHEMA
    ).sort("text_id")
    labels.write_parquet(OUT / f"labels_{PROMPT}.parquet")
    batches = [
        {"batch": n, "texts": len(r["ids"]), **r["usage"]}
        for n, r in sorted(records.items())
    ]
    meta = {
        "run": run,
        "model": MODEL,
        "location": LOCATION,
        "prompt": PROMPT,
        "batch_size": BATCH,
        "workers": workers,
        "texts": frame.height,
        "labeled": labels.height,
        "failed_batches": sum(1 for b in batches if b["error"]),
        "pending_batches": len(slices) - len(good),
        "cost_usd_this_run": round(spent, 5),
        "cost_usd_total": round(
            sum(
                cost_of(json.loads(line)["usage"])
                for line in CHECKPOINT.read_text().splitlines()
            ),
            5,
        ),
        "stopped": stopped,
        "batches": batches,
    }
    (OUT / f"run_{PROMPT}_{run}.json").write_text(
        json.dumps(meta, indent=2) + "\n"
    )
    print({k: v for k, v in meta.items() if k != "batches"})


def families(col: str = "codes") -> pl.Expr:
    return (
        pl.col(col)
        .fill_null("")
        .str.split(",")
        .list.eval(pl.element().filter(pl.element() != ""))
    )


def summary() -> None:
    from sklearn.metrics import cohen_kappa_score

    labels = pl.read_parquet(OUT / f"labels_{PROMPT}.parquet").with_columns(
        f=families()
    )
    eda = pl.read_parquet(EDA_LABELS).with_columns(f=families())
    j = labels.join(eda, on="text_id", suffix="_eda")
    repro = {
        "textos": j.height,
        "acuerdo_exacto": round(
            float((j["codes"] == j["codes_eda"]).mean()), 4
        ),
        "kappa_por_codigo": {
            c: round(
                float(
                    cohen_kappa_score(
                        j["f"].list.contains(c), j["f_eda"].list.contains(c)
                    )
                ),
                3,
            )
            for c in CODES
        },
        "kappa_u": round(
            float(
                cohen_kappa_score(j["actualizacion"], j["actualizacion_eda"])
            ),
            3,
        ),
    }
    rows = pl.read_parquet(
        WORKING / "rows.parquet", columns=["text_id", "peso"]
    )
    x = rows.join(labels, on="text_id")
    w = x["peso"]

    def share(mask: pl.Series) -> float:
        return round(float((mask.cast(pl.Float64) * w).sum() / w.sum()), 4)

    runs = sorted(OUT.glob(f"run_{PROMPT}_*.json"))
    last = json.loads(runs[-1].read_text())
    metrics = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "prompt": PROMPT,
        "model": MODEL,
        "textos": labels.height,
        "corridas": len(runs),
        "costo_usd_total": last["cost_usd_total"],
        "reproducibilidad_contra_5_2": repro,
        "poblacion_filas_neg": {
            "filas_estimadas": round(float(w.sum())),
            "multi_aspecto": share(x["f"].list.len() > 1),
            "sin_problema": share(x["f"].list.len() == 0),
            "u": share(x["actualizacion"]),
            "s": share(x["seguridad"]),
            "familias": {c: share(x["f"].list.contains(c)) for c in CODES},
        },
    }
    METRICS.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(metrics, ensure_ascii=False, indent=1))


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    lab = sub.add_parser("label")
    lab.add_argument("--workers", type=int, default=8)
    lab.add_argument("--max-cost", type=float, default=5.0)
    lab.add_argument("--solo-faltantes", action="store_true")
    sub.add_parser("summary")
    a = p.parse_args()
    if a.cmd == "summary":
        summary()
    else:
        label(a.workers, a.max_cost, a.solo_faltantes)


if __name__ == "__main__":
    main()
