"""Preparación de 5.9: filas del snapshot con el sentimiento de producción.

Tarea 0 de 5.9 (`docs/backlog/epic_5.md`). Une el snapshot del TDS con el
backfill de M4 (`M4_robertuito_s1_ppi`, 5.8), aplica `eligibility_rules_v1`
y arma las series por banco y mes que usan las tareas 1 y 2.

* **Sentimiento:** la etiqueta del léxico para las reseñas de una palabra
  cubiertas y la clase de M4 `s1` para las demás elegibles, unida por
  `text_key` (SHA-256 de `texto_sanitizado`). La T no cambia la clase, así
  que aquí no se aplica; se guardan las probabilidades sin calibrar.
* **Negativas para familias:** `NEG` con dos palabras o más
  (`TOPIC_TOO_SHORT` con k = 1).
* **Familias y marca `u`** (muestras): las negativas de la plata (`NEG` de
  Gemini, 5.5) y de `ppi_v0` (`NEG` de M4, 5.7 §3) con `aspects_v2_1`. Solo
  entran las que también son negativas para familias con M4 `s1`, para que
  las dos muestras usen la misma definición; el JSON cuenta cuántas se
  pierden y cuántas negativas de M4 quedan sin familias. Cada fila pesa
  1 / π de su muestra; la proporción por banco y mes junta las dos, porque
  cada una estima la misma razón.
* **Series** por banco y mes: el mes de entrada al monitor de P7-9
  (`scale.drift_baseline.entry_months`) y el z robusto contra los 12 meses
  previos del volumen y de la proporción de `NEG`. El último mes del
  snapshot está incompleto y no se evalúa.

Escribe en `data/incidents/` (fuera de git) las filas, la muestra con
familias y las series, y `docs/analytics/incidents/prepare_v0_metrics.json`,
solo agregados.

    uv run python -m voc_analytics.incidents.prepare
"""

import hashlib
import json
import math
from datetime import UTC, datetime

import numpy as np
import polars as pl

from voc_analytics.labeling.eligibility import (
    RULES_VERSION_V1,
    with_tnss_rule_v1,
)
from voc_analytics.paths import DATA, DOCS, LABELS
from voc_analytics.scale.aspects_ppi import OUT as PPI_ASPECTS
from voc_analytics.scale.drift_baseline import MIN_ROWS, entry_months, robust_z
from voc_analytics.sentiment.data import SNAPSHOT
from voc_analytics.topics.aspects_scale import CODES, families
from voc_analytics.topics.aspects_scale import OUT as SILVER_ASPECTS

RUN = "20261022"
MODEL = "M4_robertuito_s1_ppi"
PREDS = DATA / "backfill" / RUN / "preds" / "preds_s1.parquet"
LEXICON = DATA / "eda" / "lexicon_v1.parquet"
OUT = DATA / "incidents"
METRICS = DOCS / "incidents" / "prepare_v0_metrics.json"
CLASSES = ["NEG", "NEU", "POS"]
SAMPLES = {
    "plata": (LABELS / "silver_v0", SILVER_ASPECTS),
    "ppi_v0": (LABELS / "ppi_v0", PPI_ASPECTS),
}
LABELS_FILE = "labels_aspects_v2_1.parquet"
MIN_SAMPLE = 30  # negativas con familias para reportar la proporción del mes
Z = 1.96


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def rows() -> tuple[pl.DataFrame, dict]:
    """Una fila por reseña del snapshot, con elegibilidad y sentimiento."""
    snap = pl.read_parquet(
        SNAPSHOT,
        columns=[
            "id_resena",
            "bank_id",
            "fecha",
            "version_app",
            "estrellas",
            "texto_limpio",
            "texto_sanitizado",
        ],
    )
    df = with_tnss_rule_v1(snap, pl.read_parquet(LEXICON))
    keys = (
        df.select("texto_sanitizado")
        .unique()
        .drop_nulls()
        .with_columns(
            text_key=pl.col("texto_sanitizado").map_elements(
                sha256, return_dtype=pl.String
            )
        )
        .join(pl.read_parquet(PREDS), on="text_key", how="left")
    )
    df = df.join(keys, on="texto_sanitizado", how="left")
    m4 = (
        pl.concat_list("p_NEG", "p_NEU", "p_POS")
        .list.arg_max()
        .replace_strict(dict(enumerate(CLASSES)), return_dtype=pl.String)
    )
    eligible = pl.col("tnss_rule").is_null()
    df = df.with_columns(
        mes=pl.col("fecha").dt.strftime("%Y-%m"),
        fuente=pl.when(~eligible)
        .then(None)
        .when(pl.col("lexico").is_not_null())
        .then(pl.lit("RULE_BASED"))
        .otherwise(pl.lit("MODEL")),
        sentimiento=pl.when(~eligible)
        .then(None)
        .when(pl.col("lexico").is_not_null())
        .then(pl.col("lexico"))
        .otherwise(m4),
    ).with_columns(
        neg_familias=(pl.col("sentimiento") == "NEG")
        & (pl.col("palabras") >= 2)
    )
    model = df.filter(pl.col("fuente") == "MODEL")
    coverage = {
        "filas": df.height,
        "textos_unicos": keys.height,
        "textos_sin_prediccion": int(keys["p_NEG"].null_count()),
        "filas_modelo": model.height,
        "filas_modelo_sin_prediccion": int(model["p_NEG"].null_count()),
    }
    return (
        df.drop("texto_limpio", "texto_sanitizado", "lexico").with_columns(
            neg_familias=pl.col("neg_familias").fill_null(False)
        ),
        coverage,
    )


