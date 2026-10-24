"""Carga única del backfill de EPIC-5 desde la máquina del autor (6.3).

Corre en el Mac del autor (decisión del autor, 2026-10-24; FMEA F-11): lee
``id_resena``, ``bank_id``, ``fecha`` y ``texto_limpio`` del TDS en memoria
para la elegibilidad, sin guardarlos. Lo demás viaja sin texto: parquet con
``text_key`` en tablas temporales de BigQuery, y las tablas finales se arman
con ``MERGE`` dentro de BigQuery.

Pasos (``load_backfill``):

1. Sube a ``ml_artifacts/`` los pesos de RoBERTuito (semilla 1), el modelo de
   tópicos (``topics_v1``, el ``model_v0`` de EPIC-5) y MiniLM.
2. ``review_predictions``: elegibilidad v1 por fila, predicciones sin
   calibrar de la semilla 1 (``preds_s1.parquet``) y la T del modelo. Las
   filas ``MODEL`` sin predicción (textos editados o posteriores al
   *snapshot*) entran con el primer delta.
3. ``review_aspects``: ``labels_by_key.parquet`` para las negativas de dos
   palabras o más. Los códigos fuera de las 11 familias (2 filas con ``UI``)
   se descartan.
4. ``text_embeddings``: ``emb_minilm.npy`` replicado por banco × mes.
5. ``topic_assignments``, ``topic_model_versions``, ``topic_catalog`` y
   ``curation_topics`` (curaduría de 5.5, fase 4).
6. ``gold_labels``: el parquet sin texto de
   ``voc_analytics.labeling.export_gold_v3`` (D10).
7. Una fila de ``inference_runs`` por carga.
"""

import csv
import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from voc_common.analytics_codes import (
    AspectFamily,
    RunEnvironment,
    RunKind,
    RunStatus,
    TopicAudience,
)
from voc_common.operations_v3 import GoldLabel, InferenceRun
from voc_common.predictions_v3 import (
    TopicCatalogEntry,
    TopicCuration,
    TopicModelVersion,
)
from voc_nlp.eligibility import RULES_VERSION, tnss_rule
from voc_nlp.lexicon import Lexicon, load_lexicon

from ml_inference import artifacts
from ml_inference.bq_io import (
    StagingMergeWriter,
    load_parquet,
    render,
    run_dml,
)
from ml_inference.config import InferenceSettings
from ml_inference.seed import EPIC5_MODEL, MODEL_VERSION

log = logging.getLogger(__name__)

TOPIC_MODEL_VERSION: Final = "topics_v1"
GOLD_VERSION: Final = "gold_epic5_v1"
PROMPT_VERSION: Final = "aspects_v2_1"
LLM_MODEL: Final = "gemini-3.6-flash"
FAMILIES: Final = tuple(f.value for f in AspectFamily)
# Curaduría de 5.5: ingeniería si no sirve a producto y su coherencia es ≥ 3.
MIN_COHERENCE: Final = 3
PAGE_SIZE: Final = 50_000


@dataclass(frozen=True)
class LocalBackfill:
    """Rutas de los archivos de EPIC-5 en la máquina del autor."""

    run_dir: Path  # data/backfill/20261022
    weights_dir: Path  # data/models/weights/M4_robertuito_s1_ppi
    curation_csv: Path  # data/topics/phase4_v0/revision_topicos.csv
    gold_parquet: Path  # data/handoff/gold_labels_v1.parquet
    minilm_dir: Path  # carpeta de SentenceTransformer.save

    @classmethod
    def from_data_dir(cls, data: Path, minilm_dir: Path) -> "LocalBackfill":
        return cls(
            run_dir=data / "backfill" / "20261022",
            weights_dir=data / "models" / "weights" / EPIC5_MODEL,
            curation_csv=data / "topics" / "phase4_v0" / "revision_topicos.csv",
            gold_parquet=data / "handoff" / "gold_labels_v1.parquet",
            minilm_dir=minilm_dir,
        )

    @property
    def topic_model_dir(self) -> Path:
        return self.run_dir / "topics" / "model_v0"


