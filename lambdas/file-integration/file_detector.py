"""
file-detector Lambda (task 16.2).

Triggered by S3 ObjectCreated within 30s.
Detects file format by extension and magic bytes.
HL7 starts with MSH|, FHIR NDJSON contains JSON objects, CCD/C-CDA starts with XML header.
Enqueues file metadata to mdx-{orgId}-file-inbound SQS queue.

Requirements: 9.2
"""
from __future__ import annotations
import json, logging, os, sys, urllib.parse
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_FILE_QUEUE_TPL = os.environ.get(
    "MDX_FILE_INBOUND_QUEUE_URL_TEMPLATE",
    "https://sqs.{region}.amazonaws.com/000000000000/mdx-{org_id}-file-inbound",
)

_s3 = boto3.client("s3", region_name=_REGION)
_sqs = boto3.client("sqs", region_name=_REGION)

_FORMAT_HL7 = "HL7"
_FORMAT_FHIR = "FHIR_NDJSON"
_FORMAT_CCD = "CCD"
_FORMAT_UNKNOWN = "UNKNOWN"


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    for record in event.get("Records", []):
        s3 = record.get("s3", {})
        bucket = s3.get("bucket", {}).get("name", "")
        key = urllib.parse.unquote_plus(s3.get("object", {}).get("key", ""))
        _process(bucket, key)
    return {"statusCode": 200}


def _process(bucket: str, key: str) -> None:
    import re
    # Extract orgId from key pattern mdx-{orgId}-inbound/
    m = re.match(r"mdx-([^/]+)-inbound/", key)
    org_id = m.group(1) if m else os.environ.get("MDX_DEFAULT_ORG_ID", "dev-org")
    file_size = _get_file_size(bucket, key)
    file_format = _detect_format(bucket, key)

    logger.info("Detected: org=%s file=%s format=%s size=%d", org_id, key, file_format, file_size)

    queue_url = _FILE_QUEUE_TPL.format(region=_REGION, org_id=org_id)
    _sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps({
            "orgId": org_id,
            "bucket": bucket,
            "key": key,
            "fileFormat": file_format,
            "fileSizeBytes": file_size,
            "s3Uri": f"s3://{bucket}/{key}",
        }),
    )


def _get_file_size(bucket: str, key: str) -> int:
    try:
        resp = _s3.head_object(Bucket=bucket, Key=key)
        return resp.get("ContentLength", 0)
    except Exception:
        return 0


def _detect_format(bucket: str, key: str) -> str:
    """Read first 512 bytes and check magic bytes + extension."""
    key_lower = key.lower()
    if key_lower.endswith((".hl7", ".hl7txt")):
        return _FORMAT_HL7
    if key_lower.endswith(".ndjson"):
        return _FORMAT_FHIR
    if key_lower.endswith((".xml", ".ccd", ".ccda")):
        return _FORMAT_CCD

    try:
        resp = _s3.get_object(Bucket=bucket, Key=key, Range="bytes=0-511")
        first_bytes = resp["Body"].read()
        first_str = first_bytes.decode("utf-8", errors="replace").lstrip()
        if first_str.startswith("MSH|"):
            return _FORMAT_HL7
        if first_str.startswith("{") or first_str.startswith("["):
            return _FORMAT_FHIR
        if first_str.startswith("<?xml") or "<ClinicalDocument" in first_str:
            return _FORMAT_CCD
    except Exception as exc:
        logger.warning("Magic byte detection failed: %s", exc)

    return _FORMAT_UNKNOWN
