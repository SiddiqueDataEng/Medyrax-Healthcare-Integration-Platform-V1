"""
Unit tests for tenant-deprovision Lambda handler.

Tests the DELETE /v1/admin/organizations/{orgId} endpoint, covering:
- Successful deprovisioning (IAM, Cognito, API key, DynamoDB TTL)
- 404 when org does not exist
- 409 when org is already deprovisioned
- 400 when orgId is missing from path
- 405 for unsupported methods/paths
- Partial failure resilience (each access-revocation step is best-effort)
- DynamoDB TTL is set to deprovisionedAt + 7 years (HIPAA retention)

Requirements: 8.4
"""

from __future__ import annotations

import json
import os
import sys
import calendar
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Path setup — make handler and mdx_common importable
# ---------------------------------------------------------------------------

_HANDLER_DIR = os.path.join(os.path.dirname(__file__), "..")
_LAMBDAS_DIR = os.path.join(os.path.dirname(__file__), "..", "..")

for _p in (_HANDLER_DIR, _LAMBDAS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Set env vars before importing the handler
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("MDX_TENANTS_TABLE", "mdx-tenants")
os.environ.setdefault("MDX_COGNITO_USER_POOL_ID", "us-east-1_TestPoolId")
os.environ.setdefault("MDX_API_GATEWAY_REST_API_ID", "test-api-id")

import handler as deprovision_handler
from mdx_common.models import TenantConfig
from mdx_common.errors import TenantNotFoundError

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_ORG_ID = "acme-hospital"
_IAM_ROLE_ARN = "arn:aws:iam::123456789012:role/mdx-acme-hospital-role"
_ROLE_NAME = "mdx-acme-hospital-role"
_API_KEY_ID = "abc123apikey"
_COGNITO_CLIENT_ID = "cog1234clientid"


def _make_tenant_config(
    org_id: str = _ORG_ID,
    status: str = "active",
    iam_role_arn: str = _IAM_ROLE_ARN,
    deprovisioned_at: datetime | None = None,
) -> TenantConfig:
    """Build a TenantConfig suitable for testing."""
    return TenantConfig(
        org_id=org_id,
        org_name="ACME Hospital",
        status=status,
        kms_key_arn="arn:aws:kms:us-east-1:123456789012:key/fake-key",
        iam_role_arn=iam_role_arn,
        health_lake_data_store_id="ds-fakeid",
        deprovisioned_at=deprovisioned_at,
    )


def _delete_event(org_id: str = _ORG_ID) -> dict:
    """Build a minimal API Gateway proxy event for DELETE /v1/admin/organizations/{orgId}."""
    return {
        "httpMethod": "DELETE",
        "resource": f"/v1/admin/organizations/{org_id}",
        "path": f"/v1/admin/organizations/{org_id}",
        "pathParameters": {"orgId": org_id},
        "body": None,
    }


# ---------------------------------------------------------------------------
# Tests: successful deprovisioning
# ---------------------------------------------------------------------------


class TestSuccessfulDeprovisioning:
    """Tests for the happy path — tenant is active and gets deprovisioned."""

    def test_returns_200_on_success(self):
        """DELETE returns 200 OK when org exists and is active."""
        mock_config = _make_tenant_config()

        with (
            patch.object(
                deprovision_handler.TenantConfigService,
                "get_tenant_config_any_status",
                return_value=mock_config,
            ),
            patch.object(
                deprovision_handler.TenantConfigService,
                "deprovision_tenant",
                return_value=_make_tenant_config(status="deprovisioned"),
            ),
            patch.object(deprovision_handler._iam_client, "put_role_policy"),
        ):
            response = deprovision_handler.handler(_delete_event(), None)

        assert response["statusCode"] == 200

    def test_response_body_contains_required_fields(self):
        """200 response body has orgId, status, deprovisionedAt, dataRetentionExpiresAt, actions, message."""
        mock_config = _make_tenant_config()

        with (
            patch.object(
                deprovision_handler.TenantConfigService,
                "get_tenant_config_any_status",
                return_value=mock_config,
            ),
            patch.object(
                deprovision_handler.TenantConfigService,
                "deprovision_tenant",
                return_value=_make_tenant_config(status="deprovisioned"),
            ),
            patch.object(deprovision_handler._iam_client, "put_role_policy"),
        ):
            response = deprovision_handler.handler(_delete_event(), None)

        body = json.loads(response["body"])
        assert body["orgId"] == _ORG_ID
        assert body["status"] == "deprovisioned"
        assert "deprovisionedAt" in body
        assert "dataRetentionExpiresAt" in body
        assert "actions" in body
        assert "message" in body

    def test_iam_deny_policy_is_attached(self):
        """Deprovisioning attaches a Deny-All inline policy to the org's IAM role."""
        mock_config = _make_tenant_config()
        mock_put_policy = MagicMock()

        with (
            patch.object(
                deprovision_handler.TenantConfigService,
                "get_tenant_config_any_status",
                return_value=mock_config,
            ),
            patch.object(
                deprovision_handler.TenantConfigService,
                "deprovision_tenant",
                return_value=_make_tenant_config(status="deprovisioned"),
            ),
            patch.object(
                deprovision_handler._iam_client, "put_role_policy", mock_put_policy
            ),
        ):
            deprovision_handler.handler(_delete_event(), None)

        mock_put_policy.assert_called_once()
        call_kwargs = mock_put_policy.call_args[1]
        assert call_kwargs["RoleName"] == _ROLE_NAME
        assert "Deny" in call_kwargs["PolicyDocument"]
        assert call_kwargs["PolicyName"].startswith("mdx-deprovision-deny-")

    def test_cognito_client_is_disabled(self):
        """Deprovisioning disables the Cognito app client."""
        mock_config = _make_tenant_config()
        # Inject cognito_client_id into the config object
        mock_config.cognito_client_id = _COGNITO_CLIENT_ID  # type: ignore[attr-defined]
        mock_update_client = MagicMock()

        with (
            patch.object(
                deprovision_handler.TenantConfigService,
                "get_tenant_config_any_status",
                return_value=mock_config,
            ),
            patch.object(
                deprovision_handler.TenantConfigService,
                "deprovision_tenant",
                return_value=_make_tenant_config(status="deprovisioned"),
            ),
            patch.object(deprovision_handler._iam_client, "put_role_policy"),
            patch.object(
                deprovision_handler._cognito_client,
                "update_user_pool_client",
                mock_update_client,
            ),
        ):
            deprovision_handler.handler(_delete_event(), None)

        mock_update_client.assert_called_once()
        call_kwargs = mock_update_client.call_args[1]
        assert call_kwargs["ClientId"] == _COGNITO_CLIENT_ID
        assert call_kwargs["AllowedOAuthFlows"] == []
        assert call_kwargs["AllowedOAuthFlowsUserPoolClient"] is False

    def test_api_key_is_disabled(self):
        """Deprovisioning disables the org's API Gateway API key."""
        mock_config = _make_tenant_config()
        mock_config.api_key_id = _API_KEY_ID  # type: ignore[attr-defined]
        mock_update_key = MagicMock()

        with (
            patch.object(
                deprovision_handler.TenantConfigService,
                "get_tenant_config_any_status",
                return_value=mock_config,
            ),
            patch.object(
                deprovision_handler.TenantConfigService,
                "deprovision_tenant",
                return_value=_make_tenant_config(status="deprovisioned"),
            ),
            patch.object(deprovision_handler._iam_client, "put_role_policy"),
            patch.object(
                deprovision_handler._apigateway_client,
                "update_api_key",
                mock_update_key,
            ),
        ):
            deprovision_handler.handler(_delete_event(), None)

        mock_update_key.assert_called_once()
        call_kwargs = mock_update_key.call_args[1]
        assert call_kwargs["apiKey"] == _API_KEY_ID
        # The patch operation should set enabled=false
        patch_ops = call_kwargs["patchOperations"]
        assert any(
            op.get("path") == "/enabled" and op.get("value") == "false"
            for op in patch_ops
        )

    def test_deprovision_tenant_service_is_called(self):
        """The TenantConfigService.deprovision_tenant method is invoked with correct args."""
        mock_config = _make_tenant_config()
        mock_deprovision = MagicMock(
            return_value=_make_tenant_config(status="deprovisioned")
        )

        before = datetime.now(tz=timezone.utc)

        with (
            patch.object(
                deprovision_handler.TenantConfigService,
                "get_tenant_config_any_status",
                return_value=mock_config,
            ),
            patch.object(
                deprovision_handler.TenantConfigService,
                "deprovision_tenant",
                mock_deprovision,
            ),
            patch.object(deprovision_handler._iam_client, "put_role_policy"),
        ):
            deprovision_handler.handler(_delete_event(), None)

        after = datetime.now(tz=timezone.utc)

        mock_deprovision.assert_called_once()
        call_args, call_kwargs = mock_deprovision.call_args
        assert call_args[0] == _ORG_ID
        assert call_kwargs["hipaa_retention_days"] == deprovision_handler.HIPAA_RETENTION_DAYS
        # deprovisionedAt should be a recent UTC timestamp
        dep_at: datetime = call_kwargs["deprovisioned_at"]
        assert before <= dep_at <= after

    def test_data_retention_expiry_is_7_years_from_deprovisioned_at(self):
        """dataRetentionExpiresAt is deprovisionedAt + 7 years."""
        mock_config = _make_tenant_config()
        mock_deprovisioned_config = _make_tenant_config(status="deprovisioned")

        with (
            patch.object(
                deprovision_handler.TenantConfigService,
                "get_tenant_config_any_status",
                return_value=mock_config,
            ),
            patch.object(
                deprovision_handler.TenantConfigService,
                "deprovision_tenant",
                return_value=mock_deprovisioned_config,
            ),
            patch.object(deprovision_handler._iam_client, "put_role_policy"),
        ):
            response = deprovision_handler.handler(_delete_event(), None)

        body = json.loads(response["body"])
        deprovisioned_at = datetime.fromisoformat(body["deprovisionedAt"])
        retention_expires = datetime.fromisoformat(body["dataRetentionExpiresAt"])

        # Should be approximately 7 years (2555 days) after deprovisionedAt
        delta_days = (retention_expires - deprovisioned_at).days
        assert 2554 <= delta_days <= 2556  # small tolerance for leap years

    def test_response_content_type_is_json(self):
        """Response always includes Content-Type: application/json."""
        mock_config = _make_tenant_config()

        with (
            patch.object(
                deprovision_handler.TenantConfigService,
                "get_tenant_config_any_status",
                return_value=mock_config,
            ),
            patch.object(
                deprovision_handler.TenantConfigService,
                "deprovision_tenant",
                return_value=_make_tenant_config(status="deprovisioned"),
            ),
            patch.object(deprovision_handler._iam_client, "put_role_policy"),
        ):
            response = deprovision_handler.handler(_delete_event(), None)

        assert response["headers"]["Content-Type"] == "application/json"

    def test_iam_revoked_flag_in_response(self):
        """Response actions.iamCredentialsRevoked is True when IAM call succeeds."""
        mock_config = _make_tenant_config()

        with (
            patch.object(
                deprovision_handler.TenantConfigService,
                "get_tenant_config_any_status",
                return_value=mock_config,
            ),
            patch.object(
                deprovision_handler.TenantConfigService,
                "deprovision_tenant",
                return_value=_make_tenant_config(status="deprovisioned"),
            ),
            patch.object(deprovision_handler._iam_client, "put_role_policy"),
        ):
            response = deprovision_handler.handler(_delete_event(), None)

        body = json.loads(response["body"])
        assert body["actions"]["iamCredentialsRevoked"] is True
        assert body["actions"]["dynamoDbTtlScheduled"] is True


# ---------------------------------------------------------------------------
# Tests: error conditions
# ---------------------------------------------------------------------------


class TestErrorConditions:
    """Tests for invalid input and state error paths."""

    def test_returns_404_when_org_not_found(self):
        """DELETE returns 404 when the orgId does not exist in DynamoDB."""
        with patch.object(
            deprovision_handler.TenantConfigService,
            "get_tenant_config_any_status",
            side_effect=TenantNotFoundError(
                message="not found", org_id=_ORG_ID
            ),
        ):
            response = deprovision_handler.handler(_delete_event(), None)

        assert response["statusCode"] == 404
        body = json.loads(response["body"])
        assert body["error"] == "TENANT_NOT_FOUND"
        assert _ORG_ID in body["message"]

    def test_returns_409_when_already_deprovisioned(self):
        """DELETE returns 409 when tenant is already deprovisioned."""
        already_deprovisioned = _make_tenant_config(
            status="deprovisioned",
            deprovisioned_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
        )
        with patch.object(
            deprovision_handler.TenantConfigService,
            "get_tenant_config_any_status",
            return_value=already_deprovisioned,
        ):
            response = deprovision_handler.handler(_delete_event(), None)

        assert response["statusCode"] == 409
        body = json.loads(response["body"])
        assert body["error"] == "ALREADY_DEPROVISIONED"
        assert _ORG_ID in body["message"]

    def test_returns_400_when_org_id_empty_in_path_params(self):
        """DELETE returns 400 when pathParameters contains an empty orgId string."""
        # API GW may route /v1/admin/organizations/{orgId} and provide
        # pathParameters with an empty string when the URL template has a
        # greedy proxy pattern — guard against that.
        event = {
            "httpMethod": "DELETE",
            "resource": "/v1/admin/organizations/{orgId}",
            "path": f"/v1/admin/organizations/ ",   # whitespace-only orgId
            "pathParameters": {"orgId": "   "},    # whitespace — strip → empty
            "body": None,
        }
        response = deprovision_handler.handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "MISSING_PATH_PARAMETER"

    def test_returns_400_when_path_params_missing_org_id_key(self):
        """DELETE returns 400 when pathParameters dict has no orgId key at all."""
        event = {
            "httpMethod": "DELETE",
            "resource": "/v1/admin/organizations/{orgId}",
            "path": "/v1/admin/organizations/placeholder",
            "pathParameters": {},   # orgId key absent
            "body": None,
        }
        response = deprovision_handler.handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "MISSING_PATH_PARAMETER"

    def test_returns_500_on_dynamodb_write_failure(self):
        """DELETE returns 500 when DynamoDB write for deprovision fails."""
        from botocore.exceptions import ClientError

        mock_config = _make_tenant_config()
        ddb_error = ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "throttled"}},
            "PutItem",
        )

        with (
            patch.object(
                deprovision_handler.TenantConfigService,
                "get_tenant_config_any_status",
                return_value=mock_config,
            ),
            patch.object(
                deprovision_handler.TenantConfigService,
                "deprovision_tenant",
                side_effect=ddb_error,
            ),
            patch.object(deprovision_handler._iam_client, "put_role_policy"),
        ):
            response = deprovision_handler.handler(_delete_event(), None)

        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert body["error"] == "DEPROVISION_WRITE_FAILED"


