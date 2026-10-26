"""Motores de producción con los módulos de ``voc-nlp`` simulados."""

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from ml_inference import engines


def test_robertuito_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import voc_nlp.explain as explain
    import voc_nlp.sentiment_model as sentiment

    threads: list[int] = []
    import torch

    monkeypatch.setattr(torch, "set_num_threads", threads.append)
    monkeypatch.setattr(
        sentiment, "load_sentiment_model", lambda p: f"model:{p.name}"
    )
    monkeypatch.setattr(
        sentiment,
        "predict_proba",
        lambda m, t, b: np.full((len(t), 3), b / 100),
    )
    monkeypatch.setattr(
        explain, "occlusion_v2", lambda m, t, temp, b: [m, t, temp, b]
    )
    engine = engines.EngineLoaders().sentiment(tmp_path / "w", 32, 2)
    assert threads == [2]
    assert engine.predict(["a", "b"]).shape == (2, 3)
    assert engine.explain("hola", 1.4) == ["model:w", "hola", 1.4, 32]


def test_embedder_and_topics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import voc_nlp.topics as topics

    monkeypatch.setattr(topics, "load_embedder", lambda p: "st")
    monkeypatch.setattr(topics, "embed", lambda m, t: np.zeros((len(t), 384)))
    monkeypatch.setattr(topics, "load_topic_model", lambda p: "frozen")
    monkeypatch.setattr(topics, "assign", lambda m, s, e: [1] * len(s))
    loaders = engines.EngineLoaders()
    assert loaders.embedder(tmp_path).embed(["a"]).shape == (1, 384)
    assert loaders.topics(tmp_path).assign(["a", "b"], np.zeros((2, 2))) == [
        1,
        1,
    ]


def test_artifacts_round_trip(tmp_path: Path) -> None:
    from ml_inference import artifacts

    class _Blob:
        def __init__(self, name: str) -> None:
            self.name = name

        def download_to_filename(self, path: str) -> None:
            Path(path).write_text("x")

    class _Storage:
        def list_blobs(self, bucket: str, prefix: str) -> list[Any]:
            return [] if "vacio" in prefix else [_Blob(f"{prefix}a/b.bin")]

        def bucket(self, name: str) -> Any:
            return self

    out = artifacts.download_prefix(_Storage(), "b", "p/x/", tmp_path / "d")
    assert (out / "a" / "b.bin").read_text() == "x"

    class _TwoFiles(_Storage):
        def list_blobs(self, bucket: str, prefix: str) -> list[Any]:
            return [
                _Blob(f"{prefix}model.safetensors"),
                _Blob(f"{prefix}tf.h5"),
            ]

    skipped = artifacts.download_prefix(
        _TwoFiles(), "b", "p/x/", tmp_path / "s", skip=("tf.h5",)
    )
    assert (skipped / "model.safetensors").exists()
    assert not (skipped / "tf.h5").exists()
    with pytest.raises(FileNotFoundError):
        artifacts.download_prefix(_Storage(), "b", "p/vacio/", tmp_path / "e")
    with pytest.raises(FileNotFoundError):
        artifacts.upload_dir(_Storage(), "b", tmp_path / "nada", "p/")  # type: ignore[arg-type]


def test_gemini_cost_uses_the_configured_price() -> None:
    from ml_inference.config import InferenceSettings

    settings = InferenceSettings(
        gcp_project_id="p",
        gcs_raw_datalake_bucket="b",
        gemini_price_in=1.5,
        gemini_price_out=6.0,
    )
    usage = settings.gemini_usage()
    usage.prompt, usage.output, usage.thoughts = 1_000_000, 500_000, 500_000
    assert usage.cost_usd == 1.5 + 6.0


def test_gold_period_continues_after_2026() -> None:
    from ml_inference.lifecycle import gold_period

    assert [gold_period(y) for y in (2019, 2021, 2024, 2026, 2027, 2030)] == [
        "<=2019",
        "2020-2022",
        "2023-2024",
        "2025-2026",
        "2027-2028",
        "2029-2030",
    ]
