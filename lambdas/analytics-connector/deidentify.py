"""
analytics-deidentify Lambda (task 18.1).

SQS consumer on Integration Bus.
Applies HIPAA Safe Harbor de-identification (reuses security-layer deidentify module).
Writes deident-id -> original FHIR resource ID to mdx-deident-mapping DynamoDB.

Requirements: 11.3, 11.4
"""
from __future__ import annotations
import hashlib, json, logging, os, sys, uuid
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_DEIDENT_TABLE = os.environ.get("MDX_DEIDENT_MAPPING_TABLE", "mdx-deident-mapping")
_FIREHOSE_STREAM = os.environ.get("MDX_FIREHOSE_STREAM_NAME", "mdx-analytics-firehose")

_dynamodb = boto3.resource("dynamodb", region_name=_REGION)
_firehose = boto3.client("firehose", region_name=_REGION)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    failures = []
    for record in event.get("Records", []):
        try:
            body = json.loads(record.get("body", "{}"))
            _process(body)
        except Exception as exc:
            logger.error("analytics-deidentify failed: %s", exc)
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def _process(envelope: dict) -> None:
    org_id = envelope.get("orgId", "")
    payload = envelope.get("payload", {})
    original_id = payload.get("id", str(uuid.uuid4()))

    # Reuse security-layer de-identification
    from security_layer.deidentify import deidentify_resource  # type: ignore
    deidentified = deidentify_resource(payload)

    # Assign a de-identified ID
    deident_id = hashlib.sha256(
        f"{org_id}:{original_id}".encode()
    ).hexdigest()[:32]
    deidentified["id"] = deident_id

    # Write mapping to DynamoDB (encrypted — Platform_Admin only)
    try:
        table = _dynamodb.Table(_DEIDENT_TABLE)
        table.put_item(Item={
            "deidentId": deident_id,
            "orgId": org_id,
            "originalFhirId": original_id,
            "resourceType": payload.get("resourceType", ""),
        })
    except Exception as exc:
        logger.error("Failed to write deident-mapping: %s", exc)

    # Forward to Firehose for Parquet write
    try:
        record_data = json.dumps({
            "orgId": org_id,
            "resourceType": deidentified.get("resourceType", ""),
            "resource": deidentified,
        }) + "\n"
        _firehose.put_record(
            DeliveryStreamName=_FIREHOSE_STREAM,
            Record={"Data": record_data.encode("utf-8")},
        )
    except Exception as exc:
        logger.error("Firehose put_record failed: %s", exc)
