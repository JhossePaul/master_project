"""Principal de cada petición y las dependencias que exigen un rol."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from voc_common import HitlTask
from voc_common.text_utils import actor_hash

from api_backend.auth.iap import IAP_JWT_HEADER, verify_iap_jwt
from api_backend.auth.roles import (
    Role,
    RoleSource,
    build_role_source,
    effective_roles,
)
from api_backend.errors import ApiError, ErrorCode
from api_backend.settings import ApiSettings, get_settings

# (método, ruta) -> rol mínimo; cada router registra las suyas y la prueba del
# centinela recorre las de rol lector.
ROUTE_ROLES: dict[tuple[str, str], Role] = {}


@dataclass(frozen=True)
class Principal:
    email: str
    actor_hash: str
    roles: frozenset[Role]
    reviewer_tasks: frozenset[HitlTask]


Settings = Annotated[ApiSettings, Depends(get_settings)]


def get_role_source(request: Request, settings: Settings) -> RoleSource:
    state = request.app.state
    if getattr(state, "role_source", None) is None:
        state.role_source = build_role_source(settings)
    return state.role_source


def current_principal(request: Request, settings: Settings) -> Principal:
    if settings.portal_auth_mode == "local":
        email = settings.portal_local_user.strip().lower()
    else:
        token = request.headers.get(IAP_JWT_HEADER, "")
        email = verify_iap_jwt(token, settings.iap_audience).email
    # La fuente de roles se arma después de autenticar: sin identidad no hay
    # por qué abrir clientes de GCP.
    user = get_role_source(request, settings).load().users.get(email)
    if user is None:
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "Tu cuenta no tiene acceso; pide acceso al autor",
        )
    hashed = actor_hash(email, settings.user_hash_salt)
    request.state.actor_hash = hashed  # lo usa el registro de la petición
    return Principal(
        email=email,
        actor_hash=hashed,
        roles=effective_roles(user.roles),
        reviewer_tasks=frozenset(user.reviewer_tasks),
    )


Current = Annotated[Principal, Depends(current_principal)]


def require(*roles: Role) -> Callable[..., Principal]:
    """403 si el principal no tiene ninguno de los roles."""

    def dependency(principal: Current) -> Principal:
        if roles and principal.roles.isdisjoint(roles):
            raise ApiError(ErrorCode.FORBIDDEN, "No tienes permiso para esto")
        return principal

    return dependency


def require_reviewer(task: HitlTask) -> Callable[..., Principal]:
    """Exige el rol de revisor y la tarea en sus ``reviewer_tasks``."""

    def dependency(principal: Current) -> Principal:
        if Role.REVISOR not in principal.roles or (
            task not in principal.reviewer_tasks
        ):
            raise ApiError(
                ErrorCode.FORBIDDEN, "No tienes permiso para esta cola"
            )
        return principal

    return dependency
