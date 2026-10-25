"""Re-scoring con Kaggle, GCS y BigQuery simulados: nada sale a la red."""

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from ml_inference import rescore
from ml_inference.config import InferenceSettings
from ml_inference.rescore import (
    Rescoring,
    check_slug,
    kernel_script,
    new_rescoring,
    parse_gcs,
    run_rescore,
)
from voc_common.operations_v3 import ModelVersion

NOW = datetime(2026, 11, 4, 9, 30, tzinfo=UTC)
RUN = "202611040930"
BUCKET = "bucket"
CANDIDATE = "robertuito_sentiment_v2"
TEXTS = {"k1": "la app no abre", "k2": "me cobraron doble", "k3": "excelente"}


CURRENT = "robertuito_sentiment_v1"


def model(status: str = "candidate", version: str = CANDIDATE) -> ModelVersion:
    return ModelVersion(
        model_version=version,
        registry_uri=f"gs://{BUCKET}/ml_artifacts/sentiment/{version}/",
        base_checkpoint="base",
        training_data="silver_v1",
        calibration_version="temperature_v2",
        calibration_t=1.5,
        license="nc",
        status=status,
        recorded_at=NOW,
        promoted_at=NOW if status == "promoted" else None,
        promoted_by_hash="b" * 64 if status == "promoted" else None,
    )


# -- GCS ---------------------------------------------------------------------


class Blob:
    def __init__(self, store: "Storage", name: str) -> None:
        self.store, self.name = store, name

    def download_to_filename(self, path: str) -> None:
        Path(path).write_bytes(self.store.objects[self.name])

    def upload_from_filename(self, path: str) -> None:
        self.store.objects[self.name] = Path(path).read_bytes()

    def delete(self) -> None:
        del self.store.objects[self.name]


class Storage:
    def __init__(self, tmp: Path) -> None:
        self.objects: dict[str, bytes] = {
            f"ml_artifacts/sentiment/{CANDIDATE}/config.json": b"{}",
            f"ml_artifacts/sentiment/{CANDIDATE}/model.safetensors": b"w",
        }
        self.tmp = tmp

    def export(self, keys: list[str]) -> None:
        path = self.tmp / "export.parquet"
        pq.write_table(
            pa.table(
                {
                    "text_key": keys,
                    "texto_sanitizado": [TEXTS[k] for k in keys],
                }
            ),
            path,
        )
        self.objects[f"rescore/{RUN}/texts/000.parquet"] = path.read_bytes()

    def list_blobs(self, bucket: str, prefix: str) -> list[Blob]:
        assert bucket == BUCKET
        return [
            Blob(self, n) for n in sorted(self.objects) if n.startswith(prefix)
        ]

    def bucket(self, name: str) -> Any:
        store = self

        class _Bucket:
            def blob(self, path: str) -> Blob:
                return Blob(store, path)

        return _Bucket()


# -- Kaggle ------------------------------------------------------------------


class Kaggle:
    user = "tester"

    def __init__(
        self, kernel: list[str], keys: list[str] | None = None
    ) -> None:
        self.kernel = list(kernel)
        self.keys = keys
        self.dataset_files: dict[str, Any] = {}
        self.pushed: dict[str, Any] = {}
        self.deleted: list[str] = []
        self.output_run = RUN

    def create_dataset(self, folder: Path) -> None:
        self.dataset_files = {
            p.name: (
                pq.read_table(p) if p.suffix == ".parquet" else p.read_text()
            )
            for p in folder.iterdir()
        }

    def dataset_status(self, ref: str) -> str:
        return "ready"

    def push_kernel(self, folder: Path) -> None:
        self.pushed = {
            "script": (folder / "run.py").read_text(),
            "meta": json.loads((folder / "kernel-metadata.json").read_text()),
        }

    def kernel_status(self, ref: str) -> str:
        assert ref == "tester/voc-ml-rescoring"
        return self.kernel.pop(0) if len(self.kernel) > 1 else self.kernel[0]

    def kernel_output(self, ref: str, dest: Path) -> None:
        tokens = self.dataset_files["tokens.parquet"]
        keys = self.keys or tokens.column("text_key").to_pylist()
        n = len(keys)
        pq.write_table(
            pa.table(
                {
                    "text_key": keys,
                    "p_NEG": [0.7] * n,
                    "p_NEU": [0.2] * n,
                    "p_POS": [0.1] * n,
                }
            ),
            dest / "preds.parquet",
        )
        (dest / "log.json").write_text(json.dumps({"run": self.output_run}))

    def delete_dataset(self, ref: str) -> None:
        self.deleted.append(ref)


