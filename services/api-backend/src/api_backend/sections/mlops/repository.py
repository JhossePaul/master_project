"""Lecturas de MLOps: ``Protocol``, BigQuery y memoria."""

# ruff: noqa: S608
# Los nombres de tablas salen de ``qualified`` (lista cerrada); los valores
# viajan siempre como parámetros.

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from voc_common import (
    DriftMetric,
    InferenceRun,
    ModelQuality,
    ModelVersion,
    PromotionCheckResult,
    RiskPolicy,
    RunKind,
)

from api_backend.bq.names import qualified
from api_backend.bq.reader import BigQueryReader, Param
from api_backend.settings import ApiSettings


@dataclass(frozen=True)
class IngestionRun:
    """Una corrida de ingesta, deduplicada por ``audit_event_id``."""

    run_id: str
    bank_id: str
    mode: str
    started_at: datetime
    ended_at: datetime
    status: str
    reviews_extracted: int | None
    reviews_published: int | None
    reviews_discarded: int | None


@dataclass(frozen=True)
class EligibilityCount:
    bank_id: str
    period: date
    code: str
    n: int


class MlopsRepository(Protocol):
    def risk_policies(self) -> list[RiskPolicy]:
        """De la más antigua a la más reciente."""

    def quality(self) -> list[ModelQuality]:
        """La fila más reciente de cada señal, periodo y sujeto."""

    def drift_series(self) -> list[str]:
        """Nombres de las series de ``drift_metrics`` (todas)."""

    def drift(
        self,
        first: date,
        last: date,
        names: tuple[str, ...] = (),
        prefix: str | None = None,
    ) -> list[DriftMetric]:
        """Una fila por banco, mes y serie (la corrida más reciente)."""

    def model_versions(self) -> list[ModelVersion]:
        """Todas las filas, por ``recorded_at``."""

    def promotion_checks(self) -> list[PromotionCheckResult]:
        """El más reciente de cada candidato."""

    def runs(
        self, since: datetime, kind: RunKind | None = None
    ) -> list[InferenceRun]:
        """Estado vigente de cada corrida, la más reciente primero."""

    def ingestion(self, since: datetime) -> list[IngestionRun]: ...

    def eligibility(self) -> list[EligibilityCount]: ...

    def last_ingestion_at(self) -> datetime | None: ...

    def last_monitor_at(self) -> datetime | None: ...

    def last_topic_fit(self) -> datetime | None: ...


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class BigQueryMlopsRepository:
    def __init__(self, reader: BigQueryReader, settings: ApiSettings) -> None:
        self._reader = reader
        self._project = settings.gcp_project_id
        self._dataset = settings.bq_dataset_id

    def _table(self, name: str) -> str:
        return qualified(name, self._project, self._dataset)

    def risk_policies(self) -> list[RiskPolicy]:
        sql = f"SELECT * FROM {self._table('risk_policy')} ORDER BY valid_from"  # nosec B608
        rows = self._reader.rows(sql, [], name="mlops_risk_policies")
        return [RiskPolicy.model_validate(dict(r)) for r in rows]

    def quality(self) -> list[ModelQuality]:
        sql = (
            f"SELECT * FROM {self._table('model_quality')} "  # nosec B608
            "WHERE TRUE "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY signal, period, "
            "IFNULL(model_version, ''), IFNULL(llm_model, ''), "
            "IFNULL(prompt_version, '') ORDER BY computed_at DESC) = 1 "
            "ORDER BY period, computed_at"
        )
        rows = self._reader.rows(sql, [], name="mlops_quality")
        return [ModelQuality.model_validate(dict(r)) for r in rows]

    def drift_series(self) -> list[str]:
        sql = (
            f"SELECT DISTINCT metric FROM {self._table('drift_metrics')} "  # nosec B608
            "ORDER BY metric"
        )
        rows = self._reader.rows(sql, [], name="mlops_drift_series")
        return [str(r["metric"]) for r in rows]

    def drift(
        self,
        first: date,
        last: date,
        names: tuple[str, ...] = (),
        prefix: str | None = None,
    ) -> list[DriftMetric]:
        clauses = ["period BETWEEN @first AND @last"]
        params = [Param("first", "DATE", first), Param("last", "DATE", last)]
        matches = []
        if names:
            matches.append("metric IN UNNEST(@names)")
            params.append(Param("names", "STRING", names, array=True))
        if prefix is not None:
            matches.append("STARTS_WITH(metric, @prefix)")
            params.append(Param("prefix", "STRING", prefix))
        if matches:
            clauses.append(f"({' OR '.join(matches)})")
        sql = (
            "SELECT bank_id, period, metric, value, baseline, z, psi, "  # nosec B608
            "threshold, alert, drift_policy_version, computed_at "
            f"FROM {self._table('drift_metrics')} "
            f"WHERE {' AND '.join(clauses)} "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY bank_id, period, "
            "metric ORDER BY computed_at DESC) = 1 "
            "ORDER BY metric, bank_id, period"
        )
        rows = self._reader.rows(sql, params, name="mlops_drift")
        return [DriftMetric.model_validate(dict(r)) for r in rows]

    def model_versions(self) -> list[ModelVersion]:
        sql = (
            f"SELECT * FROM {self._table('model_versions')} "  # nosec B608
            "ORDER BY recorded_at"
        )
        rows = self._reader.rows(sql, [], name="mlops_models")
        return [ModelVersion.model_validate(dict(r)) for r in rows]

    def promotion_checks(self) -> list[PromotionCheckResult]:
        sql = (
            f"SELECT * FROM {self._table('promotion_checks')} "  # nosec B608
            "WHERE TRUE "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY candidate_version "
            "ORDER BY computed_at DESC) = 1"
        )
        rows = self._reader.rows(sql, [], name="mlops_checks")
        return [PromotionCheckResult.model_validate(dict(r)) for r in rows]

    def runs(
        self, since: datetime, kind: RunKind | None = None
    ) -> list[InferenceRun]:
        clauses = ["started_at >= @since"]
        params = [Param("since", "TIMESTAMP", since)]
        if kind is not None:
            clauses.append("kind = @kind")
            params.append(Param("kind", "STRING", kind.value))
        sql = (
            f"SELECT * FROM {self._table('inference_runs_current')} "  # nosec B608
            f"WHERE {' AND '.join(clauses)} ORDER BY started_at DESC"
        )
        rows = self._reader.rows(sql, params, name="mlops_runs")
        return [InferenceRun.model_validate(dict(r)) for r in rows]

    def ingestion(self, since: datetime) -> list[IngestionRun]:
        # Un evento de auditoría puede estar repetido: se deduplica antes de
        # agrupar, o la duración y los conteos salen inflados.
        sql = (
            "WITH events AS ("  # nosec B608
            "SELECT * "
            f"FROM {self._table('ingestion_runs_log_v2')} "
            "WHERE updated_at >= @since "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY audit_event_id "
            "ORDER BY updated_at DESC) = 1) "
            "SELECT run_id, ANY_VALUE(bank_id) AS bank_id, "
            "ANY_VALUE(mode_executed) AS mode, "
            "MIN(updated_at) AS started_at, MAX(updated_at) AS ended_at, "
            "ARRAY_AGG(status ORDER BY updated_at DESC LIMIT 1)[OFFSET(0)] "
            "AS status, "
            "MAX(reviews_extracted) AS reviews_extracted, "
            "MAX(reviews_published) AS reviews_published, "
            "MAX(reviews_discarded) AS reviews_discarded "
            "FROM events GROUP BY run_id ORDER BY started_at DESC"
        )
        rows = self._reader.rows(
            sql, [Param("since", "TIMESTAMP", since)], name="mlops_ingestion"
        )
        return [
            IngestionRun(
                run_id=str(r["run_id"]),
                bank_id=str(r["bank_id"]),
                mode=str(r["mode"]),
                started_at=r["started_at"],  # type: ignore[arg-type]
                ended_at=r["ended_at"],  # type: ignore[arg-type]
                status=str(r["status"]),
                reviews_extracted=_opt_int(r["reviews_extracted"]),
                reviews_published=_opt_int(r["reviews_published"]),
                reviews_discarded=_opt_int(r["reviews_discarded"]),
            )
            for r in rows
        ]

    def eligibility(self) -> list[EligibilityCount]:
        sql = (
            "SELECT bank_id, mes, eligibility_code, SUM(filas) AS filas "  # nosec B608
            f"FROM {self._table('eligibility_counts')} "
            "GROUP BY bank_id, mes, eligibility_code ORDER BY mes, bank_id"
        )
        rows = self._reader.rows(sql, [], name="mlops_eligibility")
        return [
            EligibilityCount(
                bank_id=str(r["bank_id"]),
                period=r["mes"],  # type: ignore[arg-type]
                code=str(r["eligibility_code"]),
                n=int(r["filas"]),  # type: ignore[call-overload]
            )
            for r in rows
        ]

    def _scalar(self, sql: str, name: str) -> datetime | None:
        rows = self._reader.rows(sql, [], name=name)
        return next(iter(rows[0].values()), None) if rows else None  # type: ignore[return-value]

    def last_ingestion_at(self) -> datetime | None:
        return self._scalar(
            "SELECT MAX(updated_at) AS v FROM "  # nosec B608
            f"{self._table('ingestion_runs_log_v2')} "
            "WHERE status = 'COMPLETED'",
            "mlops_last_ingestion",
        )

    def last_monitor_at(self) -> datetime | None:
        return self._scalar(
            f"SELECT MAX(computed_at) AS v FROM {self._table('kpi_estimates')}",  # nosec B608
            "mlops_last_monitor",
        )

    def last_topic_fit(self) -> datetime | None:
        return self._scalar(
            "SELECT MAX(fitted_at) AS v FROM "  # nosec B608
            f"{self._table('topic_model_versions')}",
            "mlops_last_topic_fit",
        )


