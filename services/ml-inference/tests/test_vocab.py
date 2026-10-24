"""Vocabulario de entrenamiento: misma regla que 5.7, subida y lectura."""

import io
from datetime import UTC, datetime
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from google.api_core.exceptions import NotFound
from ml_inference.config import InferenceSettings
from ml_inference.vocab import (
    ARCHIVE_PREFIX,
    build_vocab,
    encode,
    load_vocab,
    stage_vocab,
    training_vocab,
    vocab_blob,
)

TEXTS = pa.table(
    {
        "text_id": [1, 2, 3, 4],
        "texto_sanitizado": ["Hola  App", "la APP falla", "solo prueba", None],
    }
)
ROWS = pa.table(
    {
        "text_id": [1, 2, 2, 3, 4],
        "split": [
            "entrenamiento",
            "entrenamiento",
            "holdout",
            "holdout",
            "entrenamiento",
        ],
    }
)


def settings() -> InferenceSettings:
    return InferenceSettings(gcp_project_id="p", gcs_raw_datalake_bucket="b")


def test_training_vocab_matches_drift_baseline_rule() -> None:
    # Minúsculas, separación por un espacio (el doble espacio deja ''), sin
    # textos de otras particiones.
    assert training_vocab(TEXTS, ROWS) == {"hola", "", "app", "la", "falla"}


class _Blob:
    def __init__(self, store: dict[str, bytes], name: str) -> None:
        self.store, self.name = store, name

    def download_as_bytes(self) -> bytes:
        if self.name not in self.store:
            raise NotFound("missing")
        return self.store[self.name]

    def upload_from_string(self, data: bytes, content_type: str) -> None:
        self.store[self.name] = data


class _Storage:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def bucket(self, name: str) -> Any:
        assert name == "b"
        return self

    def blob(self, name: str) -> _Blob:
        return _Blob(self.store, name)


def _parquet(table: pa.Table) -> bytes:
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


def test_build_and_load_round_trip() -> None:
    gcs = _Storage()
    gcs.store[f"{ARCHIVE_PREFIX}texts.parquet"] = _parquet(TEXTS)
    gcs.store[f"{ARCHIVE_PREFIX}rows.parquet"] = _parquet(ROWS)
    n, digest = build_vocab(settings(), gcs, "m1")
    blob = vocab_blob(settings(), "m1")
    assert blob == "ml_artifacts/sentiment/m1/training_vocab.txt"
    assert n == 5 and len(digest) == 64
    assert gcs.store[blob] == encode(training_vocab(TEXTS, ROWS))
    assert load_vocab(settings(), gcs, "m1") == training_vocab(TEXTS, ROWS)
    with pytest.raises(FileNotFoundError):
        load_vocab(settings(), gcs, "m2")


def test_empty_training_split_is_an_error() -> None:
    gcs = _Storage()
    gcs.store[f"{ARCHIVE_PREFIX}texts.parquet"] = _parquet(TEXTS)
    gcs.store[f"{ARCHIVE_PREFIX}rows.parquet"] = _parquet(
        pa.table({"text_id": [1], "split": ["holdout"]})
    )
    with pytest.raises(ValueError, match="no words"):
        build_vocab(settings(), gcs, "m1")


def test_stage_vocab_creates_an_expiring_table() -> None:
    calls: dict[str, Any] = {}

    class _Job:
        def result(self) -> None:
            calls["done"] = True

    class _Client:
        def create_table(self, table: Any) -> None:
            calls["expires"] = table.expires

        def load_table_from_json(
            self, rows: list, table_id: str, **_: Any
        ) -> _Job:
            calls["rows"] = rows
            return _Job()

    now = datetime(2026, 7, 8, tzinfo=UTC)
    table = stage_vocab(_Client(), "p.ds", {"b", "a"}, now)
    assert table == "p.ds._vocab_20260708000000"
    assert calls["rows"] == [{"word": "a"}, {"word": "b"}] and calls["done"]
    assert calls["expires"] > now
