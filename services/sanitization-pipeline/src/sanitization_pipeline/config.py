"""Configuración de ejecución y preflight del Job de sanitización (EPIC-4 4.1).

El Job de Pulumi no recibe argumentos: los defaults deben ser válidos en
producción. Cada campo admite la variable `SANITIZATION_<CAMPO>` y un flag de
CLI equivalente; el flag tiene prioridad.
"""

import argparse
import os
import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from voc_common import Settings

ENV_PREFIX = "SANITIZATION_"
# Límite de Cloud DLP por solicitud de deidentify_content.
DLP_REQUEST_LIMIT_BYTES = 524_288
# Máximo admitido por Pub/Sub para ack deadlines.
PUBSUB_MAX_ACK_DEADLINE_SEC = 600
# Máximo de mensajes por solicitud `pull`.
PUBSUB_MAX_PULL_MESSAGES = 1000
# Tope de hilos de E/S: con 1 vCPU, más hilos solo añaden cambios de contexto.
MAX_IO_WORKERS = 64
# El pool HTTP nunca baja de las 10 conexiones por host de la biblioteca.
MIN_GCS_POOL_SIZE = 10
# Margen sobre los hilos para el heartbeat y las llamadas fuera del ledger.
GCS_POOL_HEADROOM = 4


def gcs_pool_size(io_workers: int) -> int:
    """Conexiones HTTP por host para que ningún hilo espere una conexión."""
    return max(MIN_GCS_POOL_SIZE, io_workers + GCS_POOL_HEADROOM)


class ExecutionMode(StrEnum):
    BATCH_PULL_SERVERLESS = "BATCH_PULL_SERVERLESS"
    GCS_BACKFILL_MANIFESTS = "GCS_BACKFILL_MANIFESTS"
    DATAFLOW_MANAGED = "DATAFLOW_MANAGED"


class PreflightError(ValueError):
    """Configuración inválida: el Job no debe hacer pull ni tocar destinos."""


class SanitizationExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    execution_mode: ExecutionMode = ExecutionMode.BATCH_PULL_SERVERLESS
    # El tiempo (`max_runtime_sec`) es el límite real; el tope de mensajes solo
    # evita corridas sin fin. Medido: ~2.5 msg/s antes de paralelizar la E/S.
    max_messages: int = Field(default=20_000, gt=0)
    # Máximo por `pull` de Pub/Sub: 1000 mensajes.
    microbatch_size: int = Field(
        default=1000, gt=0, le=PUBSUB_MAX_PULL_MESSAGES
    )
    max_runtime_sec: int = Field(default=1500, gt=0)
    # Cubre el último microbatch en vuelo (DLP + carga + MERGE + recibos).
    checkpoint_margin_sec: int = Field(default=300, gt=0)
    # Debe coincidir con el timeout de voc-sanitization-job (EPIC-2).
    container_timeout_sec: int = Field(default=1800, gt=0)
    ack_deadline_sec: int = Field(
        default=600, ge=10, le=PUBSUB_MAX_ACK_DEADLINE_SEC
    )
    ack_renew_interval_sec: int = Field(default=180, gt=0)
    # Hilos de E/S hacia GCS para el ledger. El pool HTTP del cliente se
    # dimensiona a partir de este valor (ver `gcs_pool_size`). Medido con 8: la
    # E/S del ledger fue el 68 % del tiempo (3 771 mensajes en 231 s).
    io_workers: int = Field(default=16, ge=1, le=MAX_IO_WORKERS)
    dlp_max_rows: int = Field(default=250, gt=0)
    dlp_max_bytes: int = Field(
        default=400_000, gt=0, lt=DLP_REQUEST_LIMIT_BYTES
    )
    # Por defecto, sanitización local con regex (sin costo ni dependencia de
    # DLP): en el corpus medido (evidence/) el texto del usuario no trajo PII
    # detectable. True activa Cloud DLP como capa previa (entorno corporativo).
    use_cloud_dlp_api: bool = False

    @model_validator(mode="after")
    def _budgets(self) -> Self:
        if self.microbatch_size > self.max_messages:
            raise ValueError("microbatch cannot exceed the message budget")
        if (
            self.max_runtime_sec + self.checkpoint_margin_sec
            > self.container_timeout_sec
        ):
            raise ValueError("runtime budget must leave checkpoint margin")
        if self.ack_renew_interval_sec >= self.ack_deadline_sec:
            raise ValueError("ack renewal must precede the ack deadline")
        return self


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m sanitization_pipeline.pipeline"
    )
    for name in SanitizationExecutionConfig.model_fields:
        flag = "--" + name.replace("_", "-")
        if name == "use_cloud_dlp_api":
            parser.add_argument(
                flag, action=argparse.BooleanOptionalAction, default=None
            )
        else:
            parser.add_argument(flag, dest=name, default=None)
    return parser


def load_config(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> SanitizationExecutionConfig:
    """Defaults < variables SANITIZATION_* < flags; valida invariantes."""
    environ = os.environ if environ is None else environ
    values: dict[str, object] = {}
    for name in SanitizationExecutionConfig.model_fields:
        raw = environ.get(ENV_PREFIX + name.upper())
        if raw is not None and raw.strip():
            values[name] = raw.strip()
    args = vars(_parser().parse_args(argv))
    values |= {k: v for k, v in args.items() if v is not None}
    return SanitizationExecutionConfig.model_validate(values)


def in_process_runner() -> Any:
    """Runner en proceso para `BEAM_RUNNER=DirectRunner`.

    Desde Beam 2.6x, `DirectRunner` intenta primero Prism, que descarga un
    binario en tiempo de ejecución; no hay opción para desactivarlo. El Job
    (y CI) usan directamente el FnApiRunner en proceso: sin red ni binarios.
    """
    from apache_beam.runners.portability.fn_api_runner import FnApiRunner

    return FnApiRunner()


def dlp_parent(settings: Settings) -> str:
    return f"projects/{settings.gcp_project_id}/locations/{settings.gcp_region}"


def preflight(
    config: SanitizationExecutionConfig,
    settings: Settings,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Valida el entorno antes de cualquier pull; devuelve el parent DLP."""
    environ = os.environ if environ is None else environ
    try:
        settings.require_ingestion_v2()
    except ValueError as exc:
        raise PreflightError(str(exc)) from None
    if config.execution_mode == ExecutionMode.DATAFLOW_MANAGED:
        raise PreflightError(
            "DATAFLOW_MANAGED requires provisioned Dataflow (API, worker "
            "permissions and apache-beam[gcp])"
        )
    runner = environ.get("BEAM_RUNNER", "DirectRunner")
    if runner != "DirectRunner":
        raise PreflightError("only DirectRunner is supported")
    parent = dlp_parent(settings)
    if not config.use_cloud_dlp_api:
        return parent
    for kind, name in (
        ("inspectTemplates", settings.dlp_inspect_template_id),
        ("deidentifyTemplates", settings.dlp_deidentify_template_id),
    ):
        # Plantillas regionales: deben pertenecer al mismo parent (fail-closed).
        if name is None or not re.fullmatch(
            re.escape(parent) + "/" + kind + r"/[A-Za-z0-9_-]+", name
        ):
            raise PreflightError(f"DLP {kind} must be a template in {parent}")
    return parent
