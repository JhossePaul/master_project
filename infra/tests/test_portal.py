"""API y portal (EPIC-7): cuenta, permisos por tabla, roles, IAP y accesos."""

import hashlib
import json
import runpy
from pathlib import Path
from typing import Any

import pulumi
import pytest
from pydantic import ValidationError

from infra.modules.analytics_bq import PORTAL_WRITABLE_TABLES
from infra.modules.secrets import (
    PORTAL_ROLES_SECRET_ID,
    PortalUserEntry,
    parse_portal_users,
    portal_roles_document,
)
from infra.tests.conftest import (
    API_BACKEND_IMAGE,
    ML_INFERENCE_IMAGE,
    WORKLOAD_CONFIG,
    InfrastructureMonitor,
)
from infra.tests.conftest import unwrap_outputs as _unwrap

PROJECT = "test-voc-project"
PORTAL_MEMBER = (
    f"serviceAccount:voc-sa-portal-api@{PROJECT}.iam.gserviceaccount.com"
)
USERS = {
    "Ana@Example.com": {"roles": ["administrador"]},
    "rev@up.edu.mx": {"roles": ["revisor"], "reviewer_tasks": ["sentiment"]},
}


def deploy_program(
    monitor: InfrastructureMonitor, extra: dict[str, str] | None = None
) -> dict[str, Any]:
    states: dict[str, Any] = {}

    @pulumi.runtime.test
    def deploy() -> None:
        pulumi.runtime.set_all_config(
            {
                "gcp:project": PROJECT,
                "gcp:region": "us-central1",
                **WORKLOAD_CONFIG,
                "bbva-voc-infra:user_hash_salt": "test-salt-1234567890",
                **(extra or {}),
            },
            secret_keys=["bbva-voc-infra:user_hash_salt"],
        )
        runpy.run_path(str(Path(__file__).resolve().parents[1] / "__main__.py"))

    deploy()
    for r in monitor.resources.values():
        states[r.urn.rsplit("::", 1)[-1]] = _unwrap(r.state)
    return states


def portal_config(users: dict[str, Any]) -> dict[str, str]:
    return {"bbva-voc-infra:portal_users": json.dumps(users)}


def test_la_cuenta_solo_lee_y_escribe_donde_debe(
    pulumi_mocks: InfrastructureMonitor,
) -> None:
    states = deploy_program(pulumi_mocks)

    assert states["voc-sa-portal-api"]["accountId"] == "voc-sa-portal-api"
    project_roles = {
        s["role"]
        for s in states.values()
        if s.get("member") == PORTAL_MEMBER
        and "dataset" not in s.get("role", "")
    }
    assert {"roles/bigquery.jobUser", "roles/dlp.user"} <= project_roles
    viewer = states["voc-portal-dataset-viewer"]
    assert viewer["role"] == "roles/bigquery.dataViewer"
    assert viewer["datasetId"] == "bbva_voc_tds"
    assert "tableId" not in viewer
    editors = {
        s["tableId"]: s
        for name, s in states.items()
        if name.startswith("voc-portal-") and name.endswith("-editor")
    }
    assert set(editors) == set(PORTAL_WRITABLE_TABLES)
    assert all(
        e["role"] == "roles/bigquery.dataEditor"
        and e["member"] == PORTAL_MEMBER
        for e in editors.values()
    )
    # Ni predicciones ni métricas de EPIC-6 son escribibles por el portal.
    assert not {"review_predictions", "drift_metrics", "kpi_estimates"} & set(
        editors
    )
    # Nunca dataEditor ni a nivel de proyecto ni del dataset.
    project_level = [
        s
        for s in states.values()
        if s.get("member") == PORTAL_MEMBER
        and s.get("role") == "roles/bigquery.dataEditor"
        and "tableId" not in s
    ]
    assert project_level == []


