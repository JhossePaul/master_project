"""Líneas base para vigilar el desempeño de M4 y de las familias (5.7).

Pedido del autor (2026-10-22): además de la deriva de los datos, vigilar si
el modelo empeora y cuándo pedir reentrenamiento (P7-10), y la calidad de las
familias de Gemini (P7-11), con mecanismos que ya existen y costo mínimo. Este
script mide las líneas base con las que se fijan los umbrales; no llama a
ningún servicio.

* **κ de M4 en la muestra humana trimestral** (`monitor_sample`, P7-7): qué
  tan ancho sale el IC del κ con n revisiones, simulando muestras aleatorias de
  la población a partir del oro *dev* aleatorio (remuestreo con probabilidad
  proporcional al peso de diseño). Modelo: `M4_robertuito_s1_ppi`.
* **Tasa de corrección en la cola HITL:** la esperada al 90 % de cobertura
  (error de M4 entre lo que se manda a revisión, `selective_v0_metrics.json`)
  y su variación semanal con ~350 revisiones.
* **Acuerdo M4–Gemini:** por mes en `holdout_nuevo` (textos posteriores al
  entrenamiento, con la etiqueta de Gemini de la plata) y en el oro *dev*.
* **Familias:** IC por *bootstrap* del κ autor–Gemini por familia y del
  acuerdo exacto en las 300 reseñas codificadas por el autor en 5.2
  (`muestra_v21`), la referencia para validar un cambio de modelo de Gemini.

Escribe `docs/analytics/scale/model_monitor_v0_metrics.json`, solo agregados.

    uv run python -m voc_analytics.scale.model_monitor
"""

import json
from datetime import UTC, datetime

import numpy as np
import polars as pl
from sklearn.metrics import cohen_kappa_score

from voc_analytics.eda.eda_aspects_v2 import CODES_V21, validation
from voc_analytics.paths import DOCS
from voc_analytics.sentiment.data import (
    PREDS,
    SILVER,
    gold,
    holdout_rows,
    silver_rows,
)

OUT = DOCS / "scale" / "model_monitor_v0_metrics.json"
M4 = "M4_robertuito_s1_ppi"
SIZES = [100, 200, 300, 500]
BOOT = 2000
SEED = 20261022
WEEKLY_QUEUE = 350
WEEKLY_AGREEMENT_SAMPLE = 500


def pct(values, qs=(2.5, 97.5)) -> list[float]:
    return [round(float(np.percentile(values, q)), 4) for q in qs]


def kappa_by_size(rng) -> dict:
    dev = gold().filter(
        (pl.col("particion") == "dev")
        & (pl.col("bloque_oro") == "aleatorio")
        & (pl.col("oro") != "NA")
    )
    preds = pl.read_parquet(PREDS / f"{M4}__dev.parquet").select(
        "item_id", "pred"
    )
    j = dev.join(preds, on="item_id")
    y, p = j["oro"].to_numpy(), j["pred"].to_numpy()
    w = j["peso"].to_numpy()
    prob = w / w.sum()
    full = float(cohen_kappa_score(y, p, sample_weight=w))
    out = {"kappa_poblacional_dev": round(full, 4), "n_dev": int(len(y))}
    for n in SIZES:
        ks = []
        for _ in range(BOOT):
            i = rng.choice(len(y), size=n, replace=True, p=prob)
            ks.append(cohen_kappa_score(y[i], p[i]))
        out[str(n)] = {
            "ic95": pct(ks),
            "semiancho": round(
                (np.percentile(ks, 97.5) - np.percentile(ks, 2.5)) / 2, 4
            ),
            "p5": round(float(np.percentile(ks, 5)), 4),
        }
    return out


def correction_rate() -> dict:
    sel = json.loads(
        (DOCS / "calibration" / "selective_v0_metrics.json").read_text()
    )
    rate = sel["modelos"][M4]["por_cobertura"]["0.9"]["error_en_revision"]
    se = (rate * (1 - rate) / WEEKLY_QUEUE) ** 0.5
    return {
        "esperada": rate,
        "revisiones_por_semana": WEEKLY_QUEUE,
        "error_estandar_semanal": round(se, 4),
        "limite_superior_99_semanal": round(rate + 2.576 * se, 4),
        "error_estandar_4_semanas": round(se / 2, 4),
        "limite_superior_99_4_semanas": round(rate + 2.576 * se / 2, 4),
    }


def agreement() -> dict:
    hold = holdout_rows(silver_rows())
    preds = pl.read_parquet(PREDS / f"{M4}__holdout.parquet").select(
        "text_id", pl.col("pred").alias("m4")
    )
    fechas = pl.read_parquet(SILVER / "rows.parquet").select(
        "id_resena", "fecha"
    )
    j = (
        hold.join(preds, on="text_id")
        .join(fechas, on="id_resena")
        .with_columns(mes=pl.col("fecha").dt.strftime("%Y-%m"))
    )
    monthly = (
        j.group_by("mes")
        .agg(
            n=pl.len(),
            acuerdo=((pl.col("m4") == pl.col("plata")) * pl.col("peso")).sum()
            / pl.col("peso").sum(),
        )
        .sort("mes")
    )
    vals = monthly["acuerdo"].to_list()
    p = float(np.mean(vals))
    se_week = (p * (1 - p) / WEEKLY_AGREEMENT_SAMPLE) ** 0.5
    return {
        "holdout_por_mes": {
            m: {"n": n, "acuerdo": round(a, 4)}
            for m, n, a in monthly.iter_rows()
        },
        "media": round(p, 4),
        "rango_mensual": [round(min(vals), 4), round(max(vals), 4)],
        "muestra_semanal_propuesta": WEEKLY_AGREEMENT_SAMPLE,
        "error_estandar_semanal": round(se_week, 4),
        "costo_semanal_usd": round(WEEKLY_AGREEMENT_SAMPLE * 0.048 / 1000, 4),
    }


def families(rng) -> dict:
    result = validation("muestra_v21")
    if result is None:
        return {"nota": "faltan las etiquetas de muestra_v21"}
    _, hum, gem = result
    n = len(hum)
    out = {"items": n, "por_familia": {}}
    for c in CODES_V21:
        a = np.array([c in x for x in hum])
        b = np.array([c in x for x in gem])
        if not a.any() and not b.any():
            continue
        base = cohen_kappa_score(a, b)
        ks = []
        for _ in range(BOOT):
            i = rng.integers(0, n, n)
            if a[i].any() or b[i].any():
                ks.append(cohen_kappa_score(a[i], b[i]))
        out["por_familia"][c] = {
            "kappa": round(float(base), 3),
            "ic95": pct(ks),
            "prevalencia_autor": round(float(a.mean()), 3),
        }
    exact = np.array([p == q for p, q in zip(hum, gem, strict=True)])
    boots = [exact[rng.integers(0, n, n)].mean() for _ in range(BOOT)]
    out["acuerdo_exacto"] = {
        "valor": round(float(exact.mean()), 3),
        "ic95": pct(boots),
    }
    return out


def main() -> None:
    rng = np.random.default_rng(SEED)
    result = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "modelo": M4,
        "kappa_m4_por_tamano_de_muestra": kappa_by_size(rng),
        "tasa_de_correccion_hitl": correction_rate(),
        "acuerdo_m4_gemini": agreement(),
        "familias_gemini_muestra_v21": families(rng),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
