"""Curva de cobertura y riesgo para el umbral HITL de sentimiento (5.6).

Se aceptan sin revisión las predicciones más seguras y se mandan a revisión
humana las demás. Para cada umbral, la **cobertura** es la proporción que se
acepta y el **riesgo** es el error entre lo aceptado. Todo se pondera por
1 / π en el oro *dev* aleatorio, así que son cifras poblacionales.

* **Probabilidades:** M4 con *temperature scaling* (adoptado por el autor,
  2026-10-22; una T por semilla). En el *dev* se usan las probabilidades
  calibradas fuera de partición de `calibrate`, para no medir el riesgo con la
  misma muestra con la que se ajustó T.
* **Señales de incertidumbre:** probabilidad máxima, entropía normalizada y
  margen entre las dos primeras clases. Se comparan por AURC (área bajo la
  curva de riesgo; menor es mejor). También el ensamble de las 3 semillas
  (D3), promediando las probabilidades calibradas.
* **Disparador por impacto:** la regla de la especificación anterior
  (4–5★, `NEG` predicho y votos de utilidad ≥ 5): cuántas reseñas agrega y
  cuánto error tienen.
* **M9:** sin probabilidades; solo la marca `duda` de Gemini, disponible para
  las 199 reseñas *dev* de `gold_v0` (la corrida de `gold_v1` no la guardó).
* **Volumen:** reseñas y textos únicos por semana en las 8 semanas completas
  más recientes del snapshot, para traducir cada cobertura a revisiones por
  semana.

Escribe `docs/analytics/calibration/selective_v0_metrics.json` y la curva en
`docs/analytics/calibration/figures/`. El oro *test* no se toca.

    uv run python -m voc_analytics.calibration.selective
"""

import json
from datetime import UTC, datetime, timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import polars as pl  # noqa: E402

from voc_analytics.calibration.calibrate import (  # noqa: E402
    apply,
    fit,
    logits,
    out_of_fold,
    proba_for,
)
from voc_analytics.paths import DOCS, LABELS  # noqa: E402
from voc_analytics.sentiment.data import (  # noqa: E402
    CLASSES,
    SNAPSHOT,
    clave,
    gold,
    snapshot,
)
from voc_analytics.sentiment.metrics import _resample  # noqa: E402

OUT_DIR = DOCS / "calibration"
OUT = OUT_DIR / "selective_v0_metrics.json"
FIGURES = OUT_DIR / "figures"
FAMILIES = {
    "M4_robertuito": [f"M4_robertuito_s{s}" for s in (1, 2, 3)],
    "M4_beto": [f"M4_beto_s{s}" for s in (1, 2, 3)],
    # Lote `m4_ppi` (5.6): los modelos con pesos guardados.
    "M4_robertuito_ppi": [f"M4_robertuito_s{s}_ppi" for s in (1, 2, 3)],
}
COVERAGES = [1.0, 0.98, 0.95, 0.9, 0.85, 0.8]
BOOTSTRAP = 1000
SEED = 20261022
WEEKS = 8


def signals(proba: np.ndarray) -> dict[str, np.ndarray]:
    """Confianza: mayor = más seguro (se acepta primero)."""
    p = np.clip(proba, 1e-12, 1.0)
    top2 = np.sort(proba, axis=1)[:, -2:]
    return {
        "prob_max": proba.max(axis=1),
        "entropia": 1 + (p * np.log(p)).sum(axis=1) / np.log(len(CLASSES)),
        "margen": top2[:, 1] - top2[:, 0],
    }


