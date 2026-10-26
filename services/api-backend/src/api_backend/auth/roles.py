"""Roles del portal: el mapa correo → roles y sus fuentes."""

import json
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator
from voc_common import HitlTask

from api_backend.errors import ApiError, ErrorCode
from api_backend.settings import ApiSettings

ROLE_MAP_TTL_SECONDS = 300


class Role(StrEnum):
    LECTOR = "lector"
    ANALISTA = "analista"
    REVISOR = "revisor"
    ADMINISTRADOR = "administrador"


class PortalUser(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    roles: list[Role] = Field(min_length=1)
    reviewer_tasks: list[HitlTask] = []


class RoleMap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    users: dict[str, PortalUser]  # correo en minúsculas -> roles

    @field_validator("users")
    @classmethod
    def _lowercase_emails(
        cls, users: dict[str, PortalUser]
    ) -> dict[str, PortalUser]:
        return {email.strip().lower(): user for email, user in users.items()}


class RoleSource(Protocol):
    def load(self) -> RoleMap: ...


def effective_roles(roles: list[Role]) -> frozenset[Role]:
    """Un rol incluye al lector; el administrador incluye al analista."""
    granted = {Role.LECTOR, *roles}
    if Role.ADMINISTRADOR in granted:
        granted.add(Role.ANALISTA)
    return frozenset(granted)


class LocalRoleSource:
    """Un solo usuario de ``PORTAL_LOCAL_USER`` (solo en modo local)."""

    def __init__(self, settings: ApiSettings) -> None:
        roles = [Role(name) for name in settings.portal_local_roles]
        self._map = RoleMap(
            version=0,
            users={
                settings.portal_local_user: PortalUser(
                    roles=roles or [Role.LECTOR],
                    reviewer_tasks=list(HitlTask),
                )
            },
        )

    def load(self) -> RoleMap:
        return self._map


class SecretManagerRoleSource:
    """Lee la última versión del secreto con el mapa de roles."""

    def __init__(
        self, project_id: str, secret: str, client: Any | None = None
    ) -> None:
        self._name = f"projects/{project_id}/secrets/{secret}/versions/latest"
        self._client = client

    def load(self) -> RoleMap:
        try:
            if self._client is None:  # perezoso: abre credenciales al usarse
                from google.cloud import secretmanager

                self._client = secretmanager.SecretManagerServiceClient()
            response = self._client.access_secret_version(name=self._name)
            return RoleMap.model_validate(
                json.loads(response.payload.data.decode("utf-8"))
            )
        except Exception as exc:  # noqa: BLE001  # red, permiso o JSON roto
            raise ApiError(
                ErrorCode.UPSTREAM, "no se pudo leer el mapa de roles"
            ) from exc


class CachedRoleSource:
    """Guarda el mapa ``ttl`` segundos; un fallo no borra el último bueno."""

    def __init__(
        self,
        inner: RoleSource,
        ttl: float = ROLE_MAP_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._ttl = ttl
        self._clock = clock
        self._value: RoleMap | None = None
        self._loaded_at = 0.0

    def load(self) -> RoleMap:
        now = self._clock()
        if self._value is None or now - self._loaded_at >= self._ttl:
            self._value = self._inner.load()
            self._loaded_at = now
        return self._value


def build_role_source(settings: ApiSettings) -> RoleSource:
    if settings.portal_auth_mode == "local":
        return LocalRoleSource(settings)
    return CachedRoleSource(
        SecretManagerRoleSource(
            settings.gcp_project_id, settings.portal_roles_secret
        )
    )
