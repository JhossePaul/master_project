"""Comprueba el canal de correo y las políticas de los tópicos de avisos."""

import runpy
from pathlib import Path

import pulumi
from pulumi.runtime import rpc

from infra.tests.conftest import InfrastructureMonitor, unwrap_outputs

_PROJECT = "test-voc-project"
_CHANNEL = f"projects/{_PROJECT}/notificationChannels/voc-alerts-email"


def _deploy(email: str | None) -> None:
    @pulumi.runtime.test
    def deploy() -> None:
        config = {"gcp:project": _PROJECT, "gcp:region": "us-central1"}
        if email is not None:
            config["bbva-voc-infra:alert_email"] = email
        pulumi.runtime.set_all_config(
            config, secret_keys=["bbva-voc-infra:alert_email"]
        )
        runpy.run_path(str(Path(__file__).resolve().parents[1] / "__main__.py"))

    deploy()


def _states(monitor: InfrastructureMonitor, typ: str) -> dict[str, dict]:
    return {
        r.urn.rsplit("::", 1)[-1]: r.state
        for r in monitor.resources.values()
        if f"{typ}::" in r.urn
    }


def test_email_channel_watches_both_alert_topics(
    pulumi_mocks: InfrastructureMonitor,
) -> None:
    _deploy("avisos@example.com")
    channels = _states(
        pulumi_mocks, "gcp:monitoring/notificationChannel:NotificationChannel"
    )
    assert list(channels) == ["voc-alerts-email"]
    channel = channels["voc-alerts-email"]
    assert channel["type"] == "email"
    # El correo viaja como secreto: no queda en texto plano en el estado.
    assert rpc.is_rpc_secret(channel["labels"])
    assert unwrap_outputs(channel["labels"]) == {
        "email_address": "avisos@example.com"
    }

    policies = _states(pulumi_mocks, "gcp:monitoring/alertPolicy:AlertPolicy")
    assert set(policies) == {
        "voc-drift-email-policy",
        "voc-model-quality-email-policy",
    }
    watched = {}
    for name, policy in policies.items():
        assert policy["notificationChannels"] == [_CHANNEL]
        assert policy["alertStrategy"] == {"autoClose": "1800s"}
        (condition,) = policy["conditions"]
        threshold = condition["conditionThreshold"]
        assert threshold["comparison"] == "COMPARISON_GT"
        assert threshold["thresholdValue"] == 0
        assert threshold["aggregations"] == [
            {"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_SUM"}
        ]
        assert "topic/send_request_count" in threshold["filter"]
        topic = threshold["filter"].split('topic_id = "')[1].split('"')[0]
        watched[name] = topic
        # El correo dice de qué suscripción leer el mensaje.
        subscription = topic.removesuffix("-topic") + "-sub"
        assert subscription in policy["documentation"]["content"]
    assert watched == {
        "voc-drift-email-policy": "voc-incident-alerts-topic",
        "voc-model-quality-email-policy": "voc-model-quality-topic",
    }
    # El correo de calidad trae los comandos de respaldo del portal.
    quality = policies["voc-model-quality-email-policy"]["documentation"]
    assert "`gcloud run jobs execute voc-ml-training`" in quality["content"]
    assert (
        "gcloud run jobs execute voc-ml-promote --args=promote,"
        "--model-version=" in quality["content"]
    )
    drift = policies["voc-drift-email-policy"]["documentation"]["content"]
    assert "gcloud run jobs execute" not in drift
    api = next(
        r.urn
        for r in pulumi_mocks.resources.values()
        if r.urn.endswith("::api-monitoring")
    )
    for name in ("voc-alerts-email", *policies):
        assert api in pulumi_mocks.dependencies[name]


def test_without_email_there_is_no_channel(
    pulumi_mocks: InfrastructureMonitor,
) -> None:
    _deploy(None)
    assert not [
        r for r in pulumi_mocks.resources.values() if "gcp:monitoring/" in r.urn
    ]