def test_el_servicio_va_con_iap_y_su_propia_cuenta(
    pulumi_mocks: InfrastructureMonitor,
) -> None:
    states = deploy_program(pulumi_mocks)

    api = states["voc-api-backend"]
    assert api["iapEnabled"] is True
    assert api["ingress"] == "INGRESS_TRAFFIC_ALL"
    template = api["template"]
    assert template["serviceAccount"].startswith("voc-sa-portal-api@")
    assert template["timeout"] == "300s"
    assert template["scaling"] == {"minInstanceCount": 0, "maxInstanceCount": 2}
    container = template["containers"][0]
    assert container["image"] == API_BACKEND_IMAGE
    assert container["resources"]["limits"] == {"cpu": "1", "memory": "1Gi"}
    env = {e["name"]: e["value"] for e in container["envs"]}
    assert env["PORTAL_AUTH_MODE"] == "iap"
    assert env["PORTAL_DATA"] == "bigquery"
    assert env["PORTAL_ROLES_SECRET"] == PORTAL_ROLES_SECRET_ID
    assert env["GCP_PROJECT_ID"] == PROJECT
    assert env["BQ_DATASET_ID"] == "bbva_voc_tds"
    assert env["GCS_RAW_DATALAKE_BUCKET"] == "voc-datalake-test-voc-project"
    assert env["IAP_AUDIENCE"] == (
        "/projects/123/locations/us-central1/services/voc-api-backend"
    )
    assert env["DLP_INSPECT_TEMPLATE"] and env["DLP_DEIDENTIFY_TEMPLATE"]
    # Sin el entorno de la ingesta: la API no necesita proxies ni Pub/Sub.
    assert not {"SCRAPER_PAGE_SIZE", "PUBSUB_RAW_REVIEWS_TOPIC"} & set(env)


def test_los_servicios_existentes_no_cambian(
    pulumi_mocks: InfrastructureMonitor,
) -> None:
    states = deploy_program(pulumi_mocks)

    worker = states["voc-ingestion-worker"]
    assert "iapEnabled" not in worker and "ingress" not in worker
    assert worker["template"]["timeout"] == "900s"


def test_el_agente_de_iap_invoca_y_cada_persona_entra(
    pulumi_mocks: InfrastructureMonitor,
) -> None:
    states = deploy_program(pulumi_mocks, portal_config(USERS))

    invoker = states["voc-api-iap-invoker"]
    assert invoker["role"] == "roles/run.invoker"
    assert invoker["member"] == (
        "serviceAccount:service-123@gcp-sa-iap.iam.gserviceaccount.com"
    )
    accessors = {
        name: s
        for name, s in states.items()
        if name.startswith("voc-portal-iap-")
    }
    assert len(accessors) == 2
    assert {s["member"] for s in accessors.values()} == {
        "user:ana@example.com",
        "user:rev@up.edu.mx",
    }
    assert all(
        s["role"] == "roles/iap.httpsResourceAccessor"
        and s["cloudRunServiceName"] == "voc-api-backend"
        for s in accessors.values()
    )
    # El nombre del recurso lleva un hash, no el correo.
    expected = hashlib.sha256(b"ana@example.com").hexdigest()[:10]
    assert f"voc-portal-iap-{expected}" in accessors
    assert not any("example.com" in name for name in states)
    assert all(s.get("member") != "allUsers" for s in states.values())


def test_sin_personas_no_hay_accesos_ni_version_de_roles(
    pulumi_mocks: InfrastructureMonitor,
) -> None:
    states = deploy_program(pulumi_mocks)

    assert not [n for n in states if n.startswith("voc-portal-iap-")]
    assert PORTAL_ROLES_SECRET_ID in states
    assert not [
        n for n in states if n.startswith(f"{PORTAL_ROLES_SECRET_ID}-v")
    ]


def test_el_secreto_de_roles_lo_lee_solo_la_cuenta_del_portal(
    pulumi_mocks: InfrastructureMonitor,
) -> None:
    states = deploy_program(
        pulumi_mocks,
        {**portal_config(USERS), "bbva-voc-infra:portal_users_version": "3"},
    )

    secret = states[PORTAL_ROLES_SECRET_ID]
    assert secret["secretId"] == "voc-portal-roles"
    accessor = states[f"{PORTAL_ROLES_SECRET_ID}-portal-api-accessor"]
    assert accessor["member"] == PORTAL_MEMBER
    assert accessor["secretId"] == "voc-portal-roles"
    version = states[f"{PORTAL_ROLES_SECRET_ID}-v3"]
    assert json.loads(version["secretData"]) == {
        "version": 3,
        "users": {
            "ana@example.com": {
                "roles": ["administrador"],
                "reviewer_tasks": [],
            },
            "rev@up.edu.mx": {
                "roles": ["revisor"],
                "reviewer_tasks": ["sentiment"],
            },
        },
    }


