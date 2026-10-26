"""Bordes de ``/api/v1/admin``: sin datos, carreras y deriva inválida."""

from datetime import UTC, datetime

import pytest
from api_backend.sections.admin import router as admin_router
from api_backend.sections.admin.repository import InMemoryAdminRepository
from api_backend.sections.admin.sample import sample_repository
from api_backend.testing import local_app
from fastapi.testclient import TestClient

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
CRITERIA = {
    "submitted_from": "2026-09-01",
    "submitted_to": "2026-10-26",
    "guideline_version": "v2.2",
}


def kit() -> tuple[TestClient, InMemoryAdminRepository]:
    repo = sample_repository(NOW)
    app = local_app("administrador")
    app.state.admin_repository = repo
    app.dependency_overrides[admin_router.now] = lambda: NOW
    return TestClient(app), repo


def test_sin_datos_las_lecturas_dan_404() -> None:
    client, repo = kit()
    repo.curves.clear()
    assert client.get("/api/v1/admin/coverage-curve").status_code == 404
    repo.risk.clear()
    assert client.get("/api/v1/admin/risk-policy").status_code == 404
    unknown = client.get("/api/v1/admin/drift-policy", params={"bank": "XX"})
    assert unknown.status_code == 404
    repo.templates.clear()
    orphan = client.get("/api/v1/admin/drift-policy", params={"bank": "BBVA"})
    assert orphan.status_code == 404


def test_la_curva_sin_la_cobertura_vigente_no_trae_punto() -> None:
    client, repo = kit()
    curve = repo.curves["sintetico_v1"]
    repo.curves["sintetico_v1"] = curve.model_copy(
        update={"points": curve.points[:2]}
    )

    data = client.get("/api/v1/admin/coverage-curve").json()

    assert data["current_point"] is None


def test_una_carrera_en_la_escritura_da_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, repo = kit()
    monkeypatch.setattr(repo, "add_risk_policy", lambda p: False)
    monkeypatch.setattr(repo, "add_drift_policy", lambda p: False)
    monkeypatch.setattr(repo, "add_gold_version", lambda v: False)

    risk = client.post(
        "/api/v1/admin/risk-policy",
        json={
            "base_version": "risk_policy_v1",
            "changes": {"retrain_kappa_floor": 0.9},
            "reason": "carrera del riesgo",
        },
    )
    drift = client.post(
        "/api/v1/admin/drift-policy",
        json={
            "bank": "BBVA",
            "base_version": "drift_policy_v1_BBVA",
            "changes": {"entry_months": 6},
            "reason": "carrera de deriva",
        },
    )
    gold = client.post(
        "/api/v1/admin/gold-versions",
        json={"criteria": CRITERIA, "reason": "carrera del oro"},
    )

    assert (risk.status_code, drift.status_code, gold.status_code) == (
        409,
        409,
        409,
    )


def test_la_deriva_invalida_da_422() -> None:
    client, repo = kit()
    response = client.post(
        "/api/v1/admin/drift-policy",
        json={
            "bank": "BBVA",
            "base_version": "drift_policy_v1_BBVA",
            "changes": {"min_baseline_months": 24},
            "reason": "base mínima mayor que la base",
        },
    )

    assert response.status_code == 422
    assert repo.writes == []


def test_el_router_arma_el_repositorio_de_bigquery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api_backend.bq import deps

    class Empty:
        def rows(self, sql: str, params: object, **_: object) -> list:
            return []

    app = local_app("administrador", portal_data="bigquery", gcp_project_id="p")
    monkeypatch.setattr(deps, "BigQueryReader", lambda c, s: Empty())
    monkeypatch.setattr(deps, "BigQueryWriter", lambda c, s: object())
    monkeypatch.setattr(deps.bigquery, "Client", lambda project: object())

    response = TestClient(app).get("/api/v1/admin/gold-versions")

    assert response.status_code == 200 and response.json() == []
