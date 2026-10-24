"""Ventana de la señal de incidentes (5.9, P9-1).

Compara ventanas de 1 a 30 días para la señal de volumen de negativas
(`M4_robertuito_s1_ppi`, de `incidents.prepare`) contra la lista externa de
incidentes que reunió el autor en medios (`data/incidents/external_v0.csv`,
fuera de git; no es exhaustiva, así que solo mide el recall).

* **Señal:** suma de negativas de los `w` días que terminan en `t`, contra
  `N = max(12, ceil(28 / w))` ventanas previas del mismo largo, sin traslape;
  z robusto con mediana y MAD (piso de 1). También el mes calendario, con el
  z de `prepare` (12 meses previos).
* **Costo:** porcentaje de días marcados: la probabilidad de que un día
  cualquiera tenga una alerta en `[d, d + w]`, la misma regla que cuenta un
  incidente como detectado. Los episodios por año no sirven para comparar
  ventanas: con ventanas largas las alertas se juntan en pocos episodios de
  semanas.
* **Umbral por banco** (como `drift_policy`): el menor de la rejilla cuyo
  porcentaje de días marcados no pasa el presupuesto.
* **Alcance:** desde el mes de entrada de cada banco (P7-9) hasta el último
  mes completo del snapshot. Los incidentes fuera de ese rango no cuentan.
* **Fechas imprecisas:** la del medio es la de publicación, no la del
  incidente, y la de la reseña es la de su última edición. La sensibilidad
  separa la tolerancia `T` de la ventana: un incidente cuenta si alguna
  ventana que termina en `[d - T, d + T + w - 1]` alerta, y el porcentaje de
  días marcados usa la misma zona. También se mide en qué día, entre
  `d - 7` y `d + 7`, cae el pico del z de 1 día.

Decisión del autor (2026-10-22), sujeta al backfill de familias y tópicos
(P9-3): ventana de 1 día como señal principal y una ventana larga como
complementaria para problemas sostenidos.

Escribe `data/incidents/daily_v0.parquet` (z diario de las ventanas de 1 y
30 días, para la lista de candidatos) y
`docs/analytics/incidents/signal_v0_metrics.json`, solo agregados.

    uv run python -m voc_analytics.incidents.signal
"""

import hashlib
import json
import math
from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl

from voc_analytics.incidents.prepare import OUT
from voc_analytics.paths import DOCS
from voc_analytics.scale.drift_baseline import entry_months

EXTERNAL = OUT / "external_v0.csv"
METRICS = DOCS / "incidents" / "signal_v0_metrics.json"
BANKS = {
    "BBVA": "BBVA",
    "Azteca": "AZTECA",
    "Santander": "SANTANDER",
    "Banorte": "BANORTE",
    "Nu México": "NUBANK",
}
WINDOWS = [1, 2, 3, 4, 5, 7, 10, 14, 21, 30]
KEEP = (1, 30)  # ventanas que se guardan por día para la tarea 1
BASELINE_DAYS = 28
MIN_BASELINE = 12
THRESHOLDS = np.arange(2.0, 30.01, 0.25)
BUDGETS = [0.05, 0.10, 0.20]
TOLERANCES = [0, 1, 3, 7]
SENS_BUDGET = 0.10
PEAK_DAYS = 7
PEAK_Z = 4.0


def external(first: dict[str, date], last: date) -> tuple[pl.DataFrame, dict]:
    ext = (
        pl.read_csv(EXTERNAL)
        .rename({"Fecha": "fecha", "Banco": "banco"})
        .with_columns(
            fecha=pl.col("fecha").str.strip_chars().str.to_date(),
            bank_id=pl.col("banco").replace_strict(BANKS),
        )
    )
    start = pl.col("bank_id").replace_strict(first, return_dtype=pl.Date)
    inside = (pl.col("fecha") >= start) & (pl.col("fecha") <= last)
    info = {
        "archivo": EXTERNAL.name,
        "sha256": hashlib.sha256(EXTERNAL.read_bytes()).hexdigest(),
        "incidentes": ext.height,
        "antes_de_la_entrada": ext.filter(pl.col("fecha") < start).height,
        "despues_del_ultimo_mes": ext.filter(pl.col("fecha") > last).height,
        "evaluables_por_banco": dict(
            sorted(ext.filter(inside).group_by("bank_id").len().iter_rows())
        ),
    }
    return ext.filter(inside), info


