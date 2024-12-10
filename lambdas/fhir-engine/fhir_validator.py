"""
FHIR R4 resource validator (task 9.1).

Validates resources against R4 base profiles using fhir.resources library.
Returns list of validation error strings, empty list on success.

SLA: complete within 500ms (Requirement 1.1, 1.2).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Supported R4 resource types (Requirement 1.4)
SUPPORTED_RESOURCE_TYPES = frozenset([
    "Patient", "Practitioner", "Organization", "Encounter", "Observation",
    "Condition", "MedicationRequest", "DiagnosticReport", "AllergyIntolerance",
    "Procedure", "Coverage",
])


def validate_resource(resource: dict[str, Any]) -> list[str]:
    """
    Validate a FHIR R4 resource dict against its base profile.

    Returns a list of validation error strings (empty = valid).

    Parameters
    ----------
    resource:
        FHIR R4 resource as a Python dict.

    Returns
    -------
    list[str]
        Validation error messages.  Empty list when resource is valid.
    """
    errors: list[str] = []
    resource_type = resource.get("resourceType", "")

    if not resource_type:
        errors.append("Missing required field: resourceType")
        return errors

    if resource_type not in SUPPORTED_RESOURCE_TYPES:
        errors.append(
            f"Unsupported resource type '{resource_type}'. "
            f"Supported: {sorted(SUPPORTED_RESOURCE_TYPES)}"
        )
        return errors

    # Try fhir.resources validation
    try:
        from fhir.resources import construct_fhir_element  # type: ignore
        construct_fhir_element(resource_type, resource)
        logger.debug("fhir.resources validation passed for %s", resource_type)
        return []
    except ImportError:
        logger.warning("fhir.resources not installed — falling back to manual validation")
    except Exception as exc:
        errors.append(f"Profile validation error: {exc}")
        return errors

    # Manual fallback validation (required fields per resource type)
    errors.extend(_manual_validate(resource_type, resource))
    return errors


def _manual_validate(resource_type: str, resource: dict[str, Any]) -> list[str]:
    """Perform basic required-field checks without the fhir.resources library."""
    errors: list[str] = []
    required: dict[str, list[str]] = {
        "Patient": [],
        "Practitioner": [],
        "Organization": ["name"],
        "Encounter": ["status", "class", "subject"],
        "Observation": ["status", "code", "subject"],
        "Condition": ["subject"],
        "MedicationRequest": ["status", "intent", "subject", "medication"],
        "DiagnosticReport": ["status", "code", "subject"],
        "AllergyIntolerance": ["patient"],
        "Procedure": ["status", "subject", "code"],
        "Coverage": ["status", "beneficiary"],
    }
    for field in required.get(resource_type, []):
        if not resource.get(field):
            errors.append(f"{resource_type}.{field} is required")
    return errors


def build_operation_outcome(errors: list[str]) -> dict[str, Any]:
    """
    Build a FHIR OperationOutcome resource from a list of error messages.

    Returns an OperationOutcome dict suitable for inclusion in an HTTP 422 body.
    """
    issues = []
    for msg in errors:
        issues.append({
            "severity": "error",
            "code": "invariant",
            "diagnostics": msg,
        })
    return {
        "resourceType": "OperationOutcome",
        "issue": issues,
    }
