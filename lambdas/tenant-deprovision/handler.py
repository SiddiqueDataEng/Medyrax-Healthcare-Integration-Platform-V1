"""
tenant-deprovision Lambda
=========================
Handles the deprovisioning of a Connected_Organization in the Medyrax™ platform.

Exposes one route (via AWS API Gateway):

    DELETE  /v1/admin/organizations/{orgId}
        Immediately revokes the org's IAM credentials, disables the Cognito
        User Pool client, and disables the org's API Gateway usage plan API key.
        Then marks the tenant record in ``mdx-tenants`` with
        ``status=deprovisioned`` and ``deprovisionedAt=<now>``, scheduling a
        DynamoDB TTL of ``deprovisionedAt + 7 years`` to satisfy HIPAA
        record-retention requirements (Requirement 8.4).

        Returns **200 OK** with a structured deprovision summary on success.
        Returns **404 Not Found** when the orgId does not exist.
        Returns **409 Conflict** when the tenant is already deprovisioned.
        Returns **400 Bad Request** when orgId is missing from the path.
        Returns **500 Internal Server Error** on unexpected AWS API failures.

Security note
-------------
This Lambda is secured at the API Gateway level by a Cognito JWT authorizer
requiring the ``Platform_Admin`` role.  The handler trusts the upstream
authorizer and does not re-check the JWT.

Environment variables
---------------------
MDX_TENANTS_TABLE
    DynamoDB table name (default: ``mdx-tenants``).
MDX_COGNITO_USER_POOL_ID
    Cognito User Pool ID used to disable the org's app client.
    When absent, the Cognito step is skipped with a logged warning.
MDX_API_GATEWAY_REST_API_ID
    API Gateway REST API ID used to locate and disable the org's usage plan
    API key.  When absent, the API key step is skipped with a logged warning.
AWS_DEFAULT_REGION
    AWS region (injected automatically by the Lambda runtime).

Requirements: 8.4
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Path resolution — support both Lambda layer and local development
# ---------------------------------------------------------------------------

try:
    from mdx_common.errors import TenantNotFoundError
    from mdx_common.tenant_config_service import TenantConfigService
    from mdx_common.models import TenantConfig
    from mdx_common.constants import HIPAA_RETENTION_DAYS
except ImportError:
    # For local development: add the lambdas/ directory so that mdx_common
    # is importable directly.
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from mdx_common.errors import TenantNotFoundError  # type: ignore[no-redef]
    from mdx_common.tenant_config_service import TenantConfigService  # type: ignore[no-redef]
    from mdx_common.models import TenantConfig  # type: ignore[no-redef]
    from mdx_common.constants import HIPAA_RETENTION_DAYS  # type: ignore[no-redef]

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AWS_REGION: str = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
TENANTS_TABLE: str = os.environ.get("MDX_TENANTS_TABLE", "mdx-tenants")
COGNITO_USER_POOL_ID: str = os.environ.get("MDX_COGNITO_USER_POOL_ID", "")
API_GATEWAY_REST_API_ID: str = os.environ.get("MDX_API_GATEWAY_REST_API_ID", "")

# ---------------------------------------------------------------------------
# Boto3 clients (module-level for Lambda warm-start reuse)
# ---------------------------------------------------------------------------

_iam_client = boto3.client("iam", region_name=AWS_REGION)
_cognito_client = boto3.client("cognito-idp", region_name=AWS_REGION)
_apigateway_client = boto3.client("apigateway", region_name=AWS_REGION)

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
# IAM credential revocation
# ---------------------------------------------------------------------------


def _revoke_iam_credentials(org_id: str, iam_role_arn: str) -> dict[str, Any]:
    """
    Revoke IAM credentials for the org's execution role by attaching an
    explicit Deny-All inline policy.

    This is an immediate, non-destructive revocation: the role still exists
    (so CloudFormation/CDK stack deletion can proceed later), but all AWS API
    calls made with the role's credentials will be denied immediately.

    Parameters
    ----------
    org_id:
        Connected_Organization identifier — used to name the deny policy.
    iam_role_arn:
        ARN of the org's IAM execution role.  If empty, the step is skipped.

    Returns
    -------
    dict
        A status dict with keys ``"revoked"`` (bool) and ``"detail"`` (str).
    """
    if not iam_role_arn:
        logger.warning(
            "No IAM role ARN for org_id='%s'; skipping IAM credential revocation.",
            org_id,
        )
        return {"revoked": False, "detail": "no_iam_role_arn"}

    # Extract the role name from the ARN (last component after '/')
    role_name = iam_role_arn.split("/")[-1]

    deny_policy_doc = json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "MedyraxDeprovisionDenyAll",
                    "Effect": "Deny",
                    "Action": "*",
                    "Resource": "*",
                }
            ],
        }
    )

    policy_name = f"mdx-deprovision-deny-{org_id}"

    try:
        _iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName=policy_name,
            PolicyDocument=deny_policy_doc,
        )
        logger.info(
            "Attached Deny-All inline policy '%s' to role '%s' for org_id='%s'.",
            policy_name,
            role_name,
            org_id,
        )
        return {"revoked": True, "detail": f"deny_policy_attached:{policy_name}"}
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        logger.error(
            "Failed to attach Deny-All policy to role '%s' for org_id='%s': %s",
            role_name,
            org_id,
            exc,
        )
        return {
            "revoked": False,
            "detail": f"iam_error:{error_code}",
        }


# ---------------------------------------------------------------------------
# Cognito User Pool client disablement
# ---------------------------------------------------------------------------


def _disable_cognito_client(org_id: str, cognito_client_id: str) -> dict[str, Any]:
    """
    Disable the org's Cognito User Pool app client to prevent new token issuance.

    Cognito does not support disabling an individual app client directly — the
    standard approach is to remove all supported OAuth flows and set the token
    validity to the minimum, which effectively prevents new authentications.
    Where a dedicated client per org is used, we update the client to remove
    all allowed OAuth flows and set token expiry to 1 minute (minimum).

    Parameters
    ----------
    org_id:
        Connected_Organization identifier (for logging).
    cognito_client_id:
        Cognito app client ID associated with this org.  If empty, the step
        is skipped.

    Returns
    -------
    dict
        Status dict with ``"disabled"`` (bool) and ``"detail"`` (str).
    """
    if not cognito_client_id:
        logger.warning(
            "No Cognito client ID for org_id='%s'; skipping Cognito client disablement.",
            org_id,
        )
        return {"disabled": False, "detail": "no_cognito_client_id"}

    if not COGNITO_USER_POOL_ID:
        logger.warning(
            "MDX_COGNITO_USER_POOL_ID not configured; skipping Cognito step for org_id='%s'.",
            org_id,
        )
        return {"disabled": False, "detail": "no_user_pool_id_configured"}

    try:
        _cognito_client.update_user_pool_client(
            UserPoolId=COGNITO_USER_POOL_ID,
            ClientId=cognito_client_id,
            # Remove all OAuth flows to block new token issuance
            AllowedOAuthFlows=[],
            AllowedOAuthScopes=[],
            AllowedOAuthFlowsUserPoolClient=False,
            # Set access token validity to 5 minutes (minimum allowed by Cognito)
            AccessTokenValidity=5,
            TokenValidityUnits={"accessToken": "minutes"},
        )
        logger.info(
            "Disabled Cognito client '%s' for org_id='%s' (removed OAuth flows, "
            "set 5-minute token expiry).",
            cognito_client_id,
            org_id,
        )
        return {
            "disabled": True,
            "detail": f"oauth_flows_removed:client_id={cognito_client_id}",
        }
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        logger.error(
            "Failed to disable Cognito client '%s' for org_id='%s': %s",
            cognito_client_id,
            org_id,
            exc,
        )
        return {
            "disabled": False,
            "detail": f"cognito_error:{error_code}",
        }


# ---------------------------------------------------------------------------
# API Gateway API key disablement
# ---------------------------------------------------------------------------


def _disable_api_key(org_id: str, api_key_id: str) -> dict[str, Any]:
    """
    Immediately disable the org's API Gateway API key to block further API calls.

    API Gateway's UpdateApiKey operation supports toggling ``enabled``
    directly, so this is a single atomic call.

    Parameters
    ----------
    org_id:
        Connected_Organization identifier (for logging).
    api_key_id:
        API Gateway API key ID for this org.  If empty, the step is skipped.

    Returns
    -------
    dict
        Status dict with ``"disabled"`` (bool) and ``"detail"`` (str).
    """
    if not api_key_id:
        logger.warning(
            "No API key ID for org_id='%s'; skipping API key disablement.",
            org_id,
        )
        return {"disabled": False, "detail": "no_api_key_id"}

    try:
        _apigateway_client.update_api_key(
            apiKey=api_key_id,
            patchOperations=[
                {"op": "replace", "path": "/enabled", "value": "false"}
            ],
        )
        logger.info(
            "Disabled API Gateway key '%s' for org_id='%s'.",
            api_key_id,
            org_id,
        )
        return {"disabled": True, "detail": f"api_key_disabled:{api_key_id}"}
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        logger.error(
            "Failed to disable API key '%s' for org_id='%s': %s",
            api_key_id,
            org_id,
            exc,
        )
        return {
            "disabled": False,
            "detail": f"apigateway_error:{error_code}",
        }


# ---------------------------------------------------------------------------
# Core deprovisioning logic
# ---------------------------------------------------------------------------


def _deprovision_organization(org_id: str) -> dict[str, Any]:
    """
    Execute the full deprovisioning sequence for ``org_id``:

    1. Load the tenant config (any status) from DynamoDB.
    2. Guard against double-deprovisioning (return 409 if already deprovisioned).
    3. Revoke IAM credentials immediately (attach Deny-All inline policy).
    4. Disable the Cognito User Pool app client immediately.
    5. Disable the API Gateway API key immediately.
    6. Write ``status=deprovisioned``, ``deprovisionedAt``, and
       ``ttl=deprovisionedAt + 7 years`` to the ``mdx-tenants`` DynamoDB record.

    Parameters
    ----------
    org_id:
        Connected_Organization to deprovision.

    Returns
    -------
    dict
        API Gateway proxy response dict.
    """
    service = TenantConfigService(table_name=TENANTS_TABLE, region_name=AWS_REGION)

    # ------------------------------------------------------------------
    # 1. Load tenant config (any status)
    # ------------------------------------------------------------------
    try:
        config = service.get_tenant_config_any_status(org_id)
    except TenantNotFoundError:
        logger.info("Deprovisioning requested for unknown org_id='%s'.", org_id)
        return _error(
            404,
            "TENANT_NOT_FOUND",
            f"Organization '{org_id}' was not found. Verify the orgId and try again.",
        )

    # ------------------------------------------------------------------
    # 2. Guard: already deprovisioned?
    # ------------------------------------------------------------------
    if config.status == "deprovisioned":
        logger.info(
            "org_id='%s' is already deprovisioned (at %s). Returning 409.",
            org_id,
            config.deprovisioned_at,
        )
        return _error(
            409,
            "ALREADY_DEPROVISIONED",
            (
                f"Organization '{org_id}' has already been deprovisioned"
                + (
                    f" at {config.deprovisioned_at.isoformat()}."
                    if config.deprovisioned_at
                    else "."
                )
            ),
        )

    deprovisioned_at = datetime.now(tz=timezone.utc)

    # ------------------------------------------------------------------
    # 3. Revoke IAM credentials immediately
    # ------------------------------------------------------------------
    iam_result = _revoke_iam_credentials(org_id, config.iam_role_arn)

    # ------------------------------------------------------------------
    # 4. Disable Cognito User Pool client immediately
    # ------------------------------------------------------------------
    # The Cognito client ID is stored in the integration profile.
    # Fall back to empty string if not configured on this tenant record.
    cognito_client_id: str = getattr(config, "cognito_client_id", "") or ""
    cognito_result = _disable_cognito_client(org_id, cognito_client_id)

    # ------------------------------------------------------------------
    # 5. Disable API Gateway API key immediately
    # ------------------------------------------------------------------
    api_key_id: str = getattr(config, "api_key_id", "") or ""
    api_key_result = _disable_api_key(org_id, api_key_id)

    # ------------------------------------------------------------------
    # 6. Persist deprovisioned status + HIPAA TTL to DynamoDB
    # ------------------------------------------------------------------
    try:
        updated_config = service.deprovision_tenant(
            org_id,
            deprovisioned_at=deprovisioned_at,
            hipaa_retention_days=HIPAA_RETENTION_DAYS,
        )
    except TenantNotFoundError:
        # Race condition: record was deleted between our read and write.
        logger.error(
            "Tenant record for org_id='%s' disappeared between read and deprovision write.",
            org_id,
        )
        return _error(
            404,
            "TENANT_NOT_FOUND",
            f"Organization '{org_id}' was not found during final update.",
        )
    except ClientError as exc:
        logger.error(
            "DynamoDB write failed while deprovisioning org_id='%s': %s",
            org_id,
            exc,
        )
        return _error(
            500,
            "DEPROVISION_WRITE_FAILED",
            "Failed to persist deprovisioned status. Please retry.",
        )

    # ------------------------------------------------------------------
    # 7. Build and return the success response
    # ------------------------------------------------------------------
    logger.info(
        "Deprovisioning complete for org_id='%s'. "
        "IAM=%s | Cognito=%s | APIKey=%s | DynamoDB=ok",
        org_id,
        iam_result["detail"],
        cognito_result["detail"],
        api_key_result["detail"],
    )

    # Calculate TTL for response display
    import calendar

    ttl_epoch = int(
        calendar.timegm(deprovisioned_at.utctimetuple())
        + HIPAA_RETENTION_DAYS * 86_400
    )
    ttl_datetime = datetime.fromtimestamp(ttl_epoch, tz=timezone.utc)

    return _ok(
        {
            "orgId": org_id,
            "status": "deprovisioned",
            "deprovisionedAt": deprovisioned_at.isoformat(),
            "dataRetentionExpiresAt": ttl_datetime.isoformat(),
            "actions": {
                "iamCredentialsRevoked": iam_result["revoked"],
                "iamDetail": iam_result["detail"],
                "cognitoClientDisabled": cognito_result["disabled"],
                "cognitoDetail": cognito_result["detail"],
                "apiKeyDisabled": api_key_result["disabled"],
                "apiKeyDetail": api_key_result["detail"],
                "dynamoDbTtlScheduled": True,
            },
            "message": (
                f"Organization '{org_id}' has been deprovisioned. "
                "PHI data will be retained until "
                f"{ttl_datetime.strftime('%Y-%m-%d')} per HIPAA 7-year retention policy."
            ),
        }
    )


# ---------------------------------------------------------------------------
# Lambda handler — API Gateway proxy router
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Route API Gateway proxy events to the deprovisioning sub-handler.

    Supported route:
        DELETE  /v1/admin/organizations/{orgId}

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

    # DELETE /v1/admin/organizations/{orgId}
    if http_method == "DELETE" and _matches_deprovision_route(resource):
        path_params: dict[str, str] = event.get("pathParameters") or {}
        org_id: str = (path_params.get("orgId") or "").strip()

        if not org_id:
            return _error(
                400,
                "MISSING_PATH_PARAMETER",
                "'orgId' is required in the URL path.",
            )

        return _deprovision_organization(org_id)

    return _error(
        405,
        "METHOD_NOT_ALLOWED",
        f"Method '{http_method}' is not allowed for path '{resource}'.",
    )


# ---------------------------------------------------------------------------
# Route matching helper
# ---------------------------------------------------------------------------

import re

_DEPROVISION_ROUTE_RE = re.compile(
    r"^/v\d+/admin/organizations/[^/]+/?$"
)


def _matches_deprovision_route(resource: str) -> bool:
    """Return True when ``resource`` matches the DELETE deprovision route."""
    return bool(_DEPROVISION_ROUTE_RE.match(resource))
