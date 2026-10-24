"""Re-ajuste trimestral del modelo de tópicos (Job ``voc-ml-topics-refit``).

Corre cuando la ``risk_policy`` vigente pide ``topic_refit_frequency =
quarterly`` y no hay una versión ajustada en el trimestre en curso (o con
``--force``). No usa Gemini ni sale de GCP.

1. **Muestra** (decisión del autor, 2026-10-24): textos únicos que el modelo
   predijo ``NEG`` con dos palabras o más en los 12 meses cerrados más
   recientes, hasta ``SAMPLE_TEXTS`` con la misma cuota por banco (los bancos
   chicos no quedan tapados). El sorteo es reproducible
   (``FARM_FINGERPRINT`` de ``<semilla>:<text_key>``) y se hace en BigQuery:
   del TDS solo salen los textos elegidos.
2. **Ajuste:** cláusulas (``voc_nlp.topics.segment``), MiniLM y
   ``voc_nlp.topics_refit.refit`` con los parámetros de ``topics_v1``.
3. **Emparejamiento:** las mismas cláusulas se asignan con la versión
   vigente y cada tópico nuevo se empareja con el anterior de centroide más
   parecido, sin umbral (``previous_topic_id`` y ``centroid_similarity`` en
   ``topic_catalog``).
4. **Escritura:** artefactos en ``ml_artifacts/topics/<versión>/``, luego el
   catálogo y al final la fila de ``topic_model_versions``. La versión no
   asigna hasta que el curador decide cada tópico en ``curation_topics``
   (vista ``topic_model_current``).
"""

import json
import logging
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
from voc_common.policies import RiskPolicy
from voc_common.predictions_v3 import TopicCatalogEntry, TopicModelVersion
from voc_nlp.topics_refit import (
    DEFAULT_PARAMS,
    TopicParams,
    centroids,
    match,
    refit,
    save_topic_model,
    topic_terms,
)

from ml_inference import artifacts
from ml_inference.bq_io import StagingMergeWriter, query_rows, render
from ml_inference.config import InferenceSettings
from ml_inference.engines import EngineLoaders

log = logging.getLogger(__name__)

SAMPLE_TEXTS: Final = 40_000
WINDOW_MONTHS: Final = 12
MIN_TEXTS: Final = 1_000
SAMPLE_SEED: Final = "topics_refit"

SAMPLE_SQL: Final = """
WITH texts AS (
  SELECT text_key, ANY_VALUE(bank_id) AS bank_id
  FROM `${ds}.review_predictions_current`
  WHERE sentiment = 'NEG' AND palabras >= 2
    AND fecha >= @start AND fecha < @end
  GROUP BY text_key
),
ranked AS (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY bank_id
      ORDER BY FARM_FINGERPRINT(CONCAT(@seed, ':', text_key)), text_key
    ) AS rn,
    DIV(@total, COUNT(DISTINCT bank_id) OVER ()) AS quota
  FROM texts
)
SELECT r.text_key, r.bank_id, ANY_VALUE(t.texto_sanitizado) AS texto
FROM ranked AS r
JOIN `${tds}` AS t ON TO_HEX(SHA256(t.texto_sanitizado)) = r.text_key
WHERE r.rn <= r.quota
GROUP BY r.text_key, r.bank_id
ORDER BY r.text_key
"""

VERSIONS_SQL: Final = """
SELECT topic_model_version, fitted_at FROM `${ds}.topic_model_versions`
ORDER BY fitted_at DESC
"""


@dataclass(frozen=True)
class Units:
    """Cláusulas de la muestra, en orden (sin guardar el texto)."""

    keys: list[str]
    segments: list[str]
    texts: int