def _opt_int(value: object) -> int | None:
    return None if value is None else int(value)  # type: ignore[call-overload]


@dataclass
class InMemoryMlopsRepository:
    """Lo que usan las pruebas y ``PORTAL_DATA=fixtures``."""

    policies: list[RiskPolicy]
    quality_rows: list[ModelQuality] = field(default_factory=list)
    drift_rows: list[DriftMetric] = field(default_factory=list)
    model_rows: list[ModelVersion] = field(default_factory=list)
    check_rows: list[PromotionCheckResult] = field(default_factory=list)
    run_rows: list[InferenceRun] = field(default_factory=list)
    ingestion_rows: list[IngestionRun] = field(default_factory=list)
    eligibility_rows: list[EligibilityCount] = field(default_factory=list)
    ingestion_at: datetime | None = None
    monitor_at: datetime | None = None
    topic_fit_at: datetime | None = None

    def risk_policies(self) -> list[RiskPolicy]:
        return sorted(self.policies, key=lambda p: p.valid_from)

    def quality(self) -> list[ModelQuality]:
        return sorted(
            self.quality_rows, key=lambda q: (q.period, q.computed_at)
        )

    def drift_series(self) -> list[str]:
        return sorted({m.metric for m in self.drift_rows})

    def drift(
        self,
        first: date,
        last: date,
        names: tuple[str, ...] = (),
        prefix: str | None = None,
    ) -> list[DriftMetric]:
        def wanted(metric: str) -> bool:
            if not names and prefix is None:
                return True
            return metric in names or (
                prefix is not None and metric.startswith(prefix)
            )

        rows = [
            m
            for m in self.drift_rows
            if first <= m.period <= last and wanted(m.metric)
        ]
        return sorted(rows, key=lambda m: (m.metric, m.bank_id, m.period))

    def model_versions(self) -> list[ModelVersion]:
        return sorted(self.model_rows, key=lambda m: m.recorded_at)

    def promotion_checks(self) -> list[PromotionCheckResult]:
        latest: dict[str, PromotionCheckResult] = {}
        for check in sorted(self.check_rows, key=lambda c: c.computed_at):
            latest[check.candidate_version] = check
        return list(latest.values())

    def runs(
        self, since: datetime, kind: RunKind | None = None
    ) -> list[InferenceRun]:
        rows = [
            r
            for r in self.run_rows
            if r.started_at >= since and (kind is None or r.kind is kind)
        ]
        return sorted(rows, key=lambda r: r.started_at, reverse=True)

    def ingestion(self, since: datetime) -> list[IngestionRun]:
        rows = [r for r in self.ingestion_rows if r.started_at >= since]
        return sorted(rows, key=lambda r: r.started_at, reverse=True)

    def eligibility(self) -> list[EligibilityCount]:
        return list(self.eligibility_rows)

    def last_ingestion_at(self) -> datetime | None:
        return self.ingestion_at

    def last_monitor_at(self) -> datetime | None:
        return self.monitor_at

    def last_topic_fit(self) -> datetime | None:
        return self.topic_fit_at