def window_z(neg: np.ndarray, w: int) -> np.ndarray:
    """z robusto de la suma de `w` días contra las ventanas previas."""
    s = np.convolve(neg, np.ones(w), mode="full")[: len(neg)]
    n = max(MIN_BASELINE, math.ceil(BASELINE_DAYS / w))
    lags = w * np.arange(1, n + 1)
    z = np.full(len(neg), np.nan)
    for t in range(n * w + w - 1, len(neg)):
        h = s[t - lags]
        med = np.median(h)
        mad = 1.4826 * np.median(np.abs(h - med))
        z[t] = (s[t] - med) / max(mad, 1.0)
    return z


def flagged(alert: np.ndarray, w: int) -> np.ndarray:
    """Por día `d`: si hay alguna alerta en `[d, d + w]`."""
    return zone(alert, 0, w)


def zone(alert: np.ndarray, lo: int, hi: int) -> np.ndarray:
    """Por día `d`: si hay alguna alerta en `[d - lo, d + hi]`."""
    n = len(alert)
    c = np.concatenate([[0], np.cumsum(alert.astype(int))])
    d = np.arange(n)
    return (c[np.clip(d + hi + 1, 0, n)] - c[np.clip(d - lo, 0, n)]) > 0


def tolerance(z: np.ndarray, mask: np.ndarray, pos: np.ndarray, w: int) -> dict:
    """Detectados por tolerancia `T`, con el presupuesto `SENS_BUDGET`."""
    out = {}
    for t in TOLERANCES:
        for thr in THRESHOLDS:
            f = zone((z >= thr) & mask, t, t + w - 1)
            if f[mask].mean() <= SENS_BUDGET:
                out[t] = int(f[pos].sum())
                break
    return out


def peak_offsets(z: np.ndarray, pos: np.ndarray) -> list[int]:
    """Día del pico del z de 1 día respecto a `d`, si llega a `PEAK_Z`."""
    out = []
    for p in pos:
        lo, hi = p - PEAK_DAYS, p + PEAK_DAYS + 1
        if lo < 0 or hi > len(z) or np.isnan(z[lo:hi]).any():
            continue
        i = int(np.argmax(z[lo:hi]))
        if z[lo + i] >= PEAK_Z:
            out.append(i - PEAK_DAYS)
    return out


def episodes(alert: np.ndarray, w: int) -> int:
    idx = np.flatnonzero(alert)
    return 0 if len(idx) == 0 else 1 + int((np.diff(idx) > w).sum())


def evaluate(
    z: np.ndarray,
    mask: np.ndarray,
    pos: np.ndarray,
    w: int,
    years: float,
    gap: int | None = None,
) -> list[dict]:
    """Recall y costo de cada umbral de la rejilla para un banco.

    `gap`: días entre alertas que separan dos episodios (`w` por defecto).
    """
    out = []
    for thr in THRESHOLDS:
        alert = (z >= thr) & mask
        f = flagged(alert, w)
        out.append(
            {
                "umbral": float(thr),
                "dias_marcados": float(f[mask].mean()),
                "detectados": int(f[pos].sum()),
                "episodios_por_anio": episodes(alert, gap or w) / years,
            }
        )
    return out


def pick(grid: list[dict], budget: float) -> dict:
    ok = [g for g in grid if g["dias_marcados"] <= budget]
    return min(ok, key=lambda g: g["umbral"])


