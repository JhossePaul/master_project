"""Etiquetado de plata con Gemini en Vertex AI (EPIC-5, feature 5.3).

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.labeling.label_gemini \\
        <muestra.parquet> [versión]

`versión` es `prompt_v0` a `prompt_v3` (por defecto). Lee
`pilot_id` y `texto_sanitizado`, nunca las estrellas. Envía lotes con
temperatura 0 y razonamiento mínimo; cada versión fija su formato de salida,
su tamaño de lote y su guía (`VERSIONS`). Escribe junto a la muestra
`labels_<run>.parquet` y `run_<run>.json` (tokens, latencia, fallas y costo
estimado).
"""

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
from google import genai
from google.genai import types

PROJECT = "project-7bafd424-a385-4c05-b5b"
LOCATION = "global"
MODEL = "gemini-3.6-flash"
MAX_TEXT_CHARS = 2000
MAX_ATTEMPTS = 3
# USD por 1M tokens, precio introductorio de Vertex AI hasta 2026-12-31
# (estándar desde 2027: 1.50 / 7.50). Los tokens de razonamiento se cobran
# como salida.
PRICE_IN = 0.75
PRICE_OUT = 3.75
THINKING = types.ThinkingConfig(thinking_level="minimal")
SCHEMA_V0 = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "i": {"type": "INTEGER"},
            "s": {"type": "STRING", "enum": ["NEG", "NEU", "POS", "NA"]},
            "f": {"type": "BOOLEAN"},
            "d": {"type": "BOOLEAN"},
        },
        "required": ["i", "s", "f", "d"],
    },
}
LINE_V1 = re.compile(r"^\s*(\d+)\s+(NEG|NEU|POS|NA)\s+([01])\s*$")


def prompt(version: str) -> str:
    return (Path(__file__).parent / "prompts" / f"{version}.md").read_text()


def parse_v0(text: str) -> list[dict]:
    return json.loads(text)


def parse_v1(text: str) -> list[dict]:
    """Una línea `i etiqueta f` por texto; `d` no existe en v1."""
    items = []
    for line in text.splitlines():
        if match := LINE_V1.match(line):
            i, s, f = match.groups()
            items.append({"i": int(i), "s": s, "f": f == "1", "d": None})
    return items


# v0: JSON con esquema. v1: mismas reglas, salida compacta en texto y lotes
# de 100 para repartir la instrucción.
VERSIONS = {
    "prompt_v0": {
        "batch_size": 50,
        "parse": parse_v0,
        "config": types.GenerateContentConfig(
            system_instruction=prompt("prompt_v0"),
            temperature=0,
            response_mime_type="application/json",
            response_schema=SCHEMA_V0,
            thinking_config=THINKING,
            max_output_tokens=4096,
        ),
    },
    # v3: v2 con "bien" = POS y "ok" = NEU (`annotation_guideline_v2`).
    "prompt_v3": {
        "batch_size": 100,
        "parse": parse_v1,
        "guideline": "annotation_guideline_v2",
        "config": types.GenerateContentConfig(
            system_instruction=prompt("prompt_v3"),
            temperature=0,
            response_mime_type="text/plain",
            thinking_config=THINKING,
            max_output_tokens=4096,
        ),
    },
    # v2: formato de v1 con las reglas de `annotation_guideline_v1`.
    "prompt_v2": {
        "batch_size": 100,
        "parse": parse_v1,
        "guideline": "annotation_guideline_v1",
        "config": types.GenerateContentConfig(
            system_instruction=prompt("prompt_v2"),
            temperature=0,
            response_mime_type="text/plain",
            thinking_config=THINKING,
            max_output_tokens=4096,
        ),
    },
    "prompt_v1": {
        "batch_size": 100,
        "parse": parse_v1,
        "config": types.GenerateContentConfig(
            system_instruction=prompt("prompt_v1"),
            temperature=0,
            response_mime_type="text/plain",
            thinking_config=THINKING,
            max_output_tokens=4096,
        ),
    },
}


def as_line(i: int, text: str) -> str:
    flat = " ".join(text.split())[:MAX_TEXT_CHARS]
    return f"{i}\t{flat}"


def label_batch(
    client: genai.Client, batch: pl.DataFrame, version: dict
) -> tuple[list, dict]:
    ids = batch["pilot_id"].to_list()
    contents = "\n".join(
        as_line(i, t)
        for i, t in zip(ids, batch["texto_sanitizado"], strict=True)
    )
    usage = {
        "prompt": 0,
        "output": 0,
        "thoughts": 0,
        "cached": 0,
        "attempts": 0,
    }
    error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        usage["attempts"] = attempt
        start = time.monotonic()
        try:
            response = client.models.generate_content(
                model=MODEL, contents=contents, config=version["config"]
            )
        except Exception as exc:  # noqa: BLE001 - se registra y se reintenta
            error = f"{type(exc).__name__}: {str(exc)[:200]}"
            time.sleep(2**attempt)
            continue
        usage["latency_s"] = round(time.monotonic() - start, 2)
        meta = response.usage_metadata
        usage["prompt"] += meta.prompt_token_count or 0
        usage["output"] += meta.candidates_token_count or 0
        usage["thoughts"] += meta.thoughts_token_count or 0
        usage["cached"] += meta.cached_content_token_count or 0
        usage["model_version"] = response.model_version
        try:
            items = version["parse"](response.text or "")
        except (TypeError, json.JSONDecodeError) as exc:
            error = f"salida inválida: {exc}"
            continue
        got = {item["i"] for item in items}
        if got == set(ids) and len(items) == len(ids):
            usage["error"] = None
            return items, usage
        missing, extra = len(set(ids) - got), len(got - set(ids))
        error = f"ids no coinciden: faltan {missing}, sobran {extra}"
    usage["error"] = error
    return [], usage


