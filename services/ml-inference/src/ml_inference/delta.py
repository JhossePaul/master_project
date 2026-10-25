"""Delta diario: un Job con pasos en serie y un modelo en memoria a la vez.

1. **Pendientes:** filas del TDS sin fila en ``review_predictions`` para la
   versión promovida y su ``text_key``, hasta el tope por corrida.
2. **Sentimiento:** elegibilidad v1; RoBERTuito una vez por texto único
   ``MODEL``; T de la versión; umbral de la política o de la subida del banco.
3. **HITL:** casos ``low_confidence`` (o ``drift_boost``) con su oclusión
   precalculada, hasta el tope semanal de la política.
4. **Familias:** negativas de dos palabras o más sin ninguna fila en
   ``review_aspects``, con cualquier prompt. Un texto que ya tiene familias
   (de cualquier prompt) se copia con su ``prompt_version``; Gemini solo
   etiqueta los textos que nunca etiquetó, con el prompt vigente. Un cambio
   de prompt no re-etiqueta el histórico: eso lo hace ``aspects-backfill``,
   solo con el costo aprobado.
5. **Embeddings y tópicos:** MiniLM por texto, una fila por banco × mes, y
   cláusulas con el modelo de tópicos vigente, solo de las reseñas que
   predijo una corrida del delta (lo que llegó por la ingesta diaria). Los
   vectores de las cláusulas se guardan una vez en ``segment_embeddings`` y
   se reutilizan. Si quedan negativas del histórico sin asignar a la
   versión vigente y no hay un backfill en curso, lanza
   ``voc-ml-topics-backfill``.
6. **Registro:** fila en ``inference_runs``.

Cada modelo se carga solo si su paso tiene trabajo y se libera antes del
siguiente. Un texto que Gemini no etiqueta queda pendiente para mañana.
"""

import gc
import logging
import resource
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import numpy as np
from voc_common.analytics_codes import (
    DisplayMode,
    ExplanationSource,
    HitlReason,
    HitlStatus,
    HitlTask,
    LabelSource,
    RunEnvironment,
    RunKind,
    RunStatus,
    SentimentValue,
)
from voc_common.hitl_v3 import HitlEvent, HitlItem
from voc_common.operations_v3 import InferenceRun, ReviewExplanation
from voc_common.predictions_v3 import (
    ReviewAspects,
    ReviewPrediction,
    SegmentEmbedding,
    TextEmbedding,
    TopicAssignment,
)
from voc_nlp.calibration import apply_temperature
from voc_nlp.eligibility import RULES_VERSION, tnss_rule
from voc_nlp.hitl import requires_hitl, threshold_for
from voc_nlp.lexicon import Lexicon, load_lexicon

from ml_inference import artifacts
from ml_inference.bq_io import StagingMergeWriter, query_rows, render
from ml_inference.config import InferenceSettings
from ml_inference.engines import EngineLoaders
from ml_inference.jobs import JobRunner
from ml_inference.state import ServingState, load_state

log = logging.getLogger(__name__)

CLASSES: Final = (SentimentValue.NEG, SentimentValue.NEU, SentimentValue.POS)


@dataclass
class Clients:
    bigquery: Any
    storage: Any
    genai: Any | None = None
    engines: EngineLoaders = field(default_factory=EngineLoaders)
    # Sin él, el backfill de tópicos no se lanza (se avisa en el log).
    jobs: JobRunner | None = None


@dataclass
class _Counts:
    reviews: int = 0
    texts: int = 0
    hitl_items: int = 0
    aspects: int = 0
    embeddings: int = 0
    topics: int = 0
    cost_usd: float = 0.0


