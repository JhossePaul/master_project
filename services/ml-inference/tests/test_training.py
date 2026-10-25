"""Reentrenamiento: conjunto, Kaggle sin texto, registro y modo auto."""

import hashlib
import io
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from ml_inference import registry, training
from ml_inference.config import InferenceSettings
from ml_inference.training import (
    Training,
    TrainingError,
    next_version,
    run_training,
)
from voc_common.analytics_codes import RetrainTrigger

NOW = datetime(2026, 11, 4, 9, 30, tzinfo=UTC)
RUN = "202611040930"
BUCKET = "bucket"
ARCHIVE = "archive/epic5/labels/silver_v0/"


def key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def parquet(table: dict[str, list]) -> bytes:
    out = io.BytesIO()
    pq.write_table(pa.table(table), out)
    return out.getvalue()


# -- GCS ---------------------------------------------------------------------


class Blob:
    def __init__(self, store: "Storage", name: str) -> None:
        self.store, self.name = store, name

    def download_as_bytes(self) -> bytes:
        from google.api_core.exceptions import NotFound

        if self.name not in self.store.objects:
            raise NotFound(self.name)
        return self.store.objects[self.name]

    def download_to_filename(self, path: str) -> None:
        Path(path).write_bytes(self.store.objects[self.name])

    def upload_from_filename(self, path: str) -> None:
        self.store.objects[self.name] = Path(path).read_bytes()

    def upload_from_string(self, data: bytes, **_: Any) -> None:
        self.store.objects[self.name] = data


class Storage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def bucket(self, name: str) -> Any:
        store = self

        class _Bucket:
            def blob(self, path: str) -> Blob:
                return Blob(store, path)

        return _Bucket()

    def list_blobs(self, bucket: str, prefix: str) -> list[Blob]:
        return [
            Blob(self, n) for n in sorted(self.objects) if n.startswith(prefix)
        ]


def archive(storage: Storage, gold_ids: bool = True) -> None:
    texts = {
        1: "la app no abre",
        2: "excelente servicio",
        3: "texto del oro",
        4: "texto con clave del oro",
        5: "no evaluable",
        6: "me cobraron doble",
        7: "muestra de concepto",
        8: "texto del holdout",
    }
    storage.objects[f"{ARCHIVE}texts.parquet"] = parquet(
        {"text_id": list(texts), "texto_sanitizado": list(texts.values())}
    )
    storage.objects[f"{ARCHIVE}rows.parquet"] = parquet(
        {
            "id_resena": [f"r{i}" for i in texts],
            "split": ["entrenamiento"] * 7 + ["holdout_nuevo"],
            "text_id": list(texts),
        }
    )
    storage.objects[f"{ARCHIVE}labels_prompt_v3.parquet"] = parquet(
        {
            "text_id": list(texts),
            "gemini_s": ["NEG", "POS", "NEG", "NEG", "NA", "NEG", "NEG", "POS"],
        }
    )
    if gold_ids:
        storage.objects[f"{ARCHIVE}gold_ids.parquet"] = parquet(
            {
                "id_resena": ["r3", "g9"],
                "text_key": [key("otro"), key("texto con clave del oro")],
            }
        )
    for name in ("config.json", "model.safetensors", "tokenizer.json"):
        storage.objects[f"ml_artifacts/sentiment/base/{name}"] = b"{}"


# -- BigQuery ----------------------------------------------------------------


class Job:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []

    def result(self, timeout: float | None = None, **_: Any) -> list[dict]:
        return self.rows


DEV = [
    {
        "id_resena": f"d{i}",
        "text_key": key(f"dev {i}"),
        "label": ["NEG", "NEU", "POS"][i % 3],
        "weight": 1.0 + i % 2,
        "bank_id": "BBVA",
        "fecha": NOW - timedelta(days=30 * i),
        "texto_sanitizado": f"dev {i}",
    }
    for i in range(12)
]


