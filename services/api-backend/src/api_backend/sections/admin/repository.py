"""Lecturas y escrituras de administración: ``Protocol``, BigQuery y memoria."""

# ruff: noqa: S608
# Los nombres de tablas salen de ``qualified`` (lista cerrada); los valores
# viajan siempre como parámetros.

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from voc_common import (
    DriftPolicy,
    DriftPolicyTemplate,
    GoldVersion,
    HitlBoost,
    HitlCoverageCurve,
    RiskPolicy,
)

from api_backend.bq.names import qualified
from api_backend.bq.reader import BigQueryReader, Param
from api_backend.bq.writer import BigQueryWriter
from api_backend.sections.admin.schemas import GoldCriteria
from api_backend.settings import ApiSettings

TIMING_WINDOW_DAYS = 90


@dataclass(frozen=True)
class DriftMonth:
    """Un mes evaluado de una serie: sus estadísticos, no su alerta."""

    series: str
    period: str  # YYYY-MM
    z: float | None
    psi: float | None


@dataclass(frozen=True)
class GoldRow:
    """Una revisión que cumple los criterios (sin texto)."""

    item_id: str
    id_resena: str
    bank_id: str
    validated_label: str | None
    submitted_at: datetime
    reviewer_hash: str


class AdminRepository(Protocol):
    def risk_policies(self) -> list[RiskPolicy]:
        """Todas las versiones, de la más antigua a la más reciente."""

    def promoted_model_version(self) -> str | None: ...

    def curve(self, model_version: str) -> HitlCoverageCurve | None:
        """La curva más reciente del modelo."""

    def timing(self, window_days: int) -> tuple[float | None, int]:
        """Mediana de ``seconds_spent`` y número de revisiones medidas."""

    def active_boosts(self) -> list[HitlBoost]: ...

    def add_risk_policy(self, policy: RiskPolicy) -> bool: ...

    def drift_policies(self, bank: str) -> list[DriftPolicy]:
        """Todas las versiones del banco, de la más antigua a la reciente."""

    def drift_template(self, version: str) -> DriftPolicyTemplate | None: ...

    def drift_months(self, bank: str) -> list[DriftMonth]:
        """Meses evaluados por el monitor (con umbral), última corrida."""

    def add_drift_policy(self, policy: DriftPolicy) -> bool: ...

    def gold_versions(self) -> list[GoldVersion]: ...

    def gold_rows(
        self, criteria: GoldCriteria, cutoff_at: datetime | None
    ) -> list[GoldRow]: ...

    def add_gold_version(self, version: GoldVersion) -> bool: ...


def _json(value: Any) -> Any:
    """Las columnas JSON de BigQuery llegan como texto."""
    return json.loads(value) if isinstance(value, str) else value


