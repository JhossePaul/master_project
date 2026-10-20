"""EDA de patrones temporales del TDS (EPIC-5, feature 5.2), solo agregados.

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.eda.eda_temporal data/tds_<SNAPSHOT>.parquet

Hipótesis del autor (2026-10-18):

* H-T1, trimestres: los releases grandes siguen el calendario trimestral.
* H-T2, sprints: los parches salen cada ~2 semanas (scrum).
* H-T3, quincena: hay más incidencias en quincena ("BBVA se cae en quincena").
  Confusor: en México la quincena es día de pago, con picos de transacciones,
  así que también se mide la carga.

Las definiciones de quincena, release y día pico están en
`labeling/temporal_context.py`, compartidas con la plata. Calendario de
releases: se deriva de `version_app`.

* Fecha de release: el día en que la versión acumula `RELEASE_NTH` reseñas,
  para no depender de reseñas sueltas de testers. Se excluyen las versiones
  `BETA` y las que tienen menos de `MIN_REVIEWS`.
* `-minApiNN` se elimina, porque el mismo build se publica por nivel de API.
* "Feature release" = cambio en las dos primeras componentes (`26.90`,
  `12.1`). "Parche" = cualquier versión nueva.

Variables: el volumen diario total y el de cada nivel de estrellas por
separado, cada uno relativo a su propia media. No se supone que una estrella
indique sentimiento: eso es justo lo que el proyecto corrige, y el sentimiento
real se medirá con la plata. Las fechas se convierten de UTC a
America/Mexico_City antes de calcular el día del mes. El
periodo es 2020-01-01 a 2026-10-13, con los cinco bancos presentes.
`fecha` es la última edición de la reseña, no su creación.
"""

import json
import math
import sys
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import polars as pl  # noqa: E402

from voc_analytics.labeling.temporal_context import (  # noqa: E402
    MIN_REVIEWS,
    RELEASE_NTH,
    SERIES,
    daily_counts,
    is_biweekly_payday,
    local_day,
    mark_spikes,
    releases,
)
from voc_analytics.paths import DOCS  # noqa: E402

OUT = DOCS / "eda"
FIG = OUT / "figures"
BANKS = ["BBVA", "SANTANDER", "AZTECA", "BANORTE", "NUBANK"]
COLORS = dict(
    zip(
        BANKS,
        ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"],
        strict=True,
    )
)
START, END = date(2020, 1, 1), date(2026, 10, 13)
WINDOW = range(-7, 22)


def rows(df: pl.DataFrame) -> list[dict]:
    return df.to_dicts()


def intervals(rel: pl.DataFrame, kind: str) -> pl.DataFrame:
    frame = rel if kind == "parche" else rel.filter("es_feature")
    return (
        frame.sort("bank_id", "dia")
        .with_columns(
            gap=(
                pl.col("dia") - pl.col("dia").shift(1).over("bank_id")
            ).dt.total_days()
        )
        .drop_nulls("gap")
        .filter(pl.col("dia") >= START)
    )


SERIE_LABEL = {
    "n": "total",
    "n_1": "1★",
    "n_2": "2★",
    "n_3": "3★",
    "n_4": "4★",
    "n_5": "5★",
}


def binom_p(k: int, n: int, p: float) -> float:
    """P(X >= k) con X ~ Binomial(n, p)."""
    return sum(
        math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1)
    )


def grid(
    frame: pl.DataFrame,
    x: str,
    y: str,
    title: str,
    xlabel: str,
    ylabel: str,
    name: str,
    marks: tuple = (),
) -> None:
    """Una gráfica por serie (total y cada estrella), una línea por banco."""
    fig, axes = plt.subplots(2, 3, figsize=(13, 7), sharex=True, sharey=True)
    for ax, serie in zip(axes.flat, SERIES, strict=True):
        for bank in BANKS:
            d = frame.filter(
                (pl.col("bank_id") == bank) & (pl.col("serie") == serie)
            ).sort(x)
            ax.plot(d[x], d[y], color=COLORS[bank], label=bank, lw=1.3)
        for mark in marks:
            ax.axvline(mark, color="#999999", lw=0.6, ls=":")
        ax.axhline(1, color="#999999", lw=0.6)
        ax.set_title(SERIE_LABEL[serie])
        ax.grid(alpha=0.3)
    for ax in axes[1]:
        ax.set_xlabel(xlabel)
    for ax in axes[:, 0]:
        ax.set_ylabel(ylabel)
    fig.suptitle(title)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=5, frameon=False)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(FIG / name, dpi=150)
    plt.close(fig)


def figure_gaps(gaps: pl.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.5))
    bins = list(range(0, 64, 2))
    for bank in BANKS:
        d = gaps.filter(pl.col("bank_id") == bank)["gap"].clip(upper_bound=62)
        ax.hist(d, bins=bins, histtype="step", lw=1.6, color=COLORS[bank])
    ax.plot([], [])
    ax.set_xlabel(
        "días entre versiones nuevas (parches incluidos; ≥62 agrupado)"
    )
    ax.set_ylabel("número de intervalos")
    ax.set_title("Cadencia de releases derivada de version_app, 2020-2026")
    ax.legend(
        BANKS,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.15),
        ncol=5,
        frameon=False,
    )
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "temporal_release_gaps.png", dpi=150)
    plt.close(fig)


