"""Tablas y vistas analíticas v3 (EPIC-6, 6.2) con Pulumi Mocks."""

import json
import re
import runpy
from pathlib import Path
from typing import Any

import pulumi
import pytest
from voc_common.bq_schema import ANALYTICS_V3_TABLES, bq_schema

from infra.modules import analytics_bq
from infra.modules.analytics_bq import (
    TABLE_LAYOUTS,
    VIEWS,
    view_references,
    view_sql,
)
from infra.tests.conftest import InfrastructureMonitor, unwrap_outputs

ENTRYPOINT = Path(__file__).resolve().parents[1] / "__main__.py"


def _deploy(
    monitor: InfrastructureMonitor, environment: str, cmek: bool = False
) -> dict[str, Any]:
    @pulumi.runtime.test
    def deploy() -> None:
        pulumi.runtime.set_all_config(
            {
                "gcp:project": "test-voc-project",
                "bbva-voc-infra:environment": environment,
                "bbva-voc-infra:user_hash_salt": "test-only-salt-1234567890",
                "bbva-voc-infra:enable_cmek": str(cmek).lower(),
            }
        )
        runpy.run_path(str(ENTRYPOINT))

    deploy()
    return {
        r.urn.rsplit("::", 1)[-1]: r
        for r in monitor.resources.values()
        if "gcp:bigquery/table:Table::" in r.urn
    }


@pytest.mark.parametrize("environment", ["dev", "prod"])
def test_every_v3_table_uses_the_schema_of_its_model(
    pulumi_mocks: InfrastructureMonitor, environment: str
) -> None:
    resources = _deploy(pulumi_mocks, environment)
    for name, model in ANALYTICS_V3_TABLES.items():
        state = unwrap_outputs(resources[name].state)
        assert state["tableId"] == name
        assert state["datasetId"] == "bbva_voc_tds"
        assert state["deletionProtection"] is (environment != "dev")
        expected = [
            {"name": n, "type": t, "mode": m} for n, t, m in bq_schema(model)
        ]
        assert json.loads(state["schema"]) == expected


def test_monthly_partitions_and_clustering(
    pulumi_mocks: InfrastructureMonitor,
) -> None:
    resources = _deploy(pulumi_mocks, "dev")
    for name, layout in TABLE_LAYOUTS.items():
        state = unwrap_outputs(resources[name].state)
        columns = {n: t for n, t, _ in bq_schema(ANALYTICS_V3_TABLES[name])}
        if layout.partition is None:
            assert "timePartitioning" not in state, name
        else:
            assert state["timePartitioning"] == {
                "type": "MONTH",
                "field": layout.partition,
            }
            assert columns[layout.partition] in {"TIMESTAMP", "DATE"}
        assert state.get("clusterings", []) == list(layout.clustering), name
        assert set(layout.clustering) <= set(columns), name


@pytest.mark.parametrize(
    ("table", "partition", "clustering"),
    [
        (
            "review_predictions",
            "fecha",
            ["bank_id", "model_version", "sentiment"],
        ),
        ("review_aspects", "fecha", ["bank_id", "prompt_version"]),
        ("text_embeddings", "mes", ["bank_id"]),
        ("topic_assignments", "fecha", ["bank_id", "topic_model_version"]),
        ("drift_metrics", "period", ["bank_id"]),
        ("hitl_items", "created_at", ["bank_id", "task"]),
        ("hitl_reviews", "submitted_at", ["task"]),
    ],
)
def test_layout_matches_the_backlog(
    table: str, partition: str, clustering: list[str]
) -> None:
    layout = TABLE_LAYOUTS[table]
    assert (layout.partition, list(layout.clustering)) == (
        partition,
        clustering,
    )


def test_cmek_applies_to_tables_but_not_views(
    pulumi_mocks: InfrastructureMonitor,
) -> None:
    resources = _deploy(pulumi_mocks, "prod", cmek=True)
    key = next(
        r
        for r in pulumi_mocks.resources.values()
        if r.urn.endswith("::voc-cmek-key")
    )
    grant = next(
        r
        for r in pulumi_mocks.resources.values()
        if r.urn.endswith("::voc-bigquery-cmek-access")
    )
    for name in ANALYTICS_V3_TABLES:
        state = resources[name].state
        assert state["encryptionConfiguration"]["kmsKeyName"] == key.id
        assert grant.urn in pulumi_mocks.dependencies[name]
    for name in VIEWS:
        assert "encryptionConfiguration" not in resources[name].state


def test_views_read_only_existing_tables_and_depend_on_them(
    pulumi_mocks: InfrastructureMonitor,
) -> None:
    resources = _deploy(pulumi_mocks, "prod")
    created: set[str] = set(ANALYTICS_V3_TABLES)
    for name in VIEWS:
        refs = view_references(name)
        assert refs, name
        # Una vista solo lee tablas v3 o vistas creadas antes que ella.
        assert set(refs) <= created, name
        created.add(name)
        state = unwrap_outputs(resources[name].state)
        query = state["view"]["query"]
        assert state["view"]["useLegacySql"] is False
        assert state["deletionProtection"] is True
        assert "{" not in query
        assert f"`test-voc-project.bbva_voc_tds.{refs[0]}`" in query
        for ref in refs:
            assert resources[ref].urn in pulumi_mocks.dependencies[name]


@pytest.mark.parametrize("name", VIEWS)
def test_view_sql_never_reads_review_text(name: str) -> None:
    sql = view_sql(name)
    assert not re.search(r"\btexto(_sanitizado|_limpio)?\b", sql)
    assert "sanitized_reviews_tds" not in sql


def test_current_predictions_view_uses_the_promoted_model() -> None:
    sql = view_sql("review_predictions_current")
    assert "status = 'promoted'" in sql
    assert "PARTITION BY p.id_resena" in sql
    for column in (
        "estrellas_clase",
        "estrellas_difiere",
        "incongruencia_extremos",
        "texto_peor",
        "texto_mejor",
    ):
        assert column in sql


def test_daily_topic_labels_keeps_the_rules_of_5_9() -> None:
    sql = view_sql("daily_topic_labels")
    assert "sentiment = 'NEG' AND palabras >= 2" in sql
    assert "RANGE BETWEEN 28 PRECEDING AND 1 PRECEDING" in sql
    assert "WHERE r.rango <= 5" in sql
    assert "audience IN ('producto', 'ingenieria')" in sql
    assert view_references("daily_topic_labels") == (
        "review_predictions_current",
        "review_aspects",
        "topic_model_versions",
        "curation_topics",
        "topic_assignments",
    )


def test_layouts_must_cover_every_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layouts = dict(TABLE_LAYOUTS)
    del layouts["gold_labels"]
    monkeypatch.setattr(analytics_bq, "TABLE_LAYOUTS", layouts)
    with pytest.raises(ValueError, match="every v3 table"):
        analytics_bq.create_analytics_bq(
            "test-voc-project",
            None,
            None,
            True,  # type: ignore[arg-type]
        )
