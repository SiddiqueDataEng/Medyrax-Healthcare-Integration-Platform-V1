"""
telehealth-encounter-trigger Lambda (task 17.3).

Detects encounter conclusion event on Integration Bus.
Starts mdx-telehealth-encounter-sfn Step Function.

Step Function states:
  QueryPatientRecord → AggregateEncounterSummary → GenerateDocumentReference
  → RouteToPrimaryEHR → PublishCompletionEvent

End-to-end within 5 minutes SLA.

Requirements: 10.2
"""
from __future__ import annotations
import json, logging, os, sys, uuid
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)

_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_SFN_ARN = os.environ.get("MDX_TELEHEALTH_ENCOUNTER_SFN_ARN", "")
_sfn = boto3.client("stepfunctions", region_name=_REGION)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Triggered by EventBridge rule on encounter.concluded events."""
    detail = event.get("detail", {})
    org_id = detail.get("orgId", "")
    payload = detail.get("payload", {})
    encounter_id = payload.get("encounterId") or payload.get("id", "")
    patient_id = payload.get("patientId") or detail.get("patientId", "")

    if not org_id or not encounter_id:
        logger.error("Missing orgId or encounterId in encounter.concluded event")
        return {"statusCode": 400, "body": "Missing required fields"}

    if not _SFN_ARN:
        logger.warning("MDX_TELEHEALTH_ENCOUNTER_SFN_ARN not configured")
        return {"statusCode": 200, "body": "SFN not configured"}

    execution_name = f"encounter-{encounter_id[:12]}-{uuid.uuid4().hex[:8]}"

    try:
        resp = _sfn.start_execution(
            stateMachineArn=_SFN_ARN,
            name=execution_name,
            input=json.dumps({
                "orgId": org_id,
                "patientId": patient_id,
                "encounterId": encounter_id,
                "sourceEvent": detail,
            }),
        )
        logger.info(
            "Started telehealth encounter SFN: org=%s encounter=%s execution=%s",
            org_id, encounter_id, resp.get("executionArn", ""),
        )
        return {"statusCode": 202, "body": json.dumps({"executionArn": resp.get("executionArn")})}
    except Exception as exc:
        logger.error("Failed to start encounter SFN: %s", exc)
        return {"statusCode": 500, "body": json.dumps({"error": str(exc)})}
