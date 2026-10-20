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
    enable_vertex_ai_api: bool = False,
) -> dict[str, gcp.projects.Service]:
    """Devuelve recursos por API para dependencias de módulos posteriores.

    `enable_vertex_ai_api` solo habilita la API (p. ej., Gemini para el
    etiquetado de EPIC-5), sin endpoints ni Dataflow. Ambos flags comparten el
    recurso `api-aiplatform`, así que pasar de uno a otro no lo reemplaza.
    """
    apis = list(_BASE_APIS)
    if enable_cmek:
        apis.append("cloudkms.googleapis.com")
    if enable_vertex or enable_vertex_ai_api:
        apis.append("aiplatform.googleapis.com")
    if enable_vertex:
        apis.append("dataflow.googleapis.com")

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
