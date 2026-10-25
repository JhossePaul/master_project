"""Línea base histórica del monitor de deriva sin etiquetas (5.7, P7-6).

Calcula hacia atrás, por banco y mes, las series que vigilaría el monitor de
EPIC-6 (6.4) y la tasa de alerta que daría cada umbral. Así se propone un
umbral por su costo en falsas alarmas, sin la lista de incidentes (5.9).

* **Periodo:** todo el histórico, sin un corte fijo (E3, conversación con el
  autor del 2026-10-22). Un banco × mes entra cuando tiene al menos
  `MIN_ROWS` filas y 6 de sus 12 meses previos también, así que cada banco
  empieza cuando su volumen lo permite (NUBANK, desde 2020). La tasa de
  alerta y la estabilidad del volumen se reportan por banco y por año, para
  que el periodo de referencia se elija con los datos.
* **Entrada** (snapshot completo): filas; palabras medias; proporción de
  textos de una palabra, de más de 60 palabras y no predecibles
  (`eligibility_rules_v0.1`); vocabulario fuera del entrenamiento (tokens que
  no aparecen en los textos de entrenamiento de la plata); PSI de la
  distribución de palabras contra los 12 meses previos.
* **Predicción** (muestras): proporción de `NEG` de Gemini en la plata y de M4
  (`M4_robertuito_s1_ppi`) en `ppi_v0`, ponderadas por 1 / π.
* **Alerta:** PSI ≥ umbral, o z robusto (mediana y MAD de los 12 meses
  previos) ≥ umbral. Meses con menos de `MIN_ROWS` filas no se evalúan.

Escribe `docs/analytics/scale/drift_baseline_v0_metrics.json`, solo
agregados.

    uv run python -m voc_analytics.scale.drift_baseline
"""

import json
from datetime import UTC, datetime

import numpy as np
import polars as pl

from voc_analytics.labeling.eligibility import with_tnss_rule
from voc_analytics.paths import DOCS, LABELS
from voc_analytics.sentiment.data import PREDS, SILVER, SNAPSHOT

OUT = DOCS / "scale" / "drift_baseline_v0_metrics.json"
START = "2011-01"
BASELINE = 12
MIN_ROWS = 200
MIN_SAMPLE = 30
BINS = [0, 1, 2, 5, 10, 20, 40, 60, 10_000]
Z_THRESHOLDS = [3.0, 4.0, 5.0]
PSI_THRESHOLDS = [0.1, 0.25]
M4 = "M4_robertuito_s1_ppi"


def words(col: str) -> pl.Expr:
    return pl.col(col).str.split(" ").list.len()


def training_vocab() -> set[str]:
    texts = pl.read_parquet(SILVER / "texts.parquet")
    rows = pl.read_parquet(SILVER / "rows.parquet").filter(
        pl.col("split") == "entrenamiento"
    )
    t = texts.join(rows.select("text_id").unique(), on="text_id")
    return set(
        t.select(pl.col("texto_sanitizado").str.to_lowercase().str.split(" "))
        .explode("texto_sanitizado")["texto_sanitizado"]
        .to_list()
    )


def input_monthly(vocab: set[str]) -> pl.DataFrame:
    raw = pl.read_parquet(
        SNAPSHOT,
        columns=[
            "id_resena",
            "bank_id",
            "texto_sanitizado",
            "texto_limpio",
            "fecha",
        ],
    )
    df = with_tnss_rule(raw).with_columns(
        mes=pl.col("fecha").dt.strftime("%Y-%m"),
        palabras=words("texto_limpio"),
        no_predecible=pl.col("tnss_rule").is_not_null()
        & (pl.col("tnss_rule") != "TNSS_SINGLE_WORD"),
    )
    df = df.filter(pl.col("mes") >= START)
    tokens = (
        df.select(
            "bank_id",
            "mes",
            pl.col("texto_sanitizado").str.to_lowercase().str.split(" "),
        )
        .explode("texto_sanitizado")
        .with_columns(fuera=~pl.col("texto_sanitizado").is_in(list(vocab)))
        .group_by("bank_id", "mes")
        .agg(vocab_fuera=pl.col("fuera").mean())
    )
    bins = df.with_columns(
        bin=pl.col("palabras")
        .cut(BINS[1:-1], left_closed=False)
        .cast(pl.String)
    )
    hist = bins.group_by("bank_id", "mes", "bin").len("n")
    base = (
        df.group_by("bank_id", "mes")
        .agg(
            filas=pl.len(),
            palabras_media=pl.col("palabras").mean(),
            una_palabra=(pl.col("palabras") == 1).mean(),
            mas_de_60=(pl.col("palabras") > 60).mean(),
            no_predecible=pl.col("no_predecible").mean(),
        )
        .join(tokens, on=["bank_id", "mes"])
        .sort("bank_id", "mes")
    )
    return base, hist


