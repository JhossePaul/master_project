"""Cloud Run Job histórico: `python -m ingestion_worker.job`.

Continúa un plan persistido por la API (nunca crea ni extiende planes). Los
identificadores llegan por overrides validados (`INGESTION_BANK_ID`,
`INGESTION_PLAN_ID`, `INGESTION_STREAM_ID` opcional) o por argumentos locales.
El código de salida distingue pausas normales de fallos reintentables o que
requieren intervención; `max_retries` del Job solo reintenta los segundos.
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from collections.abc import Sequence

from voc_common import BankKey, IngestionMode, Settings

from ingestion_worker.runner import ExtractionRequest, ExtractionStatus
from ingestion_worker.runtime import IngestionRuntime

_LOG = logging.getLogger(__name__)

EX_OK = 0
EX_FAILED = 1
EX_USAGE = 64
EX_TEMPFAIL = 75
EX_TERMINATED = 143

EXIT_CODES = {
    # Fin o pausa con checkpoint: la siguiente ejecución continúa el plan.
    ExtractionStatus.TARGET_REACHED: EX_OK,
    ExtractionStatus.SOURCE_EXHAUSTED_OBSERVED: EX_OK,
    ExtractionStatus.BUDGET_EXHAUSTED: EX_OK,
    ExtractionStatus.PAUSED_BACKLOG: EX_OK,
    # Reintentar de inmediato contra un límite del origen no ayuda.
    ExtractionStatus.PARTIAL_RATE_LIMITED: EX_OK,
    # Transitorios: el reintento del Job reanuda desde el respaldo.
    ExtractionStatus.PUBLICATION_INCOMPLETE: EX_TEMPFAIL,
    ExtractionStatus.TRANSPORT_ERROR: EX_TEMPFAIL,
    ExtractionStatus.LEASE_CONFLICT: EX_TEMPFAIL,
    # Requieren revisión humana o del adaptador.
    ExtractionStatus.RECOVERY_REQUIRED: EX_FAILED,
    ExtractionStatus.PROTOCOL_ERROR: EX_FAILED,
    ExtractionStatus.BLOCKED: EX_FAILED,
}


def _log(severity: str, message: str, **fields: object) -> None:
    # Cloud Logging interpreta JSON de una línea; sin cursores ni textos.
    print(
        json.dumps(
            {"severity": severity, "message": message, **fields},
            default=str,
            ensure_ascii=False,
        ),
        flush=True,
    )


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m ingestion_worker.job")
    parser.add_argument("--bank", default=os.getenv("INGESTION_BANK_ID"))
    parser.add_argument("--plan-id", default=os.getenv("INGESTION_PLAN_ID"))
    parser.add_argument(
        "--stream-id", default=os.getenv("INGESTION_STREAM_ID") or None
    )
    return parser.parse_args(argv)


async def run_job(
    runtime: IngestionRuntime,
    bank: BankKey,
    plan_id: str,
    stream_id: str | None = None,
) -> int:
    repo = runtime.repository
    snapshot = await asyncio.to_thread(repo.load, bank)
    if plan_id not in snapshot.catalog.plans:
        _log("ERROR", "Historical plan is not persisted", plan_id=plan_id)
        return EX_USAGE
    plan = repo.get_plan(snapshot, plan_id)
    mode = (
        IngestionMode.FULL_BACKFILL
        if plan.requested_lower_at is None
        else IngestionMode.BACKFILL
    )
    request = ExtractionRequest(
        bank_id=bank,
        mode=mode,
        plan_id=plan_id,
        stream_id=stream_id,
        create_plan=False,
    )
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    if task is not None:
        # SIGTERM de Cloud Run: cancelación best effort; el respaldo y el
        # ledger permiten que la siguiente ejecución continúe.
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        async with runtime.extractor() as extractor:
            result = await extractor.run_extraction(request)
    except asyncio.CancelledError:
        _log("WARNING", "Historical run terminated", plan_id=plan_id)
        return EX_TERMINATED
    finally:
        if task is not None:
            loop.remove_signal_handler(signal.SIGTERM)
    delivered = await runtime.flush_audits(bank)
    _log(
        "INFO" if EXIT_CODES[result.status] == EX_OK else "WARNING",
        "Historical run finished",
        run_id=result.run_id,
        bank_id=bank.value,
        plan_id=plan_id,
        stream_ids=result.stream_ids,
        status=result.status.value,
        reason=result.reason,
        pages_committed=result.pages_committed,
        reviews_published=result.reviews_published,
        requests=result.requests,
        recovery_requests=result.recovery_requests,
        recovery_actions=result.recovery_actions,
        audits_delivered=delivered,
    )
    return EXIT_CODES[result.status]


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    if not args.bank or not args.plan_id:
        _log("ERROR", "INGESTION_BANK_ID and INGESTION_PLAN_ID are required")
        return EX_USAGE
    try:
        bank = BankKey(args.bank)
        settings = Settings()
        settings.require_ingestion_v2()
        request = ExtractionRequest(
            bank_id=bank,
            mode=IngestionMode.BACKFILL,
            plan_id=args.plan_id,
            stream_id=args.stream_id,
        )
    except ValueError as exc:
        _log("ERROR", "Invalid historical job configuration", error=str(exc))
        return EX_USAGE
    runtime = IngestionRuntime.from_settings(settings)
    return asyncio.run(
        run_job(runtime, bank, request.plan_id or "", request.stream_id)
    )


if __name__ == "__main__":  # pragma: no cover - entrypoint del contenedor
    sys.exit(main())
