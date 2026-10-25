"""Reentrenamiento del modelo de sentimiento en la GPU de Kaggle.

Corre en el Job ``voc-ml-training`` (comando ``train``), a mano o desde el
monitor con ``retrain_trigger = auto``. Sigue la receta de la competencia de
modelos desde el modelo base, no desde el vigente: cada versión sale solo de
la receta y de un conjunto con hash. La clave de Kaggle llega de Secret
Manager como ``KAGGLE_API_TOKEN``.

Pasos (``run_training``):

1. ``build``: el conjunto de entrenamiento, en memoria y sin salir de GCP:
   * la partición ``entrenamiento`` de la plata archivada
     (``archive/epic5/labels/silver_v0/``), un texto por clave, sin ``NA``;
   * las revisiones de sentimiento de la cola (``low_confidence`` y
     ``drift_boost``, primera ronda, sin ``no_evaluable``), que reemplazan a
     la plata del mismo texto;
   * la plata reciente: ``recent_silver_texts`` textos del modelo posteriores
     a la plata, sorteados con la corrida como semilla y etiquetados con
     Gemini y el prompt de la plata, hasta ``recent_silver_max_usd``.
   Se excluye todo texto y reseña del oro (``gold_ids.parquet``, de todas
   las colas, *dev* y *test*) y de las muestras ``monitor_sample`` y
   ``agreement_sample``, que miden el κ. El manifiesto (conteos y SHA-256 de
   las parejas texto-etiqueta) no lleva texto.
2. ``tokenize``: ``preprocess_tweet`` y el tokenizador del modelo base, como
   el *re-scoring*; la validación sale de ``val_split`` agrupada por texto.
3. ``push_dataset``: a Kaggle suben ids de tokens, etiquetas, la máscara de
   validación, los ids del oro *dev* y el modelo base de
   ``ml_artifacts/sentiment/base/``; nunca texto.
4. ``run_kernel`` y ``wait_kernel``: el kernel de ``voc_nlp.training`` con
   GPU y sin internet. Un kernel fallido o que excede el tiempo deja la
   corrida en ``failed`` sin registrar nada.
5. ``pull``: pesos fp16 con su tokenizador, el historial y las
   probabilidades del oro *dev*; comprueba que la salida es de esta corrida.
6. ``calibrate``: la temperatura ajustada en el oro *dev* (pesos 1 / π), la
   curva de cobertura y riesgo con la confianza corregida y el κ del *dev*.
7. ``publish``: pesos, ``training_vocab.txt`` y el manifiesto en
   ``ml_artifacts/sentiment/<versión>/``, verificados.
8. ``register``: candidato en el registro y en ``model_versions`` con
   ``training_data_hash``, y su curva.
9. ``cleanup``: borra el dataset de Kaggle tras la subida verificada.

En ``auto`` termina lanzando ``voc-ml-rescoring`` del candidato; nunca
promueve. Las versiones siguen el patrón vigente: ``robertuito_sentiment_v<n>``
y ``temperature_v<n>``.
"""

import hashlib
import io
import json
import logging
import os
import re
import shutil
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from voc_common.analytics_codes import (
    RetrainTrigger,
    RunEnvironment,
    RunKind,
    RunStatus,
)
from voc_common.operations_v3 import InferenceRun, ModelVersion
from voc_common.policies import HitlCoverageCurve, RiskPolicy
from voc_nlp import training as kernel
from voc_nlp.agreement import cohen_kappa
from voc_nlp.calibration import apply_temperature, fit_temperature
from voc_nlp.sentiment_model import load_tokenizer, prepare, token_ids
from voc_nlp.training import TrainParams, kernel_source, val_split

