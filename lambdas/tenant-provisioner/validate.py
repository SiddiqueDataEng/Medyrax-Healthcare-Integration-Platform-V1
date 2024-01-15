"""
tenant-provisioner-validate Lambda
====================================
Step 1 of the ``mdx-org-provision-sfn`` Step Function.

Validates the incoming provisioning request payload against the required
schema before any AWS resources are created.  Rejects requests early so
downstream states do not waste time or money on an invalid request.

Input (Step Function event):
    {
        "orgId":      str  — unique org identifier (slug, e.g. "acme-hospital")
        "orgName":    str  — human-readable org name
        "adminEmail": str  — primary admin contact (used for SNS notification)
        "alertEmail": str  — optional secondary alert email
        "webhookUrl": str  — optional HTTPS webhook URL
    }

Output on success (passed to next state):
    Same dict as input, with ``"validated": true`` appended.

Output on failure:
    Raises ``ProvisioningValidationError`` which Step Functions catches and
    transitions to the ``ProvisioningFailed`` state.

Requirements: 8.1
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

# org_id must be 3–63 lowercase alphanumeric chars and hyphens,
# must not start or end with a hyphen (matches S3 bucket name rules)
_ORG_ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,61}[a-z0-9]$")

# Simple email pattern; intentionally permissive — SES will hard-bounce invalid ones
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Webhook must be HTTPS
_WEBHOOK_RE = re.compile(r"^https://")


class ProvisioningValidationError(Exception):
    """Raised when the provisioning request fails schema validation."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def _validate_org_id(org_id: str) -> list[str]:
    errs: list[str] = []
    if not isinstance(org_id, str) or not org_id:
        errs.append("'orgId' is required and must be a non-empty string.")
        return errs
    if len(org_id) < 3 or len(org_id) > 63:
        errs.append("'orgId' must be between 3 and 63 characters.")
    if not _ORG_ID_RE.match(org_id):
        errs.append(
            "'orgId' must match the pattern [a-z0-9][a-z0-9-]{1,61}[a-z0-9] "
            "(lowercase, alphanumeric, hyphens allowed but not at start/end)."
        )
    return errs


def _validate_org_name(org_name: str) -> list[str]:
    errs: list[str] = []
    if not isinstance(org_name, str) or not org_name.strip():
        errs.append("'orgName' is required and must be a non-empty string.")
        return errs
    if len(org_name) > 256:
        errs.append("'orgName' must not exceed 256 characters.")
    return errs


def _validate_email(field_name: str, value: Any, required: bool = True) -> list[str]:
    errs: list[str] = []
    if not value:
        if required:
            errs.append(f"'{field_name}' is required and must be a valid email address.")
        return errs
    if not isinstance(value, str) or not _EMAIL_RE.match(value):
        errs.append(f"'{field_name}' must be a valid email address.")
    return errs


def _validate_webhook(webhook_url: Any) -> list[str]:
    errs: list[str] = []
    if not webhook_url:
        return errs  # optional field
    if not isinstance(webhook_url, str) or not _WEBHOOK_RE.match(webhook_url):
        errs.append("'webhookUrl' must be a valid HTTPS URL when provided.")
    if len(webhook_url) > 2048:
        errs.append("'webhookUrl' must not exceed 2048 characters.")
    return errs


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Validate the tenant provisioning request schema.

    Parameters
    ----------
    event:
        Step Function input — provisioning request dict.
    context:
        AWS Lambda context object (unused).

    Returns
    -------
    dict
        The original event dict with ``validated=True`` appended, ready for
        the next Step Function state.

    Raises
    ------
    ProvisioningValidationError
        When one or more required fields are missing or malformed.  Step
        Functions will catch this as a task failure and transition to the
        ``ProvisioningFailed`` state.
    """
    logger.info(
        "Validating provisioning request for orgId='%s'",
        event.get("orgId", "<missing>"),
    )

    errors: list[str] = []

    errors.extend(_validate_org_id(event.get("orgId", "")))
    errors.extend(_validate_org_name(event.get("orgName", "")))
    errors.extend(_validate_email("adminEmail", event.get("adminEmail"), required=True))
    errors.extend(_validate_email("alertEmail", event.get("alertEmail"), required=False))
    errors.extend(_validate_webhook(event.get("webhookUrl")))

    if errors:
        logger.error(
            "Provisioning validation failed for orgId='%s': %s",
            event.get("orgId"),
            errors,
        )
        raise ProvisioningValidationError(errors=errors)

    logger.info(
        "Provisioning request validated successfully for orgId='%s'",
        event["orgId"],
    )
    return {**event, "validated": True}
