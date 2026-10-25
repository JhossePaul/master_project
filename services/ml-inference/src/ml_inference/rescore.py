"""*Re-scoring* del modelo de sentimiento en la GPU de Kaggle.

Predice todo el corpus con una versión candidata antes de promoverla
(``lifecycle``): sus filas entran a ``review_predictions`` sin verse, porque
la vista solo muestra la versión promovida. Corre en el Job
``voc-ml-rescoring`` (comando ``rescore``) y no pasa por la máquina de nadie;
la clave de Kaggle llega de Secret Manager como ``KAGGLE_API_TOKEN``. Solo
cambia el sentimiento: las familias de Gemini y los tópicos no dependen del
modelo y no se recalculan.

Pasos (``run_rescore``):

1. ``export``: ``EXPORT DATA`` de los textos únicos que predice el modelo
   (``label_source = 'MODEL'`` en la versión promovida) a
   ``gs://<bucket>/rescore/<corrida>/texts/``, con ``text_key`` =
   ``TO_HEX(SHA256(texto_sanitizado))``. Los textos de una palabra y los no
   elegibles no salen de GCP.
2. ``push_dataset``: el Job prepara los textos con el mismo código que el
   delta (``preprocess_tweet`` en paralelo y el tokenizador de la versión),
   así que a Kaggle suben ids de tokens, no texto, y los pesos del registro.
   La preparación tomó 27 min en la CPU de Kaggle con el corpus de los
   experimentos (``docs/analytics/scale/scale_report.md``). Cada corrida sube
   su propio dataset privado (``voc-backfill-corpus-<corrida>``).
3. ``run_kernel`` y ``wait_kernel``: el kernel privado con GPU y sin
   internet predice en fp16 y escribe probabilidades sin calibrar por
   ``text_key``. Un kernel fallido o que excede el tiempo deja la corrida en
   ``failed`` sin cargar nada.
4. ``pull``: trae la salida, comprueba que es de esta corrida y la guarda en
   ``gs://<bucket>/rescore/<corrida>/preds.parquet``.
5. ``load``: aplica la T de la versión en BigQuery y crea las filas de la
   candidata a partir de las de la versión promovida (misma elegibilidad;
   las filas del léxico y las no predichas se copian). ``requires_hitl`` usa
   el umbral de la curva registrada de la candidata a la cobertura vigente;
   ``risk_policy_version`` queda nulo hasta que ``promote`` inserte su
   política. Verifica que cada texto exportado tiene predicción y que cada
   fila esperada quedó en la tabla.
6. ``promotion_checks``: con la carga verificada, la regla de promoción
   (diferencias de κ y macro-F1 con su IC contra la versión promovida, en
   el oro *dev*) queda guardada para la pantalla de promoción; ``promote``
   la vuelve a calcular. Si no se puede calcular (sin versión promovida o
   sin oro en común), se avisa en el log y la corrida sigue.
7. ``cleanup``: solo después de una carga verificada, borra el dataset de
   Kaggle y los textos exportados a GCS. Si la verificación falla, el
   dataset se queda y la corrida no termina (se borra a mano).
"""

import json
import logging
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Any, Final, Protocol

import pyarrow as pa
import pyarrow.parquet as pq
from voc_common.analytics_codes import (
    PromotionVerdict,
    RunEnvironment,
    RunKind,
    RunStatus,
)
from voc_common.operations_v3 import (
    InferenceRun,
    ModelVersion,
    PromotionCheckResult,
)
from voc_common.policies import HitlCoverageCurve, RiskPolicy
from voc_nlp.eligibility import RULES_VERSION
from voc_nlp.sentiment_model import load_tokenizer, prepare, token_ids

from ml_inference import artifacts
from ml_inference.bq_io import (
    StagingMergeWriter,
    load_parquet,
    query_rows,
    render,
    run_dml,
)
from ml_inference.config import InferenceSettings
from ml_inference.runs import write_run

log = logging.getLogger(__name__)

DATASET_PREFIX: Final = "voc-backfill-corpus"
KERNEL_SLUG: Final = "voc-ml-rescoring"
GCS_PREFIX: Final = "rescore"
CHUNK: Final = 50_000
BATCH: Final = 256
POLL_SECONDS: Final = 60
DATASET_TIMEOUT_SEC: Final = 1800
DONE: Final = "complete"
FAILED: Final = ("error", "cancel")
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{4,48}[a-z0-9]")
_BUCKET = re.compile(r"[a-z0-9][a-z0-9._-]{1,220}")


