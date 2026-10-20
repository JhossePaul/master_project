"""EDA global del TDS (EPIC-5 feature 5.2), solo agregados.

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.eda.eda_global data/tds_<SNAPSHOT>.parquet

Escribe `docs/analytics/eda/metrics.json` y figuras PNG en
`docs/analytics/eda/figures/`. Nunca escribe texto de reseñas salvo frases
genéricas muy repetidas (>= MIN_PUBLIC_COUNT filas y <= 4 palabras), que no
pueden identificar a nadie.
"""

import json
import sys
from pathlib import Path

import emoji
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import polars as pl  # noqa: E402
from lingua import Language, LanguageDetectorBuilder  # noqa: E402

from voc_analytics.paths import DOCS  # noqa: E402

OUT = DOCS / "eda"
FIG = OUT / "figures"
MIN_PUBLIC_COUNT = 500
BANKS = ["BBVA", "SANTANDER", "AZTECA", "BANORTE", "NUBANK"]
# Paleta categórica de referencia (dataviz), slots 1-5 en orden fijo.
COLORS = dict(
    zip(
        BANKS,
        ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"],
        strict=True,
    )
)
TOKENS = (
    "PERSON_NAME",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD_NUMBER",
    "MEXICO_CURP_NUMBER",
    "MX_CLABE_BANCARIA",
    "MX_RFC_TAX_ID",
    "BBVA_ACCOUNT_NUMBER",
)
TOKEN_RE = r"(?i)\[(?:" + "|".join(TOKENS) + r")\]"
REF_RE = r"ref\s*:\s*\d{4}\s*:\s*[a-zA-Z0-9]+\s*:\s*[a-zA-Z0-9]+"
LENGTH_BUCKETS = [0, 1, 2, 3, 5, 10, 20, 40, 60, 100]


def bucket_expr(col: str) -> pl.Expr:
    expr = pl.lit(f">{LENGTH_BUCKETS[-1]}")
    for low, high in reversed(
        list(zip(LENGTH_BUCKETS[:-1], LENGTH_BUCKETS[1:], strict=True))
    ):
        label = str(high) if high - low == 1 else f"{low + 1}-{high}"
        expr = pl.when(pl.col(col) <= high).then(pl.lit(label)).otherwise(expr)
    return pl.when(pl.col(col) == 0).then(pl.lit("0")).otherwise(expr)


def rows(df: pl.DataFrame) -> list[dict]:
    return df.to_dicts()


def content_flags(df: pl.DataFrame) -> pl.DataFrame:
    """Marcas por texto único; el texto sin tokens ni símbolos decide."""
    without_tokens = pl.col("texto").str.replace_all(TOKEN_RE, " ")
    stripped = without_tokens.map_elements(
        lambda s: emoji.replace_emoji(s, replace=" "), return_dtype=pl.String
    )
    return df.with_columns(
        palabras=pl.col("texto").str.count_matches(r"\S+"),
        tiene_token=pl.col("texto").str.contains(TOKEN_RE),
        tiene_ref=pl.col("texto").str.contains(REF_RE),
        tiene_emoji=pl.col("texto").map_elements(
            lambda s: emoji.emoji_count(s) > 0, return_dtype=pl.Boolean
        ),
        alfanum=stripped.str.count_matches(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]"),
        letras=stripped.str.count_matches(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]"),
    )


def detect_language(texts: list[str]) -> list[str]:
    detector = (
        LanguageDetectorBuilder.from_languages(
            Language.SPANISH, Language.ENGLISH, Language.PORTUGUESE
        )
        .with_minimum_relative_distance(0.25)
        .with_low_accuracy_mode()
        .build()
    )
    found = detector.detect_languages_in_parallel_of(texts)
    return [lang.iso_code_639_1.name if lang else "UNSURE" for lang in found]


def figure_lines(
    data: pl.DataFrame, x: str, y: str, title: str, ylabel: str, name: str
) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=150)
    for bank in BANKS:
        part = data.filter(pl.col("bank_id") == bank).sort(x)
        if part.is_empty():
            continue
        ax.plot(part[x], part[y], color=COLORS[bank], linewidth=2, label=bank)
    ax.set_title(title, loc="left", fontsize=11, color="#0b0b0b")
    ax.set_ylabel(ylabel, color="#52514e", fontsize=9)
    ax.tick_params(colors="#52514e", labelsize=8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#d6d5d0")
    ax.grid(axis="y", color="#ecebe7", linewidth=0.8)
    ax.legend(
        frameon=False,
        fontsize=8,
        ncols=5,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.12),
    )
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    fig.tight_layout()
    fig.savefig(FIG / name)
    plt.close(fig)