from ml_inference import artifacts, registry
from ml_inference.bq_io import StagingMergeWriter, query_rows, render
from ml_inference.config import InferenceSettings
from ml_inference.jobs import JobRunner
from ml_inference.lifecycle import (
    CLASSES,
    GoldPrediction,
    Lifecycle,
    gold_period,
)
from ml_inference.monitor.quality import GOLD_VERSION
from ml_inference.rescore import (
    DATASET_TIMEOUT_SEC,
    KaggleClient,
    RescoreError,
    check_slug,
    wait_for,
)
from ml_inference.vocab import ARCHIVE_PREFIX, VOCAB_FILE, encode

log = logging.getLogger(__name__)

KERNEL_SLUG: Final = "voc-ml-training"
DATASET_PREFIX: Final = "voc-training"
GOLD_IDS_FILE: Final = "gold_ids.parquet"
MANIFEST_FILE: Final = "training_manifest.json"
BASE_NAME: Final = "base"
TRAIN_SPLIT: Final = "entrenamiento"
LICENSE: Final = "pysentimiento: uso no comercial e investigación"
VERSION_PREFIX: Final = "robertuito_sentiment_v"
_VERSION = re.compile(rf"{VERSION_PREFIX}(\d+)")

# Reseñas y textos que miden el κ: no entrenan.
SAMPLES_SQL: Final = """
SELECT DISTINCT i.id_resena, p.text_key
FROM `${ds}.hitl_items` AS i
JOIN `${ds}.review_predictions_current` AS p USING (id_resena)
WHERE i.reason IN ('monitor_sample', 'agreement_sample')
"""

# Primera revisión de la cola por texto (la más reciente si hay varias).
REVIEWS_SQL: Final = """
SELECT r.id_resena, r.validated_label AS label,
  TO_HEX(SHA256(t.texto_sanitizado)) AS text_key, t.texto_sanitizado
FROM `${ds}.hitl_reviews` AS r
JOIN `${ds}.hitl_items` AS i USING (item_id)
JOIN `${tds}` AS t ON t.id_resena = r.id_resena
WHERE r.task = 'sentiment' AND r.review_round = 1
  AND i.reason IN ('low_confidence', 'drift_boost')
  AND r.validated_label IS NOT NULL
  AND 'no_evaluable' NOT IN UNNEST(r.flags)
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY TO_HEX(SHA256(t.texto_sanitizado))
  ORDER BY r.submitted_at DESC
) = 1
"""

# Textos del modelo posteriores a la plata, en un orden reproducible.
RECENT_SQL: Final = """
SELECT p.text_key, ANY_VALUE(t.texto_sanitizado) AS texto_sanitizado
FROM `${ds}.review_predictions_current` AS p
JOIN `${tds}` AS t
  ON t.id_resena = p.id_resena
  AND TO_HEX(SHA256(t.texto_sanitizado)) = p.text_key
WHERE p.label_source = 'MODEL' AND p.fecha >= @since
GROUP BY p.text_key
ORDER BY FARM_FINGERPRINT(CONCAT(@seed, ':', p.text_key))
LIMIT @limit
"""

# Oro *dev* evaluable con su texto actual (solo sus ids suben a Kaggle).
DEV_SQL: Final = """
SELECT g.id_resena, g.text_key, g.label, g.weight, t.bank_id, t.fecha,
  t.texto_sanitizado
FROM `${ds}.gold_labels` AS g
JOIN `${tds}` AS t
  ON t.id_resena = g.id_resena
  AND TO_HEX(SHA256(t.texto_sanitizado)) = g.text_key
WHERE g.gold_version = @gold_version AND g.split = 'dev'
  AND g.task = 'sentiment' AND g.label IN UNNEST(@classes)
"""


class TrainingError(RuntimeError):
    """Falla esperada de una corrida: queda en ``failed``."""


@dataclass(frozen=True)
class Example:
    text_key: str
    text: str
    label: str
    source: str  # silver, review o recent