class BigQuery:
    def __init__(self) -> None:
        self.params: dict[str, dict[str, Any]] = {}

    def query(self, sql: str, job_config: Any = None, **_: Any) -> Job:
        params = {
            p.name: getattr(p, "value", getattr(p, "values", None))
            for p in getattr(job_config, "query_parameters", []) or []
        }
        if "seconds_spent" in sql:
            return Job([{"median": None, "n": 0}])
        if "monitor_sample" in sql:
            return Job(
                [{"id_resena": "m1", "text_key": key("muestra de concepto")}]
            )
        if "hitl_reviews" in sql:
            return Job(
                [
                    {
                        "id_resena": "x6",
                        "label": "NEU",
                        "text_key": key("me cobraron doble"),
                        "texto_sanitizado": "me cobraron doble",
                    },
                    {
                        "id_resena": "x9",
                        "label": "POS",
                        "text_key": key("revisión nueva"),
                        "texto_sanitizado": "revisión nueva",
                    },
                ]
            )
        if "FARM_FINGERPRINT" in sql:
            self.params["recent"] = params
            texts = ["app lenta hoy", "todo bueno", "na raro", "la app no abre"]
            return Job(
                [{"text_key": key(t), "texto_sanitizado": t} for t in texts]
            )
        if "gold_labels" in sql:
            self.params["dev"] = params
            return Job(DEV)
        if "ISOWEEK" in sql:
            return Job(
                [
                    {"bank_id": None, "week": NOW, "texts": 8000},
                    {"bank_id": "BBVA", "week": NOW, "texts": 2000},
                ]
            )
        raise AssertionError(f"unexpected query: {sql[:80]}")


# -- Kaggle, Gemini, registro y escritura -------------------------------------


class Kaggle:
    user = "tester"

    def __init__(self, statuses: list[str], run: str = RUN) -> None:
        self.statuses = list(statuses)
        self.run = run
        self.files: dict[str, Any] = {}
        self.pushed: dict[str, Any] = {}
        self.deleted: list[str] = []
        self.complete_output = True

    def create_dataset(self, folder: Path) -> None:
        for path in folder.rglob("*"):
            if path.is_file():
                name = path.relative_to(folder).as_posix()
                self.files[name] = (
                    pq.read_table(path)
                    if name.endswith(".parquet")
                    else path.read_bytes()
                )

    def dataset_status(self, ref: str) -> str:
        return "ready"

    def push_kernel(self, folder: Path) -> None:
        self.pushed = {
            "script": (folder / "run.py").read_text(),
            "meta": json.loads((folder / "kernel-metadata.json").read_text()),
        }

    def kernel_status(self, ref: str) -> str:
        return (
            self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        )

    def kernel_output(self, ref: str, dest: Path) -> None:
        (dest / "train_log.json").write_text(
            json.dumps({"run": self.run, "best_epoch": 2})
        )
        if not self.complete_output:
            return
        keys = self.files["dev.parquet"]["key"].to_pylist()
        pq.write_table(
            pa.table(
                {
                    "key": keys,
                    "p_NEG": [0.7] * len(keys),
                    "p_NEU": [0.2] * len(keys),
                    "p_POS": [0.1] * len(keys),
                }
            ),
            dest / "dev_preds.parquet",
        )
        model = dest / "model"
        model.mkdir()
        for name in ("config.json", "model.safetensors", "tokenizer.json"):
            (model / name).write_text("{}")

    def delete_dataset(self, ref: str) -> None:
        self.deleted.append(ref)


class Gemini:
    """Sentimiento con el prompt de la plata: ``bueno`` → POS, ``na`` → NA."""

    def __init__(self) -> None:
        self.models = self
        self.sent: list[str] = []
        self.prompt_tokens: int | None = None

    def generate_content(self, *, model: str, contents: str, config: Any):
        lines = []
        for line in contents.splitlines():
            i, text = line.split("\t", 1)
            self.sent.append(text)
            label = (
                "POS" if "bueno" in text else "NA" if "na " in text else "NEG"
            )
            lines.append(f"{i} {label} 0")
        meta = (
            None
            if self.prompt_tokens is None
            else type(
                "U",
                (),
                {
                    "prompt_token_count": self.prompt_tokens,
                    "candidates_token_count": 0,
                    "thoughts_token_count": 0,
                },
            )()
        )
        return type("R", (), {"text": "\n".join(lines), "usage_metadata": meta})