def quarter_start(now: datetime) -> datetime:
    day = now.astimezone(UTC)
    return datetime(day.year, 3 * ((day.month - 1) // 3) + 1, 1, tzinfo=UTC)


def window(now: datetime) -> tuple[datetime, datetime]:
    """Los ``WINDOW_MONTHS`` meses cerrados antes del mes en curso."""
    day = now.astimezone(UTC)
    end = datetime(day.year, day.month, 1, tzinfo=UTC)
    months = day.year * 12 + day.month - 1 - WINDOW_MONTHS
    return datetime(months // 12, months % 12 + 1, 1, tzinfo=UTC), end


def next_version(latest: str | None) -> str:
    """``topics_v1`` → ``topics_v2``; ``topics_v1`` si no hay ninguna."""
    if latest is None:
        return "topics_v1"
    found = re.fullmatch(r"(.*_v)(\d+)", latest)
    if found is None:
        return f"{latest}_v2"
    return f"{found[1]}{int(found[2]) + 1}"


def is_due(
    policy: RiskPolicy | None,
    latest_fit: datetime | None,
    now: datetime,
) -> bool:
    if policy is None or policy.topic_refit_frequency != "quarterly":
        log.warning(
            "topics-refit: frecuencia %r no soportada",
            None if policy is None else policy.topic_refit_frequency,
        )
        return False
    return latest_fit is None or latest_fit < quarter_start(now)


def units_of(rows: Sequence[Mapping[str, Any]]) -> Units:
    from voc_nlp.topics import segment

    keys, segments = [], []
    for r in rows:
        for part in segment(r["texto"]):
            keys.append(r["text_key"])
            segments.append(part)
    return Units(keys, segments, len(rows))


def catalog(
    version: str,
    terms: Mapping[int, list[str]],
    pairs: Mapping[int, tuple[int, float]],
) -> list[TopicCatalogEntry]:
    return [
        TopicCatalogEntry(
            topic_model_version=version,
            topic_id=topic,
            terms=words,
            previous_topic_id=pairs[topic][0] if topic in pairs else None,
            centroid_similarity=pairs[topic][1] if topic in pairs else None,
        )
        for topic, words in sorted(terms.items())
    ]


@dataclass
class TopicsRefit:
    settings: InferenceSettings
    bigquery: Any
    storage: Any
    writer: StagingMergeWriter
    engines: EngineLoaders = field(default_factory=EngineLoaders)
    params: TopicParams = DEFAULT_PARAMS
    fit: Callable[..., Any] = refit
    sample_texts: int = SAMPLE_TEXTS
    min_texts: int = MIN_TEXTS

    def _rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        return query_rows(
            self.bigquery,
            render(sql, ds=self.settings.dataset, tds=self.settings.tds_table),
            params,
        )

    def _download(self, kind: str, name: str, dest: Path) -> Path:
        prefix = artifacts.artifact_prefix(
            self.settings.ml_artifacts_prefix, kind, name
        )
        return artifacts.download_prefix(
            self.storage, self.settings.gcs_raw_datalake_bucket, prefix, dest
        )

    def run(
        self,
        policy: RiskPolicy | None,
        current: str | None,
        now: datetime,
        force: bool = False,
    ) -> str | None:
        """Ajusta y registra una versión nueva; ``None`` si no toca."""
        versions = self._rows(VERSIONS_SQL)
        latest = versions[0] if versions else None
        latest_fit = latest["fitted_at"] if latest else None
        if isinstance(latest_fit, str):
            latest_fit = datetime.fromisoformat(
                latest_fit.replace("Z", "+00:00")
            )
        if not force and not is_due(policy, latest_fit, now):
            log.info("topics-refit: ya hay versión del trimestre")
            return None
        start, end = window(now)
        rows = self._rows(
            SAMPLE_SQL,
            start=start,
            end=end,
            seed=SAMPLE_SEED,
            total=self.sample_texts,
        )
        if len(rows) < self.min_texts:
            log.warning("topics-refit: %d textos, muy pocos", len(rows))
            return None
        version = next_version(
            latest["topic_model_version"] if latest else None
        )
        work = Path(tempfile.mkdtemp(prefix="topics-refit-"))
        try:
            return self._fit(rows, version, current, start, end, now, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _fit(
        self,
        rows: Sequence[Mapping[str, Any]],
        version: str,
        current: str | None,
        start: datetime,
        end: datetime,
        now: datetime,
        work: Path,
    ) -> str:
        from voc_nlp.topics import EMBEDDING_MODEL, SEGMENTER

        units = units_of(rows)
        name = EMBEDDING_MODEL.rsplit("/", 1)[-1]
        embedder = self.engines.embedder(
            self._download(artifacts.EMBEDDINGS, name, work / "minilm")
        )
        emb = np.asarray(embedder.embed(units.segments))
        del embedder
        model, topics = self.fit(units.segments, emb, self.params)
        terms = topic_terms(model, self.params.top_n_words)
        if not terms:
            raise RuntimeError("the refit found no topics")
        pairs: dict[int, tuple[int, float]] = {}
        if current is not None:
            previous = self.engines.topics(
                self._download(artifacts.TOPICS, current, work / "previous")
            )
            old = previous.assign(units.segments, emb)
            pairs = {
                m.topic_id: (m.previous_topic_id, round(m.similarity, 4))
                for m in match(centroids(emb, old), centroids(emb, topics))
            }
        noise = float(np.mean(np.asarray(topics) == -1))
        meta = {
            **self.params.as_dict(),
            "topicos": len(terms),
            "segmentos_ajuste": len(units.segments),
            "textos_ajuste": units.texts,
            "ruido": round(noise, 4),
            "anterior": current,
        }
        folder = save_topic_model(model, work / "model")
        (folder / "model.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n"
        )
        artifacts.upload_dir(
            self.storage,
            self.settings.gcs_raw_datalake_bucket,
            folder,
            artifacts.artifact_prefix(
                self.settings.ml_artifacts_prefix, artifacts.TOPICS, version
            ),
        )
        run_id = f"topics-refit-{version}"
        self.writer.write(
            "topic_catalog",
            catalog(version, terms, pairs),
            ["topic_model_version", "topic_id"],
            run_id,
        )
        # Al final: una versión sin catálogo nunca se activa a medias.
        self.writer.write(
            "topic_model_versions",
            [
                TopicModelVersion(
                    topic_model_version=version,
                    fitted_at=now,
                    embedding_model=EMBEDDING_MODEL,
                    segmenter=SEGMENTER,
                    params=meta,
                    fit_sample=(
                        f"{units.texts} textos NEG únicos de "
                        f"{start:%Y-%m} a {end:%Y-%m} (excluido), igual por "
                        f"banco, semilla {SAMPLE_SEED!r}; "
                        f"{len(units.segments)} cláusulas"
                    ),
                )
            ],
            ["topic_model_version"],
            run_id,
        )
        log.info(
            "topics-refit: %s con %d tópicos (%d emparejados), ruido %.1f %%",
            version,
            len(terms),
            len(pairs),
            100 * noise,
        )
        return version