def run_delta(
    settings: InferenceSettings,
    clients: Clients,
    now: datetime,
    *,
    lexicon: Lexicon | None = None,
    run_id: str | None = None,
) -> InferenceRun:
    """Corre el delta completo y registra la corrida, también si falla."""
    run_id = run_id or f"delta-{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    writer = StagingMergeWriter(clients.bigquery, settings.dataset)
    state = load_state(clients.bigquery, settings.dataset)
    counts = _Counts()
    status = RunStatus.FAILED
    try:
        step = _Steps(settings, clients, writer, state, now, run_id)
        step.sentiment(lexicon or load_lexicon(), counts)
        step.aspects(counts)
        step.embeddings(counts)
        step.topics(counts)
        status = RunStatus.SUCCEEDED
    finally:
        run = InferenceRun(
            run_id=run_id,
            kind=RunKind.DELTA,
            environment=RunEnvironment.CLOUDRUN,
            model_version=state.model.model_version,
            started_at=now,
            ended_at=max(datetime.now(UTC), now),
            reviews=counts.reviews,
            texts=counts.texts,
            status=status,
            cost_usd=round(counts.cost_usd, 6),
            peak_memory_mib=peak_memory_mib(),
        )
        writer.write("inference_runs", [run], ["run_id"], run_id)
        log.info("delta %s: %s", status.value, counts)
    return run


