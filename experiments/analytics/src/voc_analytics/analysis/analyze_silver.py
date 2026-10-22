"""Métricas de la plata (EPIC-5, feature 5.3), solo agregados.

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.analysis.analyze_silver

Une `rows.parquet` (filas muestreadas, con estrato y contexto temporal) con
`labels_prompt_v3.parquet` (una etiqueta por texto único) y escribe
`docs/analytics/labeling/silver_v0_metrics.json`.

* **Estimaciones poblacionales:** ponderadas por 1 / probabilidad de inclusión
  (Horvitz-Thompson). Heredan el error de Gemini (κ 0.84–0.93 contra el
  oro); las estimaciones sin ese sesgo salen del oro o de PPI (5.6).
* **Contexto temporal:** proporción de `NEG` del texto dentro de cada banco ×
  nivel de estrellas, comparando quincena, días pico y días tras un release
  contra el resto. Así la mezcla de estrellas no confunde la comparación. Se
  usa una prueba z de dos proporciones sin ponderar dentro de cada celda (la
  marca de quincena no depende del estrato, así que el sesgo es pequeño).
"""

import json
import math

import polars as pl

from voc_analytics.paths import DOCS, LABELS

SILVER = LABELS / "silver_v0"
OUT = DOCS / "labeling" / "silver_v0_metrics.json"
CLASSES = ["NEG", "NEU", "POS", "NA"]


def z_test(k1: int, n1: int, k0: int, n0: int) -> float | None:
    """p bilateral de la diferencia de dos proporciones."""
    if min(n1, n0) == 0:
        return None
    p = (k1 + k0) / (n1 + n0)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n0))
    if se == 0:
        return None
    z = (k1 / n1 - k0 / n0) / se
    return round(math.erfc(abs(z) / math.sqrt(2)), 4)


def weighted(df: pl.DataFrame, by: list[str], flag: pl.Expr) -> pl.DataFrame:
    return (
        df.group_by(by)
        .agg(
            pl.len().alias("filas"),
            ((flag.cast(pl.Float64) * pl.col("w")).sum() / pl.col("w").sum())
            .round(4)
            .alias("p"),
        )
        .sort(by)
    )


def contrast(df: pl.DataFrame, flag: str) -> list[dict]:
    """NEG del texto con la marca contra sin ella, por banco × estrellas."""
    out = []
    for (bank, stars), cell in sorted(
        df.partition_by(["bank_id", "estrellas"], as_dict=True).items()
    ):
        on, off = cell.filter(pl.col(flag)), cell.filter(~pl.col(flag))
        k1, n1 = int(on["neg"].sum()), on.height
        k0, n0 = int(off["neg"].sum()), off.height
        out.append(
            {
                "bank_id": bank,
                "estrellas": stars,
                "n_marca": n1,
                "neg_marca": round(k1 / n1, 4) if n1 else None,
                "n_resto": n0,
                "neg_resto": round(k0 / n0, 4) if n0 else None,
                "p": z_test(k1, n1, k0, n0),
            }
        )
    return out


def main() -> None:
    labels = pl.read_parquet(SILVER / "labels_prompt_v3.parquet")
    df = (
        pl.read_parquet(SILVER / "rows.parquet")
        .join(labels, on="text_id")
        .with_columns(
            w=1 / pl.col("prob_inclusion"),
            neg=pl.col("gemini_s") == "NEG",
            estrellas_clase=pl.when(pl.col("estrellas") <= 2)
            .then(pl.lit("NEG"))
            .when(pl.col("estrellas") == 3)
            .then(pl.lit("NEU"))
            .otherwise(pl.lit("POS")),
            tras_release=pl.col("dias_desde_version").is_between(0, 3),
            jueves=pl.col("dia").dt.weekday() == 4,
        )
        .with_columns(
            incongruente=(
                (pl.col("estrellas") <= 2) & (pl.col("gemini_s") == "POS")
            )
            | ((pl.col("estrellas") >= 4) & (pl.col("gemini_s") == "NEG")),
            difiere=(pl.col("gemini_s") != "NA")
            & (pl.col("estrellas_clase") != pl.col("gemini_s")),
        )
    )
    evaluable = df.filter(pl.col("gemini_s") != "NA")
    total_w = df["w"].sum()
    metrics = {
        "filas": df.height,
        "textos": labels.height,
        "por_split": dict(df.group_by("split").len().iter_rows()),
        "poblacion": {
            "clase": {
                c: round(
                    df.filter(pl.col("gemini_s") == c)["w"].sum() / total_w, 4
                )
                for c in CLASSES
            },
            "menciona_falla": round(
                (df["gemini_falla"].cast(pl.Float64) * df["w"]).sum() / total_w,
                4,
            ),
            "estrellas_difiere_de_plata": round(
                (evaluable["difiere"].cast(pl.Float64) * evaluable["w"]).sum()
                / evaluable["w"].sum(),
                4,
            ),
            "incongruencia_extremos": round(
                (df["incongruente"].cast(pl.Float64) * df["w"]).sum() / total_w,
                4,
            ),
        },
        "plata_por_estrellas": weighted(
            df, ["estrellas"], pl.col("gemini_s") == "NEG"
        )
        .rename({"p": "neg"})
        .join(
            weighted(df, ["estrellas"], pl.col("gemini_s") == "POS").select(
                "estrellas", pl.col("p").alias("pos")
            ),
            on="estrellas",
        )
        .join(
            weighted(df, ["estrellas"], pl.col("gemini_s") == "NEU").select(
                "estrellas", pl.col("p").alias("neu")
            ),
            on="estrellas",
        )
        .join(
            weighted(df, ["estrellas"], pl.col("gemini_falla")).select(
                "estrellas", pl.col("p").alias("falla")
            ),
            on="estrellas",
        )
        .to_dicts(),
        "incongruencia_por_banco": weighted(
            df, ["bank_id"], pl.col("incongruente")
        ).to_dicts(),
        "incongruencia_por_periodo": weighted(
            df, ["periodo"], pl.col("incongruente")
        ).to_dicts(),
        "incongruencia_banco_periodo": weighted(
            df, ["bank_id", "periodo"], pl.col("incongruente")
        ).to_dicts(),
        "neg_en_5_estrellas_banco_periodo": weighted(
            df.filter(pl.col("estrellas") == 5),
            ["bank_id", "periodo"],
            pl.col("neg"),
        ).to_dicts(),
        "contexto": {
            "quincena": contrast(df, "quincena"),
            "dia_pico_total": contrast(df, "dia_pico_total"),
            "dia_pico_estrella": contrast(df, "dia_pico_estrella"),
            "tras_release_0_3": contrast(
                df.filter(pl.col("dias_desde_version").is_not_null()),
                "tras_release",
            ),
            "jueves_nubank": contrast(
                df.filter(pl.col("bank_id") == "NUBANK"), "jueves"
            ),
        },
    }
    OUT.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(metrics, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
