"""Mapa de roles, sus fuentes y las dependencias que exigen un rol."""

import json
from dataclasses import dataclass
from functools import partial
from typing import Annotated

import pytest
from api_backend.auth.deps import (
    Principal,
    current_principal,
    get_role_source,
    require,
    require_reviewer,
)
from api_backend.auth.roles import (
    CachedRoleSource,
    LocalRoleSource,
    PortalUser,
    Role,
    RoleMap,
    SecretManagerRoleSource,
    effective_roles,
)
from api_backend.errors import ApiError, ErrorCode
from api_backend.settings import ApiSettings, get_settings
from api_backend.testing import AUDIENCE, IapKit, role_map
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError
from voc_common import HitlTask
from voc_common.text_utils import actor_hash

SALT = "s" * 16
ANALISTA = require(Role.ANALISTA)
COLA_SENTIMIENTO = require_reviewer(HitlTask.SENTIMENT)


def test_mapa_pasa_correos_a_minusculas() -> None:
    mapa = role_map(**{"Ana@Example.com": {"roles": ["lector"]}})

    assert list(mapa.users) == ["ana@example.com"]


def test_mapa_rechaza_campos_extra_y_roles_vacios() -> None:
    with pytest.raises(ValidationError):
        RoleMap.model_validate(
            {"version": 1, "users": {"a@b.c": {"roles": []}}}
        )
    with pytest.raises(ValidationError):
        PortalUser.model_validate({"roles": ["lector"], "extra": 1})


def test_un_rol_incluye_al_lector_y_el_admin_al_analista() -> None:
    assert effective_roles([Role.REVISOR]) == {Role.LECTOR, Role.REVISOR}
    assert effective_roles([Role.ADMINISTRADOR]) == {
        Role.LECTOR,
        Role.ANALISTA,
        Role.ADMINISTRADOR,
    }
    assert Role.REVISOR not in effective_roles([Role.ADMINISTRADOR])


class FakeSecretClient:
    def __init__(self, payload: bytes | Exception) -> None:
        self.payload = payload
        self.names: list[str] = []

    def access_secret_version(self, name: str):
        self.names.append(name)
        if isinstance(self.payload, Exception):
            raise self.payload

        @dataclass
        class Data:
            data: bytes

        @dataclass
        class Response:
            payload: Data

        return Response(Data(self.payload))


def test_secret_manager_lee_la_ultima_version() -> None:
    body = json.dumps(
        {"version": 3, "users": {"A@b.c": {"roles": ["analista"]}}}
    ).encode()
    client = FakeSecretClient(body)

    mapa = SecretManagerRoleSource("p", "voc-portal-roles", client).load()

    assert client.names == [
        "projects/p/secrets/voc-portal-roles/versions/latest"
    ]
    assert mapa.users["a@b.c"].roles == [Role.ANALISTA]


@pytest.mark.parametrize("payload", [b"no es json", RuntimeError("sin red")])
def test_secret_manager_con_fallo_da_502(payload: bytes | Exception) -> None:
    source = SecretManagerRoleSource("p", "s", FakeSecretClient(payload))

    with pytest.raises(ApiError) as caught:
        source.load()

    assert caught.value.code is ErrorCode.UPSTREAM


class CountingSource:
    def __init__(self) -> None:
        self.calls = 0

    def load(self) -> RoleMap:
        self.calls += 1
        return role_map(**{"a@b.c": {"roles": ["lector"]}})


def test_cache_de_cinco_minutos() -> None:
    now = [0.0]
    inner = CountingSource()
    source = CachedRoleSource(inner, ttl=300, clock=lambda: now[0])

    source.load()
    now[0] = 299
    source.load()
    assert inner.calls == 1
    now[0] = 300
    source.load()
    assert inner.calls == 2


def local_settings(**extra: object) -> ApiSettings:
    return ApiSettings.model_validate(
        {
            "environment": "local",
            "portal_auth_mode": "local",
            "portal_local_user": "Ana@Example.com",
            "portal_data": "fixtures",
            "user_hash_salt": SALT,
            **extra,
        }
    )


def test_fuente_local_da_todas_las_tareas() -> None:
    settings = local_settings(portal_local_roles=["revisor"])

    mapa = LocalRoleSource(settings).load()

    user = mapa.users["ana@example.com"]
    assert user.roles == [Role.REVISOR]
    assert set(user.reviewer_tasks) == set(HitlTask)


def test_fuente_local_sin_roles_es_lector() -> None:
    mapa = LocalRoleSource(local_settings()).load()

    assert mapa.users["ana@example.com"].roles == [Role.LECTOR]


def build_app(settings: ApiSettings, mapa: RoleMap | None = None) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_settings] = lambda: settings
    if mapa is not None:
        app.state.role_source = CachedRoleSource(_Static(mapa))

    @app.exception_handler(ApiError)
    async def handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": exc.code}}, status_code=exc.status_code
        )

    @app.get("/me")
    def me(principal: Annotated[Principal, Depends(current_principal)]):
        return {
            "actor_hash": principal.actor_hash,
            "roles": sorted(principal.roles),
        }

    @app.get("/analista")
    def analista(_: Annotated[Principal, Depends(ANALISTA)]):
        return {}

    @app.get("/cola")
    def cola(_: Annotated[Principal, Depends(COLA_SENTIMIENTO)]):
        return {}

    return app


