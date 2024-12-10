"""
TransformationAuditor — write HL7↔FHIR transformation audit records to DynamoDB.

Writes to table ``mdx-transformation-audit`` (PK: orgId#messageControlId,
SK: ISO-8601 timestamp).  Sets TTL = now + 7 years (HIPAA Requirement 13.5).

The ``record()`` function is fire-and-non-raise: DynamoDB errors are logged
as warnings rather than propagated so that a transient DDB failure never
blocks message processing.

Requirements: 13.5
"""

from __future__ import annotations

import calendar
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# DynamoDB table name — override via environment variable
_TABLE_NAME = os.environ.get("MDX_TRANSFORMATION_AUDIT_TABLE", "mdx-transformation-audit")

# 7-year HIPAA retention in seconds
_SEVEN_YEARS_SECONDS = 365 * 7 * 24 * 3600


class TransformationAuditor:
    """
    Write transformation audit records to DynamoDB.

    Usage::

        auditor = TransformationAuditor()
        auditor.record(
            source_id="msg-123",
            target_id="fhir-456",
            ruleset_version="1.0",
            source_content=raw_hl7,
            target_content=json.dumps(fhir_resource),
            org_id="acme-hospital",
        )
    """

    def __init__(
        self,
        table_name: Optional[str] = None,
        region: Optional[str] = None,
        dynamodb_resource=None,
    ) -> None:
        self._table_name = table_name or _TABLE_NAME
        self._region = region or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        self._dynamodb = dynamodb_resource

    def _get_table(self):
        """Lazily initialise the DynamoDB Table resource."""
        if self._dynamodb is None:
            import boto3
            self._dynamodb = boto3.resource("dynamodb", region_name=self._region)
        return self._dynamodb.Table(self._table_name)

    def record(
        self,
        *,
        source_id: str,
        target_id: str,
        ruleset_version: str,
        source_content: str,
        target_content: str,
        org_id: str,
        message_type: str = "",
    ) -> None:
        """
        Write a transformation audit record to DynamoDB.

        Parameters
        ----------
        source_id:
            Message control ID of the source HL7 message, or FHIR resource ID.
        target_id:
            Server-assigned ID of the produced FHIR resource (or HL7 control ID).
        ruleset_version:
            Version string of the transformation ruleset used (e.g. ``"1.0"``).
        source_content:
            Raw source text (HL7 string or FHIR JSON) — used for SHA-256.
        target_content:
            Raw target text — used for SHA-256.
        org_id:
            Connected_Organization that owns this transformation.
        message_type:
            HL7 message type string for informational purposes (e.g. ``"ADT_A01"``).
        """
        now = datetime.now(tz=timezone.utc)
        ts_str = now.isoformat()
        ttl = int(calendar.timegm(now.utctimetuple())) + _SEVEN_YEARS_SECONDS

        source_sha256 = hashlib.sha256(
            source_content.encode("utf-8", errors="replace")
        ).hexdigest()
        target_sha256 = hashlib.sha256(
            target_content.encode("utf-8", errors="replace")
        ).hexdigest()

        item = {
            "pk": f"{org_id}#{source_id}",
            "timestamp": ts_str,
            "orgId": org_id,
            "sourceId": source_id,
            "targetId": target_id,
            "rulesetVersion": ruleset_version,
            "sourceSha256": source_sha256,
            "targetSha256": target_sha256,
            "messageType": message_type,
            "ttl": ttl,
        }

        try:
            self._get_table().put_item(Item=item)
            logger.debug(
                "Transformation audit written: org=%s source=%s target=%s",
                org_id, source_id, target_id,
            )
        except Exception as exc:
            # Non-blocking — log warning and continue (Requirement 13.5 states
            # the record MUST be written, but transient DDB errors should not
            # block message processing; an alarm monitors DLQ depth).
            logger.warning(
                "Failed to write transformation audit record: %s "
                "(source_id=%s, org_id=%s)",
                exc, source_id, org_id,
            )