@dataclass
class Loader:
    settings: InferenceSettings
    bigquery: Any
    storage: Any
    files: LocalBackfill
    work_dir: Path
    actor_hash: str
    now: datetime
    lexicon: Lexicon | None = None
    topic_terms: Callable[[Path], dict[int, list[str]]] | None = None

    @property
    def ds(self) -> str:
        return self.settings.dataset

    @property
    def run_id(self) -> str:
        return f"backfill-20261022-{self.now:%Y%m%dT%H%M%S}"

    def _staging(self, name: str, path: Path) -> str:
        table = f"{self.ds}._load_{name}_{self.now:%Y%m%d%H%M%S}"
        return load_parquet(self.bigquery, str(path), table)

    def _drop(self, *tables: str) -> None:
        for table in tables:
            self.bigquery.delete_table(table, not_found_ok=True)

    # -- 1. artefactos -------------------------------------------------------

    def upload_artifacts(self) -> dict[str, int]:
        root = self.settings.ml_artifacts_prefix
        bucket = self.settings.gcs_raw_datalake_bucket
        plan = {
            artifacts.SENTIMENT: (self.files.weights_dir, MODEL_VERSION),
            artifacts.TOPICS: (self.files.topic_model_dir, TOPIC_MODEL_VERSION),
            artifacts.EMBEDDINGS: (self.files.minilm_dir, artifacts.MINILM),
        }
        return {
            kind: artifacts.upload_dir(
                self.storage,
                bucket,
                source,
                artifacts.artifact_prefix(root, kind, name),
            )
            for kind, (source, name) in plan.items()
        }

    # -- 2. sentimiento ------------------------------------------------------

    def _tds_pages(self) -> Iterator[list[dict[str, Any]]]:
        job = self.bigquery.query(
            render(
                "SELECT id_resena, bank_id, fecha, texto_limpio FROM `$${tds}`",
                tds=self.settings.tds_table,
            )
        )
        page: list[dict[str, Any]] = []
        for row in job.result(page_size=PAGE_SIZE):
            page.append(dict(row.items()))
            if len(page) == PAGE_SIZE:
                yield page
                page = []
        if page:
            yield page

    def eligibility_file(self) -> tuple[Path, int]:
        """Parquet ``id_resena`` → código, fuente, etiqueta del léxico y
        palabras. El texto no se escribe."""
        lexicon = self.lexicon or load_lexicon()
        path = self.work_dir / "eligibility.parquet"
        schema = pa.schema(
            [
                ("id_resena", pa.string()),
                ("eligibility_code", pa.string()),
                ("label_source", pa.string()),
                ("lexicon_label", pa.string()),
                ("palabras", pa.int64()),
            ]
        )
        total = 0
        with pq.ParquetWriter(path, schema) as out:
            for page in self._tds_pages():
                decisions = [
                    tnss_rule(
                        r["texto_limpio"], r["fecha"], r["bank_id"], lexicon
                    )
                    for r in page
                ]
                out.write_table(
                    pa.table(
                        {
                            "id_resena": [r["id_resena"] for r in page],
                            "eligibility_code": [
                                d.code.value for d in decisions
                            ],
                            "label_source": [d.source.value for d in decisions],
                            "lexicon_label": [
                                d.label.value if d.label else None
                                for d in decisions
                            ],
                            "palabras": [d.palabras for d in decisions],
                        },
                        schema=schema,
                    )
                )
                total += len(page)
        return path, total

    def predictions(self, policy: dict[str, Any] | None) -> int:
        eligibility, _ = self.eligibility_file()
        elig = self._staging("eligibility", eligibility)
        preds = self._staging(
            "preds", self.files.run_dir / "preds" / "preds_s1.parquet"
        )
        try:
            return run_dml(
                self.bigquery,
                predictions_sql(self.ds, self.settings.tds_table, elig, preds),
                {
                    "model_version": MODEL_VERSION,
                    "calibration_version": policy_value(policy, "cv"),
                    "t": policy_value(policy, "t"),
                    "policy_version": policy_value(policy, "version"),
                    "threshold": policy_value(policy, "threshold"),
                    "rules_version": RULES_VERSION,
                    "run_id": self.run_id,
                    "now": self.now,
                },
            )
        finally:
            self._drop(elig, preds)

    # -- 3. familias -------------------------------------------------------

    def aspects(self) -> int:
        labels = self._staging(
            "aspects",
            self.files.run_dir / "aspects" / "labels_by_key.parquet",
        )
        try:
            return run_dml(
                self.bigquery,
                aspects_sql(self.ds, labels),
                {
                    "families": list(FAMILIES),
                    "prompt": PROMPT_VERSION,
                    "llm": LLM_MODEL,
                    "model_version": MODEL_VERSION,
                    "run_id": self.run_id,
                    "now": self.now,
                },
            )
        finally:
            self._drop(labels)

    # -- 4. embeddings -----------------------------------------------------

    def embeddings_file(self) -> Path:
        folder = self.files.run_dir / "embeddings"
        keys = pq.read_table(folder / "keys.parquet")["text_key"]
        vectors = np.load(folder / "emb_minilm.npy", mmap_mode="r")
        if len(keys) != vectors.shape[0]:
            raise ValueError("embeddings and keys differ in length")
        path = self.work_dir / "embeddings.parquet"
        schema = pa.schema(
            [("text_key", pa.string()), ("embedding", pa.list_(pa.float32()))]
        )
        with pq.ParquetWriter(path, schema) as out:
            for start in range(0, len(keys), PAGE_SIZE):
                chunk = np.asarray(vectors[start : start + PAGE_SIZE])
                flat = pa.array(chunk.reshape(-1), type=pa.float32())
                offsets = pa.array(
                    np.arange(0, chunk.size + 1, chunk.shape[1], dtype=np.int32)
                )
                out.write_table(
                    pa.table(
                        {
                            "text_key": keys[start : start + PAGE_SIZE],
                            "embedding": pa.ListArray.from_arrays(
                                offsets, flat
                            ),
                        },
                        schema=schema,
                    )
                )
        return path

    def embeddings(self) -> int:
        from voc_nlp.topics import EMBEDDING_MODEL

        staging = self._staging("embeddings", self.embeddings_file())
        try:
            return run_dml(
                self.bigquery,
                embeddings_sql(self.ds, self.settings.tds_table, staging),
                {"model": EMBEDDING_MODEL, "now": self.now},
            )
        finally:
            self._drop(staging)

    # -- 5. tópicos ----------------------------------------------------------

    def topic_assignments(self) -> int:
        staging = self._staging(
            "segments",
            self.files.run_dir / "topics" / "segment_topics_v0.parquet",
        )
        try:
            return run_dml(
                self.bigquery,
                topics_sql(self.ds, staging),
                {
                    "version": TOPIC_MODEL_VERSION,
                    "model_version": MODEL_VERSION,
                },
            )
        finally:
            self._drop(staging)

    def topic_tables(self, writer: StagingMergeWriter) -> dict[str, int]:
        meta = json.loads(
            (self.files.topic_model_dir / "model.json").read_text("utf-8")
        )
        version = TopicModelVersion(
            topic_model_version=TOPIC_MODEL_VERSION,
            fitted_at=datetime.fromisoformat(meta["generado"]),
            embedding_model=meta["embeddings"],
            segmenter="clause_segmenter_v1",
            params={
                k: meta[k]
                for k in (
                    "variante",
                    "max_seq",
                    "min_cluster_size",
                    "min_samples",
                    "semilla_umap",
                    "topicos",
                )
            },
            fit_sample=f"{meta['segmentos_ajuste']} segmentos (5.5, 5.9)",
        )
        terms = (self.topic_terms or bertopic_terms)(self.files.topic_model_dir)
        catalog = [
            TopicCatalogEntry(
                topic_model_version=TOPIC_MODEL_VERSION,
                topic_id=topic,
                terms=words,
            )
            for topic, words in sorted(terms.items())
        ]
        return {
            "topic_model_versions": writer.write(
                "topic_model_versions",
                [version],
                ["topic_model_version"],
                self.run_id,
            ),
            "topic_catalog": writer.write(
                "topic_catalog",
                catalog,
                ["topic_model_version", "topic_id"],
                self.run_id,
            ),
            "curation_topics": writer.write(
                "curation_topics",
                curation_rows(
                    self.files.curation_csv, self.actor_hash, self.now
                ),
                ["topic_model_version", "topic_id", "curator_hash"],
                self.run_id,
            ),
        }

    # -- 6. oro ------------------------------------------------------------

    def gold(self, writer: StagingMergeWriter) -> int:
        table = pq.read_table(self.files.gold_parquet).to_pylist()
        rows = [
            GoldLabel(gold_version=GOLD_VERSION, loaded_at=self.now, **row)
            for row in table
        ]
        return writer.write(
            "gold_labels",
            rows,
            ["gold_version", "split", "text_key", "id_resena"],
            self.run_id,
        )

    # -- 7. corridas ---------------------------------------------------------

    def runs(
        self, counts: dict[str, int], ended: datetime
    ) -> list[InferenceRun]:
        manifest = json.loads(
            (self.files.run_dir / "manifest.json").read_text("utf-8")
        )
        common = {
            "kind": RunKind.BACKFILL,
            "started_at": self.now,
            "ended_at": ended,
            "status": RunStatus.SUCCEEDED,
        }
        return [
            InferenceRun(
                run_id=f"{self.run_id}-sentiment",
                environment=RunEnvironment.KAGGLE,
                model_version=MODEL_VERSION,
                reviews=counts.get("review_predictions", 0),
                texts=int(manifest["textos_unicos"]),
                **common,
            ),
            InferenceRun(
                run_id=f"{self.run_id}-aspects",
                environment=RunEnvironment.LOCAL,
                model_version=None,
                reviews=counts.get("review_aspects", 0),
                texts=0,
                **common,
            ),
            InferenceRun(
                run_id=f"{self.run_id}-topics",
                environment=RunEnvironment.LOCAL,
                model_version=None,
                reviews=counts.get("topic_assignments", 0),
                texts=counts.get("text_embeddings", 0),
                **common,
            ),
        ]


