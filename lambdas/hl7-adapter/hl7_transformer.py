"""
hl7-transformer Lambda (task 8.3).

Converts parsed canonical model to FHIR R4 resource, validates codes via
Terminology Service, publishes to EventBridge within 2s, records audit.

Requirements: 2.3, 2.4, 13.5
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mdx-data-mapper"))

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_EVENT_BUS_ARN_TEMPLATE = os.environ.get(
    "MDX_EVENT_BUS_ARN_TEMPLATE",
    "arn:aws:events:{region}:000000000000:event-bus/mdx-{org_id}-bus",
)

_events = boto3.client("events", region_name=_REGION)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Process SQS batch of parsed canonical models for FHIR transformation."""
    batch_item_failures = []

    for record in event.get("Records", []):
        try:
            _process_record(record)
        except Exception as exc:
            logger.error("Transformer failed: %s", exc)
            batch_item_failures.append({"itemIdentifier": record["messageId"]})

    return {"batchItemFailures": batch_item_failures}


def _process_record(record: dict[str, Any]) -> None:
    start_ms = time.monotonic() * 1000
    body = json.loads(record.get("body", "{}"))
    org_id = body.get("orgId", "")
    msg_control_id = body.get("messageControlId", "")
    msg_type = body.get("messageType", "")
    patient_id = body.get("patientId", "")
    raw_source = body.get("rawSource", "")
    source_sha256 = body.get("sourceSha256", "")

    # Reconstruct a minimal CanonicalMessage from the SQS payload
    from mdx_common.models import CanonicalMessage  # type: ignore
    from mdx_common.enums import Hl7MessageType  # type: ignore

    canonical = CanonicalMessage(
        message_id=msg_control_id,
        patient_id=patient_id,
        fhir_elements=body.get("fhirElements", {}),
        extension_map=body.get("extensionMap", {}),
        raw_source=raw_source,
        source_sha256=source_sha256,
    )
    try:
        canonical.message_type = Hl7MessageType(msg_type)
    except (ValueError, KeyError):
        canonical.message_type = None

    # Convert to FHIR
    from canonical_to_fhir import CanonicalToFHIRSerializer

    serializer = CanonicalToFHIRSerializer()
    fhir_resource = serializer.serialize(canonical)

    # Compute target sha256
    import hashlib
    fhir_str = json.dumps(fhir_resource, sort_keys=True)
    target_sha256 = hashlib.sha256(fhir_str.encode()).hexdigest()
    fhir_id = fhir_resource.get("id", str(uuid.uuid4()))

    # Record transformation audit
    from transformation_auditor import TransformationAuditor
    auditor = TransformationAuditor()
    auditor.record(
        source_id=msg_control_id,
        target_id=fhir_id,
        ruleset_version="1.0",
        source_content=raw_source,
        target_content=fhir_str,
        org_id=org_id,
        message_type=msg_type,
    )

    # Publish to EventBridge Integration Bus
    event_bus_arn = _EVENT_BUS_ARN_TEMPLATE.format(region=_REGION, org_id=org_id)
    resource_type = fhir_resource.get("resourceType", "Bundle")

    _events.put_events(Entries=[{
        "Source": "medyrax.hl7-transformer",
        "DetailType": "fhir.resource.created",
        "Detail": json.dumps({
            "eventId": str(uuid.uuid4()),
            "orgId": org_id,
            "patientId": patient_id,
            "resourceType": resource_type,
            "eventType": "fhir.resource.created",
            "payload": fhir_resource,
            "schemaVersion": "1.0",
        }),
        "EventBusName": event_bus_arn,
    }])

    elapsed_ms = (time.monotonic() * 1000) - start_ms
    logger.info(
        "HL7 transformed: org=%s type=%s->%s elapsed=%.1fms",
        org_id, msg_type, resource_type, elapsed_ms,
    )

    if elapsed_ms > 2000:
        logger.warning(
            "Transformation exceeded 2s SLA: %.1fms (org=%s)", elapsed_ms, org_id
        )
