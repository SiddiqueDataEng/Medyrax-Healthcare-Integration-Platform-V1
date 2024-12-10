"""
datamapper-diff Lambda (task 7.4) — Data Mapper validation endpoint.

POST /v1/admin/mapper/validate
    Accepts source HL7 + candidate FHIR resource.
    Runs canonical model diff.
    Returns JSON diff with missing/extra/modified elements.

Requirements: 13.6
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

# Path resolution
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _ok(body: dict) -> dict:
    return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def _err(code: int, msg: str) -> dict:
    return {"statusCode": code, "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": msg})}


def _canonical_diff(c1: Any, c2: Any) -> dict[str, Any]:
    """
    Compare two CanonicalMessage objects and return a structured diff.

    Returns a dict with keys:
        missing   — elements in c1 not in c2
        extra     — elements in c2 not in c1
        modified  — elements present in both but with different values
    """
    fe1 = c1.fhir_elements
    fe2 = c2.fhir_elements
    ext1 = c1.extension_map
    ext2 = c2.extension_map

    all_keys = set(fe1) | set(fe2)
    missing, extra, modified = {}, {}, {}

    for k in all_keys:
        if k not in fe2:
            missing[k] = fe1[k]
        elif k not in fe1:
            extra[k] = fe2[k]
        elif fe1[k] != fe2[k]:
            modified[k] = {"source": fe1[k], "candidate": fe2[k]}

    ext_all = set(ext1) | set(ext2)
    ext_missing = {k: ext1[k] for k in ext_all if k in ext1 and k not in ext2}
    ext_extra = {k: ext2[k] for k in ext_all if k in ext2 and k not in ext1}

    return {
        "missingElements": missing,
        "extraElements": extra,
        "modifiedElements": modified,
        "missingExtensions": ext_missing,
        "extraExtensions": ext_extra,
        "isEquivalent": not (missing or extra or modified or ext_missing or ext_extra),
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for POST /v1/admin/mapper/validate.

    Request body JSON:
        {
            "sourceHl7": "<HL7 message string>",
            "candidateFhir": {<FHIR resource dict>}
        }
    """
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError as exc:
        return _err(400, f"Invalid JSON body: {exc}")

    source_hl7 = body.get("sourceHl7", "")
    candidate_fhir = body.get("candidateFhir", {})

    if not source_hl7:
        return _err(400, "'sourceHl7' is required")
    if not candidate_fhir:
        return _err(400, "'candidateFhir' is required")

    try:
        from hl7_to_canonical import HL7ToCanonicalParser
        from fhir_to_canonical import FHIRToCanonicalParser
        from canonical_to_fhir import CanonicalToFHIRSerializer

        hl7_parser = HL7ToCanonicalParser()
        fhir_parser = FHIRToCanonicalParser()

        canonical_from_hl7 = hl7_parser.parse(source_hl7)
        canonical_from_fhir = fhir_parser.parse(candidate_fhir)

        diff = _canonical_diff(canonical_from_hl7, canonical_from_fhir)

        return _ok({
            "diff": diff,
            "sourceMessageId": canonical_from_hl7.message_id,
            "candidateResourceType": candidate_fhir.get("resourceType", "unknown"),
        })

    except Exception as exc:
        logger.error("Mapper diff failed: %s", exc)
        return _err(500, f"Diff computation failed: {exc}")
