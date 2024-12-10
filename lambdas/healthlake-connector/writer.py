"""
healthlake-writer Lambda (task 11.1).

Triggered by SQS queue mdx-{orgId}-healthlake-inbound.
Calls HealthLake CreateResource/UpdateResource, retries 1s/2s/4s.
On exhaustion publishes dead-letter event to Integration Bus.
On success publishes healthlake.resource.persisted event.

Requirements: 3.1, 3.2, 3.3
"""
from __future__ import annotations
import json, logging, os, sys, uuid
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_EVENT_BUS_TPL = os.environ.get(
    "MDX_EVENT_BUS_ARN_TEMPLATE",
    "arn:aws:events:{region}:000000000000:event-bus/mdx-{org_id}-bus",
)
_events = boto3.client("events", region_name=_REGION)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    failures = []
    for record in event.get("Records", []):
        try:
            _process(record)
        except Exception as exc:
            logger.error("healthlake-writer failed: %s", exc)
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def _process(record: dict) -> None:
    body = json.loads(record.get("body", "{}"))
    org_id = body.get("orgId", "")
    operation = body.get("operation", "create")
    resource = body.get("resource", {})
    resource_type = resource.get("resourceType", "")
    resource_id = resource.get("id", "")

    # Load tenant config to get dataStoreId
    from mdx_common.tenant_config_service import get_tenant_config  # type: ignore
    from mdx_common.errors import HealthLakeError  # type: ignore
    from healthlake_client import HealthLakeClient  # type: ignore

    config = get_tenant_config(org_id)
    client = HealthLakeClient(region=_REGION)

    try:
        if operation == "create":
            resp = client.create_resource(config.health_lake_data_store_id, resource)
            hl_id = resp.get("ResourceId", resource_id)
        elif operation == "update":
            resp = client.update_resource(
                config.health_lake_data_store_id, resource_type, resource_id, resource
            )
            hl_id = resource_id
        else:
            logger.warning("Unknown operation %s, skipping", operation)
            return

        # Publish success event
        _publish(org_id, "healthlake.resource.persisted", {
            "resourceType": resource_type,
            "resourceId": hl_id,
            "operation": operation,
        })
        logger.info("HealthLake %s succeeded: %s/%s", operation, resource_type, hl_id)

    except HealthLakeError as exc:
        # All retries exhausted — publish dead-letter event (Req 3.3)
        logger.error("HealthLake exhausted retries: %s", exc)
        _publish(org_id, "healthlake.resource.dead_letter", {
            "resourceType": resource_type,
            "resourceId": resource_id,
            "operation": operation,
            "error": str(exc),
        })


def _publish(org_id: str, event_type: str, detail: dict) -> None:
    try:
        _events.put_events(Entries=[{
            "Source": "medyrax.healthlake-writer",
            "DetailType": event_type,
            "Detail": json.dumps({
                "eventId": str(uuid.uuid4()),
                "orgId": org_id,
                "eventType": event_type,
                "payload": detail,
                "schemaVersion": "1.0",
            }),
            "EventBusName": _EVENT_BUS_TPL.format(region=_REGION, org_id=org_id),
        }])
    except Exception as exc:
        logger.error("EventBridge publish failed: %s", exc)
