"""
analytics-kafka-forwarder Lambda (task 18.3).

Triggered by high-priority Integration Bus events.
Forwards to MSK (Kafka) topic mdx-analytics-{resourceType}.

Requirements: 11.2 (high-priority streaming)
"""
from __future__ import annotations
import json, logging, os, sys
from typing import Any

logger = logging.getLogger(__name__)
_KAFKA_BOOTSTRAP = os.environ.get("MDX_KAFKA_BOOTSTRAP_SERVERS", "")
_KAFKA_TOPIC_PREFIX = "mdx-analytics"


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    if not _KAFKA_BOOTSTRAP:
        logger.warning("KAFKA_BOOTSTRAP_SERVERS not configured — skipping Kafka forwarding")
        return {"statusCode": 200, "body": "Kafka not configured"}

    for record in event.get("Records", []):
        try:
            body = json.loads(record.get("body", "{}"))
            _forward(body)
        except Exception as exc:
            logger.error("Kafka forward failed: %s", exc)

    return {"statusCode": 200}


def _forward(envelope: dict) -> None:
    resource_type = envelope.get("resourceType", "unknown").lower()
    topic = f"{_KAFKA_TOPIC_PREFIX}-{resource_type}"

    try:
        from kafka import KafkaProducer  # type: ignore
        producer = KafkaProducer(
            bootstrap_servers=_KAFKA_BOOTSTRAP.split(","),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        producer.send(topic, value=envelope)
        producer.flush(timeout=5)
        logger.info("Forwarded to Kafka topic=%s", topic)
    except ImportError:
        logger.warning("kafka-python not available — install in Lambda layer")
