"""Puntaje continuo de 1 a 5 (TNSS) contra el *gap* por clases (5.8, P8-9).

Pedido del autor (2026-10-22): confirmar si la métrica original del TNSS se
evaluó y, si no, medirla para decidir P8-9. En 5.6 solo se midió el *gap* por
clases (`ppi.py`: matriz 3 × 3 y brecha neta ordinal). Aquí se miden, con el
mismo PPI++ (M4 calibrado sobre `ppi_v0` y el oro *dev* aleatorio), las
variantes continuas:

* `score_clase`: `NEG` = 1, `NEU` = 3, `POS` = 5 con la clase predicha.
* `score_esperado`: 1·p(`NEG`) + 3·p(`NEU`) + 5·p(`POS`) con la probabilidad
  calibrada (la fórmula de `tnss_numeric_calibrated` en EPIC-6). Su objetivo
  humano es el mismo que el de `score_clase`; solo cambia el predictor.
* `score_original`: 1 + 4·p(`POS`), la propuesta original del TNSS.
* Para cada una, el *gap* por reseña: estrellas menos el puntaje del texto.
* **α de la propuesta original:** R = α·S + (1 − α)·T, así que el *gap*
  estrellas − R es (1 − α) veces el de T. Se reporta como identidad, no se
  estima: no hay una calificación "verdadera" contra la cual ajustar α.
* **Descomposición** del *gap* de `score_clase` por celda estrellas × texto
  (con las predicciones de M4 en `ppi_v0`): cuánto viene de reseñas en las
  que estrellas y texto coinciden (artefacto de la escala, por ejemplo 4★
  con texto `POS` da −1) y cuánto de las discordantes.
* **Por reseña:** en el oro *dev* aleatorio, error absoluto medio de
  `score_esperado` contra el puntaje humano, y qué parte de las reseñas cae
  en la zona ambigua (2 a 4).

El oro *test* no se toca. Escribe
`docs/analytics/calibration/tnss_score_v0_metrics.json`, solo agregados.

    uv run python -m voc_analytics.calibration.tnss_score
"""

import json
from datetime import UTC, datetime

import numpy as np
import polars as pl

from voc_analytics.calibration.calibrate import apply, logits, proba_for
from voc_analytics.calibration.ppi import (
    M4_MODEL,
    OUT_DIR,
    PPI_ROWS,
    SCORE,
    cell,
    combine,
    period,
)
from voc_analytics.sentiment.data import CLASSES, gold, gold_ids, stars_class

OUT = OUT_DIR / "tnss_score_v0_metrics.json"
CALIBRATION = OUT_DIR / "calibration_v0_metrics.json"
MAP = {"NEG": 1.0, "NEU": 3.0, "POS": 5.0}
TARGETS = [
    "estrellas",
    "score_clase",
    "score_esperado",
    "score_original",
    "gap_clase",
    "gap_esperado",
    "gap_original",
    "brecha_neta",
]


def calibrated(frame: pl.DataFrame, key: str, kind: str) -> np.ndarray:
    t = json.loads(CALIBRATION.read_text())["modelos"][M4_MODEL]
    raw = proba_for(M4_MODEL, frame, key, kind)
    return apply(
        logits(raw), np.array([np.log(t["temperature"]["temperatura"])])
    )


def human(label: pl.Expr) -> list[pl.Expr]:
    s = label.replace_strict(MAP, return_dtype=pl.Float64)
    o = (label == "POS").cast(pl.Float64) * 4 + 1
    stars = pl.col("estrellas").cast(pl.Float64)
    net = label.replace_strict(SCORE, return_dtype=pl.Float64) - pl.col(
        "estrellas_clase"
    ).replace_strict(SCORE, return_dtype=pl.Float64)
    return [s, s, o, stars - s, stars - s, stars - o, net]


def predicted(proba: np.ndarray, frame: pl.DataFrame) -> dict[str, np.ndarray]:
    lab = np.asarray(CLASSES)[proba.argmax(axis=1)]
    s = np.vectorize(MAP.get)(lab)
    e = proba @ np.array([1.0, 3.0, 5.0])
    o = 1 + 4 * proba[:, 2]
    stars = frame["estrellas"].to_numpy().astype(float)
    sc = np.vectorize(SCORE.get)(frame["estrellas_clase"].to_numpy())
    net = np.vectorize(SCORE.get)(lab) - sc
    return {
        "score_clase": s,
        "score_esperado": e,
        "score_original": o,
        "gap_clase": stars - s,
        "gap_esperado": stars - e,
        "gap_original": stars - o,
        "brecha_neta": net.astype(float),
        "_clase": lab,
    }