class RescoreError(RuntimeError):
    """Falla esperada de una corrida: queda en ``failed``."""


class KernelFailed(RescoreError):
    pass


class VerificationFailed(RescoreError):
    pass


class KaggleClient(Protocol):
    """Lo que el Job usa de la API de Kaggle."""

    user: str

    def create_dataset(self, folder: Path) -> None: ...
    def dataset_status(self, ref: str) -> str: ...
    def push_kernel(self, folder: Path) -> None: ...
    def kernel_status(self, ref: str) -> str: ...
    def kernel_output(self, ref: str, dest: Path) -> None: ...
    def delete_dataset(self, ref: str) -> None: ...


class KaggleApiClient:  # pragma: no cover - red real
    """Adaptador de ``kaggle`` (``KAGGLE_API_TOKEN`` del entorno)."""

    def __init__(self) -> None:
        from kaggle.api.kaggle_api_extended import KaggleApi

        self.api = KaggleApi()
        try:
            self.api.authenticate()
        except SystemExit:
            raise RescoreError("Kaggle authentication failed") from None
        self.user = self.api.get_config_value(self.api.CONFIG_NAME_USER)

    def create_dataset(self, folder: Path) -> None:
        self.api.dataset_create_new(
            str(folder), public=False, quiet=True, dir_mode="skip"
        )

    def dataset_status(self, ref: str) -> str:
        return str(self.api.dataset_status(ref)).lower()

    def push_kernel(self, folder: Path) -> None:
        self.api.kernels_push(str(folder))

    def kernel_status(self, ref: str) -> str:
        status = self.api.kernels_status(ref)
        return str(getattr(status, "status", status)).lower()

    def kernel_output(self, ref: str, dest: Path) -> None:
        self.api.kernels_output(ref, str(dest), force=True, quiet=True)

    def delete_dataset(self, ref: str) -> None:
        owner, slug = ref.split("/", 1)
        self.api.dataset_delete(owner, slug, no_confirm=True)


# -- SQL ---------------------------------------------------------------------

_EXPORT = """
EXPORT DATA OPTIONS (
  uri = 'gs://${bucket}/${prefix}/${run}/texts/*.parquet',
  format = 'PARQUET', overwrite = true) AS
"""

TEXTS_SQL: Final = """
SELECT TO_HEX(SHA256(t.texto_sanitizado)) AS text_key,
  ANY_VALUE(t.texto_sanitizado) AS texto_sanitizado
FROM `${tds}` AS t
WHERE TO_HEX(SHA256(t.texto_sanitizado)) IN (
  SELECT text_key FROM `${ds}.review_predictions_current`
  WHERE label_source = 'MODEL'
)
GROUP BY 1
"""

# Filas de la candidata a partir de las de la versión promovida. La
# temperatura replica ``voc_nlp.calibration.apply_temperature``.
SOURCE_SQL: Final = """
WITH base AS (
  SELECT c.id_resena, c.bank_id, c.text_key, c.fecha, c.version_app,
    c.estrellas, c.palabras, c.eligibility_code, c.label_source,
    c.sentiment AS kept_sentiment,
    LN(GREATEST(LEAST(p.p_NEG, 1.0), 1e-6)) / @t AS zn,
    LN(GREATEST(LEAST(p.p_NEU, 1.0), 1e-6)) / @t AS zu,
    LN(GREATEST(LEAST(p.p_POS, 1.0), 1e-6)) / @t AS zp
  FROM `${ds}.review_predictions_current` AS c
  LEFT JOIN `${preds}` AS p USING (text_key)
  WHERE NOT (c.label_source = 'MODEL' AND p.text_key IS NULL)
),
expo AS (
  SELECT *, EXP(zn - GREATEST(zn, zu, zp)) AS en,
    EXP(zu - GREATEST(zn, zu, zp)) AS eu,
    EXP(zp - GREATEST(zn, zu, zp)) AS ep
  FROM base
),
proba AS (
  SELECT *, en / (en + eu + ep) AS pn, eu / (en + eu + ep) AS pu,
    ep / (en + eu + ep) AS pp
  FROM expo
)
SELECT id_resena, bank_id, text_key, fecha, version_app, estrellas,
  palabras, @rules_version AS eligibility_rules_version,
  eligibility_code, label_source,
  CASE
    WHEN label_source != 'MODEL' THEN kept_sentiment
    WHEN pn >= pu AND pn >= pp THEN 'NEG'
    WHEN pu >= pp THEN 'NEU'
    ELSE 'POS'
  END AS sentiment,
  IF(label_source = 'MODEL', pn, NULL) AS p_neg,
  IF(label_source = 'MODEL', pu, NULL) AS p_neu,
  IF(label_source = 'MODEL', pp, NULL) AS p_pos,
  IF(label_source = 'MODEL', GREATEST(pn, pu, pp), NULL) AS confidence,
  @model_version AS model_version,
  @calibration_version AS calibration_version,
  CAST(NULL AS STRING) AS risk_policy_version,
  CAST(NULL AS STRING) AS hitl_boost_id,
  COALESCE(label_source = 'MODEL'
    AND GREATEST(pn, pu, pp) < @threshold, FALSE) AS requires_hitl,
  @run_id AS run_id, @now AS predicted_at
FROM proba
"""

