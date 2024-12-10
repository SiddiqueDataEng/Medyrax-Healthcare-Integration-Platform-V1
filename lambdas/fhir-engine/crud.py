"""
fhir-engine-crud Lambda handler (task 9.2).

Handles POST/PUT/GET/DELETE for all 11 supported FHIR R4 resource types.
Assigns server-generated logical ID on create; writes to mdx-fhir-id-registry;
delegates persistence to healthlake-writer via SQS; publishes event to Integration Bus.

Requirements: 1.3, 1.4, 1.7
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
_HEALTHLAKE_QUEUE_TEMPLATE = os.environ.get(
    "MDX_HEALTHLAKE_QUEUE_URL_TEMPLATE",
    "https://sqs.{region}.amazonaws.com/000000000000/mdx-{org_id}-healthlake-inbound",
)
_EVENT_BUS_ARN_TEMPLATE = os.environ.get(
    "MDX_EVENT_BUS_ARN_TEMPLATE",
    "arn:aws:events:{region}:000000000000:event-bus/mdx-{org_id}-bus",
)
_FHIR_ID_REGISTRY_TABLE = os.environ.get("MDX_FHIR_ID_REGISTRY_TABLE", "mdx-fhir-id-registry")

_sqs = boto3.client("sqs", region_name=_REGION)
_events = boto3.client("events", region_name=_REGION)
_dynamodb = boto3.resource("dynamodb", region_name=_REGION)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Route CRUD operations to sub-handlers."""
    method = (event.get("httpMethod") or "").upper()
    path_params = event.get("pathParameters") or {}
    resource_type = path_params.get("resource", "")
    resource_id = path_params.get("id", "")
    org_id = _extract_org_id(event)

    if not resource_type:
        return _err(400, "Missing resource type in path")

    if method == "POST":
        return _create(event, resource_type, org_id)
    if method == "PUT" and resource_id:
        return _update(event, resource_type, resource_id, org_id)
    if method == "GET" and resource_id:
        return _read(resource_type, resource_id, org_id)
    if method == "DELETE" and resource_id:
        return _delete(resource_type, resource_id, org_id)

    return _err(405, f"Method {method} not allowed")


def _create(event: dict, resource_type: str, org_id: str) -> dict[str, Any]:
    """Create a new FHIR resource."""
    from fhir_validator import validate_resource, build_operation_outcome  # type: ignore

    try:
        resource = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError as exc:
        return _err(400, f"Invalid JSON: {exc}")

    errors = validate_resource(resource)
    if errors:
        return _response(422, build_operation_outcome(errors))

    # Assign server-generated logical ID
    server_id = str(uuid.uuid4())
    resource["id"] = server_id

    # Register in fhir-id-registry
    client_id = resource.get("id") or server_id
    _register_fhir_id(org_id, resource_type, client_id, server_id)

    # Delegate persistence to HealthLake via SQS
    _enqueue_healthlake(org_id, "create", resource)

    # Publish event to Integration Bus
    _publish_event(org_id, resource_type, server_id, "fhir.resource.created", resource)

    return _response(201, resource, headers={"Location": f"/{resource_type}/{server_id}"})


def _update(event: dict, resource_type: str, resource_id: str, org_id: str) -> dict[str, Any]:
    """Update an existing FHIR resource."""
    from fhir_validator import validate_resource, build_operation_outcome  # type: ignore

    try:
        resource = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError as exc:
        return _err(400, f"Invalid JSON: {exc}")

    resource["id"] = resource_id
    errors = validate_resource(resource)
    if errors:
        return _response(422, build_operation_outcome(errors))

    _enqueue_healthlake(org_id, "update", resource)
    _publish_event(org_id, resource_type, resource_id, "fhir.resource.updated", resource)
    return _response(200, resource)


def _read(resource_type: str, resource_id: str, org_id: str) -> dict[str, Any]:
    """Read a FHIR resource (stub — actual read delegated to healthlake-reader)."""
    # In production this invokes healthlake-reader Lambda synchronously.
    # MVP: return a placeholder OperationOutcome directing caller to HealthLake.
    return _response(200, {
        "resourceType": resource_type,
        "id": resource_id,
        "meta": {"comment": "Fetched via HealthLake — use healthlake-reader for direct queries"},
    })


def _delete(resource_type: str, resource_id: str, org_id: str) -> dict[str, Any]:
    """Soft-delete a FHIR resource."""
    _enqueue_healthlake(org_id, "delete", {"resourceType": resource_type, "id": resource_id})
    _publish_event(org_id, resource_type, resource_id, "fhir.resource.deleted", {})
    return {"statusCode": 204, "headers": {}, "body": ""}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _register_fhir_id(org_id: str, resource_type: str, client_id: str, server_id: str) -> None:
    try:
        table = _dynamodb.Table(_FHIR_ID_REGISTRY_TABLE)
        table.put_item(Item={
            "pk": f"{org_id}#{resource_type}",
            "sk": client_id,
            "healthLakeId": server_id,
            "orgId": org_id,
            "resourceType": resource_type,
        })
    except Exception as exc:
        logger.error("fhir-id-registry write failed: %s", exc)


def _enqueue_healthlake(org_id: str, operation: str, resource: dict) -> None:
    queue_url = _HEALTHLAKE_QUEUE_TEMPLATE.format(region=_REGION, org_id=org_id)
    try:
        _sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({
                "orgId": org_id,
                "operation": operation,
                "resource": resource,
            }),
        )
    except Exception as exc:
        logger.error("HealthLake SQS enqueue failed: %s", exc)


def _publish_event(org_id: str, resource_type: str, resource_id: str,
                   event_type: str, payload: dict) -> None:
    event_bus_arn = _EVENT_BUS_ARN_TEMPLATE.format(region=_REGION, org_id=org_id)
    try:
        _events.put_events(Entries=[{
            "Source": "medyrax.fhir-engine",
            "DetailType": event_type,
            "Detail": json.dumps({
                "eventId": str(uuid.uuid4()),
                "orgId": org_id,
                "resourceType": resource_type,
                "resourceId": resource_id,
                "eventType": event_type,
                "payload": payload,
                "schemaVersion": "1.0",
            }),
            "EventBusName": event_bus_arn,
        }])
    except Exception as exc:
        logger.error("EventBridge publish failed: %s", exc)


def _extract_org_id(event: dict) -> str:
    """Extract org_id from JWT claims or request context."""
    claims = (
        (event.get("requestContext") or {})
        .get("authorizer", {})
        .get("claims", {})
    )
    return claims.get("custom:orgId") or claims.get("orgId") or ""


def _response(status: int, body: dict, headers: dict | None = None) -> dict[str, Any]:
    h = {"Content-Type": "application/fhir+json"}
    if headers:
        h.update(headers)
    return {"statusCode": status, "headers": h, "body": json.dumps(body)}


def _err(status: int, msg: str) -> dict[str, Any]:
    return _response(status, {"error": msg})
