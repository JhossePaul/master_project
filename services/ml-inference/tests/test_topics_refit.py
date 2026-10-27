"""Re-ajuste de tópicos: cuándo toca, muestra, pares y orden de escritura."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from ml_inference.config import InferenceSettings
from ml_inference.engines import EngineLoaders
from ml_inference.topics_refit import (
    SAMPLE_SEED,
    TopicsRefit,
    is_due,
    next_version,
    quarter_start,
    window,
)
from voc_common.analytics_codes import RunKind
from voc_nlp.topics_refit import TopicParams

pytest.importorskip("bertopic")

NOW = datetime(2026, 10, 5, 6, tzinfo=UTC)
THEMES = {
    "transferencia spei rechazada": 0,
    "contraseña bloqueada token": 1,
    "cobro doble comision": 2,
}


def policy(frequency: str = "quarterly", mode: str = "scheduled") -> Any:
    return type(
        "P", (), {"topic_refit_frequency": frequency, "topic_refit_mode": mode}
    )()


def test_due_once_per_quarter() -> None:
    assert quarter_start(NOW) == datetime(2026, 10, 1, tzinfo=UTC)
    assert is_due(policy(), None, NOW)
    assert is_due(policy(), datetime(2026, 9, 30, tzinfo=UTC), NOW)
    assert not is_due(policy(), datetime(2026, 10, 2, tzinfo=UTC), NOW)
    assert not is_due(policy("monthly"), None, NOW)
    assert not is_due(None, None, NOW)


def test_window_and_version_names() -> None:
    assert window(NOW) == (
        datetime(2025, 10, 1, tzinfo=UTC),
        datetime(2026, 10, 1, tzinfo=UTC),
    )
    assert window(datetime(2026, 1, 9, tzinfo=UTC))[0] == datetime(
        2025, 1, 1, tzinfo=UTC
    )
    assert next_version("topics_v1") == "topics_v2"
    assert next_version(None) == "topics_v1"
    assert next_version("custom") == "custom_v2"


# -- Dobles ------------------------------------------------------------------


class Blob:
    def __init__(self, store: "Storage", name: str) -> None:
        self.store, self.name = store, name

    def download_to_filename(self, path: str) -> None:
        Path(path).write_bytes(b"x")

    def upload_from_filename(self, path: str) -> None:
        self.store.uploaded.append(self.name)


class Storage:
    def __init__(self) -> None:
        self.uploaded: list[str] = []

    def list_blobs(self, bucket: str, prefix: str) -> list[Blob]:
        return [Blob(self, f"{prefix}config.json")]

    def bucket(self, name: str) -> Any:
        store = self
        return type("B", (), {"blob": lambda _, n: Blob(store, n)})()


class Job:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def result(self, timeout: float | None = None) -> list[dict]:
        return self.rows


class BigQuery:
    def __init__(self, versions: list[dict], texts: int = 60) -> None:
        self.versions = versions
        self.texts = texts
        self.params: dict[str, Any] = {}

    def query(self, sql: str, job_config: Any = None, **_: Any) -> Job:
        if "FROM `test-project.bbva_voc_tds.topic_model_versions`" in sql:
            return Job(self.versions)
        assert "FARM_FINGERPRINT" in sql and "palabras >= 2" in sql
        self.params = {p.name: p.value for p in job_config.query_parameters}
        rows = []
        for theme in THEMES:
            for i in range(self.texts):
                rows.append(
                    {
                        "text_key": f"{theme[:5]}{i:03d}",
                        "bank_id": "BBVA",
                        "texto": f"{theme} caso {i}. y ademas {theme} otra vez",
                    }
                )
        return Job(rows)


class Writer:
    def __init__(self) -> None:
        self.tables: list[tuple[str, list]] = []

    def write(self, table: str, rows: list, key: list, run_id: str) -> int:
        self.tables.append((table, rows))
        return len(rows)


def theme_of(text: str) -> int:
    return next(k for t, k in THEMES.items() if t.split()[0] in text)


class Embedder:
    def embed(self, texts: list[str]) -> np.ndarray:
        rng = np.random.default_rng(0)
        out = np.zeros((len(texts), 12), dtype=np.float32)
        for i, text in enumerate(texts):
            out[i, theme_of(text) * 4] = 10.0
        return out + rng.normal(0, 0.2, out.shape).astype(np.float32)


class Previous:
    """Versión vigente: los temas con otros ids (10, 11, 12)."""

    def assign(self, segments: list[str], emb: np.ndarray) -> list[int]:
        return [10 + theme_of(s) for s in segments]


def job(bq: BigQuery, **kw: Any) -> tuple[TopicsRefit, Storage, Writer]:
    storage, writer = Storage(), Writer()
    settings = InferenceSettings(
        gcp_project_id="test-project", gcs_raw_datalake_bucket="bucket"
    )
    refit = TopicsRefit(
        settings,
        bq,
        storage,
        writer,  # type: ignore[arg-type]
        engines=EngineLoaders(
            embedder=lambda path: Embedder(), topics=lambda path: Previous()
        ),
        params=TopicParams(min_cluster_size=15, min_samples=3, n_neighbors=10),
        min_texts=10,
        **kw,
    )
    return refit, storage, writer


def statuses(writer: Writer) -> list[str]:
    return [rows[0].status.value for _, rows in writer.tables]


def test_the_run_records_who_launched_it_and_why() -> None:
    refit, _, writer = job(
        BigQuery([]),
        actor_hash="a" * 64,
        reason="nuevo vocabulario tras la actualización",
        clock=lambda: NOW + timedelta(minutes=7),
    )
    assert refit.run(policy(mode="manual"), None, NOW, force=True)
    start, end = writer.tables[0][1][0], writer.tables[-1][1][0]
    assert (start.status.value, end.status.value) == ("running", "succeeded")
    assert start.run_id == end.run_id == "topics-refit-topics_v1"
    assert end.kind is RunKind.TOPIC_REFIT
    assert end.actor_hash == "a" * 64 and end.reason.startswith("nuevo")
    assert end.ended_at == NOW + timedelta(minutes=7)
    assert end.texts == 180 and end.cost_usd == 0.0
    assert end.peak_memory_mib is not None


def test_a_scheduled_run_has_no_actor() -> None:
    refit, _, writer = job(BigQuery([]))
    assert refit.run(policy(), None, NOW)
    row = writer.tables[-1][1][0]
    assert row.actor_hash is None and row.reason is None


def test_refit_pairs_topics_and_writes_the_version_last() -> None:
    bq = BigQuery(
        [
            {
                "topic_model_version": "topics_v1",
                "fitted_at": "2026-07-01T00:00:00Z",
            }
        ]
    )
    refit, storage, writer = job(bq)
    assert refit.run(policy(), "topics_v1", NOW) == "topics_v2"
    assert bq.params["seed"] == SAMPLE_SEED and bq.params["total"] == 40_000
    assert bq.params["start"] == datetime(2025, 10, 1, tzinfo=UTC)
    assert [t for t, _ in writer.tables] == [
        "inference_runs",
        "topic_catalog",
        "topic_model_versions",
        "inference_runs",
    ]
    catalog = writer.tables[1][1]
    assert len(catalog) == 3
    # Cada tópico nuevo se empareja con el mismo tema de la versión vigente.
    by_previous = {c.previous_topic_id: c for c in catalog}
    assert set(by_previous) == {10, 11, 12}
    assert all(c.centroid_similarity > 0.9 for c in catalog)
    assert "spei" in " ".join(by_previous[10].terms)
    version = writer.tables[2][1][0]
    assert version.topic_model_version == "topics_v2"
    assert (
        version.params["topicos"] == 3
        and version.params["anterior"] == "topics_v1"
    )
    assert version.params["textos_ajuste"] == 180
    assert "igual por banco" in version.fit_sample
    prefix = "ml_artifacts/topics/topics_v2/"
    uploaded = {n.removeprefix(prefix).split("/")[0] for n in storage.uploaded}
    assert {"umap.pkl", "bertopic", "model.json"} <= uploaded


def test_first_version_has_no_pairs() -> None:
    refit, _, writer = job(BigQuery([]))
    assert refit.run(policy(), None, NOW) == "topics_v1"
    assert all(c.previous_topic_id is None for c in writer.tables[1][1])


def test_not_due_or_too_small_writes_nothing() -> None:
    recent = [
        {
            "topic_model_version": "topics_v2",
            "fitted_at": datetime(2026, 10, 2, tzinfo=UTC),
        }
    ]
    refit, _, writer = job(BigQuery(recent))
    assert refit.run(policy(), "topics_v2", NOW) is None
    assert writer.tables == []


def test_a_forced_run_with_too_few_texts_closes_as_failed() -> None:
    recent = [
        {
            "topic_model_version": "topics_v2",
            "fitted_at": datetime(2026, 10, 2, tzinfo=UTC),
        }
    ]
    small, _, writer = job(BigQuery(recent, texts=2))
    assert small.run(policy(), "topics_v2", NOW, force=True) is None
    assert [t for t, _ in writer.tables] == ["inference_runs"] * 2
    assert statuses(writer) == ["running", "failed"]


def test_a_fit_without_topics_fails_before_writing() -> None:
    empty = type(
        "M",
        (),
        {"bertopic": type("B", (), {"get_topics": lambda self: {-1: []}})()},
    )()
    refit, storage, writer = job(
        BigQuery([]),
        fit=lambda segments, emb, params: (empty, [-1] * len(segments)),
    )
    with pytest.raises(RuntimeError, match="no topics"):
        refit.run(policy(), None, NOW)
    assert [t for t, _ in writer.tables] == ["inference_runs"] * 2
    assert statuses(writer) == ["running", "failed"]
    assert storage.uploaded == []


def test_manual_mode_refits_only_with_force() -> None:
    assert not is_due(policy(mode="manual"), None, NOW)
    refit, _, writer = job(BigQuery([]))
    assert refit.run(policy(mode="manual"), None, NOW) is None
    assert writer.tables == []
    assert (
        refit.run(policy(mode="manual"), None, NOW, force=True) == "topics_v1"
    )