def policy_value(policy: dict[str, Any] | None, field: str) -> Any:
    """Calibración, T y umbral vigentes, o nulos si aún no se siembra."""
    if policy is None:
        return None
    return policy[field]


def bertopic_terms(path: Path, top: int = 10) -> dict[int, list[str]]:
    """Términos de cada tópico del modelo congelado (sin el ruido ``-1``)."""
    from voc_nlp.topics import load_topic_model

    model = load_topic_model(path).bertopic
    return {
        int(topic): [word for word, _ in (model.get_topic(topic) or [])][:top]
        for topic in model.get_topics()
        if int(topic) != -1
    }


def curation_rows(
    path: Path, curator_hash: str, now: datetime
) -> list[TopicCuration]:
    """Curaduría de 5.5 (fase 4) con la regla de audiencia de 5.9."""
    rows = []
    with path.open(encoding="utf-8") as handle:
        for r in csv.DictReader(handle):
            product = r["util_para_producto_si_no"].strip().lower() == "si"
            coherence = int(r["coherencia_1a5"])
            audience = (
                TopicAudience.PRODUCTO
                if product
                else TopicAudience.INGENIERIA
                if coherence >= MIN_COHERENCE
                else TopicAudience.SIN_VALOR
            )
            codes = (r.get("familia_correcta") or "").replace(" ", "")
            if not codes:
                codes = r.get("familia_mayoritaria") or ""
            families = list(
                dict.fromkeys(c for c in codes.split(",") if c in FAMILIES)
            )
            rows.append(
                TopicCuration(
                    topic_model_version=TOPIC_MODEL_VERSION,
                    topic_id=int(r["topico"]),
                    curated_name=r["nombre_propuesto"].strip()
                    or f"tópico {r['topico']}",
                    coherence_1_5=coherence,
                    audience=audience,
                    families=families,
                    is_new_theme=r["tema_nuevo_si_no"].strip().lower() == "si",
                    mapping_confirmed=True,
                    curator_hash=curator_hash,
                    curated_at=now,
                )
            )
    return rows


