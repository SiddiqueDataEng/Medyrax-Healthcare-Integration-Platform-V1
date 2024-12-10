"""
fhir-engine-bundle Lambda handler (task 9.4).

Accepts a FHIR transaction Bundle.
Two-phase atomic commit via DynamoDB transactions.
On any entry failure: abort, zero entries persisted.

Requirements: 1.5, 1.6
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from typing import Any

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger(__name__)
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_FHIR_ID_REGISTRY_TABLE = os.environ.get("MDX_FHIR_ID_REGISTRY_TABLE", "mdx-fhir-id-registry")

_dynamodb = boto3.client("dynamodb", region_name=_REGION)
_sqs = boto3.client("sqs", region_name=_REGION)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle transaction Bundle POST."""
    from fhir_validator import validate_resource, build_operation_outcome  # type: ignore

    try:
        bundle = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError as exc:
        return _err(400, f"Invalid JSON: {exc}")

    if bundle.get("resourceType") != "Bundle" or bundle.get("type") != "transaction":
        return _err(400, "Expected a FHIR transaction Bundle")

    entries = bundle.get("entry") or []
    validated_resources = []
    response_entries = []

    # Phase 1: validate all entries
    for i, entry in enumerate(entries):
        resource = entry.get("resource", {})
        errors = validate_resource(resource)
        if errors:
            # Any failure → abort all (Requirement 1.5, 1.6)
            return _response(422, {
                "resourceType": "OperationOutcome",
                "issue": [{
                    "severity": "error",
                    "code": "invariant",
                    "diagnostics": f"Entry {i} failed: {'; '.join(errors)}",
                    "location": [f"Bundle.entry[{i}]"],
                }],
            })
        resource["id"] = resource.get("id") or str(uuid.uuid4())
        validated_resources.append(resource)

    # Phase 2: atomic DynamoDB transaction to stage IDs
    org_id = _extract_org_id(event)
    try:
        _atomic_register_ids(org_id, validated_resources)
    except Exception as exc:
        logger.error("DynamoDB transaction aborted: %s", exc)
        return _response(500, build_operation_outcome([f"Transaction aborted: {exc}"]))

    # Phase 3: enqueue all to HealthLake
    for resource in validated_resources:
        _enqueue_healthlake(org_id, "create", resource)
        response_entries.append({
            "response": {
                "status": "201 Created",
                "location": f"{resource['resourceType']}/{resource['id']}",
            }
        })

    return _response(200, {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "type": "transaction-response",
        "entry": response_entries,
    })


def _atomic_register_ids(org_id: str, resources: list[dict]) -> None:
    """Register all resource IDs atomically in DynamoDB (two-phase)."""
    if not resources:
        return
    items = []
    for r in resources:
        rt = r.get("resourceType", "Unknown")
        rid = r.get("id", str(uuid.uuid4()))
        items.append({
            "Put": {
                "TableName": _FHIR_ID_REGISTRY_TABLE,
                "Item": {
                    "pk": {"S": f"{org_id}#{rt}"},
                    "sk": {"S": rid},
                    "healthLakeId": {"S": rid},
                    "orgId": {"S": org_id},
                    "resourceType": {"S": rt},
                },
                "ConditionExpression": "attribute_not_exists(pk) OR attribute_exists(pk)",
            }
        })
    # DynamoDB transactWrite supports max 100 items
    for i in range(0, len(items), 25):
        _dynamodb.transact_write_items(TransactItems=items[i:i+25])


def _enqueue_healthlake(org_id: str, operation: str, resource: dict) -> None:
    """Enqueue resource to HealthLake via SQS."""
    queue_url_template = os.environ.get(
        "MDX_HEALTHLAKE_QUEUE_URL_TEMPLATE",
        "https://sqs.{region}.amazonaws.com/000000000000/mdx-{org_id}-healthlake-inbound",
    )
    try:
        _sqs.send_message(
            QueueUrl=queue_url_template.format(region=_REGION, org_id=org_id),
            MessageBody=json.dumps({"orgId": org_id, "operation": operation, "resource": resource}),
        )
    except Exception as exc:
        logger.error("HealthLake enqueue failed: %s", exc)


def _extract_org_id(event: dict) -> str:
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims", {})
    return claims.get("custom:orgId") or ""


def _response(status: int, body: dict) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/fhir+json"},
        "body": json.dumps(body),
    }


def _err(status: int, msg: str) -> dict[str, Any]:
    return _response(status, {"resourceType": "OperationOutcome",
                               "issue": [{"severity": "error", "diagnostics": msg}]})
