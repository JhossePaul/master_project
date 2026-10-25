"""Secreto de la clave de Kaggle para el *re-scoring*.

Pulumi crea el secreto vacío y el permiso de lectura; el valor lo carga el
autor y no pasa por Pulumi ni por git:

    gcloud secrets versions add voc-kaggle-token --data-file=-

Solo ``voc-sa-ml-backend`` lo lee, y el Job ``voc-ml-rescoring`` lo recibe
como ``KAGGLE_API_TOKEN``.
"""

from dataclasses import dataclass
from typing import Final

import pulumi
import pulumi_gcp as gcp

# Nombre del secreto, no su valor.
KAGGLE_SECRET_ID: Final = "voc-kaggle-token"  # noqa: S105  # nosec B105


@dataclass
class SecretResources:
    kaggle_token: gcp.secretmanager.Secret
    kaggle_accessor: gcp.secretmanager.SecretIamMember


def create_secrets(
    project_id: str,
    reader: gcp.serviceaccount.Account,
    api_deps: list[pulumi.Resource],
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
    return SecretResources(secret, accessor)
