"""``/api/v1/admin``: versiones nuevas, vista previa, tasas de deriva y oro."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from api_backend.auth.deps import ROUTE_ROLES
from api_backend.auth.roles import Role
from api_backend.sections.admin import router as admin_router
from api_backend.sections.admin.repository import (
    DriftMonth,
    InMemoryAdminRepository,
)
from api_backend.sections.admin.sample import sample_repository
from api_backend.sections.admin.service import next_drift_version
from api_backend.testing import LOCAL_SALT, local_app
from fastapi.testclient import TestClient
from voc_common.text_utils import actor_hash

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
ADMIN = "admin@example.com"
BASE = "risk_policy_v1"


def kit(
    roles: str = "administrador",
) -> tuple[TestClient, InMemoryAdminRepository]:
    repo = sample_repository(NOW)
    app = local_app(roles, portal_local_user=ADMIN)
    app.state.admin_repository = repo
    app.dependency_overrides[admin_router.now] = lambda: NOW
    return TestClient(app), repo


def risk_body(changes: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"base_version": BASE, "changes": changes, **extra}


# -- Apetito de riesgo -------------------------------------------------------


def test_lee_la_politica_vigente_y_su_historial() -> None:
    client, _ = kit()
    data = client.get("/api/v1/admin/risk-policy").json()

    assert data["current"]["policy_version"] == BASE
    assert [p["policy_version"] for p in data["history"]] == [BASE]


def test_la_curva_trae_el_punto_vigente_el_tiempo_y_las_subidas() -> None:
    client, _ = kit()
    data = client.get("/api/v1/admin/coverage-curve").json()

    assert data["curve"]["model_version"] == "sintetico_v1"
    assert data["current_point"]["coverage"] == 0.9
    assert (data["median_seconds"], data["timed_n"]) == (7.0, 412)
    assert [b["bank_id"] for b in data["hitl_boosts_active"]] == ["NUBANK"]


def test_la_vista_previa_lista_solo_lo_que_cambia_y_no_guarda() -> None:
    client, repo = kit()
    data = client.post(
        "/api/v1/admin/risk-policy/preview",
        json=risk_body({"hitl_target_coverage": 0.85}),
    ).json()

    fields = {d["field"]: (d["before"], d["after"]) for d in data["diff"]}
    assert fields == {
        "hitl_target_coverage": (0.9, 0.85),
        "hitl_threshold": (0.74, 0.66),
    }
    assert data["large_change"] is False and data["errors"] == []
    assert repo.writes == []


def test_cambiar_la_cobertura_recalcula_el_umbral_y_audita() -> None:
    client, repo = kit()
    response = client.post(
        "/api/v1/admin/risk-policy",
        json=risk_body(
            {"hitl_target_coverage": 0.85}, reason="prueba de la pantalla"
        ),
    )

    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["policy_version"] == "risk_policy_v2"
    assert saved["hitl_threshold"] == 0.66
    assert saved["model_version"] == "sintetico_v1"
    assert saved["set_by_hash"] == actor_hash(ADMIN, LOCAL_SALT)
    assert saved["reason"] == "prueba de la pantalla"
    assert [table for table, _ in repo.writes] == ["risk_policy"]
    again = client.get("/api/v1/admin/risk-policy").json()
    assert again["current"]["policy_version"] == "risk_policy_v2"
    assert len(again["history"]) == 2


def test_mas_de_cinco_puntos_exigen_confirmar() -> None:
    client, repo = kit()
    changes = {"hitl_target_coverage": 0.8}
    preview = client.post(
        "/api/v1/admin/risk-policy/preview", json=risk_body(changes)
    ).json()
    assert preview["large_change"] is True

    sin = client.post(
        "/api/v1/admin/risk-policy",
        json=risk_body(changes, reason="bajar la revisión"),
    )
    assert sin.status_code == 422 and "CONFIRMAR" in sin.text
    assert repo.writes == []

    con = client.post(
        "/api/v1/admin/risk-policy",
        json=risk_body(
            changes, reason="bajar la revisión", confirm_word="CONFIRMAR"
        ),
    )
    assert con.status_code == 201


def test_un_grupo_incompleto_es_error_y_422_al_guardar() -> None:
    client, repo = kit()
    changes = {"drift_boost_days": 7}
    preview = client.post(
        "/api/v1/admin/risk-policy/preview", json=risk_body(changes)
    ).json()
    assert preview["proposed"] is None and preview["errors"]

    response = client.post(
        "/api/v1/admin/risk-policy",
        json=risk_body(changes, reason="subida incompleta"),
    )
    assert response.status_code == 422
    assert repo.writes == []


def test_el_grupo_completo_se_guarda() -> None:
    client, _ = kit()
    response = client.post(
        "/api/v1/admin/risk-policy",
        json=risk_body(
            {
                "drift_boost_coverage": 0.95,
                "drift_boost_days": 7,
                "drift_boost_weekly_cap": 300,
            },
            reason="subida por deriva",
        ),
    )

    assert response.status_code == 201
    assert response.json()["drift_boost_days"] == 7


def test_una_base_vieja_da_409() -> None:
    client, repo = kit()
    response = client.post(
        "/api/v1/admin/risk-policy",
        json={
            "base_version": "risk_policy_v0",
            "changes": {"retrain_kappa_floor": 0.9},
            "reason": "base vieja",
        },
    )

    assert response.status_code == 409
    assert repo.writes == []


def test_el_motivo_corto_y_los_campos_del_sistema_se_rechazan() -> None:
    client, _ = kit()
    corto = client.post(
        "/api/v1/admin/risk-policy",
        json=risk_body({"retrain_kappa_floor": 0.9}, reason="corto"),
    )
    assert corto.status_code == 422
    sistema = client.post(
        "/api/v1/admin/risk-policy",
        json=risk_body({"hitl_threshold": 0.1}, reason="forzar el umbral"),
    )
    assert sistema.status_code == 422


def test_el_disparo_automatico_avisa() -> None:
    client, _ = kit()
    data = client.post(
        "/api/v1/admin/risk-policy/preview",
        json=risk_body({"retrain_trigger": "auto"}),
    ).json()

    assert any("Kaggle" in w for w in data["warnings"])


# -- Deriva ------------------------------------------------------------------


def test_la_politica_de_deriva_se_compara_con_su_plantilla() -> None:
    client, _ = kit()
    data = client.get(
        "/api/v1/admin/drift-policy", params={"bank": "BBVA"}
    ).json()

    assert data["current"]["drift_policy_version"] == "drift_policy_v1_BBVA"
    assert data["template"]["template_version"] == "drift_template_v1"
    assert data["diff_vs_template"] == []


def months(z: list[float]) -> list[DriftMonth]:
    return [
        DriftMonth("neg_share", f"2025-{i + 1:02d}", value, None)
        for i, value in enumerate(z)
    ]


def test_las_tasas_propuestas_coinciden_con_un_calculo_a_mano() -> None:
    client, repo = kit()
    # 4 meses; |z| >= 4 en dos; |z| >= 3 en tres; |z| >= 2 en cuatro.
    repo.months["BBVA"] = months([5.0, -4.5, 3.2, 1.0])
    response = client.post(
        "/api/v1/admin/drift-policy/rates",
        json={"bank": "BBVA", "thresholds": {"z": {"neg_share": 3.0}}},
    )

    assert response.status_code == 200
    (row,) = response.json()["series"]
    assert row["series"] == "neg_share"
    assert (row["months"], row["current_alerts"], row["proposed_alerts"]) == (
        4,
        2,
        3,
    )
    assert (row["current_per_year"], row["proposed_per_year"]) == (6.0, 9.0)
    assert row["reference"] == 1.1


def test_guardar_deriva_crea_la_version_del_banco() -> None:
    client, repo = kit()
    response = client.post(
        "/api/v1/admin/drift-policy",
        json={
            "bank": "BBVA",
            "base_version": "drift_policy_v1_BBVA",
            "changes": {
                "thresholds": {
                    "z": {"neg_share": 3.0},
                    "psi": {"length_distribution": 0.25},
                }
            },
            "reason": "z 3 en la proporción negativa",
        },
    )

    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["drift_policy_version"] == "drift_policy_v2_BBVA"
    assert saved["template_version"] == "drift_template_v1"
    assert saved["thresholds"]["z"] == {"neg_share": 3.0}
    assert saved["set_by_hash"] == actor_hash(ADMIN, LOCAL_SALT)
    assert [t for t, _ in repo.writes] == ["drift_policy"]
    stale = client.post(
        "/api/v1/admin/drift-policy",
        json={
            "bank": "BBVA",
            "base_version": "drift_policy_v1_BBVA",
            "changes": {"entry_months": 6},
            "reason": "base vieja",
        },
    )
    assert stale.status_code == 409


def test_la_politica_de_deriva_rechaza_campos_ajenos() -> None:
    client, _ = kit()
    response = client.post(
        "/api/v1/admin/drift-policy",
        json={
            "bank": "BBVA",
            "base_version": "drift_policy_v1_BBVA",
            "changes": {"bank_id": "OTRO"},
            "reason": "campo ajeno",
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        ("drift_policy_v1_BBVA", "drift_policy_v2_BBVA"),
        ("drift_policy_v9_BBVA", "drift_policy_v10_BBVA"),
        ("drift_policy_v2_nubank", "drift_policy_v3_nubank"),
        ("raro", "raro_v2"),
    ],
)
def test_siguiente_version_de_deriva(current: str, expected: str) -> None:
    assert next_drift_version(current) == expected


# -- Oro ---------------------------------------------------------------------

CRITERIA = {
    "submitted_from": (NOW - timedelta(days=30)).date().isoformat(),
    "submitted_to": NOW.date().isoformat(),
    "guideline_version": "v2.2",
}


def test_los_criterios_excluyen_no_evaluable_y_la_segunda_ronda() -> None:
    client, repo = kit()
    before = client.post(
        "/api/v1/admin/gold-versions/preview", json=CRITERIA
    ).json()
    assert before["total"] == 12
    first, second = repo.reviews[0].item_id, repo.reviews[1].item_id
    repo.review_meta[first]["flags"] = ["no_evaluable"]
    repo.review_meta[second]["review_round"] = 2

    after = client.post(
        "/api/v1/admin/gold-versions/preview", json=CRITERIA
    ).json()
    assert after["total"] == 10
    assert sum(c["n"] for c in after["by_bank"]) == 10
    assert sum(c["n"] for c in after["by_label"]) == 10
    segunda = client.post(
        "/api/v1/admin/gold-versions/preview",
        json={**CRITERIA, "review_round": 2},
    )
    assert segunda.status_code == 422


def test_crear_una_version_del_oro_y_reproducir_sus_items() -> None:
    client, repo = kit()
    response = client.post(
        "/api/v1/admin/gold-versions",
        json={"criteria": CRITERIA, "reason": "muestra del tercer trimestre"},
    )

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["version"]["gold_version"] == "gold_hitl_v1"
    assert created["version"]["items"] == 12
    assert created["version"]["cutoff_at"].startswith("2026-10-26T12:00")
    assert created["reason"] == "muestra del tercer trimestre"
    assert [t for t, _ in repo.writes] == ["gold_versions"]

    # Una revisión posterior al corte no entra en sus ítems.
    late = repo.reviews[0].__class__(
        item_id="monitor_sample:2026Q4:syn-late:sintetico_v1",
        id_resena="syn-late",
        bank_id="BBVA",
        validated_label="NEG",
        submitted_at=NOW + timedelta(hours=1),
        reviewer_hash="b" * 64,
    )
    repo.reviews.append(late)
    repo.review_meta[late.item_id] = {"guideline_version": "v2.2"}
    items = client.get("/api/v1/admin/gold-versions/gold_hitl_v1/items").json()
    assert len(items["items"]) == 12
    assert set(items["items"][0]) == {
        "item_id",
        "id_resena",
        "validated_label",
        "submitted_at",
        "reviewer",
    }
    assert items["items"][0]["reviewer"] == "a" * 8

    second = client.post(
        "/api/v1/admin/gold-versions",
        json={"criteria": CRITERIA, "reason": "segunda versión"},
    ).json()
    assert second["version"]["gold_version"] == "gold_hitl_v2"
    listed = client.get("/api/v1/admin/gold-versions").json()
    assert [v["version"]["gold_version"] for v in listed] == [
        "gold_hitl_v1",
        "gold_hitl_v2",
    ]


def test_una_version_sin_revisiones_o_inexistente_falla() -> None:
    client, _ = kit()
    vacio = client.post(
        "/api/v1/admin/gold-versions",
        json={
            "criteria": {**CRITERIA, "guideline_version": "v9"},
            "reason": "no hay nada que incluir",
        },
    )
    assert vacio.status_code == 422
    assert (
        client.get("/api/v1/admin/gold-versions/gold_hitl_v7/items").status_code
        == 404
    )
    al_reves = client.post(
        "/api/v1/admin/gold-versions/preview",
        json={**CRITERIA, "submitted_from": "2026-12-01"},
    )
    assert al_reves.status_code == 422


# -- Roles -------------------------------------------------------------------


def admin_routes() -> list[tuple[str, str]]:
    return sorted(
        key
        for key, role in ROUTE_ROLES.items()
        if role is Role.ADMINISTRADOR and key[1].startswith("/api/v1/admin")
    )


@pytest.mark.parametrize("roles", ["analista", "lector", "revisor"])
def test_quien_no_es_administrador_recibe_403_en_todas_las_rutas(
    roles: str,
) -> None:
    client, repo = kit(roles)
    routes = admin_routes()

    assert len(routes) == 11
    for method, path in routes:
        url = path.replace("{gold_version}", "gold_hitl_v1")
        response = client.request(method, url, json={})
        assert response.status_code == 403, (method, path)
    assert repo.writes == []