def sample(df: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    """Negativas de las dos muestras con familias, pesadas por 1 / π."""
    m4 = df.select("id_resena", "mes", "neg_familias")
    parts, info = [], {}
    for name, (labels, aspects) in SAMPLES.items():
        r = pl.read_parquet(
            labels / "rows.parquet",
            columns=["id_resena", "bank_id", "prob_inclusion", "text_id"],
        ).join(m4, on="id_resena", how="left")
        a = pl.read_parquet(aspects / LABELS_FILE)
        j = r.join(a, on="text_id")
        missing = r.filter(pl.col("neg_familias")).join(
            a, on="text_id", how="anti"
        )
        info[name] = {
            "filas_muestra": r.height,
            "filas_sin_snapshot": int(r["mes"].null_count()),
            "filas_con_familias": j.height,
            "filas_con_familias_neg_m4": int(j["neg_familias"].sum()),
            "filas_neg_m4_sin_familias": missing.height,
        }
        parts.append(
            j.filter(pl.col("neg_familias")).select(
                "id_resena",
                "bank_id",
                "mes",
                "codes",
                fuente=pl.lit(name),
                w=1 / pl.col("prob_inclusion"),
                u=pl.col("actualizacion"),
                s=pl.col("seguridad"),
            )
        )
    return pl.concat(parts), info


def wilson(p: float | None, n: float) -> list | None:
    if p is None or n <= 0:
        return None
    den = 1 + Z**2 / n
    mid = (p + Z**2 / (2 * n)) / den
    half = Z * math.sqrt(p * (1 - p) / n + Z**2 / (4 * n**2)) / den
    return [round(mid - half, 4), round(mid + half, 4)]


def monthly(df: pl.DataFrame, samp: pl.DataFrame) -> pl.DataFrame:
    """Series por banco y mes, sin huecos entre el primer y el último mes."""
    base = df.group_by("bank_id", "mes").agg(
        filas=pl.len(),
        con_sentimiento=pl.col("sentimiento").is_not_null().sum(),
        neg=(pl.col("sentimiento") == "NEG").sum(),
        neg_familias=pl.col("neg_familias").sum(),
    )
    fam = (
        samp.with_columns(fam=families())
        .group_by("bank_id", "mes")
        .agg(
            n_muestra=pl.len(),
            n_efectivo=pl.col("w").sum() ** 2 / (pl.col("w") ** 2).sum(),
            u=(pl.col("w") * pl.col("u")).sum() / pl.col("w").sum(),
            s=(pl.col("w") * pl.col("s")).sum() / pl.col("w").sum(),
            **{
                c: (pl.col("w") * pl.col("fam").list.contains(c)).sum()
                / pl.col("w").sum()
                for c in CODES
            },
        )
    )
    months = month_range(df["mes"].min(), df["mes"].max())
    grid = pl.DataFrame({"bank_id": sorted(df["bank_id"].unique())}).join(
        pl.DataFrame({"mes": months}), how="cross"
    )
    out = (
        grid.join(base, on=["bank_id", "mes"], how="left")
        .join(fam, on=["bank_id", "mes"], how="left")
        .with_columns(
            pl.col("filas", "con_sentimiento", "neg", "neg_familias")
            .fill_null(0)
            .cast(pl.Int64),
            pl.col("n_muestra").fill_null(0).cast(pl.Int64),
        )
        .with_columns(
            prop_neg=pl.when(pl.col("con_sentimiento") > 0).then(
                pl.col("neg") / pl.col("con_sentimiento")
            )
        )
        .sort("bank_id", "mes")
    )
    last = months[-1]
    z = []
    for _, g in out.group_by("bank_id", maintain_order=True):
        ok = (g["filas"] >= MIN_ROWS) & (g["mes"] != last)
        z.append(
            g.select("bank_id", "mes").with_columns(
                z_neg=pl.Series(
                    robust_z(
                        [
                            float(v) if k else None
                            for v, k in zip(g["neg"], ok, strict=True)
                        ]
                    ),
                    dtype=pl.Float64,
                ),
                z_prop_neg=pl.Series(
                    robust_z(
                        [
                            v if k else None
                            for v, k in zip(g["prop_neg"], ok, strict=True)
                        ]
                    ),
                    dtype=pl.Float64,
                ),
            )
        )
    return out.join(pl.concat(z), on=["bank_id", "mes"])


def month_range(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def distribution(df: pl.DataFrame) -> dict:
    total = df.height
    by = df.group_by(pl.col("sentimiento").fill_null("EXCLUIDA")).len()
    return {k: round(n / total, 4) for k, n in sorted(by.iter_rows())}


def bank_summary(series: pl.DataFrame, entry: dict) -> dict:
    """Cuánto sirve la muestra para la marca `u` desde el mes de entrada."""
    out = {}
    last = series["mes"].max()
    for b in sorted(entry):
        g = series.filter(
            (pl.col("bank_id") == b)
            & (pl.col("mes") >= entry[b])
            & (pl.col("mes") != last)
        )
        enough = g.filter(pl.col("n_muestra") >= MIN_SAMPLE)
        widths = [
            ci[1] - ci[0]
            for p, n in zip(enough["u"], enough["n_efectivo"], strict=True)
            if (ci := wilson(p, n))
        ]
        out[b] = {
            "mes_entrada": entry[b],
            "meses_evaluados": g.height,
            "filas": int(g["filas"].sum()),
            "neg_familias": int(g["neg_familias"].sum()),
            "neg_familias_en_muestra": int(g["n_muestra"].sum()),
            "meses_con_muestra_suficiente": enough.height,
            "n_muestra_mediana": float(g["n_muestra"].median()),
            "ancho_ic_u_mediano": round(float(np.median(widths)), 4)
            if widths
            else None,
            "meses_z_neg_ge_4": int((g["z_neg"] >= 4).sum()),
            "meses_z_prop_neg_ge_4": int((g["z_prop_neg"] >= 4).sum()),
        }
    return out


def by_source(samp: pl.DataFrame) -> dict:
    """Prevalencias ponderadas por muestra, para ver si son comparables."""
    out = {}
    for (name,), g in sorted(samp.group_by("fuente"), key=lambda x: x[0]):
        g = g.with_columns(fam=families())
        w = g["w"].sum()
        out[name] = {
            "filas": g.height,
            "u": round(float((g["w"] * g["u"]).sum() / w), 4),
            "s": round(float((g["w"] * g["s"]).sum() / w), 4),
            "familias": {
                c: round(
                    float((g["w"] * g["fam"].list.contains(c)).sum() / w), 4
                )
                for c in CODES
            },
        }
    return out


def main() -> None:
    df, coverage = rows()
    samp, info = sample(df)
    series = monthly(df, samp)
    months = month_range(series["mes"].min(), series["mes"].max())
    entry = entry_months(series.select("bank_id", "mes", "filas"), months)

    OUT.mkdir(parents=True, exist_ok=True)
    df.write_parquet(OUT / "rows_v0.parquet")
    samp.write_parquet(OUT / "sample_v0.parquet")
    series.write_parquet(OUT / "monthly_v0.parquet")

    neg = df.filter(pl.col("neg_familias"))
    result = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "snapshot_file": SNAPSHOT.name,
        "backfill": RUN,
        "modelo": MODEL,
        "reglas": RULES_VERSION_V1,
        "mes_parcial": months[-1],
        "cobertura": coverage,
        "sentimiento_por_fila": distribution(df),
        "sentimiento_por_banco": {
            b: distribution(g)
            for (b,), g in sorted(df.group_by("bank_id"), key=lambda x: x[0])
        },
        "negativas_para_familias": {
            "filas": neg.height,
            "textos_unicos": int(neg["text_key"].n_unique()),
        },
        "muestras": info,
        "muestra_total": {
            "filas": samp.height,
            "proporcion_de_negativas": round(samp.height / neg.height, 4),
        },
        "prevalencias_por_muestra": by_source(samp),
        "por_banco": bank_summary(series, entry),
        "parametros": {
            "min_filas_mes": MIN_ROWS,
            "min_muestra_mes": MIN_SAMPLE,
            "z_referencia": 4,
        },
    }
    METRICS.parent.mkdir(parents=True, exist_ok=True)
    METRICS.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
