"""Secreto de la clave de Kaggle para el *re-scoring*.

Pulumi crea el secreto vacío y el permiso de lectura; el valor lo carga el
autor y no pasa por Pulumi ni por git:

    gcloud secrets versions add voc-kaggle-token --data-file=-

Solo ``voc-sa-ml-backend`` lo lee, y el Job ``voc-ml-rescoring`` lo recibe
como ``KAGGLE_API_TOKEN``.

El secreto ``voc-portal-roles`` (EPIC-7) lleva el mapa de correos a roles del
portal. Su valor sí sale de Pulumi, de la configuración cifrada
``portal_users``, y solo lo lee ``voc-sa-portal-api``:

    pulumi config set --secret portal_users \\
      '{"ana@example.com": {"roles": ["administrador"]}}'

Un cambio de personas exige subir ``portal_users_version``: la versión del
secreto lleva ese número en su nombre.
"""

import json
from dataclasses import dataclass
from typing import Annotated, Final, Literal

import pulumi
import pulumi_gcp as gcp
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
)
from voc_common import HitlTask

# Nombre del secreto, no su valor.
KAGGLE_SECRET_ID: Final = "voc-kaggle-token"  # noqa: S105  # nosec B105
PORTAL_ROLES_SECRET_ID: Final = "voc-portal-roles"  # noqa: S105  # nosec B105
PortalRole = Literal["lector", "analista", "revisor", "administrador"]
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_lower=True, pattern=r"^[^@\s]+@[^@\s]+$"
    ),
]


_EMAIL = TypeAdapter(Email)


class PortalUserEntry(BaseModel):
    """Una persona de ``portal_users``: sus roles y colas de revisión."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    roles: list[PortalRole] = Field(min_length=1)
    reviewer_tasks: list[HitlTask] = []


def parse_portal_users(raw: object) -> dict[str, PortalUserEntry]:
    """Valida ``portal_users`` (correo → entrada), con correos en minúsculas."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("portal_users debe ser un objeto correo -> roles")
    users: dict[str, PortalUserEntry] = {}
    for email, entry in raw.items():
        normalized = _EMAIL.validate_python(email)
        if normalized in users:
            raise ValueError("portal_users repite un correo")
        users[normalized] = PortalUserEntry.model_validate(entry)
    return users


def portal_roles_document(
    users: dict[str, PortalUserEntry], version: int
) -> str:
    """JSON con la forma de ``RoleMap`` de la API (``extra="forbid"``)."""
    return json.dumps(
        {
            "version": version,
            "users": {
                email: entry.model_dump(mode="json")
                for email, entry in sorted(users.items())
            },
        },
        sort_keys=True,
    )


@dataclass
class SecretResources:
    kaggle_token: gcp.secretmanager.Secret
    kaggle_accessor: gcp.secretmanager.SecretIamMember
    portal_roles: gcp.secretmanager.Secret | None = None
    portal_roles_version: gcp.secretmanager.SecretVersion | None = None
    portal_roles_accessor: gcp.secretmanager.SecretIamMember | None = None


def create_secrets(
    project_id: str,
    reader: gcp.serviceaccount.Account,
    api_deps: list[pulumi.Resource],
    *,
    portal_reader: gcp.serviceaccount.Account | None = None,
    portal_users: dict[str, PortalUserEntry] | None = None,
    portal_users_version: int = 1,
) -> SecretResources:
    opts = pulumi.ResourceOptions(depends_on=api_deps)
    secret = gcp.secretmanager.Secret(
        KAGGLE_SECRET_ID,
        project=project_id,
        secret_id=KAGGLE_SECRET_ID,
        replication={"auto": {}},
        opts=opts,
    )
    accessor = gcp.secretmanager.SecretIamMember(
        f"{KAGGLE_SECRET_ID}-ml-backend-accessor",
        project=project_id,
        secret_id=secret.secret_id,
        role="roles/secretmanager.secretAccessor",
        member=reader.email.apply(lambda email: f"serviceAccount:{email}"),
        opts=opts,
    )
    if portal_reader is None:
        return SecretResources(secret, accessor)
    roles = gcp.secretmanager.Secret(
        PORTAL_ROLES_SECRET_ID,
        project=project_id,
        secret_id=PORTAL_ROLES_SECRET_ID,
        replication={"auto": {}},
        opts=opts,
    )
    # Sin personas no hay versión: la API responde 502 hasta que se carguen.
    roles_version = (
        gcp.secretmanager.SecretVersion(
            f"{PORTAL_ROLES_SECRET_ID}-v{portal_users_version}",
            secret=roles.id,
            secret_data=pulumi.Output.secret(
                portal_roles_document(portal_users, portal_users_version)
            ),
            opts=opts,
        )
        if portal_users
        else None
    )
    roles_accessor = gcp.secretmanager.SecretIamMember(
        f"{PORTAL_ROLES_SECRET_ID}-portal-api-accessor",
        project=project_id,
        secret_id=roles.secret_id,
        role="roles/secretmanager.secretAccessor",
        member=portal_reader.email.apply(
            lambda email: f"serviceAccount:{email}"
        ),
        opts=opts,
    )
    return SecretResources(
        secret, accessor, roles, roles_version, roles_accessor
    )