MERGE_SQL: Final = """
MERGE `${ds}.review_predictions` T
USING (${source}) S
ON T.id_resena = S.id_resena AND T.model_version = S.model_version
  AND T.text_key = S.text_key
WHEN NOT MATCHED THEN INSERT ROW
"""

# Filas esperadas y cuántas ya están en la tabla con la versión candidata.
VERIFY_SQL: Final = """
WITH source AS (${source})
SELECT COUNT(*) AS expected, COUNT(r.id_resena) AS loaded,
  COUNT(DISTINCT IF(s.label_source = 'MODEL', s.text_key, NULL)) AS texts
FROM source AS s
LEFT JOIN `${ds}.review_predictions` AS r
  ON r.model_version = s.model_version AND r.id_resena = s.id_resena
  AND r.text_key = s.text_key
"""

CURVE_SQL: Final = """
SELECT * FROM `${ds}.hitl_coverage_curves`
WHERE model_version = @mv AND calibration_version = @cv
ORDER BY computed_at DESC LIMIT 1
"""

# -- Kernel ------------------------------------------------------------------

KERNEL: Final = '''"""Re-scoring en Kaggle (lo genera ml_inference.rescore)."""
import json, time
from pathlib import Path

import numpy as np, pyarrow as pa, pyarrow.parquet as pq, torch
from transformers import AutoModelForSequenceClassification

src = next(Path("/kaggle/input").rglob("tokens.parquet")).parent
work = Path("/kaggle/working")
CLASSES = ["NEG", "NEU", "POS"]
table = pq.read_table(src / "tokens.parquet")
keys = table["text_key"]
ids = table["input_ids"].to_pylist()
model = AutoModelForSequenceClassification.from_pretrained(
    src, torch_dtype=torch.float16, local_files_only=True).cuda().eval()
assert [model.config.id2label[i] for i in range(3)] == CLASSES
order = np.argsort([len(x) for x in ids], kind="stable")
out = np.zeros((len(ids), 3), dtype=np.float32)
start = time.perf_counter()
with torch.inference_mode():
    for i in range(0, len(ids), BATCH):
        idx = order[i:i + BATCH]
        batch = [ids[j] for j in idx]
        width = max(map(len, batch))
        x = torch.full((len(batch), width), PAD)
        for r, b in enumerate(batch):
            x[r, :len(b)] = torch.tensor(b)
        x = x.cuda()
        logits = model(input_ids=x, attention_mask=x != PAD).logits
        out[idx] = torch.softmax(logits.float(), dim=-1).cpu().numpy()
secs = time.perf_counter() - start
pq.write_table(pa.table({"text_key": keys, "p_NEG": out[:, 0],
                         "p_NEU": out[:, 1], "p_POS": out[:, 2]}),
               work / "preds.parquet", compression="zstd")
(work / "log.json").write_text(json.dumps({
    "run": RUN, "texts": len(ids), "seconds": round(secs, 1)}))
'''


def wait_for(
    status: Callable[[], str],
    timeout_sec: float,
    what: str,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    first_delay: bool = True,
) -> None:
    """Espera a que un dataset o kernel de Kaggle termine o falle."""
    start = clock()
    if first_delay:
        # Recién empujado, el estado puede ser todavía el de la versión
        # anterior; la salida se comprueba además contra la corrida.
        sleep(POLL_SECONDS)
    while True:
        current = status()
        if DONE in current or current == "ready":
            return
        if any(word in current for word in FAILED):
            raise KernelFailed(f"Kaggle {what} ended with {current}")
        if clock() - start > timeout_sec:
            raise KernelFailed(f"Kaggle {what} timed out ({current})")
        sleep(POLL_SECONDS)


