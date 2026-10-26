"""Comprueba identidades, roles exactos, CMEK y orden de aprovisionamiento."""

import runpy
from pathlib import Path

import pulumi
import pulumi_gcp as gcp
import pytest

from infra.modules.kms_iam import create_security_resources
from infra.tests.conftest import InfrastructureMonitor

_PROJECT = "test-voc-project"
_ROLES = {
    "voc-sa-ingestion": {
        "roles/pubsub.publisher",
        "roles/bigquery.dataEditor",
    },
    "voc-sa-scheduler": set(),
    "voc-sa-sanitization": {
        "roles/pubsub.subscriber",
        "roles/pubsub.viewer",
        "roles/dlp.user",
        "roles/bigquery.dataEditor",
        "roles/bigquery.jobUser",
    },
    "voc-sa-ml-backend": {
        "roles/bigquery.dataEditor",
        "roles/bigquery.jobUser",
        "roles/aiplatform.user",
        "roles/dlp.user",
    },
    "voc-sa-portal-api": {
        "roles/bigquery.jobUser",
        "roles/dlp.user",
    },
    "voc-sa-ml-online": {"roles/bigquery.jobUser"},
}


@pytest.mark.parametrize("cmek", [False, True])
def test_security_resources_and_dependencies(
    pulumi_mocks: InfrastructureMonitor, cmek: bool
) -> None:
    @pulumi.runtime.test
    def deploy() -> None:
        api = gcp.projects.Service(
            "test-iam-api", project=_PROJECT, service="iam.googleapis.com"
        )
        resources = create_security_resources(
            _PROJECT, "us-central1", cmek, [api]
        )
        assert (resources.kms_crypto_key_id is not None) is cmek
        assert (
            len(
                {
                    resources.sa_ingestion_worker,
                    resources.sa_scheduler_invoker,
                    resources.sa_sanitization_worker,
                    resources.sa_ml_and_backend,
                    resources.sa_portal_api,
                    resources.sa_ml_online,
                }
            )
            == 6
        )

    deploy()
    registrations = list(pulumi_mocks.resources.values())
    states = [r.state for r in registrations]
    accounts = [s for s in states if "accountId" in s]
    assert {s["accountId"] for s in accounts} == set(_ROLES)
    assert all(s["project"] == _PROJECT for s in accounts)

    memberships = [s for s in states if "member" in s]
    assert len(memberships) == 14
    for account, roles in _ROLES.items():
        expected_member = (
            f"serviceAccount:{account}@{_PROJECT}.iam.gserviceaccount.com"
        )
        assert {
            s["role"] for s in memberships if s["member"] == expected_member
        } == roles
    assert all(s["project"] == _PROJECT for s in memberships)

    api_urn = next(r.urn for r in registrations if "test-iam-api" in r.urn)
    for name, dependencies in pulumi_mocks.dependencies.items():
        if name != "test-iam-api":
            assert api_urn in dependencies

    rings = [r for r in registrations if "gcp:kms/keyRing:KeyRing" in r.urn]
    keys = [r for r in registrations if "gcp:kms/cryptoKey:CryptoKey" in r.urn]
    assert len(rings) == len(keys) == int(cmek)
    if cmek:
        assert rings[0].state == {
            "name": "voc-kms-keyring",
            "project": _PROJECT,
            "location": "us-central1",
        }
        key = keys[0].state
        assert key["keyRing"] == rings[0].id
        assert key["purpose"] == "ENCRYPT_DECRYPT"
        assert key["rotationPeriod"] == "7776000s"
        assert key["versionTemplate"] == {
            "algorithm": "GOOGLE_SYMMETRIC_ENCRYPTION",
            "protectionLevel": "SOFTWARE",
        }
        assert rings[0].urn in pulumi_mocks.dependencies["voc-cmek-key"]


@pytest.mark.parametrize("cmek", [False, True])
def test_entrypoint_creates_security(
    pulumi_mocks: InfrastructureMonitor, cmek: bool
) -> None:
    @pulumi.runtime.test
    def deploy() -> None:
        pulumi.runtime.set_all_config(
            {
                "gcp:project": _PROJECT,
                "gcp:region": "us-east1",
                "bbva-voc-infra:enable_cmek": str(cmek).lower(),
            }
        )
        entrypoint = Path(__file__).resolve().parents[1] / "__main__.py"
        program = runpy.run_path(str(entrypoint))
        assert (program["security"].kms_crypto_key_id is not None) is cmek

    deploy()
    registrations = list(pulumi_mocks.resources.values())
    apis = {
        r.urn for r in registrations if "gcp:projects/service:Service" in r.urn
    }
    accounts = [r for r in registrations if "serviceaccount/account" in r.urn]
    assert len(accounts) == 6
    for account in accounts:
        name = account.urn.rsplit("::", 1)[-1]
        assert apis <= pulumi_mocks.dependencies[name]
    rings = [r for r in registrations if "gcp:kms/keyRing:KeyRing" in r.urn]
    if cmek:
        assert rings[0].state["location"] == "us-east1"
    else:
        assert not rings