def labeled() -> pl.DataFrame:
    dev = (
        gold()
        .filter(
            (pl.col("particion") == "dev")
            & (pl.col("bloque_oro") == "aleatorio")
            & (pl.col("oro") != "NA")
        )
        .sort("item_id")
    )
    pred = predicted(calibrated(dev, "item_id", "dev"), dev)
    names = TARGETS[1:]
    return dev.with_columns(
        *(
            e.alias(f"{n}_oro")
            for n, e in zip(names, human(pl.col("oro")), strict=True)
        ),
        *(pl.Series(f"{n}_pred", pred[n]) for n in names),
        w=pl.col("peso"),
        estrellas_oro=pl.col("estrellas").cast(pl.Float64),
        estrellas_pred=pl.col("estrellas").cast(pl.Float64),
    )


def unlabeled() -> tuple[pl.DataFrame, np.ndarray]:
    rows = (
        pl.read_parquet(PPI_ROWS)
        .filter(~pl.col("id_resena").is_in(list(gold_ids())))
        .with_columns(
            periodo=period(pl.col("fecha").dt.year()),
            estrellas_clase=stars_class(),
            w=1 / pl.col("prob_inclusion"),
        )
    )
    texts = rows.select("text_id").unique().sort("text_id")
    proba = calibrated(texts, "text_id", "ppi")
    probs = texts.with_columns(p0=proba[:, 0], p1=proba[:, 1], p2=proba[:, 2])
    rows = rows.join(probs, on="text_id")
    p = rows.select("p0", "p1", "p2").to_numpy()
    pred = predicted(p, rows)
    clase = pl.Series("clase_texto", pred.pop("_clase"))
    out = rows.with_columns(
        clase,
        *(pl.Series(f"{n}_pred", v) for n, v in pred.items()),
        estrellas_pred=pl.col("estrellas").cast(pl.Float64),
    )
    return out, p


def estimate(g: pl.DataFrame, u: pl.DataFrame) -> dict:
    keys = sorted(
        set(map(tuple, g.select("bank_id", "periodo").rows()))
        & set(map(tuple, u.select("bank_id", "periodo").rows()))
    )
    result = {}
    for t in TARGETS:
        cells = {
            (b, p): cell(
                g.filter((pl.col("bank_id") == b) & (pl.col("periodo") == p)),
                u.filter((pl.col("bank_id") == b) & (pl.col("periodo") == p)),
                t,
            )
            for b, p in keys
        }
        result[t] = {
            "corpus": combine(list(cells.values())),
            "por_banco": {
                b: combine([c for (bb, _), c in cells.items() if bb == b])
                for b in sorted({b for b, _ in keys})
            },
        }
    return result


def decomposition(u: pl.DataFrame) -> dict:
    total = u["w"].sum()
    by = (
        u.group_by("estrellas", "clase_texto")
        .agg(
            peso=pl.col("w").sum(),
            gap=(pl.col("gap_clase_pred") * pl.col("w")).sum(),
        )
        .with_columns(
            proporcion=pl.col("peso") / total,
            aporte=pl.col("gap") / total,
            concordante=pl.col("clase_texto")
            == pl.col("estrellas").replace_strict(
                {1: "NEG", 2: "NEG", 3: "NEU", 4: "POS", 5: "POS"},
                return_dtype=pl.String,
            ),
        )
        .sort("estrellas", "clase_texto")
    )
    return {
        "gap_total": round(float(by["aporte"].sum()), 4),
        "aporte_concordantes": round(
            float(by.filter(pl.col("concordante"))["aporte"].sum()), 4
        ),
        "aporte_discordantes": round(
            float(by.filter(~pl.col("concordante"))["aporte"].sum()), 4
        ),
        "celdas": [
            {
                "estrellas": int(r["estrellas"]),
                "texto": r["clase_texto"],
                "proporcion": round(r["proporcion"], 4),
                "aporte_al_gap": round(r["aporte"], 4),
            }
            for r in by.iter_rows(named=True)
        ],
    }


def per_review(g: pl.DataFrame) -> dict:
    y = g["score_clase_oro"].to_numpy()
    w = g["w"].to_numpy()
    out = {}
    for n in ("score_clase", "score_esperado", "score_original"):
        p = g[f"{n}_pred"].to_numpy()
        target = g[f"{n}_oro"].to_numpy()
        out[n] = {
            "error_absoluto_medio": round(
                float(np.average(np.abs(p - target), weights=w)), 4
            ),
            "zona_ambigua_2_a_4": round(
                float(np.average((p > 2) & (p < 4), weights=w)), 4
            ),
        }
    out["n"] = int(len(y))
    return out


def main() -> None:
    g = labeled()
    u, _ = unlabeled()
    result = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "predictor": f"{M4_MODEL} (calibrado)",
        "n_oro": int(g.height),
        "n_ppi": int(u.height),
        "estimaciones": estimate(g, u),
        "descomposicion_gap_clase": decomposition(u),
        "por_resena_oro_dev": per_review(g),
        "alpha": "gap(alpha) = (1 - alpha) * gap(texto): alpha solo escala",
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"escrito {OUT}", flush=True)


if __name__ == "__main__":
    main()
