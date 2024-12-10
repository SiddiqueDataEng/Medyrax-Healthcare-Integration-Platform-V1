"""
telehealth-resource-router Lambda (task 17.4).

POST /v1/fhir/r4/integration/telehealth/resources
Routes Encounter/Observation resources to HealthLake via Integration Bus within 2s.

Requirements: 10.1
"""
from __future__ import annotations
import json, logging, os, sys, time, uuid
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_EVENT_BUS_TPL = os.environ.get(
    "MDX_EVENT_BUS_ARN_TEMPLATE",
    "arn:aws:events:{region}:000000000000:event-bus/mdx-{org_id}-bus",
)
_events = boto3.client("events", region_name=_REGION)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    start = time.monotonic()
    org_id = _org_id(event)
    if not org_id:
        return _err(401, "Missing orgId")

    try:
        resource = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError as exc:
        return _err(400, str(exc))

    resource_type = resource.get("resourceType", "")
    if resource_type not in ("Encounter", "Observation"):
        return _err(400, f"Only Encounter/Observation resources are accepted, got: {resource_type}")

    resource.setdefault("id", str(uuid.uuid4()))

    _events.put_events(Entries=[{
        "Source": "medyrax.telehealth-router",
        "DetailType": "fhir.resource.ingest",
        "Detail": json.dumps({
            "eventId": str(uuid.uuid4()),
            "orgId": org_id,
            "resourceType": resource_type,
            "eventType": "fhir.resource.ingest",
            "payload": resource,
            "schemaVersion": "1.0",
        }),
        "EventBusName": _EVENT_BUS_TPL.format(region=_REGION, org_id=org_id),
    }])

    elapsed = (time.monotonic() - start) * 1000
    if elapsed > 2000:
        logger.warning("resource-router exceeded 2s SLA: %.0fms", elapsed)

    return {
        "statusCode": 202,
        "headers": {"Content-Type": "application/fhir+json"},
        "body": json.dumps({
            "resourceType": resource_type,
            "id": resource["id"],
            "status": "queued",
        }),
    }


def _org_id(event: dict) -> str:
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims", {})
    return claims.get("custom:orgId") or ""


def _err(code: int, msg: str) -> dict:
    return {"statusCode": code, "body": json.dumps({"error": msg})}
