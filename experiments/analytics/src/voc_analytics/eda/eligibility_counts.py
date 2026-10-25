"""Conteos de `eligibility_rules_v1` por banco × periodo × motivo (5.8, P8-4).

Aplica las reglas aprobadas en 5.8 (`labeling.eligibility.with_tnss_rule_v1`)
al snapshot del TDS y escribe los conteos que publica
`docs/analytics/eda/eligibility_rules.md`.

* **TNSS:** cada fila queda `ELEGIBLE` (con `MODEL` o `RULE_BASED` como
  fuente) o con el código de la regla que la excluye.
* **Tópicos y familias:** sobre las filas con TNSS, `TOPIC_NOT_NEGATIVE` usa
  el sentimiento **predicho**: la etiqueta del léxico o la clase de
  `M4_robertuito_s1_ppi` (la de producción) del backfill de 5.8, unida por
  `text_key` (SHA-256 de `texto_sanitizado`). La T no cambia la clase.
* **Léxico congelado:** se reconstruye con `eda.eda_lexicon.build_lexicon`
  (mismos parámetros que la sección 5.3 del EDA) y se guarda en
  `data/eda/lexicon_v1.parquet` (fuera de git); el JSON registra su SHA-256 y
  el número de formas por etiqueta.

Escribe `docs/analytics/eda/eligibility_v1_counts.json`, solo agregados.

    uv run python -m voc_analytics.eda.eligibility_counts \\
        data/tds_20261016T054714Z.parquet
"""

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from voc_analytics.eda.eda_lexicon import build_lexicon
from voc_analytics.labeling.eligibility import (
    RULES_VERSION_V1,
    with_tnss_rule_v1,
)
from voc_analytics.paths import DATA, DOCS
from voc_analytics.sampling.strata import period

OUT = DOCS / "eda" / "eligibility_v1_counts.json"
LEXICON = DATA / "eda" / "lexicon_v1.parquet"
PREDS = DATA / "backfill" / "20261022" / "preds" / "preds_s1.parquet"
CLASSES = ["NEG", "NEU", "POS"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def table(df: pl.DataFrame, col: str) -> dict:
    total = df.height
    by = df.group_by(col).len().sort("len", descending=True)
    return {
        "filas": total,
        "por_motivo": {
            k: {"filas": n, "proporcion": round(n / total, 5)}
            for k, n in by.iter_rows()
        },
    }


def breakdown(df: pl.DataFrame, col: str) -> list[dict]:
    rows = (
        df.group_by("bank_id", "periodo", col)
        .len()
        .sort("bank_id", "periodo", col)
    )
    return [
        {"bank_id": b, "periodo": p, "motivo": m, "filas": n}
        for b, p, m, n in rows.iter_rows()
    ]


def main(path: str) -> None:
    lexicon, meta = build_lexicon()
    LEXICON.parent.mkdir(parents=True, exist_ok=True)
    lexicon.write_parquet(LEXICON)

    snap = pl.read_parquet(
        path,
        columns=["bank_id", "fecha", "texto_limpio", "texto_sanitizado"],
    )
    df = with_tnss_rule_v1(snap, lexicon).with_columns(
        periodo=period(),
        tnss=pl.coalesce(
            "tnss_rule",
            pl.when(pl.col("lexico").is_not_null())
            .then(pl.lit("ELEGIBLE_RULE_BASED"))
            .otherwise(pl.lit("ELEGIBLE_MODEL")),
        ),
    )

    # Sentimiento predicho para la tarea de tópicos.
    model = df.filter(pl.col("tnss") == "ELEGIBLE_MODEL")
    keys = model.select("texto_sanitizado").unique()
    keys = keys.with_columns(
        text_key=pl.col("texto_sanitizado").map_elements(
            lambda t: hashlib.sha256(t.encode()).hexdigest(),
            return_dtype=pl.String,
        )
    )
    preds = pl.read_parquet(PREDS).select(
        "text_key",
        m4=pl.concat_list("p_NEG", "p_NEU", "p_POS")
        .list.arg_max()
        .replace_strict(dict(enumerate(CLASSES)), return_dtype=pl.String),
    )
    keys = keys.join(preds, on="text_key", how="left")
    df = df.join(
        keys.select("texto_sanitizado", "m4"),
        on="texto_sanitizado",
        how="left",
    ).with_columns(
        sentimiento=pl.when(pl.col("tnss") == "ELEGIBLE_RULE_BASED")
        .then(pl.col("lexico"))
        .when(pl.col("tnss") == "ELEGIBLE_MODEL")
        .then(pl.col("m4"))
    )
    missing = int(
        df.filter(
            (pl.col("tnss") == "ELEGIBLE_MODEL") & pl.col("m4").is_null()
        ).height
    )
    df = df.with_columns(
        topic=pl.when(~pl.col("tnss").str.starts_with("ELEGIBLE"))
        .then(pl.lit("TOPIC_TNSS_NOT_PREDICTED"))
        .when(pl.col("sentimiento").is_null())
        .then(pl.lit("SIN_PREDICCION_EN_BACKFILL"))
        .when(pl.col("sentimiento") != "NEG")
        .then(pl.lit("TOPIC_NOT_NEGATIVE"))
        .when(pl.col("palabras") <= 1)
        .then(pl.lit("TOPIC_TOO_SHORT"))
        .otherwise(pl.lit("ELEGIBLE"))
    )

    result = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "version": RULES_VERSION_V1,
        "snapshot_file": Path(path).name,
        "lexico": {
            "archivo": LEXICON.name,
            "sha256": sha256(LEXICON),
            **meta,
        },
        "prediccion_topicos": {
            "modelo": "M4_robertuito_s1_ppi",
            "backfill": "20261022",
            "filas_modelo_sin_prediccion": missing,
        },
        "tnss": table(df, "tnss"),
        "tnss_por_banco": {
            b: table(g, "tnss")
            for (b,), g in sorted(df.group_by("bank_id"), key=lambda x: x[0])
        },
        "tnss_por_banco_periodo": breakdown(df, "tnss"),
        "topicos": table(df, "topic"),
        "topicos_por_banco": {
            b: table(g, "topic")
            for (b,), g in sorted(df.group_by("bank_id"), key=lambda x: x[0])
        },
        "topicos_por_banco_periodo": breakdown(df, "topic"),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {k: result[k] for k in ("lexico", "prediccion_topicos", "tnss")},
            ensure_ascii=False,
            indent=2,
        )
    )
    print(json.dumps(result["topicos"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
