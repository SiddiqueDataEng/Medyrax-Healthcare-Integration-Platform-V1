"""
HL7 Transformation Ruleset Loader (task 7.2).

Reads ruleset JSON from S3:
    s3://mdx-transformation-rules/{message_type}/{version}/ruleset.json

Caches in a module-level dict keyed by ``{message_type}_{version}`` so that
each Lambda execution environment pays the S3 read only once per cold start.

Requirements: 2.2, 2.8
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# ── Module-level cache ───────────────────────────────────────────────────────
_cache: dict[str, dict[str, Any]] = {}
_cache_lock = threading.Lock()

# ── Configuration ────────────────────────────────────────────────────────────
_S3_BUCKET = os.environ.get(
    "MDX_TRANSFORMATION_RULES_BUCKET", "mdx-transformation-rules"
)
_AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

# ── S3 client (module-level for warm reuse) ─────────────────────────────────
_s3_client = None
_s3_lock = threading.Lock()


def _get_s3() -> Any:
    global _s3_client
    if _s3_client is None:
        with _s3_lock:
            if _s3_client is None:
                _s3_client = boto3.client("s3", region_name=_AWS_REGION)
    return _s3_client


# Supported message types (Requirement 2.2)
SUPPORTED_TYPES: frozenset[str] = frozenset([
    "ADT_A01", "ADT_A02", "ADT_A03", "ADT_A04", "ADT_A05", "ADT_A06",
    "ADT_A07", "ADT_A08", "ADT_A09", "ADT_A10", "ADT_A11", "ADT_A12",
    "ADT_A13", "ADT_A28", "ADT_A29", "ADT_A31", "ADT_A40",
    "ORM_O01", "ORU_R01",
    "MDM_T01", "MDM_T02", "MDM_T11",
    "DFT_P03",
    "SIU_S12", "SIU_S13", "SIU_S14", "SIU_S15",
    "VXU_V04",
])


def get_ruleset(message_type: str, version: str = "1.0") -> dict[str, Any]:
    """
    Return the transformation ruleset for ``message_type`` at ``version``.

    Checks the module-level cache first; loads from S3 on a miss.
    The ruleset is cached indefinitely for the lifetime of the Lambda
    execution environment.

    Parameters
    ----------
    message_type:
        HL7 message type string (e.g. ``"ADT_A01"``).
    version:
        Ruleset version (e.g. ``"1.0"``).

    Returns
    -------
    dict
        Parsed ruleset JSON.  If the ruleset cannot be loaded, returns a
        minimal passthrough ruleset so processing continues.

    Raises
    ------
    ValueError
        When ``message_type`` is not in :data:`SUPPORTED_TYPES`.
    """
    if message_type not in SUPPORTED_TYPES:
        raise ValueError(
            f"Unsupported message type '{message_type}'. "
            f"Supported: {sorted(SUPPORTED_TYPES)}"
        )

    cache_key = f"{message_type}_{version}"

    with _cache_lock:
        if cache_key in _cache:
            logger.debug("Ruleset cache hit: %s", cache_key)
            return _cache[cache_key]

    ruleset = _load_from_s3(message_type, version) or _default_ruleset(message_type, version)

    with _cache_lock:
        _cache[cache_key] = ruleset

    return ruleset


def invalidate_cache(message_type: Optional[str] = None, version: str = "1.0") -> None:
    """Invalidate ruleset cache entry (or entire cache when type is None)."""
    with _cache_lock:
        if message_type is None:
            _cache.clear()
            logger.info("Transformation ruleset cache cleared.")
        else:
            _cache.pop(f"{message_type}_{version}", None)
            logger.info("Evicted ruleset cache entry: %s_%s", message_type, version)


def _load_from_s3(message_type: str, version: str) -> Optional[dict[str, Any]]:
    """Fetch and parse ruleset JSON from S3; return None on any error."""
    s3_key = f"{message_type}/{version}/ruleset.json"
    try:
        resp = _get_s3().get_object(Bucket=_S3_BUCKET, Key=s3_key)
        body = resp["Body"].read().decode("utf-8")
        ruleset = json.loads(body)
        logger.info("Loaded ruleset from s3://%s/%s", _S3_BUCKET, s3_key)
        return ruleset
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404"):
            logger.warning(
                "Ruleset not found in S3: s3://%s/%s — using default passthrough.",
                _S3_BUCKET, s3_key,
            )
        else:
            logger.error("S3 error loading ruleset %s: %s", s3_key, exc)
    except Exception as exc:
        logger.error("Unexpected error loading ruleset %s: %s", s3_key, exc)
    return None


def _default_ruleset(message_type: str, version: str) -> dict[str, Any]:
    """Return a minimal passthrough ruleset when S3 has no ruleset."""
    return {
        "messageType": message_type,
        "version": version,
        "source": "default_passthrough",
        "segmentMappings": {
            "MSH": {"sourceField": "MSH", "targetPath": "MessageHeader"},
            "PID": {"sourceField": "PID", "targetPath": "Patient"},
            "PV1": {"sourceField": "PV1", "targetPath": "Encounter"},
            "OBX": {"sourceField": "OBX", "targetPath": "Observation"},
            "DG1": {"sourceField": "DG1", "targetPath": "Condition"},
        },
        "preserveUnmapped": True,
    }
