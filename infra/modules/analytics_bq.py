"""Tablas y vistas analíticas v3 en ``bbva_voc_tds`` (EPIC-6, 6.2).

Las columnas salen de los contratos de ``voc-common`` con ``bq_schema``; aquí
solo se decide la partición, la agrupación y las vistas. Todas las tablas son
de solo inserción: lo vigente se lee en las vistas.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pulumi
import pulumi_gcp as gcp
from voc_common.bq_schema import ANALYTICS_V3_TABLES, bq_schema

from infra.modules.storage_bq import bq_table

SQL_DIR: Final = Path(__file__).parent / "sql"


@dataclass(frozen=True)
class TableLayout:
    """Partición mensual (o ninguna) y agrupación de una tabla v3."""

    partition: str | None = None
    clustering: tuple[str, ...] = ()


# Partición por mes y agrupación de la tabla de 6.2 en ``epic_6.md``.
TABLE_LAYOUTS: Final[Mapping[str, TableLayout]] = {
    "review_predictions": TableLayout(
        "fecha", ("bank_id", "model_version", "sentiment")
    ),
    "review_aspects": TableLayout("fecha", ("bank_id", "prompt_version")),
    "text_embeddings": TableLayout("mes", ("bank_id",)),
    "topic_model_versions": TableLayout(None, ("topic_model_version",)),
    "topic_catalog": TableLayout(None, ("topic_model_version",)),
    "curation_topics": TableLayout(None, ("topic_model_version",)),
    "topic_assignments": TableLayout(
        "fecha", ("bank_id", "topic_model_version")
    ),
    "model_versions": TableLayout(),
    "inference_runs": TableLayout("started_at"),
    "drift_metrics": TableLayout("period", ("bank_id",)),
    "drift_alerts": TableLayout("created_at", ("bank_id",)),
    "drift_alert_events": TableLayout("at"),
    "kpi_estimates": TableLayout("computed_at", ("bank_id",)),
    "review_explanations": TableLayout(),
    "model_quality": TableLayout(),
    "risk_policy": TableLayout(),
    "hitl_boosts": TableLayout(None, ("bank_id",)),
    "drift_policy": TableLayout(None, ("bank_id",)),
    "drift_policy_template": TableLayout(),
    "hitl_coverage_curves": TableLayout(),
    "hitl_items": TableLayout("created_at", ("bank_id", "task")),
    "hitl_events": TableLayout("at"),
    "hitl_reviews": TableLayout("submitted_at", ("task",)),
    "guidelines": TableLayout(),
    "gold_versions": TableLayout(),
    "gold_labels": TableLayout(),
}

# Orden de creación: una vista puede leer las de arriba.
VIEWS: Final[tuple[str, ...]] = (
    "review_predictions_current",
    "risk_policy_current",
    "drift_policy_current",
    "hitl_boosts_active",
    "hitl_queue",
    "drift_alerts_current",
    "eligibility_counts",
    "topic_model_current",
    "daily_topic_labels",
)

_REFERENCE = re.compile(r"`\{project\}\.\{dataset\}\.([a-z0-9_]+)`")


@dataclass(frozen=True)
class AnalyticsBqResources:
    tables: Mapping[str, gcp.bigquery.Table]
    views: Mapping[str, gcp.bigquery.Table]


def view_sql(name: str) -> str:
    """Consulta de la vista con ``{project}`` y ``{dataset}`` sin resolver."""
    return (SQL_DIR / f"{name}.sql").read_text(encoding="utf-8")


def view_references(name: str) -> tuple[str, ...]:
    """Tablas y vistas del dataset que lee la vista, en orden de aparición."""
    return tuple(dict.fromkeys(_REFERENCE.findall(view_sql(name))))


def create_analytics_bq(
    project: str,
    dataset: gcp.bigquery.Dataset,
    kms_key: pulumi.Input[str] | None,
    is_dev: bool,
    *,
    deps: list[pulumi.Resource] | None = None,
) -> AnalyticsBqResources:
    """Crea las 26 tablas v3 y sus vistas en el dataset del TDS.

    ``deps`` son las APIs y, con CMEK, el permiso del agente de BigQuery.
    """
    deps = deps or []
    if set(TABLE_LAYOUTS) != set(ANALYTICS_V3_TABLES):
        raise ValueError("TABLE_LAYOUTS must cover every v3 table")
    tables: dict[str, gcp.bigquery.Table] = {}
    for name, model in ANALYTICS_V3_TABLES.items():
        layout = TABLE_LAYOUTS[name]
        tables[name] = bq_table(
            name,
            project_id=project,
            dataset=dataset,
            fields=bq_schema(model),
            kms_key_id=kms_key,
            is_dev=is_dev,
            deps=deps,
            clustering=list(layout.clustering),
            partition_field=layout.partition,
            partition_type="MONTH",
        )
    views: dict[str, gcp.bigquery.Table] = {}
    for name in VIEWS:
        sources = [
            tables.get(ref) or views[ref] for ref in view_references(name)
        ]
        query = dataset.dataset_id.apply(
            lambda dataset_id, name=name: view_sql(name).format(
                project=project, dataset=dataset_id
            )
        )
        views[name] = gcp.bigquery.Table(
            name,
            project=project,
            dataset_id=dataset.dataset_id,
            table_id=name,
            view={"query": query, "use_legacy_sql": False},
            deletion_protection=not is_dev,
            opts=pulumi.ResourceOptions(depends_on=[dataset, *deps, *sources]),
        )
    return AnalyticsBqResources(tables, views)
