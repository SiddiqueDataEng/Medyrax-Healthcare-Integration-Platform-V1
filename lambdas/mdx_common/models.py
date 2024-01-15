"""
Medyrax™ canonical data models.

All data that flows through the platform is represented using these
Python 3.12 dataclasses before being serialized to FHIR R4 JSON or
HL7 v2.x pipe-delimited format.  Every Lambda function imports from
this module so the shape of the data is consistent across subsystems.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from mdx_common.enums import (
    FhirResourceType,
    Hl7MessageType,
    IntegrationPattern,
    UserRole,
)


# ---------------------------------------------------------------------------
# EventEnvelope
# ---------------------------------------------------------------------------

@dataclass
class EventEnvelope:
    """
    Standard wrapper that every Medyrax™ event carries on the Integration Bus.

    Producers put one of these on EventBridge / SQS FIFO.  Consumers read the
    envelope to route the message before deserializing the inner ``payload``.

    Attributes
    ----------
    event_id:
        Globally unique identifier for this event (UUID v4).  Used as the SQS
        FIFO ``MessageDeduplicationId`` to provide exactly-once delivery.
    org_id:
        Identifier of the Connected_Organization that owns this event.  Drives
        tenant-level routing and isolation decisions throughout the platform.
    patient_id:
        FHIR Patient logical ID.  Used as the SQS FIFO ``MessageGroupId`` to
        enforce per-patient message ordering.
    resource_type:
        FHIR R4 resource type carried in ``payload`` (e.g. ``Observation``).
    event_type:
        Human-readable event discriminator (e.g. ``fhir.resource.created``).
    integration_pattern:
        Integration channel through which this event originated.
    payload:
        Arbitrary serializable payload — typically a FHIR R4 JSON dict or a
        pre-serialized HL7 message string.
    timestamp:
        UTC timestamp of when the event was created.  Defaults to ``now()``.
    schema_version:
        Envelope schema version.  Increment when breaking changes are made.
    correlation_id:
        Optional ID used to correlate related events (e.g. all events produced
        by the same Bundle transaction share a ``correlation_id``).
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    org_id: str = ""
    patient_id: Optional[str] = None
    resource_type: Optional[FhirResourceType] = None
    event_type: str = ""
    integration_pattern: Optional[IntegrationPattern] = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    schema_version: str = "1.0"
    correlation_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for ``json.dumps``."""
        return {
            "eventId": self.event_id,
            "orgId": self.org_id,
            "patientId": self.patient_id,
            "resourceType": self.resource_type.value if self.resource_type else None,
            "eventType": self.event_type,
            "integrationPattern": (
                self.integration_pattern.value if self.integration_pattern else None
            ),
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "schemaVersion": self.schema_version,
            "correlationId": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventEnvelope":
        """Deserialize from a plain dict (e.g. from SQS message body)."""
        resource_type_raw = data.get("resourceType")
        integration_pattern_raw = data.get("integrationPattern")
        timestamp_raw = data.get("timestamp")
        return cls(
            event_id=data.get("eventId", str(uuid.uuid4())),
            org_id=data.get("orgId", ""),
            patient_id=data.get("patientId"),
            resource_type=(
                FhirResourceType(resource_type_raw) if resource_type_raw else None
            ),
            event_type=data.get("eventType", ""),
            integration_pattern=(
                IntegrationPattern(integration_pattern_raw)
                if integration_pattern_raw
                else None
            ),
            payload=data.get("payload", {}),
            timestamp=(
                datetime.fromisoformat(timestamp_raw)
                if timestamp_raw
                else datetime.now(tz=timezone.utc)
            ),
            schema_version=data.get("schemaVersion", "1.0"),
            correlation_id=data.get("correlationId"),
        )


# ---------------------------------------------------------------------------
# CanonicalMessage
# ---------------------------------------------------------------------------

@dataclass
class CanonicalMessage:
    """
    Internal canonical representation of a clinical message.

    The Data Mapper converts both HL7 v2.x messages and FHIR R4 resources
    into this intermediate form.  All transformation logic operates on
    ``CanonicalMessage`` objects, never on raw HL7 or FHIR strings, which
    ensures that round-trip integrity properties can be verified by comparing
    two ``CanonicalMessage`` instances for semantic equivalence.

    Attributes
    ----------
    message_id:
        Unique identifier for this canonical message.
    message_type:
        HL7 message type (e.g. ``ADT_A01``) if the source was HL7, otherwise
        derived from the FHIR resource type.
    source_system:
        Originating system identifier (MSH-3 for HL7, ``Bundle.entry.request``
        for FHIR transactions).
    patient_id:
        Canonical patient identifier extracted from the message.
    segments:
        For HL7 sources: ordered list of parsed segments (each segment is a
        dict mapping field indices to string values).
        For FHIR sources: empty list (use ``fhir_elements`` instead).
    fhir_elements:
        For FHIR sources: dict of FHIR element paths to their values.
        For HL7 sources: populated after transformation.
    extension_map:
        Unmapped HL7 fields or FHIR extensions that have no standard mapping.
        Preserved verbatim to satisfy round-trip integrity requirements.
        Key: ``"{segment}-{fieldIndex}"`` for HL7, FHIR path for FHIR.
    raw_source:
        Original raw message bytes/string before parsing.  Stored for audit
        and diff purposes.
    source_sha256:
        SHA-256 hex digest of ``raw_source``.  Written to the transformation
        audit DynamoDB record.
    created_at:
        UTC timestamp when this canonical object was created.
    """

    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    message_type: Optional[Hl7MessageType] = None
    source_system: str = ""
    patient_id: Optional[str] = None
    segments: list[dict[int, str]] = field(default_factory=list)
    fhir_elements: dict[str, Any] = field(default_factory=dict)
    extension_map: dict[str, Any] = field(default_factory=dict)
    raw_source: Optional[str] = None
    source_sha256: Optional[str] = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    def is_semantically_equivalent(self, other: "CanonicalMessage") -> bool:
        """
        Return True when ``self`` and ``other`` carry the same clinical meaning.

        Two canonical messages are semantically equivalent when:
        - Their ``fhir_elements`` dicts are equal (for FHIR-sourced messages).
        - Their ``segments`` lists are equal (for HL7-sourced messages).
        - Their ``extension_map`` dicts are equal (unmapped fields preserved).

        This method is used directly by property-based tests to verify that
        parse → serialize → parse produces an equivalent canonical model.
        """
        fhir_eq = self.fhir_elements == other.fhir_elements
        segments_eq = self.segments == other.segments
        extensions_eq = self.extension_map == other.extension_map
        return fhir_eq and segments_eq and extensions_eq


# ---------------------------------------------------------------------------
# TenantConfig
# ---------------------------------------------------------------------------

@dataclass
class TenantConfig:
    """
    Runtime configuration for a single Connected_Organization.

    Loaded from DynamoDB table ``mdx-tenants`` by every Lambda function at
    cold-start (and cached module-level) via ``TenantConfigService``.  Never
    log or serialize ``kms_key_arn`` or ``iam_role_arn`` in plain-text logs.

    Attributes
    ----------
    org_id:
        Primary partition key of the tenant record.
    org_name:
        Human-readable name of the Connected_Organization.
    status:
        Lifecycle status.  Only ``"active"`` tenants may process requests.
    kms_key_arn:
        ARN of the per-org KMS CMK used for all at-rest encryption.
    iam_role_arn:
        ARN of the per-org IAM execution role.
    health_lake_data_store_id:
        AWS HealthLake datastore ID for this org.  Required for all HealthLake
        API calls.
    sqs_fifo_queue_url:
        URL of the primary SQS FIFO queue for this org.
    sqs_alert_queue_url:
        URL of the SQS standard queue for clinical alert routing.
    sqs_dlq_url:
        URL of the dead-letter queue.
    event_bus_arn:
        ARN of the per-org EventBridge custom event bus.
    sftp_server_id:
        AWS Transfer Family SFTP server ID.
    s3_input_bucket:
        S3 bucket for inbound files.
    s3_input_prefix:
        S3 key prefix for inbound files (e.g. ``"inbound/"``).
    s3_output_bucket:
        S3 bucket for outbound files.
    s3_output_prefix:
        S3 key prefix for outbound files.
    s3_reports_bucket:
        S3 bucket for file validation reports.
    webhook_url:
        Optional HTTPS URL for webhook event delivery.
    alert_email:
        Optional email address for SNS alert notifications.
    session_timeout_minutes:
        Cognito access token expiry in minutes (default 15).
    kms_rotation_days:
        KMS CMK rotation interval in days (default 365).
    analytics_schedule_minutes:
        How often the Analytics Connector pushes to S3 Parquet (default 30).
    provisioned_at:
        UTC timestamp when this tenant was provisioned.
    deprovisioned_at:
        UTC timestamp when this tenant was deprovisioned (``None`` if active).
    """

    org_id: str
    org_name: str
    status: str = "active"  # active | suspended | deprovisioned
    kms_key_arn: str = ""
    iam_role_arn: str = ""
    health_lake_data_store_id: str = ""
    sqs_fifo_queue_url: str = ""
    sqs_alert_queue_url: str = ""
    sqs_dlq_url: str = ""
    event_bus_arn: str = ""
    sftp_server_id: str = ""
    s3_input_bucket: str = ""
    s3_input_prefix: str = "inbound/"
    s3_output_bucket: str = ""
    s3_output_prefix: str = "outbound/"
    s3_reports_bucket: str = ""
    webhook_url: Optional[str] = None
    alert_email: Optional[str] = None
    session_timeout_minutes: int = 15
    kms_rotation_days: int = 365
    analytics_schedule_minutes: int = 30
    provisioned_at: Optional[datetime] = None
    deprovisioned_at: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        """Return ``True`` only when the tenant is in ``active`` status."""
        return self.status == "active"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a DynamoDB-compatible dict (no datetime objects)."""
        return {
            "orgId": self.org_id,
            "orgName": self.org_name,
            "status": self.status,
            "kmsKeyArn": self.kms_key_arn,
            "iamRoleArn": self.iam_role_arn,
            "healthLakeDataStoreId": self.health_lake_data_store_id,
            "sqsFifoQueueUrl": self.sqs_fifo_queue_url,
            "sqsAlertQueueUrl": self.sqs_alert_queue_url,
            "sqsDlqUrl": self.sqs_dlq_url,
            "eventBusArn": self.event_bus_arn,
            "sftpServerId": self.sftp_server_id,
            "s3InputBucket": self.s3_input_bucket,
            "s3InputPrefix": self.s3_input_prefix,
            "s3OutputBucket": self.s3_output_bucket,
            "s3OutputPrefix": self.s3_output_prefix,
            "s3ReportsBucket": self.s3_reports_bucket,
            "webhookUrl": self.webhook_url,
            "alertEmail": self.alert_email,
            "sessionTimeoutMinutes": self.session_timeout_minutes,
            "kmsRotationDays": self.kms_rotation_days,
            "analyticsScheduleMinutes": self.analytics_schedule_minutes,
            "provisionedAt": (
                self.provisioned_at.isoformat() if self.provisioned_at else None
            ),
            "deprovisionedAt": (
                self.deprovisioned_at.isoformat() if self.deprovisioned_at else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TenantConfig":
        """Deserialize from a DynamoDB item dict."""

        def _parse_dt(val: Any) -> Optional[datetime]:
            return datetime.fromisoformat(val) if val else None

        return cls(
            org_id=data["orgId"],
            org_name=data.get("orgName", ""),
            status=data.get("status", "active"),
            kms_key_arn=data.get("kmsKeyArn", ""),
            iam_role_arn=data.get("iamRoleArn", ""),
            health_lake_data_store_id=data.get("healthLakeDataStoreId", ""),
            sqs_fifo_queue_url=data.get("sqsFifoQueueUrl", ""),
            sqs_alert_queue_url=data.get("sqsAlertQueueUrl", ""),
            sqs_dlq_url=data.get("sqsDlqUrl", ""),
            event_bus_arn=data.get("eventBusArn", ""),
            sftp_server_id=data.get("sftpServerId", ""),
            s3_input_bucket=data.get("s3InputBucket", ""),
            s3_input_prefix=data.get("s3InputPrefix", "inbound/"),
            s3_output_bucket=data.get("s3OutputBucket", ""),
            s3_output_prefix=data.get("s3OutputPrefix", "outbound/"),
            s3_reports_bucket=data.get("s3ReportsBucket", ""),
            webhook_url=data.get("webhookUrl"),
            alert_email=data.get("alertEmail"),
            session_timeout_minutes=int(data.get("sessionTimeoutMinutes", 15)),
            kms_rotation_days=int(data.get("kmsRotationDays", 365)),
            analytics_schedule_minutes=int(data.get("analyticsScheduleMinutes", 30)),
            provisioned_at=_parse_dt(data.get("provisionedAt")),
            deprovisioned_at=_parse_dt(data.get("deprovisionedAt")),
        )


# ---------------------------------------------------------------------------
# AuditLogEntry
# ---------------------------------------------------------------------------

@dataclass
class AuditLogEntry:
    """
    Structured audit log record emitted by the Security Layer.

    Written to CloudWatch Logs group ``mdx-audit-{orgId}`` within 1 second of
    every PHI access (Requirement 7.3).  Retained for 7 years (Requirement 7.8).

    Attributes
    ----------
    timestamp:
        UTC timestamp of the PHI access event.
    accessor_id:
        Identity of the principal (Cognito sub, IAM ARN, or service name).
    accessor_role:
        RBAC role the accessor acted under.
    org_id:
        Connected_Organization whose data was accessed.
    resource_type:
        FHIR R4 resource type that was accessed (e.g. ``"Patient"``).
    resource_id:
        Server-generated logical ID of the FHIR resource.
    operation:
        FHIR interaction type: ``read | search | create | update | delete``.
    source_ip:
        IP address of the caller as reported by API Gateway / Lambda.
    allowed:
        ``True`` if access was granted; ``False`` if denied (RBAC 403).
    event_id:
        Unique identifier for this audit record.
    """

    timestamp: datetime
    accessor_id: str
    accessor_role: UserRole
    org_id: str
    resource_type: str
    resource_id: str
    operation: str
    source_ip: str
    allowed: bool
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-serializable dict for CloudWatch Logs."""
        return {
            "eventId": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "accessorId": self.accessor_id,
            "accessorRole": self.accessor_role.value,
            "orgId": self.org_id,
            "resourceType": self.resource_type,
            "resourceId": self.resource_id,
            "operation": self.operation,
            "sourceIp": self.source_ip,
            "allowed": self.allowed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditLogEntry":
        """Deserialize from a CloudWatch Logs event JSON dict."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            accessor_id=data["accessorId"],
            accessor_role=UserRole(data["accessorRole"]),
            org_id=data["orgId"],
            resource_type=data["resourceType"],
            resource_id=data["resourceId"],
            operation=data["operation"],
            source_ip=data["sourceIp"],
            allowed=data["allowed"],
            event_id=data.get("eventId", str(uuid.uuid4())),
        )
