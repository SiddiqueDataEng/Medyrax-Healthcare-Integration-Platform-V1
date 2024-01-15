"""
Unit tests for tenant-provisioner-validate Lambda.

Tests the schema validation logic for provisioning requests.
Requirements: 8.1
"""

from __future__ import annotations

import pytest
import sys
import os

# Ensure tenant-provisioner module is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from validate import handler, ProvisioningValidationError


# ---------------------------------------------------------------------------
# Valid request fixtures
# ---------------------------------------------------------------------------

VALID_EVENT = {
    "orgId": "acme-hospital",
    "orgName": "ACME Hospital",
    "adminEmail": "admin@acme-hospital.org",
}


# ---------------------------------------------------------------------------
# Valid request tests
# ---------------------------------------------------------------------------


def test_valid_minimal_request_passes():
    """A minimal valid request returns the event with validated=True."""
    result = handler(VALID_EVENT, None)
    assert result["validated"] is True
    assert result["orgId"] == "acme-hospital"
    assert result["orgName"] == "ACME Hospital"


def test_valid_full_request_passes():
    """A full request including optional fields passes validation."""
    event = {
        **VALID_EVENT,
        "alertEmail": "alerts@acme-hospital.org",
        "webhookUrl": "https://hooks.acme.example.com/medyrax",
    }
    result = handler(event, None)
    assert result["validated"] is True


def test_valid_request_preserves_all_input_fields():
    """All input fields are preserved in the output."""
    event = {
        **VALID_EVENT,
        "alertEmail": "alerts@acme.org",
        "webhookUrl": "https://hooks.acme.org/medyrax",
        "customField": "should-be-preserved",
    }
    result = handler(event, None)
    assert result["customField"] == "should-be-preserved"
    assert result["adminEmail"] == VALID_EVENT["adminEmail"]


# ---------------------------------------------------------------------------
# orgId validation
# ---------------------------------------------------------------------------


def test_missing_org_id_raises():
    event = {**VALID_EVENT}
    del event["orgId"]
    with pytest.raises(ProvisioningValidationError) as exc_info:
        handler(event, None)
    assert any("orgId" in e for e in exc_info.value.errors)


def test_empty_org_id_raises():
    event = {**VALID_EVENT, "orgId": ""}
    with pytest.raises(ProvisioningValidationError) as exc_info:
        handler(event, None)
    assert any("orgId" in e for e in exc_info.value.errors)


def test_org_id_too_short_raises():
    event = {**VALID_EVENT, "orgId": "ab"}
    with pytest.raises(ProvisioningValidationError) as exc_info:
        handler(event, None)
    assert any("orgId" in e for e in exc_info.value.errors)


def test_org_id_too_long_raises():
    event = {**VALID_EVENT, "orgId": "a" + "b" * 62 + "c"}  # 65 chars
    with pytest.raises(ProvisioningValidationError) as exc_info:
        handler(event, None)
    assert any("orgId" in e for e in exc_info.value.errors)


def test_org_id_with_uppercase_raises():
    event = {**VALID_EVENT, "orgId": "ACME-Hospital"}
    with pytest.raises(ProvisioningValidationError) as exc_info:
        handler(event, None)
    assert any("orgId" in e for e in exc_info.value.errors)


def test_org_id_starting_with_hyphen_raises():
    event = {**VALID_EVENT, "orgId": "-acme-hospital"}
    with pytest.raises(ProvisioningValidationError) as exc_info:
        handler(event, None)
    assert any("orgId" in e for e in exc_info.value.errors)


def test_org_id_ending_with_hyphen_raises():
    event = {**VALID_EVENT, "orgId": "acme-hospital-"}
    with pytest.raises(ProvisioningValidationError) as exc_info:
        handler(event, None)
    assert any("orgId" in e for e in exc_info.value.errors)


# ---------------------------------------------------------------------------
# orgName validation
# ---------------------------------------------------------------------------


def test_missing_org_name_raises():
    event = {**VALID_EVENT}
    del event["orgName"]
    with pytest.raises(ProvisioningValidationError) as exc_info:
        handler(event, None)
    assert any("orgName" in e for e in exc_info.value.errors)


def test_blank_org_name_raises():
    event = {**VALID_EVENT, "orgName": "   "}
    with pytest.raises(ProvisioningValidationError) as exc_info:
        handler(event, None)
    assert any("orgName" in e for e in exc_info.value.errors)


def test_org_name_too_long_raises():
    event = {**VALID_EVENT, "orgName": "A" * 257}
    with pytest.raises(ProvisioningValidationError) as exc_info:
        handler(event, None)
    assert any("orgName" in e for e in exc_info.value.errors)


# ---------------------------------------------------------------------------
# adminEmail validation
# ---------------------------------------------------------------------------


def test_missing_admin_email_raises():
    event = {**VALID_EVENT}
    del event["adminEmail"]
    with pytest.raises(ProvisioningValidationError) as exc_info:
        handler(event, None)
    assert any("adminEmail" in e for e in exc_info.value.errors)


def test_malformed_admin_email_raises():
    event = {**VALID_EVENT, "adminEmail": "not-an-email"}
    with pytest.raises(ProvisioningValidationError) as exc_info:
        handler(event, None)
    assert any("adminEmail" in e for e in exc_info.value.errors)


# ---------------------------------------------------------------------------
# alertEmail validation (optional field)
# ---------------------------------------------------------------------------


def test_optional_alert_email_absent_passes():
    result = handler(VALID_EVENT, None)
    assert result["validated"] is True


def test_malformed_optional_alert_email_raises():
    event = {**VALID_EVENT, "alertEmail": "not-an-email"}
    with pytest.raises(ProvisioningValidationError) as exc_info:
        handler(event, None)
    assert any("alertEmail" in e for e in exc_info.value.errors)


# ---------------------------------------------------------------------------
# webhookUrl validation (optional field)
# ---------------------------------------------------------------------------


def test_optional_webhook_absent_passes():
    result = handler(VALID_EVENT, None)
    assert result["validated"] is True


def test_webhook_must_be_https():
    event = {**VALID_EVENT, "webhookUrl": "http://insecure-webhook.example.com"}
    with pytest.raises(ProvisioningValidationError) as exc_info:
        handler(event, None)
    assert any("webhookUrl" in e for e in exc_info.value.errors)


def test_valid_https_webhook_passes():
    event = {**VALID_EVENT, "webhookUrl": "https://secure-webhook.example.com/hook"}
    result = handler(event, None)
    assert result["validated"] is True


# ---------------------------------------------------------------------------
# Multiple validation errors
# ---------------------------------------------------------------------------


def test_multiple_validation_errors_aggregated():
    """All errors are aggregated in a single raise, not fail-fast."""
    event = {
        "orgId": "",
        "orgName": "",
        "adminEmail": "bad",
    }
    with pytest.raises(ProvisioningValidationError) as exc_info:
        handler(event, None)
    # Should have at least 3 errors (orgId, orgName, adminEmail)
    assert len(exc_info.value.errors) >= 3
