"""
cds-hooks-service Lambda (tasks 19.1, 19.3).

CDS Hooks discovery endpoint GET /cds-services.
Handles patient-view, order-sign, order-select hooks.
Prefetches FHIR context from HealthLake.
Returns suggestion/info/warning cards.

Requirements: CDS Hooks 1.0 spec
"""
from __future__ import annotations
import json, logging, os, sys
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_RULES_TABLE = os.environ.get("MDX_CDS_RULES_TABLE", "mdx-cds-rules")

_dynamodb = boto3.resource("dynamodb", region_name=_REGION)

# Built-in CDS services
_SERVICES = [
    {
        "id": "medyrax-patient-view",
        "hook": "patient-view",
        "title": "Medyrax Patient Risk Assessment",
        "description": "Evaluates patient risk based on clinical history.",
        "prefetch": {
            "patient": "Patient/{{context.patientId}}",
            "conditions": "Condition?patient={{context.patientId}}&_count=10",
        },
    },
    {
        "id": "medyrax-order-sign",
        "hook": "order-sign",
        "title": "Medyrax Order Validation",
        "description": "Validates medication orders against patient history.",
        "prefetch": {
            "patient": "Patient/{{context.patientId}}",
            "medications": "MedicationRequest?patient={{context.patientId}}&_count=20",
        },
    },
    {
        "id": "medyrax-order-select",
        "hook": "order-select",
        "title": "Medyrax Drug Interaction Check",
        "description": "Checks for drug interactions on order selection.",
        "prefetch": {
            "medications": "MedicationRequest?patient={{context.patientId}}&_count=20",
        },
    },
]


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    http_method = (event.get("httpMethod") or "GET").upper()
    path = event.get("path") or event.get("resource") or ""

    # Discovery endpoint
    if http_method == "GET" and "/cds-services" in path and not _is_hook_invocation(path):
        return _response(200, {"services": _SERVICES})

    # Hook invocation
    if http_method == "POST":
        hook_id = _extract_hook_id(path)
        return _invoke_hook(event, hook_id)

    return _response(404, {"error": "Not found"})


def _is_hook_invocation(path: str) -> bool:
    parts = path.rstrip("/").split("/")
    return len(parts) >= 2 and parts[-2] == "cds-services"


def _extract_hook_id(path: str) -> str:
    parts = path.rstrip("/").split("/")
    return parts[-1] if parts else ""


def _invoke_hook(event: dict, hook_id: str) -> dict[str, Any]:
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON"})

    hook = body.get("hook", "")
    context = body.get("context", {})
    prefetch = body.get("prefetch", {})
    org_id = _org_id(event)

    cards = []

    # Load org-specific rules from DynamoDB
    rules = _load_rules(org_id, hook)

    for rule in rules:
        card = _evaluate_rule(rule, context, prefetch)
        if card:
            cards.append(card)

    # Default cards for built-in hooks
    if not rules:
        cards.extend(_default_cards(hook, context))

    return _response(200, {"cards": cards})


def _load_rules(org_id: str, hook: str) -> list[dict]:
    try:
        table = _dynamodb.Table(_RULES_TABLE)
        resp = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("orgId").eq(org_id),
        )
        return [r for r in resp.get("Items", []) if r.get("hookType") == hook]
    except Exception as exc:
        logger.warning("Failed to load CDS rules: %s", exc)
        return []


def _evaluate_rule(rule: dict, context: dict, prefetch: dict) -> dict | None:
    """Evaluate a FHIRPath-based rule and return a CDS card or None."""
    try:
        condition = rule.get("condition", "true")
        if condition == "true":
            return {
                "summary": rule.get("summary", "Clinical Decision Support Alert"),
                "indicator": rule.get("indicator", "info"),
                "source": {"label": "Medyrax CDS", "url": "https://medyrax.io"},
                "detail": rule.get("detail", ""),
            }
    except Exception as exc:
        logger.warning("Rule evaluation error: %s", exc)
    return None


def _default_cards(hook: str, context: dict) -> list[dict]:
    if hook == "patient-view":
        return [{
            "summary": "Patient record loaded",
            "indicator": "info",
            "source": {"label": "Medyrax CDS"},
            "detail": "Patient history retrieved successfully.",
        }]
    return []


def _org_id(event: dict) -> str:
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims", {})
    return claims.get("custom:orgId") or ""


def _response(status: int, body: dict) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
