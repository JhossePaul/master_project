"""API de ingesta: progreso, incremental acotado y lanzamiento del histórico.

El incremental se ejecuta dentro de la petición con el presupuesto del perfil
HTTP (780 s < timeout 900 s). Los históricos nunca corren aquí: la API persiste
el plan y lanza el Cloud Run Job, que continúa el plan bajo su propio lease.
"""

import asyncio
import logging
from dataclasses import asdict
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from google.api_core.exceptions import GoogleAPICallError
from google.cloud import storage
from voc_common import (
    BankKey,
    IngestionMode,
    IngestionRequestPayload,
    SequentialBatchIngestionRequest,
    Settings,
    log_event,
)

from ingestion_worker.runner import (
    ExtractionRequest,
    ExtractionResult,
    ExtractionStatus,
)
from ingestion_worker.runtime import (
    CloudRunJobLauncher,
    IngestionRuntime,
    LaunchError,
    execution_config,
    storage_layout,
)
from ingestion_worker.watermark_store import (
    IntegrityError,
    LeaseConflict,
    StateConflict,
    WatermarkRepository,
)

_LOG = logging.getLogger(__name__)


@lru_cache
def get_repository() -> WatermarkRepository:
    settings = Settings()
    settings.require_ingestion_v2()
    return WatermarkRepository(
        storage.Client(project=settings.gcp_project_id),
        settings.gcs_raw_datalake_bucket,
        layout=storage_layout(settings),
        lease_duration_sec=settings.ingestion_lease_duration_sec,
    )


@lru_cache
def _runtime() -> IngestionRuntime:
    return IngestionRuntime.from_settings(Settings())


def get_runtime() -> IngestionRuntime:
    try:
        return _runtime()
    except (ValueError, GoogleAPICallError):
        raise HTTPException(
            status_code=503, detail="Ingestion v2 is not available"
        ) from None


def _view(result: ExtractionResult) -> dict[str, Any]:
    # Solo IDs, contadores y fechas: el resultado no contiene cursores.
    return jsonable_encoder(asdict(result))


def _run_status(result: ExtractionResult) -> int:
    return 409 if result.status == ExtractionStatus.LEASE_CONFLICT else 200


async def _incremental(
    runtime: IngestionRuntime,
    bank: BankKey,
    max_reviews: int,
    **config: Any,
) -> ExtractionResult:
    profile = execution_config(runtime.settings, **config)
    async with runtime.extractor(profile) as extractor:
        result = await extractor.run_extraction(
            ExtractionRequest(
                bank_id=bank,
                mode=IngestionMode.INCREMENTAL,
                max_reviews=max_reviews,
            )
        )
    await runtime.flush_audits(bank)
    return result


async def _launch_historical(
    runtime: IngestionRuntime, payload: IngestionRequestPayload
) -> JSONResponse:
    settings = runtime.settings
    try:
        settings.require_ingestion_v2(historical=True)
    except ValueError:
        raise HTTPException(
            status_code=503, detail="Historical Job is not configured"
        ) from None
    if payload.partition_by_stars and payload.mode == IngestionMode.BACKFILL:
        # Particiones con cota anual pueden no certificar cierre (3.4).
        raise HTTPException(
            status_code=422, detail="Star partitions require FULL_BACKFILL"
        )
    stars = (1, 2, 3, 4, 5) if payload.partition_by_stars else (None,)
    request = ExtractionRequest(
        bank_id=payload.bank_id, mode=payload.mode, star_filters=stars
    )
    try:
        async with runtime.extractor() as extractor:
            plan = await extractor.prepare_plan(request)
    except (LeaseConflict, StateConflict):
        raise HTTPException(
            status_code=409, detail="Bank has an active ingestion lease"
        ) from None
    except ValueError:
        raise HTTPException(
            status_code=409, detail="Request conflicts with the persisted plan"
        ) from None
    body: dict[str, Any] = {
        "bank_id": payload.bank_id.value,
        "mode": payload.mode.value,
        "plan_id": plan.plan_id,
        "plan_status": plan.status.value,
        "stream_ids": list(plan.stream_ids),
        "requested_lower_at": plan.requested_lower_at,
        "launched": False,
        "execution": None,
        "operation": None,
    }
    if runtime.launcher is None:
        runtime.launcher = CloudRunJobLauncher.from_settings(settings)
    try:
        launch = await asyncio.to_thread(
            runtime.launcher.launch, payload.bank_id, plan.plan_id, None
        )
    except LaunchError:
        raise HTTPException(
            status_code=502, detail="Historical Job launch failed"
        ) from None
    body |= {"launched": True, **launch}
    return JSONResponse(status_code=202, content=jsonable_encoder(body))


