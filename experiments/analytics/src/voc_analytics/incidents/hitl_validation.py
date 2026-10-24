"""Validación única de la cola HITL con una semana real (5.9, heredada de 5.6).

Decisión del autor en 5.6 (2026-10-22): para la tesis basta medir el umbral
HITL en el oro *dev* y validarlo una vez con la cola de una semana real. En
5.9 (2026-10-22) el autor eligió el **modo ciego** y la **última semana
completa** del snapshot; la revisión la hace él en la app local.

* **Semana:** la última de lunes a domingo completa del snapshot.
* **Modelo y umbral:** `M4_robertuito_s1_ppi` con su T (`calibration`), y el
  umbral de probabilidad máxima calibrada que da el 90 % de cobertura en el
  oro *dev* aleatorio (ponderado por 1 / π, como `calibration.selective`). Es
  el umbral que usaría producción (`risk_policy`); la cobertura real de la
  semana se mide, no se fuerza.
* **Cola:** los textos únicos de la semana con sentimiento por modelo
  (`MODEL`) y confianza menor al umbral, sin los que están en el oro (el
  autor ya los anotó). Un ítem por texto, en orden aleatorio con semilla.
  Modo `ciego`: la app no muestra la predicción.

Subcomandos:

* `queue`: escribe `data/labels/hitl_v0/queue.parquet` (formato de la app de
  anotación) y `predictions.parquet` (la predicción de cada ítem, fuera de la
  vista del revisor).
* `summary`: después de anotar, compara la anotación con M4 y escribe
  `docs/analytics/incidents/hitl_validation_v0_metrics.json`, solo agregados:
  tasa de corrección con IC, por clase predicha, y tiempo por reseña.

Todo queda fuera de git salvo el JSON.

    uv run python -m voc_analytics.incidents.hitl_validation queue
    GOLD_DIR=hitl_v0 uv run streamlit run src/voc_analytics/annotation/app.py
    uv run python -m voc_analytics.incidents.hitl_validation summary
"""

import argparse
import json
import math
from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl

from voc_analytics.calibration.calibrate import apply, logits
from voc_analytics.calibration.selective import at_coverage
from voc_analytics.incidents.prepare import OUT as INCIDENTS
from voc_analytics.paths import DOCS, LABELS
from voc_analytics.sentiment.data import PREDS, gold, gold_ids

MODEL = "M4_robertuito_s1_ppi"
T = 1.6811  # `calibration_v0_metrics.json`, temperatura de `s1_ppi`
COVERAGE = 0.90
CLASSES = ["NEG", "NEU", "POS"]
OUT = LABELS / "hitl_v0"
METRICS = DOCS / "incidents" / "hitl_validation_v0_metrics.json"
SEED = 20261023
Z = 1.96
PAUSE = 120  # segundos: un registro más largo es una pausa, no lectura


def calibrated(proba: np.ndarray) -> np.ndarray:
    return apply(logits(proba), np.array([math.log(T)]))


def threshold() -> dict:
    """Umbral de confianza que da `COVERAGE` en el oro *dev* aleatorio."""
    dev = gold().filter(
        (pl.col("particion") == "dev")
        & (pl.col("oro") != "NA")
        & (pl.col("bloque_oro") == "aleatorio")
    )
    preds = pl.read_parquet(PREDS / f"{MODEL}__dev.parquet")
    j = dev.join(preds, on="item_id")
    proba = calibrated(j.select("p_NEG", "p_NEU", "p_POS").to_numpy())
    pred = np.array(CLASSES)[proba.argmax(axis=1)]
    err = (pred != j["oro"].to_numpy()).astype(float)
    return at_coverage(proba.max(axis=1), err, j["peso"].to_numpy(), COVERAGE)


def last_full_week(last: date) -> tuple[date, date]:
    end = last - timedelta(days=last.weekday() + 1)  # domingo anterior
    if last.weekday() == 6:
        end = last
    return end - timedelta(days=6), end


