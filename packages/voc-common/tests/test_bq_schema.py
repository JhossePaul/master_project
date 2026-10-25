"""Esquema de BigQuery derivado de los modelos v3 (6.1)."""

from datetime import date, datetime
from enum import IntEnum
from typing import Any, Literal

import pytest
from pydantic import BaseModel
from voc_common.analytics_codes import AspectFamily, SentimentValue
from voc_common.bq_schema import ANALYTICS_V3_TABLES, bq_schema
from voc_common.operations_v3 import PromotionCheckResult
from voc_common.policies import RiskPolicy
from voc_common.predictions_v3 import (
    ReviewPrediction,
    SegmentEmbedding,
    TextEmbedding,
)

_TYPES = {"STRING", "INT64", "FLOAT64", "BOOL", "TIMESTAMP", "DATE", "JSON"}
_MODES = {"REQUIRED", "NULLABLE", "REPEATED"}


class _Sub(BaseModel):
    x: int


class _AllTypes(BaseModel):
    s: str
    i: int
    f: float
    b: bool
    ts: datetime
    d: date
    e: SentimentValue
    lit: Literal["a", "b"]
    opt: int | None
    arr: list[float]
    arr_enum: tuple[AspectFamily, ...]
    sub: _Sub
    opt_sub: _Sub | None
    mapping: dict[str, Any]
    subs: list[_Sub]


def test_every_python_type_maps_to_its_bigquery_type() -> None:
    assert bq_schema(_AllTypes) == (
        ("s", "STRING", "REQUIRED"),
        ("i", "INT64", "REQUIRED"),
        ("f", "FLOAT64", "REQUIRED"),
        ("b", "BOOL", "REQUIRED"),
        ("ts", "TIMESTAMP", "REQUIRED"),
        ("d", "DATE", "REQUIRED"),
        ("e", "STRING", "REQUIRED"),
        ("lit", "STRING", "REQUIRED"),
        ("opt", "INT64", "NULLABLE"),
        ("arr", "FLOAT64", "REPEATED"),
        ("arr_enum", "STRING", "REPEATED"),
        ("sub", "JSON", "REQUIRED"),
        ("opt_sub", "JSON", "NULLABLE"),
        ("mapping", "JSON", "REQUIRED"),
        ("subs", "JSON", "REPEATED"),
    )


def test_review_prediction_columns() -> None:
    schema = dict(
        (name, (kind, mode)) for name, kind, mode in bq_schema(ReviewPrediction)
    )
    assert schema["text_key"] == ("STRING", "REQUIRED")
    assert schema["palabras"] == ("INT64", "REQUIRED")
    assert schema["sentiment"] == ("STRING", "NULLABLE")
    assert schema["p_neg"] == ("FLOAT64", "NULLABLE")
    assert schema["requires_hitl"] == ("BOOL", "REQUIRED")
    assert schema["predicted_at"] == ("TIMESTAMP", "REQUIRED")
    assert list(schema) == list(ReviewPrediction.model_fields)


def test_text_embedding_is_a_repeated_float() -> None:
    schema = {
        name: (kind, mode) for name, kind, mode in bq_schema(TextEmbedding)
    }
    assert schema["embedding"] == ("FLOAT64", "REPEATED")
    assert schema["mes"] == ("DATE", "REQUIRED")


@pytest.mark.parametrize(
    ("table", "model"), sorted(ANALYTICS_V3_TABLES.items())
)
def test_every_v3_table_has_a_valid_schema(
    table: str, model: type[BaseModel]
) -> None:
    schema = bq_schema(model)
    assert schema, table
    assert {kind for _, kind, _ in schema} <= _TYPES
    assert {mode for _, _, mode in schema} <= _MODES
    assert len({name for name, _, _ in schema}) == len(schema)


def test_registry_covers_the_26_tables_of_schema_v3() -> None:
    assert len(ANALYTICS_V3_TABLES) == 26


def test_tables_of_retraining_derive_their_schema() -> None:
    # Se registran en ANALYTICS_V3_TABLES junto con su tabla en infra/.
    assert ("verdict", "STRING", "REQUIRED") in bq_schema(PromotionCheckResult)
    assert ("embedding", "FLOAT64", "REPEATED") in bq_schema(SegmentEmbedding)
    assert {"retrain_trigger", "topic_refit_trigger"} <= {
        name for name, _, mode in bq_schema(RiskPolicy) if mode == "NULLABLE"
    }


class _Color(IntEnum):
    RED = 1


class _BadEnum(BaseModel):
    c: _Color


class _BadUnion(BaseModel):
    u: int | str


class _BadOptionalArray(BaseModel):
    a: list[int] | None


class _BadNullableElement(BaseModel):
    a: list[int | None]


class _BadNested(BaseModel):
    a: list[list[int]]


class _BadLiteral(BaseModel):
    lit: Literal["a", 1]


class _BadType(BaseModel):
    b: bytes


class _BadTuple(BaseModel):
    t: tuple[int, str]


@pytest.mark.parametrize(
    "model",
    [
        _BadEnum,
        _BadUnion,
        _BadOptionalArray,
        _BadNullableElement,
        _BadNested,
        _BadLiteral,
        _BadType,
        _BadTuple,
    ],
)
def test_unsupported_types_fail(model: type[BaseModel]) -> None:
    with pytest.raises(TypeError):
        bq_schema(model)
