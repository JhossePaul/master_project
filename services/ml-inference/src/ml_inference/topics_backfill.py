"""Re-asignación del histórico de tópicos a la versión vigente.

Corre en el Job ``voc-ml-topics-backfill`` (comando ``topics-backfill``),
en Cloud Run y sin Kaggle: el texto no sale de GCP. La lanza el delta cuando
quedan negativas sin asignar a la versión vigente; mientras tanto, el delta
solo asigna lo que llega por la ingesta diaria.

Pasos (``run_topics_backfill``):

1. **Vectores que faltan:** las negativas pendientes cuyo texto no tiene
   filas en ``segment_embeddings`` (por ejemplo, una que pasó a ``NEG`` tras
   una promoción) se segmentan y se embeben con MiniLM, y sus vectores se
   guardan.
2. **Asignación:** lee de ``segment_embeddings`` los vectores de las
   negativas pendientes, por texto y en orden, en lotes de unas 50 000
   cláusulas que no parten un texto, y les asigna tópico con el UMAP y el
   BERTopic congelados de la versión. ``BERTopic.transform`` no lee el texto
   cuando recibe los vectores, así que el histórico no se vuelve a leer.
3. **Escritura:** ``topic_assignments`` con ``MERGE`` después de cada lote;
   una corrida interrumpida se retoma con lo que quedó pendiente.
4. **Verificación:** ninguna negativa de dos palabras o más queda sin
   asignar; si queda alguna, la corrida termina en ``failed``.

Una fila en ``inference_runs`` (``kind = topic_backfill``) registra la
corrida, también si falla.
"""

import gc
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
from voc_common.analytics_codes import RunEnvironment, RunKind, RunStatus
from voc_common.operations_v3 import InferenceRun
from voc_common.predictions_v3 import SegmentEmbedding, TopicAssignment

from ml_inference import artifacts
from ml_inference.bq_io import StagingMergeWriter, iter_rows, query_rows, render
from ml_inference.config import InferenceSettings
from ml_inference.delta import peak_memory_mib
from ml_inference.engines import EngineLoaders

log = logging.getLogger(__name__)

BATCH_SEGMENTS: Final = 50_000
EMBED_TEXTS: Final = 5_000

# Negativas de dos palabras o más sin asignación para la versión.
_PENDING: Final = """
  SELECT p.id_resena, p.bank_id, p.text_key, p.fecha
  FROM `${ds}.review_predictions_current` AS p
  LEFT JOIN `${ds}.topic_assignments` AS a
    ON a.id_resena = p.id_resena AND a.text_key = p.text_key
    AND a.topic_model_version = @version
  WHERE p.sentiment = 'NEG' AND p.palabras >= 2 AND a.id_resena IS NULL
"""

# ``@@pending@@`` se reemplaza por ``_PENDING``, una constante: los valores
# van siempre como parámetros.
_MISSING_TEMPLATE: Final = """
-- Textos pendientes sin vectores de cláusulas
WITH pending AS (@@pending@@)
SELECT DISTINCT p.text_key, t.texto_sanitizado
FROM pending AS p
JOIN `${tds}` AS t
  ON t.id_resena = p.id_resena
  AND TO_HEX(SHA256(t.texto_sanitizado)) = p.text_key
LEFT JOIN `${ds}.segment_embeddings` AS e ON e.text_key = p.text_key
WHERE e.text_key IS NULL
"""
MISSING_SQL: Final = _MISSING_TEMPLATE.replace("@@pending@@", _PENDING)

_VECTORS_TEMPLATE: Final = """
-- Vectores de las cláusulas pendientes, por texto
WITH pending AS (@@pending@@)
SELECT e.text_key, e.segment_index, e.embedding
FROM `${ds}.segment_embeddings` AS e
WHERE e.text_key IN (SELECT text_key FROM pending)
ORDER BY e.text_key, e.segment_index
"""
VECTORS_SQL: Final = _VECTORS_TEMPLATE.replace("@@pending@@", _PENDING)

_REVIEWS_TEMPLATE: Final = """
-- Reseñas pendientes de un lote de textos
WITH pending AS (@@pending@@)
SELECT * FROM pending WHERE text_key IN UNNEST(@keys)
"""
REVIEWS_SQL: Final = _REVIEWS_TEMPLATE.replace("@@pending@@", _PENDING)

_LEFT_TEMPLATE: Final = """
-- Reseñas que siguen pendientes
WITH pending AS (@@pending@@)
SELECT COUNT(*) AS left_reviews FROM pending
"""
LEFT_SQL: Final = _LEFT_TEMPLATE.replace("@@pending@@", _PENDING)


class TopicBackfillError(RuntimeError):
    """Falla esperada de la corrida: queda en ``failed``."""


@dataclass
class _Batch:
    keys: list[str]
    indices: list[int]
    vectors: list[list[float]]


