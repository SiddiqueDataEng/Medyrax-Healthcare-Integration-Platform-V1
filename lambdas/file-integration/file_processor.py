"""
file-processor Lambda (task 16.4).

Streams valid file from S3, dispatches each HL7 message or FHIR resource
to appropriate processing queue. Publishes job-completion event.

Requirements: 9.6
"""
from __future__ import annotations
import json, logging, os, sys, uuid
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_s3 = boto3.client("s3", region_name=_REGION)
_sqs = boto3.client("sqs", region_name=_REGION)
_events = boto3.client("events", region_name=_REGION)

_HL7_QUEUE_TPL = os.environ.get(
    "MDX_HL7_INBOUND_QUEUE_URL_TEMPLATE",
    "https://sqs.{region}.amazonaws.com/000000000000/mdx-{org_id}-hl7-inbound.fifo",
)
_EVENT_BUS_TPL = os.environ.get(
    "MDX_EVENT_BUS_ARN_TEMPLATE",
    "arn:aws:events:{region}:000000000000:event-bus/mdx-{org_id}-bus",
)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    failures = []
    for record in event.get("Records", []):
        try:
            body = json.loads(record.get("body", "{}"))
            _process(body)
        except Exception as exc:
            logger.error("file-processor error: %s", exc)
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def _process(msg: dict) -> None:
    org_id = msg.get("orgId", "")
    bucket = msg.get("bucket", "")
    key = msg.get("key", "")
    file_format = msg.get("fileFormat", "UNKNOWN")
    job_id = str(uuid.uuid4())

    resp = _s3.get_object(Bucket=bucket, Key=key)
    content = resp["Body"].read().decode("utf-8", errors="replace")

    success_count = 0
    error_count = 0
    record_count = 0

    if file_format == "HL7":
        messages = _split_hl7(content)
        record_count = len(messages)
        queue_url = _HL7_QUEUE_TPL.format(region=_REGION, org_id=org_id)
        for idx, hl7_msg in enumerate(messages):
            try:
                msg_id = f"{job_id}-{idx}"
                _sqs.send_message(
                    QueueUrl=queue_url,
                    MessageBody=json.dumps({
                        "orgId": org_id,
                        "hl7Message": hl7_msg,
                        "messageControlId": msg_id,
                        "sourceFile": f"s3://{bucket}/{key}",
                        "jobId": job_id,
                    }),
                    MessageGroupId=f"job-{job_id}",
                    MessageDeduplicationId=msg_id,
                )
                success_count += 1
            except Exception as exc:
                logger.error("Failed to enqueue HL7 message %d: %s", idx, exc)
                error_count += 1

    elif file_format == "FHIR_NDJSON":
        for i, line in enumerate(content.strip().splitlines()):
            if not line.strip():
                continue
            record_count += 1
            try:
                resource = json.loads(line)
                # Route to FHIR Engine via EventBridge
                _events.put_events(Entries=[{
                    "Source": "medyrax.file-processor",
                    "DetailType": "fhir.resource.ingest",
                    "Detail": json.dumps({
                        "eventId": str(uuid.uuid4()),
                        "orgId": org_id,
                        "eventType": "fhir.resource.ingest",
                        "payload": resource,
                        "jobId": job_id,
                        "schemaVersion": "1.0",
                    }),
                    "EventBusName": _EVENT_BUS_TPL.format(region=_REGION, org_id=org_id),
                }])
                success_count += 1
            except Exception as exc:
                logger.error("Failed to route FHIR resource %d: %s", i, exc)
                error_count += 1

    # Publish job-completion event
    try:
        _events.put_events(Entries=[{
            "Source": "medyrax.file-processor",
            "DetailType": "file.processing.completed",
            "Detail": json.dumps({
                "eventId": str(uuid.uuid4()),
                "orgId": org_id,
                "jobId": job_id,
                "fileName": key,
                "recordCount": record_count,
                "successCount": success_count,
                "errorCount": error_count,
            }),
            "EventBusName": _EVENT_BUS_TPL.format(region=_REGION, org_id=org_id),
        }])
    except Exception as exc:
        logger.warning("Failed to publish job-completion event: %s", exc)

    logger.info("Processed job=%s: total=%d success=%d errors=%d",
                job_id, record_count, success_count, error_count)


def _split_hl7(content: str) -> list[str]:
    messages, current = [], []
    for line in content.replace("\r", "\n").splitlines():
        if line.startswith("MSH") and current:
            messages.append("\r".join(current) + "\r")
            current = []
        if line.strip():
            current.append(line.strip())
    if current:
        messages.append("\r".join(current) + "\r")
    return [m for m in messages if m.startswith("MSH")]
