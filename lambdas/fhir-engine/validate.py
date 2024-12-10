"""
fhir-engine-validate Lambda handler (task 9.1).

POST /{version}/fhir/r4/{resource}  (validation mode)
    Accepts FHIR R4 resource JSON.
    Returns 200 + validated resource, or 422 + OperationOutcome.

Requirements: 1.1, 1.2
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for FHIR validation endpoint."""
    from fhir_validator import validate_resource, build_operation_outcome  # type: ignore

    try:
        body_raw = event.get("body") or "{}"
        resource = json.loads(body_raw) if isinstance(body_raw, str) else body_raw
    except json.JSONDecodeError as exc:
        return _response(400, {"error": f"Invalid JSON body: {exc}"})

    errors = validate_resource(resource)

    if errors:
        logger.info(
            "FHIR validation failed: type=%s errors=%d",
            resource.get("resourceType", "?"), len(errors),
        )
        return _response(422, build_operation_outcome(errors))

    logger.info("FHIR validation passed: type=%s", resource.get("resourceType"))
    return _response(200, resource)


def _response(status: int, body: dict) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/fhir+json",
            "X-Medyrax-Version": "1.0",
        },
        "body": json.dumps(body),
    }