@dataclass
class TrainingSet:
    examples: list[Example]
    excluded: int = 0
    replaced: int = 0
    recent_cost_usd: float = 0.0

    @property
    def sha256(self) -> str:
        """SHA-256 de las parejas ``text_key``-etiqueta, en orden."""
        lines = sorted(f"{e.text_key}\t{e.label}\n" for e in self.examples)
        return hashlib.sha256("".join(lines).encode()).hexdigest()

    def manifest(self) -> dict[str, Any]:
        """Conteos y hash, sin texto."""
        return {
            "examples": len(self.examples),
            "by_source": dict(Counter(e.source for e in self.examples)),
            "by_label": dict(Counter(e.label for e in self.examples)),
            "excluded": self.excluded,
            "replaced_by_review": self.replaced,
            "recent_silver_cost_usd": round(self.recent_cost_usd, 6),
            "sha256": self.sha256,
        }


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def next_version(names: Sequence[str]) -> int:
    """El ``n`` siguiente a los ``robertuito_sentiment_v<n>`` registrados."""
    found = [int(m[1]) for n in names if (m := _VERSION.fullmatch(n))]
    return max(found, default=0) + 1


@dataclass
class Training:
    settings: InferenceSettings
    bigquery: Any
    storage: Any
    kaggle: KaggleClient
    genai: Any
    run: str
    work: Path
    version: int
    policy: RiskPolicy | None = None
    jobs: JobRunner | None = None
    params: TrainParams = field(default_factory=TrainParams)
    workers: int = field(default_factory=lambda: os.cpu_count() or 1)
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    data: TrainingSet | None = None
    dev: list[dict[str, Any]] = field(default_factory=list)
    dev_proba: dict[str, np.ndarray] = field(default_factory=dict)
    history: dict[str, Any] = field(default_factory=dict)
    weights_uri: str | None = None

    def __post_init__(self) -> None:
        check_slug(self.dataset_slug)

    @property
    def bucket(self) -> str:
        return self.settings.gcs_raw_datalake_bucket

    @property
    def model_version(self) -> str:
        return f"{VERSION_PREFIX}{self.version}"

    @property
    def calibration_version(self) -> str:
        return f"temperature_v{self.version}"

    @property
    def run_id(self) -> str:
        return f"train-{self.model_version}-{self.run}"

    @property
    def dataset_slug(self) -> str:
        return f"{DATASET_PREFIX}-{self.run}"

    @property
    def dataset_ref(self) -> str:
        return f"{self.kaggle.user}/{self.dataset_slug}"

    @property
    def kernel_ref(self) -> str:
        return f"{self.kaggle.user}/{KERNEL_SLUG}"

    @property
    def dataset_dir(self) -> Path:
        return self.work / "dataset"

    @property
    def output_dir(self) -> Path:
        return self.work / "output"

    def _sql(self, template: str) -> str:
        return render(
            template, ds=self.settings.dataset, tds=self.settings.tds_table
        )

    def _archive(self, name: str, columns: list[str]) -> pa.Table:
        from google.api_core.exceptions import NotFound

        blob = self.storage.bucket(self.bucket).blob(f"{ARCHIVE_PREFIX}{name}")
        try:
            data = blob.download_as_bytes()
        except NotFound:
            raise TrainingError(f"{ARCHIVE_PREFIX}{name} is missing") from None
        return pq.read_table(io.BytesIO(data), columns=columns)

    # 1. Conjunto ---------------------------------------------------------

    def _excluded(self) -> tuple[set[str], set[str]]:
        """Reseñas y textos del oro y de las muestras que miden el κ."""
        gold = self._archive(GOLD_IDS_FILE, ["id_resena", "text_key"])
        ids = set(gold["id_resena"].to_pylist())
        keys = set(gold["text_key"].to_pylist())
        for r in query_rows(self.bigquery, self._sql(SAMPLES_SQL)):
            ids.add(r["id_resena"])
            keys.add(r["text_key"])
        return ids, keys

    def _silver(self, ids: set[str], keys: set[str]) -> tuple[dict, int]:
        rows = self._archive("rows.parquet", ["id_resena", "split", "text_id"])
        texts = self._archive("texts.parquet", ["text_id", "texto_sanitizado"])
        labels = self._archive(
            "labels_prompt_v3.parquet", ["text_id", "gemini_s"]
        )
        train = rows.filter(pc.equal(rows["split"], TRAIN_SPLIT))
        # Un texto con alguna reseña del oro o de las muestras queda fuera.
        dropped = {
            t
            for i, t in zip(
                train["id_resena"].to_pylist(),
                train["text_id"].to_pylist(),
                strict=True,
            )
            if i in ids
        }
        wanted = set(train["text_id"].to_pylist()) - dropped
        label_of = dict(
            zip(
                labels["text_id"].to_pylist(),
                labels["gemini_s"].to_pylist(),
                strict=True,
            )
        )
        out: dict[str, Example] = {}
        excluded = len(dropped)
        for tid, text in zip(
            texts["text_id"].to_pylist(),
            texts["texto_sanitizado"].to_pylist(),
            strict=True,
        ):
            label = label_of.get(tid)
            if tid not in wanted or text is None or label not in CLASSES:
                continue
            key = text_key(text)
            if key in keys:
                excluded += 1
                continue
            out.setdefault(key, Example(key, text, label, "silver"))
        return out, excluded

    def _recent(
        self, taken: set[str], keys: set[str]
    ) -> tuple[list[Example], float]:
        from voc_nlp import aspects, sentiment_gemini

        n = self.settings.recent_silver_texts
        cap = self.settings.recent_silver_max_usd
        if n == 0 or cap == 0 or self.genai is None:
            log.info("train: sin plata reciente")
            return [], 0.0
        rows = query_rows(
            self.bigquery,
            self._sql(RECENT_SQL),
            {
                "since": datetime.combine(
                    self.settings.recent_silver_since, datetime.min.time()
                ),
                "seed": self.run,
                # Margen para los que ya están o se excluyen.
                "limit": n + len(taken) // 10 + 1000,
            },
        )
        items = [
            (r["text_key"], r["texto_sanitizado"])
            for r in rows
            if r["text_key"] not in taken and r["text_key"] not in keys
        ][:n]
        usage = aspects.Usage()
        prompt = sentiment_gemini.load_prompt()
        size = sentiment_gemini.BATCH_SIZE
        estimate = size / 1000 * self.settings.recent_silver_usd_per_1000
        texts = dict(items)
        out: list[Example] = []
        batches = 0
        for start in range(0, len(items), size):
            per_batch = usage.cost_usd / batches if batches else estimate
            if usage.cost_usd + per_batch > cap:
                log.warning(
                    "train: plata reciente detenida en $%.4f (tope $%.2f)",
                    usage.cost_usd,
                    cap,
                )
                break
            batches += 1
            for got in sentiment_gemini.label_texts(
                self.genai,
                items[start : start + size],
                prompt,
                self.settings.gemini_model,
                usage=usage,
            ):
                if got.label in CLASSES:
                    out.append(
                        Example(got.key, texts[got.key], got.label, "recent")
                    )
        return out, usage.cost_usd

    def build(self) -> TrainingSet:
        ids, keys = self._excluded()
        examples, excluded = self._silver(ids, keys)
        replaced = 0
        for r in query_rows(self.bigquery, self._sql(REVIEWS_SQL)):
            key = r["text_key"]
            if (
                r["id_resena"] in ids
                or key in keys
                or r["label"] not in CLASSES
            ):
                continue
            replaced += key in examples
            examples[key] = Example(
                key, r["texto_sanitizado"], r["label"], "review"
            )
        recent, cost = self._recent(set(examples), keys)
        for e in recent:
            examples.setdefault(e.text_key, e)
        self.data = TrainingSet(
            sorted(examples.values(), key=lambda e: e.text_key),
            excluded=excluded,
            replaced=replaced,
            recent_cost_usd=cost,
        )
        log.info("train: conjunto %s", self.data.manifest())
        if not self.data.examples:
            raise TrainingError("the training set is empty")
        return self.data

    # 2 y 3. Tokens y dataset ------------------------------------------------

    def _prepare(self, texts: list[str]) -> list[str]:
        if self.workers <= 1:
            return prepare(texts)
        size = -(-len(texts) // self.workers)
        parts = [texts[i : i + size] for i in range(0, len(texts), size)]
        with ProcessPoolExecutor(self.workers) as pool:
            return [t for part in pool.map(prepare, parts) for t in part]

    def push_dataset(self) -> None:
        """Ids, etiquetas y el modelo base; sin texto."""
        if self.data is None:
            raise TrainingError("build the training set first")
        base = self.dataset_dir / kernel.BASE_DIR
        artifacts.download_prefix(
            self.storage,
            self.bucket,
            artifacts.artifact_prefix(
                self.settings.ml_artifacts_prefix,
                artifacts.SENTIMENT,
                BASE_NAME,
            ),
            base,
        )
        tokenizer = load_tokenizer(base)
        examples = self.data.examples
        ids = token_ids(tokenizer, self._prepare([e.text for e in examples]))
        is_val = val_split(
            [e.text_key for e in examples],
            self.params.val_share,
            self.params.split_seed,
        )
        pq.write_table(
            pa.table(
                {
                    "input_ids": pa.array(ids, pa.list_(pa.int32())),
                    "label": pa.array(
                        [CLASSES.index(e.label) for e in examples], pa.int8()
                    ),
                    "is_val": pa.array(is_val.tolist(), pa.bool_()),
                }
            ),
            self.dataset_dir / kernel.TRAIN_FILE,
            compression="zstd",
        )
        self.dev = query_rows(
            self.bigquery,
            self._sql(DEV_SQL),
            {
                "gold_version": GOLD_VERSION,
                "classes": list(CLASSES),
            },
        )
        if not self.dev:
            raise TrainingError("the dev gold has no evaluable reviews")
        dev_texts = {r["text_key"]: r["texto_sanitizado"] for r in self.dev}
        dev_keys = sorted(dev_texts)
        pq.write_table(
            pa.table(
                {
                    "key": dev_keys,
                    "input_ids": pa.array(
                        token_ids(
                            tokenizer,
                            self._prepare([dev_texts[k] for k in dev_keys]),
                        ),
                        pa.list_(pa.int32()),
                    ),
                }
            ),
            self.dataset_dir / kernel.DEV_FILE,
            compression="zstd",
        )
        meta = {
            "title": self.dataset_slug,
            "id": self.dataset_ref,
            "licenses": [{"name": "other"}],
        }
        (self.dataset_dir / "dataset-metadata.json").write_text(
            json.dumps(meta, indent=2)
        )
        self.kaggle.create_dataset(self.dataset_dir)
        wait_for(
            lambda: self.kaggle.dataset_status(self.dataset_ref),
            DATASET_TIMEOUT_SEC,
            "dataset",
            self.sleep,
            self.clock,
            first_delay=False,
        )
        log.info(
            "train: dataset con %d textos (%d de validación) y %d del dev",
            len(examples),
            int(is_val.sum()),
            len(dev_keys),
        )
        shutil.rmtree(self.dataset_dir)

    # 4 y 5. Kernel y salida ------------------------------------------------

    def run_kernel(self) -> None:
        folder = self.work / "kernel"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "run.py").write_text(kernel_source(self.run, self.params))
        meta = {
            "id": self.kernel_ref,
            "title": KERNEL_SLUG,
            "code_file": "run.py",
            "language": "python",
            "kernel_type": "script",
            "is_private": True,
            "enable_gpu": True,
            "enable_internet": False,
            "dataset_sources": [self.dataset_ref],
        }
        (folder / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
        self.kaggle.push_kernel(folder)

    def wait_kernel(self, timeout_sec: float) -> None:
        wait_for(
            lambda: self.kaggle.kernel_status(self.kernel_ref),
            timeout_sec,
            "kernel",
            self.sleep,
            self.clock,
        )

    def pull(self) -> None:
        out = self.output_dir
        out.mkdir(parents=True, exist_ok=True)
        self.kaggle.kernel_output(self.kernel_ref, out)
        log_file = out / kernel.LOG_FILE
        preds = out / kernel.DEV_PREDS_FILE
        weights = out / kernel.MODEL_DIR
        if not (log_file.exists() and preds.exists() and weights.is_dir()):
            raise TrainingError("the kernel output is incomplete")
        self.history = json.loads(log_file.read_text())
        if self.history.get("run") != self.run:
            raise TrainingError("the kernel output belongs to another run")
        table = pq.read_table(preds).to_pydict()
        self.dev_proba = {
            key: np.array([table[f"p_{c}"][i] for c in CLASSES])
            for i, key in enumerate(table["key"])
        }

    # 6. Calibración --------------------------------------------------------

    def calibrate(
        self, lifecycle: Lifecycle, now: datetime
    ) -> tuple[float, HitlCoverageCurve, float]:
        """Temperatura, curva y κ del oro *dev* con la confianza corregida."""
        rows = [r for r in self.dev if r["text_key"] in self.dev_proba]
        if len(rows) < len(self.dev):
            raise TrainingError("the kernel missed dev gold predictions")
        raw = np.array([self.dev_proba[r["text_key"]] for r in rows])
        y = np.array([CLASSES.index(r["label"]) for r in rows])
        w = np.array([float(r["weight"]) for r in rows])
        t = fit_temperature(raw, y, w)
        proba = apply_temperature(raw, t)
        predicted = [CLASSES[i] for i in proba.argmax(axis=1)]
        gold = [
            GoldPrediction(
                id_resena=r["id_resena"],
                label=r["label"],
                weight=float(r["weight"]),
                stratum=f"{r['bank_id']}|{gold_period(r['fecha'].year)}",
                predicted=p,
                confidence=float(c),
            )
            for r, p, c in zip(rows, predicted, proba.max(axis=1), strict=True)
        ]
        kappa = cohen_kappa([r["label"] for r in rows], predicted, w)
        curve = lifecycle.curve_for(self._candidate(t, kappa, now), gold, now)
        log.info("train: T = %.4f, κ del dev = %.4f", t, kappa)
        return t, curve, kappa

    def _candidate(self, t: float, kappa: float, now: datetime) -> ModelVersion:
        return ModelVersion(
            model_version=self.model_version,
            registry_uri=self.weights_uri or "pending",
            base_checkpoint=self.params.base,
            training_data=self.training_data,
            calibration_version=self.calibration_version,
            calibration_t=t,
            kappa_dev=kappa,
            license=LICENSE,
            status="candidate",
            recorded_at=now,
        )

    @property
    def training_data(self) -> str:
        return f"silver_v0+hitl+recent_silver ({self.run})"

    # 7 a 9. Publicación, registro y limpieza -------------------------------

    @property
    def prefix(self) -> str:
        return artifacts.artifact_prefix(
            self.settings.ml_artifacts_prefix,
            artifacts.SENTIMENT,
            self.model_version,
        )

    def publish(self) -> str:
        if self.data is None:
            raise TrainingError("build the training set first")
        weights = self.output_dir / kernel.MODEL_DIR
        words: set[str] = set()
        for e in self.data.examples:
            words.update(e.text.lower().split(" "))
        (weights / VOCAB_FILE).write_bytes(encode(words))
        manifest = {
            "model_version": self.model_version,
            "run": self.run,
            "base": self.params.base,
            "params": asdict(self.params),
            "best_epoch": self.history.get("best_epoch"),
            **self.data.manifest(),
        }
        (weights / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2))
        artifacts.upload_dir(self.storage, self.bucket, weights, self.prefix)
        names = {
            b.name.removeprefix(self.prefix)
            for b in self.storage.list_blobs(self.bucket, prefix=self.prefix)
        }
        needed = {"config.json", "model.safetensors", VOCAB_FILE, MANIFEST_FILE}
        if not needed <= names:
            raise TrainingError(f"upload incomplete: {sorted(needed - names)}")
        self.weights_uri = artifacts.gcs_uri(self.bucket, self.prefix)
        return self.weights_uri

    def register(
        self,
        writer: StagingMergeWriter,
        t: float,
        curve: HitlCoverageCurve,
        kappa: float,
        now: datetime,
    ) -> ModelVersion:
        if self.data is None or self.weights_uri is None:
            raise TrainingError("publish before registering")
        if self.settings.serving_image is None:
            raise TrainingError("SERVING_IMAGE is not set")
        return registry.register(
            self.settings,
            writer,
            weights_uri=self.weights_uri,
            model_version=self.model_version,
            calibration_version=self.calibration_version,
            calibration_t=t,
            curve=curve,
            metrics={"kappa_dev": kappa},
            serving_image=self.settings.serving_image,
            base_checkpoint=self.params.base,
            training_data=self.training_data,
            license_name=LICENSE,
            now=now,
            training_data_hash=self.data.sha256,
        )

    def cleanup(self) -> None:
        self.kaggle.delete_dataset(self.dataset_ref)

    def launch_rescoring(self) -> str | None:
        """En ``auto``, el *re-scoring* del candidato; nunca la promoción."""
        if (
            self.policy is None
            or self.policy.retrain_mode != RetrainTrigger.AUTO
        ):
            return None
        if self.jobs is None:
            log.warning("train: modo auto sin lanzador de Jobs")
            return None
        return self.jobs.execute(
            self.settings.rescoring_job,
            ["rescore", f"--model-version={self.model_version}"],
        )


