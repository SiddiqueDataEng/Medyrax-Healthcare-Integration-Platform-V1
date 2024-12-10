"""
hl7-parser Lambda (task 8.2).

Triggered by SQS FIFO queue ``mdx-{orgId}-hl7-inbound.fifo``.
Parses each HL7 message, converts to CanonicalMessage, and puts the
canonical model on the integration bus via EventBridge.

On parse failure:
    - Returns a NAK AE via SQS reply queue
    - Logs to CloudWatch

Requirements: 2.2, 2.5, 2.8
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_REPLY_QUEUE_URL = os.environ.get("MDX_HL7_REPLY_QUEUE_URL", "")
_TRANSFORMER_QUEUE_URL_TEMPLATE = os.environ.get(
    "MDX_HL7_TRANSFORMER_QUEUE_URL_TEMPLATE",
    "https://sqs.{region}.amazonaws.com/000000000000/mdx-{org_id}-hl7-parsed.fifo",
)

_sqs = boto3.client("sqs", region_name=_REGION)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Process SQS batch of HL7 messages from hl7-inbound.fifo."""
    batch_item_failures = []

    for record in event.get("Records", []):
        try:
            _process_record(record)
        except Exception as exc:
            logger.error("Failed to process record %s: %s", record.get("messageId"), exc)
            batch_item_failures.append({"itemIdentifier": record["messageId"]})

    return {"batchItemFailures": batch_item_failures}


def _process_record(record: dict[str, Any]) -> None:
    """Parse one SQS record containing an HL7 message."""
    body = json.loads(record.get("body", "{}"))
    org_id = body.get("orgId", "")
    hl7_text = body.get("hl7Message", "")
    msg_control_id = body.get("messageControlId", "")

    if not hl7_text:
        logger.warning("Empty HL7 message in record %s", record.get("messageId"))
        return

    try:
        # Import the data-mapper parser
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mdx-data-mapper"))
        from hl7_to_canonical import HL7ToCanonicalParser

        parser = HL7ToCanonicalParser()
        canonical = parser.parse(hl7_text, org_id=org_id)

        logger.info(
            "Parsed HL7 message: org=%s type=%s patient=%s control=%s",
            org_id,
            canonical.message_type,
            canonical.patient_id,
            msg_control_id,
        )

        # Forward canonical model to transformer queue
        transformer_url = _TRANSFORMER_QUEUE_URL_TEMPLATE.format(
            region=_REGION, org_id=org_id
        )
        _sqs.send_message(
            QueueUrl=transformer_url,
            MessageBody=json.dumps({
                "orgId": org_id,
                "messageControlId": msg_control_id,
                "messageType": canonical.message_type.value if canonical.message_type else "",
                "patientId": canonical.patient_id or "",
                "fhirElements": canonical.fhir_elements,
                "extensionMap": canonical.extension_map,
                "sourceSha256": canonical.source_sha256 or "",
                "rawSource": canonical.raw_source or "",
            }),
            MessageGroupId=canonical.patient_id or "unknown",
            MessageDeduplicationId=f"parsed-{msg_control_id}",
        )

    except Exception as exc:
        logger.error(
            "HL7 parse error for control=%s org=%s: %s", msg_control_id, org_id, exc
        )
        _send_nak_reply(msg_control_id, org_id, str(exc))
        raise


def _send_nak_reply(msg_control_id: str, org_id: str, error_msg: str) -> None:
    """Send NAK AE notification to the SQS reply queue."""
    if not _REPLY_QUEUE_URL:
        return
    try:
        _sqs.send_message(
            QueueUrl=_REPLY_QUEUE_URL,
            MessageBody=json.dumps({
                "status": "NAK",
                "errorCode": "AE",
                "messageControlId": msg_control_id,
                "orgId": org_id,
                "errorMessage": error_msg,
            }),
        )
    except Exception as exc:
        logger.error("Failed to send NAK reply: %s", exc)
