"""Top 5 diario de temas de las negativas (5.9, P9-4).

Decisión del autor (2026-10-22): algo sencillo para el *hover* del cockpit
(EPIC-7, 7.5): por banco y día, las 5 familias y los 5 tópicos con más
reseñas negativas, con su participación. Es descriptivo, no una alerta.

* **Base:** las reseñas negativas para familias del día (`NEG` de M4 `s1` con
  dos palabras o más; `incidents.prepare`), una por fila del TDS.
* **Familias:** las `aspects_v2_1` del backfill (`incidents.backfill_aspects`)
  con su nombre de la guía `v2.1`; `OT` cuenta como "Sin familia".
* **Tópicos:** solo los 19 que el autor juzgó útiles en 5.5 (fase 4):
  producto (útil = sí) e ingeniería (coherencia ≥ 3 y útil = no), con el
  nombre que les dio. El resto (genéricos, ruido) no se muestra.
* **Participación:** reseñas del día con ese tema entre las negativas del
  día. Una reseña puede tener varios temas, así que no suman 100 %. El
  empate se rompe por código.
* **Participación habitual** (decisión del autor, 2026-10-22): la del mismo
  tema en los 28 días previos del banco, sin el día (reseñas con el tema
  entre negativas del periodo). Es un dato al lado, sin umbral ni marca.

Escribe `data/incidents/daily_topics_v0.parquet` (fuera de git; los nombres
de tópicos son del autor) y
`docs/analytics/incidents/daily_topics_v0_metrics.json`, solo agregados.

    uv run python -m voc_analytics.incidents.daily_topics
"""

import json
from datetime import UTC, datetime

import polars as pl

from voc_analytics.incidents.backfill_aspects import OUT as ASPECTS
from voc_analytics.incidents.backfill_topics import OUT as TOPICS
from voc_analytics.incidents.prepare import OUT
from voc_analytics.paths import DATA, DOCS
from voc_analytics.topics.aspects_scale import families

CURATION = DATA / "topics" / "phase4_v0" / "revision_topicos.csv"
METRICS = DOCS / "incidents" / "daily_topics_v0_metrics.json"
TOP = 5
MIN_COHERENCE = 3
HABITUAL_DAYS = 28
FAMILY_NAMES = {
    "AC": "Acceso y autenticación",
    "FA": "Falla general de la app",
    "LE": "Lentitud general",
    "TR": "Transferencias y pagos",
    "DI": "Dinero y cargos",
    "PR": "Productos y cuentas",
    "AT": "Atención",
    "DV": "Diseño visual",
    "UX": "Usabilidad, recorrido y cambios de funciones",
    "CO": "Compatibilidad, instalación y actualización",
    "OT": "Sin familia",
}


def useful_topics() -> pl.DataFrame:
    """Los tópicos útiles de 5.5: producto o ingeniería, con su nombre."""
    cur = pl.read_csv(CURATION)
    product = pl.col("util_para_producto_si_no") == "Si"
    engineering = ~product & (pl.col("coherencia_1a5") >= MIN_COHERENCE)
    return cur.filter(product | engineering).select(
        codigo=pl.col("topico").cast(pl.Int64),
        nombre=pl.col("nombre_propuesto"),
        audiencia=pl.when(product)
        .then(pl.lit("producto"))
        .otherwise(pl.lit("ingeniería")),
    )


def top(base: pl.DataFrame, themes: pl.DataFrame, tipo: str) -> pl.DataFrame:
    """Top `TOP` temas por banco y día, con su participación habitual."""
    n = base.group_by("bank_id", "dia").agg(n_neg=pl.len())
    counts = (
        base.join(themes, on="text_key")
        .group_by("bank_id", "dia", "codigo")
        .agg(filas=pl.len())
    )
    window = f"{HABITUAL_DAYS}d"
    dense = (
        n.join(counts.select("codigo").unique(), how="cross")
        .join(counts, on=["bank_id", "dia", "codigo"], how="left")
        .with_columns(pl.col("filas").fill_null(0))
        .sort("bank_id", "codigo", "dia")
        .with_columns(
            participacion=pl.col("filas") / pl.col("n_neg"),
            habitual=(
                pl.col("filas").rolling_sum_by("dia", window, closed="left")
                / pl.col("n_neg").rolling_sum_by("dia", window, closed="left")
            )
            .over("bank_id", "codigo")
            .fill_nan(None),
        )
    )
    return (
        dense.filter(pl.col("filas") > 0)
        .sort(
            "bank_id",
            "dia",
            "filas",
            "codigo",
            descending=[False, False, True, False],
        )
        .with_columns(
            rango=pl.int_range(1, pl.len() + 1).over("bank_id", "dia")
        )
        .filter(pl.col("rango") <= TOP)
        .with_columns(tipo=pl.lit(tipo))
    )