def run_training(
    job: Training,
    writer: StagingMergeWriter,
    timeout_sec: float,
    now: Callable[[], datetime],
) -> InferenceRun:
    """Corre los pasos y registra la corrida, con éxito o fallida."""
    started = now()
    status = RunStatus.FAILED
    try:
        if job.settings.serving_image is None:
            raise TrainingError("SERVING_IMAGE is not set")
        job.build()
        job.push_dataset()
        job.run_kernel()
        job.wait_kernel(timeout_sec)
        job.pull()
        lifecycle = Lifecycle(job.bigquery, writer, job.settings.dataset)
        t, curve, kappa = job.calibrate(lifecycle, started)
        job.publish()
        job.register(writer, t, curve, kappa, now())
        job.cleanup()
        status = RunStatus.SUCCEEDED
        job.launch_rescoring()
    except (TrainingError, RescoreError) as exc:
        log.error("train %s: %s (dataset %s)", job.run, exc, job.dataset_ref)
    finally:
        row = InferenceRun(
            run_id=job.run_id,
            kind=RunKind.TRAINING,
            environment=RunEnvironment.KAGGLE,
            model_version=job.model_version,
            started_at=started,
            ended_at=now(),
            reviews=0,
            texts=len(job.data.examples) if job.data else 0,
            status=status,
            cost_usd=round(job.data.recent_cost_usd, 6) if job.data else 0.0,
        )
        writer.write("inference_runs", [row], ["run_id"], job.run_id)
        shutil.rmtree(job.work, ignore_errors=True)
    return row


def new_training(
    settings: InferenceSettings,
    bigquery: Any,
    storage: Any,
    kaggle: KaggleClient,
    genai: Any,
    run: str,
    versions: dict[str, ModelVersion],
    policy: RiskPolicy | None,
    jobs: JobRunner | None,
) -> Training:
    work = Path(tempfile.mkdtemp(prefix="train-"))
    return Training(
        settings,
        bigquery,
        storage,
        kaggle,
        genai,
        run,
        work,
        next_version(list(versions)),
        policy=policy,
        jobs=jobs,
    )
