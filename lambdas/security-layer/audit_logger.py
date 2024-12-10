"""
security-audit-logger Lambda + middleware (task 13.1).

Writes structured JSON audit events to CloudWatch Logs mdx-audit-{orgId}
within 1 second of every PHI access.

Audit record fields:
  timestamp, accessorId, accessorRole, orgId, resourceType,
  resourceId, operation, sourceIp, allowed

Requirements: 7.3
"""
from __future__ import annotations
import functools, json, logging, os, sys, time, uuid
from datetime import datetime, timezone
from typing import Any, Callable

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_LOG_GROUP_TPL = "mdx-audit-{org_id}"

_logs = boto3.client("logs", region_name=_REGION)

# In-process cache of sequence tokens per log stream
_sequence_tokens: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Core write function
# ---------------------------------------------------------------------------

def write_audit_event(
    *,
    accessor_id: str,
    accessor_role: str,
    org_id: str,
    resource_type: str,
    resource_id: str,
    operation: str,
    source_ip: str,
    allowed: bool,
    event_id: str | None = None,
) -> None:
    """
    Write one audit event to CloudWatch Logs within 1s.
    Non-blocking — logs warning on CWL failure, never raises.
    """
    now = datetime.now(tz=timezone.utc)
    record = {
        "eventId": event_id or str(uuid.uuid4()),
        "timestamp": now.isoformat(),
        "accessorId": accessor_id,
        "accessorRole": accessor_role,
        "orgId": org_id,
        "resourceType": resource_type,
        "resourceId": resource_id,
        "operation": operation,
        "sourceIp": source_ip,
        "allowed": allowed,
    }

    log_group = _LOG_GROUP_TPL.format(org_id=org_id)
    log_stream = now.strftime("%Y/%m/%d")

    try:
        _ensure_log_stream(log_group, log_stream)
        kwargs: dict[str, Any] = {
            "logGroupName": log_group,
            "logStreamName": log_stream,
            "logEvents": [{
                "timestamp": int(now.timestamp() * 1000),
                "message": json.dumps(record),
            }],
        }
        token = _sequence_tokens.get(f"{log_group}/{log_stream}")
        if token:
            kwargs["sequenceToken"] = token

        resp = _logs.put_log_events(**kwargs)
        _sequence_tokens[f"{log_group}/{log_stream}"] = (
            resp.get("nextSequenceToken", "")
        )
    except Exception as exc:
        logger.warning("Failed to write audit event to CWL: %s", exc)


def _ensure_log_stream(group: str, stream: str) -> None:
    """Create log group/stream if they don't exist (idempotent)."""
    stream_key = f"{group}/{stream}"
    if stream_key in _sequence_tokens:
        return
    try:
        _logs.create_log_group(logGroupName=group)
    except _logs.exceptions.ResourceAlreadyExistsException:
        pass
    except Exception:
        pass
    try:
        _logs.create_log_stream(logGroupName=group, logStreamName=stream)
    except _logs.exceptions.ResourceAlreadyExistsException:
        pass
    except Exception:
        pass
    _sequence_tokens[stream_key] = ""   # mark as initialised


# ---------------------------------------------------------------------------
# Decorator / middleware
# ---------------------------------------------------------------------------

def audit_middleware(
    resource_type: str = "",
    operation: str = "",
):
    """
    Decorator that wraps a Lambda handler and writes an audit event.

    Usage::

        @audit_middleware(resource_type="Patient", operation="read")
        def handler(event, context):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(event: dict, context: Any) -> Any:
            claims = (
                (event.get("requestContext") or {})
                .get("authorizer", {})
                .get("claims", {})
            )
            accessor_id = claims.get("sub", "unknown")
            accessor_role = (
                (claims.get("cognito:groups") or ["unknown"])[0]
                if isinstance(claims.get("cognito:groups"), list)
                else claims.get("cognito:groups", "unknown")
            )
            org_id = claims.get("custom:orgId") or claims.get("orgId") or "unknown"
            source_ip = (
                (event.get("requestContext") or {})
                .get("identity", {})
                .get("sourceIp", "unknown")
            )
            path_params = event.get("pathParameters") or {}
            resource_id = path_params.get("id") or path_params.get("resource", "")
            rt = resource_type or path_params.get("resource", "")
            op = operation or (event.get("httpMethod") or "").lower()
            allowed = True

            try:
                result = func(event, context)
                status = result.get("statusCode", 200) if isinstance(result, dict) else 200
                allowed = status < 400
                return result
            except Exception:
                allowed = False
                raise
            finally:
                write_audit_event(
                    accessor_id=accessor_id,
                    accessor_role=accessor_role,
                    org_id=org_id,
                    resource_type=rt,
                    resource_id=resource_id,
                    operation=op,
                    source_ip=source_ip,
                    allowed=allowed,
                )
        return wrapper
    return decorator
