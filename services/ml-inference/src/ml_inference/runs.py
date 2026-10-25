"""Filas de ``inference_runs``: inicio y cierre de cada corrida.

Las corridas largas (backfill de tópicos y entrenamiento) escriben una fila
``running`` al empezar y otra con su estado final al terminar, con el mismo
``run_id``; así quien las lanza sabe si hay una en curso sin preguntar a
Cloud Run. Una fila ``running`` sin cierre y más vieja que el tiempo máximo
de su Job es de una corrida que murió sin registrarse (por ejemplo, por
memoria): no cuenta como en curso.
"""

from datetime import datetime, timedelta
from typing import Any, Final

from voc_common.analytics_codes import RunKind, RunStatus
from voc_common.operations_v3 import InferenceRun

from ml_inference.bq_io import StagingMergeWriter, query_rows, render

RUN_KEY: Final = ("run_id", "status")

RUNNING_SQL: Final = """
SELECT COUNT(*) AS running
FROM `${ds}.inference_runs` AS r
WHERE r.kind = @kind AND r.status = 'running' AND r.started_at >= @since
  AND (@version IS NULL OR r.topic_model_version = @version)
  AND NOT EXISTS (
    SELECT 1 FROM `${ds}.inference_runs` AS f
    WHERE f.run_id = r.run_id AND f.status != 'running'
  )
"""


def write_run(writer: StagingMergeWriter, run: InferenceRun) -> int:
    return writer.write("inference_runs", [run], list(RUN_KEY), run.run_id)


def start_row(run: InferenceRun) -> InferenceRun:
    """La fila de inicio de ``run``: sin cierre ni conteos."""
    return run.model_copy(
        update={
            "status": RunStatus.RUNNING,
            "ended_at": None,
            "reviews": 0,
            "texts": 0,
            "cost_usd": None,
            "peak_memory_mib": None,
        }
    )


def running(
    client: Any,
    dataset: str,
    kind: RunKind,
    now: datetime,
    max_age: timedelta,
    topic_model_version: str | None = None,
) -> bool:
    """Si hay una corrida de ``kind`` (y de esa versión) en curso."""
    rows = query_rows(
        client,
        render(RUNNING_SQL, ds=dataset),
        {
            "kind": kind.value,
            "since": now - max_age,
            "version": topic_model_version,
        },
    )
    return bool(rows) and int(rows[0]["running"]) > 0
