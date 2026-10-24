"""Costo real de las familias con Gemini sobre las negativas de `ppi_v0` (5.7).

Decisión del autor (2026-10-22, P8-7): medir el costo real de etiquetar las
familias `aspects_v2_1` con Gemini, de forma informativa, antes del llenado
histórico en GCP. Etiqueta los textos únicos de `ppi_v0` que M4
(`M4_robertuito_s1_ppi`) predice como `NEG`, con el mismo prompt, modelo y
lotes que 5.5 (`topics.aspects_scale.label`). Las etiquetas sirven además
para el análisis por versión de 5.9 (P9-2).

* **label:** etiqueta con un tope de gasto (`--max-cost`, por defecto $6).
* **summary:** costo por 1 000 textos, tokens por texto y proyección al
  corpus: textos únicos `NEG` estimados como la proporción de la muestra por
  los 1 383 138 textos únicos.

Escribe en `data/scale/aspects_ppi_v0/` (fuera de git) y solo agregados en
`docs/analytics/scale/aspects_cost_v0_metrics.json`.

    uv run python -m voc_analytics.scale.aspects_ppi label --workers 8
    uv run python -m voc_analytics.scale.aspects_ppi summary
"""

import argparse
import json
from datetime import UTC, datetime

import polars as pl

from voc_analytics.paths import DATA, DOCS, LABELS
from voc_analytics.sentiment.data import PREDS
from voc_analytics.topics.aspects_scale import PROMPT, cost_of, label

OUT = DATA / "scale" / "aspects_ppi_v0"
METRICS = DOCS / "scale" / "aspects_cost_v0_metrics.json"
M4 = "M4_robertuito_s1_ppi"
CORPUS_UNIQUE_TEXTS = 1_383_138


def negatives() -> tuple[pl.DataFrame, int]:
    texts = pl.read_parquet(LABELS / "ppi_v0" / "texts.parquet").select(
        "text_id", "texto_sanitizado"
    )
    preds = pl.read_parquet(PREDS / f"{M4}__ppi.parquet").select(
        "text_id", "pred"
    )
    neg = texts.join(preds.filter(pl.col("pred") == "NEG"), on="text_id")
    return neg.select("text_id", "texto_sanitizado"), texts.height


def summary() -> None:
    neg, total = negatives()
    lines = (OUT / "checkpoint.jsonl").read_text().splitlines()
    usage = [json.loads(x)["usage"] for x in lines]
    ok = [u for u in usage if not u["error"]]
    texts = sum(
        len(json.loads(x)["ids"])
        for x in lines
        if not json.loads(x)["usage"]["error"]
    )
    cost = sum(cost_of(u) for u in usage)
    per_1000 = cost / texts * 1000
    share = neg.height / total
    projected = share * CORPUS_UNIQUE_TEXTS
    result = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "prompt": PROMPT,
        "textos_muestra": total,
        "textos_neg": neg.height,
        "proporcion_neg_textos_unicos": round(share, 4),
        "textos_etiquetados": texts,
        "lotes_fallidos": len(usage) - len(ok),
        "costo_usd": round(cost, 4),
        "costo_por_1000_textos_usd": round(per_1000, 4),
        "tokens_entrada_por_texto": round(
            sum(u["prompt"] for u in ok) / texts, 1
        ),
        "tokens_salida_por_texto": round(
            sum(u["output"] + u["thoughts"] for u in ok) / texts, 1
        ),
        "proyeccion_corpus": {
            "textos_unicos_neg": round(projected),
            "costo_usd": round(projected * per_1000 / 1000, 2),
            "nota": "textos únicos del corpus × proporción NEG de la muestra;"
            " el precio es el introductorio vigente hasta 2026-12-31",
        },
    }
    METRICS.parent.mkdir(parents=True, exist_ok=True)
    METRICS.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    lab = sub.add_parser("label")
    lab.add_argument("--workers", type=int, default=8)
    lab.add_argument("--max-cost", type=float, default=6.0)
    lab.add_argument("--solo-faltantes", action="store_true")
    sub.add_parser("summary")
    args = ap.parse_args()
    if args.cmd == "label":
        neg, _ = negatives()
        label(args.workers, args.max_cost, args.solo_faltantes, neg, OUT)
    else:
        summary()


if __name__ == "__main__":
    main()
