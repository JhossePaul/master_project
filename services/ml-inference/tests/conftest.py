"""BigQuery, GCS, Gemini y modelos falsos para probar el delta sin red."""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from ml_inference.config import InferenceSettings
from ml_inference.delta import Clients
from ml_inference.engines import EngineLoaders
from voc_common.constants import SentimentLabel
from voc_common.operations_v3 import TokenAttribution
from voc_nlp.lexicon import Lexicon

PROJECT = "test-project"
DATASET = f"{PROJECT}.bbva_voc_tds"
ACTOR = "b" * 64
MODEL = "robertuito_sentiment_v1"
NOW = datetime(2026, 11, 4, 9, 30, tzinfo=UTC)
LEXICON = Lexicon("lexicon_v1", {"excelente": SentimentLabel.POS})


def text_key(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()


@dataclass
class FakeJob:
    rows: list[dict[str, Any]] = field(default_factory=list)
    num_dml_affected_rows: int = 0
    errors: Any = None
    job_id: str = "job"

    def result(
        self, timeout: float | None = None, page_size: int | None = None
    ) -> list[Any]:
        return [_Row(r) for r in self.rows]


class _Row(dict):
    pass


def _name(table: Any) -> str:
    raw = table if isinstance(table, str) else str(table.reference)
    return raw.rsplit(".", 1)[-1]


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


class FakeBigQuery:
    """Tablas en memoria y las consultas del delta, reconocidas por texto."""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.staging: dict[str, list[dict[str, Any]]] = {}
        self.deleted: list[str] = []
        self.fail_merge = False
        self.queries: list[str] = []

    def rows(self, table: str) -> list[dict[str, Any]]:
        return self.tables.setdefault(table, [])

    # -- API usada por StagingMergeWriter -----------------------------------

    def create_table(self, table: Any, timeout: float | None = None) -> None:
        self.staging[_name(table)] = []

    def load_table_from_json(self, rows: list, dest: str, **_: Any) -> FakeJob:
        self.staging[_name(dest)] = list(rows)
        return FakeJob()

    def delete_table(self, table: str, **_: Any) -> None:
        self.deleted.append(_name(table))
        self.staging.pop(_name(table), None)

    def query(self, sql: str, job_config: Any = None, **_: Any) -> FakeJob:
        self.queries.append(sql)
        params = {
            p.name: getattr(p, "value", getattr(p, "values", None))
            for p in getattr(job_config, "query_parameters", []) or []
        }
        if sql.startswith("MERGE"):
            return self._merge(sql)
        return FakeJob(self._select(sql, params))

    def _merge(self, sql: str) -> FakeJob:
        if self.fail_merge:
            from google.api_core.exceptions import InternalServerError

            raise InternalServerError("merge failed")
        target, staging = re.findall(r"`([^`]+)`", sql)[:2]
        key = list(dict.fromkeys(re.findall(r"T\.`?(\w+)`? = S\.`?\w+`?", sql)))
        rows = self.rows(_name(target))
        seen = {tuple(str(r[k]) for k in key) for r in rows}
        added = 0
        for row in self.staging[_name(staging)]:
            k = tuple(str(row[c]) for c in key)
            if k not in seen:
                rows.append(row)
                seen.add(k)
                added += 1
        return FakeJob(num_dml_affected_rows=added)

    # -- Consultas de lectura ---------------------------------------------

    def _current(self) -> list[dict[str, Any]]:
        promoted = {
            m["model_version"]
            for m in self.rows("model_versions")
            if m["status"] == "promoted"
        }
        latest: dict[str, dict[str, Any]] = {}
        for p in self.rows("review_predictions"):
            if p["model_version"] in promoted:
                old = latest.get(p["id_resena"])
                if old is None or _iso(p["predicted_at"]) > _iso(
                    old["predicted_at"]
                ):
                    latest[p["id_resena"]] = p
        return list(latest.values())

    def _tds(self) -> list[dict[str, Any]]:
        return [
            {**t, "text_key": text_key(t["texto_sanitizado"] or "")}
            for t in self.rows("sanitized_reviews_tds")
        ]

    def _topic_pending(self, other: str, version_field: str, value: str):
        texts = {t["id_resena"]: t for t in self._tds()}
        done = {
            (r["id_resena"], r["text_key"])
            for r in self.rows(other)
            if r[version_field] == value
        }
        return [
            {
                "id_resena": p["id_resena"],
                "bank_id": p["bank_id"],
                "text_key": p["text_key"],
                "fecha": p["fecha"],
                "model_version": p["model_version"],
                "run_id": p.get("run_id"),
                "texto_sanitizado": texts.get(p["id_resena"], {}).get(
                    "texto_sanitizado"
                ),
            }
            for p in self._current()
            if p["sentiment"] == "NEG"
            and p["palabras"] >= 2
            and (p["id_resena"], p["text_key"]) not in done
        ]

    def _aspects_backfill(self, sql: str, params: dict[str, Any]) -> list[dict]:
        done = {
            (a["id_resena"], a["text_key"])
            for a in self.rows("review_aspects")
            if a["prompt_version"] == params["prompt"]
        }
        pending = [
            r
            for r in self._topic_pending(
                "review_aspects", "prompt_version", None
            )
            if (r["id_resena"], r["text_key"]) not in done
        ]
        if "-- Textos sin familias" in sql:
            return [{"texts": len({r["text_key"] for r in pending})}]
        keys = sorted(
            {r["text_key"] for r in pending if r["text_key"] > params["after"]}
        )
        keys = set(keys[: params["limit"]])
        return sorted(
            (r for r in pending if r["text_key"] in keys),
            key=lambda r: r["text_key"],
        )

    def _topics_backfill(self, sql: str, params: dict[str, Any]) -> list[dict]:
        pending = self._topic_pending(
            "topic_assignments", "topic_model_version", params["version"]
        )
        stored = self.rows("segment_embeddings")
        if "-- Textos pendientes sin vectores" in sql:
            with_vectors = {e["text_key"] for e in stored}
            out = {
                p["text_key"]: {
                    "text_key": p["text_key"],
                    "texto_sanitizado": p["texto_sanitizado"],
                }
                for p in pending
                if p["text_key"] not in with_vectors
                and p["texto_sanitizado"] is not None
            }
            return list(out.values())
        if "-- Vectores de las cláusulas pendientes" in sql:
            keys = {p["text_key"] for p in pending}
            return sorted(
                (e for e in stored if e["text_key"] in keys),
                key=lambda e: (e["text_key"], e["segment_index"]),
            )
        if "-- Reseñas pendientes de un lote" in sql:
            return [p for p in pending if p["text_key"] in params["keys"]]
        if "-- Reseñas que siguen pendientes" in sql:
            return [{"left_reviews": len(pending)}]
        raise AssertionError(f"unexpected query: {sql[:120]}")

    def _select(self, sql: str, params: dict[str, Any]) -> list[dict]:
        if "-- " in sql and "sin familias del prompt vigente" in sql:
            return self._aspects_backfill(sql, params)
        if "-- " in sql and "WITH pending AS" in sql:
            return self._topics_backfill(sql, params)
        if ".model_versions`" in sql:
            return list(self.rows("model_versions"))
        if "risk_policy_current" in sql:
            return list(self.rows("risk_policy"))[-1:]
        if "hitl_coverage_curves" in sql:
            return list(self.rows("hitl_coverage_curves"))[-1:]
        if "hitl_boosts_active" in sql:
            return [
                b for b in self.rows("hitl_boosts") if not b["ended_reason"]
            ]
        if "FROM `" + DATASET + ".topic_model_current`" in sql:
            return list(self.rows("topic_model_versions"))[-1:]
        if "COUNT(*) AS n" in sql:
            week = _iso(params["week_start"])
            items = [
                i
                for i in self.rows("hitl_items")
                if _iso(i["created_at"]) >= week
                and i["reason"] in ("low_confidence", "drift_boost")
                and ("bank" not in params or i["bank_id"] == params["bank"])
                and ("bank" not in params or i["reason"] == "drift_boost")
            ]
            return [{"n": len(items)}]
        if ".review_predictions` AS p" in sql:
            done = {
                (p["id_resena"], p["text_key"])
                for p in self.rows("review_predictions")
                if p["model_version"] == params["model_version"]
            }
            rows = [
                t
                for t in self._tds()
                if (t["id_resena"], t["text_key"]) not in done
            ]
            return sorted(rows, key=lambda t: _iso(t["fecha"]))[
                : params["limit"]
            ]
        if "review_aspects` AS a" in sql:
            # Cualquier fila, con cualquier prompt, deja la reseña fuera.
            labeled = {
                (a["id_resena"], a["text_key"])
                for a in self.rows("review_aspects")
            }
            return [
                r
                for r in self._topic_pending(
                    "review_aspects", "prompt_version", None
                )
                if (r["id_resena"], r["text_key"]) not in labeled
            ][: params["limit"]]
        if "FROM `" + DATASET + ".review_aspects`" in sql:
            latest: dict[str, dict] = {}
            for a in self.rows("review_aspects"):
                if a["text_key"] in params["keys"]:
                    latest[a["text_key"]] = a
            return list(latest.values())
        if "text_embeddings` AS e" in sql:
            done = {
                (e["text_key"], e["bank_id"], str(e["mes"]))
                for e in self.rows("text_embeddings")
            }
            out: dict[tuple, dict] = {}
            for t in self._tds():
                if not (t["texto_sanitizado"] or "").strip():
                    continue
                mes = t["fecha"].date().replace(day=1)
                k = (t["text_key"], t["bank_id"], str(mes))
                if k not in done:
                    out[k] = {
                        "text_key": t["text_key"],
                        "bank_id": t["bank_id"],
                        "mes": mes,
                        "texto_sanitizado": t["texto_sanitizado"],
                    }
            return list(out.values())[: params["limit"]]
        if "ANY_VALUE(embedding)" in sql:
            seen: dict[str, dict] = {}
            for e in self.rows("text_embeddings"):
                if e["text_key"] in params["keys"]:
                    seen.setdefault(
                        e["text_key"],
                        {
                            "text_key": e["text_key"],
                            "embedding": e["embedding"],
                        },
                    )
            return list(seen.values())
        if "AS running" in sql:
            runs = self.rows("inference_runs")
            closed = {r["run_id"] for r in runs if r["status"] != "running"}
            since = _iso(params["since"])
            return [
                {
                    "running": sum(
                        r["kind"] == params["kind"]
                        and r["status"] == "running"
                        and _iso(r["started_at"]) >= since
                        and params["version"]
                        in (None, r.get("topic_model_version"))
                        and r["run_id"] not in closed
                        for r in runs
                    )
                }
            ]
        if "AS unassigned" in sql:
            pending = self._topic_pending(
                "topic_assignments", "topic_model_version", params["version"]
            )
            return [{"unassigned": len(pending)}]
        if "FROM `" + DATASET + ".segment_embeddings`" in sql:
            return [
                e
                for e in self.rows("segment_embeddings")
                if e["text_key"] in params["keys"]
            ]
        if "topic_assignments` AS a" in sql:
            delta_runs = {
                r["run_id"]
                for r in self.rows("inference_runs")
                if r["kind"] == "delta"
            } | {params["run_id"]}
            return [
                r
                for r in self._topic_pending(
                    "topic_assignments",
                    "topic_model_version",
                    params["version"],
                )
                if r["run_id"] in delta_runs
            ][: params["limit"]]
        raise AssertionError(f"unexpected query: {sql[:120]}")


class FakeBlob:
    def __init__(self, name: str) -> None:
        self.name = name

    def download_to_filename(self, path: str) -> None:
        Path(path).write_text("peso")


class FakeStorage:
    def __init__(self) -> None:
        self.listed: list[str] = []

    def list_blobs(self, bucket: str, prefix: str) -> list[FakeBlob]:
        self.listed.append(prefix)
        return [FakeBlob(prefix), FakeBlob(f"{prefix}config.json")]


def _proba(text: str) -> list[float]:
    if "duda" in text:
        return [0.40, 0.35, 0.25]
    if "malo" in text or "no abre" in text:
        return [0.97, 0.02, 0.01]
    return [0.02, 0.03, 0.95]


class FakeSentiment:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.explained: list[str] = []
        self.temperatures: list[float] = []

    def predict(self, texts: Sequence[str]) -> np.ndarray:
        self.calls.append(list(texts))
        return np.array([_proba(t) for t in texts], dtype=np.float32)

    def explain(self, text: str, temperature: float) -> list[TokenAttribution]:
        self.explained.append(text)
        self.temperatures.append(temperature)
        return [
            TokenAttribution(start=0, end=1, d_neg=0.5, d_neu=-0.2, d_pos=-0.3)
        ]


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        self.calls.append(list(texts))
        return np.full((len(texts), 384), 0.5, dtype=np.float32)


class FakeTopics:
    def assign(self, segments: Sequence[str], embeddings: Any) -> list[int]:
        return [3 if "pero" not in s else -1 for s in segments]


class FakeJobs:
    """Registra las ejecuciones (no las corre)."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, list[str]]] = []

    def execute(self, job: str, args: Sequence[str]) -> str:
        self.executed.append((job, list(args)))
        return f"operations/{job}-{len(self.executed)}"


class FakeGemini:
    """Responde todas las líneas salvo las de textos con ``omitir``."""

    def __init__(self) -> None:
        self.models = self
        self.calls = 0
        self.sent: list[str] = []
        # Tokens de entrada por llamada (sin ellos, el costo es 0).
        self.prompt_tokens: int | None = None

    def generate_content(self, *, model: str, contents: str, config: Any):
        self.calls += 1
        self.sent.extend(
            line.split(chr(9), 1)[1] for line in contents.splitlines()
        )
        lines = [
            f"{line.split(chr(9))[0]} AC 1 0 0"
            for line in contents.splitlines()
            if "omitir" not in line
        ]
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


@dataclass
class World:
    bq: FakeBigQuery
    storage: FakeStorage
    sentiment: FakeSentiment
    embedder: FakeEmbedder
    gemini: FakeGemini
    clients: Clients
    jobs: FakeJobs
    settings: InferenceSettings
    lexicon: Lexicon = LEXICON
    now: datetime = NOW

    @staticmethod
    def tds_row(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return tds_row(*args, **kwargs)

    @staticmethod
    def text_key(text: str) -> str:
        return text_key(text)


@pytest.fixture
def world(tmp_path: Path) -> World:
    bq = FakeBigQuery()
    sentiment, embedder, gemini = FakeSentiment(), FakeEmbedder(), FakeGemini()
    jobs = FakeJobs()
    clients = Clients(
        bigquery=bq,
        storage=FakeStorage(),
        genai=gemini,
        engines=EngineLoaders(
            sentiment=lambda path, batch, threads: sentiment,
            embedder=lambda path: embedder,
            topics=lambda path: FakeTopics(),
        ),
        jobs=jobs,
    )
    settings = InferenceSettings(
        gcp_project_id=PROJECT,
        gcs_raw_datalake_bucket="bucket",
        artifacts_dir=tmp_path / "artifacts",
    )
    seed_world(bq)
    return World(
        bq,
        clients.storage,
        sentiment,
        embedder,
        gemini,
        clients,
        jobs,
        settings,
    )


def tds_row(
    id_resena: str,
    text: str,
    bank: str = "BBVA",
    fecha: datetime = datetime(2026, 11, 3, 12, tzinfo=UTC),
) -> dict[str, Any]:
    return {
        "id_resena": id_resena,
        "bank_id": bank,
        "fecha": fecha,
        "version_app": "10.1.0",
        "estrellas": 1,
        "texto_limpio": text.lower(),
        "texto_sanitizado": text,
    }


def seed_world(bq: FakeBigQuery) -> None:
    bq.rows("model_versions").append(
        {
            "model_version": MODEL,
            "registry_uri": "gs://bucket/ml_artifacts/sentiment/" + MODEL + "/",
            "base_checkpoint": "pysentimiento/robertuito-sentiment-analysis",
            "training_data": "silver_v1",
            "training_data_hash": None,
            "calibration_version": "temperature_s1",
            "calibration_t": 1.0,
            "kappa_dev": None,
            "ece_dev": None,
            "aurc_dev": None,
            "license": "non-commercial",
            "status": "promoted",
            "promoted_at": NOW,
            "promoted_by_hash": ACTOR,
            "recorded_at": NOW,
        }
    )
    bq.rows("risk_policy").append(
        {
            "policy_version": "risk_policy_v1",
            "valid_from": NOW,
            "hitl_signal": "prob_max",
            "hitl_target_coverage": 0.9,
            "hitl_threshold": 0.9,
            "model_version": MODEL,
            "hitl_weekly_cap": None,
            "drift_boost_coverage": None,
            "drift_boost_days": None,
            "drift_boost_weekly_cap": None,
            "monitor_sample_size": 300,
            "monitor_frequency": "quarterly",
            "topic_refit_frequency": "quarterly",
            "retrain_kappa_floor": 0.89,
            "human_agreement_sample_size": None,
            "human_agreement_frequency": None,
            "warn_correction_rate": 0.28,
            "warn_agreement_floor": 0.94,
            "agreement_sample_weekly": 500,
            "families_exact_floor": 0.53,
            "families_min_prevalence": 0.05,
            "set_by_hash": ACTOR,
            "reason": "prueba",
        }
    )
    point = {
        "risk": 0.01,
        "risk_ci_low": 0.0,
        "risk_ci_high": 0.02,
        "errors_caught": 0.5,
        "reviews_per_week": 100.0,
        "minutes_per_week": 100.0,
    }
    bq.rows("hitl_coverage_curves").append(
        {
            "model_version": MODEL,
            "calibration_version": "temperature_s1",
            "points": [
                {**point, "coverage": 0.8, "threshold": 0.98},
                {**point, "coverage": 0.9, "threshold": 0.9},
            ],
            "weekly_volume_total": 3500,
            "weekly_volume_by_bank": {"BBVA": 1000},
            "computed_at": NOW,
        }
    )
    bq.rows("topic_model_versions").append(
        {"topic_model_version": "topics_v1", "fitted_at": NOW}
    )


@pytest.fixture
def fake_bq() -> FakeBigQuery:
    return FakeBigQuery()
