"""Dependencia compartida que entrega el lector de BigQuery."""

from fastapi import Request
from google.cloud import bigquery

from api_backend.bq.reader import BigQueryReader
from api_backend.settings import ApiSettings


def reader_for(request: Request, settings: ApiSettings) -> BigQueryReader:
    """Un lector por proceso: el cliente y la caché se comparten."""
    state = request.app.state
    if getattr(state, "bq_reader", None) is None:
        client = bigquery.Client(project=settings.gcp_project_id)
        state.bq_reader = BigQueryReader(client, settings)
    return state.bq_reader
