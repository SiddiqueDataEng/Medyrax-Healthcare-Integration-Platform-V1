"""
tenant-provision-api Lambda
============================
REST API handler for the Medyrax™ tenant provisioning endpoints.

Exposes two routes (via AWS API Gateway):

    POST  /v1/admin/organizations
        Validates the request body, then starts a new execution of the
        ``mdx-org-provision-sfn`` Step Function.
        Returns **202 Accepted** with the Step Functions execution ARN and
        the orgId so the caller can poll status.

    GET   /v1/admin/organizations/{orgId}/status
        Queries Step Functions for the most recent execution targeting
        ``orgId`` and returns the current provisioning status.
        Returns **200 OK** with a structured status object, or **404** when
        no execution is found for the given orgId.

Both endpoints are secured at the API Gateway level via Cognito JWT
(Platform_Admin role required — enforced by the Lambda Authorizer upstream).
This Lambda does not re-check auth; it trusts the authorizer's claims.

Environment variables
---------------------
MDX_SFN_ARN
    ARN of the ``mdx-org-provision-sfn`` Step Function state machine.
    Required for the POST handler.
AWS_DEFAULT_REGION
    AWS region (injected automatically by the Lambda runtime).

Requirements: 8.1
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

import boto3
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Path resolution — support both Lambda layer deployment and local development
# ---------------------------------------------------------------------------

try:
    from mdx_common.errors import TenantNotFoundError
except ImportError:
    # Fallback for local development: add the lambdas/ directory so that
    # `mdx_common` is importable as a package (lambdas/mdx_common/__init__.py).
    sys.path.insert(
        0,
        os.path.join(os.path.dirname(__file__), ".."),
    )
    from mdx_common.errors import TenantNotFoundError  # type: ignore[no-redef]

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AWS_REGION: str = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
SFN_ARN: str = os.environ.get("MDX_SFN_ARN", "")

# ---------------------------------------------------------------------------
# Boto3 clients (module-level for Lambda warm-start reuse)
# ---------------------------------------------------------------------------

_sfn_client = boto3.client("stepfunctions", region_name=AWS_REGION)

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _ok(body: dict[str, Any], status_code: int = 200) -> dict[str, Any]:
    """Return a successful API Gateway proxy response."""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _error(status_code: int, error_code: str, message: str) -> dict[str, Any]:
    """Return an error API Gateway proxy response."""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "error": error_code,
                "message": message,
            }
        ),
    }


# ---------------------------------------------------------------------------
# Request body parsing
# ---------------------------------------------------------------------------


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    """
    Extract and JSON-parse the request body from an API Gateway proxy event.

    Returns an empty dict if the body is absent or null (for GET requests).
    Raises ``ValueError`` when the body is present but not valid JSON.
    """
    raw = event.get("body") or "{}"
    if isinstance(raw, dict):
        # API GW may have already parsed it (e.g. in test harnesses)
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Request body is not valid JSON: {exc}") from exc


# ---------------------------------------------------------------------------
# POST /v1/admin/organizations — start provisioning
# ---------------------------------------------------------------------------


def _start_provisioning(event: dict[str, Any]) -> dict[str, Any]:
    """
    Handle POST /v1/admin/organizations.

    1. Parse and lightly validate the request body (full schema validation is
       performed inside the Step Function's first state).
    2. Start a Step Functions execution with the request payload.
    3. Return HTTP 202 Accepted with the execution ARN.

    The Step Function's ``ValidateProvisioningRequest`` state performs deep
    schema validation, so this handler only checks that the required top-level
    ``orgId`` field is present — enough to name the execution deterministically
    and reject obviously malformed requests before touching AWS APIs.
    """
    if not SFN_ARN:
        logger.error("MDX_SFN_ARN environment variable is not configured.")
        return _error(500, "CONFIGURATION_ERROR", "Step Function ARN is not configured.")

    try:
        body = _parse_body(event)
    except ValueError as exc:
        return _error(400, "INVALID_REQUEST_BODY", str(exc))

    org_id: str = body.get("orgId", "").strip()
    if not org_id:
        return _error(
            400,
            "MISSING_REQUIRED_FIELD",
            "'orgId' is required in the request body.",
        )

    # Use a deterministic execution name so re-submitting the same orgId
    # returns an idempotency error from SFN rather than creating a duplicate
    # execution silently.
    execution_name = f"provision-{org_id}"

    logger.info(
        "Starting provisioning Step Function for orgId='%s' (execution='%s')",
        org_id,
        execution_name,
    )

    try:
        response = _sfn_client.start_execution(
            stateMachineArn=SFN_ARN,
            name=execution_name,
            input=json.dumps(body),
        )
    except _sfn_client.exceptions.ExecutionAlreadyExists:
        # Idempotent: a provisioning execution for this orgId already exists.
        # Return 409 Conflict with a descriptive message so the caller can
        # decide whether to poll /status or take a different action.
        logger.warning(
            "Provisioning execution already exists for orgId='%s'", org_id
        )
        return _error(
            409,
            "EXECUTION_ALREADY_EXISTS",
            f"A provisioning execution for orgId='{org_id}' is already running or has "
            "completed. Use GET /v1/admin/organizations/{orgId}/status to check its state.",
        )
    except _sfn_client.exceptions.StateMachineDoesNotExist:
        logger.error("Step Function ARN not found: %s", SFN_ARN)
        return _error(500, "CONFIGURATION_ERROR", "Provisioning state machine not found.")
    except ClientError as exc:
        logger.error("Failed to start Step Function execution: %s", exc)
        return _error(
            500,
            "SFN_START_FAILED",
            "Failed to start provisioning workflow. Please try again.",
        )

    execution_arn: str = response["executionArn"]
    logger.info(
        "Provisioning execution started for orgId='%s': %s", org_id, execution_arn
    )

    return _ok(
        {
            "orgId": org_id,
            "executionArn": execution_arn,
            "status": "PROVISIONING_STARTED",
            "message": (
                f"Provisioning workflow started for org '{org_id}'. "
                "Poll GET /v1/admin/organizations/{orgId}/status for progress."
            ),
        },
        status_code=202,
    )


# ---------------------------------------------------------------------------
# GET /v1/admin/organizations/{orgId}/status — query provisioning status
# ---------------------------------------------------------------------------

# Step Functions status values → platform-level status strings
_SFN_STATUS_MAP = {
    "RUNNING": "PROVISIONING_IN_PROGRESS",
    "SUCCEEDED": "PROVISIONING_COMPLETE",
    "FAILED": "PROVISIONING_FAILED",
    "TIMED_OUT": "PROVISIONING_TIMED_OUT",
    "ABORTED": "PROVISIONING_ABORTED",
}


def _get_provisioning_status(event: dict[str, Any]) -> dict[str, Any]:
    """
    Handle GET /v1/admin/organizations/{orgId}/status.

    1. Extract ``orgId`` from the path parameters.
    2. Describe the Step Functions execution named ``provision-{orgId}``.
    3. Return the current status, start time, and (if finished) stop time
       and any error output.

    Returns 404 when no execution exists for the given orgId.
    Returns 400 when orgId is missing from the path.
    """
    path_params: dict[str, str] = event.get("pathParameters") or {}
    org_id: str = (path_params.get("orgId") or "").strip()

    if not org_id:
        return _error(400, "MISSING_PATH_PARAMETER", "'orgId' is required in the path.")

    execution_name = f"provision-{org_id}"

    if not SFN_ARN:
        logger.error("MDX_SFN_ARN environment variable is not configured.")
        return _error(500, "CONFIGURATION_ERROR", "Step Function ARN is not configured.")

    # Derive the execution ARN from the state machine ARN and execution name.
    # SFN ARN format: arn:aws:states:{region}:{account}:stateMachine:{name}
    # Execution ARN: arn:aws:states:{region}:{account}:execution:{name}:{executionName}
    sfn_arn_parts = SFN_ARN.split(":")
    if len(sfn_arn_parts) < 7:
        logger.error("MDX_SFN_ARN has unexpected format: %s", SFN_ARN)
        return _error(500, "CONFIGURATION_ERROR", "Step Function ARN format is invalid.")

    # Replace "stateMachine" segment with "execution" and append execution name
    sfn_arn_parts[5] = "execution"
    state_machine_name = sfn_arn_parts[6]
    execution_arn = ":".join(sfn_arn_parts) + f":{execution_name}"
    # Correct ARN: arn:aws:states:{region}:{acct}:execution:{sm-name}:{exec-name}
    execution_arn = (
        f"arn:aws:states:{sfn_arn_parts[3]}:{sfn_arn_parts[4]}:"
        f"execution:{state_machine_name}:{execution_name}"
    )

    logger.info(
        "Querying provisioning status for orgId='%s' (execution='%s')",
        org_id,
        execution_arn,
    )

    try:
        desc = _sfn_client.describe_execution(executionArn=execution_arn)
    except _sfn_client.exceptions.ExecutionDoesNotExist:
        logger.info("No provisioning execution found for orgId='%s'", org_id)
        return _error(
            404,
            "EXECUTION_NOT_FOUND",
            f"No provisioning execution found for orgId='{org_id}'. "
            "Start provisioning via POST /v1/admin/organizations.",
        )
    except ClientError as exc:
        logger.error(
            "Failed to describe Step Function execution for orgId='%s': %s",
            org_id,
            exc,
        )
        return _error(
            500,
            "SFN_DESCRIBE_FAILED",
            "Failed to retrieve provisioning status. Please try again.",
        )

    sfn_status: str = desc.get("status", "UNKNOWN")
    platform_status: str = _SFN_STATUS_MAP.get(sfn_status, sfn_status)

    response_body: dict[str, Any] = {
        "orgId": org_id,
        "executionArn": desc.get("executionArn", execution_arn),
        "status": platform_status,
        "sfnStatus": sfn_status,
        "startedAt": (
            desc["startDate"].isoformat()
            if desc.get("startDate")
            else None
        ),
    }

    # Include stop time and error details for terminal states
    if sfn_status in ("SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"):
        response_body["completedAt"] = (
            desc["stopDate"].isoformat() if desc.get("stopDate") else None
        )

    if sfn_status == "FAILED":
        response_body["error"] = desc.get("error")
        response_body["cause"] = desc.get("cause")

    if sfn_status == "SUCCEEDED" and desc.get("output"):
        try:
            response_body["output"] = json.loads(desc["output"])
        except (json.JSONDecodeError, TypeError):
            response_body["output"] = desc.get("output")

    return _ok(response_body)


# ---------------------------------------------------------------------------
# Lambda handler — API Gateway proxy router
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Route API Gateway proxy events to the appropriate sub-handler.

    Supported routes:
        POST  /v1/admin/organizations
        GET   /v1/admin/organizations/{orgId}/status

    All other method/path combinations return HTTP 405 Method Not Allowed.

    Parameters
    ----------
    event:
        AWS API Gateway proxy integration event dict.
    context:
        AWS Lambda context object (unused).

    Returns
    -------
    dict
        API Gateway proxy response dict with ``statusCode``, ``headers``,
        and ``body`` keys.
    """
    http_method: str = (event.get("httpMethod") or "").upper()
    resource: str = event.get("resource") or event.get("path") or ""

    logger.info("Received %s %s", http_method, resource)

    # POST /v1/admin/organizations
    if http_method == "POST" and _matches_create_route(resource):
        return _start_provisioning(event)

    # GET /v1/admin/organizations/{orgId}/status
    if http_method == "GET" and _matches_status_route(resource):
        return _get_provisioning_status(event)

    return _error(
        405,
        "METHOD_NOT_ALLOWED",
        f"Method '{http_method}' is not allowed for path '{resource}'.",
    )


# ---------------------------------------------------------------------------
# Route matching helpers
# ---------------------------------------------------------------------------

import re

_CREATE_ROUTE_RE = re.compile(
    r"^/v\d+/admin/organizations/?$"
)
_STATUS_ROUTE_RE = re.compile(
    r"^/v\d+/admin/organizations/[^/]+/status/?$"
)


def _matches_create_route(resource: str) -> bool:
    """Return True when ``resource`` matches the POST create route."""
    return bool(_CREATE_ROUTE_RE.match(resource))


def _matches_status_route(resource: str) -> bool:
    """Return True when ``resource`` matches the GET status route."""
    return bool(_STATUS_ROUTE_RE.match(resource))
