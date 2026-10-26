"""``BigQueryAdminRepository`` con un lector y un escritor falsos."""

import json
from datetime import UTC, date, datetime
from typing import Any

from api_backend.sections.admin.repository import BigQueryAdminRepository
from api_backend.sections.admin.sample import (
    curve,
    risk_policy,
    thresholds,
)
from api_backend.sections.admin.schemas import GoldCriteria
from api_backend.settings import ApiSettings
from voc_common import DriftPolicy, GoldVersion

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)


class FakeReader:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows_out = rows
        self.calls: list[tuple[str, list[Any]]] = []

    def rows(self, sql: str, params: list[Any], **_: object) -> list[dict]:
        self.calls.append((sql, params))
        return self.rows_out


class FakeWriter:
    def __init__(self) -> None:
        self.inserted: list[tuple[str, Any, list[str]]] = []

    def insert(self, table: str, row: Any, key: list[str]) -> bool:
        self.inserted.append((table, row, key))
        return True


def repo(
    rows: list[dict[str, Any]],
) -> tuple[BigQueryAdminRepository, FakeReader, FakeWriter]:
    reader, writer = FakeReader(rows), FakeWriter()
    settings = ApiSettings.model_validate(
        {"gcp_project_id": "p", "bq_dataset_id": "d", "iap_audience": "/a"}
    )
    return (
        BigQueryAdminRepository(reader, writer, settings),  # type: ignore[arg-type]
        reader,
        writer,
    )


def test_lee_las_versiones_de_riesgo_ordenadas() -> None:
    r, reader, _ = repo([risk_policy(NOW).model_dump()])

    (policy,) = r.risk_policies()

    assert policy.policy_version == "risk_policy_v1"
    assert "`p.d.risk_policy`" in reader.calls[0][0]
    assert "ORDER BY valid_from" in reader.calls[0][0]


def test_el_modelo_promovido_y_la_curva() -> None:
    r, reader, _ = repo([{"model_version": "m1"}])
    assert r.promoted_model_version() == "m1"
    assert "status = 'promoted'" in reader.calls[0][0]

    row = curve(NOW).model_dump()
    row["weekly_volume_by_bank"] = json.dumps(row["weekly_volume_by_bank"])
    r, reader, _ = repo([row])
    found = r.curve("sintetico_v1")
    assert found is not None and found.weekly_volume_total == 3500
    assert "`p.d.hitl_coverage_curves`" in reader.calls[0][0]
    assert repo([])[0].curve("x") is None
    assert repo([])[0].promoted_model_version() is None


def test_el_tiempo_medido_y_las_subidas() -> None:
    r, reader, _ = repo([{"median": 7.0, "n": 412}])
    assert r.timing(90) == (7.0, 412)
    assert "`p.d.hitl_reviews`" in reader.calls[0][0]
    assert repo([{"median": None, "n": 0}])[0].timing(90) == (None, 0)
    assert repo([])[0].active_boosts() == []


def test_deriva_lee_plantilla_politicas_y_meses() -> None:
    template = {
        "template_version": "t1",
        "valid_from": NOW,
        "thresholds": json.dumps(thresholds().model_dump()),
        "baseline_months": 12,
        "min_baseline_months": 6,
        "min_rows_per_month": 200,
        "entry_months": 12,
        "set_by_hash": "a" * 64,
        "reason": "plantilla",
    }
    r, _, _ = repo([template])
    found = r.drift_template("t1")
    assert found is not None and found.thresholds.z["neg_share"] == 4.0
    assert repo([])[0].drift_template("t1") is None

    policy = {
        **template,
        "drift_policy_version": "drift_policy_v1_BBVA",
        "bank_id": "BBVA",
    }
    r, reader, _ = repo([policy])
    (listed,) = r.drift_policies("BBVA")
    assert listed.bank_id == "BBVA"
    assert "`p.d.drift_policy`" in reader.calls[0][0]

    r, reader, _ = repo(
        [{"metric": "neg_share", "period": "2025-01", "z": 4.5, "psi": None}]
    )
    (month,) = r.drift_months("BBVA")
    assert (month.series, month.period, month.z) == (
        "neg_share",
        "2025-01",
        4.5,
    )
    assert "threshold IS NOT NULL" in reader.calls[0][0]


def test_escribe_cada_version_con_su_clave() -> None:
    r, _, writer = repo([])
    drift = DriftPolicy(
        drift_policy_version="drift_policy_v2_BBVA",
        bank_id="BBVA",
        template_version="t1",
        valid_from=NOW,
        thresholds=thresholds(),
        baseline_months=12,
        min_baseline_months=6,
        min_rows_per_month=200,
        entry_months=12,
        set_by_hash="a" * 64,
        reason="prueba de escritura",
    )
    gold = GoldVersion(
        gold_version="gold_hitl_v1",
        criteria={"reason": "monitor_sample"},
        cutoff_at=NOW,
        items=1,
        created_by_hash="a" * 64,
        created_at=NOW,
    )

    assert r.add_risk_policy(risk_policy(NOW))
    assert r.add_drift_policy(drift)
    assert r.add_gold_version(gold)

    assert [(t, k) for t, _, k in writer.inserted] == [
        ("risk_policy", ["policy_version"]),
        ("drift_policy", ["drift_policy_version"]),
        ("gold_versions", ["gold_version"]),
    ]


def test_el_oro_filtra_en_sql_con_parametros_y_sin_texto() -> None:
    r, reader, _ = repo(
        [
            {
                "item_id": "i1",
                "id_resena": "r1",
                "bank_id": "BBVA",
                "validated_label": "NEG",
                "submitted_at": NOW,
                "reviewer_hash": "a" * 64,
            }
        ]
    )
    criteria = GoldCriteria(
        submitted_from=date(2026, 7, 1),
        submitted_to=date(2026, 9, 30),
        guideline_version="v2.2",
    )

    (row,) = r.gold_rows(criteria, NOW)
    sql, params = reader.calls[0]

    assert row.bank_id == "BBVA"
    assert "submitted_at <= @cutoff" in sql
    assert "texto" not in sql
    assert {p.name for p in params} >= {"reason", "round", "exclude", "cutoff"}
    r.gold_rows(criteria, None)
    assert "@cutoff" not in reader.calls[1][0]


def test_las_versiones_del_oro_parsean_el_json() -> None:
    r, _, _ = repo(
        [
            {
                "gold_version": "gold_hitl_v1",
                "criteria": json.dumps({"reason": "monitor_sample"}),
                "cutoff_at": NOW,
                "items": 3,
                "created_by_hash": "a" * 64,
                "created_at": NOW,
            }
        ]
    )

    (version,) = r.gold_versions()

    assert version.criteria == {"reason": "monitor_sample"}