# -- BigQuery ----------------------------------------------------------------


class Job:
    def __init__(self, rows: list[dict] | None = None, affected: int = 0):
        self.rows, self.num_dml_affected_rows = rows or [], affected

    def result(self, timeout: float | None = None, **_: Any) -> list[dict]:
        return self.rows


class BigQuery:
    def __init__(self, loaded_gap: int = 0, curve: bool = True) -> None:
        self.queries: list[tuple[str, dict[str, Any]]] = []
        self.loads: list[str] = []
        self.deleted: list[str] = []
        self.loaded_gap = loaded_gap
        self.curve = curve
        self.texts = 3
        # Oro dev por versión: el candidato acierta todas, el vigente no.
        self.gold: dict[str, list[dict[str, Any]]] = {}

    def query(self, sql: str, job_config: Any = None, **_: Any) -> Job:
        params = {
            p.name: getattr(p, "value", None)
            for p in getattr(job_config, "query_parameters", []) or []
        }
        self.queries.append((sql, params))
        if sql.lstrip().startswith("MERGE"):
            return Job(affected=5)
        if "AS expected" in sql:
            return Job(
                [
                    {
                        "expected": 5,
                        "loaded": 5 - self.loaded_gap,
                        "texts": self.texts,
                    }
                ]
            )
        if "risk_policy_current" in sql:
            return Job([{"hitl_target_coverage": 0.9}])
        if "hitl_coverage_curves" in sql:
            return Job([{}] if self.curve else [])
        if "gold_labels" in sql:
            return Job(self.gold.get(params["model_version"], []))
        return Job()

    def load_table_from_file(self, handle: Any, table_id: str, **_: Any) -> Job:
        self.loads.append(table_id)
        return Job()

    def get_table(self, table_id: str) -> Any:
        return type("T", (), {"expires": None})()

    def update_table(self, table: Any, fields: list[str]) -> None:
        pass

    def delete_table(self, table: str, **_: Any) -> None:
        self.deleted.append(table)

    def sql(self, needle: str) -> list[tuple[str, dict[str, Any]]]:
        return [q for q in self.queries if needle in q[0]]


class Tokenizer:
    pad_token_id = 1

    def __call__(self, texts: list[str], **_: Any) -> dict[str, list]:
        return {"input_ids": [[0, len(t), 2] for t in texts]}


class Writer:
    def __init__(self) -> None:
        self.rows: list[Any] = []
        self.checks: list[Any] = []

    def write(self, table: str, rows: list, key: list, run_id: str) -> int:
        assert table in ("inference_runs", "promotion_checks")
        if table == "promotion_checks":
            assert key == ["candidate_version", "current_version", "run_id"]
            self.checks += rows
        else:
            self.rows += rows
        return len(rows)


