"""Priorización (Q4) contra un criterio observable (5.6).

Las fórmulas de la especificación anterior (`priority_weight_score`) son
hipótesis. Aquí se comparan varias puntuaciones por su capacidad de poner
arriba los 3 incidentes conocidos de BBVA (2024-07, 2025-10 y 2025-11, los
mismos de 5.5). Con 3 incidentes la prueba es ilustrativa, no un ajuste.

* **Datos:** la plata `silver_v0` completa (Gemini `prompt_v3`), con 1 / π
  para estimar totales de población; las familias `aspects_v2_1` y la marca
  `u` de las 40 382 negativas codificadas en 5.5; los votos de utilidad del
  snapshot.
* **Puntuaciones por banco × mes** (sumas ponderadas sobre las reseñas):
  * `volumen_neg`: reseñas `NEG`;
  * `proporcion_neg`: `NEG` sobre el total del mes;
  * `formula_anterior`: (1[`NEG`] + 0.5 · 1[4–5★ y `NEG`]) ·
    (1 + ln(1 + votos)), la de la especificación anterior, con
    p(`NEG`) = 1[`NEG`] porque Gemini no da probabilidades;
  * `votos_neg`: `NEG` · ln(1 + votos);
  * `volumen_u` y `proporcion_u`: negativas con la marca `u` (actualización);
  * `formula_con_u`: la anterior multiplicada por (1 + 1[`u`]).
* **Dos lecturas:** el nivel del mes y su anomalía (z robusto contra los 12
  meses previos, como la señal de 5.5).
* **Criterio A, qué mes atender:** el rango de cada mes de incidente entre
  los meses de BBVA desde 2022-01, y la precisión en los 3 primeros.
* **Criterio B, qué atender dentro del mes:** en cada mes de incidente, el
  orden de las familias y de la marca `u` por volumen y por la fórmula
  anterior; la causa esperada (de 5.5) es `u` en 2024-07 y `UX` o `DV` en
  2025-10 y 2025-11.
* **Límite:** los votos se acumulan con el tiempo, así que favorecen los
  meses viejos; la plata tiene una mediana de 57 filas por banco y mes.

Escribe `docs/analytics/calibration/priority_v0_metrics.json`, solo
agregados.

    uv run python -m voc_analytics.calibration.priority
"""

import json
from datetime import UTC, datetime

import numpy as np
import polars as pl

from voc_analytics.paths import DATA, DOCS
from voc_analytics.sentiment.data import SILVER, snapshot

OUT = DOCS / "calibration" / "priority_v0_metrics.json"
ASPECTS = DATA / "topics" / "aspects_scale_v0" / "labels_aspects_v2_1.parquet"
INCIDENTS = {"2024-07": {"u"}, "2025-10": {"UX", "DV"}, "2025-11": {"UX", "DV"}}
FROM_MONTH = "2022-01"
BASELINE_MONTHS = 12
MIN_BASELINE = 6
SCORES = [
    "volumen_neg",
    "proporcion_neg",
    "formula_anterior",
    "votos_neg",
    "volumen_u",
    "proporcion_u",
    "formula_con_u",
]


def rows() -> pl.DataFrame:
    base = pl.read_parquet(SILVER / "rows.parquet").select(
        "id_resena",
        "bank_id",
        "estrellas",
        "fecha",
        "prob_inclusion",
        "text_id",
    )
    labels = pl.read_parquet(SILVER / "labels_prompt_v3.parquet").select(
        "text_id", pl.col("gemini_s").alias("pred")
    )
    aspects = pl.read_parquet(ASPECTS).select(
        "text_id", "codes", pl.col("actualizacion").alias("u")
    )
    votes = snapshot(base["id_resena"], ["votos_utilidad"])
    return (
        base.join(labels, on="text_id")
        .join(aspects, on="text_id", how="left")
        .join(votes, on="id_resena", how="left")
        .with_columns(
            mes=pl.col("fecha").dt.strftime("%Y-%m"),
            w=1 / pl.col("prob_inclusion"),
            neg=(pl.col("pred") == "NEG").cast(pl.Float64),
            u=pl.col("u").fill_null(False).cast(pl.Float64),
            lv=(1 + pl.col("votos_utilidad").fill_null(0)).log(),
        )
        .with_columns(
            u=pl.col("u") * pl.col("neg"),
            old=(
                pl.col("neg") + 0.5 * pl.col("neg") * (pl.col("estrellas") >= 4)
            )
            * (1 + pl.col("lv")),
        )
    )