def _policy_row(row: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if "thresholds" in out:
        out["thresholds"] = _json(out["thresholds"])
    return out


class BigQueryAdminRepository:
    def __init__(
        self,
        reader: BigQueryReader,
        writer: BigQueryWriter,
        settings: ApiSettings,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._project = settings.gcp_project_id
        self._dataset = settings.bq_dataset_id

    def _table(self, name: str) -> str:
        return qualified(name, self._project, self._dataset)

    def risk_policies(self) -> list[RiskPolicy]:
        sql = f"SELECT * FROM {self._table('risk_policy')} ORDER BY valid_from"  # nosec B608
        rows = self._reader.rows(sql, [], name="admin_risk_policies")
        return [RiskPolicy.model_validate(dict(r)) for r in rows]

    def promoted_model_version(self) -> str | None:
        sql = (
            "SELECT model_version FROM "  # nosec B608
            f"{self._table('model_versions')} "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY model_version "
            "ORDER BY recorded_at DESC) = 1 AND status = 'promoted' "
            "ORDER BY promoted_at DESC LIMIT 1"
        )
        rows = self._reader.rows(sql, [], name="admin_promoted", cache=True)
        return str(rows[0]["model_version"]) if rows else None

    def curve(self, model_version: str) -> HitlCoverageCurve | None:
        sql = (
            f"SELECT * FROM {self._table('hitl_coverage_curves')} "  # nosec B608
            "WHERE model_version = @mv ORDER BY computed_at DESC LIMIT 1"
        )
        rows = self._reader.rows(
            sql,
            [Param("mv", "STRING", model_version)],
            name="admin_curve",
            cache=True,
        )
        if not rows:
            return None
        row = dict(rows[0])
        row["weekly_volume_by_bank"] = _json(row["weekly_volume_by_bank"])
        return HitlCoverageCurve.model_validate(row)

    def timing(self, window_days: int) -> tuple[float | None, int]:
        sql = (
            "SELECT APPROX_QUANTILES(seconds_spent, 2)[OFFSET(1)] AS median, "  # nosec B608
            "COUNT(*) AS n "
            f"FROM {self._table('hitl_reviews')} "
            "WHERE task = 'sentiment' AND submitted_at >= "
            "TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)"
        )
        rows = self._reader.rows(
            sql,
            [Param("days", "INT64", window_days)],
            name="admin_timing",
            cache=True,
        )
        row = rows[0] if rows else {}
        n = int(row.get("n") or 0)  # type: ignore[call-overload]
        median = row.get("median")
        return (float(median) if median is not None and n else None, n)  # type: ignore[arg-type]

    def active_boosts(self) -> list[HitlBoost]:
        sql = f"SELECT * FROM {self._table('hitl_boosts_active')}"  # nosec B608
        rows = self._reader.rows(sql, [], name="admin_boosts")
        return [HitlBoost.model_validate(dict(r)) for r in rows]

    def add_risk_policy(self, policy: RiskPolicy) -> bool:
        return self._writer.insert(
            "risk_policy", policy, key=["policy_version"]
        )

    def drift_policies(self, bank: str) -> list[DriftPolicy]:
        sql = (
            f"SELECT * FROM {self._table('drift_policy')} "  # nosec B608
            "WHERE bank_id = @bank ORDER BY valid_from"
        )
        rows = self._reader.rows(
            sql, [Param("bank", "STRING", bank)], name="admin_drift_policies"
        )
        return [DriftPolicy.model_validate(_policy_row(r)) for r in rows]

    def drift_template(self, version: str) -> DriftPolicyTemplate | None:
        sql = (
            f"SELECT * FROM {self._table('drift_policy_template')} "  # nosec B608
            "WHERE template_version = @version LIMIT 1"
        )
        rows = self._reader.rows(
            sql,
            [Param("version", "STRING", version)],
            name="admin_drift_template",
            cache=True,
        )
        return (
            DriftPolicyTemplate.model_validate(_policy_row(rows[0]))
            if rows
            else None
        )

    def drift_months(self, bank: str) -> list[DriftMonth]:
        sql = (
            "SELECT metric, SUBSTR(CAST(period AS STRING), 1, 7) AS period, "  # nosec B608
            "z, psi "
            f"FROM {self._table('drift_metrics')} "
            # Sin filtrar por el umbral guardado: el z y el PSI de cada mes se
            # calculan siempre, y una serie que ganó umbral después (las
            # familias con la política v2) no tiene historia evaluada con él.
            "WHERE bank_id = @bank "
            "AND (z IS NOT NULL OR psi IS NOT NULL) "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY metric, period "
            "ORDER BY computed_at DESC) = 1"
        )
        rows = self._reader.rows(
            sql,
            [Param("bank", "STRING", bank)],
            name="admin_drift_months",
            cache=True,
        )
        return [
            DriftMonth(str(r["metric"]), str(r["period"]), r["z"], r["psi"])  # type: ignore[arg-type]
            for r in rows
        ]

    def add_drift_policy(self, policy: DriftPolicy) -> bool:
        return self._writer.insert(
            "drift_policy", policy, key=["drift_policy_version"]
        )

    def gold_versions(self) -> list[GoldVersion]:
        sql = (
            f"SELECT * FROM {self._table('gold_versions')} "  # nosec B608
            "ORDER BY created_at"
        )
        rows = self._reader.rows(sql, [], name="admin_gold_versions")
        return [
            GoldVersion.model_validate({**r, "criteria": _json(r["criteria"])})
            for r in rows
        ]

    def gold_rows(
        self, criteria: GoldCriteria, cutoff_at: datetime | None
    ) -> list[GoldRow]:
        cutoff = " AND r.submitted_at <= @cutoff" if cutoff_at else ""
        sql = (
            "SELECT r.item_id, r.id_resena, i.bank_id, r.validated_label, "  # nosec B608
            "r.submitted_at, r.reviewer_hash "
            f"FROM {self._table('hitl_reviews')} AS r JOIN "
            "(SELECT DISTINCT item_id, bank_id, reason FROM "
            f"{self._table('hitl_items')}) AS i ON i.item_id = r.item_id "
            "WHERE r.task = 'sentiment' AND i.reason = @reason "
            "AND r.review_round = @round AND r.guideline_version = @guideline "
            "AND r.validated_label IS NOT NULL "
            "AND r.submitted_at >= TIMESTAMP(@from_date) "
            "AND r.submitted_at < "
            "TIMESTAMP(DATE_ADD(@to_date, INTERVAL 1 DAY)) "
            "AND NOT EXISTS (SELECT 1 FROM UNNEST(r.flags) AS f "
            f"WHERE f IN UNNEST(@exclude)){cutoff} "
            "ORDER BY r.submitted_at, r.item_id"
        )
        params = [
            Param("reason", "STRING", criteria.reason),
            Param("round", "INT64", criteria.review_round),
            Param("guideline", "STRING", criteria.guideline_version),
            Param("from_date", "DATE", criteria.submitted_from),
            Param("to_date", "DATE", criteria.submitted_to),
            Param(
                "exclude",
                "STRING",
                [f.value for f in criteria.exclude_flags],
                array=True,
            ),
        ]
        if cutoff_at:
            params.append(Param("cutoff", "TIMESTAMP", cutoff_at))
        rows = self._reader.rows(sql, params, name="admin_gold_rows")
        return [GoldRow(**dict(r)) for r in rows]  # type: ignore[arg-type]

    def add_gold_version(self, version: GoldVersion) -> bool:
        return self._writer.insert(
            "gold_versions", version, key=["gold_version"]
        )


class InMemoryAdminRepository:
    """Misma interfaz con listas: pruebas y datos de muestra."""

    def __init__(self) -> None:
        self.risk: list[RiskPolicy] = []
        self.promoted: str | None = None
        self.curves: dict[str, HitlCoverageCurve] = {}
        self.timed: tuple[float | None, int] = (None, 0)
        self.boosts: list[HitlBoost] = []
        self.drift: dict[str, list[DriftPolicy]] = {}
        self.templates: dict[str, DriftPolicyTemplate] = {}
        self.months: dict[str, list[DriftMonth]] = {}
        self.golds: list[GoldVersion] = []
        self.reviews: list[GoldRow] = []
        # Revisiones con sus marcas, para aplicar ``exclude_flags``.
        self.review_meta: dict[str, dict[str, Any]] = {}
        # Todo lo que se escribió: (tabla, fila).
        self.writes: list[tuple[str, Any]] = []

    def risk_policies(self) -> list[RiskPolicy]:
        return sorted(self.risk, key=lambda p: p.valid_from)

    def promoted_model_version(self) -> str | None:
        return self.promoted

    def curve(self, model_version: str) -> HitlCoverageCurve | None:
        return self.curves.get(model_version)

    def timing(self, window_days: int) -> tuple[float | None, int]:
        return self.timed

    def active_boosts(self) -> list[HitlBoost]:
        return list(self.boosts)

    def add_risk_policy(self, policy: RiskPolicy) -> bool:
        if any(p.policy_version == policy.policy_version for p in self.risk):
            return False
        self.risk.append(policy)
        self.writes.append(("risk_policy", policy))
        return True

    def drift_policies(self, bank: str) -> list[DriftPolicy]:
        return sorted(self.drift.get(bank, []), key=lambda p: p.valid_from)

    def drift_template(self, version: str) -> DriftPolicyTemplate | None:
        return self.templates.get(version)

    def drift_months(self, bank: str) -> list[DriftMonth]:
        return list(self.months.get(bank, []))

    def add_drift_policy(self, policy: DriftPolicy) -> bool:
        rows = self.drift.setdefault(policy.bank_id, [])
        if any(
            p.drift_policy_version == policy.drift_policy_version for p in rows
        ):
            return False
        rows.append(policy)
        self.writes.append(("drift_policy", policy))
        return True

    def gold_versions(self) -> list[GoldVersion]:
        return sorted(self.golds, key=lambda g: g.created_at)

    def gold_rows(
        self, criteria: GoldCriteria, cutoff_at: datetime | None
    ) -> list[GoldRow]:
        out = []
        for row in self.reviews:
            meta = self.review_meta.get(row.item_id, {})
            day = row.submitted_at.date()
            if (
                meta.get("reason", "monitor_sample") == criteria.reason
                and meta.get("review_round", 1) == criteria.review_round
                and meta.get("guideline_version") == criteria.guideline_version
                and criteria.submitted_from <= day <= criteria.submitted_to
                and row.validated_label is not None
                and not set(meta.get("flags", [])) & set(criteria.exclude_flags)
                and (cutoff_at is None or row.submitted_at <= cutoff_at)
            ):
                out.append(row)
        return sorted(out, key=lambda r: (r.submitted_at, r.item_id))

    def add_gold_version(self, version: GoldVersion) -> bool:
        if any(g.gold_version == version.gold_version for g in self.golds):
            return False
        self.golds.append(version)
        self.writes.append(("gold_versions", version))
        return True