@dataclass
class TopicsBackfill:
    settings: InferenceSettings
    bigquery: Any
    storage: Any
    writer: StagingMergeWriter
    version: str
    run_id: str
    now: datetime
    engines: EngineLoaders = field(default_factory=EngineLoaders)
    reviews: int = 0
    texts: int = 0

    def _sql(self, template: str) -> str:
        return render(
            template, ds=self.settings.dataset, tds=self.settings.tds_table
        )

    def _download(self, kind: str, name: str) -> Path:
        dest = self.settings.artifacts_dir / kind / name
        if not dest.exists():
            artifacts.download_prefix(
                self.storage,
                self.settings.gcs_raw_datalake_bucket,
                artifacts.artifact_prefix(
                    self.settings.ml_artifacts_prefix, kind, name
                ),
                dest,
            )
        return dest

    def embed_missing(self) -> int:
        """Segmenta, embebe y guarda los textos pendientes sin vectores."""
        from voc_nlp.topics import EMBEDDING_MODEL, SEGMENTER, segment

        missing = query_rows(
            self.bigquery, self._sql(MISSING_SQL), {"version": self.version}
        )
        if not missing:
            return 0
        name = EMBEDDING_MODEL.rsplit("/", 1)[-1]
        embedder = self.engines.embedder(
            self._download(artifacts.EMBEDDINGS, name)
        )
        written = 0
        for start in range(0, len(missing), EMBED_TEXTS):
            flat = [
                (r["text_key"], i, part)
                for r in missing[start : start + EMBED_TEXTS]
                for i, part in enumerate(segment(r["texto_sanitizado"]))
            ]
            vectors = embedder.embed([part for _, _, part in flat])
            rows = [
                SegmentEmbedding(
                    text_key=key,
                    segment_index=i,
                    segmenter=SEGMENTER,
                    embedding_model=EMBEDDING_MODEL,
                    embedding=[float(x) for x in vec],
                    run_id=self.run_id,
                    created_at=self.now,
                )
                for (key, i, _), vec in zip(flat, vectors, strict=True)
            ]
            written += self.writer.write(
                "segment_embeddings",
                rows,
                ["text_key", "segment_index"],
                self.run_id,
            )
        del embedder
        gc.collect()
        log.info("topics-backfill: %d textos embebidos", len(missing))
        return written

    def batches(self) -> Iterator[_Batch]:
        """Vectores pendientes en lotes que no parten un texto."""
        batch = _Batch([], [], [])
        for r in iter_rows(
            self.bigquery, self._sql(VECTORS_SQL), {"version": self.version}
        ):
            key = r["text_key"]
            if len(batch.keys) >= BATCH_SEGMENTS and key != batch.keys[-1]:
                yield batch
                batch = _Batch([], [], [])
            batch.keys.append(key)
            batch.indices.append(int(r["segment_index"]))
            batch.vectors.append(r["embedding"])
        if batch.keys:
            yield batch

    def assign(self) -> int:
        """Asigna y escribe lote por lote; devuelve las filas nuevas."""
        assigner = None
        written = 0
        for batch in self.batches():
            if assigner is None:
                assigner = self.engines.topics(
                    self._download(artifacts.TOPICS, self.version)
                )
            emb = np.asarray(batch.vectors, dtype=np.float32)
            # BERTopic no lee el texto cuando recibe los vectores.
            topics = assigner.assign([""] * len(batch.keys), emb)
            by_key: dict[str, list[tuple[int, int]]] = {}
            for key, index, topic in zip(
                batch.keys, batch.indices, topics, strict=True
            ):
                by_key.setdefault(key, []).append((index, int(topic)))
            reviews = query_rows(
                self.bigquery,
                self._sql(REVIEWS_SQL),
                {"version": self.version, "keys": sorted(by_key)},
            )
            rows = [
                TopicAssignment(
                    id_resena=r["id_resena"],
                    bank_id=r["bank_id"],
                    text_key=r["text_key"],
                    fecha=r["fecha"],
                    segment_index=index,
                    topic_model_version=self.version,
                    topic_id=topic,
                )
                for r in reviews
                for index, topic in by_key[r["text_key"]]
            ]
            written += self.writer.write(
                "topic_assignments",
                rows,
                [
                    "id_resena",
                    "text_key",
                    "topic_model_version",
                    "segment_index",
                ],
                self.run_id,
            )
            self.texts += len(by_key)
            self.reviews += len({r["id_resena"] for r in reviews})
            log.info(
                "topics-backfill: lote de %d cláusulas, %d textos",
                len(batch.keys),
                len(by_key),
            )
        del assigner
        gc.collect()
        return written

    def verify(self) -> None:
        left = query_rows(
            self.bigquery, self._sql(LEFT_SQL), {"version": self.version}
        )
        if int(left[0]["left_reviews"]):
            raise TopicBackfillError(
                f"{left[0]['left_reviews']} negatives still without topic"
            )


def run_topics_backfill(
    settings: InferenceSettings,
    bigquery: Any,
    storage: Any,
    version: str,
    now: datetime,
    *,
    engines: EngineLoaders | None = None,
    run_id: str | None = None,
) -> InferenceRun:
    """Corre el backfill de ``version`` y registra la corrida."""
    run_id = run_id or f"topics-backfill-{version}-{now:%Y%m%dT%H%M%S}"
    writer = StagingMergeWriter(bigquery, settings.dataset)
    job = TopicsBackfill(
        settings,
        bigquery,
        storage,
        writer,
        version,
        run_id,
        now,
        engines or EngineLoaders(),
    )
    status = RunStatus.FAILED
    try:
        job.embed_missing()
        job.assign()
        job.verify()
        status = RunStatus.SUCCEEDED
    finally:
        run = InferenceRun(
            run_id=run_id,
            kind=RunKind.TOPIC_BACKFILL,
            environment=RunEnvironment.CLOUDRUN,
            model_version=None,
            started_at=now,
            ended_at=max(datetime.now(UTC), now),
            reviews=job.reviews,
            texts=job.texts,
            status=status,
            peak_memory_mib=peak_memory_mib(),
        )
        writer.write("inference_runs", [run], ["run_id"], run_id)
        log.info(
            "topics-backfill %s: %s, %d reseñas, %d textos",
            version,
            status.value,
            job.reviews,
            job.texts,
        )
    return run
