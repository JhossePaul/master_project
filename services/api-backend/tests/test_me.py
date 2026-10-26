"""``GET /api/v1/me`` y ``/healthz``."""

import pytest
from api_backend.auth import deps, iap
from api_backend.main import create_app
from api_backend.settings import ApiSettings
from api_backend.testing import (
    AUDIENCE,
    LOCAL_EMAIL,
    LOCAL_SALT,
    IapKit,
    StaticRoleSource,
    local_app,
    role_map,
)
from fastapi.testclient import TestClient
from voc_common.text_utils import actor_hash

SALT = LOCAL_SALT
EMAIL = LOCAL_EMAIL


def test_me_devuelve_roles_actor_hash_y_entorno() -> None:
    response = TestClient(local_app("revisor")).get("/api/v1/me")

    assert response.status_code == 200
    assert response.json() == {
        "email": EMAIL,
        "actor_hash": actor_hash(EMAIL, SALT),
        "roles": ["lector", "revisor"],
        "reviewer_tasks": ["sentiment", "aspects", "topic"],
        "environment": "local",
        "commit": "abc123",
    }


def test_healthz_no_pide_identidad() -> None:
    app = local_app()
    app.state.role_source = StaticRoleSource(role_map())

    response = TestClient(app).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "commit": "abc123"}


def test_correo_sin_entrada_en_el_mapa_da_403_con_formato_de_error() -> None:
    app = local_app()
    app.state.role_source = StaticRoleSource(
        role_map(**{"otra@example.com": {"roles": ["lector"]}})
    )

    response = TestClient(app).get("/api/v1/me")

    error = response.json()["error"]
    assert response.status_code == 403
    assert error["code"] == "forbidden"
    assert error["request_id"] == response.headers["x-request-id"]


def test_me_con_iap_usa_el_jwt_y_el_mapa(
    iap_kit: IapKit, monkeypatch: pytest.MonkeyPatch
) -> None:
    from functools import partial

    monkeypatch.setattr(
        deps,
        "verify_iap_jwt",
        partial(iap.verify_iap_jwt, transport=iap_kit.transport),
    )
    settings = ApiSettings.model_validate(
        {"iap_audience": AUDIENCE, "portal_data": "fixtures"}
    )
    app = create_app(settings)
    app.state.role_source = StaticRoleSource(
        role_map(**{EMAIL: {"roles": ["administrador"]}})
    )
    client = TestClient(app)

    sin_jwt = client.get("/api/v1/me")
    con_jwt = client.get(
        "/api/v1/me", headers={"x-goog-iap-jwt-assertion": iap_kit.sign()}
    )

    assert sin_jwt.status_code == 401
    assert con_jwt.status_code == 200
    assert con_jwt.json()["roles"] == ["lector", "analista", "administrador"]


def test_el_correo_no_se_registra(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TestClient(local_app()).get("/api/v1/me")

    out = capsys.readouterr().out
    assert EMAIL not in out
    assert actor_hash(EMAIL, SALT) in out
