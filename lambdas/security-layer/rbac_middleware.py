"""
RBAC enforcement middleware (task 13.2).

Lambda Powertools-style middleware: extracts JWT claims, resolves role from
Cognito groups, checks against DynamoDB role-permission matrix.
On denial: returns HTTP 403 and calls audit_logger with allowed=False.

Requirements: 7.4, 7.5
"""
from __future__ import annotations
import functools, json, logging, os, sys
from typing import Any, Callable

import boto3
from boto3.dynamodb.conditions import Key

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)

_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_RBAC_TABLE = os.environ.get("MDX_RBAC_TABLE", "mdx-rbac-permissions")

_dynamodb = boto3.resource("dynamodb", region_name=_REGION)

# In-process permission cache (role -> set of allowed operations)
_perm_cache: dict[str, set[str]] = {}


def _get_permissions(role: str) -> set[str]:
    """Load allowed operations for a role from DynamoDB (cached)."""
    if role in _perm_cache:
        return _perm_cache[role]
    try:
        table = _dynamodb.Table(_RBAC_TABLE)
        resp = table.query(KeyConditionExpression=Key("roleName").eq(role))
        perms = {item["permission"] for item in resp.get("Items", [])}
        _perm_cache[role] = perms
        return perms
    except Exception as exc:
        logger.error("RBAC table query failed for role=%s: %s", role, exc)
        return set()


def require_permission(permission: str):
    """
    Decorator that enforces RBAC permission check before a Lambda handler runs.

    Usage::

        @require_permission("fhir:Patient:read")
        def handler(event, context):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(event: dict, context: Any) -> Any:
            from audit_logger import write_audit_event  # type: ignore

            claims = (
                (event.get("requestContext") or {})
                .get("authorizer", {})
                .get("claims", {})
            )
            accessor_id = claims.get("sub", "unknown")
            groups = claims.get("cognito:groups", [])
            if isinstance(groups, str):
                groups = [groups]
            role = groups[0] if groups else "unknown"
            org_id = claims.get("custom:orgId") or "unknown"
            source_ip = (
                (event.get("requestContext") or {})
                .get("identity", {})
                .get("sourceIp", "unknown")
            )

            allowed_perms = _get_permissions(role)

            # Check both exact permission and wildcard
            if permission not in allowed_perms and "*" not in allowed_perms:
                logger.warning(
                    "RBAC denied: accessor=%s role=%s permission=%s org=%s",
                    accessor_id, role, permission, org_id,
                )
                write_audit_event(
                    accessor_id=accessor_id,
                    accessor_role=role,
                    org_id=org_id,
                    resource_type=permission.split(":")[1] if ":" in permission else permission,
                    resource_id="",
                    operation=permission.split(":")[2] if permission.count(":") >= 2 else "access",
                    source_ip=source_ip,
                    allowed=False,
                )
                return {
                    "statusCode": 403,
                    "headers": {"Content-Type": "application/json",
                                "WWW-Authenticate": 'Bearer error="insufficient_scope"'},
                    "body": json.dumps({
                        "error": "access_denied",
                        "message": f"Role '{role}' lacks permission '{permission}'",
                    }),
                }

            return func(event, context)
        return wrapper
    return decorator


def seed_default_permissions() -> None:
    """
    Seed the RBAC table with default role permissions.
    Call once during environment bootstrap.
    """
    DEFAULT_PERMISSIONS = {
        "Platform_Admin": ["*"],
        "Organization_Admin": [
            "fhir:*:read", "fhir:*:create", "fhir:*:update",
            "tenant:*:read", "tenant:*:update",
        ],
        "Clinical_User": [
            "fhir:Patient:read", "fhir:Encounter:read", "fhir:Observation:read",
            "fhir:Observation:create", "fhir:Condition:read",
            "fhir:MedicationRequest:read", "fhir:DiagnosticReport:read",
        ],
        "Integration_Service": [
            "fhir:*:read", "fhir:*:create", "fhir:*:update",
            "healthlake:*:*", "integration_bus:*:publish",
        ],
        "Audit_Reviewer": [
            "audit:*:read", "compliance:*:read",
        ],
    }
    table = _dynamodb.Table(_RBAC_TABLE)
    for role, perms in DEFAULT_PERMISSIONS.items():
        for perm in perms:
            try:
                table.put_item(Item={"roleName": role, "permission": perm})
            except Exception as exc:
                logger.warning("Failed to seed permission %s/%s: %s", role, perm, exc)
