"""
terminology-validator Lambda handler (tasks 5.1, 5.2, 5.3).

GET  /v1/fhir/r4/CodeSystem/$validate-code  -> validates a code against LOINC/SNOMED/ICD-10/NPI
POST /v1/fhir/r4/ConceptMap/$translate      -> translates local codes to standard codes

SLA: 300ms for validation, weekly refresh via terminology-refresher.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.7
"""
from __future__ import annotations
import json, logging, os, sys, time
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_TERMINOLOGY_TABLE = os.environ.get("MDX_TERMINOLOGY_TABLE", "mdx-terminology-codes")
_REVIEW_QUEUE_TPL = os.environ.get(
    "MDX_REVIEW_QUEUE_URL_TEMPLATE",
    "https://sqs.{region}.amazonaws.com/000000000000/mdx-{org_id}-review-queue",
)

_dynamodb = boto3.resource("dynamodb", region_name=_REGION)
_sqs = boto3.client("sqs", region_name=_REGION)

# Supported code systems (Requirement 4.1)
SUPPORTED_SYSTEMS = {
    "http://loinc.org": "LOINC",
    "http://snomed.info/sct": "SNOMED",
    "http://hl7.org/fhir/sid/icd-10": "ICD-10",
    "http://hl7.org/fhir/sid/icd-10-cm": "ICD-10",
    "http://hl7.org/fhir/sid/us-npi": "NPI",
    "LOINC": "LOINC",
    "SNOMED": "SNOMED",
    "ICD-10": "ICD-10",
    "NPI": "NPI",
}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    start = time.monotonic()
    http_method = (event.get("httpMethod") or "GET").upper()
    path = event.get("path") or event.get("resource") or ""
    org_id = _org_id(event)

    if "$validate-code" in path:
        result = _validate_code(event, org_id)
    elif "$translate" in path:
        result = _translate_code(event, org_id)
    else:
        result = _err(404, "Not found")

    elapsed_ms = (time.monotonic() - start) * 1000
    if elapsed_ms > 300:
        logger.warning("Terminology operation exceeded 300ms SLA: %.1fms", elapsed_ms)
    return result


def _validate_code(event: dict, org_id: str) -> dict[str, Any]:
    """Validate a code against its declared terminology system."""
    params = event.get("queryStringParameters") or {}
    code = params.get("code", "")
    system = params.get("system", "")

    if not code or not system:
        return _err(400, "Both 'code' and 'system' query parameters are required")

    sys_key = SUPPORTED_SYSTEMS.get(system)
    if not sys_key:
        return _ok({
            "resourceType": "Parameters",
            "parameter": [
                {"name": "result", "valueBoolean": False},
                {"name": "message", "valueString": f"Unsupported terminology system: {system}"},
                {"name": "confidence", "valueDecimal": 0.0},
            ],
        })

    # Check DynamoDB (fallback when Redis unavailable)
    pk = f"{sys_key}#{code}"
    try:
        table = _dynamodb.Table(_TERMINOLOGY_TABLE)
        resp = table.get_item(Key={"pk": pk})
        item = resp.get("Item")
    except Exception as exc:
        logger.warning("DynamoDB lookup failed for %s: %s", pk, exc)
        item = None

    if item:
        return _ok({
            "resourceType": "Parameters",
            "parameter": [
                {"name": "result", "valueBoolean": True},
                {"name": "display", "valueString": item.get("display", code)},
                {"name": "confidence", "valueDecimal": 1.0},
            ],
        })

    return _ok({
        "resourceType": "Parameters",
        "parameter": [
            {"name": "result", "valueBoolean": False},
            {"name": "message", "valueString": f"Code '{code}' not found in {sys_key}"},
            {"name": "confidence", "valueDecimal": 0.0},
        ],
    })


def _translate_code(event: dict, org_id: str) -> dict[str, Any]:
    """Translate a local code to a standard code using ConceptMap records."""
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _err(400, "Invalid JSON body")

    params = body.get("parameter", [])
    source_code = next((p.get("valueCode") for p in params if p.get("name") == "code"), "")
    source_system = next((p.get("valueUri") for p in params if p.get("name") == "system"), "")

    if not source_code:
        return _err(400, "Missing 'code' parameter")

    # Look up ConceptMap in DynamoDB
    pk = f"CONCEPTMAP#{source_system}#{source_code}"
    try:
        table = _dynamodb.Table(_TERMINOLOGY_TABLE)
        resp = table.get_item(Key={"pk": pk})
        item = resp.get("Item")
    except Exception as exc:
        logger.warning("ConceptMap lookup failed: %s", exc)
        item = None

    if item:
        return _ok({
            "resourceType": "Parameters",
            "parameter": [
                {"name": "result", "valueBoolean": True},
                {"name": "match", "part": [
                    {"name": "equivalence", "valueCode": "equivalent"},
                    {"name": "concept", "valueCoding": {
                        "system": item.get("targetSystem", source_system),
                        "code": item.get("targetCode", source_code),
                        "display": item.get("targetDisplay", ""),
                    }},
                ]},
            ],
        })

    # No mapping found — return original code with data-absent-reason (Requirement 4.3)
    _publish_to_review_queue(org_id, source_code, source_system)

    return _ok({
        "resourceType": "Parameters",
        "parameter": [
            {"name": "result", "valueBoolean": False},
            {"name": "match", "part": [
                {"name": "equivalence", "valueCode": "unmatched"},
                {"name": "concept", "valueCoding": {
                    "system": source_system,
                    "code": source_code,
                    "extension": [{
                        "url": "http://hl7.org/fhir/StructureDefinition/data-absent-reason",
                        "valueCode": "unknown",
                    }],
                }},
            ]},
        ],
    })


def _publish_to_review_queue(org_id: str, code: str, system: str) -> None:
    """Publish unmatched code to review queue (Requirement 4.3)."""
    if not org_id:
        return
    try:
        queue_url = _REVIEW_QUEUE_TPL.format(region=_REGION, org_id=org_id)
        _sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({
                "orgId": org_id,
                "unmappedCode": code,
                "codeSystem": system,
                "action": "review_mapping",
            }),
        )
    except Exception as exc:
        logger.warning("Failed to publish to review queue: %s", exc)


def _org_id(event: dict) -> str:
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims", {})
    return claims.get("custom:orgId") or ""


def _ok(body: dict) -> dict[str, Any]:
    return {"statusCode": 200,
            "headers": {"Content-Type": "application/fhir+json"},
            "body": json.dumps(body)}


def _err(code: int, msg: str) -> dict[str, Any]:
    return {"statusCode": code,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": msg})}
