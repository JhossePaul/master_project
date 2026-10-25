"""Carga del backfill: parquet sintéticos con las columnas reales, sin red."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from ml_inference.bq_io import StagingMergeWriter
from ml_inference.config import InferenceSettings
from ml_inference.load_local import (
    Loader,
    LocalBackfill,
    aspects_sql,
    curation_rows,
    load_backfill,
    predictions_sql,
)
from voc_common.constants import SentimentLabel
from voc_nlp.lexicon import Lexicon

NOW = datetime(2026, 11, 5, tzinfo=UTC)
ACTOR = "b" * 64
KEY_A, KEY_B = "a" * 64, "c" * 64


class _Job:
    def __init__(self, rows: list[dict] | None = None, affected: int = 0):
        self.rows = rows or []
        self.num_dml_affected_rows = affected
        self.errors = None

    def result(
        self, timeout: float | None = None, page_size: int | None = None
    ):
        return [type("R", (dict,), {})(r) for r in self.rows]


class LoadBigQuery:
    """Registra cargas de parquet, DML y borrados; sirve el TDS y el estado."""

    def __init__(self, tds: list[dict[str, Any]], state: dict[str, list]):
        self.tds = tds
        self.state = state
        self.loaded: dict[str, pa.Table] = {}
        self.dml: list[tuple[str, dict]] = []
        self.deleted: list[str] = []
        self.merged: dict[str, list] = {}
        self.staging_rows: dict[str, list] = {}

    def query(self, sql: str, job_config: Any = None, **_: Any) -> _Job:
        params = {
            p.name: getattr(p, "value", getattr(p, "values", None))
            for p in getattr(job_config, "query_parameters", []) or []
        }
        if sql.startswith("SELECT id_resena, bank_id, fecha, texto_limpio"):
            return _Job(self.tds)
        if ".model_versions`" in sql and sql.lstrip().startswith("SELECT"):
            return _Job(self.state["model_versions"])
        if "risk_policy_current" in sql:
            return _Job(self.state["risk_policy"])
        if sql.lstrip().startswith("SELECT"):
            return _Job([])
        if sql.lstrip().startswith("MERGE `") and "._staging_" in sql:
            target, staging = re.findall(r"`([^`]+)`", sql)[:2]
            rows = self.staging_rows[staging]
            self.merged[target.rsplit(".", 1)[-1]] = rows
            return _Job(affected=len(rows))
        self.dml.append((sql, params))
        return _Job(affected=7)

    def load_table_from_file(
        self, handle: Any, table_id: str, **_: Any
    ) -> _Job:
        self.loaded[table_id.rsplit(".", 1)[-1]] = pq.read_table(handle)
        return _Job()

    def get_table(self, table_id: str) -> Any:
        return type("T", (), {"expires": None})()

    def update_table(self, table: Any, fields: list[str]) -> None:
        assert fields == ["expires"]

    def delete_table(self, table: Any, **_: Any) -> None:
        self.deleted.append(str(table))

    # StagingMergeWriter
    def create_table(self, table: Any, **_: Any) -> None:
        pass

    def load_table_from_json(self, rows: list, dest: str, **_: Any) -> _Job:
        self.staging_rows[dest] = rows
        return _Job()


class FakeStorage:
    def __init__(self) -> None:
        self.uploaded: list[str] = []

    def bucket(self, name: str) -> Any:
        storage = self

        class _Bucket:
            def blob(self, path: str) -> Any:
                class _Blob:
                    def upload_from_filename(self, local: str) -> None:
                        storage.uploaded.append(path)

                return _Blob()

        return _Bucket()


def _files(tmp_path: Path) -> LocalBackfill:
    run = tmp_path / "backfill" / "20261022"
    (run / "preds").mkdir(parents=True)
    (run / "aspects").mkdir()
    (run / "embeddings").mkdir()
    model = run / "topics" / "model_v0"
    model.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "text_key": [KEY_A, KEY_B],
                "p_NEG": pa.array([0.9, 0.1], pa.float32()),
                "p_NEU": pa.array([0.05, 0.1], pa.float32()),
                "p_POS": pa.array([0.05, 0.8], pa.float32()),
            }
        ),
        run / "preds" / "preds_s1.parquet",
    )
    pq.write_table(
        pa.table(
            {
                "text_key": [KEY_A],
                "codes": ["AC,UI"],
                "actualizacion": [True],
                "seguridad": [False],
                "elogio": [False],
                "prompt": ["aspects_v2_1"],
            }
        ),
        run / "aspects" / "labels_by_key.parquet",
    )
    pq.write_table(
        pa.table({"text_key": [KEY_A, KEY_B]}),
        run / "embeddings" / "keys.parquet",
    )
    np.save(
        run / "embeddings" / "emb_minilm.npy", np.ones((2, 384), np.float32)
    )
    pq.write_table(
        pa.table(
            {
                "text_id": pa.array([1, 1], pa.uint32()),
                "text_key": [KEY_A, KEY_A],
                "orden": [0, 1],
                "topic": pa.array([4, -1], pa.int32()),
            }
        ),
        run / "topics" / "segment_topics_v0.parquet",
    )
    np.save(
        run / "topics" / "emb_segments_minilm.npy",
        np.full((2, 384), 0.25, np.float32),
    )
    (model / "umap.pkl").write_bytes(b"x")
    (model / "bertopic").write_bytes(b"x")
    (model / "model.json").write_text(
        json.dumps(
            {
                "variante": "clausulas_mcs100",
                "segmentador": "clauses_v0",
                "embeddings": "sentence-transformers/x",
                "max_seq": 128,
                "min_cluster_size": 100,
                "min_samples": 10,
                "semilla_umap": 0,
                "segmentos_ajuste": 63040,
                "topicos": 2,
                "generado": "2026-10-23T02:11:55+00:00",
            }
        )
    )
    (run / "manifest.json").write_text(json.dumps({"textos_unicos": 2}))
    weights = tmp_path / "weights"
    weights.mkdir()
    (weights / "config.json").write_text("{}")
    minilm = tmp_path / "minilm"
    minilm.mkdir()
    (minilm / "modules.json").write_text("[]")
    curation = tmp_path / "revision_topicos.csv"
    curation.write_text(
        "topico,grupo,terminos,peso_neg_pct,familia_mayoritaria,pureza,"
        "nombre_propuesto,coherencia_1a5,util_para_producto_si_no,"
        "familia_correcta,tema_nuevo_si_no,comentario\n"
        "4,principal,t,1,AC,0.5,Token,4,Si,AC,No,\n"
        "7,principal,t,1,TR,0.5,Cajeros,3,No,MEZCLA,Si,\n"
        "9,principal,t,1,OT,0.5,,1,No,,No,\n"
    )
    gold = tmp_path / "gold.parquet"
    pq.write_table(
        pa.table(
            {
                "split": ["dev", "aspects_gold_v2_1"],
                "task": ["sentiment", "aspects"],
                "id_resena": ["r1", None],
                "text_key": [KEY_A, KEY_B],
                "label": ["NEG", None],
                "families": pa.array([[], ["AC"]], pa.list_(pa.string())),
                "flag_update": [None, False],
                "flag_security": [None, False],
                "praise": [None, True],
                "weight": [12.5, None],
                "guideline_version": ["v2.2", "v2.1"],
            }
        ),
        gold,
    )
    return LocalBackfill(run, weights, curation, gold, minilm)


def _state() -> dict[str, list]:
    return {
        "model_versions": [
            {
                "model_version": "robertuito_sentiment_v1",
                "registry_uri": "gs://b/ml_artifacts/sentiment/x/",
                "base_checkpoint": "base",
                "training_data": "silver",
                "calibration_version": "temperature_v0_s1",
                "calibration_t": 1.6811,
                "license": "nc",
                "status": "promoted",
                "promoted_at": NOW,
                "promoted_by_hash": ACTOR,
                "recorded_at": NOW,
            }
        ],
        "risk_policy": [],
    }


def _settings() -> InferenceSettings:
    return InferenceSettings(gcp_project_id="p", gcs_raw_datalake_bucket="b")


def _tds() -> list[dict[str, Any]]:
    fecha = datetime(2026, 10, 1, tzinfo=UTC)
    return [
        {
            "id_resena": "r1",
            "bank_id": "BBVA",
            "fecha": fecha,
            "texto_limpio": "no abre la app",
        },
        {
            "id_resena": "r2",
            "bank_id": "BBVA",
            "fecha": fecha,
            "texto_limpio": "excelente",
        },
        {
            "id_resena": "r3",
            "bank_id": "BBVA",
            "fecha": fecha,
            "texto_limpio": "😡",
        },
    ]


def _run(tmp_path: Path) -> tuple[LoadBigQuery, FakeStorage, list]:
    bq = LoadBigQuery(_tds(), _state())
    storage = FakeStorage()
    runs = load_backfill(
        _settings(),
        bq,
        storage,
        _files(tmp_path),
        tmp_path,
        ACTOR,
        NOW,
        lexicon=Lexicon("lexicon_v1", {"excelente": SentimentLabel.POS}),
        topic_terms=lambda path: {4: ["token", "sms"], 7: ["cajero"]},
    )
    return bq, storage, runs


def test_eligibility_file_has_no_text(tmp_path: Path) -> None:
    bq, _, _ = _run(tmp_path)
    elig = next(t for n, t in bq.loaded.items() if "eligibility" in n)
    assert elig.column_names == [
        "id_resena",
        "eligibility_code",
        "label_source",
        "lexicon_label",
        "palabras",
    ]
    rows = {r["id_resena"]: r for r in elig.to_pylist()}
    assert rows["r1"]["label_source"] == "MODEL"
    assert rows["r2"]["label_source"] == "RULE_BASED"
    assert rows["r2"]["lexicon_label"] == "POS"
    assert rows["r3"]["eligibility_code"] == "TNSS_NO_TEXT_CONTENT"


def test_uploads_artifacts_and_staging_without_text(tmp_path: Path) -> None:
    bq, storage, _ = _run(tmp_path)
    assert "ml_artifacts/sentiment/robertuito_sentiment_v1/config.json" in (
        storage.uploaded
    )
    assert any(
        p.startswith("ml_artifacts/topics/topics_v1/") for p in storage.uploaded
    )
    assert any(
        p.startswith(
            "ml_artifacts/embeddings/paraphrase-multilingual-MiniLM-L12-v2/"
        )
        for p in storage.uploaded
    )
    for table in bq.loaded.values():
        assert "texto_sanitizado" not in table.column_names
        assert "texto_limpio" not in table.column_names
    emb = next(t for n, t in bq.loaded.items() if "embeddings" in n)
    assert len(emb.column("embedding")[0]) == 384
    # Toda tabla temporal se borra al terminar.
    dropped = {d.rsplit(".", 1)[-1] for d in bq.deleted if "._load_" in d}
    assert dropped == set(bq.loaded)


def test_merge_parameters_and_runs(tmp_path: Path) -> None:
    bq, _, runs = _run(tmp_path)
    sqls = [sql for sql, _ in bq.dml]
    assert len(sqls) == 5
    preds = bq.dml[0][1]
    assert preds["t"] == pytest.approx(1.6811)
    assert preds["threshold"] is None and preds["policy_version"] is None
    assert preds["model_version"] == "robertuito_sentiment_v1"
    assert {r.run_id.rsplit("-", 1)[-1] for r in runs} == {
        "sentiment",
        "aspects",
        "topics",
    }
    sentiment = next(r for r in runs if r.run_id.endswith("sentiment"))
    assert sentiment.environment.value == "kaggle" and sentiment.texts == 2
    assert sentiment.reviews == 7


def test_predictions_sql_replicates_calibration_and_skips_unpredicted() -> None:
    sql = predictions_sql("p.d", "p.d.tds", "p.d._e", "p.d._p")
    assert "LN(GREATEST(LEAST(p.p_NEG, 1.0), 1e-6)) / @t" in sql
    assert "NOT (e.label_source = 'MODEL' AND p.text_key IS NULL)" in sql
    assert "WHEN NOT MATCHED THEN INSERT ROW" in sql
    assert "GREATEST(pn, pu, pp) < @threshold" in sql


def test_aspects_sql_keeps_only_the_eleven_families() -> None:
    sql = aspects_sql("p.d", "p.d._l")
    assert "c IN UNNEST(@families)" in sql
    assert "p.sentiment = 'NEG' AND p.palabras >= 2" in sql


def test_curation_audience_rule(tmp_path: Path) -> None:
    rows = {
        r.topic_id: r
        for r in curation_rows(_files(tmp_path).curation_csv, ACTOR, NOW)
    }
    assert rows[4].audience.value == "producto"
    assert [f.value for f in rows[4].families] == ["AC"]
    assert rows[7].audience.value == "ingenieria" and rows[7].families == []
    assert rows[7].is_new_theme
    assert rows[9].audience.value == "sin_valor"
    assert rows[9].curated_name == "tópico 9"


def test_topic_tables_and_gold(tmp_path: Path) -> None:
    bq = LoadBigQuery(_tds(), _state())
    files = _files(tmp_path)
    loader = Loader(
        _settings(),
        bq,
        FakeStorage(),
        files,
        tmp_path,
        ACTOR,
        NOW,
        topic_terms=lambda path: {4: ["token"], 7: ["cajero"]},
    )
    writer = StagingMergeWriter(bq, "p.bbva_voc_tds")
    counts = loader.topic_tables(writer)
    assert set(counts) == {
        "topic_model_versions",
        "topic_catalog",
        "curation_topics",
    }
    assert loader.gold(writer) == 2
    gold = bq.merged["gold_labels"]
    assert {g["split"] for g in gold} == {"dev", "aspects_gold_v2_1"}
    assert next(g for g in gold if g["split"] == "dev")["weight"] == 12.5


def test_embeddings_must_match_keys(tmp_path: Path) -> None:
    files = _files(tmp_path)
    np.save(
        files.run_dir / "embeddings" / "emb_minilm.npy",
        np.ones((3, 384), np.float32),
    )
    loader = Loader(
        _settings(),
        LoadBigQuery([], _state()),
        FakeStorage(),
        files,
        tmp_path,
        ACTOR,
        NOW,
    )
    with pytest.raises(ValueError, match="differ"):
        loader.embeddings_file()


def test_segment_embeddings_come_from_the_backfill_vectors(
    tmp_path: Path,
) -> None:
    bq, _, _ = _run(tmp_path)
    staged = next(t for n, t in bq.loaded.items() if "segment_embeddings" in n)
    assert staged.column_names == ["text_key", "segment_index", "embedding"]
    assert staged.column("segment_index").to_pylist() == [0, 1]
    assert len(staged.column("embedding")[0]) == 384
    sql, params = next(
        (q, p) for q, p in bq.dml if ".segment_embeddings` T" in q
    )
    assert "T.segment_index = S.segment_index" in sql
    assert params["segmenter"] == "clause_segmenter_v1"
    assert params["model"].endswith("MiniLM-L12-v2")


def test_segment_vectors_must_match_segments(tmp_path: Path) -> None:
    files = _files(tmp_path)
    np.save(
        files.run_dir / "topics" / "emb_segments_minilm.npy",
        np.ones((3, 384), np.float32),
    )
    loader = Loader(
        _settings(),
        LoadBigQuery([], _state()),
        FakeStorage(),
        files,
        tmp_path,
        ACTOR,
        NOW,
    )
    with pytest.raises(ValueError, match="differ"):
        loader.segment_embeddings_file()


def test_without_segment_vectors_nothing_is_loaded(tmp_path: Path) -> None:
    files = _files(tmp_path)
    (files.run_dir / "topics" / "emb_segments_minilm.npy").unlink()
    bq = LoadBigQuery([], _state())
    loader = Loader(_settings(), bq, FakeStorage(), files, tmp_path, ACTOR, NOW)
    assert loader.segment_embeddings() == 0
    assert bq.loaded == {} and bq.dml == []


def test_gold_ids_have_no_text_nor_labels(tmp_path: Path) -> None:
    from ml_inference.load_local import gold_ids_table, upload_gold_ids

    for queue, ids in (("gold_v0", ["r1", "r2"]), ("gold_v1", ["r2", "r3"])):
        (tmp_path / queue).mkdir()
        pq.write_table(
            pa.table(
                {
                    "id_resena": ids,
                    "texto_sanitizado": [f"texto {i}" for i in ids],
                    "gemini_s": ["NEG"] * len(ids),
                }
            ),
            tmp_path / queue / "queue.parquet",
        )
    table = gold_ids_table(tmp_path)
    assert table.column_names == ["id_resena", "text_key"]
    assert sorted(table["id_resena"].to_pylist()) == ["r1", "r2", "r3"]
    uploaded: dict[str, bytes] = {}

    class _Blob:
        def __init__(self, name: str) -> None:
            self.name = name

        def upload_from_string(self, data: bytes, **_: Any) -> None:
            uploaded[self.name] = data

    class _Storage:
        def bucket(self, name: str) -> Any:
            return type("B", (), {"blob": lambda self, n: _Blob(n)})()

    assert upload_gold_ids(_settings(), _Storage(), tmp_path) == 3
    assert list(uploaded) == ["archive/epic5/labels/silver_v0/gold_ids.parquet"]
    with pytest.raises(FileNotFoundError):
        gold_ids_table(tmp_path / "vacio")
