"""Reglas de elegibilidad ``eligibility_rules_v1``
(``docs/analytics/eda/eligibility_rules.md``).

Port por fila de ``voc_analytics.labeling.eligibility.with_tnss_rule_v1`` y de
las reglas de tópicos de ``voc_analytics.eda.eligibility_counts``. Gana la
primera regla que coincide. Las palabras se cuentan sobre ``texto_limpio``;
el modelo y el ``text_key`` usan ``texto_sanitizado``.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import emoji
from voc_common.analytics_codes import (
    EligibilityCode,
    LabelSource,
    SentimentValue,
    TopicEligibilityCode,
)
from voc_common.constants import SentimentLabel

from voc_nlp.lexicon import Lexicon

RULES_VERSION: Final = "eligibility_rules_v1"
# Primera fecha válida de la app por banco; los demás bancos no tienen corte.
APP_VALID_FROM: Final[dict[str, datetime]] = {
    "NUBANK": datetime(2020, 1, 1, tzinfo=UTC),
}
# Tokens con que la sanitización reemplaza la PII.
PII_TOKENS: Final = (
    "PERSON_NAME",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD_NUMBER",
    "MEXICO_CURP_NUMBER",
    "MX_CLABE_BANCARIA",
    "MX_RFC_TAX_ID",
    "BBVA_ACCOUNT_NUMBER",
)
# Familias y tópicos solo para negativas de más de k = 1 palabras.
TOPIC_MIN_WORDS: Final = 2

_WORD = re.compile(r"\S+")
_TOKEN = re.compile(r"(?i)\[(?:" + "|".join(PII_TOKENS) + r")\]")
_ALNUM = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]")


def count_words(texto_limpio: str) -> int:
    """Palabras de ``texto_limpio``: secuencias sin espacios."""
    return len(_WORD.findall(texto_limpio))


def has_text_content(texto_limpio: str) -> bool:
    """Letras o dígitos tras quitar los tokens de PII y los emojis."""
    stripped = emoji.replace_emoji(_TOKEN.sub(" ", texto_limpio), replace=" ")
    return _ALNUM.search(stripped) is not None


@dataclass(frozen=True)
class TnssDecision:
    """Resultado de las reglas TNSS para una fila del TDS."""

    code: EligibilityCode
    source: LabelSource
    palabras: int
    # Etiqueta del léxico cuando ``source`` es ``RULE_BASED``.
    label: SentimentLabel | None = None


def tnss_rule(
    texto_limpio: str | None,
    fecha: datetime,
    bank_id: str,
    lexicon: Lexicon,
) -> TnssDecision:
    """Aplica ``eligibility_rules_v1`` a una fila (``fecha`` en UTC)."""
    text = texto_limpio or ""
    palabras = count_words(text)
    excluded: EligibilityCode | None = None
    valid_from = APP_VALID_FROM.get(bank_id)
    if palabras == 0:
        excluded = EligibilityCode.TNSS_EMPTY
    elif not has_text_content(text):
        excluded = EligibilityCode.TNSS_NO_TEXT_CONTENT
    elif valid_from is not None and _as_utc(fecha) < valid_from:
        excluded = EligibilityCode.TNSS_TIME_OUTLIER
    elif palabras == 1:
        label = lexicon.label(text)
        if label is None:
            excluded = EligibilityCode.TNSS_SINGLE_WORD
        else:
            return TnssDecision(
                EligibilityCode.ELEGIBLE, LabelSource.RULE_BASED, 1, label
            )
    if excluded is not None:
        return TnssDecision(excluded, LabelSource.NO_PREDICTED, palabras)
    return TnssDecision(EligibilityCode.ELEGIBLE, LabelSource.MODEL, palabras)


def topic_rule(
    sentiment: SentimentValue | None, palabras: int
) -> TopicEligibilityCode:
    """Elegibilidad para familias y tópicos de una reseña ya predicha."""
    if sentiment is None or sentiment is SentimentValue.NO_PREDICTED:
        return TopicEligibilityCode.TOPIC_TNSS_NOT_PREDICTED
    if sentiment is not SentimentValue.NEG:
        return TopicEligibilityCode.TOPIC_NOT_NEGATIVE
    if palabras < TOPIC_MIN_WORDS:
        return TopicEligibilityCode.TOPIC_TOO_SHORT
    return TopicEligibilityCode.ELEGIBLE


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
