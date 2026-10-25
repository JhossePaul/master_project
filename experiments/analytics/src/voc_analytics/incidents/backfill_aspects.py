"""Backfill de las familias `aspects_v2_1` con Gemini (5.9, P9-3).

Decisión del autor (2026-10-22): etiquetar todas las negativas del corpus,
porque la señal diaria de 5.9 necesita la marca `u` y la familia dominante
por episodio, y porque el llenado histórico (P8-7) hará falta de todos modos.
Los artefactos se conservan para cargarlos en EPIC-6 (6.3).

* **Textos:** los textos únicos del snapshot que son negativas para familias
  (`NEG` de `M4_robertuito_s1_ppi` con dos palabras o más;
  `incidents.prepare`), con su `text_key` (SHA-256 de `texto_sanitizado`).
  Los textos que entraron al TDS después del snapshot quedan para el delta
  de EPIC-6.
* **Etiquetado:** el mismo prompt, modelo y lotes que 5.5 y 5.7
  (`topics.aspects_scale.label`), en Vertex AI dentro del proyecto (F-10).
  Se etiquetan todos, también los que ya tenían etiqueta en la plata o en
  `ppi_v0`, para que el backfill salga de una sola corrida; esos textos
  miden la reproducibilidad entre corridas.

Subcomandos:

* `texts`: arma `texts.parquet` (`text_id`, `text_key`, `texto_sanitizado`).
* `label`: etiqueta con un tope de gasto; `--solo-faltantes` completa los
  lotes fallidos.
* `summary`: escribe `labels_by_key.parquet` (etiquetas por `text_key`, la
  forma que carga 6.3) y
  `docs/analytics/incidents/backfill_aspects_v0_metrics.json`, solo
  agregados.

Escribe en `data/backfill/20261022/aspects/`, fuera de git.

    uv run python -m voc_analytics.incidents.backfill_aspects texts
    uv run python -m voc_analytics.incidents.backfill_aspects label \\
        --workers 12 --max-cost 70
    uv run python -m voc_analytics.incidents.backfill_aspects summary
"""

import argparse
import json
from datetime import UTC, datetime

import polars as pl

from voc_analytics.incidents.prepare import OUT as INCIDENTS
from voc_analytics.incidents.prepare import RUN, SAMPLES
from voc_analytics.paths import DATA, DOCS
from voc_analytics.topics.aspects_scale import (
    CODES,
    PROMPT,
    cost_of,
    families,
    label,
)

BACKFILL = DATA / "backfill" / RUN
OUT = BACKFILL / "aspects"
METRICS = DOCS / "incidents" / "backfill_aspects_v0_metrics.json"
FLAGS = ["actualizacion", "seguridad", "elogio"]


def texts() -> None:
    keys = (
        pl.read_parquet(
            INCIDENTS / "rows_v0.parquet", columns=["text_key", "neg_familias"]
        )
        .filter(pl.col("neg_familias"))
        .select("text_key")
        .unique()
    )
    corpus = pl.read_parquet(
        BACKFILL / "texts", columns=["text_key", "texto_sanitizado"]
    )
    frame = (
        keys.join(corpus, on="text_key")
        .sort("text_key")
        .with_row_index("text_id")
        .with_columns(pl.col("text_id").cast(pl.UInt32))
    )
    OUT.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(OUT / "texts.parquet")
    print({"negativas_unicas": keys.height, "con_texto": frame.height})


def reproducibility(labels: pl.DataFrame) -> dict:
    """Acuerdo con las etiquetas previas de 5.5 (plata) y 5.7 (`ppi_v0`)."""
    out = {}
    for name, (sample, aspects) in SAMPLES.items():
        prev = (
            pl.read_parquet(sample / "texts.parquet")
            .select("text_id", "texto_sanitizado")
            .join(
                pl.read_parquet(aspects / f"labels_{PROMPT}.parquet"),
                on="text_id",
            )
            .drop("text_id")
        )
        j = labels.join(
            prev, on="texto_sanitizado", suffix="_prev"
        ).with_columns(fam=families(), fam_prev=families("codes_prev"))
        exact = j.filter(
            pl.col("fam").list.sort() == pl.col("fam_prev").list.sort()
        ).height
        out[name] = {
            "textos_comunes": j.height,
            "acuerdo_exacto_familias": round(exact / j.height, 4),
            "acuerdo_u": round(
                float((j["actualizacion"] == j["actualizacion_prev"]).mean()), 4
            ),
            "por_familia": {
                c: round(
                    float(
                        (
                            j["fam"].list.contains(c)
                            == j["fam_prev"].list.contains(c)
                        ).mean()
                    ),
                    4,
                )
                for c in CODES
            },
        }
    return out


def summary() -> None:
    frame = pl.read_parquet(OUT / "texts.parquet")
    labels = pl.read_parquet(OUT / f"labels_{PROMPT}.parquet")
    by_key = frame.join(labels, on="text_id")
    by_key.select("text_key", "codes", *FLAGS).with_columns(
        prompt=pl.lit(PROMPT)
    ).write_parquet(OUT / "labels_by_key.parquet")

    lines = (OUT / "checkpoint.jsonl").read_text().splitlines()
    usage = [json.loads(x)["usage"] for x in lines]
    fam = by_key.with_columns(fam=families())
    result = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "prompt": PROMPT,
        "backfill": RUN,
        "textos": frame.height,
        "etiquetados": labels.height,
        "faltantes": frame.height - labels.height,
        "lotes": len(usage),
        "lotes_fallidos": sum(1 for u in usage if u["error"]),
        "costo_usd": round(sum(cost_of(u) for u in usage), 2),
        "prevalencia_por_texto": {
            "u": round(float(fam["actualizacion"].mean()), 4),
            "s": round(float(fam["seguridad"].mean()), 4),
            "sin_familia": round(float((fam["fam"].list.len() == 0).mean()), 4),
            "multi_familia": round(
                float((fam["fam"].list.len() >= 2).mean()), 4
            ),
            "familias": {
                c: round(float(fam["fam"].list.contains(c).mean()), 4)
                for c in CODES
            },
        },
        "reproducibilidad": reproducibility(
            by_key.select("texto_sanitizado", "codes", "actualizacion")
        ),
    }
    METRICS.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("texts")
    lab = sub.add_parser("label")
    lab.add_argument("--workers", type=int, default=12)
    lab.add_argument("--max-cost", type=float, default=70.0)
    lab.add_argument("--solo-faltantes", action="store_true")
    sub.add_parser("summary")
    args = ap.parse_args()
    if args.cmd == "texts":
        texts()
    elif args.cmd == "label":
        frame = pl.read_parquet(
            OUT / "texts.parquet", columns=["text_id", "texto_sanitizado"]
        )
        label(args.workers, args.max_cost, args.solo_faltantes, frame, OUT)
    else:
        summary()


if __name__ == "__main__":
    main()
