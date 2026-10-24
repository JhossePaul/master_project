"""Activación de APIs de GCP sin deshabilitarlas al destruir el stack."""

import pulumi_gcp as gcp

_BASE_APIS: tuple[str, ...] = (
    "iam.googleapis.com",
    # Política IAM del proyecto: crear o borrar un projects.IAMMember.
    "cloudresourcemanager.googleapis.com",
    "pubsub.googleapis.com",
    "storage.googleapis.com",
    "bigquery.googleapis.com",
    "dlp.googleapis.com",
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    # Canal de correo y políticas de los avisos.
    "monitoring.googleapis.com",
)


def enable_project_apis(
    project_id: str,
    enable_cmek: bool = False,
    enable_vertex_ai_api: bool = False,
) -> dict[str, gcp.projects.Service]:
    """Devuelve recursos por API para dependencias de módulos posteriores.

    `enable_vertex_ai_api` habilita la API de Vertex AI (Gemini y Model
    Registry), sin endpoints dedicados: se retiraron con el índice de 768
    dimensiones (P8-6, EPIC-6).
    """
    apis = list(_BASE_APIS)
    if enable_cmek:
        apis.append("cloudkms.googleapis.com")
    if enable_vertex_ai_api:
        apis.append("aiplatform.googleapis.com")

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