def monthly(df: pl.DataFrame) -> pl.DataFrame:
    w = pl.col("w")
    return (
        df.group_by("bank_id", "mes")
        .agg(
            total=w.sum(),
            volumen_neg=(w * pl.col("neg")).sum(),
            formula_anterior=(w * pl.col("old")).sum(),
            votos_neg=(w * pl.col("neg") * pl.col("lv")).sum(),
            volumen_u=(w * pl.col("u")).sum(),
            formula_con_u=(w * pl.col("old") * (1 + pl.col("u"))).sum(),
            filas=pl.len(),
        )
        .with_columns(
            proporcion_neg=pl.col("volumen_neg") / pl.col("total"),
            proporcion_u=pl.col("volumen_u")
            / pl.col("volumen_neg").clip(lower_bound=1e-9),
        )
        .sort("bank_id", "mes")
    )


def robust_z(values: np.ndarray) -> np.ndarray:
    z = np.full(len(values), np.nan)
    for i in range(len(values)):
        hist = values[max(0, i - BASELINE_MONTHS) : i]
        if len(hist) < MIN_BASELINE:
            continue
        med = np.median(hist)
        mad = 1.4826 * np.median(np.abs(hist - med))
        z[i] = (values[i] - med) / max(mad, 1e-9 + 0.01 * max(abs(med), 1e-9))
    return z


def month_ranking(m: pl.DataFrame) -> dict:
    bbva = m.filter(pl.col("bank_id") == "BBVA").sort("mes")
    out = {}
    for score in SCORES:
        vals = bbva[score].to_numpy()
        for view, series in (("nivel", vals), ("anomalia", robust_z(vals))):
            frame = bbva.select("mes").with_columns(v=pl.Series(series))
            frame = frame.filter(
                (pl.col("mes") >= FROM_MONTH) & pl.col("v").is_not_nan()
            ).sort("v", descending=True)
            order = frame["mes"].to_list()
            ranks = {
                mes: (order.index(mes) + 1 if mes in order else None)
                for mes in INCIDENTS
            }
            top3 = set(order[:3])
            out[f"{score}|{view}"] = {
                "meses": len(order),
                "rango_incidentes": ranks,
                "precision_en_3": round(len(top3 & set(INCIDENTS)) / 3, 3),
                "rango_medio": round(
                    float(np.mean([r for r in ranks.values() if r])), 2
                ),
            }
    return out


def within_month(df: pl.DataFrame) -> dict:
    out = {}
    neg = df.filter((pl.col("bank_id") == "BBVA") & (pl.col("neg") == 1))
    for mes, expected in INCIDENTS.items():
        g = neg.filter(pl.col("mes") == mes)
        fam = (
            g.filter(pl.col("codes").is_not_null())
            .with_columns(pl.col("codes").str.split(","))
            .explode("codes")
            .filter(pl.col("codes") != "")
            .group_by(pl.col("codes").alias("categoria"))
            .agg(
                volumen=pl.col("w").sum(),
                formula_anterior=(pl.col("w") * pl.col("old")).sum(),
            )
        )
        u = g.filter(pl.col("u") == 1).select(
            pl.lit("u").alias("categoria"),
            pl.col("w").sum().alias("volumen"),
            (pl.col("w") * pl.col("old")).sum().alias("formula_anterior"),
        )
        cats = pl.concat([fam, u])
        entry = {"filas_neg": g.height, "esperado": sorted(expected)}
        for score in ("volumen", "formula_anterior"):
            order = cats.sort(score, descending=True)["categoria"].to_list()
            rank = min(
                (order.index(c) + 1 for c in expected if c in order),
                default=None,
            )
            entry[score] = {"orden": order[:5], "rango_esperado": rank}
        out[mes] = entry
    return out


def main() -> None:
    df = rows()
    m = monthly(df)
    result = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "filas": df.height,
        "filas_por_mes_bbva_mediana": float(
            m.filter(pl.col("bank_id") == "BBVA")["filas"].median()
        ),
        "incidentes": {k: sorted(v) for k, v in INCIDENTS.items()},
        "desde": FROM_MONTH,
        "criterio_a_mes": month_ranking(m),
        "criterio_b_dentro_del_mes": within_month(df),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"escrito {OUT}", flush=True)


if __name__ == "__main__":
    main()