# ---------------------------------------------------------------------------
# Tests: partial failure resilience (best-effort revocation steps)
# ---------------------------------------------------------------------------


class TestPartialFailureResilience:
    """
    Individual access-revocation steps are best-effort: IAM, Cognito, and API key
    failures should not abort the deprovisioning flow; they are reported in the
    response actions dict but the DynamoDB record is still updated.
    """

    def test_iam_failure_does_not_abort_deprovisioning(self):
        """IAM put_role_policy ClientError is tolerated; DynamoDB write still proceeds."""
        from botocore.exceptions import ClientError

        mock_config = _make_tenant_config()
        iam_error = ClientError(
            {"Error": {"Code": "NoSuchEntityException", "Message": "role not found"}},
            "PutRolePolicy",
        )
        mock_deprovision = MagicMock(
            return_value=_make_tenant_config(status="deprovisioned")
        )

        with (
            patch.object(
                deprovision_handler.TenantConfigService,
                "get_tenant_config_any_status",
                return_value=mock_config,
            ),
            patch.object(
                deprovision_handler.TenantConfigService,
                "deprovision_tenant",
                mock_deprovision,
            ),
            patch.object(
                deprovision_handler._iam_client, "put_role_policy", side_effect=iam_error
            ),
        ):
            response = deprovision_handler.handler(_delete_event(), None)

        # Overall request still succeeds
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        # DynamoDB deprovision was still called
        mock_deprovision.assert_called_once()
        # IAM revocation flag is False
        assert body["actions"]["iamCredentialsRevoked"] is False

    def test_cognito_failure_does_not_abort_deprovisioning(self):
        """Cognito update_user_pool_client ClientError is tolerated."""
        from botocore.exceptions import ClientError

        mock_config = _make_tenant_config()
        mock_config.cognito_client_id = _COGNITO_CLIENT_ID  # type: ignore[attr-defined]
        cognito_error = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "client not found"}},
            "UpdateUserPoolClient",
        )
        mock_deprovision = MagicMock(
            return_value=_make_tenant_config(status="deprovisioned")
        )

        with (
            patch.object(
                deprovision_handler.TenantConfigService,
                "get_tenant_config_any_status",
                return_value=mock_config,
            ),
            patch.object(
                deprovision_handler.TenantConfigService,
                "deprovision_tenant",
                mock_deprovision,
            ),
            patch.object(deprovision_handler._iam_client, "put_role_policy"),
            patch.object(
                deprovision_handler._cognito_client,
                "update_user_pool_client",
                side_effect=cognito_error,
            ),
        ):
            response = deprovision_handler.handler(_delete_event(), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["actions"]["cognitoClientDisabled"] is False
        mock_deprovision.assert_called_once()

    def test_api_key_failure_does_not_abort_deprovisioning(self):
        """API Gateway update_api_key ClientError is tolerated."""
        from botocore.exceptions import ClientError

        mock_config = _make_tenant_config()
        mock_config.api_key_id = _API_KEY_ID  # type: ignore[attr-defined]
        apigw_error = ClientError(
            {"Error": {"Code": "NotFoundException", "Message": "key not found"}},
            "UpdateApiKey",
        )
        mock_deprovision = MagicMock(
            return_value=_make_tenant_config(status="deprovisioned")
        )

        with (
            patch.object(
                deprovision_handler.TenantConfigService,
                "get_tenant_config_any_status",
                return_value=mock_config,
            ),
            patch.object(
                deprovision_handler.TenantConfigService,
                "deprovision_tenant",
                mock_deprovision,
            ),
            patch.object(deprovision_handler._iam_client, "put_role_policy"),
            patch.object(
                deprovision_handler._apigateway_client,
                "update_api_key",
                side_effect=apigw_error,
            ),
        ):
            response = deprovision_handler.handler(_delete_event(), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["actions"]["apiKeyDisabled"] is False
        mock_deprovision.assert_called_once()

    def test_skips_iam_when_role_arn_empty(self):
        """No IAM call is made when iam_role_arn is empty on the tenant config."""
        mock_config = _make_tenant_config(iam_role_arn="")
        mock_put_policy = MagicMock()

        with (
            patch.object(
                deprovision_handler.TenantConfigService,
                "get_tenant_config_any_status",
                return_value=mock_config,
            ),
            patch.object(
                deprovision_handler.TenantConfigService,
                "deprovision_tenant",
                return_value=_make_tenant_config(status="deprovisioned"),
            ),
            patch.object(
                deprovision_handler._iam_client, "put_role_policy", mock_put_policy
            ),
        ):
            response = deprovision_handler.handler(_delete_event(), None)

        mock_put_policy.assert_not_called()
        body = json.loads(response["body"])
        assert body["actions"]["iamCredentialsRevoked"] is False

    def test_skips_cognito_when_client_id_empty(self):
        """No Cognito call is made when cognito_client_id is absent."""
        mock_config = _make_tenant_config()
        # Do NOT set cognito_client_id
        mock_update_client = MagicMock()

        with (
            patch.object(
                deprovision_handler.TenantConfigService,
                "get_tenant_config_any_status",
                return_value=mock_config,
            ),
            patch.object(
                deprovision_handler.TenantConfigService,
                "deprovision_tenant",
                return_value=_make_tenant_config(status="deprovisioned"),
            ),
            patch.object(deprovision_handler._iam_client, "put_role_policy"),
            patch.object(
                deprovision_handler._cognito_client,
                "update_user_pool_client",
                mock_update_client,
            ),
        ):
            response = deprovision_handler.handler(_delete_event(), None)

        mock_update_client.assert_not_called()
        body = json.loads(response["body"])
        assert body["actions"]["cognitoClientDisabled"] is False

    def test_skips_api_key_when_key_id_empty(self):
        """No API Gateway call is made when api_key_id is absent."""
        mock_config = _make_tenant_config()
        mock_update_key = MagicMock()

        with (
            patch.object(
                deprovision_handler.TenantConfigService,
                "get_tenant_config_any_status",
                return_value=mock_config,
            ),
            patch.object(
                deprovision_handler.TenantConfigService,
                "deprovision_tenant",
                return_value=_make_tenant_config(status="deprovisioned"),
            ),
            patch.object(deprovision_handler._iam_client, "put_role_policy"),
            patch.object(
                deprovision_handler._apigateway_client,
                "update_api_key",
                mock_update_key,
            ),
        ):
            deprovision_handler.handler(_delete_event(), None)

        mock_update_key.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: route dispatch
# ---------------------------------------------------------------------------


class TestRouteDispatch:
    """Tests for the HTTP method/path router."""

    def test_post_returns_405(self):
        """POST to the deprovision path returns 405."""
        event = {
            "httpMethod": "POST",
            "resource": f"/v1/admin/organizations/{_ORG_ID}",
            "path": f"/v1/admin/organizations/{_ORG_ID}",
            "pathParameters": {"orgId": _ORG_ID},
            "body": None,
        }
        response = deprovision_handler.handler(event, None)
        assert response["statusCode"] == 405
        body = json.loads(response["body"])
        assert body["error"] == "METHOD_NOT_ALLOWED"

    def test_get_returns_405(self):
        """GET to the deprovision path returns 405."""
        event = {
            "httpMethod": "GET",
            "resource": f"/v1/admin/organizations/{_ORG_ID}",
            "path": f"/v1/admin/organizations/{_ORG_ID}",
            "pathParameters": {"orgId": _ORG_ID},
            "body": None,
        }
        response = deprovision_handler.handler(event, None)
        assert response["statusCode"] == 405

    def test_unknown_path_returns_405(self):
        """Unknown path returns 405."""
        event = {
            "httpMethod": "DELETE",
            "resource": "/v1/admin/unknown-resource",
            "path": "/v1/admin/unknown-resource",
            "pathParameters": None,
            "body": None,
        }
        response = deprovision_handler.handler(event, None)
        assert response["statusCode"] == 405

    @pytest.mark.parametrize(
        "resource",
        [
            "/v1/admin/organizations/acme-hospital",
            "/v2/admin/organizations/my-org-123",
            "/v1/admin/organizations/test-org/",
        ],
    )
    def test_deprovision_route_matching(self, resource: str):
        """Route matcher accepts versioned org paths."""
        assert deprovision_handler._matches_deprovision_route(resource) is True

    @pytest.mark.parametrize(
        "resource",
        [
            "/admin/organizations/acme-hospital",      # missing version prefix
            "/v1/organizations/acme-hospital",          # missing 'admin'
            "/v1/admin/organizations",                  # missing orgId segment
            "/v1/admin/organizations/org/status",       # extra segment
        ],
    )
    def test_non_matching_routes_rejected(self, resource: str):
        """Route matcher correctly rejects non-matching paths."""
        assert deprovision_handler._matches_deprovision_route(resource) is False


# ---------------------------------------------------------------------------
# Tests: IAM revocation helper (unit tests for _revoke_iam_credentials)
# ---------------------------------------------------------------------------


class TestRevokeIamCredentials:
    """Unit tests for the _revoke_iam_credentials helper."""

    def test_extracts_role_name_from_arn(self):
        """Helper correctly extracts role name from an IAM role ARN."""
        mock_put = MagicMock()
        with patch.object(deprovision_handler._iam_client, "put_role_policy", mock_put):
            result = deprovision_handler._revoke_iam_credentials(
                "test-org", "arn:aws:iam::123456789012:role/my-custom-role-name"
            )

        call_kwargs = mock_put.call_args[1]
        assert call_kwargs["RoleName"] == "my-custom-role-name"
        assert result["revoked"] is True

    def test_policy_document_contains_deny_all(self):
        """Attached policy document denies all actions on all resources."""
        mock_put = MagicMock()
        with patch.object(deprovision_handler._iam_client, "put_role_policy", mock_put):
            deprovision_handler._revoke_iam_credentials("test-org", _IAM_ROLE_ARN)

        policy_doc = json.loads(mock_put.call_args[1]["PolicyDocument"])
        statement = policy_doc["Statement"][0]
        assert statement["Effect"] == "Deny"
        assert statement["Action"] == "*"
        assert statement["Resource"] == "*"

    def test_returns_not_revoked_when_role_arn_empty(self):
        """Returns revoked=False immediately when iam_role_arn is empty."""
        result = deprovision_handler._revoke_iam_credentials("test-org", "")
        assert result["revoked"] is False
        assert result["detail"] == "no_iam_role_arn"

    def test_returns_not_revoked_on_client_error(self):
        """Returns revoked=False when IAM API call raises ClientError."""
        from botocore.exceptions import ClientError

        exc = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "access denied"}},
            "PutRolePolicy",
        )
        with patch.object(deprovision_handler._iam_client, "put_role_policy", side_effect=exc):
            result = deprovision_handler._revoke_iam_credentials("test-org", _IAM_ROLE_ARN)

        assert result["revoked"] is False
        assert "iam_error" in result["detail"]