def gold_rows(right: int, n: int = 40) -> list[dict[str, Any]]:
    """Oro dev de una versión que acierta las primeras ``right`` reseñas."""
    labels = ["NEG", "NEU", "POS"]
    rows = []
    for i in range(n):
        label = labels[i % 3]
        rows.append(
            {
                "id_resena": f"g{i}",
                "label": label,
                "weight": 1.0,
                "bank_id": "BBVA",
                "fecha": NOW,
                "sentiment": label if i < right else labels[(i + 1) % 3],
                "label_source": "MODEL",
                "p_neg": 0.8,
                "p_neu": 0.1,
                "p_pos": 0.1,
            }
        )
    return rows


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(rescore, "load_tokenizer", lambda path: Tokenizer())
    import ml_inference.lifecycle as lifecycle

    monkeypatch.setattr(
        lifecycle,
        "point_for",
        lambda curve, coverage: type("P", (), {"threshold": 0.61})(),
    )
    monkeypatch.setattr(
        rescore.HitlCoverageCurve, "model_validate", lambda row: row
    )
    monkeypatch.setattr(
        rescore.RiskPolicy,
        "model_validate",
        lambda row: type("R", (), row)(),
    )
    storage = Storage(tmp_path)
    storage.export(sorted(TEXTS))
    settings = InferenceSettings(
        gcp_project_id="test-project",
        gcs_raw_datalake_bucket=BUCKET,
        artifacts_dir=tmp_path / "artifacts",
    )
    return {"storage": storage, "settings": settings, "tmp": tmp_path}


def make(
    setup: dict[str, Any],
    kaggle: Kaggle,
    bq: BigQuery | None = None,
    **kw: Any,
) -> Rescoring:
    clock = iter(range(0, 10**6, 60))
    return Rescoring(
        setup["settings"],
        bq or BigQuery(),
        setup["storage"],
        kaggle,
        model(),
        RUN,
        setup["tmp"] / "work",
        workers=kw.pop("workers", 1),
        sleep=lambda s: None,
        clock=lambda: next(clock),
        **kw,
    )


def run(job: Rescoring, timeout: float = 600) -> tuple[Any, Writer]:
    writer = Writer()
    times = iter(
        [NOW, NOW + timedelta(minutes=20), NOW + timedelta(minutes=30)]
    )
    row = run_rescore(job, writer, timeout, lambda: next(times))  # type: ignore[arg-type]
    return row, writer


def test_happy_path_loads_verifies_and_cleans_up(setup: dict) -> None:
    kaggle = Kaggle(["queued", "running", "complete"])
    bq = BigQuery()
    job = make(setup, kaggle, bq)
    row, writer = run(job)
    assert row.status.value == "succeeded"
    assert (row.reviews, row.texts, row.kind.value) == (5, 3, "rescoring")
    assert row.environment.value == "kaggle" and writer.rows == [row]
    # El EXPORT DATA usa la clave de los demás pasos y la carpeta de la corrida.
    ((export, _),) = bq.sql("EXPORT DATA")
    assert "TO_HEX(SHA256(t.texto_sanitizado))" in export
    assert f"gs://{BUCKET}/rescore/{RUN}/texts/*.parquet" in export
    assert "label_source = 'MODEL'" in export
    # A Kaggle suben ids y pesos, sin texto.
    tokens = kaggle.dataset_files["tokens.parquet"]
    assert tokens.column_names == ["text_key", "input_ids"]
    assert tokens.num_rows == 3
    assert {"config.json", "model.safetensors"} <= set(kaggle.dataset_files)
    meta = json.loads(kaggle.dataset_files["dataset-metadata.json"])
    assert meta["id"] == f"tester/voc-backfill-corpus-{RUN}"
    kernel = kaggle.pushed["meta"]
    assert kernel["is_private"] and kernel["enable_gpu"]
    assert kernel["enable_internet"] is False
    assert kernel["dataset_sources"] == [meta["id"]]
    assert f"RUN = '{RUN}'" in kaggle.pushed["script"]
    # Predicciones a GCS; MERGE con la T y el umbral de la curva.
    assert f"rescore/{RUN}/preds.parquet" in setup["storage"].objects
    ((merge, params),) = bq.sql("MERGE")
    assert params["t"] == 1.5 and params["threshold"] == 0.61
    assert params["model_version"] == CANDIDATE
    assert "risk_policy_version" in merge
    assert bq.deleted == [bq.loads[0]]
    # Limpieza: dataset de Kaggle y textos exportados; las predicciones quedan.
    assert kaggle.deleted == [meta["id"]]
    objects = setup["storage"].objects
    assert not [n for n in objects if "/texts/" in n]
    assert not job.work.exists()


