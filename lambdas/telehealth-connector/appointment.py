"""
telehealth-appointment Lambda (task 17.1).

POST /v1/fhir/r4/integration/telehealth/appointment
Receives appointment event, creates FHIR Appointment resource,
publishes to Integration Bus within 3s.

Requirements: 10.4
"""
from __future__ import annotations
import gzip, json, logging, os, sys, time, uuid
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
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError as exc:
        return _err(400, str(exc))

    appointment_id = str(uuid.uuid4())
    fhir_appointment = {
        "resourceType": "Appointment",
        "id": appointment_id,
        "status": body.get("status", "booked"),
        "start": body.get("startTime", ""),
        "end": body.get("endTime", ""),
        "participant": body.get("participants", []),
        "serviceType": [{"text": body.get("serviceType", "telehealth")}],
        "description": body.get("description", ""),
        "meta": {"source": "telehealth-connector"},
    }

    # Publish to Integration Bus
    _events.put_events(Entries=[{
        "Source": "medyrax.telehealth",
        "DetailType": "fhir.resource.created",
        "Detail": json.dumps({
            "eventId": str(uuid.uuid4()),
            "orgId": org_id,
            "resourceType": "Appointment",
            "eventType": "fhir.resource.created",
            "payload": fhir_appointment,
            "schemaVersion": "1.0",
        }),
        "EventBusName": _EVENT_BUS_TPL.format(region=_REGION, org_id=org_id),
    }])

    elapsed = (time.monotonic() - start) * 1000
    if elapsed > 3000:
        logger.warning("Appointment exceeded 3s SLA: %.0fms", elapsed)

    return {
        "statusCode": 201,
        "headers": {"Content-Type": "application/fhir+json"},
        "body": json.dumps(fhir_appointment),
    }


def _org_id(event: dict) -> str:
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims", {})
    return claims.get("custom:orgId") or ""


def _err(code: int, msg: str) -> dict:
    return {"statusCode": code, "body": json.dumps({"error": msg})}
