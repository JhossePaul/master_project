"""Mocks compartidos: recursos, outputs calculados y dependencias Pulumi."""

from typing import Any

import pulumi
import pytest
from pulumi.runtime import rpc
from pulumi.runtime.mocks import MockMonitor
from voc_common.bq_schema import ANALYTICS_V3_TABLES

from infra.modules.analytics_bq import VIEWS

REGISTRY = "us-central1-docker.pkg.dev/test-voc-project/voc-containers-repo"


def digest_image(service: str, fill: str = "a") -> str:
    """Referencia inmutable como la publica Cloud Build (tag SHA + digest)."""
    return f"{REGISTRY}/{service}:0123abc@sha256:{fill * 64}"


INGESTION_IMAGE = digest_image("ingestion-worker", "a")
SANITIZATION_IMAGE = digest_image("sanitization-pipeline", "b")
API_BACKEND_IMAGE = digest_image("api-backend", "c")
ML_INFERENCE_IMAGE = digest_image("ml-inference", "d")
# Tablas con esquema del dataset (EPIC-2 y EPIC-6) y vistas v3.
BQ_TABLES = frozenset(
    {"sanitized_reviews_tds", "ingestion_runs_log_v2", *ANALYTICS_V3_TABLES}
)
BQ_VIEWS = frozenset(VIEWS)
# Fase 2: cargas Cloud Run/Scheduler con todas las imágenes publicadas.
WORKLOAD_CONFIG = {
    "bbva-voc-infra:deploy_workloads": "true",
    "bbva-voc-infra:ingestion_worker_image": INGESTION_IMAGE,
    "bbva-voc-infra:sanitization_job_image": SANITIZATION_IMAGE,
    "bbva-voc-infra:api_backend_image": API_BACKEND_IMAGE,
}


class InfrastructureMocks(pulumi.runtime.Mocks):
    def __init__(self) -> None:
        self.records: list[pulumi.runtime.MockResourceArgs] = []

    def new_resource(
        self, args: pulumi.runtime.MockResourceArgs
    ) -> tuple[str, dict[str, Any]]:
        self.records.append(args)
        outputs = dict(args.inputs)
        if args.typ == "gcp:cloudrunv2/service:Service":
            outputs["uri"] = f"https://{args.name}.run.app"
        if args.typ == "gcp:serviceaccount/account:Account":
            outputs["email"] = (
                f"{outputs['accountId']}@{outputs['project']}.iam.gserviceaccount.com"
            )
        if args.typ == "gcp:monitoring/notificationChannel:NotificationChannel":
            outputs["name"] = (
                f"projects/{outputs['project']}/notificationChannels/{args.name}"
            )
        if args.typ == "gcp:projects/serviceIdentity:ServiceIdentity":
            outputs["email"] = (
                "service-123@gcp-sa-pubsub.iam.gserviceaccount.com"
            )
        return f"{args.name}-id", outputs

    def call(self, args: pulumi.runtime.MockCallArgs) -> dict[str, Any]:
        if (
            args.token
            == "gcp:storage/getProjectServiceAccount:getProjectServiceAccount"  # noqa: S105
        ):
            return {
                "project": args.args["project"],
                "emailAddress": (
                    "service-123@gs-project-accounts.iam.gserviceaccount.com"
                ),
            }
        if (
            args.token
            == "gcp:bigquery/getDefaultServiceAccount:getDefaultServiceAccount"  # noqa: S105
        ):
            return {
                "project": args.args["project"],
                "email": "bq-123@bigquery-encryption.iam.gserviceaccount.com",
            }
        raise AssertionError(
            f"No se esperan llamadas al proveedor: {args.token}"
        )


class InfrastructureMonitor(MockMonitor):
    def __init__(self, mocks: InfrastructureMocks) -> None:
        super().__init__(mocks)
        self.dependencies: dict[str, set[str]] = {}

    def RegisterResource(self, request: Any) -> Any:  # noqa: N802
        self.dependencies[request.name] = set(request.dependencies)
        return super().RegisterResource(request)


@pytest.fixture(autouse=True)
def pulumi_mocks() -> InfrastructureMonitor:
    mocks = InfrastructureMocks()
    monitor = InfrastructureMonitor(mocks)
    pulumi.runtime.set_mocks(
        mocks, project="bbva-voc-infra", stack="dev", monitor=monitor
    )
    pulumi.runtime.set_all_config({"gcp:project": "test-voc-project"})
    return monitor


def unwrap_outputs(value: Any) -> Any:
    """Inspecciona outputs simulados propagados como secretos por Pulumi."""
    if rpc.is_rpc_secret(value):
        return unwrap_outputs(rpc.unwrap_rpc_secret(value))
    if isinstance(value, dict):
        return {k: unwrap_outputs(v) for k, v in value.items()}
    if isinstance(value, list):
        return [unwrap_outputs(v) for v in value]
    return value


def assert_acyclic(monitor: InfrastructureMonitor) -> None:
    """El grafo completo debe poder ordenarse sin ciclos entre recursos."""
    names = {
        r.urn: r.urn.rsplit("::", 1)[-1] for r in monitor.resources.values()
    }
    graph = {
        name: {names[urn] for urn in dependencies if urn in names}
        for name, dependencies in monitor.dependencies.items()
    }
    visited: set[str] = set()
    active: set[str] = set()

    def visit(name: str) -> None:
        assert name not in active, f"Dependencia circular en {name}"
        if name in visited:
            return
        active.add(name)
        for dependency in graph.get(name, set()):
            visit(dependency)
        active.remove(name)
        visited.add(name)

    for name in graph:
        visit(name)