def main() -> None:
    rows = pl.read_parquet(
        OUT / "rows_v0.parquet", columns=["bank_id", "fecha", "sentimiento"]
    )
    monthly = pl.read_parquet(OUT / "monthly_v0.parquet")
    months = sorted(monthly["mes"].unique())
    last_month = months[-2]  # el último está incompleto
    last = date.fromisoformat(months[-1] + "-01") - timedelta(days=1)
    entry = entry_months(monthly.select("bank_id", "mes", "filas"), months)
    first = {b: date.fromisoformat(m + "-01") for b, m in entry.items()}
    ext, ext_info = external(first, last)

    daily = (
        rows.filter(pl.col("sentimiento") == "NEG")
        .group_by("bank_id", dia=pl.col("fecha").dt.date())
        .len("neg")
    )
    grids: dict = {w: {} for w in WINDOWS}
    grids["mes"] = {}
    kept, n_inc = [], {}
    sens: dict = {w: {} for w in WINDOWS}
    offsets: list[int] = []
    for b in sorted(entry):
        g = daily.filter(pl.col("bank_id") == b)
        days = pl.date_range(g["dia"].min(), last, "1d", eager=True)
        g = (
            pl.DataFrame({"dia": days})
            .join(g.drop("bank_id"), on="dia", how="left")
            .fill_null(0)
            .sort("dia")
        )
        dias = g["dia"].to_numpy()
        neg = g["neg"].to_numpy().astype(float)
        mask = dias >= np.datetime64(first[b])
        years = mask.sum() / 365.25
        inc = ext.filter(pl.col("bank_id") == b)["fecha"].to_numpy()
        pos = np.searchsorted(dias, inc)
        n_inc[b] = len(pos)
        zs = {}
        for w in WINDOWS:
            zs[w] = window_z(neg, w)
            grids[w][b] = evaluate(zs[w], mask, pos, w, years)
            sens[w][b] = tolerance(zs[w], mask, pos, w)
        offsets += peak_offsets(zs[1], pos)
        # Mes calendario: z de `prepare`, repetido en cada día del mes.
        mz = dict(
            monthly.filter(pl.col("bank_id") == b)
            .select("mes", "z_neg")
            .iter_rows()
        )
        mes = g["dia"].dt.strftime("%Y-%m")
        zm = np.array([mz.get(m) for m in mes], dtype=float)
        mask_m = mask & (mes <= last_month).to_numpy()
        grids["mes"][b] = evaluate(
            np.nan_to_num(zm, nan=-np.inf), mask_m, pos, 0, years, gap=1
        )
        kept.append(
            g.with_columns(
                bank_id=pl.lit(b),
                **{f"z_{w}d": pl.Series(zs[w]) for w in KEEP},
            )
        )

    comparison = {}
    for B in BUDGETS:
        rows_b = {}
        for w, per_bank in grids.items():
            chosen = {b: pick(grid, B) for b, grid in per_bank.items()}
            det = sum(c["detectados"] for c in chosen.values())
            rows_b[str(w)] = {
                "recall": round(det / sum(n_inc.values()), 3),
                "detectados": det,
                "por_banco": {
                    b: {
                        "umbral": c["umbral"],
                        "detectados": c["detectados"],
                        "incidentes": n_inc[b],
                        "dias_marcados": round(c["dias_marcados"], 4),
                        "episodios_por_anio": round(c["episodios_por_anio"], 1),
                    }
                    for b, c in chosen.items()
                },
            }
        comparison[f"{B:.2f}"] = rows_b

    pl.concat(kept).select(
        "bank_id", "dia", "neg", "z_1d", "z_30d"
    ).write_parquet(OUT / "daily_v0.parquet")
    result = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "fuente": "incidents/rows_v0.parquet (M4_robertuito_s1_ppi)",
        "lista_externa": ext_info,
        "mes_de_entrada": entry,
        "ultimo_dia": last.isoformat(),
        "parametros": {
            "ventanas_dias": WINDOWS,
            "linea_base": (
                f"max({MIN_BASELINE}, ceil({BASELINE_DAYS} / w)) ventanas"
            ),
            "piso_mad": 1.0,
            "umbrales": [float(THRESHOLDS[0]), float(THRESHOLDS[-1]), 0.25],
            "presupuestos_dias_marcados": BUDGETS,
            "deteccion": (
                "alerta en [d, d + w]; mes calendario: alerta en el mes de d"
            ),
        },
        "comparacion": comparison,
        "sensibilidad_tolerancia": {
            "presupuesto_dias_marcados": SENS_BUDGET,
            "zona": "alerta en [d - T, d + T + w - 1]",
            "recall": {
                str(w): {
                    str(t): round(
                        sum(per_bank[b][t] for b in per_bank)
                        / sum(n_inc.values()),
                        3,
                    )
                    for t in TOLERANCES
                }
                for w, per_bank in sens.items()
            },
        },
        "desfase_del_pico": {
            "z_minimo": PEAK_Z,
            "dias_alrededor": PEAK_DAYS,
            "incidentes_con_pico": len(offsets),
            "por_dia": {str(k): offsets.count(k) for k in sorted(set(offsets))},
        },
    }
    METRICS.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for B, per_w in comparison.items():
        print(B, {w: v["recall"] for w, v in per_w.items()})


if __name__ == "__main__":
    main()