@pytest.mark.parametrize(
    ("status", "timeout"), [(["running", "error"], 600), (["running"], 100)]
)
def test_failed_or_slow_kernel_loads_nothing(
    setup: dict, status: list[str], timeout: float
) -> None:
    kaggle = Kaggle(status)
    bq = BigQuery()
    row, _ = run(make(setup, kaggle, bq), timeout)
    assert row.status.value == "failed" and row.reviews == 0
    assert not bq.sql("MERGE") and not bq.loads
    assert kaggle.deleted == []


def test_output_of_another_run_is_rejected(setup: dict) -> None:
    kaggle = Kaggle(["complete"])
    kaggle.output_run = "otra"
    bq = BigQuery()
    row, _ = run(make(setup, kaggle, bq))
    assert row.status.value == "failed" and not bq.sql("MERGE")


def test_incomplete_kernel_output_fails(setup: dict) -> None:
    kaggle = Kaggle(["complete"])
    kaggle.kernel_output = lambda ref, dest: None  # type: ignore[method-assign]
    row, _ = run(make(setup, kaggle))
    assert row.status.value == "failed" and kaggle.deleted == []


def test_missing_predictions_fail_before_loading(setup: dict) -> None:
    kaggle = Kaggle(["complete"], keys=["k1", "k2"])
    bq = BigQuery()
    row, _ = run(make(setup, kaggle, bq))
    assert row.status.value == "failed" and not bq.loads
    assert kaggle.deleted == []


@pytest.mark.parametrize("gap", ["rows", "texts"])
def test_unverified_load_keeps_the_dataset(setup: dict, gap: str) -> None:
    kaggle = Kaggle(["complete"])
    bq = BigQuery(loaded_gap=1 if gap == "rows" else 0)
    if gap == "texts":
        bq.texts = 2
    row, _ = run(make(setup, kaggle, bq))
    assert row.status.value == "failed"
    assert bq.sql("MERGE") and bq.deleted == bq.loads
    assert kaggle.deleted == []
    assert [n for n in setup["storage"].objects if "/texts/" in n]


def test_without_curve_requires_hitl_stays_false(setup: dict) -> None:
    bq = BigQuery(curve=False)
    row, _ = run(make(setup, Kaggle(["complete"]), bq))
    assert row.status.value == "succeeded"
    ((_, params),) = bq.sql("MERGE")
    assert params["threshold"] is None


def test_preparation_runs_in_parallel_like_the_delta(setup: dict) -> None:
    job = make(setup, Kaggle(["complete"]), workers=2)
    texts = ["Hola @usuario 😡", "https://x.y ok", "sin cambios"]
    from voc_nlp.sentiment_model import prepare

    assert job._prepare(texts) == prepare(texts)


def test_export_without_files_fails(setup: dict) -> None:
    setup["storage"].objects = {
        k: v for k, v in setup["storage"].objects.items() if "/texts/" not in k
    }
    row, _ = run(make(setup, Kaggle(["complete"])))
    assert row.status.value == "failed" and row.texts == 0


def test_tokenizer_without_pad_and_kernel_before_tokens(setup: dict) -> None:
    job = make(setup, Kaggle(["complete"]))
    with pytest.raises(rescore.RescoreError, match="tokenize"):
        job.run_kernel()
    job.dataset_dir.mkdir(parents=True)
    Tokenizer.pad_token_id = None  # type: ignore[assignment]
    try:
        with pytest.raises(rescore.RescoreError, match="pad"):
            job.tokenize()
    finally:
        Tokenizer.pad_token_id = 1