def create_app(
    repository: WatermarkRepository | None = None,
    *,
    runtime: IngestionRuntime | None = None,
) -> FastAPI:
    app = FastAPI(title="Ingestion worker")
    if runtime is not None:
        repository = repository or runtime.repository
        app.dependency_overrides[get_runtime] = lambda: runtime
    if repository is not None:
        app.dependency_overrides[get_repository] = lambda: repository

    @app.get("/health")
    def health() -> dict[str, str]:
        # Vida del proceso; no consulta GCP ni el origen.
        return {"status": "ok"}

    @app.get("/api/v1/watermarks/{bank_id}")
    def watermark(
        bank_id: BankKey,
        repo: Annotated[WatermarkRepository, Depends(get_repository)],
    ) -> dict:
        try:
            return repo.progress(bank_id)
        except (IntegrityError, StateConflict, GoogleAPICallError, ValueError):
            raise HTTPException(
                status_code=503, detail="Ingestion state unavailable"
            ) from None

    @app.post("/api/v1/ingest")
    async def ingest(
        payload: IngestionRequestPayload,
        rt: Annotated[IngestionRuntime, Depends(get_runtime)],
    ) -> JSONResponse:
        if payload.page_size != rt.settings.scraper_page_size:
            # El tamaño forma parte del contexto: cambiarlo crea otro stream.
            raise HTTPException(
                status_code=422, detail="page_size is fixed by deployment"
            )
        if payload.mode != IngestionMode.INCREMENTAL:
            return await _launch_historical(rt, payload)
        result = await _incremental(
            rt, payload.bank_id, payload.max_reviews_per_run
        )
        return JSONResponse(
            status_code=_run_status(result), content=_view(result)
        )

    @app.post("/api/v1/ingest/all")
    async def ingest_all(
        payload: SequentialBatchIngestionRequest,
        rt: Annotated[IngestionRuntime, Depends(get_runtime)],
    ) -> JSONResponse:
        if payload.mode != IngestionMode.INCREMENTAL:
            # Los históricos se lanzan bajo demanda, nunca por cron.
            raise HTTPException(
                status_code=422, detail="Sequential runs are incremental only"
            )
        settings = rt.settings
        started = rt.monotonic()
        total = settings.ingestion_max_runtime_sec
        minimum = 2 * settings.scraper_timeout_sec
        banks = list(dict.fromkeys(payload.banks))
        results: list[dict[str, Any]] = []
        for index, bank in enumerate(banks):
            if index:
                await rt.sleep(payload.inter_bank_delay_sec)
            # Reparto equitativo del presupuesto restante de la petición.
            share = (total - (rt.monotonic() - started)) / (len(banks) - index)
            if share < minimum:
                results.append(
                    {"bank_id": bank.value, "status": "SKIPPED_BUDGET"}
                )
                continue
            runtime_sec = int(share)
            try:
                result = await _incremental(
                    rt,
                    bank,
                    payload.max_reviews_per_bank,
                    ingestion_max_runtime_sec=runtime_sec,
                    ingestion_max_backoff_sec=min(
                        settings.ingestion_max_backoff_sec, runtime_sec / 2
                    ),
                )
            except Exception as exc:
                # Un banco con estado ilegible no debe frenar a los demás.
                log_event(
                    "ERROR",
                    "Bank run failed",
                    bank_id=bank.value,
                    error=type(exc).__name__,
                )
                results.append(
                    {
                        "bank_id": bank.value,
                        "status": "ERROR",
                        "error": type(exc).__name__,
                    }
                )
                continue
            results.append(_view(result))
        failed = any(r.get("status") == "ERROR" for r in results)
        # 500 si algún banco falló, para que Scheduler lo marque como fallido,
        # pero todos los bancos ya corrieron.
        return JSONResponse(
            status_code=500 if failed else 200,
            content={"mode": payload.mode.value, "results": results},
        )

    return app


app = create_app()