def main(path: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    df = pl.read_parquet(path).with_columns(
        texto=pl.col("texto_limpio").fill_null(""),
        anio=pl.col("fecha").dt.year(),
        mes=pl.col("fecha").dt.truncate("1mo"),
    )
    n = df.height
    metrics: dict = {"snapshot_file": Path(path).name, "rows": n}

    # Textos únicos y marcas de contenido (calculadas una vez por texto).
    unique = content_flags(df.select("texto").unique())
    multi = unique.filter(pl.col("palabras") >= 3)
    langs = detect_language(multi["texto"].to_list())
    unique = unique.join(
        multi.select("texto").with_columns(idioma=pl.Series(langs)),
        on="texto",
        how="left",
    ).with_columns(idioma=pl.col("idioma").fill_null("SHORT"))
    df = df.join(unique, on="texto", how="left")

    normalized = df.select(
        pl.col("texto")
        .str.to_lowercase()
        .str.replace_all(r"[^\w\s]", " ")
        .str.replace_all(r"\s+", " ")
        .str.strip_chars()
        .alias("norm")
    )
    shared = (
        df.group_by("texto")
        .agg(pl.col("bank_id").n_unique().alias("bancos"), pl.len())
        .filter(pl.col("bancos") > 1)
    )
    freq = df.group_by("texto").len().sort("len", descending=True)
    metrics["duplicates"] = {
        "unique_texts": unique.height,
        "unique_share": round(unique.height / n, 4),
        "unique_normalized": normalized["norm"].n_unique(),
        "rows_top_100_texts": int(freq.head(100)["len"].sum()),
        "rows_top_1000_texts": int(freq.head(1000)["len"].sum()),
        "texts_in_several_banks": shared.height,
        "rows_with_text_in_several_banks": int(shared["len"].sum()),
        "unique_by_bank": rows(
            df.group_by("bank_id")
            .agg(
                pl.len().alias("filas"),
                pl.col("texto").n_unique().alias("unicos"),
            )
            .sort("bank_id")
        ),
    }
    metrics["frequent_generic_texts"] = rows(
        freq.join(unique.select("texto", "palabras"), on="texto")
        .filter((pl.col("len") >= MIN_PUBLIC_COUNT) & (pl.col("palabras") <= 4))
        .head(40)
        .rename({"len": "filas"})
        .select("texto", "filas")
    )

    # Longitud y contenido.
    df = df.with_columns(bucket=bucket_expr("palabras"))
    metrics["length_buckets"] = rows(
        df.group_by("bucket")
        .agg(
            pl.len().alias("filas"),
            pl.col("estrellas").mean().round(2).alias("estrellas_prom"),
        )
        .sort("filas", descending=True)
    )
    metrics["content"] = {
        "empty": int((df["palabras"] == 0).sum()),
        "no_alnum_after_tokens_and_emoji": int(
            ((df["palabras"] > 0) & (df["alfanum"] == 0)).sum()
        ),
        "only_digits_or_symbols": int(
            ((df["alfanum"] > 0) & (df["letras"] == 0)).sum()
        ),
        "with_sanitization_token": int(df["tiene_token"].sum()),
        "with_ref_code": int(df["tiene_ref"].sum()),
        "with_emoji": int(df["tiene_emoji"].sum()),
        "titulo_not_null": int(df["titulo"].is_not_null().sum()),
        "with_reply": int(df["texto_respuesta_sanitizado"].is_not_null().sum()),
        "version_unknown": int((df["version_app"] == "UNKNOWN").sum()),
        "pii_findings_rows": int((df["pii_findings_count"] > 0).sum()),
    }
    metrics["language_rows"] = rows(
        df.group_by("idioma")
        .len()
        .rename({"len": "filas"})
        .sort("filas", descending=True)
    )
    metrics["language_by_bank"] = rows(
        df.filter(pl.col("idioma").is_in(["EN", "PT"]))
        .group_by("bank_id", "idioma")
        .len()
        .sort("bank_id", "idioma")
    )

    # Estrellas, votos y deriva temporal.
    metrics["stars_by_bank"] = rows(
        df.group_by("bank_id", "estrellas").len().sort("bank_id", "estrellas")
    )
    metrics["votes_by_bank"] = rows(
        df.group_by("bank_id")
        .agg(
            (pl.col("votos_utilidad") > 0).mean().round(4).alias("con_votos"),
            pl.col("votos_utilidad").quantile(0.99).alias("p99"),
            pl.col("votos_utilidad").max().alias("max"),
        )
        .sort("bank_id")
    )
    yearly = (
        df.group_by("bank_id", "anio")
        .agg(
            pl.len().alias("filas"),
            pl.col("estrellas").mean().round(3).alias("estrellas_prom"),
            (pl.col("palabras") == 1).mean().round(4).alias("una_palabra"),
            ((pl.col("palabras") <= 3) & (pl.col("estrellas") == 5))
            .mean()
            .round(4)
            .alias("corta_5_estrellas"),
            pl.col("estrellas")
            .filter(pl.col("palabras") > 1)
            .mean()
            .round(3)
            .alias("estrellas_prom_sin_una_palabra"),
            (pl.col("version_app") == "UNKNOWN")
            .mean()
            .round(4)
            .alias("version_desconocida"),
        )
        .sort("bank_id", "anio")
    )
    metrics["yearly"] = rows(yearly)
    metrics["single_word_star_bias"] = rows(
        df.group_by("bank_id")
        .agg(
            pl.col("estrellas").mean().round(3).alias("todas"),
            pl.col("estrellas")
            .filter(pl.col("palabras") > 1)
            .mean()
            .round(3)
            .alias("sin_una_palabra"),
            pl.col("estrellas")
            .filter(pl.col("palabras") == 1)
            .mean()
            .round(3)
            .alias("solo_una_palabra"),
        )
        .sort("bank_id")
    )
    monthly = df.group_by("bank_id", "mes").len().rename({"len": "filas"})
    metrics["nubank_monthly_until_2021"] = rows(
        monthly.filter(
            (pl.col("bank_id") == "NUBANK") & (pl.col("mes").dt.year() <= 2021)
        )
        .sort("mes")
        .with_columns(pl.col("mes").dt.strftime("%Y-%m"))
    )
    metrics["first_month_over_100"] = rows(
        monthly.filter(pl.col("filas") >= 100)
        .group_by("bank_id")
        .agg(pl.col("mes").min().dt.strftime("%Y-%m"))
        .sort("bank_id")
    )

    # Candidatas de reglas de elegibilidad (5.1), sin precedencia todavía.
    metrics["rule_candidates"] = {
        "TNSS_EMPTY": metrics["content"]["empty"],
        "TNSS_NO_TEXT_CONTENT": metrics["content"][
            "no_alnum_after_tokens_and_emoji"
        ],
        "TNSS_SINGLE_WORD": int((df["palabras"] == 1).sum()),
        "TNSS_NOT_SPANISH_lingua_EN_PT": int(
            df["idioma"].is_in(["EN", "PT"]).sum()
        ),
        "TOPIC_TOO_SHORT_by_max_words": {
            str(k): int((df["palabras"] <= k).sum()) for k in (1, 2, 3, 4, 5)
        },
    }

    figure_lines(
        monthly.sort("mes"),
        "mes",
        "filas",
        "Reseñas por mes y banco",
        "reseñas por mes",
        "monthly_volume.png",
    )
    figure_lines(
        yearly.filter(pl.col("filas") >= 1000),
        "anio",
        "estrellas_prom",
        "Estrellas promedio por año (años con ≥ 1 000 reseñas)",
        "estrellas promedio",
        "yearly_stars.png",
    )
    figure_lines(
        yearly.filter(pl.col("filas") >= 1000).with_columns(
            pl.col("una_palabra") * 100
        ),
        "anio",
        "una_palabra",
        "Reseñas de una sola palabra (% por año)",
        "% de reseñas",
        "yearly_single_word.png",
    )

    (OUT / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str) + "\n"
    )
    print(
        json.dumps(
            {
                k: metrics[k]
                for k in ("duplicates", "content", "rule_candidates")
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