def test_kernel_script_is_valid_python() -> None:
    script = kernel_script(RUN, pad=1, batch=8)
    ast.parse(script)
    assert script.startswith(f"RUN = '{RUN}'\nPAD = 1\nBATCH = 8\n")
    assert "local_files_only=True" in script


def test_names_and_uris_are_validated(setup: dict) -> None:
    assert check_slug("voc-backfill-corpus-1") == "voc-backfill-corpus-1"
    with pytest.raises(ValueError):
        check_slug("Bad_Slug")
    assert parse_gcs("gs://b/a/c") == ("b", "a/c/")
    with pytest.raises(ValueError):
        parse_gcs("/local/path")
    with pytest.raises(ValueError, match="slug"):
        make(setup, Kaggle(["complete"])).__class__(
            setup["settings"],
            None,
            None,
            Kaggle([]),
            model(),
            "MAL RUN",
            Path(),
        )
    bad = setup["settings"].model_copy(
        update={"gcs_raw_datalake_bucket": "Bad Bucket"}
    )
    with pytest.raises(ValueError, match="bucket"):
        Rescoring(bad, None, None, Kaggle([]), model(), RUN, Path())


def test_new_rescoring_needs_a_candidate(setup: dict) -> None:
    settings = setup["settings"]
    with pytest.raises(LookupError):
        new_rescoring(settings, None, None, Kaggle([]), CANDIDATE, RUN, {})
    with pytest.raises(ValueError, match="promoted"):
        new_rescoring(
            settings,
            None,
            None,
            Kaggle([]),
            CANDIDATE,
            RUN,
            {CANDIDATE: model("promoted")},
        )
    job = new_rescoring(
        settings, None, None, Kaggle([]), CANDIDATE, RUN, {CANDIDATE: model()}
    )
    assert job.work.exists() and job.run_id == f"rescore-{CANDIDATE}-{RUN}"
    job.work.rmdir()


def test_verified_load_writes_the_promotion_check(setup: dict) -> None:
    bq = BigQuery()
    bq.gold = {CURRENT: gold_rows(20), CANDIDATE: gold_rows(40)}
    job = make(
        setup, Kaggle(["complete"]), bq, current=model("promoted", CURRENT)
    )
    row, writer = run(job)
    assert row.status.value == "succeeded"
    (check,) = writer.checks
    assert (check.candidate_version, check.current_version) == (
        CANDIDATE,
        CURRENT,
    )
    assert check.n == 40 and check.gold_version == "gold_epic5_v1"
    assert check.verdict.value == "better"
    assert check.kappa_ci_low <= check.kappa_diff <= check.kappa_ci_high
    assert check.run_id == job.run_id
    assert check.computed_at == NOW + timedelta(minutes=20)


def test_failed_load_writes_no_promotion_check(setup: dict) -> None:
    bq = BigQuery(loaded_gap=1)
    bq.gold = {CURRENT: gold_rows(20), CANDIDATE: gold_rows(40)}
    job = make(
        setup, Kaggle(["complete"]), bq, current=model("promoted", CURRENT)
    )
    row, writer = run(job)
    assert row.status.value == "failed" and writer.checks == []


@pytest.mark.parametrize("current", [None, "promoted"])
def test_rule_that_cannot_be_computed_does_not_fail_the_run(
    setup: dict, current: str | None
) -> None:
    # Sin versión promovida, o sin oro en común: se avisa y la corrida sigue.
    promoted = model("promoted", CURRENT) if current else None
    job = make(setup, Kaggle(["complete"]), BigQuery(), current=promoted)
    row, writer = run(job)
    assert row.status.value == "succeeded" and writer.checks == []


def test_new_rescoring_measures_against_the_promoted_version(
    setup: dict,
) -> None:
    job = new_rescoring(
        setup["settings"],
        None,
        None,
        Kaggle([]),
        CANDIDATE,
        RUN,
        {CANDIDATE: model(), CURRENT: model("promoted", CURRENT)},
    )
    assert job.current is not None and job.current.model_version == CURRENT
    job.work.rmdir()
