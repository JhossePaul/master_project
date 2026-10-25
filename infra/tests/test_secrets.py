"""Secreto de Kaggle: vacío en Pulumi y legible solo por la cuenta de ML."""

import pulumi
import pulumi_gcp as gcp

from infra.modules.secrets import KAGGLE_SECRET_ID, create_secrets
from infra.tests.conftest import InfrastructureMonitor

_PROJECT = "test-voc-project"


def test_kaggle_secret_and_its_only_reader(
    pulumi_mocks: InfrastructureMonitor,
) -> None:
    @pulumi.runtime.test
    def deploy() -> None:
        api = gcp.projects.Service(
            "test-secret-api",
            project=_PROJECT,
            service="secretmanager.googleapis.com",
        )
        reader = gcp.serviceaccount.Account(
            "voc-sa-ml-backend",
            project=_PROJECT,
            account_id="voc-sa-ml-backend",
        )
        create_secrets(_PROJECT, reader, [api])

    deploy()
    states = {
        r.urn.rsplit("::", 1)[-1]: r.state
        for r in pulumi_mocks.resources.values()
    }
    secret = states[KAGGLE_SECRET_ID]
    assert secret["secretId"] == "voc-kaggle-token"
    assert secret["replication"] == {"auto": {}}
    # Sin versiones: el valor lo carga el autor fuera de Pulumi.
    assert not any(
        "SecretVersion" in r.urn for r in pulumi_mocks.resources.values()
    )
    grants = [
        s
        for s in states.values()
        if s.get("role", "").startswith("roles/secret")
    ]
    assert grants == [
        {
            "project": _PROJECT,
            "secretId": "voc-kaggle-token",
            "role": "roles/secretmanager.secretAccessor",
            "member": "serviceAccount:voc-sa-ml-backend@test-voc-project"
            ".iam.gserviceaccount.com",
        }
    ]
    api = next(
        r.urn
        for r in pulumi_mocks.resources.values()
        if r.urn.endswith("::test-secret-api")
    )
    for name in (KAGGLE_SECRET_ID, f"{KAGGLE_SECRET_ID}-ml-backend-accessor"):
        assert api in pulumi_mocks.dependencies[name]