def curve(
    conf: np.ndarray, err: np.ndarray, w: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Cobertura, riesgo y umbral al aceptar de mayor a menor confianza."""
    order = np.argsort(-conf, kind="stable")
    cw = np.cumsum(w[order])
    ce = np.cumsum((w * err)[order])
    return cw / w.sum(), ce / cw, conf[order]


def aurc(conf: np.ndarray, err: np.ndarray, w: np.ndarray) -> float:
    cov, risk, _ = curve(conf, err, w)
    return float(np.sum(risk * np.diff(np.concatenate([[0.0], cov]))))


def at_coverage(
    conf: np.ndarray, err: np.ndarray, w: np.ndarray, target: float
) -> dict:
    cov, risk, thr = curve(conf, err, w)
    i = min(int(np.searchsorted(cov, target - 1e-9)), len(cov) - 1)
    rejected = ~(conf >= thr[i])
    err_rej = (
        float(np.average(err[rejected], weights=w[rejected]))
        if rejected.any()
        else None
    )
    return {
        "cobertura": round(float(cov[i]), 4),
        "riesgo": round(float(risk[i]), 4),
        "umbral": round(float(thr[i]), 4),
        "error_en_revision": None if err_rej is None else round(err_rej, 4),
        "errores_atrapados": round(
            float((w * err)[rejected].sum() / max((w * err).sum(), 1e-12)), 4
        ),
    }


def boot_risk(
    conf: np.ndarray,
    err: np.ndarray,
    w: np.ndarray,
    strata: np.ndarray,
    target: float,
) -> list[float]:
    rng = np.random.default_rng(SEED)
    vals = []
    for _ in range(BOOTSTRAP):
        i = _resample(strata, rng)
        vals.append(at_coverage(conf[i], err[i], w[i], target)["riesgo"])
    return [round(float(np.percentile(vals, q)), 4) for q in (2.5, 97.5)]


def weekly_volume() -> dict:
    lazy = pl.scan_parquet(SNAPSHOT).select("fecha", "texto_sanitizado")
    last = lazy.select(pl.col("fecha").max()).collect().item()
    end = (last - timedelta(days=last.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = end - timedelta(weeks=WEEKS)
    weeks = (
        lazy.filter((pl.col("fecha") >= start) & (pl.col("fecha") < end))
        .with_columns(
            clave("texto_sanitizado"), semana=pl.col("fecha").dt.week()
        )
        .group_by("semana")
        .agg(
            resenas=pl.len(),
            textos_unicos=pl.col("clave").n_unique(),
        )
        .collect()
    )
    return {
        "desde": start.date().isoformat(),
        "hasta": end.date().isoformat(),
        "resenas_por_semana": round(float(weeks["resenas"].mean()), 1),
        "textos_unicos_por_semana": round(
            float(weeks["textos_unicos"].mean()), 1
        ),
    }


def m9_duda(dev: pl.DataFrame) -> dict:
    runs = sorted(
        (json.loads(p.read_text())["run"], p)
        for p in (LABELS / "gold_v0").glob("run_*.json")
        if json.loads(p.read_text())["prompt_version"] == "prompt_v3"
    )
    labels = pl.read_parquet(
        LABELS / "gold_v0" / f"labels_{runs[0][0]}.parquet"
    ).select("item_id", "gemini_s", "gemini_duda")
    j = dev.join(labels, on="item_id", how="inner")
    w = j["peso"].to_numpy()
    err = (j["gemini_s"] != j["oro"]).to_numpy().astype(float)
    duda = j["gemini_duda"].fill_null(False).to_numpy().astype(bool)
    flagged_err = (w * err)[duda].sum() / max((w * err).sum(), 1e-12)
    return {
        "n": int(j.height),
        "proporcion_con_duda": round(float(np.average(duda, weights=w)), 4),
        "riesgo_sin_duda": round(
            float(np.average(err[~duda], weights=w[~duda])), 4
        )
        if (~duda).any()
        else None,
        "riesgo_total": round(float(np.average(err, weights=w)), 4),
        "errores_atrapados": round(float(flagged_err), 4),
    }


def main() -> None:
    dev_all = gold().filter(
        (pl.col("particion") == "dev") & (pl.col("oro") != "NA")
    )
    dev = dev_all.filter(pl.col("bloque_oro") == "aleatorio").sort("item_id")
    directed = dev_all.filter(pl.col("bloque_oro") == "dirigido").sort(
        "item_id"
    )
    y, w = dev["oro"].to_numpy(), dev["peso"].to_numpy()
    strata = dev["estrato"].to_numpy()
    y_idx = np.array([CLASSES.index(v) for v in y])
    y_dir = directed["oro"].to_numpy()
    votes = snapshot(dev["id_resena"], ["votos_utilidad"])
    dev_votes = (
        dev.select("id_resena")
        .join(votes, on="id_resena", how="left")["votos_utilidad"]
        .fill_null(0)
        .to_numpy()
    )
    stars = dev["estrellas"].to_numpy()

    results: dict = {}
    curves_for_plot = {}
    for family, names in FAMILIES.items():
        oof_all, dir_all = [], []
        for name in names:
            print(f"cobertura y riesgo {name}", flush=True)
            raw = proba_for(name, dev, "item_id", "dev")
            z = logits(raw)
            oof = out_of_fold(z, y, w, "temperature")
            params = fit(z, y_idx, w, "temperature")
            raw_dir = proba_for(name, directed, "item_id", "dev")
            oof_all.append(oof)
            dir_all.append(apply(logits(raw_dir), params))
            results[name] = evaluate_run(
                oof, y, w, strata, dir_all[-1], y_dir, stars, dev_votes
            )
            if name.endswith("s1"):
                curves_for_plot[name] = oof
        ens = np.mean(oof_all, axis=0)
        results[f"{family}_ensamble"] = evaluate_run(
            ens, y, w, strata, np.mean(dir_all, axis=0), y_dir, stars, dev_votes
        )
        curves_for_plot[f"{family}_ensamble"] = ens

    volume = weekly_volume()
    m9 = m9_duda(dev)

    FIGURES.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(5.5, 4))
    colors = ["#002D72", "#215347", "#7A1A37", "#B9975B"]
    for (name, proba), color in zip(
        curves_for_plot.items(), colors, strict=False
    ):
        err = (np.asarray(CLASSES)[proba.argmax(axis=1)] != y).astype(float)
        cov, risk, _ = curve(proba.max(axis=1), err, w)
        ax.plot(cov, risk, color=color, lw=1.5, label=name)
    ax.set_xlim(0.7, 1.0)
    ax.set_xlabel("Cobertura (aceptado sin revisión)")
    ax.set_ylabel("Riesgo (error ponderado entre lo aceptado)")
    ax.set_title(f"M4 calibrado, dev aleatorio (n = {len(y)})")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "risk_coverage_m4.png", dpi=150)

    OUT.write_text(
        json.dumps(
            {
                "generado": datetime.now(UTC).isoformat(timespec="seconds"),
                "n_dev_aleatorio": int(dev.height),
                "n_dev_dirigido": int(directed.height),
                "coberturas": COVERAGES,
                "bootstrap": BOOTSTRAP,
                "volumen": volume,
                "m9_duda_gold_v0": m9,
                "modelos": results,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(f"escrito {OUT}", flush=True)


def evaluate_run(
    proba: np.ndarray,
    y: np.ndarray,
    w: np.ndarray,
    strata: np.ndarray,
    proba_dir: np.ndarray,
    y_dir: np.ndarray,
    stars: np.ndarray,
    votes: np.ndarray,
) -> dict:
    pred = np.asarray(CLASSES)[proba.argmax(axis=1)]
    err = (pred != y).astype(float)
    sig = signals(proba)
    out: dict = {
        "riesgo_total": round(float(np.average(err, weights=w)), 4),
        "aurc": {k: round(aurc(v, err, w), 5) for k, v in sig.items()},
        "por_cobertura": {},
    }
    conf = sig["prob_max"]
    for c in COVERAGES:
        point = at_coverage(conf, err, w, c)
        if c < 1.0:
            point["ic_riesgo"] = boot_risk(conf, err, w, strata, c)
        out["por_cobertura"][str(c)] = point
    pred_dir = np.asarray(CLASSES)[proba_dir.argmax(axis=1)]
    err_dir = (pred_dir != y_dir).astype(float)
    ones = np.ones(len(y_dir))
    out["dirigido"] = {
        "riesgo_total": round(float(err_dir.mean()), 4),
        "por_cobertura": {
            str(c): at_coverage(proba_dir.max(axis=1), err_dir, ones, c)
            for c in COVERAGES
        },
    }
    impact = (stars >= 4) & (pred == "NEG") & (votes >= 5)
    out["disparador_impacto"] = {
        "n": int(impact.sum()),
        "proporcion": round(float(np.average(impact, weights=w)), 4),
        "error": round(float(err[impact].mean()), 4) if impact.any() else None,
    }
    return out


if __name__ == "__main__":
    main()
