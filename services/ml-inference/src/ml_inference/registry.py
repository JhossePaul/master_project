"""Registro y promoción de modelos de sentimiento.

Vertex Model Registry guarda cada versión con su ``artifact_uri`` en
``ml_artifacts/`` y el alias ``produccion`` apunta a la vigente. El
contenedor de *serving* que exige el registro es la imagen de
``ml-inference``, que nunca se despliega como endpoint: predecir en lote
sale más barato (``docs/analytics/scale/scale_report.md``).
``model_versions`` en BigQuery es la fuente que lee el delta: cada cambio
de estado es una fila nueva.
"""

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

from voc_common.analytics_codes import ModelStatus
from voc_common.operations_v3 import ModelVersion
from voc_common.policies import HitlCoverageCurve

from ml_inference.bq_io import StagingMergeWriter
from ml_inference.config import InferenceSettings
from ml_inference.state import load_state

log = logging.getLogger(__name__)

DISPLAY_NAME: Final = "robertuito-sentiment"
PRODUCTION_ALIAS: Final = "produccion"


def _aiplatform() -> Any:
    from google.cloud import aiplatform

    return aiplatform


def _parent(aiplatform: Any) -> Any | None:
    found = aiplatform.Model.list(filter=f'display_name="{DISPLAY_NAME}"')
    return found[0] if found else None


def register(
    settings: InferenceSettings,
    writer: StagingMergeWriter,
    *,
    weights_uri: str,
    model_version: str,
    calibration_version: str,
    calibration_t: float,
    curve: HitlCoverageCurve,
    metrics: Mapping[str, float],
    serving_image: str,
    base_checkpoint: str,
    training_data: str,
    license_name: str,
    now: datetime,
) -> ModelVersion:
    """Sube una versión candidata al registro y la anota en BigQuery."""
    aiplatform = _aiplatform()
    aiplatform.init(
        project=settings.gcp_project_id, location=settings.gcp_region
    )
    parent = _parent(aiplatform)
    aiplatform.Model.upload(
        display_name=DISPLAY_NAME,
        artifact_uri=weights_uri,
        serving_container_image_uri=serving_image,
        parent_model=parent.resource_name if parent else None,
        is_default_version=parent is None,
        version_aliases=[model_version],
        labels={"calibration": calibration_version.replace(".", "_")},
    )
    row = ModelVersion(
        model_version=model_version,
        registry_uri=weights_uri,
        base_checkpoint=base_checkpoint,
        training_data=training_data,
        calibration_version=calibration_version,
        calibration_t=calibration_t,
        kappa_dev=metrics.get("kappa_dev"),
        ece_dev=metrics.get("ece_dev"),
        aurc_dev=metrics.get("aurc_dev"),
        license=license_name,
        status=ModelStatus.CANDIDATE,
        recorded_at=now,
    )
    run_id = f"register-{model_version}"
    writer.write(
        "model_versions",
        [row],
        ["model_version", "status", "recorded_at"],
        run_id,
    )
    writer.write(
        "hitl_coverage_curves",
        [curve],
        ["model_version", "calibration_version", "computed_at"],
        run_id,
    )
    return row


def promote(
    settings: InferenceSettings,
    writer: StagingMergeWriter,
    bigquery: Any,
    *,
    model_version: str,
    actor_hash: str,
    reason: str,
    now: datetime,
) -> ModelVersion:
    """Mueve ``produccion`` a ``model_version`` y retira la anterior.

    También sirve de *rollback*: promover la versión anterior no re-predice,
    porque sus filas siguen en ``review_predictions``.
    """
    aiplatform = _aiplatform()
    aiplatform.init(
        project=settings.gcp_project_id, location=settings.gcp_region
    )
    parent = _parent(aiplatform)
    if parent is None:
        raise LookupError(f"{DISPLAY_NAME} is not in the model registry")
    version = aiplatform.Model(
        model_name=f"{parent.resource_name}@{model_version}"
    )
    aiplatform.models.ModelRegistry(
        model=parent.resource_name
    ).add_version_aliases(
        new_aliases=[PRODUCTION_ALIAS], version=version.version_id
    )
    candidates = latest_versions(bigquery, settings.dataset)
    if model_version not in candidates:
        raise LookupError(f"{model_version} is not in model_versions")
    rows = []
    for name, current in candidates.items():
        if name != model_version and current.status is ModelStatus.PROMOTED:
            rows.append(
                current.model_copy(
                    update={
                        "status": ModelStatus.RETIRED,
                        "recorded_at": now,
                    }
                )
            )
    promoted = candidates[model_version].model_copy(
        update={
            "status": ModelStatus.PROMOTED,
            "promoted_at": now,
            "promoted_by_hash": actor_hash,
            "recorded_at": now,
        }
    )
    rows.append(promoted)
    writer.write(
        "model_versions",
        rows,
        ["model_version", "status", "recorded_at"],
        f"promote-{model_version}",
    )
    log.info("promovido %s: %s", model_version, reason)
    return promoted


def resolve(bigquery: Any, settings: InferenceSettings) -> ModelVersion:
    """La versión que lee el delta: la promovida en ``model_versions``."""
    return load_state(bigquery, settings.dataset).model


def latest_versions(bigquery: Any, dataset: str) -> dict[str, ModelVersion]:
    """Última fila de cada versión en ``model_versions``."""
    from ml_inference.bq_io import query_rows, render

    rows = query_rows(
        bigquery,
        render(
            "SELECT * FROM `${ds}.model_versions` WHERE TRUE "
            "QUALIFY ROW_NUMBER() OVER "
            "(PARTITION BY model_version ORDER BY recorded_at DESC) = 1",
            ds=dataset,
        ),
    )
    return {r["model_version"]: ModelVersion.model_validate(r) for r in rows}