class Tokenizer:
    pad_token_id = 1

    def __call__(self, texts: list[str], **_: Any) -> dict[str, list]:
        return {"input_ids": [[0, len(t), 2] for t in texts]}


class Writer:
    def __init__(self) -> None:
        self.tables: dict[str, list[Any]] = {}

    def write(self, table: str, rows: list, key: list, run_id: str) -> int:
        self.tables.setdefault(table, []).extend(rows)
        return len(rows)


class AiPlatform:
    def __init__(self) -> None:
        self.uploads: list[dict[str, Any]] = []
        outer = self

        class Model:
            @staticmethod
            def list(filter: str) -> list[Any]:
                return []

            @staticmethod
            def upload(**kwargs: Any) -> None:
                outer.uploads.append(kwargs)

        self.Model = Model

    def init(self, **_: Any) -> None:
        pass


class Jobs:
    def __init__(self) -> None:
        self.executed: list[tuple[str, list[str]]] = []

    def execute(self, job: str, args: Any) -> str:
        self.executed.append((job, list(args)))
        return "operations/1"


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(training, "load_tokenizer", lambda path: Tokenizer())
    platform = AiPlatform()
    monkeypatch.setattr(registry, "_aiplatform", lambda: platform)
    storage = Storage()
    archive(storage)
    settings = InferenceSettings(
        gcp_project_id="test-project",
        gcs_raw_datalake_bucket=BUCKET,
        artifacts_dir=tmp_path / "artifacts",
        serving_image="us-docker.pkg.dev/p/r/ml@sha256:" + "a" * 64,
    )
    return {
        "storage": storage,
        "settings": settings,
        "tmp": tmp_path,
        "platform": platform,
    }


def make(
    setup: dict[str, Any],
    kaggle: Kaggle,
    *,
    policy: Any = None,
    jobs: Any = None,
    gemini: Any = None,
    settings: InferenceSettings | None = None,
) -> Training:
    clock = iter(range(0, 10**6, 60))
    return Training(
        settings or setup["settings"],
        BigQuery(),
        setup["storage"],
        kaggle,
        gemini or Gemini(),
        RUN,
        setup["tmp"] / "work",
        3,
        policy=policy,
        jobs=jobs,
        workers=1,
        sleep=lambda s: None,
        clock=lambda: next(clock),
    )


def run(job: Training, timeout: float = 600) -> tuple[Any, Writer]:
    writer = Writer()
    times = iter([NOW + timedelta(minutes=m) for m in range(0, 300, 10)])
    row = run_training(job, writer, timeout, lambda: next(times))  # type: ignore[arg-type]
    return row, writer


def test_next_version() -> None:
    assert next_version([]) == 1
    names = ["robertuito_sentiment_v1", "robertuito_sentiment_v2", "otro_v9"]
    assert next_version(names) == 3


