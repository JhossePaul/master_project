"""Contexto temporal de una reseña: quincena, releases y días pico.

Lo comparten el EDA temporal (`eda/eda_temporal.py`) y la plata
(`sample_silver.py`), para que ambos usen las mismas definiciones.

* **Día local:** `fecha` (UTC) en hora de Ciudad de México.
* **Quincena** (*biweekly payday*): en México se paga el 15 y el último día
  del mes. La marca cubre ±1 día alrededor de cada pago: los días 14 a 16, y
  el penúltimo día, el último y el día 1 del mes siguiente. Así se adapta a
  meses de 30 días y a febrero.
* **Release:** fecha estimada desde `version_app`. Es el día en que la versión
  acumula `RELEASE_NTH` reseñas. Se excluyen las `BETA` y las versiones con
  menos de `MIN_REVIEWS`, y se quita el sufijo `-minApiNN`. Un release de
  feature es la primera versión de cada `mayor.menor`.
* **Día pico:** volumen del día de al menos 3 veces la mediana móvil centrada
  de 29 días del banco, y al menos 20 reseñas. Se calcula para el volumen total
  y para cada nivel de estrellas por separado, sin suponer qué significa cada
  estrella. Usa días futuros: sirve para análisis, no para detección en tiempo
  real.
"""

import polars as pl

MIN_REVIEWS = 30
RELEASE_NTH = 5
SPIKE_FACTOR = 3
SPIKE_MIN = 20
SPIKE_WINDOW = 29


def local_day(col: str = "fecha") -> pl.Expr:
    return (
        pl.col(col)
        .dt.replace_time_zone("UTC")
        .dt.convert_time_zone("America/Mexico_City")
        .dt.date()
    )


def is_biweekly_payday(day: pl.Expr) -> pl.Expr:
    """Marca de quincena para una columna de fechas (`pl.Date`)."""
    dom = day.dt.day()
    last = day.dt.month_end().dt.day()
    return dom.is_between(14, 16) | (dom >= last - 1) | (dom == 1)


def releases(df: pl.DataFrame) -> pl.DataFrame:
    """Una fila por versión normalizada y su fecha estimada de release.

    `df` necesita `bank_id`, `version_app` y `dia` (día local).
    """
    versions = (
        df.filter(
            (pl.col("version_app") != "UNKNOWN")
            & ~pl.col("version_app").str.contains("(?i)beta")
        )
        .with_columns(
            version=pl.col("version_app").str.replace(r"-minApi\d+$", "")
        )
        .sort("dia")
        .group_by("bank_id", "version", maintain_order=True)
        .agg(
            pl.len().alias("resenas"),
            pl.col("dia").get(RELEASE_NTH - 1, null_on_oob=True).alias("dia"),
        )
        .filter(pl.col("resenas") >= MIN_REVIEWS)
        .drop_nulls("dia")
        .with_columns(feature=pl.col("version").str.extract(r"^(\d+\.\d+)"))
        .sort("bank_id", "dia")
    )
    first_feature = versions.group_by("bank_id", "feature").agg(
        pl.col("dia").min().alias("dia_feature")
    )
    return versions.join(first_feature, on=["bank_id", "feature"]).with_columns(
        es_feature=pl.col("dia") == pl.col("dia_feature")
    )


SERIES = ["n", "n_1", "n_2", "n_3", "n_4", "n_5"]


def daily_counts(df: pl.DataFrame) -> pl.DataFrame:
    """Serie diaria completa por banco, con ceros en días vacíos.

    `n` es el total y `n_1`…`n_5` el volumen de cada nivel de estrellas.
    `df` necesita `bank_id`, `dia` y `estrellas`.
    """
    span = df.group_by("bank_id").agg(
        pl.col("dia").min().alias("desde"), pl.col("dia").max().alias("hasta")
    )
    calendar = span.select(
        "bank_id",
        pl.date_ranges("desde", "hasta", "1d").alias("dia"),
    ).explode("dia")
    counts = df.group_by("bank_id", "dia").agg(
        pl.len().alias("n"),
        *[
            (pl.col("estrellas") == k).sum().alias(f"n_{k}")
            for k in range(1, 6)
        ],
    )
    return (
        calendar.join(counts, on=["bank_id", "dia"], how="left")
        .with_columns(pl.col(SERIES).fill_null(0))
        .sort("bank_id", "dia")
    )


def mark_spikes(daily: pl.DataFrame, col: str = "n") -> pl.DataFrame:
    """Agrega `pico_<col>` a una serie diaria con `bank_id`, `dia` y `col`."""
    median = (
        pl.col(col).rolling_median(SPIKE_WINDOW, center=True).over("bank_id")
    )
    return daily.sort("bank_id", "dia").with_columns(
        (
            (pl.col(col) >= SPIKE_FACTOR * median.clip(lower_bound=1))
            & (pl.col(col) >= SPIKE_MIN)
        ).alias(f"pico_{col}")
    )


def attach(rows: pl.DataFrame, raw: pl.DataFrame) -> pl.DataFrame:
    """Agrega a `rows` (con `bank_id`, `dia` y `estrellas`) el contexto.

    `raw` es el corpus completo con `bank_id`, `version_app`, `dia` y
    `estrellas`: el calendario de releases y los picos se derivan de todo el
    corpus, no solo de las filas muestreadas.
    """
    rel = releases(raw)
    daily = daily_counts(raw)
    for col in SERIES:
        daily = mark_spikes(daily, col)
    total = daily.select("bank_id", "dia", pl.col("pico_n").alias("pico_total"))
    by_star = daily.unpivot(
        on=[f"pico_n_{k}" for k in range(1, 6)],
        index=["bank_id", "dia"],
        variable_name="serie",
        value_name="pico_estrella",
    ).select(
        "bank_id",
        "dia",
        pl.col("serie").str.extract(r"(\d)$").cast(pl.Int64).alias("estrellas"),
        "pico_estrella",
    )

    def last(kind: pl.DataFrame, name: str) -> pl.DataFrame:
        return kind.select("bank_id", pl.col("dia").alias(name)).sort(name)

    out = (
        rows.with_columns(
            dia_mes=pl.col("dia").dt.day(),
            quincena=is_biweekly_payday(pl.col("dia")),
        )
        .sort("dia")
        .join_asof(
            last(rel, "dia_version"),
            left_on="dia",
            right_on="dia_version",
            by="bank_id",
            strategy="backward",
        )
        .join_asof(
            last(rel.filter("es_feature"), "dia_feature"),
            left_on="dia",
            right_on="dia_feature",
            by="bank_id",
            strategy="backward",
        )
        .with_columns(
            dias_desde_version=(pl.col("dia") - pl.col("dia_version"))
            .dt.total_days()
            .cast(pl.Int32),
            dias_desde_feature=(pl.col("dia") - pl.col("dia_feature"))
            .dt.total_days()
            .cast(pl.Int32),
        )
        .drop("dia_version", "dia_feature")
        .join(total, on=["bank_id", "dia"], how="left")
        .join(by_star, on=["bank_id", "dia", "estrellas"], how="left")
        .with_columns(
            dia_pico_total=pl.col("pico_total").fill_null(False),
            # Pico del mismo nivel de estrellas que la reseña.
            dia_pico_estrella=pl.col("pico_estrella").fill_null(False),
        )
        .drop("pico_total", "pico_estrella")
    )
    return out
