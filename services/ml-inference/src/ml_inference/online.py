"""Servicio privado ``voc-ml-online``: explicación y embedding bajo pedido.

PyTorch, RoBERTuito y MiniLM no caben en la API del portal (1 GiB), así que
la API los llama aquí con un ID token. Cada modelo se carga la primera vez que
se usa y se conserva en memoria. Ni el texto ni su explicación se registran.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel, Field, field_validator
from voc_common.operations_v3 import TokenAttribution

from ml_inference import artifacts
from ml_inference.config import InferenceSettings

MAX_WORDS: Final = 128
MAX_QUERY_CHARS: Final = 1000
EXPLAIN_METHOD: Final = "occlusion_v2"


class Explainer(Protocol):
    def explain(
        self, text: str, temperature: float
    ) -> tuple[list[TokenAttribution], list[float]]:
        """Atribuciones y las tres probabilidades calibradas del texto."""


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class OnlineLoaders:
    """Cómo se cargan los modelos; las pruebas los sustituyen."""

    sentiment: Callable[[str], Explainer]
    temperature: Callable[[str], float]
    embedder: Callable[[], tuple[str, Embedder]]


class ExplainIn(BaseModel):
    text: str = Field(min_length=1)
    model_version: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def _word_cap(cls, text: str) -> str:
        if len(text.split()) > MAX_WORDS:
            raise ValueError(f"at most {MAX_WORDS} words")
        return text


class ExplainOut(BaseModel):
    model_version: str
    method: str
    attributions: list[TokenAttribution]
    p_neg: float
    p_neu: float
    p_pos: float


class EmbedIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)


class EmbedOut(BaseModel):
    embedding_model: str
    embedding: list[float]


class OnlineModels:
    """Carga perezosa y segura entre hilos de cada modelo."""

    def __init__(self, loaders: OnlineLoaders) -> None:
        self._loaders = loaders
        self._lock = threading.Lock()
        self._sentiment: dict[str, Explainer] = {}
        self._embedder: tuple[str, Embedder] | None = None

    def sentiment(self, model_version: str) -> Explainer:
        with self._lock:
            if model_version not in self._sentiment:
                # Un solo modelo de sentimiento en memoria a la vez.
                self._sentiment.clear()
                self._sentiment[model_version] = self._loaders.sentiment(
                    model_version
                )
            return self._sentiment[model_version]

    def embedder(self) -> tuple[str, Embedder]:
        with self._lock:
            if self._embedder is None:
                self._embedder = self._loaders.embedder()
            return self._embedder

    def temperature(self, model_version: str) -> float:
        return self._loaders.temperature(model_version)

    @property
    def loaded(self) -> list[str]:
        out = [f"sentiment:{v}" for v in self._sentiment]
        if self._embedder is not None:
            out.append(f"embedder:{self._embedder[0]}")
        return out


def create_app(models: OnlineModels) -> FastAPI:
    app = FastAPI(title="voc-ml-online", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "loaded": models.loaded}

    @app.post("/explain")
    def explain(body: ExplainIn) -> ExplainOut:
        engine = models.sentiment(body.model_version)
        attributions, proba = engine.explain(
            body.text, models.temperature(body.model_version)
        )
        return ExplainOut(
            model_version=body.model_version,
            method=EXPLAIN_METHOD,
            attributions=attributions,
            p_neg=proba[0],
            p_neu=proba[1],
            p_pos=proba[2],
        )

    @app.post("/embed")
    def embed(body: EmbedIn) -> EmbedOut:
        name, embedder = models.embedder()
        return EmbedOut(
            embedding_model=name, embedding=embedder.embed(body.text)
        )

    return app


# -- carga real (red y modelos) ---------------------------------------------


class _RealExplainer:
    def __init__(self, weights: Path, batch_size: int, threads: int) -> None:
        import torch
        from voc_nlp.sentiment_model import load_sentiment_model

        torch.set_num_threads(threads)
        self._model = load_sentiment_model(weights)
        self._batch = batch_size

    def explain(
        self, text: str, temperature: float
    ) -> tuple[list[TokenAttribution], list[float]]:
        from voc_nlp.calibration import apply_temperature
        from voc_nlp.explain import occlusion_v2
        from voc_nlp.sentiment_model import predict_proba

        proba = apply_temperature(
            predict_proba(self._model, [text], self._batch), temperature
        )[0]
        return (
            occlusion_v2(self._model, text, temperature, self._batch),
            [float(p) for p in np.asarray(proba)],
        )


class _RealEmbedder:
    def __init__(self, path: Path) -> None:
        from voc_nlp.topics import load_embedder

        self._model = load_embedder(path)

    def embed(self, text: str) -> list[float]:
        from voc_nlp.topics import embed

        return [float(x) for x in embed(self._model, [text])[0]]


def real_loaders(
    settings: InferenceSettings,
    storage: Any,
    bigquery: Any,
) -> OnlineLoaders:  # pragma: no cover - red real
    def download(kind: str, name: str) -> Path:
        dest = settings.artifacts_dir / kind / name
        if not dest.exists():
            artifacts.download_prefix(
                storage,
                settings.gcs_raw_datalake_bucket,
                artifacts.artifact_prefix(
                    settings.ml_artifacts_prefix, kind, name
                ),
                dest,
            )
        return dest

    def sentiment(version: str) -> Explainer:
        return _RealExplainer(
            download(artifacts.SENTIMENT, version),
            settings.sentiment_batch_size,
            settings.torch_threads,
        )

    def temperature(version: str) -> float:
        from google.cloud import bigquery as bq

        sql = (
            "SELECT calibration_t FROM "  # noqa: S608  # nosec B608
            f"`{settings.dataset}.model_versions` "
            "WHERE model_version = @v LIMIT 1"  # igual en todas sus filas
        )
        config = bq.QueryJobConfig(
            query_parameters=[bq.ScalarQueryParameter("v", "STRING", version)]
        )
        rows = list(bigquery.query(sql, job_config=config).result())
        if not rows:
            raise LookupError(f"unknown model version {version!r}")
        return float(rows[0]["calibration_t"])

    def embedder() -> tuple[str, Embedder]:
        from voc_nlp.topics import EMBEDDING_MODEL

        name = EMBEDDING_MODEL.rsplit("/", 1)[-1]
        return EMBEDDING_MODEL, _RealEmbedder(
            download(artifacts.EMBEDDINGS, name)
        )

    return OnlineLoaders(sentiment, temperature, embedder)
