"""Los enums del esquema v3 coinciden con el contrato y con las reglas (6.1)."""

import re
from enum import StrEnum
from pathlib import Path

import pytest
from voc_common.analytics_codes import (
    AlertStatus,
    AspectFamily,
    BoostEndReason,
    DisplayMode,
    EligibilityCode,
    ExplanationSource,
    GoldSplit,
    HitlReason,
    HitlStatus,
    HitlTask,
    KpiMethod,
    LabelSource,
    ModelStatus,
    QualitySignal,
    QualityStatus,
    ReviewFlag,
    ReviewOutcome,
    RunEnvironment,
    RunKind,
    SentimentValue,
    TopicEligibilityCode,
)
from voc_common.constants import SentimentLabel

_RULES_DOC = (
    Path(__file__).resolve().parents[3]
    / "docs/analytics/eda/eligibility_rules.md"
)


@pytest.mark.parametrize(
    ("enum", "values"),
    [
        (
            EligibilityCode,
            [
                "ELEGIBLE",
                "TNSS_EMPTY",
                "TNSS_NO_TEXT_CONTENT",
                "TNSS_TIME_OUTLIER",
                "TNSS_SINGLE_WORD",
            ],
        ),
        (
            TopicEligibilityCode,
            [
                "ELEGIBLE",
                "TOPIC_TNSS_NOT_PREDICTED",
                "TOPIC_NOT_NEGATIVE",
                "TOPIC_TOO_SHORT",
            ],
        ),
        (LabelSource, ["MODEL", "RULE_BASED", "NO_PREDICTED"]),
        (SentimentValue, ["NEG", "NEU", "POS", "NO_PREDICTED"]),
        (
            AspectFamily,
            ["AC", "TR", "DI", "PR", "AT", "FA", "LE", "CO", "DV", "UX", "OT"],
        ),
        (HitlTask, ["sentiment", "aspects", "topic"]),
        (
            HitlReason,
            [
                "low_confidence",
                "drift_boost",
                "monitor_sample",
                "agreement_sample",
                "manual",
            ],
        ),
        (DisplayMode, ["blind", "assisted"]),
        (
            HitlStatus,
            [
                "queued",
                "assigned",
                "in_review",
                "submitted",
                "skipped",
                "expired",
            ],
        ),
        (ReviewOutcome, ["confirmed", "corrected"]),
        (
            ReviewFlag,
            ["menciona_falla", "duda", "no_evaluable", "nombre_persona"],
        ),
        (GoldSplit, ["dev", "muestra_v21"]),
        (RunKind, ["backfill", "delta", "rescoring"]),
        (RunEnvironment, ["kaggle", "cloudrun", "local"]),
        (ModelStatus, ["candidate", "promoted", "retired"]),
        (AlertStatus, ["open", "confirmed", "dismissed"]),
        (BoostEndReason, ["expired", "alert_closed", "manual"]),
        (
            QualitySignal,
            [
                "kappa_monitor",
                "correction_rate",
                "agreement_m4_gemini",
                "families_validation",
            ],
        ),
        (QualityStatus, ["ok", "warning", "retrain", "rejected"]),
        (KpiMethod, ["ppi", "raw"]),
        (ExplanationSource, ["precomputed_hitl", "on_demand"]),
    ],
)
def test_enum_values_match_schema_v3(
    enum: type[StrEnum], values: list[str]
) -> None:
    assert [member.value for member in enum] == values


def test_sentiment_value_extends_the_three_model_classes() -> None:
    model_classes = {label.value for label in SentimentLabel}
    assert model_classes == {v.value for v in SentimentValue} - {"NO_PREDICTED"}


@pytest.mark.skipif(not _RULES_DOC.exists(), reason="docs/ fuera del checkout")
def test_eligibility_codes_follow_the_rules_document_order() -> None:
    text = _RULES_DOC.read_text(encoding="utf-8")
    approved = re.findall(
        r"^\| \d \| `(TNSS_[A-Z_]+)` \|", text, flags=re.MULTILINE
    )
    assert approved == [code.value for code in EligibilityCode][1:]