def main() -> None:
    base = (
        pl.read_parquet(
            OUT / "rows_v0.parquet",
            columns=["bank_id", "fecha", "text_key", "neg_familias"],
        )
        .filter(pl.col("neg_familias"))
        .select("bank_id", "text_key", dia=pl.col("fecha").dt.date())
    )
    fam = (
        pl.read_parquet(
            ASPECTS / "labels_by_key.parquet", columns=["text_key", "codes"]
        )
        .with_columns(codigo=families())
        .explode("codigo")
        .drop_nulls("codigo")
        .select("text_key", "codigo")
    )
    useful = useful_topics()
    top_ = (
        pl.read_parquet(TOPICS / "topics_by_key.parquet")
        .explode("topicos")
        .drop_nulls("topicos")
        .select("text_key", codigo=pl.col("topicos").cast(pl.Int64))
        .join(useful.select("codigo"), on="codigo")
    )
    daily_f = top(base, fam, "familia").with_columns(
        nombre=pl.col("codigo").replace_strict(FAMILY_NAMES)
    )
    daily_t = (
        top(base, top_, "topico")
        .join(useful.select("codigo", "nombre"), on="codigo")
        .with_columns(pl.col("codigo").cast(pl.String))
    )
    cols = [
        "bank_id",
        "dia",
        "n_neg",
        "tipo",
        "rango",
        "codigo",
        "nombre",
        "filas",
        "participacion",
        "habitual",
    ]
    daily = pl.concat([daily_f.select(cols), daily_t.select(cols)]).sort(
        "bank_id", "dia", "tipo", "rango"
    )
    daily.write_parquet(OUT / "daily_topics_v0.parquet")

    days = base.group_by("bank_id", "dia").agg(n_neg=pl.len())
    with_topic = base.join(top_.select("text_key").unique(), on="text_key")
    first = daily.filter(pl.col("rango") == 1)
    result = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "top": TOP,
        "habitual": (
            f"reseñas con el tema entre las negativas de los {HABITUAL_DAYS}"
            " días previos (sin el día), por banco"
        ),
        "top1_familia_participacion_sobre_habitual_mediana": round(
            float(
                (
                    first.filter(pl.col("tipo") == "familia")["participacion"]
                    / first.filter(pl.col("tipo") == "familia")["habitual"]
                ).median()
            ),
            3,
        ),
        "topicos_utiles": {
            "total": useful.height,
            "producto": useful.filter(pl.col("audiencia") == "producto").height,
            "ingenieria": useful.filter(
                pl.col("audiencia") == "ingeniería"
            ).height,
        },
        "negativas": base.height,
        "negativas_con_topico_util": round(with_topic.height / base.height, 4),
        "dias_banco": days.height,
        "por_banco": {
            b: {
                "dias": g.height,
                "negativas_por_dia_mediana": float(g["n_neg"].median()),
                "familia_mas_frecuente_en_el_primer_lugar": (
                    first.filter(
                        (pl.col("bank_id") == b) & (pl.col("tipo") == "familia")
                    )
                    .group_by("codigo")
                    .len()
                    .sort("len", descending=True)["codigo"][0]
                ),
            }
            for (b,), g in sorted(days.group_by("bank_id"), key=lambda x: x[0])
        },
        "primer_lugar_familias": {
            c: round(n / first.filter(pl.col("tipo") == "familia").height, 4)
            for c, n in first.filter(pl.col("tipo") == "familia")
            .group_by("codigo")
            .len()
            .sort("len", descending=True)
            .iter_rows()
        },
    }
    METRICS.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
