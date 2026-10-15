"""Entrypoint del Job: `python -m sanitization_pipeline.pipeline`.

Feature 4.1: carga configuración, valida el entorno (fail-closed) y despacha
el modo de ejecución. Los orquestadores de cada modo se implementan en 4.4;
hasta entonces el Job termina sin hacer pull ni escribir en ningún destino.
"""

import json
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

EX_OK = 0
EX_USAGE = 64
EX_SOFTWARE = 70
# Fallo transitorio: los mensajes sin ack se reintentan (4.4).
EX_TEMPFAIL = 75

Runner = Callable[[SanitizationExecutionConfig, Settings, str], int]
# Se completa en 4.4 con BATCH_PULL_SERVERLESS y GCS_BACKFILL_MANIFESTS.
RUNNERS: dict[ExecutionMode, Runner] = {}


def _log(severity: str, message: str, **fields: object) -> None:
    # Cloud Logging interpreta JSON de una línea; sin textos ni PII.
    print(
        json.dumps(
            {"severity": severity, "message": message, **fields},
            default=str,
            ensure_ascii=False,
        ),
        flush=True,
    )


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
        _log("ERROR", "Invalid sanitization configuration", error=detail)
        return EX_USAGE
    runner = RUNNERS.get(config.execution_mode)
    if runner is None:
        _log(
            "ERROR",
            "Execution mode not implemented yet",
            execution_mode=config.execution_mode.value,
        )
        return EX_SOFTWARE
    return runner(config, settings, parent)


if __name__ == "__main__":  # pragma: no cover - entrypoint del contenedor
    sys.exit(main())
