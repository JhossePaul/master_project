"""Contratos de Pub/Sub, GCS y BigQuery con y sin CMEK."""

import json
import runpy
from pathlib import Path
from typing import Any

import pulumi
import pytest
from voc_common import (
    AnalyzedReviewPrediction,
    HitlTriageAuditRecord,
    SanitizedReviewRecord,
)

from infra.tests.conftest import InfrastructureMonitor


def _resources(
    monitor: InfrastructureMonitor, resource_type: str
) -> dict[str, Any]:
    return {
        r.urn.rsplit("::", 1)[-1]: r
        for r in monitor.resources.values()
        if f"{resource_type}::" in r.urn
    }


@pytest.mark.parametrize("environment", ["dev", "prod", "staging"])
@pytest.mark.parametrize("cmek", [False, True])
def test_integration_contracts_and_cmek(
    pulumi_mocks: InfrastructureMonitor, environment: str, cmek: bool
) -> None:
    @pulumi.runtime.test
    def deploy() -> None:
        pulumi.runtime.set_all_config(
            {
                "gcp:project": "test-voc-project",
                "gcp:region": "us-central1",
                "bbva-voc-infra:environment": environment,
                "bbva-voc-infra:user_hash_salt": "test-only-salt-1234567890",
                "bbva-voc-infra:enable_cmek": str(cmek).lower(),
            }
        )
        runpy.run_path(str(Path(__file__).resolve().parents[1] / "__main__.py"))

    deploy()
    resources = pulumi_mocks
    topics = _resources(resources, "gcp:pubsub/topic:Topic")
    subs = _resources(resources, "gcp:pubsub/subscription:Subscription")
    assert set(topics) == {
        "voc-raw-reviews-topic",
        "voc-raw-reviews-dlq",
        "voc-incident-alerts-topic",
    }
    assert set(subs) == {
        "voc-raw-reviews-sub",
        "voc-raw-reviews-dlq-sub",
        "voc-incident-alerts-sub",
    }
    raw = subs["voc-raw-reviews-sub"].state
    dlq = subs["voc-raw-reviews-dlq-sub"].state
    alerts = subs["voc-incident-alerts-sub"].state
    assert raw["ackDeadlineSeconds"] == 600
    assert alerts["ackDeadlineSeconds"] == 60
    assert (
        raw["messageRetentionDuration"]
        == dlq["messageRetentionDuration"]
        == "604800s"
    )
    assert raw["topic"] == topics["voc-raw-reviews-topic"].id
    assert dlq["topic"] == topics["voc-raw-reviews-dlq"].id
    assert alerts["topic"] == topics["voc-incident-alerts-topic"].id
    assert raw["deadLetterPolicy"] == {
        "deadLetterTopic": topics["voc-raw-reviews-dlq"].id,
        "maxDeliveryAttempts": 5,
    }
    publishers = _resources(
        resources, "gcp:pubsub/topicIAMMember:TopicIAMMember"
    )
    subscribers = _resources(
        resources, "gcp:pubsub/subscriptionIAMMember:SubscriptionIAMMember"
    )
    assert len(publishers) == len(subscribers) == 1
    publisher = next(iter(publishers.values())).state
    subscriber = next(iter(subscribers.values())).state
    assert publisher["role"] == "roles/pubsub.publisher"
    assert publisher["topic"] == "voc-raw-reviews-dlq"
    assert subscriber["role"] == "roles/pubsub.subscriber"
    assert subscriber["subscription"] == "voc-raw-reviews-sub"
    assert (
        publisher["member"]
        == subscriber["member"]
        == ("serviceAccount:service-123@gcp-sa-pubsub.iam.gserviceaccount.com")
    )

    bucket = next(
        iter(_resources(resources, "gcp:storage/bucket:Bucket").values())
    )
    dataset = next(
        iter(_resources(resources, "gcp:bigquery/dataset:Dataset").values())
    )
    assert bucket.state["name"] == "voc-datalake-test-voc-project"
    assert (
        bucket.state["location"] == dataset.state["location"] == "us-central1"
    )
    assert bucket.state["uniformBucketLevelAccess"] is True
    assert bucket.state["softDeletePolicy"]["retentionDurationSeconds"] == 0
    assert bucket.state["forceDestroy"] is (environment == "dev")
    assert dataset.state["deleteContentsOnDestroy"] is (environment == "dev")
    assert bucket.state["lifecycleRules"] == [
        {
            "action": {"type": "Delete"},
            "condition": {
                "age": 7,
                "matchesPrefixes": ["raw_staging/", "temp_beam/"],
            },
        }
    ]
    assert dataset.state["datasetId"] == "bbva_voc_tds"
    tables = _resources(resources, "gcp:bigquery/table:Table")
    assert set(tables) == {
        "sanitized_reviews_tds",
        "delora_predictions",
        "ingestion_watermarks_log",
        "hitl_triage_audit_log",
    }
    models = {
        "sanitized_reviews_tds": SanitizedReviewRecord,
        "delora_predictions": AnalyzedReviewPrediction,
        "hitl_triage_audit_log": HitlTriageAuditRecord,
    }
    for name, table in tables.items():
        state = table.state
        assert state["tableId"] == name
        assert state["datasetId"] == "bbva_voc_tds"
        assert state["deletionProtection"] is (environment != "dev")
        schema = {field["name"]: field for field in json.loads(state["schema"])}
        assert (
            not {"usuario", "imagen_usuario", "texto", "texto_respuesta"}
            & schema.keys()
        )
        if name in models:
            assert set(schema) == set(models[name].model_fields)
        for field in schema.values():
            assert field["type"] in {
                "STRING",
                "INTEGER",
                "TIMESTAMP",
                "FLOAT",
                "BOOLEAN",
            }
            assert field["mode"] in {"REQUIRED", "NULLABLE", "REPEATED"}
        assert dataset.urn in resources.dependencies[name]
    sanitized = tables["sanitized_reviews_tds"].state
    predictions = tables["delora_predictions"].state
    assert (
        sanitized["timePartitioning"]
        == predictions["timePartitioning"]
        == {"type": "DAY", "field": "fecha"}
    )
    assert sanitized["clusterings"] == ["bank_id", "version_app"]
    assert predictions["clusterings"] == ["bank_id", "topico", "tnss_score"]
    predictions_schema = json.loads(predictions["schema"])
    assert next(
        f for f in predictions_schema if f["name"] == "embedding_vector"
    ) == {"name": "embedding_vector", "type": "FLOAT", "mode": "REPEATED"}
    watermark_schema = json.loads(
        tables["ingestion_watermarks_log"].state["schema"]
    )
    assert {f["name"] for f in watermark_schema} == {
        "bank_id",
        "app_id",
        "mode_executed",
        "max_review_timestamp",
        "min_review_timestamp",
        "oldest_continuation_token",
        "reviews_extracted_in_run",
        "updated_at",
    }
    grants = _resources(
        resources, "gcp:kms/cryptoKeyIAMMember:CryptoKeyIAMMember"
    )
    assert len(grants) == (3 if cmek else 0)
    if cmek:
        key = next(
            iter(_resources(resources, "gcp:kms/cryptoKey:CryptoKey").values())
        )
        for grant in grants.values():
            assert grant.state["cryptoKeyId"] == key.id
            assert (
                grant.state["role"]
                == "roles/cloudkms.cryptoKeyEncrypterDecrypter"
            )
        assert {g.state["member"] for g in grants.values()} == {
            "serviceAccount:service-123@gcp-sa-pubsub.iam.gserviceaccount.com",
            "serviceAccount:service-123@gs-project-accounts.iam.gserviceaccount.com",
            "serviceAccount:bq-123@bigquery-encryption.iam.gserviceaccount.com",
        }
        assert bucket.state["encryption"]["defaultKmsKeyName"] == key.id
        assert (
            dataset.state["defaultEncryptionConfiguration"]["kmsKeyName"]
            == key.id
        )
        for table in tables.values():
            assert (
                table.state["encryptionConfiguration"]["kmsKeyName"] == key.id
            )
        for name, topic in topics.items():
            assert topic.state["kmsKeyName"] == key.id
            assert (
                grants["voc-pubsub-cmek-access"].urn
                in resources.dependencies[name]
            )
        assert (
            grants["voc-storage-cmek-access"].urn
            in resources.dependencies["voc-datalake"]
        )
        assert (
            grants["voc-bigquery-cmek-access"].urn
            in resources.dependencies["bbva-voc-tds"]
        )
    else:
        assert "encryption" not in bucket.state
        assert "defaultEncryptionConfiguration" not in dataset.state
        assert all("kmsKeyName" not in topic.state for topic in topics.values())
        assert all(
            "encryptionConfiguration" not in table.state
            for table in tables.values()
        )
    apis = _resources(resources, "gcp:projects/service:Service")
    api_urns = {r.urn for r in apis.values()}
    for name, resource in {**topics, **subs, **tables}.items():
        assert resource.state["project"] == "test-voc-project"
        assert api_urns <= resources.dependencies[name]
