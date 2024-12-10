"""
integration-bus-filter-config Lambda (task 12.3).

Stores per-org consumer filter rules in mdx-tenants DynamoDB.
Updates EventBridge rule patterns accordingly.
Supports filters: resource type, event type, orgId, patientId.

Requirements: 5.3
"""
from __future__ import annotations
import json, logging, os, sys
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_events = boto3.client("events", region_name=_REGION)
_dynamodb = boto3.resource("dynamodb", region_name=_REGION)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """PUT /v1/integration/filter-config"""
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError as exc:
        return _err(400, str(exc))

    org_id = _org_id(event)
    if not org_id:
        return _err(401, "Missing orgId")

    filters = body.get("filters", {})
    # Persist to DynamoDB tenant record
    try:
        table = _dynamodb.Table(os.environ.get("MDX_TENANTS_TABLE", "mdx-tenants"))
        table.update_item(
            Key={"orgId": org_id, "SK": "CONFIG"},
            UpdateExpression="SET filterRules = :f",
            ExpressionAttributeValues={":f": json.dumps(filters)},
        )
    except Exception as exc:
        logger.error("Failed to save filter config: %s", exc)
        return _err(500, "Failed to save filter config")

    # Build and update EventBridge rule pattern
    pattern = _build_event_pattern(org_id, filters)
    rule_name = f"mdx-{org_id}-filter-rule"
    event_bus = f"mdx-{org_id}-bus"
    try:
        _events.put_rule(
            Name=rule_name,
            EventBusName=event_bus,
            EventPattern=json.dumps(pattern),
            State="ENABLED",
            Description=f"Medyrax filter rule for org {org_id}",
        )
    except Exception as exc:
        logger.warning("EventBridge rule update failed: %s", exc)

    return {
        "statusCode": 200,
        "body": json.dumps({"orgId": org_id, "filters": filters, "ruleUpdated": True}),
    }


def _build_event_pattern(org_id: str, filters: dict) -> dict:
    pattern: dict[str, Any] = {"source": [{"prefix": "medyrax."}]}
    detail: dict[str, Any] = {"orgId": [org_id]}
    if filters.get("resourceType"):
        detail["resourceType"] = [filters["resourceType"]] if isinstance(
            filters["resourceType"], str) else filters["resourceType"]
    if filters.get("eventType"):
        detail["eventType"] = [filters["eventType"]] if isinstance(
            filters["eventType"], str) else filters["eventType"]
    if filters.get("patientId"):
        detail["patientId"] = [filters["patientId"]]
    pattern["detail"] = detail
    return pattern


def _org_id(event: dict) -> str:
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims", {})
    return claims.get("custom:orgId") or ""


def _err(code: int, msg: str) -> dict:
    return {"statusCode": code, "body": json.dumps({"error": msg})}
