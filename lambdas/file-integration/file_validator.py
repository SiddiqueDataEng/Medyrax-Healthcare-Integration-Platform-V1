"""
file-validator Lambda (task 16.3).

Triggered by SQS. Stream-reads file from S3 (up to 100MB).
Validates HL7, FHIR NDJSON, CCD/C-CDA format.
On failure: quarantines file, sends SNS alert, writes validation report.

Requirements: 9.3, 9.4
"""
from __future__ import annotations
import json, logging, os, sys, uuid
from datetime import datetime, timezone
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_s3 = boto3.client("s3", region_name=_REGION)
_sns = boto3.client("sns", region_name=_REGION)
_sqs = boto3.client("sqs", region_name=_REGION)

_MAX_FILE_BYTES = 100 * 1024 * 1024  # 100 MB


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    failures = []
    for record in event.get("Records", []):
        try:
            body = json.loads(record.get("body", "{}"))
            _validate(body)
        except Exception as exc:
            logger.error("file-validator failed: %s", exc)
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def _validate(msg: dict) -> None:
    org_id = msg.get("orgId", "")
    bucket = msg.get("bucket", "")
    key = msg.get("key", "")
    file_format = msg.get("fileFormat", "UNKNOWN")

    # Read file (stream for large files)
    resp = _s3.get_object(Bucket=bucket, Key=key)
    content_length = int(resp.get("ContentLength", 0))
    if content_length > _MAX_FILE_BYTES:
        _quarantine(org_id, bucket, key, "File exceeds 100MB limit")
        return

    content = resp["Body"].read().decode("utf-8", errors="replace")

    errors: list[str] = []
    if file_format == "HL7":
        errors = _validate_hl7(content)
    elif file_format == "FHIR_NDJSON":
        errors = _validate_fhir_ndjson(content)
    elif file_format == "CCD":
        errors = _validate_ccd(content)
    else:
        errors = [f"Unknown file format: {file_format}"]

    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S")
    report = {
        "orgId": org_id,
        "bucket": bucket,
        "key": key,
        "fileFormat": file_format,
        "validatedAt": datetime.now(tz=timezone.utc).isoformat(),
        "valid": len(errors) == 0,
        "errors": errors,
    }

    # Write report to S3
    reports_bucket = os.environ.get("MDX_REPORTS_BUCKET", f"mdx-{org_id}-reports")
    try:
        _s3.put_object(
            Bucket=reports_bucket,
            Key=f"{ts}-validation.json",
            Body=json.dumps(report),
            ContentType="application/json",
        )
    except Exception as exc:
        logger.warning("Failed to write validation report: %s", exc)

    if errors:
        _quarantine(org_id, bucket, key, "; ".join(errors[:3]))
        return

    # Forward to processor queue
    processor_url = os.environ.get(
        "MDX_FILE_PROCESSOR_QUEUE_URL",
        f"https://sqs.{_REGION}.amazonaws.com/000000000000/mdx-{org_id}-file-process",
    )
    try:
        _sqs.send_message(
            QueueUrl=processor_url,
            MessageBody=json.dumps({**msg, "validatedAt": report["validatedAt"]}),
        )
    except Exception as exc:
        logger.error("Failed to enqueue validated file: %s", exc)


def _quarantine(org_id: str, bucket: str, key: str, reason: str) -> None:
    """Move invalid file to quarantine prefix and send SNS alert."""
    quarantine_key = key.replace("inbound/", "quarantine/", 1)
    try:
        _s3.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": key},
            Key=quarantine_key,
        )
        _s3.delete_object(Bucket=bucket, Key=key)
        logger.warning("Quarantined file: %s -> %s (%s)", key, quarantine_key, reason)
    except Exception as exc:
        logger.error("Quarantine failed: %s", exc)

    # SNS alert
    alert_topic = os.environ.get("MDX_ALERT_SNS_TOPIC_ARN", "")
    if alert_topic:
        try:
            _sns.publish(
                TopicArn=alert_topic,
                Subject=f"File validation failure — {org_id}",
                Message=json.dumps({
                    "orgId": org_id,
                    "file": f"s3://{bucket}/{key}",
                    "quarantinedTo": f"s3://{bucket}/{quarantine_key}",
                    "reason": reason,
                }),
            )
        except Exception as exc:
            logger.warning("SNS alert failed: %s", exc)


def _validate_hl7(content: str) -> list[str]:
    errors = []
    for line in content.splitlines():
        if line.startswith("MSH"):
            fields = line.split("|")
            if len(fields) < 9:
                errors.append(f"MSH segment has only {len(fields)} fields (minimum 9)")
            return errors
    return ["No MSH segment found"]


def _validate_fhir_ndjson(content: str) -> list[str]:
    errors = []
    for i, line in enumerate(content.strip().splitlines()):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if "resourceType" not in obj:
                errors.append(f"Line {i+1}: missing resourceType")
        except json.JSONDecodeError as exc:
            errors.append(f"Line {i+1}: invalid JSON: {exc}")
        if len(errors) >= 10:
            break
    return errors


def _validate_ccd(content: str) -> list[str]:
    if not (content.strip().startswith("<?xml") or "<ClinicalDocument" in content):
        return ["Not a valid CCD/C-CDA XML document"]
    return []
