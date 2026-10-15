"""Read-only progress endpoint; extraction/launch endpoints belong to 3.5."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from google.api_core.exceptions import GoogleAPICallError
from google.cloud import storage
from voc_common import BankKey, IngestionStorageLayout, Settings

from ingestion_worker.watermark_store import (
    IntegrityError,
    StateConflict,
    WatermarkRepository,
)


@lru_cache
def get_repository() -> WatermarkRepository:
    settings = Settings()
    settings.require_ingestion_v2()
    return WatermarkRepository(
        storage.Client(project=settings.gcp_project_id),
        settings.gcs_raw_datalake_bucket,
        layout=IngestionStorageLayout.model_validate(
            {
                key: getattr(settings, key)
                for key in IngestionStorageLayout.model_fields
            }
        ),
        lease_duration_sec=settings.ingestion_lease_duration_sec,
    )


def create_app(repository: WatermarkRepository | None = None) -> FastAPI:
    app = FastAPI(title="Ingestion progress")
    if repository is not None:
        app.dependency_overrides[get_repository] = lambda: repository

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

    return app


app = create_app()