# ---------------------------------------------------------------------------
# Tests: Cognito helper (unit tests for _disable_cognito_client)
# ---------------------------------------------------------------------------


class TestDisableCognitoClient:
    """Unit tests for the _disable_cognito_client helper."""

    def test_returns_not_disabled_when_client_id_empty(self):
        """Returns disabled=False immediately when cognito_client_id is empty."""
        result = deprovision_handler._disable_cognito_client("test-org", "")
        assert result["disabled"] is False
        assert result["detail"] == "no_cognito_client_id"

    def test_returns_not_disabled_when_user_pool_not_configured(self):
        """Returns disabled=False when MDX_COGNITO_USER_POOL_ID env var is absent."""
        original = deprovision_handler.COGNITO_USER_POOL_ID
        deprovision_handler.COGNITO_USER_POOL_ID = ""
        try:
            result = deprovision_handler._disable_cognito_client(
                "test-org", "some-client-id"
            )
        finally:
            deprovision_handler.COGNITO_USER_POOL_ID = original

        assert result["disabled"] is False
        assert result["detail"] == "no_user_pool_id_configured"

    def test_disables_oauth_flows_on_success(self):
        """Sets AllowedOAuthFlows=[] and AllowedOAuthFlowsUserPoolClient=False."""
        mock_update = MagicMock()
        with patch.object(
            deprovision_handler._cognito_client,
            "update_user_pool_client",
            mock_update,
        ):
            result = deprovision_handler._disable_cognito_client(
                "test-org", _COGNITO_CLIENT_ID
            )

        assert result["disabled"] is True
        call_kwargs = mock_update.call_args[1]
        assert call_kwargs["AllowedOAuthFlows"] == []
        assert call_kwargs["AllowedOAuthFlowsUserPoolClient"] is False

    def test_returns_not_disabled_on_client_error(self):
        """Returns disabled=False when Cognito API call raises ClientError."""
        from botocore.exceptions import ClientError

        exc = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "not found"}},
            "UpdateUserPoolClient",
        )
        with patch.object(
            deprovision_handler._cognito_client,
            "update_user_pool_client",
            side_effect=exc,
        ):
            result = deprovision_handler._disable_cognito_client(
                "test-org", _COGNITO_CLIENT_ID
            )

        assert result["disabled"] is False
        assert "cognito_error" in result["detail"]


