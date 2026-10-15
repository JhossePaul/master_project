"""Recursos Vertex opcionales; BigQuery sigue siendo el modo por defecto."""

from dataclasses import dataclass

import pulumi
import pulumi_gcp as gcp


@dataclass
class VertexResources:
    endpoint: gcp.vertex.AiEndpoint | None = None
    index: gcp.vertex.AiIndex | None = None


def create_vertex_resources(
    project_id: str,
    region: str,
    bucket_name: pulumi.Output[str],
    enable_dedicated_endpoints: bool,
    *,
    api_deps: list[pulumi.Resource] | None = None,
) -> VertexResources:
    """El índice batch requiere embeddings cargados en vertex/embeddings/."""
    if not enable_dedicated_endpoints:
        return VertexResources()
    opts = pulumi.ResourceOptions(depends_on=api_deps or [])
    endpoint = gcp.vertex.AiEndpoint(
        "delora-tnss-endpoint",
        display_name="delora-tnss-endpoint",
        project=project_id,
        location=region,
        region=region,
        opts=opts,
    )
    index = gcp.vertex.AiIndex(
        "voc-vector-search-index",
        display_name="voc-vector-search-index",
        project=project_id,
        region=region,
        index_update_method="BATCH_UPDATE",
        metadata={
            "contents_delta_uri": pulumi.Output.concat(
                "gs://", bucket_name, "/vertex/embeddings/"
            ),
            "config": {
                "dimensions": 768,
                "distance_measure_type": "COSINE_DISTANCE",
                "algorithm_config": {"brute_force_config": {}},
            },
        },
        opts=opts,
    )
    return VertexResources(endpoint, index)
