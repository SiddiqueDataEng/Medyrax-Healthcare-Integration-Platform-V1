"""
integration_bus_publisher utility (task 12.2).

Used by all Lambda functions to publish events to EventBridge with standard envelope.
Automatically sets SQS FIFO MessageGroupId = patientId, MessageDeduplicationId = eventId.

Requirements: 5.1, 5.2, 5.5
"""
from __future__ import annotations
import json, logging, os, sys, uuid
from datetime import datetime, timezone
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_EVENT_BUS_ARN_TPL = os.environ.get(
    "MDX_EVENT_BUS_ARN_TEMPLATE",
    "arn:aws:events:{region}:000000000000:event-bus/mdx-{org_id}-bus",
)

_events = boto3.client("events", region_name=_REGION)
_sqs = boto3.client("sqs", region_name=_REGION)


def publish_event(
    *,
    org_id: str,
    patient_id: str | None = None,
    resource_type: str,
    event_type: str,
    payload: dict[str, Any],
    correlation_id: str | None = None,
    source: str = "medyrax.platform",
) -> str:
    """
    Publish a standard Medyrax event envelope to the org's EventBridge bus.

    Parameters
    ----------
    org_id:
        Connected_Organization identifier.
    patient_id:
        FHIR Patient logical ID (used as SQS FIFO MessageGroupId).
    resource_type:
        FHIR R4 resource type string.
    event_type:
        Event discriminator (e.g. 'fhir.resource.created').
    payload:
        Event payload dict.
    correlation_id:
        Optional correlation ID to link related events.
    source:
        EventBridge source string.

    Returns
    -------
    str
        The generated eventId UUID.
    """
    event_id = str(uuid.uuid4())
    envelope = {
        "eventId": event_id,
        "orgId": org_id,
        "patientId": patient_id,
        "resourceType": resource_type,
        "eventType": event_type,
        "payload": payload,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "schemaVersion": "1.0",
        "correlationId": correlation_id,
    }

    event_bus_arn = _EVENT_BUS_ARN_TPL.format(region=_REGION, org_id=org_id)
    try:
        _events.put_events(Entries=[{
            "Source": source,
            "DetailType": event_type,
            "Detail": json.dumps(envelope),
            "EventBusName": event_bus_arn,
        }])
        logger.debug("Published %s for org=%s patient=%s", event_type, org_id, patient_id)
    except Exception as exc:
        from mdx_common.errors import IntegrationBusError  # type: ignore
        raise IntegrationBusError(
            message=f"EventBridge publish failed: {exc}",
            queue_url=event_bus_arn,
        ) from exc

    return event_id


def send_to_queue(
    *,
    queue_url: str,
    org_id: str,
    patient_id: str | None = None,
    event_id: str | None = None,
    body: dict[str, Any],
) -> None:
    """
    Send a message to an SQS FIFO queue with standard deduplication fields.

    MessageGroupId = patientId (for per-patient ordering)
    MessageDeduplicationId = eventId (for exactly-once delivery)
    """
    eid = event_id or str(uuid.uuid4())
    kwargs: dict[str, Any] = {
        "QueueUrl": queue_url,
        "MessageBody": json.dumps(body),
    }
    if queue_url.endswith(".fifo"):
        kwargs["MessageGroupId"] = patient_id or org_id or "default"
        kwargs["MessageDeduplicationId"] = eid
    try:
        _sqs.send_message(**kwargs)
    except Exception as exc:
        from mdx_common.errors import IntegrationBusError  # type: ignore
        raise IntegrationBusError(
            message=f"SQS send failed: {exc}",
            queue_url=queue_url,
        ) from exc