def test_training_set_rules(setup: dict) -> None:
    job = make(setup, Kaggle(["complete"]))
    data = job.build(NOW)
    labels = {e.text: (e.label, e.source) for e in data.examples}
    assert labels == {
        "la app no abre": ("NEG", "silver"),
        "excelente servicio": ("POS", "silver"),
        # La revisión reemplaza a la plata del mismo texto.
        "me cobraron doble": ("NEU", "review"),
        "revisión nueva": ("POS", "review"),
        "app lenta hoy": ("NEG", "recent"),
        "todo bueno": ("POS", "recent"),
    }
    # Fuera: el oro (por reseña y por texto), la muestra de concepto, el
    # NA, el holdout y lo que Gemini marca NA.
    assert data.replaced == 1 and data.excluded == 3
    # El texto que ya estaba no vuelve a Gemini.
    assert "la app no abre" not in job.genai.sent
    manifest = data.manifest()
    assert manifest["by_source"] == {"silver": 2, "review": 2, "recent": 2}
    assert manifest["sha256"] == data.sha256
    assert job.bigquery.params["recent"]["seed"] == RUN
    # Ventana de 12 meses, nunca antes del corte de la plata.
    assert job.bigquery.params["recent"]["since"] == datetime(
        2026, 4, 1, tzinfo=UTC
    )
    later = make(setup, Kaggle(["complete"]))
    later.build(datetime(2028, 1, 15, tzinfo=UTC))
    assert later.bigquery.params["recent"]["since"] > datetime(
        2026, 12, 1, tzinfo=UTC
    )


def test_happy_path_trains_registers_and_cleans_up(setup: dict) -> None:
    kaggle = Kaggle(["queued", "running", "complete"])
    job = make(setup, kaggle)
    row, writer = run(job)
    assert row.status.value == "succeeded"
    assert (row.kind.value, row.environment.value) == ("training", "kaggle")
    assert row.model_version == "robertuito_sentiment_v3" and row.texts == 6
    # A Kaggle suben ids, etiquetas y el modelo base; ningún texto.
    train = kaggle.files["train.parquet"]
    assert train.column_names == ["input_ids", "label", "is_val"]
    assert train.num_rows == 6
    dev = kaggle.files["dev.parquet"]
    assert dev.column_names == ["key", "input_ids"]
    assert all(re.fullmatch(r"[0-9a-f]{64}", k) for k in dev["key"].to_pylist())
    assert {"base/config.json", "base/model.safetensors"} <= set(kaggle.files)
    meta = kaggle.pushed["meta"]
    assert meta["enable_gpu"] and meta["enable_internet"] is False
    assert meta["dataset_sources"] == ["tester/voc-training-" + RUN]
    assert f"RUN = '{RUN}'" in kaggle.pushed["script"]
    assert not re.search(
        r"^\s*(from|import) voc_nlp", kaggle.pushed["script"], re.M
    )
    # Publicación verificada con vocabulario y manifiesto sin texto.
    prefix = "ml_artifacts/sentiment/robertuito_sentiment_v3/"
    objects = setup["storage"].objects
    assert {f"{prefix}model.safetensors", f"{prefix}training_vocab.txt"} <= set(
        objects
    )
    manifest = objects[f"{prefix}training_manifest.json"].decode()
    assert "cobraron" not in manifest and json.loads(manifest)["examples"] == 6
    # Registro con el hash del conjunto, T y curva.
    (model,) = writer.tables["model_versions"]
    assert model.status.value == "candidate"
    assert model.training_data_hash == json.loads(manifest)["sha256"]
    assert model.calibration_version == "temperature_v3"
    assert model.registry_uri == f"gs://{BUCKET}/{prefix}"
    assert model.calibration_t > 0 and model.kappa_dev is not None
    assert model.ece_dev is not None and model.aurc_dev is not None
    assert json.loads(manifest)["calibration"]["calibrated"]
    (curve,) = writer.tables["hitl_coverage_curves"]
    assert curve.model_version == "robertuito_sentiment_v3"
    assert curve.weekly_volume_total == 1000
    (upload,) = setup["platform"].uploads
    assert upload["artifact_uri"] == f"gs://{BUCKET}/{prefix}"
    assert kaggle.deleted == ["tester/voc-training-" + RUN]
    assert not job.work.exists()


@pytest.mark.parametrize(
    ("statuses", "timeout"), [(["running", "error"], 600), (["running"], 100)]
)
def test_failed_or_slow_kernel_registers_nothing(
    setup: dict, statuses: list[str], timeout: float
) -> None:
    kaggle = Kaggle(statuses)
    row, writer = run(make(setup, kaggle), timeout)
    assert row.status.value == "failed"
    assert "model_versions" not in writer.tables
    assert not [n for n in setup["storage"].objects if "_v3/" in n]
    assert kaggle.deleted == []