# -- SQL ------------------------------------------------------------------


def predictions_sql(ds: str, tds: str, elig: str, preds: str) -> str:
    """``review_predictions`` con temperatura y umbral, como el delta.

    La temperatura replica ``voc_nlp.calibration.apply_temperature``:
    ``log(clip(p, 1e-6, 1)) / T`` y *softmax* restando el máximo.
    """
    return render(
        """
    MERGE `${ds}.review_predictions` T
    USING (
      WITH base AS (
        SELECT t.id_resena, t.bank_id, t.fecha, t.version_app, t.estrellas,
          TO_HEX(SHA256(t.texto_sanitizado)) AS text_key,
          e.eligibility_code, e.label_source, e.lexicon_label, e.palabras,
          LN(GREATEST(LEAST(p.p_NEG, 1.0), 1e-6)) / @t AS zn,
          LN(GREATEST(LEAST(p.p_NEU, 1.0), 1e-6)) / @t AS zu,
          LN(GREATEST(LEAST(p.p_POS, 1.0), 1e-6)) / @t AS zp
        FROM `${tds}` AS t
        JOIN `${elig}` AS e USING (id_resena)
        LEFT JOIN `${preds}` AS p
          ON p.text_key = TO_HEX(SHA256(t.texto_sanitizado))
        WHERE NOT (e.label_source = 'MODEL' AND p.text_key IS NULL)
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
          WHEN label_source = 'NO_PREDICTED' THEN 'NO_PREDICTED'
          WHEN label_source = 'RULE_BASED' THEN lexicon_label
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
        IF(label_source = 'MODEL', @policy_version, NULL)
          AS risk_policy_version,
        CAST(NULL AS STRING) AS hitl_boost_id,
        COALESCE(label_source = 'MODEL'
          AND GREATEST(pn, pu, pp) < @threshold, FALSE) AS requires_hitl,
        @run_id AS run_id, @now AS predicted_at
      FROM proba
    ) S
    ON T.id_resena = S.id_resena AND T.model_version = S.model_version
      AND T.text_key = S.text_key
    WHEN NOT MATCHED THEN INSERT ROW
    """,
        ds=ds,
        tds=tds,
        elig=elig,
        preds=preds,
    )