def psi_series(hist: pl.DataFrame, months: list[str], bank: str) -> list:
    h = hist.filter(pl.col("bank_id") == bank)
    labels = sorted(h["bin"].unique().to_list())
    mat = np.zeros((len(months), len(labels)))
    idx = {m: i for i, m in enumerate(months)}
    for m, b, n in h.select("mes", "bin", "n").iter_rows():
        if m in idx:
            mat[idx[m], labels.index(b)] = n
    out = []
    for i in range(len(months)):
        prev = mat[max(0, i - BASELINE) : i].sum(axis=0)
        if i < BASELINE or prev.sum() == 0 or mat[i].sum() == 0:
            out.append(None)
            continue
        p = np.clip(mat[i] / mat[i].sum(), 1e-4, None)
        q = np.clip(prev / prev.sum(), 1e-4, None)
        out.append(float(np.sum((p - q) * np.log(p / q))))
    return out


def robust_z(values: list) -> list:
    out = []
    for i, v in enumerate(values):
        hist = [x for x in values[max(0, i - BASELINE) : i] if x is not None]
        if v is None or len(hist) < BASELINE // 2:
            out.append(None)
            continue
        med = float(np.median(hist))
        mad = 1.4826 * float(np.median(np.abs(np.array(hist) - med)))
        out.append((v - med) / max(mad, 0.01 * max(abs(med), 1e-6), 1e-6))
    return out


def prediction_monthly() -> pl.DataFrame:
    silver = (
        pl.read_parquet(SILVER / "rows.parquet")
        .join(
            pl.read_parquet(SILVER / "labels_prompt_v3.parquet").select(
                "text_id", pl.col("gemini_s").alias("pred")
            ),
            on="text_id",
        )
        .select("bank_id", "fecha", "prob_inclusion", "pred")
        .with_columns(fuente=pl.lit("gemini_plata"))
    )
    ppi = (
        pl.read_parquet(LABELS / "ppi_v0" / "rows.parquet")
        .join(pl.read_parquet(PREDS / f"{M4}__ppi.parquet"), on="text_id")
        .select("bank_id", "fecha", "prob_inclusion", "pred")
        .with_columns(fuente=pl.lit("m4_ppi_v0"))
    )
    return (
        pl.concat([silver, ppi])
        .with_columns(
            mes=pl.col("fecha").dt.strftime("%Y-%m"),
            w=1 / pl.col("prob_inclusion"),
        )
        .filter(pl.col("mes") >= START)
        .group_by("fuente", "bank_id", "mes")
        .agg(
            n=pl.len(),
            neg=((pl.col("pred") == "NEG") * pl.col("w")).sum()
            / pl.col("w").sum(),
        )
        .sort("fuente", "bank_id", "mes")
    )


def entry_months(base: pl.DataFrame, months: list[str]) -> dict[str, str]:
    """Mes de entrada de cada banco al monitor (regla propuesta en P7-9).

    El primer mes que cierra 12 meses seguidos con al menos `MIN_ROWS`
    filas; desde ahí se cuentan sus alertas.
    """
    out = {}
    for b in base["bank_id"].unique().sort().to_list():
        g = base.filter(pl.col("bank_id") == b)
        rows = dict(zip(g["mes"], g["filas"], strict=True))
        run = 0
        for m in months:
            run = run + 1 if rows.get(m, 0) >= MIN_ROWS else 0
            if run == BASELINE:
                out[b] = m
                break
    return out


def bank_rates(series: dict, months: list[str], entry: dict) -> dict:
    """Tasa de alerta por banco desde su mes de entrada, y meses por año."""
    out = {}
    for name, per_bank in series.items():
        thresholds = PSI_THRESHOLDS if name.startswith("psi") else Z_THRESHOLDS
        out[name] = {}
        for b, vals in per_bank.items():
            if b not in entry:
                continue
            kept = [
                v
                for m, v in zip(months, vals, strict=True)
                if m > entry[b] and v is not None
            ]
            out[name][b] = (
                {"evaluables": len(kept)}
                | {
                    f"tasa_{t:g}": (
                        round(float(np.mean([abs(v) >= t for v in kept])), 4)
                        if kept
                        else None
                    )
                    for t in thresholds
                }
                | {
                    f"meses_por_anio_{t:g}": (
                        round(
                            12 * float(np.mean([abs(v) >= t for v in kept])), 1
                        )
                        if kept
                        else None
                    )
                    for t in thresholds
                }
            )
    return out


