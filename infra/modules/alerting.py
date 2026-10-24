"""Avisos por correo de los tópicos de deriva y de calidad del modelo.

Cloud Monitoring no lee el contenido de Pub/Sub, así que cada política
vigila las publicaciones del tópico y manda un correo cuando hay alguna. El
mensaje (sin texto de reseñas) queda en la suscripción del tópico y en
BigQuery (``drift_alerts`` y ``model_quality``).
"""

from dataclasses import dataclass

import pulumi
import pulumi_gcp as gcp

# Publicaciones sumadas por ventana; el correo sale con una o más.
ALIGNMENT_PERIOD = "300s"
AUTO_CLOSE = "1800s"


@dataclass(frozen=True)
class AlertTopic:
    """Tópico vigilado y lo que dice su correo."""

    key: str
    topic_id: str
    subscription_id: str
    title: str
    detail: str


@dataclass
class AlertingResources:
    channel: gcp.monitoring.NotificationChannel
    policies: dict[str, gcp.monitoring.AlertPolicy]


ALERT_TOPICS = (
    AlertTopic(
        "drift",
        "voc-incident-alerts-topic",
        "voc-incident-alerts-sub",
        "Alerta de deriva",
        "Una serie de un banco superó el umbral de su drift_policy. El "
        "detalle está en drift_alerts y, si la risk_policy lo configura, "
        "abrió una subida de revisión humana.",
    ),
    AlertTopic(
        "model-quality",
        "voc-model-quality-topic",
        "voc-model-quality-sub",
        "Aviso de calidad del modelo",
        "El monitor registró un warning, retrain o rejected en "
        "model_quality. No dispara nada solo: lo revisa quien opera los "
        "modelos.",
    ),
)


def _documentation(alert: AlertTopic) -> str:
    return (
        f"{alert.detail}\n\n"
        "El mensaje, sin texto de reseñas, se lee con:\n\n"
        f"`gcloud pubsub subscriptions pull {alert.subscription_id} "
        "--limit=10`"
    )


def create_alerting_resources(
    project_id: str,
    email: pulumi.Input[str],
    api_deps: list[pulumi.Resource],
) -> AlertingResources:
    """Crea el canal de correo y una política por tópico de avisos."""
    opts = pulumi.ResourceOptions(depends_on=api_deps)
    channel = gcp.monitoring.NotificationChannel(
        "voc-alerts-email",
        project=project_id,
        display_name="Avisos de VoC por correo",
        type="email",
        labels={"email_address": email},
        opts=opts,
    )
    policies = {
        alert.key: gcp.monitoring.AlertPolicy(
            f"voc-{alert.key}-email-policy",
            project=project_id,
            display_name=alert.title,
            combiner="OR",
            conditions=[
                {
                    "display_name": f"Publicación en {alert.topic_id}",
                    "condition_threshold": {
                        "filter": (
                            'resource.type = "pubsub_topic" AND '
                            f'resource.labels.topic_id = "{alert.topic_id}" '
                            'AND metric.type = "pubsub.googleapis.com/'
                            'topic/send_request_count"'
                        ),
                        "comparison": "COMPARISON_GT",
                        "threshold_value": 0,
                        "duration": "0s",
                        "aggregations": [
                            {
                                "alignment_period": ALIGNMENT_PERIOD,
                                "per_series_aligner": "ALIGN_SUM",
                            }
                        ],
                    },
                }
            ],
            notification_channels=[channel.name],
            alert_strategy={"auto_close": AUTO_CLOSE},
            documentation={
                "content": _documentation(alert),
                "mime_type": "text/markdown",
            },
            opts=opts,
        )
        for alert in ALERT_TOPICS
    }
    return AlertingResources(channel, policies)