def peak_memory_mib() -> int:
    """Memoria residente pico del proceso (KiB en Linux, bytes en macOS)."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(
        peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024
    )


@dataclass
class _Steps:
    settings: InferenceSettings
    clients: Clients
    writer: StagingMergeWriter
    state: ServingState
    now: datetime
    run_id: str

    @property
    def ds(self) -> str:
        return self.settings.dataset

    @property
    def tds(self) -> str:
        return self.settings.tds_table

    def _rows(self, template: str, **params: Any) -> list[dict[str, Any]]:
        sql = render(template, ds=self.ds, tds=self.tds)
        return query_rows(self.clients.bigquery, sql, params)

    def _download(self, kind: str, name: str) -> Path:
        prefix = artifacts.artifact_prefix(
            self.settings.ml_artifacts_prefix, kind, name
        )
        dest = self.settings.artifacts_dir / kind / name
        if not dest.exists():
            artifacts.download_prefix(
                self.clients.storage,
                self.settings.gcs_raw_datalake_bucket,
                prefix,
                dest,
            )
        return dest

    # -- 1 a 3: pendientes, sentimiento y HITL ------------------------------

    def sentiment(self, lexicon: Lexicon, counts: _Counts) -> None:
        model = self.state.model
        pending = self._rows(
            """
            SELECT t.id_resena, t.bank_id, t.fecha, t.version_app,
              t.estrellas, t.texto_limpio, t.texto_sanitizado,
              TO_HEX(SHA256(t.texto_sanitizado)) AS text_key
            FROM `${tds}` AS t
            LEFT JOIN `${ds}.review_predictions` AS p
              ON p.id_resena = t.id_resena
              AND p.model_version = @model_version
              AND p.text_key = TO_HEX(SHA256(t.texto_sanitizado))
            WHERE p.id_resena IS NULL
            ORDER BY t.fecha
            LIMIT @limit
            """,
            model_version=model.model_version,
            limit=self.settings.max_reviews_per_run,
        )
        counts.reviews = len(pending)
        if not pending:
            return
        decisions = [
            tnss_rule(r["texto_limpio"], r["fecha"], r["bank_id"], lexicon)
            for r in pending
        ]
        texts = {
            r["text_key"]: r["texto_sanitizado"]
            for r, d in zip(pending, decisions, strict=True)
            if d.source is LabelSource.MODEL
        }
        counts.texts = len(texts)
        proba: dict[str, np.ndarray] = {}
        engine = None
        if texts:
            weights = self._download(artifacts.SENTIMENT, model.model_version)
            engine = self.clients.engines.sentiment(
                weights,
                self.settings.sentiment_batch_size,
                self.settings.torch_threads,
            )
            keys = list(texts)
            raw = engine.predict([texts[k] for k in keys])
            calibrated = apply_temperature(raw, model.calibration_t)
            proba = dict(zip(keys, calibrated, strict=True))
        rows = [
            self._prediction(r, d, proba.get(r["text_key"]))
            for r, d in zip(pending, decisions, strict=True)
        ]
        self.writer.write(
            "review_predictions",
            rows,
            ["id_resena", "model_version", "text_key"],
            self.run_id,
        )
        texts_by_key = {r["text_key"]: r["texto_sanitizado"] for r in pending}
        counts.hitl_items = self._hitl(rows, texts_by_key, engine)
        del engine
        gc.collect()

    def _prediction(
        self, row: dict[str, Any], decision: Any, proba: np.ndarray | None
    ) -> ReviewPrediction:
        model = self.state.model
        common = {
            "id_resena": row["id_resena"],
            "bank_id": row["bank_id"],
            "text_key": row["text_key"],
            "fecha": row["fecha"],
            "version_app": row["version_app"],
            "estrellas": row["estrellas"],
            "palabras": decision.palabras,
            "eligibility_rules_version": RULES_VERSION,
            "eligibility_code": decision.code,
            "label_source": decision.source,
            "model_version": model.model_version,
            "calibration_version": model.calibration_version,
            "run_id": self.run_id,
            "predicted_at": self.now,
        }
        if decision.source is LabelSource.NO_PREDICTED:
            return ReviewPrediction(
                **common,
                sentiment=SentimentValue.NO_PREDICTED,
                requires_hitl=False,
            )
        if decision.source is LabelSource.RULE_BASED:
            return ReviewPrediction(
                **common,
                sentiment=SentimentValue(decision.label.value),
                requires_hitl=False,
            )
        if proba is None:
            raise RuntimeError("MODEL row without prediction")
        p = [float(x) for x in proba]
        confidence = max(p)
        policy = self.state.policy_for_model
        boost = self.state.boosts.get(row["bank_id"]) if policy else None
        flagged = False
        if policy is not None:
            curve = self.state.curve
            threshold = (
                threshold_for(policy, boost, curve)
                if curve is not None
                else policy.hitl_threshold
            )
            flagged = requires_hitl(confidence, threshold)
        return ReviewPrediction(
            **common,
            sentiment=CLASSES[int(np.argmax(p))],
            p_neg=p[0],
            p_neu=p[1],
            p_pos=p[2],
            confidence=confidence,
            risk_policy_version=policy.policy_version if policy else None,
            hitl_boost_id=boost.boost_id if boost and flagged else None,
            requires_hitl=flagged,
        )

    def _week_count(self, bank_id: str | None = None) -> int:
        week_start = (self.now - timedelta(days=self.now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        sql = (
            "SELECT COUNT(*) AS n FROM `${ds}.hitl_items` "
            "WHERE created_at >= @week_start "
            "AND reason IN ('low_confidence', 'drift_boost')"
        )
        params: dict[str, Any] = {"week_start": week_start}
        if bank_id is not None:
            sql += " AND bank_id = @bank AND reason = 'drift_boost'"
            params["bank"] = bank_id
        return int(self._rows(sql, **params)[0]["n"])

    def _hitl(
        self,
        rows: Sequence[ReviewPrediction],
        texts: dict[str, str],
        engine: Any,
    ) -> int:
        flagged = sorted(
            (r for r in rows if r.requires_hitl),
            key=lambda r: r.confidence or 0.0,
        )
        policy = self.state.policy_for_model
        if not flagged or policy is None:
            return 0
        room = (
            None
            if policy.hitl_weekly_cap is None
            else max(policy.hitl_weekly_cap - self._week_count(), 0)
        )
        boost_room: dict[str, int] = {}
        items: list[HitlItem] = []
        for r in flagged:
            boost = (
                self.state.boosts.get(r.bank_id) if r.hitl_boost_id else None
            )
            if boost is not None:
                left = boost_room.setdefault(
                    r.bank_id,
                    max(boost.weekly_cap - self._week_count(r.bank_id), 0),
                )
                if left == 0:
                    continue
                boost_room[r.bank_id] = left - 1
            elif room is not None:
                if room == 0:
                    continue
                room -= 1
            items.append(self._item(r, boost.boost_id if boost else None))
        if not items:
            return 0
        added = self.writer.write("hitl_items", items, ["item_id"], self.run_id)
        events = [
            HitlEvent(
                event_id=f"{i.item_id}:queued",
                item_id=i.item_id,
                status=HitlStatus.QUEUED,
                at=self.now,
            )
            for i in items
        ]
        self.writer.write("hitl_events", events, ["event_id"], self.run_id)
        if engine is not None:
            wanted = {i.id_resena for i in items}
            keys = {r.text_key for r in flagged if r.id_resena in wanted}
            explanations = [
                ReviewExplanation(
                    text_key=key,
                    model_version=self.state.model.model_version,
                    method="occlusion_v1",
                    attributions=engine.explain(texts[key]),
                    source=ExplanationSource.PRECOMPUTED_HITL,
                    computed_at=self.now,
                )
                for key in sorted(keys)
            ]
            self.writer.write(
                "review_explanations",
                explanations,
                ["text_key", "model_version", "method"],
                self.run_id,
            )
        return added

    def _item(self, r: ReviewPrediction, boost_id: str | None) -> HitlItem:
        return HitlItem(
            item_id=f"sentiment:{r.id_resena}:{r.text_key[:16]}:{r.model_version}",
            id_resena=r.id_resena,
            bank_id=r.bank_id,
            task=HitlTask.SENTIMENT,
            reason=HitlReason.DRIFT_BOOST
            if boost_id
            else HitlReason.LOW_CONFIDENCE,
            boost_id=boost_id,
            display_mode=DisplayMode.ASSISTED,
            model_version=r.model_version,
            risk_policy_version=r.risk_policy_version,
            predicted={
                "label": r.sentiment.value if r.sentiment else None,
                "p_neg": r.p_neg,
                "p_neu": r.p_neu,
                "p_pos": r.p_pos,
            },
            # Menor confianza primero (la familia aún no se conoce).
            priority=round(1.0 - (r.confidence or 0.0), 6),
            created_at=self.now,
        )

    # -- 4: familias -------------------------------------------------------

    def aspects(self, counts: _Counts) -> None:
        from voc_nlp import aspects as gemini

        if self.clients.genai is None:
            log.warning("sin cliente de Gemini: las familias quedan pendientes")
            return
        pending = self._rows(
            """
            SELECT p.id_resena, p.bank_id, p.text_key, p.fecha,
              p.model_version, t.texto_sanitizado
            FROM `${ds}.review_predictions_current` AS p
            JOIN `${tds}` AS t
              ON t.id_resena = p.id_resena
              AND TO_HEX(SHA256(t.texto_sanitizado)) = p.text_key
            -- Sin ninguna fila, con cualquier prompt.
            LEFT JOIN `${ds}.review_aspects` AS a
              ON a.id_resena = p.id_resena AND a.text_key = p.text_key
            WHERE p.sentiment = 'NEG' AND p.palabras >= 2
              AND a.id_resena IS NULL
            -- Las más recientes primero si hay más que el tope.
            ORDER BY p.fecha DESC
            LIMIT @limit
            """,
            limit=self.settings.max_reviews_per_run,
        )
        if not pending:
            return
        keys = sorted({r["text_key"] for r in pending})
        # La etiqueta más reciente de cada texto, con el prompt que tenga.
        known = {
            r["text_key"]: r
            for r in self._rows(
                """
                SELECT text_key, families, flag_update, flag_security,
                  praise, llm_model, prompt_version, guideline_version
                FROM `${ds}.review_aspects`
                WHERE text_key IN UNNEST(@keys)
                QUALIFY ROW_NUMBER() OVER
                  (PARTITION BY text_key ORDER BY labeled_at DESC) = 1
                """,
                keys=keys,
            )
        }
        texts = {r["text_key"]: r["texto_sanitizado"] for r in pending}
        unknown = [(k, texts[k]) for k in keys if k not in known]
        usage = gemini.Usage()
        prompt = gemini.load_prompt()
        size = self.settings.aspects_batch_size
        for start in range(0, len(unknown), size):
            for label in gemini.label_batch(
                self.clients.genai,
                unknown[start : start + size],
                prompt,
                self.settings.gemini_model,
                usage=usage,
            ):
                known[label.key] = {
                    "families": [f.value for f in label.families],
                    "flag_update": label.flag_update,
                    "flag_security": label.flag_security,
                    "praise": label.praise,
                    "llm_model": self.settings.gemini_model,
                    "prompt_version": gemini.PROMPT_VERSION,
                    "guideline_version": gemini.GUIDELINE_VERSION,
                }
        counts.cost_usd += usage.cost_usd
        rows = [
            ReviewAspects(
                id_resena=r["id_resena"],
                bank_id=r["bank_id"],
                text_key=r["text_key"],
                fecha=r["fecha"],
                families=known[r["text_key"]]["families"],
                flag_update=known[r["text_key"]]["flag_update"],
                flag_security=known[r["text_key"]]["flag_security"],
                praise=known[r["text_key"]]["praise"],
                prompt_version=known[r["text_key"]]["prompt_version"],
                llm_model=known[r["text_key"]]["llm_model"],
                guideline_version=known[r["text_key"]]["guideline_version"],
                sentiment_model_version=r["model_version"],
                run_id=self.run_id,
                labeled_at=self.now,
            )
            for r in pending
            if r["text_key"] in known
        ]
        counts.aspects = self.writer.write(
            "review_aspects",
            rows,
            ["id_resena", "text_key", "prompt_version"],
            self.run_id,
        )

    # -- 5: embeddings y tópicos -------------------------------------------

    def _embedder(self) -> Any:
        from voc_nlp.topics import EMBEDDING_MODEL

        name = EMBEDDING_MODEL.rsplit("/", 1)[-1]
        return self.clients.engines.embedder(
            self._download(artifacts.EMBEDDINGS, name)
        )

    def embeddings(self, counts: _Counts) -> None:
        from voc_nlp.topics import EMBEDDING_MODEL

        pending = self._rows(
            """
            SELECT DISTINCT TO_HEX(SHA256(t.texto_sanitizado)) AS text_key,
              t.bank_id, DATE_TRUNC(DATE(t.fecha), MONTH) AS mes,
              t.texto_sanitizado
            FROM `${tds}` AS t
            LEFT JOIN `${ds}.text_embeddings` AS e
              ON e.text_key = TO_HEX(SHA256(t.texto_sanitizado))
              AND e.bank_id = t.bank_id
              AND e.mes = DATE_TRUNC(DATE(t.fecha), MONTH)
            WHERE e.text_key IS NULL
              AND TRIM(COALESCE(t.texto_sanitizado, '')) != ''
            LIMIT @limit
            """,
            limit=self.settings.max_reviews_per_run,
        )
        if not pending:
            return
        keys = sorted({r["text_key"] for r in pending})
        vectors = {
            r["text_key"]: r["embedding"]
            for r in self._rows(
                """
                SELECT text_key, ANY_VALUE(embedding) AS embedding
                FROM `${ds}.text_embeddings`
                WHERE text_key IN UNNEST(@keys) GROUP BY text_key
                """,
                keys=keys,
            )
        }
        texts = {r["text_key"]: r["texto_sanitizado"] for r in pending}
        new = [k for k in keys if k not in vectors]
        if new:
            embedder = self._embedder()
            for key, vec in zip(
                new, embedder.embed([texts[k] for k in new]), strict=True
            ):
                vectors[key] = [float(x) for x in vec]
            del embedder
            gc.collect()
        rows = [
            TextEmbedding(
                text_key=r["text_key"],
                bank_id=r["bank_id"],
                mes=r["mes"],
                embedding=vectors[r["text_key"]],
                embedding_model=EMBEDDING_MODEL,
                created_at=self.now,
            )
            for r in pending
        ]
        counts.embeddings = self.writer.write(
            "text_embeddings", rows, ["text_key", "bank_id", "mes"], self.run_id
        )

    def topics(self, counts: _Counts) -> None:
        version = self.state.topic_model_version
        if version is None:
            log.warning("sin modelo de tópicos: los tópicos quedan pendientes")
            return
        pending = self._rows(
            """
            SELECT p.id_resena, p.bank_id, p.text_key, p.fecha,
              t.texto_sanitizado
            FROM `${ds}.review_predictions_current` AS p
            JOIN `${tds}` AS t
              ON t.id_resena = p.id_resena
              AND TO_HEX(SHA256(t.texto_sanitizado)) = p.text_key
            LEFT JOIN `${ds}.topic_assignments` AS a
              ON a.id_resena = p.id_resena AND a.text_key = p.text_key
              AND a.topic_model_version = @version
            WHERE p.sentiment = 'NEG' AND p.palabras >= 2
              AND a.id_resena IS NULL
              -- Solo lo que llegó por la ingesta: el histórico lo re-asigna
              -- el backfill de tópicos.
              AND (p.run_id = @run_id OR p.run_id IN (
                SELECT run_id FROM `${ds}.inference_runs`
                WHERE kind = 'delta'))
            ORDER BY p.fecha DESC
            LIMIT @limit
            """,
            version=version,
            run_id=self.run_id,
            limit=self.settings.max_reviews_per_run,
        )
        if pending:
            self._assign_topics(version, pending, counts)
        self._launch_topic_backfill(version)

    def _segment_vectors(
        self, texts: dict[str, str]
    ) -> tuple[list[tuple[str, str]], np.ndarray]:
        """Cláusulas de cada texto con su vector; calcula y guarda los que
        faltan en ``segment_embeddings``."""
        from voc_nlp.topics import EMBEDDING_MODEL, SEGMENTER, segment

        segments = {key: segment(text) for key, text in texts.items()}
        stored: dict[str, dict[int, list[float]]] = {}
        for r in self._rows(
            """
            SELECT text_key, segment_index, embedding
            FROM `${ds}.segment_embeddings`
            WHERE text_key IN UNNEST(@keys)
            """,
            keys=sorted(texts),
        ):
            stored.setdefault(r["text_key"], {})[r["segment_index"]] = r[
                "embedding"
            ]
        # Un texto con otro número de cláusulas guardadas se vuelve a embeber.
        missing = [
            (k, i, s)
            for k, parts in segments.items()
            if len(stored.get(k, {})) != len(parts)
            for i, s in enumerate(parts)
        ]
        if missing:
            embedder = self._embedder()
            vectors = embedder.embed([s for _, _, s in missing])
            del embedder
            gc.collect()
            rows = []
            for (key, i, _), vec in zip(missing, vectors, strict=True):
                stored.setdefault(key, {})[i] = [float(x) for x in vec]
                rows.append(
                    SegmentEmbedding(
                        text_key=key,
                        segment_index=i,
                        segmenter=SEGMENTER,
                        embedding_model=EMBEDDING_MODEL,
                        embedding=stored[key][i],
                        run_id=self.run_id,
                        created_at=self.now,
                    )
                )
            self.writer.write(
                "segment_embeddings",
                rows,
                ["text_key", "segment_index"],
                self.run_id,
            )
        flat = [(k, s) for k, parts in segments.items() for s in parts]
        emb = np.array(
            [
                stored[k][i]
                for k, parts in segments.items()
                for i in range(len(parts))
            ],
            dtype=np.float32,
        )
        return flat, emb

    def _assign_topics(
        self, version: str, pending: list[dict[str, Any]], counts: _Counts
    ) -> None:
        texts = {r["text_key"]: r["texto_sanitizado"] for r in pending}
        flat, emb = self._segment_vectors(texts)
        assigner = self.clients.engines.topics(
            self._download(artifacts.TOPICS, version)
        )
        assigned = assigner.assign([s for _, s in flat], emb)
        del assigner
        gc.collect()
        by_key: dict[str, list[int]] = {}
        for (key, _), topic in zip(flat, assigned, strict=True):
            by_key.setdefault(key, []).append(int(topic))
        rows = [
            TopicAssignment(
                id_resena=r["id_resena"],
                bank_id=r["bank_id"],
                text_key=r["text_key"],
                fecha=r["fecha"],
                segment_index=i,
                topic_model_version=version,
                topic_id=topic,
            )
            for r in pending
            for i, topic in enumerate(by_key[r["text_key"]])
        ]
        counts.topics = self.writer.write(
            "topic_assignments",
            rows,
            ["id_resena", "text_key", "topic_model_version", "segment_index"],
            self.run_id,
        )

    def _launch_topic_backfill(self, version: str) -> None:
        """Lanza el backfill si quedan negativas sin asignar a ``version``."""
        left = int(
            self._rows(
                """
                SELECT COUNT(*) AS unassigned
                FROM `${ds}.review_predictions_current` AS p
                LEFT JOIN `${ds}.topic_assignments` AS a
                  ON a.id_resena = p.id_resena AND a.text_key = p.text_key
                  AND a.topic_model_version = @version
                WHERE p.sentiment = 'NEG' AND p.palabras >= 2
                  AND a.id_resena IS NULL
                """,
                version=version,
            )[0]["unassigned"]
        )
        if not left:
            return
        job = self.settings.topics_backfill_job
        jobs = self.clients.jobs
        if jobs is None:
            log.warning(
                "%d negativas sin tópico de %s: sin lanzador de Jobs",
                left,
                version,
            )
            return
        if jobs.running(job):
            log.info(
                "%d negativas sin tópico de %s: %s en curso", left, version, job
            )
            return
        operation = jobs.execute(job, ["topics-backfill"])
        log.info(
            "%d negativas sin tópico de %s: lanzado %s (%s)",
            left,
            version,
            job,
            operation,
        )
