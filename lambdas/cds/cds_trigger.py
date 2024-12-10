"""
cds-trigger Lambda (task 19.1).

Subscribed to Integration Bus events for Observation.created.
Evaluates LOINC codes against criticality list in mdx-cds-critical-loinc DynamoDB.
If critical: starts Step Function mdx-cds-sfn within 15s.

Requirements: 12.1
"""
from __future__ import annotations
import json, logging, os, sys, time, uuid
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_CDS_SFN_ARN = os.environ.get("MDX_CDS_SFN_ARN", "")
_CRITICAL_LOINC_TABLE = os.environ.get("MDX_CDS_CRITICAL_LOINC_TABLE", "mdx-cds-critical-loinc")

_sfn = boto3.client("stepfunctions", region_name=_REGION)
_dynamodb = boto3.resource("dynamodb", region_name=_REGION)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Process EventBridge events for Observation.created."""
    start = time.monotonic()

    detail = event.get("detail", {})
    org_id = detail.get("orgId", "")
    payload = detail.get("payload", {})
    resource_type = detail.get("resourceType", payload.get("resourceType", ""))

    if resource_type != "Observation":
        return {"statusCode": 200, "body": "Not an Observation event"}

    # Extract LOINC code from Observation
    code_obj = payload.get("code", {})
    codings = code_obj.get("coding", [{}])
    loinc_code = next(
        (c.get("code") for c in codings if "loinc" in c.get("system", "").lower()),
        codings[0].get("code", "") if codings else "",
    )
    patient_id = (payload.get("subject") or {}).get("reference", "").replace("Patient/", "")

    if not loinc_code:
        return {"statusCode": 200, "body": "No LOINC code found"}

    # Check if LOINC code is in criticality list
    is_critical = _check_critical_loinc(org_id, loinc_code)
    if not is_critical:
        logger.debug("LOINC %s is not critical for org=%s", loinc_code, org_id)
        return {"statusCode": 200, "body": "Not critical"}

    # Start CDS Step Function
    if not _CDS_SFN_ARN:
        logger.warning("MDX_CDS_SFN_ARN not configured")
        return {"statusCode": 200, "body": "CDS SFN not configured"}

    execution_name = f"cds-{loinc_code[:8]}-{uuid.uuid4().hex[:8]}"
    try:
        _sfn.start_execution(
            stateMachineArn=_CDS_SFN_ARN,
            name=execution_name,
            input=json.dumps({
                "orgId": org_id,
                "patientId": patient_id,
                "observationId": payload.get("id", ""),
                "loincCode": loinc_code,
                "observation": payload,
            }),
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "CDS SFN started: org=%s loinc=%s patient=%s elapsed=%.0fms",
            org_id, loinc_code, patient_id, elapsed_ms,
        )
        if elapsed_ms > 15000:
            logger.warning("CDS trigger exceeded 15s SLA: %.0fms", elapsed_ms)
    except Exception as exc:
        logger.error("Failed to start CDS SFN: %s", exc)

    return {"statusCode": 200, "body": json.dumps({"triggered": True, "loincCode": loinc_code})}


def _check_critical_loinc(org_id: str, loinc_code: str) -> bool:
    """Check if a LOINC code is in the org's criticality list."""
    try:
        table = _dynamodb.Table(_CRITICAL_LOINC_TABLE)
        # Check org-specific critical codes first, then platform-wide defaults
        for pk in [f"{org_id}#{loinc_code}", f"default#{loinc_code}"]:
            resp = table.get_item(Key={"pk": pk})
            if resp.get("Item"):
                return True
    except Exception as exc:
        logger.warning("Critical LOINC lookup failed: %s — defaulting to non-critical", exc)
    return False
