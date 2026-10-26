"""Ayudas para las pruebas: transporte falso de IAP y mapas de roles."""

import json
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import FastAPI

from api_backend.auth.roles import RoleMap
from api_backend.main import create_app
from api_backend.settings import ApiSettings

AUDIENCE = "/projects/1/locations/us-central1/services/voc-api-backend"
KEY_ID = "test-key"


@dataclass
class FakeResponse:
    status: int
    data: bytes


class FakeTransport:
    """Sustituye la descarga de las claves públicas de IAP."""

    def __init__(self, public_pem: str) -> None:
        self._body = json.dumps({KEY_ID: public_pem}).encode()

    def __call__(
        self, url: str, method: str = "GET", **_: object
    ) -> FakeResponse:
        return FakeResponse(200, self._body)


@dataclass
class IapKit:
    transport: FakeTransport
    other_transport: FakeTransport  # claves que no firmaron el JWT
    sign: Callable[..., str]


def role_map(**users: dict[str, object]) -> RoleMap:
    return RoleMap.model_validate({"version": 1, "users": users})


class StaticRoleSource:
    """Fuente de roles con un mapa fijo."""

    def __init__(self, mapa: RoleMap) -> None:
        self._mapa = mapa

    def load(self) -> RoleMap:
        return self._mapa


LOCAL_EMAIL = "ana@example.com"
LOCAL_SALT = "s" * 16


def local_app(roles: str = "analista", **extra: object) -> FastAPI:
    """App en modo local con datos sintéticos y un solo usuario."""
    settings = ApiSettings.model_validate(
        {
            "environment": "local",
            "portal_auth_mode": "local",
            "portal_local_user": LOCAL_EMAIL,
            "portal_local_roles": roles,
            "portal_data": "fixtures",
            "user_hash_salt": LOCAL_SALT,
            "build_commit": "abc123",
            **extra,
        }
    )
    return create_app(settings)