def aspects_sql(ds: str, labels: str) -> str:
    return render(
        """
    MERGE `${ds}.review_aspects` T
    USING (
      SELECT p.id_resena, p.bank_id, p.text_key, p.fecha,
        ARRAY(
          SELECT c FROM UNNEST(SPLIT(l.codes, ',')) AS c
          WHERE c IN UNNEST(@families)
        ) AS families,
        l.actualizacion AS flag_update, l.seguridad AS flag_security,
        l.elogio AS praise, @prompt AS prompt_version, @llm AS llm_model,
        'v2.1' AS guideline_version,
        @model_version AS sentiment_model_version,
        @run_id AS run_id, @now AS labeled_at
      FROM `${ds}.review_predictions` AS p
      JOIN `${labels}` AS l USING (text_key)
      WHERE p.model_version = @model_version
        AND p.sentiment = 'NEG' AND p.palabras >= 2
    ) S
    ON T.id_resena = S.id_resena AND T.text_key = S.text_key
      AND T.prompt_version = S.prompt_version
    WHEN NOT MATCHED THEN INSERT ROW
    """,
        ds=ds,
        labels=labels,
    )


def embeddings_sql(ds: str, tds: str, staging: str) -> str:
    return render(
        """
    MERGE `${ds}.text_embeddings` T
    USING (
      SELECT k.text_key, k.bank_id, k.mes, e.embedding,
        @model AS embedding_model, @now AS created_at
      FROM (
        SELECT DISTINCT TO_HEX(SHA256(texto_sanitizado)) AS text_key,
          bank_id, DATE_TRUNC(DATE(fecha), MONTH) AS mes
        FROM `${tds}`
      ) AS k
      JOIN `${staging}` AS e USING (text_key)
    ) S
    ON T.text_key = S.text_key AND T.bank_id = S.bank_id AND T.mes = S.mes
    WHEN NOT MATCHED THEN INSERT ROW
    """,
        ds=ds,
        tds=tds,
        staging=staging,
    )


def topics_sql(ds: str, staging: str) -> str:
    return render(
        """
    MERGE `${ds}.topic_assignments` T
    USING (
      SELECT p.id_resena, p.bank_id, p.text_key, p.fecha,
        s.orden AS segment_index, @version AS topic_model_version,
        s.topic AS topic_id
      FROM `${ds}.review_predictions` AS p
      JOIN `${staging}` AS s USING (text_key)
      WHERE p.model_version = @model_version
        AND p.sentiment = 'NEG' AND p.palabras >= 2
    ) S
    ON T.id_resena = S.id_resena AND T.text_key = S.text_key
      AND T.topic_model_version = S.topic_model_version
      AND T.segment_index = S.segment_index
    WHEN NOT MATCHED THEN INSERT ROW
    """,
        ds=ds,
        staging=staging,
    )


def load_backfill(
    settings: InferenceSettings,
    bigquery: Any,
    storage: Any,
    files: LocalBackfill,
    work_dir: Path,
    actor_hash: str,
    now: datetime,
    **overrides: Any,
) -> list[InferenceRun]:
    """Corre los siete pasos y registra las corridas en ``inference_runs``."""
    from ml_inference.state import load_state

    loader = Loader(
        settings,
        bigquery,
        storage,
        files,
        work_dir,
        actor_hash,
        now,
        **overrides,
    )
    writer = StagingMergeWriter(bigquery, settings.dataset)
    state = load_state(bigquery, settings.dataset)
    policy = state.policy_for_model
    params = {
        "cv": state.model.calibration_version,
        "t": state.model.calibration_t,
        "version": policy.policy_version if policy else None,
        "threshold": policy.hitl_threshold if policy else None,
    }
    counts: dict[str, int] = {}
    log.info("artefactos: %s", loader.upload_artifacts())
    counts["review_predictions"] = loader.predictions(params)
    counts["review_aspects"] = loader.aspects()
    counts["text_embeddings"] = loader.embeddings()
    counts["topic_assignments"] = loader.topic_assignments()
    counts.update(loader.topic_tables(writer))
    counts["gold_labels"] = loader.gold(writer)
    log.info("filas nuevas: %s", counts)
    runs = loader.runs(counts, max(datetime.now(now.tzinfo), now))
    writer.write("inference_runs", runs, ["run_id"], loader.run_id)
    return runs