def main(path: str) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    raw = pl.read_parquet(
        path, columns=["bank_id", "version_app", "fecha", "estrellas"]
    ).with_columns(dia=local_day())
    rel = releases(raw)
    df = raw.filter(pl.col("dia").is_between(START, END))
    metrics: dict = {
        "snapshot_file": Path(path).name,
        "periodo": [START.isoformat(), END.isoformat()],
        "parametros": {
            "min_reviews": MIN_REVIEWS,
            "release_nth": RELEASE_NTH,
            "quincena": "días 14-16, penúltimo y último día del mes, y día 1",
            "series": "volumen total y volumen de cada nivel de estrellas",
        },
    }

    # Serie diaria por banco: total y cada estrella, sin suponer su sentido.
    daily = daily_counts(df).with_columns(
        anio=pl.col("dia").dt.year(),
        dia_mes=pl.col("dia").dt.day(),
        dia_semana=pl.col("dia").dt.weekday(),
        mes_trimestre=(pl.col("dia").dt.month() - 1) % 3 + 1,
        quincena=is_biweekly_payday(pl.col("dia")),
    )
    long = daily.unpivot(
        on=SERIES,
        index=[
            "bank_id",
            "dia",
            "anio",
            "dia_mes",
            "dia_semana",
            "mes_trimestre",
            "quincena",
        ],
        variable_name="serie",
        value_name="v",
    )

    def profile(key: str) -> pl.DataFrame:
        """Volumen medio por `key` / volumen medio de la serie (índice 1)."""
        return (
            long.group_by("bank_id", "serie", key)
            .agg(pl.col("v").mean().alias("media"))
            .with_columns(
                indice=(
                    pl.col("media")
                    / pl.col("media").mean().over("bank_id", "serie")
                ).round(3)
            )
            .drop("media")
            .sort("bank_id", "serie", key)
        )

    by_day = profile("dia_mes")
    by_weekday = profile("dia_semana")
    grid(
        by_day,
        "dia_mes",
        "indice",
        "Volumen por día del mes, total y por estrella (2020-2026)",
        "día del mes (hora de Ciudad de México)",
        "volumen / media de la serie",
        "temporal_day_of_month.png",
        marks=(1, 15, 30),
    )
    grid(
        by_weekday,
        "dia_semana",
        "indice",
        "Volumen por día de la semana, total y por estrella (2020-2026)",
        "día de la semana (1 = lunes)",
        "volumen / media de la serie",
        "temporal_weekday.png",
    )
    metrics["dia_del_mes"] = rows(by_day)
    metrics["dia_semana"] = rows(by_weekday)
    metrics["mes_del_trimestre"] = rows(profile("mes_trimestre"))

    # Quincena contra el resto, por serie, con consistencia entre años.
    def payday_ratio(frame: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
        return (
            frame.group_by(*keys, "quincena")
            .agg(pl.col("v").mean())
            .pivot(on="quincena", index=keys, values="v")
            .with_columns(razon=pl.col("true") / pl.col("false"))
            .drop("true", "false")
        )

    yearly = payday_ratio(long, ["bank_id", "serie", "anio"])
    metrics["quincena_vs_resto"] = rows(
        payday_ratio(long, ["bank_id", "serie"])
        .join(
            yearly.group_by("bank_id", "serie").agg(
                pl.len().alias("anios"),
                (pl.col("razon") > 1).sum().alias("anios_razon_mayor_1"),
                pl.col("razon").min().round(3).alias("razon_min_anual"),
                pl.col("razon").max().round(3).alias("razon_max_anual"),
            ),
            on=["bank_id", "serie"],
        )
        .with_columns(pl.col("razon").round(3))
        .sort("bank_id", "serie")
    )
    # Mezcla de estrellas (descriptiva): proporción de cada nivel.
    metrics["mezcla_estrellas_quincena"] = rows(
        daily.group_by("bank_id", "quincena")
        .agg(
            [
                (pl.col(f"n_{k}").sum() / pl.col("n").sum())
                .round(4)
                .alias(f"p_{k}")
                for k in range(1, 6)
            ]
        )
        .sort("bank_id", "quincena")
    )

    # Cadencia de releases.
    gaps = intervals(rel, "parche")
    figure_gaps(gaps)
    feature_gaps = intervals(rel, "feature")

    def cadence(frame: pl.DataFrame) -> list[dict]:
        return rows(
            frame.group_by("bank_id")
            .agg(
                pl.len().alias("intervalos"),
                pl.col("gap").median().alias("mediana_dias"),
                pl.col("gap").quantile(0.25).alias("p25"),
                pl.col("gap").quantile(0.75).alias("p75"),
                pl.col("gap")
                .is_between(11, 17)
                .mean()
                .round(3)
                .alias("share_11_17_dias"),
                pl.col("gap")
                .is_between(80, 100)
                .mean()
                .round(3)
                .alias("share_80_100_dias"),
            )
            .sort("bank_id")
        )

    rel_period = rel.filter(pl.col("dia").is_between(START, END))
    payday_share = round(daily["quincena"].mean(), 3)
    metrics["releases"] = {
        "versiones": rows(
            rel_period.group_by("bank_id")
            .agg(
                pl.len().alias("versiones"),
                pl.col("es_feature").sum().alias("features"),
            )
            .sort("bank_id")
        ),
        "cadencia_parches": cadence(gaps),
        "cadencia_features": cadence(feature_gaps),
        "features_por_mes_del_trimestre": rows(
            rel_period.filter("es_feature")
            .group_by(
                "bank_id",
                ((pl.col("dia").dt.month() - 1) % 3 + 1).alias("mes_trimestre"),
            )
            .len()
            .sort("bank_id", "mes_trimestre")
        ),
        "versiones_por_dia_semana": rows(
            rel_period.group_by("bank_id", pl.col("dia").dt.weekday())
            .len()
            .sort("bank_id", "dia")
        ),
        "versiones_en_quincena": rows(
            rel_period.group_by("bank_id")
            .agg(
                pl.len().alias("versiones"),
                is_biweekly_payday(pl.col("dia")).sum().alias("en_quincena"),
            )
            .with_columns(
                share=(pl.col("en_quincena") / pl.col("versiones")).round(3),
                esperado=pl.lit(payday_share),
            )
            .sort("bank_id")
        ),
    }

    # Estudio de eventos: volumen de cada serie alrededor de los releases de
    # feature, relativo a la semana previa (k = -7..-1).
    features = rel_period.filter("es_feature").select(
        "bank_id", pl.col("dia").alias("dia_release")
    )
    event = (
        features.join(pl.DataFrame({"k": list(WINDOW)}), how="cross")
        .with_columns(dia=pl.col("dia_release") + pl.duration(days="k"))
        .join(
            long.select("bank_id", "dia", "serie", "v"), on=["bank_id", "dia"]
        )
        .group_by("bank_id", "serie", "k")
        .agg(pl.col("v").mean())
        .with_columns(
            indice=pl.col("v")
            / pl.col("v")
            .filter(pl.col("k") < 0)
            .mean()
            .over("bank_id", "serie")
        )
    )
    grid(
        event,
        "k",
        "indice",
        "Volumen alrededor de los releases de feature, total y por estrella",
        "días desde el release",
        "volumen / semana previa",
        "temporal_release_event.png",
        marks=(0,),
    )
    metrics["evento_release"] = rows(
        event.with_columns(
            ventana=pl.when(pl.col("k") < 0)
            .then(pl.lit("antes_-7_-1"))
            .when(pl.col("k") <= 3)
            .then(pl.lit("0_3"))
            .when(pl.col("k") <= 10)
            .then(pl.lit("4_10"))
            .otherwise(pl.lit("11_21"))
        )
        .group_by("bank_id", "serie", "ventana")
        .agg(pl.col("indice").mean().round(3))
        .sort("bank_id", "serie", "ventana")
    )

    # Días pico de cada serie: ¿se concentran en quincena o tras un release?
    window_days = (
        features.join(pl.DataFrame({"k": range(4)}), how="cross")
        .select(
            "bank_id",
            (pl.col("dia_release") + pl.duration(days="k")).alias("dia"),
        )
        .unique()
        .with_columns(tras_release=pl.lit(True))
    )
    marked = daily
    for col in SERIES:
        marked = mark_spikes(marked, col)
    marked = marked.join(
        window_days, on=["bank_id", "dia"], how="left"
    ).with_columns(pl.col("tras_release").fill_null(False))
    spikes = []
    for bank in BANKS + ["TODOS"]:
        frame = (
            marked
            if bank == "TODOS"
            else marked.filter(pl.col("bank_id") == bank)
        )
        for col in SERIES:
            peak = frame.filter(pl.col(f"pico_{col}"))
            n = peak.height
            in_payday = int(peak["quincena"].sum())
            after = int(peak["tras_release"].sum())
            p_payday = frame["quincena"].mean()
            p_after = frame["tras_release"].mean()
            spikes.append(
                {
                    "bank_id": bank,
                    "serie": col,
                    "dias_pico": n,
                    "en_quincena": in_payday,
                    "share_quincena": round(in_payday / n, 3) if n else None,
                    "esperado_quincena": round(p_payday, 3),
                    "p_quincena": round(binom_p(in_payday, n, p_payday), 4)
                    if n
                    else None,
                    "tras_release": after,
                    "share_tras_release": round(after / n, 3) if n else None,
                    "esperado_tras_release": round(p_after, 3),
                    "p_tras_release": round(binom_p(after, n, p_after), 4)
                    if n
                    else None,
                }
            )
    metrics["dias_pico"] = spikes

    (OUT / "temporal_metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str) + "\n"
    )
    print(json.dumps(metrics, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
