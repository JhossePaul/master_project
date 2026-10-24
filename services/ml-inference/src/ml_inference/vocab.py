"""Vocabulario de entrenamiento del monitor de deriva (6.4).

Es el conjunto de ``drift_baseline.training_vocab`` (5.7): las palabras de
``texto_sanitizado`` en minúsculas, separadas por espacio, de la partición
de entrenamiento de la plata. Se guarda junto a los pesos, en
``ml_artifacts/sentiment/<model_version>/training_vocab.txt``, una palabra por
línea.

``build-vocab`` lo arma una vez desde el archivo de EPIC-5 en el mismo bucket
(``archive/epic5/labels/silver_v0/``, F-11): lee los parquet en memoria y
sube el resultado, sin escribir a disco. Son palabras de reseñas y la regex
no detecta nombres (F-01), así que el archivo no sale de GCP.
"""

import hashlib
import io
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any, Final

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from google.cloud import bigquery

from ml_inference import artifacts
from ml_inference.config import InferenceSettings

ARCHIVE_PREFIX: Final = "archive/epic5/labels/silver_v0/"
VOCAB_FILE: Final = "training_vocab.txt"
TRAIN_SPLIT: Final = "entrenamiento"


def vocab_blob(settings: InferenceSettings, model_version: str) -> str:
    prefix = artifacts.artifact_prefix(
        settings.ml_artifacts_prefix, artifacts.SENTIMENT, model_version
    )
    return f"{prefix}{VOCAB_FILE}"


def training_vocab(texts: pa.Table, rows: pa.Table) -> set[str]:
    """Palabras de los textos de la partición de entrenamiento."""
    train = rows.filter(pc.equal(rows["split"], TRAIN_SPLIT))
    ids = pc.unique(train["text_id"])
    kept = texts.filter(pc.is_in(texts["text_id"], value_set=ids))
    words: set[str] = set()
    for text in kept["texto_sanitizado"].to_pylist():
        if text is not None:
            words.update(text.lower().split(" "))
    return words


def encode(words: Iterable[str]) -> bytes:
    return "".join(f"{w}\n" for w in sorted(words)).encode("utf-8")


def build_vocab(
    settings: InferenceSettings, storage: Any, model_version: str
) -> tuple[int, str]:
    """Arma el vocabulario desde el archivo y lo sube (tamaño y hash)."""
    bucket = storage.bucket(settings.gcs_raw_datalake_bucket)

    def table(name: str, columns: list[str]) -> pa.Table:
        data = bucket.blob(f"{ARCHIVE_PREFIX}{name}").download_as_bytes()
        return pq.read_table(io.BytesIO(data), columns=columns)

    words = training_vocab(
        table("texts.parquet", ["text_id", "texto_sanitizado"]),
        table("rows.parquet", ["text_id", "split"]),
    )
    if not words:
        raise ValueError("the training split has no words")
    data = encode(words)
    bucket.blob(vocab_blob(settings, model_version)).upload_from_string(
        data, content_type="text/plain; charset=utf-8"
    )
    return len(words), hashlib.sha256(data).hexdigest()


def load_vocab(
    settings: InferenceSettings, storage: Any, model_version: str
) -> frozenset[str]:
    """Vocabulario del modelo; ``FileNotFoundError`` si no se ha subido."""
    from google.api_core.exceptions import NotFound

    blob = storage.bucket(settings.gcs_raw_datalake_bucket).blob(
        vocab_blob(settings, model_version)
    )
    try:
        data = blob.download_as_bytes()
    except NotFound:
        raise FileNotFoundError(f"no vocabulary for {model_version}") from None
    return frozenset(data.decode("utf-8").split("\n")[:-1])


def stage_vocab(
    client: Any, dataset: str, words: Iterable[str], now: datetime
) -> str:
    """Tabla temporal ``(word)`` con el vocabulario; expira en 1 h."""
    table_id = f"{dataset}._vocab_{now:%Y%m%d%H%M%S}"
    schema = [bigquery.SchemaField("word", "STRING", mode="REQUIRED")]
    table = bigquery.Table(table_id, schema=schema)
    table.expires = now + timedelta(hours=1)
    client.create_table(table)
    client.load_table_from_json(
        [{"word": w} for w in sorted(words)],
        table_id,
        job_config=bigquery.LoadJobConfig(
            schema=schema,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        ),
    ).result()
    return table_id
