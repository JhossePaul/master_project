"""Activación de APIs de GCP sin deshabilitarlas al destruir el stack."""

import pulumi_gcp as gcp

_BASE_APIS: tuple[str, ...] = (
    "iam.googleapis.com",
    "pubsub.googleapis.com",
    "storage.googleapis.com",
    "bigquery.googleapis.com",
    "dlp.googleapis.com",
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
)


def enable_project_apis(
    project_id: str,
    enable_cmek: bool = False,
    enable_vertex: bool = False,
) -> dict[str, gcp.projects.Service]:
    """Devuelve recursos por API para dependencias de módulos posteriores."""
    apis = list(_BASE_APIS)
    if enable_cmek:
        apis.append("cloudkms.googleapis.com")
    if enable_vertex:
        apis.extend(("aiplatform.googleapis.com", "dataflow.googleapis.com"))

    return {
        api: gcp.projects.Service(
            f"api-{api.removesuffix('.googleapis.com')}",
            project=project_id,
            service=api,
            disable_dependent_services=False,
            disable_on_destroy=False,
        )
        for api in apis
    }