def queue() -> None:
    rows = pl.read_parquet(
        INCIDENTS / "rows_v0.parquet",
        columns=[
            "id_resena",
            "bank_id",
            "fecha",
            "text_key",
            "fuente",
            "p_NEG",
            "p_NEU",
            "p_POS",
        ],
    )
    start, end = last_full_week(rows["fecha"].max().date())
    week = rows.filter(
        pl.col("fecha").dt.date().is_between(start, end)
        & (pl.col("fuente") == "MODEL")
        & pl.col("p_NEG").is_not_null()
    )
    in_gold = week.filter(pl.col("id_resena").is_in(list(gold_ids())))[
        "text_key"
    ].unique()
    texts = (
        week.filter(~pl.col("text_key").is_in(in_gold.implode()))
        .sort("fecha")
        .group_by("text_key", maintain_order=True)
        .agg(
            pl.col("id_resena").first(),
            pl.col("bank_id").first(),
            pl.col("p_NEG", "p_NEU", "p_POS").first(),
            filas=pl.len(),
        )
    )
    proba = calibrated(texts.select("p_NEG", "p_NEU", "p_POS").to_numpy())
    thr = threshold()
    texts = texts.with_columns(
        confianza=pl.Series(proba.max(axis=1)),
        pred=pl.Series(np.array(CLASSES)[proba.argmax(axis=1)]),
    )
    q = texts.filter(pl.col("confianza") < thr["umbral"]).sample(
        fraction=1.0, shuffle=True, seed=SEED
    )
    corpus = pl.read_parquet(
        INCIDENTS.parent / "backfill" / "20261022" / "texts",
        columns=["text_key", "texto_sanitizado"],
    )
    q = (
        q.join(corpus, on="text_key", how="left", maintain_order="left")
        .with_row_index("orden")
        .with_columns(
            item_id=pl.format(
                "H{}", pl.col("orden").add(1).cast(pl.String).str.zfill(4)
            ),
            bloque=pl.lit("hitl"),
            modo=pl.lit("ciego"),
        )
    )
    OUT.mkdir(parents=True, exist_ok=True)
    q.select(
        "orden",
        "item_id",
        "bloque",
        "modo",
        "id_resena",
        "bank_id",
        "texto_sanitizado",
    ).write_parquet(OUT / "queue.parquet")
    q.select("item_id", "text_key", "filas", "pred", "confianza").write_parquet(
        OUT / "predictions.parquet"
    )
    meta = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "modelo": MODEL,
        "temperatura": T,
        "cobertura_objetivo_dev": COVERAGE,
        "umbral": thr,
        "semana": [start.isoformat(), end.isoformat()],
        "textos_semana": texts.height,
        "textos_en_oro_excluidos": in_gold.len(),
        "cola": q.height,
        "cobertura_real_semana": round(1 - q.height / texts.height, 4),
        "cola_por_prediccion": dict(
            q.group_by("pred").len().sort("pred").iter_rows()
        ),
        "cola_por_banco": dict(
            q.group_by("bank_id").len().sort("bank_id").iter_rows()
        ),
    }
    (OUT / "queue_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(meta, ensure_ascii=False, indent=2))


def wilson(k: int, n: int) -> list[float]:
    p = k / n
    den = 1 + Z**2 / n
    mid = (p + Z**2 / (2 * n)) / den
    half = Z * math.sqrt(p * (1 - p) / n + Z**2 / (4 * n**2)) / den
    return [round(mid - half, 4), round(mid + half, 4)]


def summary() -> None:
    meta = json.loads((OUT / "queue_meta.json").read_text())
    preds = pl.read_parquet(OUT / "predictions.parquet")
    raw = pl.read_csv(
        OUT / "annotations.csv", infer_schema_length=0
    ).with_columns(
        pl.col("segundos").cast(pl.Float64),
        # La app guarda NO_EVALUABLE con `sentimiento` vacío, como en el oro.
        sentimiento=pl.when(pl.col("no_evaluable") == "1")
        .then(pl.lit("NO_EVALUABLE"))
        .otherwise(pl.col("sentimiento")),
    )
    # Una corrección agrega otra fila: gana la última.
    ann = raw.group_by("item_id").last()
    j = preds.join(ann, on="item_id")
    evaluable = j.filter(pl.col("sentimiento") != "NO_EVALUABLE")
    wrong = evaluable.filter(pl.col("sentimiento") != pl.col("pred"))
    result = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        **{
            k: meta[k]
            for k in (
                "modelo",
                "semana",
                "umbral",
                "cola",
                "cobertura_real_semana",
            )
        },
        "anotadas": j.height,
        "no_evaluables": j.height - evaluable.height,
        "tasa_correccion": round(wrong.height / evaluable.height, 4),
        "ic_tasa_correccion": wilson(wrong.height, evaluable.height),
        "esperada_5_7": 0.249,
        "aviso_p7_10": 0.28,
        "por_prediccion": {
            p: {
                "n": g.height,
                "corregidas": int((g["sentimiento"] != p).sum()),
            }
            for (p,), g in sorted(
                evaluable.group_by("pred"), key=lambda x: x[0]
            )
        },
        "matriz": dict(
            evaluable.group_by("pred", "sentimiento")
            .len()
            .select(pl.format("{}→{}", "pred", "sentimiento"), "len")
            .iter_rows()
        ),
        "segundos_por_resena_mediana": float(j["segundos"].median()),
        "segundos_por_resena_p90": float(j["segundos"].quantile(0.9)),
        # Incluye el tiempo de las correcciones (filas repetidas).
        "minutos_totales": round(float(raw["segundos"].sum()) / 60, 1),
        "minutos_activos": round(
            float(raw.filter(pl.col("segundos") <= PAUSE)["segundos"].sum())
            / 60,
            1,
        ),
        "registros_pausa": int((raw["segundos"] > PAUSE).sum()),
        "correcciones_del_revisor": raw.height - ann.height,
        "por_banco": {
            b: {
                "n": g.height,
                "corregidas": int((g["sentimiento"] != g["pred"]).sum()),
            }
            for (b,), g in sorted(
                evaluable.join(
                    pl.read_parquet(OUT / "queue.parquet").select(
                        "item_id", "bank_id"
                    ),
                    on="item_id",
                ).group_by("bank_id"),
                key=lambda x: x[0],
            )
        },
    }
    METRICS.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["queue", "summary"])
    {"queue": queue, "summary": summary}[ap.parse_args().cmd]()


if __name__ == "__main__":
    main()
