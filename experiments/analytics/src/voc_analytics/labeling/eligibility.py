"""Reglas deterministas de elegibilidad TNSS.

Implementa la tabla de `docs/analytics/eda/eligibility_rules.md`: gana la
primera regla que coincide; `None` significa elegible.

* `with_tnss_rule`: `eligibility_rules_v0.1`, la versión con la que se
  construyeron las muestras de EPIC-5 (sin `TNSS_SINGLE_WORD`). No cambia,
  para que sus consumidores sigan reproduciendo esas muestras.
* `with_tnss_rule_v1`: `eligibility_rules_v1` (aprobada en 5.8, P8-3 y P8-4).
  Agrega `TNSS_SINGLE_WORD` para las reseñas de una palabra cuya forma no
  tiene etiqueta de sentimiento en el léxico, y `lexico` con la etiqueta de
  las que sí (`label_source = RULE_BASED`). Las formas del léxico con
  etiqueta `NA` (no evaluable) también se excluyen.
"""

from datetime import datetime

import emoji
import polars as pl

RULES_VERSION = "eligibility_rules_v0.1"
RULES_VERSION_V1 = "eligibility_rules_v1"
SENTIMENT = ("NEG", "NEU", "POS")
APP_VALID_FROM = {"NUBANK": datetime(2020, 1, 1)}
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


def with_tnss_rule(df: pl.DataFrame) -> pl.DataFrame:
    """Agrega `palabras` y `tnss_rule` (código de exclusión o nulo)."""
    texto = pl.col("texto_limpio").fill_null("")
    stripped = texto.str.replace_all(TOKEN_RE, " ").map_elements(
        lambda s: emoji.replace_emoji(s, replace=" "), return_dtype=pl.String
    )
    valid_from = pl.col("bank_id").replace_strict(
        APP_VALID_FROM, default=None, return_dtype=pl.Datetime("us")
    )
    df = df.with_columns(
        palabras=texto.str.count_matches(r"\S+"),
        _alfanum=stripped.str.count_matches(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]"),
    )
    rule = (
        pl.when(pl.col("palabras") == 0)
        .then(pl.lit("TNSS_EMPTY"))
        .when(pl.col("_alfanum") == 0)
        .then(pl.lit("TNSS_NO_TEXT_CONTENT"))
        .when(valid_from.is_not_null() & (pl.col("fecha") < valid_from))
        .then(pl.lit("TNSS_TIME_OUTLIER"))
        .otherwise(pl.lit(None, dtype=pl.String))
    )
    return df.with_columns(tnss_rule=rule).drop("_alfanum")


def with_tnss_rule_v1(df: pl.DataFrame, lexicon: pl.DataFrame) -> pl.DataFrame:
    """`with_tnss_rule` más `TNSS_SINGLE_WORD` y la etiqueta del léxico.

    `lexicon` tiene `forma` y `lexico` (de `eda.eda_lexicon.build_lexicon`).
    Agrega `lexico`: la etiqueta de las reseñas elegibles de una palabra.
    """
    from voc_analytics.eda.eda_lexicon import with_form

    df = with_form(with_tnss_rule(df))
    labels = lexicon.filter(pl.col("lexico").is_in(SENTIMENT)).select(
        "forma", "lexico"
    )
    df = df.join(labels, on="forma", how="left").drop("forma")
    single = (pl.col("palabras") == 1) & pl.col("tnss_rule").is_null()
    return df.with_columns(
        tnss_rule=pl.when(single & pl.col("lexico").is_null())
        .then(pl.lit("TNSS_SINGLE_WORD"))
        .otherwise(pl.col("tnss_rule")),
        lexico=pl.when(single).then(pl.col("lexico")),
    )