@pytest.mark.parametrize("problem", ["other_run", "incomplete"])
def test_bad_kernel_output_fails(setup: dict, problem: str) -> None:
    kaggle = Kaggle(["complete"], run="otra" if problem == "other_run" else RUN)
    kaggle.complete_output = problem != "incomplete"
    row, writer = run(make(setup, kaggle))
    assert (
        row.status.value == "failed" and "model_versions" not in writer.tables
    )


def test_recent_silver_stops_at_its_cap(setup: dict) -> None:
    gemini = Gemini()
    gemini.prompt_tokens = 2_000_000  # $1.50 por llamada
    job = make(setup, Kaggle(["complete"]), gemini=gemini)
    data = job.build(NOW)
    # Una llamada de $1.50; la segunda pasaría el tope de $2.
    assert data.recent_cost_usd == pytest.approx(1.5)
    assert data.recent_cost_usd <= 2.0
    settings = setup["settings"].model_copy(update={"recent_silver_texts": 0})
    off = make(setup, Kaggle(["complete"]), settings=settings).build(NOW)
    assert off.recent_cost_usd == 0.0
    assert {e.source for e in off.examples} == {"silver", "review"}


@pytest.mark.parametrize(
    ("trigger", "launched"),
    [
        (RetrainTrigger.AUTO, True),
        (RetrainTrigger.MANUAL, False),
        (None, False),
    ],
)
def test_auto_launches_the_rescoring_and_never_promotes(
    setup: dict, trigger: Any, launched: bool
) -> None:
    jobs = Jobs()
    policy = type("P", (), {"retrain_mode": trigger or RetrainTrigger.MANUAL})()
    row, writer = run(
        make(setup, Kaggle(["complete"]), policy=policy, jobs=jobs)
    )
    assert row.status.value == "succeeded"
    expected = [
        (
            "voc-ml-rescoring",
            [
                "rescore",
                "--model-version=robertuito_sentiment_v3",
                f"--reason=re-scoring automático del entrenamiento {RUN}",
            ],
        )
    ]
    assert jobs.executed == (expected if launched else [])
    assert all(
        m.status.value == "candidate" for m in writer.tables["model_versions"]
    )


def test_missing_gold_ids_fail_before_kaggle(setup: dict) -> None:
    storage = Storage()
    archive(storage, gold_ids=False)
    setup["storage"] = storage
    kaggle = Kaggle(["complete"])
    row, _ = run(make(setup, kaggle))
    assert row.status.value == "failed" and kaggle.files == {}


def test_missing_serving_image_fails_before_anything(setup: dict) -> None:
    settings = setup["settings"].model_copy(update={"serving_image": None})
    kaggle = Kaggle(["complete"])
    row, _ = run(make(setup, kaggle, settings=settings))
    assert row.status.value == "failed" and row.texts == 0
    assert kaggle.files == {}


def test_candidate_curve_uses_the_calibrated_confidence(setup: dict) -> None:
    job = make(setup, Kaggle(["complete"]))
    job.dev = DEV
    job.dev_proba = {r["text_key"]: np.array([0.7, 0.2, 0.1]) for r in DEV}
    from ml_inference.lifecycle import Lifecycle

    cal = job.calibrate(Lifecycle(BigQuery(), Writer(), "p.ds"), NOW)
    assert cal.t > 0 and cal.metrics["kappa_dev"] == pytest.approx(0.0)
    assert set(cal.metrics) == {"kappa_dev", "ece_dev", "aurc_dev"}
    assert cal.curve.calibration_version == "temperature_v3"
    assert cal.reliability["calibrated"] and cal.reliability["raw"]
    job.dev_proba.pop(DEV[0]["text_key"])
    with pytest.raises(TrainingError, match="missed"):
        job.calibrate(Lifecycle(BigQuery(), Writer(), "p.ds"), NOW)