# ---------------------------------------------------------------------------
# Tests: API key helper (unit tests for _disable_api_key)
# ---------------------------------------------------------------------------


class TestDisableApiKey:
    """Unit tests for the _disable_api_key helper."""

    def test_returns_not_disabled_when_api_key_id_empty(self):
        """Returns disabled=False immediately when api_key_id is empty."""
        result = deprovision_handler._disable_api_key("test-org", "")
        assert result["disabled"] is False
        assert result["detail"] == "no_api_key_id"

    def test_disables_key_with_correct_patch_operation(self):
        """Sends PATCH /enabled=false to the correct API key ID."""
        mock_update = MagicMock()
        with patch.object(
            deprovision_handler._apigateway_client, "update_api_key", mock_update
        ):
            result = deprovision_handler._disable_api_key("test-org", _API_KEY_ID)

        assert result["disabled"] is True
        call_kwargs = mock_update.call_args[1]
        assert call_kwargs["apiKey"] == _API_KEY_ID
        patch_ops = call_kwargs["patchOperations"]
        assert {"op": "replace", "path": "/enabled", "value": "false"} in patch_ops

    def test_returns_not_disabled_on_client_error(self):
        """Returns disabled=False when API Gateway API call raises ClientError."""
        from botocore.exceptions import ClientError

        exc = ClientError(
            {"Error": {"Code": "NotFoundException", "Message": "key not found"}},
            "UpdateApiKey",
        )
        with patch.object(
            deprovision_handler._apigateway_client,
            "update_api_key",
            side_effect=exc,
        ):
            result = deprovision_handler._disable_api_key("test-org", _API_KEY_ID)

        assert result["disabled"] is False
        assert "apigateway_error" in result["detail"]