def alert_rates(series: dict, months: list[str]) -> dict:
    """Proporción de banco × mes evaluables con alerta, por umbral.

    Total, por banco y por año, para ver si algún periodo o banco alerta
    distinto.
    """
    years = [m[:4] for m in months]
    out = {}
    for name, per_bank in series.items():
        thresholds = PSI_THRESHOLDS if name.startswith("psi") else Z_THRESHOLDS

        def rate(vals: list, thresholds: list = thresholds) -> dict:
            return {"evaluables": len(vals)} | {
                f"tasa_{t:g}": (
                    round(float(np.mean([abs(v) >= t for v in vals])), 4)
                    if vals
                    else None
                )
                for t in thresholds
            }

        cells = [
            (b, years[i], v)
            for b, vals in per_bank.items()
            for i, v in enumerate(vals)
            if v is not None
        ]
        out[name] = {
            "total": rate([v for _, _, v in cells]),
            "por_banco": {
                b: rate([v for bb, _, v in cells if bb == b])
                for b in sorted(per_bank)
            },
            "por_anio": {
                y: rate([v for _, yy, v in cells if yy == y])
                for y in sorted({y for _, y, _ in cells})
            },
        }
    return out


def volume_stability(base: pl.DataFrame) -> dict:
    """Filas por mes y su coeficiente de variación, por banco y año."""
    g = (
        base.with_columns(anio=pl.col("mes").str.slice(0, 4))
        .group_by("bank_id", "anio")
        .agg(
            meses=pl.len(),
            filas_mes_mediana=pl.col("filas").median(),
            cv=pl.col("filas").std() / pl.col("filas").mean(),
        )
        .sort("bank_id", "anio")
    )
    return {
        b: {
            a: {
                "meses": m,
                "filas_mes_mediana": float(med),
                "cv": None if cv is None else round(float(cv), 3),
            }
            for _, a, m, med, cv in g.filter(pl.col("bank_id") == b).iter_rows()
        }
        for b in g["bank_id"].unique().sort().to_list()
    }


def main() -> None:
    print("vocabulario de entrenamiento", flush=True)
    vocab = training_vocab()
    print("series de entrada", flush=True)
    base, hist = input_monthly(vocab)
    months = sorted(base["mes"].unique().to_list())
    banks = sorted(base["bank_id"].unique().to_list())
    series: dict = {}
    for col in (
        "palabras_media",
        "una_palabra",
        "mas_de_60",
        "no_predecible",
        "vocab_fuera",
    ):
        series[f"z_{col}"] = {}
        for b in banks:
            g = base.filter(pl.col("bank_id") == b)
            vals = dict(zip(g["mes"], g[col], strict=True))
            rows = dict(zip(g["mes"], g["filas"], strict=True))
            raw = [
                vals.get(m) if rows.get(m, 0) >= MIN_ROWS else None
                for m in months
            ]
            series[f"z_{col}"][b] = robust_z(raw)
    series["psi_palabras"] = {}
    for b in banks:
        g = base.filter(pl.col("bank_id") == b)
        rows = dict(zip(g["mes"], g["filas"], strict=True))
        psi = psi_series(hist, months, b)
        series["psi_palabras"][b] = [
            v if rows.get(m, 0) >= MIN_ROWS else None
            for v, m in zip(psi, months, strict=True)
        ]
    print("series de predicción", flush=True)
    pred = prediction_monthly()
    for fuente in pred["fuente"].unique().sort().to_list():
        series[f"z_neg_{fuente}"] = {}
        for b in banks:
            g = pred.filter(
                (pl.col("fuente") == fuente) & (pl.col("bank_id") == b)
            )
            vals = dict(zip(g["mes"], g["neg"], strict=True))
            n = dict(zip(g["mes"], g["n"], strict=True))
            raw = [
                vals.get(m) if n.get(m, 0) >= MIN_SAMPLE else None
                for m in months
            ]
            series[f"z_neg_{fuente}"][b] = robust_z(raw)
    incidents = {}
    for name, per_bank in series.items():
        vals = per_bank.get("BBVA", [])
        incidents[name] = {
            m: (
                None
                if vals[months.index(m)] is None
                else round(vals[months.index(m)], 2)
            )
            for m in ("2024-07", "2025-10", "2025-11")
            if m in months
        }
    summary = {
        b: {
            "filas_por_mes_mediana": float(
                base.filter(pl.col("bank_id") == b)["filas"].median()
            ),
            "vocab_fuera_mediana": round(
                float(
                    base.filter(pl.col("bank_id") == b)["vocab_fuera"].median()
                ),
                4,
            ),
            "no_predecible_mediana": round(
                float(
                    base.filter(pl.col("bank_id") == b)[
                        "no_predecible"
                    ].median()
                ),
                4,
            ),
        }
        for b in banks
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "generado": datetime.now(UTC).isoformat(timespec="seconds"),
                "desde": START,
                "linea_base_meses": BASELINE,
                "minimo_filas_mes": MIN_ROWS,
                "minimo_muestra_mes": MIN_SAMPLE,
                "meses": len(months),
                "resumen_por_banco": summary,
                "estabilidad_del_volumen": volume_stability(base),
                "tasa_de_alerta": alert_rates(series, months),
                "entrada_por_banco": (entry := entry_months(base, months)),
                "tasa_por_banco_desde_entrada": bank_rates(
                    series, months, entry
                ),
                "valor_en_incidentes_bbva": incidents,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(f"escrito {OUT}", flush=True)


if __name__ == "__main__":
    main()
