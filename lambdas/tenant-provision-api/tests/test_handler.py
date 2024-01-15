"""
Unit tests for tenant-provision-api Lambda handler.

Tests both the POST (start provisioning) and GET (status query) endpoints.

Requirements: 8.1
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest

# Ensure the handler module is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Ensure mdx_common is importable — the package lives at lambdas/mdx_common/,
# so we need lambdas/ (the parent of mdx_common/) on sys.path.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Set required env vars before import so the module-level client is configured
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault(
    "MDX_SFN_ARN",
    "arn:aws:states:us-east-1:123456789012:stateMachine:mdx-org-provision-sfn",
)

import handler as provision_handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SFN_ARN = "arn:aws:states:us-east-1:123456789012:stateMachine:mdx-org-provision-sfn"
_EXECUTION_ARN = (
    "arn:aws:states:us-east-1:123456789012:execution:"
    "mdx-org-provision-sfn:provision-acme-hospital"
)


def _post_event(body: dict | str | None = None) -> dict:
    """Build a minimal API Gateway proxy event for POST /v1/admin/organizations."""
    if body is None:
        body = {"orgId": "acme-hospital", "orgName": "ACME Hospital", "adminEmail": "a@b.com"}
    return {
        "httpMethod": "POST",
        "resource": "/v1/admin/organizations",
        "path": "/v1/admin/organizations",
        "pathParameters": None,
        "body": json.dumps(body) if isinstance(body, dict) else body,
    }


def _get_event(org_id: str = "acme-hospital") -> dict:
    """Build a minimal API Gateway proxy event for GET /v1/admin/organizations/{orgId}/status."""
    return {
        "httpMethod": "GET",
        "resource": f"/v1/admin/organizations/{org_id}/status",
        "path": f"/v1/admin/organizations/{org_id}/status",
        "pathParameters": {"orgId": org_id},
        "body": None,
    }


def _sfn_execution_response(status: str = "RUNNING") -> dict:
    """Build a minimal describe_execution response dict."""
    from datetime import datetime, timezone

    resp = {
        "executionArn": _EXECUTION_ARN,
        "stateMachineArn": _SFN_ARN,
        "name": "provision-acme-hospital",
        "status": status,
        "startDate": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    }
    if status in ("SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"):
        resp["stopDate"] = datetime(2024, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    if status == "SUCCEEDED":
        resp["output"] = json.dumps({"orgId": "acme-hospital", "status": "active"})
    if status == "FAILED":
        resp["error"] = "ProvisioningValidationError"
        resp["cause"] = "Invalid orgId format"
    return resp


# ---------------------------------------------------------------------------
# POST /v1/admin/organizations — start provisioning
# ---------------------------------------------------------------------------


class TestPostStartProvisioning:
    """Tests for the POST create-provisioning endpoint."""

    def test_returns_202_on_success(self):
        """POST with valid body returns 202 Accepted and executionArn."""
        mock_response = {
            "executionArn": _EXECUTION_ARN,
            "startDate": "2024-01-01T12:00:00+00:00",
        }
        with patch.object(provision_handler._sfn_client, "start_execution", return_value=mock_response):
            response = provision_handler.handler(_post_event(), None)

        assert response["statusCode"] == 202
        body = json.loads(response["body"])
        assert body["executionArn"] == _EXECUTION_ARN
        assert body["orgId"] == "acme-hospital"
        assert body["status"] == "PROVISIONING_STARTED"

    def test_returns_400_when_org_id_missing(self):
        """POST without orgId returns 400 Bad Request."""
        event = _post_event(body={"orgName": "ACME", "adminEmail": "a@b.com"})
        with patch.object(provision_handler._sfn_client, "start_execution"):
            response = provision_handler.handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "MISSING_REQUIRED_FIELD"

    def test_returns_400_when_body_invalid_json(self):
        """POST with malformed JSON body returns 400."""
        event = _post_event(body="not-json{{{")
        response = provision_handler.handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "INVALID_REQUEST_BODY"

    def test_returns_409_when_execution_already_exists(self):
        """POST for an orgId with an active execution returns 409 Conflict."""
        exc = provision_handler._sfn_client.exceptions.ExecutionAlreadyExists(
            {"Error": {"Code": "ExecutionAlreadyExists", "Message": "already exists"}},
            "StartExecution",
        )
        with patch.object(provision_handler._sfn_client, "start_execution", side_effect=exc):
            response = provision_handler.handler(_post_event(), None)

        assert response["statusCode"] == 409
        body = json.loads(response["body"])
        assert body["error"] == "EXECUTION_ALREADY_EXISTS"

    def test_returns_500_when_sfn_arn_not_configured(self):
        """POST returns 500 when MDX_SFN_ARN env var is empty."""
        original = provision_handler.SFN_ARN
        provision_handler.SFN_ARN = ""
        try:
            response = provision_handler.handler(_post_event(), None)
        finally:
            provision_handler.SFN_ARN = original

        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert body["error"] == "CONFIGURATION_ERROR"

    def test_returns_500_when_state_machine_not_found(self):
        """POST returns 500 when Step Function ARN does not exist."""
        exc = provision_handler._sfn_client.exceptions.StateMachineDoesNotExist(
            {"Error": {"Code": "StateMachineDoesNotExist", "Message": "not found"}},
            "StartExecution",
        )
        with patch.object(provision_handler._sfn_client, "start_execution", side_effect=exc):
            response = provision_handler.handler(_post_event(), None)

        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert body["error"] == "CONFIGURATION_ERROR"

    def test_response_body_contains_message(self):
        """202 response includes a human-readable message."""
        mock_response = {"executionArn": _EXECUTION_ARN}
        with patch.object(provision_handler._sfn_client, "start_execution", return_value=mock_response):
            response = provision_handler.handler(_post_event(), None)

        body = json.loads(response["body"])
        assert "message" in body
        assert "acme-hospital" in body["message"]

    def test_body_as_pre_parsed_dict(self):
        """POST handler works when API GW has pre-parsed the body as a dict."""
        event = {
            "httpMethod": "POST",
            "resource": "/v1/admin/organizations",
            "path": "/v1/admin/organizations",
            "pathParameters": None,
            "body": {"orgId": "test-org", "orgName": "Test", "adminEmail": "t@t.com"},
        }
        mock_response = {"executionArn": _EXECUTION_ARN}
        with patch.object(provision_handler._sfn_client, "start_execution", return_value=mock_response):
            response = provision_handler.handler(event, None)

        assert response["statusCode"] == 202

    def test_content_type_header_is_json(self):
        """Response always includes Content-Type: application/json."""
        mock_response = {"executionArn": _EXECUTION_ARN}
        with patch.object(provision_handler._sfn_client, "start_execution", return_value=mock_response):
            response = provision_handler.handler(_post_event(), None)

        assert response["headers"]["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# GET /v1/admin/organizations/{orgId}/status — query provisioning status
# ---------------------------------------------------------------------------


class TestGetProvisioningStatus:
    """Tests for the GET provisioning-status endpoint."""

    def test_returns_200_with_running_status(self):
        """GET returns 200 with PROVISIONING_IN_PROGRESS for a running execution."""
        with patch.object(
            provision_handler._sfn_client,
            "describe_execution",
            return_value=_sfn_execution_response("RUNNING"),
        ):
            response = provision_handler.handler(_get_event(), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["status"] == "PROVISIONING_IN_PROGRESS"
        assert body["orgId"] == "acme-hospital"
        assert body["sfnStatus"] == "RUNNING"
        assert "startedAt" in body

    def test_returns_200_with_succeeded_status(self):
        """GET maps SFN SUCCEEDED to PROVISIONING_COMPLETE."""
        with patch.object(
            provision_handler._sfn_client,
            "describe_execution",
            return_value=_sfn_execution_response("SUCCEEDED"),
        ):
            response = provision_handler.handler(_get_event(), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["status"] == "PROVISIONING_COMPLETE"
        assert "completedAt" in body
        assert "output" in body

    def test_returns_200_with_failed_status(self):
        """GET maps SFN FAILED to PROVISIONING_FAILED and includes error details."""
        with patch.object(
            provision_handler._sfn_client,
            "describe_execution",
            return_value=_sfn_execution_response("FAILED"),
        ):
            response = provision_handler.handler(_get_event(), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["status"] == "PROVISIONING_FAILED"
        assert body["error"] == "ProvisioningValidationError"
        assert "cause" in body
        assert "completedAt" in body

    def test_returns_200_with_timed_out_status(self):
        """GET maps SFN TIMED_OUT to PROVISIONING_TIMED_OUT."""
        with patch.object(
            provision_handler._sfn_client,
            "describe_execution",
            return_value=_sfn_execution_response("TIMED_OUT"),
        ):
            response = provision_handler.handler(_get_event(), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["status"] == "PROVISIONING_TIMED_OUT"

    def test_returns_200_with_aborted_status(self):
        """GET maps SFN ABORTED to PROVISIONING_ABORTED."""
        with patch.object(
            provision_handler._sfn_client,
            "describe_execution",
            return_value=_sfn_execution_response("ABORTED"),
        ):
            response = provision_handler.handler(_get_event(), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["status"] == "PROVISIONING_ABORTED"

    def test_returns_404_when_execution_not_found(self):
        """GET returns 404 when no execution exists for orgId."""
        exc = provision_handler._sfn_client.exceptions.ExecutionDoesNotExist(
            {"Error": {"Code": "ExecutionDoesNotExist", "Message": "not found"}},
            "DescribeExecution",
        )
        with patch.object(
            provision_handler._sfn_client, "describe_execution", side_effect=exc
        ):
            response = provision_handler.handler(_get_event("unknown-org"), None)

        assert response["statusCode"] == 404
        body = json.loads(response["body"])
        assert body["error"] == "EXECUTION_NOT_FOUND"
        assert "unknown-org" in body["message"]

    def test_returns_400_when_org_id_missing_from_path(self):
        """GET without orgId path param returns 400.

        Simulates an API Gateway event where the route matched (e.g. a proxy
        route) but pathParameters does not contain 'orgId'.
        """
        # Directly call _get_provisioning_status with an event that has
        # pathParameters but no orgId key — this is what the handler sees when
        # pathParameters is present but the key is absent.
        event = {
            "httpMethod": "GET",
            "resource": "/v1/admin/organizations/PLACEHOLDER/status",
            "path": "/v1/admin/organizations/PLACEHOLDER/status",
            "pathParameters": {"orgId": ""},   # empty string orgId
            "body": None,
        }
        response = provision_handler.handler(event, None)
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "MISSING_PATH_PARAMETER"

    def test_returns_500_when_sfn_arn_not_configured(self):
        """GET returns 500 when MDX_SFN_ARN env var is empty."""
        original = provision_handler.SFN_ARN
        provision_handler.SFN_ARN = ""
        try:
            response = provision_handler.handler(_get_event(), None)
        finally:
            provision_handler.SFN_ARN = original

        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert body["error"] == "CONFIGURATION_ERROR"

    def test_execution_arn_in_response(self):
        """GET response includes the executionArn."""
        with patch.object(
            provision_handler._sfn_client,
            "describe_execution",
            return_value=_sfn_execution_response("RUNNING"),
        ):
            response = provision_handler.handler(_get_event(), None)

        body = json.loads(response["body"])
        assert "executionArn" in body

    def test_content_type_header_is_json(self):
        """GET response always includes Content-Type: application/json."""
        with patch.object(
            provision_handler._sfn_client,
            "describe_execution",
            return_value=_sfn_execution_response("RUNNING"),
        ):
            response = provision_handler.handler(_get_event(), None)

        assert response["headers"]["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# Route dispatch
# ---------------------------------------------------------------------------


class TestRouteDispatch:
    """Tests for the HTTP method/path router."""

    def test_unknown_method_returns_405(self):
        """Unsupported method returns 405 Method Not Allowed."""
        event = {
            "httpMethod": "DELETE",
            "resource": "/v1/admin/organizations",
            "path": "/v1/admin/organizations",
            "pathParameters": None,
            "body": None,
        }
        response = provision_handler.handler(event, None)
        assert response["statusCode"] == 405
        body = json.loads(response["body"])
        assert body["error"] == "METHOD_NOT_ALLOWED"

    def test_unknown_path_returns_405(self):
        """Unknown path returns 405."""
        event = {
            "httpMethod": "POST",
            "resource": "/v1/admin/unknown",
            "path": "/v1/admin/unknown",
            "pathParameters": None,
            "body": None,
        }
        response = provision_handler.handler(event, None)
        assert response["statusCode"] == 405

    @pytest.mark.parametrize(
        "resource",
        [
            "/v1/admin/organizations",
            "/v2/admin/organizations",
            "/v1/admin/organizations/",
        ],
    )
    def test_create_route_matching(self, resource):
        """POST route matcher accepts versioned organization paths."""
        assert provision_handler._matches_create_route(resource) is True

    @pytest.mark.parametrize(
        "resource",
        [
            "/v1/admin/organizations/acme-hospital/status",
            "/v2/admin/organizations/my-org-123/status",
            "/v1/admin/organizations/test-org/status/",
        ],
    )
    def test_status_route_matching(self, resource):
        """GET status route matcher accepts versioned org/status paths."""
        assert provision_handler._matches_status_route(resource) is True

    @pytest.mark.parametrize(
        "resource",
        [
            "/admin/organizations",          # missing version prefix
            "/v1/organizations",             # missing 'admin'
            "/v1/admin/organizations/status",  # missing orgId segment
        ],
    )
    def test_non_matching_routes_rejected(self, resource):
        """Route matchers correctly reject non-matching paths."""
        assert provision_handler._matches_create_route(resource) is False
        assert provision_handler._matches_status_route(resource) is False