def label_frame(
    sample: pl.DataFrame,
    prompt_version: str,
    id_col: str = "pilot_id",
    workers: int = 1,
    checkpoint: Path | None = None,
    max_cost_usd: float | None = None,
) -> tuple[pl.DataFrame, dict]:
    """Etiqueta `texto_sanitizado`; devuelve etiquetas por `id_col` y meta.

    * `workers`: peticiones en paralelo.
    * `checkpoint`: JSONL con un registro por lote terminado; al relanzar se
      omiten los lotes ya hechos (deben tener los mismos ids).
    * `max_cost_usd`: detiene la corrida si el costo acumulado lo supera.
    """
    version = VERSIONS[prompt_version]
    ids = sample[id_col].to_list()
    texts = sample["texto_sanitizado"].to_list()
    size = version["batch_size"]
    # Gemini recibe posiciones enteras dentro del lote; se traducen a `id_col`.
    slices = {
        n: (ids[start : start + size], texts[start : start + size])
        for n, start in enumerate(range(0, len(ids), size))
    }
    records: dict[int, dict] = {}
    if checkpoint and checkpoint.exists():
        for line in checkpoint.read_text().splitlines():
            record = json.loads(line)
            n = record["batch"]
            if n in slices and record["ids"] == slices[n][0]:
                if not record["usage"]["error"]:
                    records[n] = record
    client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
    run = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    def work(n: int) -> dict:
        batch_ids, batch_texts = slices[n]
        frame = pl.DataFrame(
            {"pilot_id": range(len(batch_ids)), "texto_sanitizado": batch_texts}
        )
        items, usage = label_batch(client, frame, version)
        for item in items:
            item["i"] = batch_ids[item["i"]]
        return {"batch": n, "ids": batch_ids, "items": items, "usage": usage}

    def cost_of(usage: dict) -> float:
        return (
            usage["prompt"] * PRICE_IN
            + (usage["output"] + usage["thoughts"]) * PRICE_OUT
        ) / 1e6

    spent = sum(cost_of(r["usage"]) for r in records.values())
    stopped = None
    pending = [n for n in slices if n not in records]
    sink = checkpoint.open("a") if checkpoint else None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, n): n for n in pending}
        for future in as_completed(futures):
            record = future.result()
            records[record["batch"]] = record
            spent += cost_of(record["usage"])
            if sink:
                sink.write(json.dumps(record, ensure_ascii=False) + "\n")
                sink.flush()
            print(
                json.dumps(
                    {"batch": record["batch"], **record["usage"]}
                    | {"spent_usd": round(spent, 4), "done": len(records)}
                )
            )
            ok = sum(1 for r in records.values() if not r["usage"]["error"])
            if record["usage"]["error"] and ok == 0:
                # Si los primeros lotes fallan, no gastar el resto.
                stopped = f"primer lote fallido: {record['usage']['error']}"
            elif max_cost_usd is not None and spent > max_cost_usd:
                stopped = f"tope de gasto ({max_cost_usd} USD) alcanzado"
            if stopped:
                pool.shutdown(wait=True, cancel_futures=True)
                break
    if sink:
        sink.close()
    if stopped:
        print(f"Corrida detenida: {stopped}")

    batches = [
        {"batch": n, "texts": len(r["ids"]), **r["usage"]}
        for n, r in sorted(records.items())
    ]
    labels = [item for r in records.values() for item in r["items"]]
    tokens = {
        k: sum(b[k] for b in batches)
        for k in ("prompt", "output", "thoughts", "cached")
    }
    cost = sum(cost_of(b) for b in batches)
    id_dtype = sample.schema[id_col]
    out = pl.DataFrame(
        {
            id_col: pl.Series([x["i"] for x in labels], dtype=id_dtype),
            "gemini_s": pl.Series([x["s"] for x in labels], dtype=pl.String),
            "gemini_falla": pl.Series(
                [x["f"] for x in labels], dtype=pl.Boolean
            ),
            "gemini_duda": pl.Series(
                [x["d"] for x in labels], dtype=pl.Boolean
            ),
        }
    )
    meta = {
        "run": run,
        "model": MODEL,
        "location": LOCATION,
        "prompt_version": prompt_version,
        "guideline_version": version.get(
            "guideline", "annotation_guideline_v0"
        ),
        "batch_size": size,
        "workers": workers,
        "texts": sample.height,
        "labeled": out.height,
        "failed_batches": sum(1 for b in batches if b["error"]),
        "pending_batches": len(slices) - len(records),
        "stopped": stopped,
        "tokens": tokens,
        "price_usd_per_1m": {"input": PRICE_IN, "output": PRICE_OUT},
        "cost_usd": round(cost, 5),
        "cost_usd_per_1k_texts": round(cost / max(out.height, 1) * 1000, 5),
        "batches": batches,
    }
    return out, meta


def main(path: str, prompt_version: str) -> None:
    sample = pl.read_parquet(path, columns=["pilot_id", "texto_sanitizado"])
    out, meta = label_frame(sample, prompt_version)
    folder = Path(path).parent
    out.write_parquet(folder / f"labels_{meta['run']}.parquet")
    (folder / f"run_{meta['run']}.json").write_text(
        json.dumps(meta, indent=2) + "\n"
    )
    print(
        json.dumps({k: v for k, v in meta.items() if k != "batches"}, indent=2)
    )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "prompt_v3")
