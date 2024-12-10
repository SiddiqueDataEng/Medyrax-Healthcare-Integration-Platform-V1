"""
hl7-file-processor Lambda (task 8.4).

Triggered by S3 Event Notification on ``mdx-{orgId}-inbound/`` prefix.
Stream-reads HL7 batch file, splits on message boundaries, dispatches
each message to hl7-parser SQS queue, publishes job-completion event.

Requirements: 2.6, 2.7, 9.6
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_HL7_INBOUND_QUEUE_TEMPLATE = os.environ.get(
    "MDX_HL7_INBOUND_QUEUE_URL_TEMPLATE",
    "https://sqs.{region}.amazonaws.com/000000000000/mdx-{org_id}-hl7-inbound.fifo",
)
_EVENT_BUS_ARN_TEMPLATE = os.environ.get(
    "MDX_EVENT_BUS_ARN_TEMPLATE",
    "arn:aws:events:{region}:000000000000:event-bus/mdx-{org_id}-bus",
)

_s3 = boto3.client("s3", region_name=_REGION)
_sqs = boto3.client("sqs", region_name=_REGION)
_events = boto3.client("events", region_name=_REGION)

# MLLP start block byte — batch file may use this or plain segment delimiter
_MLLP_SB = b"\x0b"


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Process S3 ObjectCreated event for HL7 batch file."""
    for s3_record in event.get("Records", []):
        s3_info = s3_record.get("s3", {})
        bucket = s3_info.get("bucket", {}).get("name", "")
        key = s3_info.get("object", {}).get("key", "")
        _process_file(bucket, key)
    return {"statusCode": 200}


def _process_file(bucket: str, key: str) -> None:
    """Stream-read and process an HL7 batch file from S3."""
    # Extract org_id from S3 key pattern: mdx-{orgId}-inbound/{filename}
    org_id = _extract_org_id(key) or os.environ.get("MDX_DEFAULT_ORG_ID", "dev-org")
    job_id = str(uuid.uuid4())

    logger.info("Processing HL7 batch file: s3://%s/%s (org=%s job=%s)", bucket, key, org_id, job_id)

    # Stream-read the file
    response = _s3.get_object(Bucket=bucket, Key=key)
    file_bytes = response["Body"].read()

    # Split into individual HL7 messages
    messages = _split_hl7_batch(file_bytes)
    total = len(messages)
    success_count = 0
    error_count = 0

    queue_url = _HL7_INBOUND_QUEUE_TEMPLATE.format(region=_REGION, org_id=org_id)

    for idx, hl7_text in enumerate(messages):
        try:
            msg_control_id = _extract_control_id(hl7_text) or f"{job_id}-{idx}"
            _sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps({
                    "orgId": org_id,
                    "hl7Message": hl7_text,
                    "messageControlId": msg_control_id,
                    "sourceFile": f"s3://{bucket}/{key}",
                    "jobId": job_id,
                }),
                MessageGroupId=f"batch-{job_id}",
                MessageDeduplicationId=f"{job_id}-{idx}",
            )
            success_count += 1
        except Exception as exc:
            logger.error("Failed to enqueue message %d from job %s: %s", idx, job_id, exc)
            error_count += 1

    # Publish job-completion event
    _publish_job_completion(org_id, job_id, key, total, success_count, error_count)

    logger.info(
        "Batch complete: job=%s total=%d success=%d errors=%d",
        job_id, total, success_count, error_count,
    )


def _split_hl7_batch(data: bytes) -> list[str]:
    """Split an HL7 batch file into individual messages."""
    text = data.decode("utf-8", errors="replace")
    messages = []

    # Try MLLP split first
    if b"\x0b" in data:
        parts = text.split("\x0b")
        for part in parts:
            cleaned = part.rstrip("\x1c\x0d").strip()
            if cleaned.startswith("MSH"):
                messages.append(cleaned)
        return messages

    # Fallback: split on MSH segment starts
    current_lines: list[str] = []
    for line in text.replace("\r", "\n").splitlines():
        if line.startswith("MSH") and current_lines:
            messages.append("\r".join(current_lines) + "\r")
            current_lines = []
        if line.strip():
            current_lines.append(line.strip())
    if current_lines:
        messages.append("\r".join(current_lines) + "\r")

    return [m for m in messages if m.strip().startswith("MSH")]


def _extract_org_id(s3_key: str) -> str:
    """Extract orgId from S3 key pattern ``mdx-{orgId}-inbound/...``."""
    import re
    m = re.match(r"mdx-([^/]+)-inbound/", s3_key)
    return m.group(1) if m else ""


def _extract_control_id(hl7_text: str) -> str:
    """Extract MSH-10 (message control ID) from HL7 text."""
    for line in hl7_text.splitlines():
        if line.startswith("MSH|"):
            fields = line.split("|")
            return fields[9] if len(fields) > 9 else ""
    return ""


def _publish_job_completion(
    org_id: str, job_id: str, file_name: str,
    record_count: int, success_count: int, error_count: int,
) -> None:
    """Publish a job-completion event to the Integration Bus."""
    try:
        event_bus_arn = _EVENT_BUS_ARN_TEMPLATE.format(region=_REGION, org_id=org_id)
        _events.put_events(Entries=[{
            "Source": "medyrax.hl7-file-processor",
            "DetailType": "hl7.batch.completed",
            "Detail": json.dumps({
                "eventId": str(uuid.uuid4()),
                "orgId": org_id,
                "jobId": job_id,
                "fileName": file_name,
                "recordCount": record_count,
                "successCount": success_count,
                "errorCount": error_count,
            }),
            "EventBusName": event_bus_arn,
        }])
    except Exception as exc:
        logger.error("Failed to publish job-completion event: %s", exc)