def test_documento_de_roles_tiene_la_forma_del_mapa_de_la_api() -> None:
    users = parse_portal_users({"A@b.c": {"roles": ["lector"]}})

    document = json.loads(portal_roles_document(users, 2))

    assert document == {
        "version": 2,
        "users": {"a@b.c": {"roles": ["lector"], "reviewer_tasks": []}},
    }
    assert set(document["users"]["a@b.c"]) == set(PortalUserEntry.model_fields)


@pytest.mark.parametrize(
    "raw",
    [
        {"sin-arroba": {"roles": ["lector"]}},
        {"a@b.c": {"roles": []}},
        {"a@b.c": {"roles": ["superusuario"]}},
        {"a@b.c": {"roles": ["lector"], "extra": 1}},
        {"a@b.c": {"roles": ["lector"]}, "A@B.C": {"roles": ["lector"]}},
        ["a@b.c"],
    ],
)
def test_portal_users_invalido_se_rechaza(raw: object) -> None:
    with pytest.raises((ValueError, ValidationError)):
        parse_portal_users(raw)


def test_sin_portal_users_el_mapa_es_vacio() -> None:
    assert parse_portal_users(None) == {}


ML_ONLINE_MEMBER = (
    f"serviceAccount:voc-sa-ml-online@{PROJECT}.iam.gserviceaccount.com"
)


def test_sin_imagen_de_ml_no_hay_servicio_en_linea(
    pulumi_mocks: InfrastructureMonitor,
) -> None:
    states = deploy_program(pulumi_mocks)

    assert "voc-ml-online" not in states
    env = {
        e["name"]
        for e in states["voc-api-backend"]["template"]["containers"][0]["envs"]
    }
    assert "ML_ONLINE_URL" not in env


def test_el_servicio_en_linea_es_privado_y_solo_la_api_lo_invoca(
    pulumi_mocks: InfrastructureMonitor,
) -> None:
    states = deploy_program(
        pulumi_mocks, {"bbva-voc-infra:ml_inference_image": ML_INFERENCE_IMAGE}
    )

    online = states["voc-ml-online"]
    assert "iapEnabled" not in online
    template = online["template"]
    assert template["serviceAccount"].startswith("voc-sa-ml-online@")
    assert template["timeout"] == "120s"
    assert template["scaling"] == {"minInstanceCount": 0, "maxInstanceCount": 1}
    assert template["maxInstanceRequestConcurrency"] == 4
    container = template["containers"][0]
    assert container["image"] == ML_INFERENCE_IMAGE
    assert container["args"] == ["serve"]
    assert container["resources"]["limits"] == {"cpu": "2", "memory": "4Gi"}
    invokers = [
        s
        for s in states.values()
        if s.get("role") == "roles/run.invoker"
        and s.get("name") == "voc-ml-online"
    ]
    assert [s["member"] for s in invokers] == [PORTAL_MEMBER]
    assert all(s.get("member") != "allUsers" for s in states.values())
    api_env = {
        e["name"]
        for e in states["voc-api-backend"]["template"]["containers"][0]["envs"]
    }
    assert "ML_ONLINE_URL" in api_env


def test_la_cuenta_en_linea_solo_lee_pesos_y_model_versions(
    pulumi_mocks: InfrastructureMonitor,
) -> None:
    states = deploy_program(pulumi_mocks)

    grants = [s for s in states.values() if s.get("member") == ML_ONLINE_MEMBER]
    roles = sorted(s["role"] for s in grants)
    assert roles == [
        "roles/bigquery.dataViewer",
        "roles/bigquery.jobUser",
        "roles/storage.objectViewer",
    ]
    viewer = next(s for s in grants if s["role"] == "roles/bigquery.dataViewer")
    assert "tableId" in viewer  # por tabla, no el dataset
    pesos = next(s for s in grants if s["role"] == "roles/storage.objectViewer")
    assert "ml_artifacts/" in pesos["condition"]["expression"]