class _Static:
    def __init__(self, mapa: RoleMap) -> None:
        self._mapa = mapa

    def load(self) -> RoleMap:
        return self._mapa


def iap_settings() -> ApiSettings:
    return ApiSettings.model_validate(
        {
            "iap_audience": AUDIENCE,
            "portal_data": "fixtures",
            "user_hash_salt": SALT,
        }
    )


def test_me_en_modo_local_da_roles_y_actor_hash() -> None:
    client = TestClient(build_app(local_settings()))

    response = client.get("/me")

    assert response.status_code == 200
    assert response.json() == {
        "actor_hash": actor_hash("ana@example.com", SALT),
        "roles": ["lector"],
    }
    assert "ana@example.com" not in response.text


def test_correo_sin_entrada_en_el_mapa_da_403() -> None:
    mapa = role_map(**{"otra@example.com": {"roles": ["lector"]}})
    client = TestClient(build_app(local_settings(), mapa))

    response = client.get("/me")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_iap_sin_jwt_da_401_aunque_traiga_el_encabezado_de_correo() -> None:
    client = TestClient(build_app(iap_settings()))

    response = client.get(
        "/me",
        headers={
            "x-goog-authenticated-user-email": "accounts.google.com:a@b.c"
        },
    )

    assert response.status_code == 401


def test_iap_con_jwt_valido_usa_el_correo_firmado(
    iap_kit: IapKit, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api_backend.auth import deps, iap

    monkeypatch.setattr(
        deps,
        "verify_iap_jwt",
        partial(iap.verify_iap_jwt, transport=iap_kit.transport),
    )
    mapa = role_map(**{"ana@example.com": {"roles": ["analista"]}})
    client = TestClient(build_app(iap_settings(), mapa))

    response = client.get(
        "/analista", headers={"x-goog-iap-jwt-assertion": iap_kit.sign()}
    )

    assert response.status_code == 200


def test_require_niega_sin_el_rol_y_admite_al_administrador() -> None:
    lector = role_map(**{"ana@example.com": {"roles": ["lector"]}})
    admin = role_map(**{"ana@example.com": {"roles": ["administrador"]}})

    assert (
        TestClient(build_app(local_settings(), lector))
        .get("/analista")
        .status_code
        == 403
    )
    assert (
        TestClient(build_app(local_settings(), admin))
        .get("/analista")
        .status_code
        == 200
    )


@pytest.mark.parametrize(
    ("user", "status"),
    [
        ({"roles": ["revisor"], "reviewer_tasks": ["sentiment"]}, 200),
        ({"roles": ["revisor"], "reviewer_tasks": ["aspects"]}, 403),
        ({"roles": ["administrador"], "reviewer_tasks": ["sentiment"]}, 403),
        ({"roles": ["analista"]}, 403),
    ],
)
def test_require_reviewer_exige_rol_y_tarea(
    user: dict[str, object], status: int
) -> None:
    mapa = role_map(**{"ana@example.com": user})

    response = TestClient(build_app(local_settings(), mapa)).get("/cola")

    assert response.status_code == status


def test_get_role_source_se_crea_una_vez_en_modo_local() -> None:
    app = build_app(local_settings())
    TestClient(app).get("/me")
    first = app.state.role_source

    TestClient(app).get("/me")

    assert app.state.role_source is first
    assert isinstance(first, LocalRoleSource)
    assert get_role_source.__name__ == "get_role_source"


def test_sin_identidad_no_se_arma_la_fuente_de_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api_backend.auth import deps

    def boom(settings: ApiSettings) -> None:
        raise AssertionError("no debía armarse")

    monkeypatch.setattr(deps, "build_role_source", boom)

    response = TestClient(build_app(iap_settings())).get("/me")

    assert response.status_code == 401


def test_secret_manager_crea_su_cliente_al_usarse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from google.cloud import secretmanager

    body = json.dumps({"version": 1, "users": {}}).encode()
    made: list[FakeSecretClient] = []

    def factory() -> FakeSecretClient:
        made.append(FakeSecretClient(body))
        return made[0]

    monkeypatch.setattr(secretmanager, "SecretManagerServiceClient", factory)
    source = SecretManagerRoleSource("p", "s")

    assert made == []
    assert source.load().users == {}
    source.load()
    assert len(made) == 1


def test_sin_credenciales_la_fuente_da_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from google.cloud import secretmanager

    def factory() -> None:
        raise RuntimeError("sin credenciales")

    monkeypatch.setattr(secretmanager, "SecretManagerServiceClient", factory)

    with pytest.raises(ApiError) as caught:
        SecretManagerRoleSource("p", "s").load()

    assert caught.value.code is ErrorCode.UPSTREAM
