"""Reglas deterministas de elegibilidad TNSS (`eligibility_rules_v0.1`).

Implementa la tabla de `docs/analytics/eligibility_rules.md`: gana la primera
regla que coincide; `None` significa elegible. `TNSS_SINGLE_WORD` se calcula
pero no excluye mientras su decisión siga pendiente (5.8).
"""

from datetime import datetime

import emoji
import polars as pl

RULES_VERSION = "eligibility_rules_v0.1"
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