def kernel_script(run: str, pad: int, batch: int = BATCH) -> str:
    return f"RUN = {run!r}\nPAD = {pad}\nBATCH = {batch}\n" + KERNEL


# -- Corrida -----------------------------------------------------------------


def check_slug(value: str) -> str:
    if not _SLUG.fullmatch(value):
        raise ValueError(f"invalid Kaggle slug: {value}")
    return value


def parse_gcs(uri: str) -> tuple[str, str]:
    """``gs://bucket/prefix/`` → (``bucket``, ``prefix/``)."""
    if not uri.startswith("gs://"):
        raise ValueError(f"not a GCS uri: {uri}")
    bucket, _, prefix = uri.removeprefix("gs://").partition("/")
    return bucket, prefix.rstrip("/") + "/"


@dataclass
class Rescoring:
    settings: InferenceSettings
    bigquery: Any
    storage: Any
    kaggle: KaggleClient
    model: ModelVersion
    run: str
    work: Path
    workers: int = field(default_factory=lambda: os.cpu_count() or 1)
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    texts: int = 0
    pad: int | None = None
    # La versión promovida, contra la que se mide la regla de promoción.
    current: ModelVersion | None = None
    # Quién la lanzó y por qué (MLOps o la CLI); nulos en el modo auto.
    actor_hash: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        check_slug(self.dataset_slug)
        if not _BUCKET.fullmatch(self.bucket):
            raise ValueError("invalid bucket name")

    @property
    def bucket(self) -> str:
        return self.settings.gcs_raw_datalake_bucket

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
    def prefix(self) -> str:
        return f"{GCS_PREFIX}/{self.run}/"

    @property
    def run_id(self) -> str:
        return f"rescore-{self.model.model_version}-{self.run}"

    def _sql(self, template: str, **tables: str) -> str:
        return render(
            template,
            ds=self.settings.dataset,
            tds=self.settings.tds_table,
            **tables,
        )

    # 1. Textos a GCS -------------------------------------------------------

    def export(self) -> None:
        head = Template(_EXPORT).substitute(
            bucket=self.bucket, prefix=GCS_PREFIX, run=self.run
        )
        run_dml(self.bigquery, head + self._sql(TEXTS_SQL))
        log.info(
            "rescore: textos exportados a gs://%s/%s", self.bucket, self.prefix
        )

    # 2. Dataset de Kaggle ----------------------------------------------------

    @property
    def dataset_dir(self) -> Path:
        return self.work / "dataset"

    def _weights(self) -> Path:
        bucket, prefix = parse_gcs(self.model.registry_uri)
        return artifacts.download_prefix(
            self.storage, bucket, prefix, self.dataset_dir
        )

    def _text_files(self) -> list[Path]:
        folder = self.work / "texts"
        folder.mkdir(parents=True, exist_ok=True)
        files = []
        for blob in self.storage.list_blobs(
            self.bucket, prefix=f"{self.prefix}texts/"
        ):
            target = folder / Path(blob.name).name
            blob.download_to_filename(str(target))
            files.append(target)
        if not files:
            raise RescoreError("the export left no text files")
        return sorted(files)

    def _prepare(self, texts: list[str]) -> list[str]:
        if self.workers <= 1:
            return prepare(texts)
        size = -(-len(texts) // self.workers)
        parts = [texts[i : i + size] for i in range(0, len(texts), size)]
        with ProcessPoolExecutor(self.workers) as pool:
            return [t for part in pool.map(prepare, parts) for t in part]

    def tokenize(self) -> int:
        """``tokens.parquet``: ``text_key`` e ids, sin texto."""
        tokenizer = load_tokenizer(self.dataset_dir)
        if tokenizer.pad_token_id is None:
            raise RescoreError("the tokenizer has no pad token")
        self.pad = int(tokenizer.pad_token_id)
        schema = pa.schema(
            [("text_key", pa.string()), ("input_ids", pa.list_(pa.int32()))]
        )
        total = 0
        path = self.dataset_dir / "tokens.parquet"
        with pq.ParquetWriter(path, schema, compression="zstd") as out:
            for file in self._text_files():
                for batch in pq.ParquetFile(file).iter_batches(CHUNK):
                    keys = batch.column("text_key").to_pylist()
                    ids = token_ids(
                        tokenizer,
                        self._prepare(
                            batch.column("texto_sanitizado").to_pylist()
                        ),
                    )
                    out.write_table(
                        pa.table(
                            {"text_key": keys, "input_ids": ids},
                            schema=schema,
                        )
                    )
                    total += len(keys)
                file.unlink()
        self.texts = total
        return total

    def push_dataset(self) -> None:
        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        self._weights()
        log.info("rescore: %d textos tokenizados", self.tokenize())
        meta = {
            "title": self.dataset_slug,
            "id": self.dataset_ref,
            "licenses": [{"name": "other"}],
        }
        (self.dataset_dir / "dataset-metadata.json").write_text(
            json.dumps(meta, indent=2)
        )
        self.kaggle.create_dataset(self.dataset_dir)
        self._wait(
            lambda: self.kaggle.dataset_status(self.dataset_ref),
            DATASET_TIMEOUT_SEC,
            "dataset",
            first_delay=False,
        )
        shutil.rmtree(self.dataset_dir)

    # 3. Kernel ---------------------------------------------------------------

    def run_kernel(self) -> None:
        folder = self.work / "kernel"
        folder.mkdir(parents=True, exist_ok=True)
        if self.pad is None:
            raise RescoreError("tokenize before pushing the kernel")
        (folder / "run.py").write_text(kernel_script(self.run, self.pad))
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
        self._wait(
            lambda: self.kaggle.kernel_status(self.kernel_ref),
            timeout_sec,
            "kernel",
        )

    def _wait(
        self,
        status: Callable[[], str],
        timeout_sec: float,
        what: str,
        first_delay: bool = True,
    ) -> None:
        wait_for(status, timeout_sec, what, self.sleep, self.clock, first_delay)

    # 4. Salida ---------------------------------------------------------------

    @property
    def preds_path(self) -> Path:
        return self.work / "preds" / "preds.parquet"

    def pull(self) -> None:
        folder = self.preds_path.parent
        folder.mkdir(parents=True, exist_ok=True)
        self.kaggle.kernel_output(self.kernel_ref, folder)
        log_file = folder / "log.json"
        if not log_file.exists() or not self.preds_path.exists():
            raise KernelFailed("the kernel output is incomplete")
        if json.loads(log_file.read_text())["run"] != self.run:
            raise KernelFailed("the kernel output belongs to another run")
        self.storage.bucket(self.bucket).blob(
            f"{self.prefix}preds.parquet"
        ).upload_from_filename(str(self.preds_path))

    # 5. Carga ----------------------------------------------------------------

    def threshold(self) -> float | None:
        """Umbral de la curva registrada a la cobertura vigente."""
        from ml_inference.lifecycle import point_for

        policies = query_rows(
            self.bigquery,
            self._sql("SELECT * FROM `${ds}.risk_policy_current`"),
        )
        curves = query_rows(
            self.bigquery,
            self._sql(CURVE_SQL),
            {
                "mv": self.model.model_version,
                "cv": self.model.calibration_version,
            },
        )
        if not policies or not curves:
            log.warning("rescore: sin curva o política; requires_hitl falso")
            return None
        coverage = RiskPolicy.model_validate(policies[0]).hitl_target_coverage
        curve = HitlCoverageCurve.model_validate(curves[0])
        return point_for(curve, coverage).threshold

    def load(self, now: datetime) -> int:
        keys = set(
            pq.read_table(self.preds_path, columns=["text_key"])
            .column("text_key")
            .to_pylist()
        )
        if len(keys) != self.texts:
            raise VerificationFailed(
                f"{self.texts} texts exported, {len(keys)} predicted"
            )
        run = self.run.replace("-", "_")
        staging = f"{self.settings.dataset}._staging_rescore_{run}"
        load_parquet(self.bigquery, str(self.preds_path), staging)
        source = self._sql(SOURCE_SQL, preds=staging)
        params = {
            "t": self.model.calibration_t,
            "rules_version": RULES_VERSION,
            "model_version": self.model.model_version,
            "calibration_version": self.model.calibration_version,
            "threshold": self.threshold(),
            "run_id": self.run_id,
            "now": now,
        }
        try:
            inserted = run_dml(
                self.bigquery,
                Template(MERGE_SQL).substitute(
                    ds=self.settings.dataset, source=source
                ),
                params,
            )
            check = query_rows(
                self.bigquery,
                Template(VERIFY_SQL).substitute(
                    ds=self.settings.dataset, source=source
                ),
                params,
            )[0]
        finally:
            self.bigquery.delete_table(staging, not_found_ok=True)
        if int(check["loaded"]) != int(check["expected"]):
            raise VerificationFailed(
                f"{check['loaded']} of {check['expected']} rows loaded"
            )
        if int(check["texts"]) != self.texts:
            raise VerificationFailed(
                f"{check['texts']} of {self.texts} texts reached the table"
            )
        return inserted

    # 6. Limpieza -------------------------------------------------------------

    def cleanup(self) -> None:
        self.kaggle.delete_dataset(self.dataset_ref)
        for blob in self.storage.list_blobs(
            self.bucket, prefix=f"{self.prefix}texts/"
        ):
            blob.delete()
        log.info("rescore: dataset %s borrado", self.dataset_ref)

    # 6. Regla de promoción ------------------------------------------------

    def record_promotion_check(
        self, writer: StagingMergeWriter, computed_at: datetime
    ) -> PromotionCheckResult | None:
        """Guarda la regla contra la versión promovida, o avisa y sigue."""
        from ml_inference.lifecycle import Lifecycle, check_promotion

        if self.current is None:
            log.warning(
                "rescore %s: sin versión promovida, sin regla", self.run
            )
            return None
        lifecycle = Lifecycle(
            self.bigquery,
            writer,
            self.settings.dataset,
            self.settings.gold_version,
        )
        try:
            check = check_promotion(
                lifecycle.gold(self.current.model_version),
                lifecycle.gold(self.model.model_version),
            )
            diff = {d.metric: d for d in check.differences}
            row = PromotionCheckResult(
                candidate_version=self.model.model_version,
                current_version=self.current.model_version,
                gold_version=lifecycle.gold_version,
                n=check.n,
                kappa_diff=diff["kappa"].value,
                kappa_ci_low=diff["kappa"].ci[0],
                kappa_ci_high=diff["kappa"].ci[1],
                macro_f1_diff=diff["macro_f1"].value,
                macro_f1_ci_low=diff["macro_f1"].ci[0],
                macro_f1_ci_high=diff["macro_f1"].ci[1],
                verdict=PromotionVerdict(check.verdict),
                run_id=self.run_id,
                computed_at=computed_at,
            )
        except ValueError as exc:
            log.warning(
                "rescore %s: regla de promoción no calculada: %s", self.run, exc
            )
            return None
        writer.write(
            "promotion_checks",
            [row],
            ["candidate_version", "current_version", "run_id"],
            self.run_id,
        )
        log.info("rescore %s: regla %s", self.run, check.describe())
        return row


def run_rescore(
    job: Rescoring,
    writer: StagingMergeWriter,
    timeout_sec: float,
    now: Callable[[], datetime],
) -> InferenceRun:
    """Corre los pasos y registra la corrida, con éxito o fallida."""
    started = now()
    reviews = 0
    status = RunStatus.FAILED
    try:
        job.export()
        job.push_dataset()
        job.run_kernel()
        job.wait_kernel(timeout_sec)
        job.pull()
        reviews = job.load(started)
        job.record_promotion_check(writer, now())
        job.cleanup()
        status = RunStatus.SUCCEEDED
    except RescoreError as exc:
        log.error("rescore %s: %s (dataset %s)", job.run, exc, job.dataset_ref)
    finally:
        row = InferenceRun(
            run_id=job.run_id,
            actor_hash=job.actor_hash,
            reason=job.reason,
            kind=RunKind.RESCORING,
            environment=RunEnvironment.KAGGLE,
            model_version=job.model.model_version,
            started_at=started,
            ended_at=now(),
            reviews=reviews,
            texts=job.texts,
            status=status,
        )
        write_run(writer, row)
        shutil.rmtree(job.work, ignore_errors=True)
    return row


def new_rescoring(
    settings: InferenceSettings,
    bigquery: Any,
    storage: Any,
    kaggle: KaggleClient,
    model_version: str,
    run: str,
    versions: dict[str, ModelVersion],
) -> Rescoring:
    if model_version not in versions:
        raise LookupError(f"{model_version} is not in model_versions")
    model = versions[model_version]
    if model.status.value == "promoted":
        raise ValueError(f"{model_version} is promoted: nothing to rescore")
    current = max(
        (v for v in versions.values() if v.status.value == "promoted"),
        key=lambda v: v.promoted_at or v.recorded_at,
        default=None,
    )
    work = Path(tempfile.mkdtemp(prefix="rescore-"))
    return Rescoring(
        settings, bigquery, storage, kaggle, model, run, work, current=current
    )
