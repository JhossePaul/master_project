"""Colas de ingesta, mensajes fallidos y alertas con CMEK opcional."""

from dataclasses import dataclass

import pulumi
import pulumi_gcp as gcp


@dataclass
class PubSubResources:
    raw_topic: gcp.pubsub.Topic
    raw_subscription: gcp.pubsub.Subscription
    dlq_topic: gcp.pubsub.Topic
    dlq_subscription: gcp.pubsub.Subscription
    alerts_topic: gcp.pubsub.Topic
    alerts_subscription: gcp.pubsub.Subscription


def create_pubsub_resources(
    kms_key_id: pulumi.Output[str] | None,
    api_deps: list[pulumi.Resource],
    *,
    project_id: str | None = None,
) -> PubSubResources:
    """Crea suscripciones Pull y permisos necesarios para entregar a la DLQ."""
    project = project_id or pulumi.Config("gcp").require("project")
    opts = pulumi.ResourceOptions(depends_on=api_deps)
    agent = gcp.projects.ServiceIdentity(
        "voc-pubsub-service-agent",
        project=project,
        service="pubsub.googleapis.com",
        opts=opts,
    )
    member = agent.email.apply(lambda email: f"serviceAccount:{email}")
    topic_deps = list(api_deps)
    if kms_key_id is not None:
        grant = gcp.kms.CryptoKeyIAMMember(
            "voc-pubsub-cmek-access",
            crypto_key_id=kms_key_id,
            role="roles/cloudkms.cryptoKeyEncrypterDecrypter",
            member=member,
            opts=opts,
        )
        topic_deps.append(grant)

    def topic(name: str) -> gcp.pubsub.Topic:
        return gcp.pubsub.Topic(
            name,
            name=name,
            project=project,
            kms_key_name=kms_key_id,
            opts=pulumi.ResourceOptions(depends_on=topic_deps),
        )

    dlq_topic = topic("voc-raw-reviews-dlq")
    dlq_sub = gcp.pubsub.Subscription(
        "voc-raw-reviews-dlq-sub",
        name="voc-raw-reviews-dlq-sub",
        project=project,
        topic=dlq_topic.id,
        message_retention_duration="604800s",
        opts=opts,
    )
    raw_topic = topic("voc-raw-reviews-topic")
    raw_sub = gcp.pubsub.Subscription(
        "voc-raw-reviews-sub",
        name="voc-raw-reviews-sub",
        project=project,
        topic=raw_topic.id,
        ack_deadline_seconds=600,
        message_retention_duration="604800s",
        dead_letter_policy={
            "dead_letter_topic": dlq_topic.id,
            "max_delivery_attempts": 5,
        },
        opts=opts,
    )
    gcp.pubsub.TopicIAMMember(
        "voc-dlq-forward-publisher",
        project=project,
        topic=dlq_topic.name,
        role="roles/pubsub.publisher",
        member=member,
        opts=opts,
    )
    gcp.pubsub.SubscriptionIAMMember(
        "voc-dlq-source-subscriber",
        project=project,
        subscription=raw_sub.name,
        role="roles/pubsub.subscriber",
        member=member,
        opts=opts,
    )
    alerts_topic = topic("voc-incident-alerts-topic")
    alerts_sub = gcp.pubsub.Subscription(
        "voc-incident-alerts-sub",
        name="voc-incident-alerts-sub",
        project=project,
        topic=alerts_topic.id,
        ack_deadline_seconds=60,
        opts=opts,
    )
    return PubSubResources(
        raw_topic, raw_sub, dlq_topic, dlq_sub, alerts_topic, alerts_sub
    )
