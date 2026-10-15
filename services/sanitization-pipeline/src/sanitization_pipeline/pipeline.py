"""Entrypoint del Job: `python -m sanitization_pipeline.pipeline`.

Carga configuración, valida el entorno (fail-closed, 4.1) y despacha el modo
de ejecución al orquestador (4.4). `DATAFLOW_MANAGED` nunca llega aquí: el
preflight lo rechaza.
"""

import sys
from collections.abc import Callable, Mapping, Sequence

from pydantic import ValidationError
from voc_common import Settings

from sanitization_pipeline.config import (
    ExecutionMode,
    PreflightError,
    SanitizationExecutionConfig,
    load_config,
    preflight,
)
from sanitization_pipeline.fast_replay import run_fast_replay
from sanitization_pipeline.orchestrator import (
    log_json,
    run_batch_pull,
    run_manifest_backfill,
)

EX_OK = 0
EX_USAGE = 64
EX_SOFTWARE = 70
# Fallo transitorio: los mensajes sin ack se reintentan (4.4).
EX_TEMPFAIL = 75

Runner = Callable[[SanitizationExecutionConfig, Settings, str], int]
RUNNERS: dict[ExecutionMode, Runner] = {
    ExecutionMode.BATCH_PULL_SERVERLESS: run_batch_pull,
    ExecutionMode.GCS_BACKFILL_MANIFESTS: run_manifest_backfill,
    ExecutionMode.GCS_FAST_REPLAY: run_fast_replay,
}


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    settings_factory: Callable[[], Settings] = Settings,
) -> int:
    try:
        config = load_config(argv, environ)
        settings = settings_factory()
        parent = preflight(config, settings, environ)
    except (PreflightError, ValidationError, ValueError) as exc:
        detail = (
            [e["msg"] for e in exc.errors()]
            if isinstance(exc, ValidationError)
            else str(exc)
        )
        log_json("ERROR", "Invalid sanitization configuration", error=detail)
        return EX_USAGE
    runner = RUNNERS.get(config.execution_mode)
    if runner is None:
        log_json(
            "ERROR",
            "Execution mode not implemented yet",
            execution_mode=config.execution_mode.value,
        )
        return EX_SOFTWARE
    return runner(config, settings, parent)


if __name__ == "__main__":  # pragma: no cover - entrypoint del contenedor
    sys.exit(main())
