"""
hl7-mllp-listener Lambda (task 8.1).

Receives raw MLLP-framed TCP data forwarded from the NLB via VPC Lambda.
Extracts the HL7 message, enqueues it to SQS FIFO, and returns ACK/NAK.

Must complete within 200ms to satisfy the ACK latency SLA (Requirement 2.1).

Environment variables:
    MDX_HL7_INBOUND_QUEUE_URL_TEMPLATE  — template with {org_id} placeholder,
                                          e.g. https://sqs.{region}.amazonaws.com/{acct}/mdx-{org_id}-hl7-inbound.fifo
    MDX_DEFAULT_ORG_ID                  — fallback org ID for single-tenant dev
    AWS_DEFAULT_REGION

Requirements: 2.1, 2.5
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

# Path resolution
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── Configuration ────────────────────────────────────────────────────────────
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_QUEUE_URL_TEMPLATE = os.environ.get(
    "MDX_HL7_INBOUND_QUEUE_URL_TEMPLATE",
    "https://sqs.{region}.amazonaws.com/000000000000/mdx-{org_id}-hl7-inbound.fifo",
)
_DEFAULT_ORG_ID = os.environ.get("MDX_DEFAULT_ORG_ID", "dev-org")

# ── Boto3 clients ─────────────────────────────────────────────────────────────
_sqs = boto3.client("sqs", region_name=_REGION)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for MLLP TCP events forwarded from NLB.

    The NLB target group invokes this Lambda with the TCP payload as a
    base64-encoded ``body`` field in the event dict.

    Returns a response whose ``body`` is the MLLP-framed ACK or NAK.
    """
    start_ms = time.monotonic() * 1000

    # ── Decode payload ───────────────────────────────────────────────────────
    raw_body = event.get("body", "")
    is_b64 = event.get("isBase64Encoded", False)

    try:
        if is_b64 and raw_body:
            raw_bytes = base64.b64decode(raw_body)
        elif isinstance(raw_body, str):
            raw_bytes = raw_body.encode("utf-8")
        else:
            raw_bytes = bytes(raw_body)
    except Exception as exc:
        logger.error("Failed to decode body: %s", exc)
        return _nak_response("", "Failed to decode MLLP payload")

    # ── Extract HL7 from MLLP framing ────────────────────────────────────────
    from mllp_framing import (
        extract_hl7, build_ack, wrap_hl7, extract_patient_id_from_hl7,
        ACK_AA, ACK_AE,
    )

    try:
        hl7_text = extract_hl7(raw_bytes)
    except Exception as exc:
        logger.error("MLLP framing extraction failed: %s", exc)
        return _nak_response("", str(exc))

    if not hl7_text.strip():
        return _nak_response("", "Empty HL7 message after MLLP extraction")

    # ── Extract MSH line for ACK generation ─────────────────────────────────
    msh_line = ""
    for line in hl7_text.splitlines():
        if line.startswith("MSH"):
            msh_line = line
            break

    if not msh_line:
        return _nak_response("", "MSH segment not found")

    # ── Determine org_id ─────────────────────────────────────────────────────
    # In production, org_id comes from the NLB routing header or MSH-3 lookup.
    # For MVP, we derive it from MSH-5 (receiving facility) or use the default.
    msh_fields = msh_line.split("|")
    org_id = msh_fields[5].split("^")[0].strip() if len(msh_fields) > 5 else ""
    org_id = org_id or _DEFAULT_ORG_ID

    # ── Extract patient ID for FIFO MessageGroupId ───────────────────────────
    patient_id = extract_patient_id_from_hl7(hl7_text) or "unknown"

    # ── Enqueue to SQS FIFO ──────────────────────────────────────────────────
    queue_url = _QUEUE_URL_TEMPLATE.format(region=_REGION, org_id=org_id)

    # Use message control ID (MSH-10) as deduplication ID
    msg_control_id = msh_fields[9] if len(msh_fields) > 9 else f"mdx-{int(time.time())}"

    try:
        _sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({
                "orgId": org_id,
                "hl7Message": hl7_text,
                "messageControlId": msg_control_id,
            }),
            MessageGroupId=patient_id,
            MessageDeduplicationId=msg_control_id,
        )
    except ClientError as exc:
        logger.error("SQS enqueue failed: %s", exc)
        nak = build_ack(msh_line, ack_code=ACK_AE, error_msg=f"SQS enqueue failed: {exc}")
        return _mllp_response(wrap_hl7(nak))

    elapsed_ms = (time.monotonic() * 1000) - start_ms
    logger.info(
        "HL7 message enqueued: org=%s patient=%s control=%s elapsed=%.1fms",
        org_id, patient_id, msg_control_id, elapsed_ms,
    )

    ack = build_ack(msh_line, ack_code=ACK_AA)
    return _mllp_response(wrap_hl7(ack))


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _mllp_response(mllp_bytes: bytes) -> dict[str, Any]:
    """Return a Lambda response with base64-encoded MLLP body."""
    return {
        "statusCode": 200,
        "isBase64Encoded": True,
        "headers": {"Content-Type": "application/octet-stream"},
        "body": base64.b64encode(mllp_bytes).decode("ascii"),
    }


def _nak_response(msh_line: str, error_msg: str) -> dict[str, Any]:
    """Build and return a NAK AE response."""
    from mllp_framing import build_ack, wrap_hl7, ACK_AE
    nak = build_ack(msh_line, ack_code=ACK_AE, error_msg=error_msg)
    logger.warning("Returning NAK AE: %s", error_msg)
    return _mllp_response(wrap_hl7(nak))
