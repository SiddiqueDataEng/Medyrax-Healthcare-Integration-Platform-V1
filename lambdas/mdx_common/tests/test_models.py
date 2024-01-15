"""
Unit and property-based tests for mdx_common.models.

Tests cover:
- EventEnvelope to_dict / from_dict round-trip
- TenantConfig.is_active property
- AuditLogEntry to_dict / from_dict round-trip
- CanonicalMessage.is_semantically_equivalent() identity and inequality
- Hypothesis-driven arbitrary string generation for EventEnvelope fields
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import sys
import os

# Ensure the lambdas directory is on the path so mdx_common can be imported
# when pytest is run from the aws/ workspace root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from mdx_common.models import (
    AuditLogEntry,
    CanonicalMessage,
    EventEnvelope,
    TenantConfig,
)
from mdx_common.enums import (
    FhirResourceType,
    IntegrationPattern,
    UserRole,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event_envelope(**kwargs: Any) -> EventEnvelope:
    """Return an EventEnvelope with sensible defaults, overridable via kwargs."""
    defaults: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "org_id": "org-test-001",
        "patient_id": "patient-abc",
        "resource_type": FhirResourceType.PATIENT,
        "event_type": "fhir.resource.created",
        "integration_pattern": IntegrationPattern.FHIR_API,
        "payload": {"resourceType": "Patient", "id": "p1"},
        "schema_version": "1.0",
        "correlation_id": str(uuid.uuid4()),
    }
    defaults.update(kwargs)
    return EventEnvelope(**defaults)


def _make_audit_entry(**kwargs: Any) -> AuditLogEntry:
    """Return an AuditLogEntry with sensible defaults, overridable via kwargs."""
    defaults: dict[str, Any] = {
        "timestamp": datetime.now(tz=timezone.utc),
        "accessor_id": "cognito-sub-xyz",
        "accessor_role": UserRole.CLINICAL_USER,
        "org_id": "org-test-001",
        "resource_type": "Patient",
        "resource_id": "patient-001",
        "operation": "read",
        "source_ip": "10.0.0.1",
        "allowed": True,
        "event_id": str(uuid.uuid4()),
    }
    defaults.update(kwargs)
    return AuditLogEntry(**defaults)


# ---------------------------------------------------------------------------
# EventEnvelope — unit tests
# ---------------------------------------------------------------------------

class TestEventEnvelopeRoundTrip:
    """Tests for EventEnvelope.to_dict() / from_dict() round-trip."""

    def test_to_dict_contains_required_keys(self) -> None:
        envelope = _make_event_envelope()
        d = envelope.to_dict()
        for key in ("eventId", "orgId", "patientId", "resourceType",
                    "eventType", "integrationPattern", "payload",
                    "timestamp", "schemaVersion", "correlationId"):
            assert key in d, f"Missing key: {key}"

    def test_round_trip_preserves_org_id(self) -> None:
        original = _make_event_envelope(org_id="hospital-42")
        restored = EventEnvelope.from_dict(original.to_dict())
        assert restored.org_id == "hospital-42"

    def test_round_trip_preserves_patient_id(self) -> None:
        original = _make_event_envelope(patient_id="patient-xyz")
        restored = EventEnvelope.from_dict(original.to_dict())
        assert restored.patient_id == "patient-xyz"

    def test_round_trip_preserves_resource_type(self) -> None:
        original = _make_event_envelope(resource_type=FhirResourceType.OBSERVATION)
        restored = EventEnvelope.from_dict(original.to_dict())
        assert restored.resource_type == FhirResourceType.OBSERVATION

    def test_round_trip_preserves_event_type(self) -> None:
        original = _make_event_envelope(event_type="hl7.message.received")
        restored = EventEnvelope.from_dict(original.to_dict())
        assert restored.event_type == "hl7.message.received"

    def test_round_trip_preserves_schema_version(self) -> None:
        original = _make_event_envelope(schema_version="2.0")
        restored = EventEnvelope.from_dict(original.to_dict())
        assert restored.schema_version == "2.0"

    def test_round_trip_with_none_patient_id(self) -> None:
        original = _make_event_envelope(patient_id=None)
        restored = EventEnvelope.from_dict(original.to_dict())
        assert restored.patient_id is None

    def test_round_trip_with_none_resource_type(self) -> None:
        original = _make_event_envelope(resource_type=None)
        restored = EventEnvelope.from_dict(original.to_dict())
        assert restored.resource_type is None

    def test_round_trip_payload_preserved(self) -> None:
        payload = {"resourceType": "Observation", "id": "obs-1", "status": "final"}
        original = _make_event_envelope(payload=payload)
        restored = EventEnvelope.from_dict(original.to_dict())
        assert restored.payload == payload

    def test_round_trip_timestamp_as_isoformat_string(self) -> None:
        original = _make_event_envelope()
        d = original.to_dict()
        # Timestamp must be a valid ISO-8601 string
        parsed = datetime.fromisoformat(d["timestamp"])
        assert parsed.tzinfo is not None  # must be timezone-aware

    def test_from_dict_generates_event_id_when_missing(self) -> None:
        d = _make_event_envelope().to_dict()
        del d["eventId"]
        restored = EventEnvelope.from_dict(d)
        assert len(restored.event_id) > 0


# ---------------------------------------------------------------------------
# TenantConfig — unit tests
# ---------------------------------------------------------------------------

class TestTenantConfigIsActive:
    """Tests for TenantConfig.is_active property."""

    def test_active_tenant_returns_true(self) -> None:
        tenant = TenantConfig(org_id="org-1", org_name="Test Hospital", status="active")
        assert tenant.is_active is True

    def test_suspended_tenant_returns_false(self) -> None:
        tenant = TenantConfig(org_id="org-2", org_name="Clinic B", status="suspended")
        assert tenant.is_active is False

    def test_deprovisioned_tenant_returns_false(self) -> None:
        tenant = TenantConfig(org_id="org-3", org_name="Old Org", status="deprovisioned")
        assert tenant.is_active is False

    def test_unknown_status_returns_false(self) -> None:
        tenant = TenantConfig(org_id="org-4", org_name="Unknown", status="unknown")
        assert tenant.is_active is False

    def test_default_status_is_active(self) -> None:
        tenant = TenantConfig(org_id="org-5", org_name="Default Org")
        assert tenant.is_active is True


# ---------------------------------------------------------------------------
# AuditLogEntry — unit tests
# ---------------------------------------------------------------------------

class TestAuditLogEntryRoundTrip:
    """Tests for AuditLogEntry.to_dict() / from_dict() round-trip."""

    def test_to_dict_contains_required_keys(self) -> None:
        entry = _make_audit_entry()
        d = entry.to_dict()
        for key in ("eventId", "timestamp", "accessorId", "accessorRole",
                    "orgId", "resourceType", "resourceId", "operation",
                    "sourceIp", "allowed"):
            assert key in d, f"Missing key: {key}"

    def test_round_trip_preserves_accessor_id(self) -> None:
        original = _make_audit_entry(accessor_id="user-abc-123")
        restored = AuditLogEntry.from_dict(original.to_dict())
        assert restored.accessor_id == "user-abc-123"

    def test_round_trip_preserves_org_id(self) -> None:
        original = _make_audit_entry(org_id="org-clinic-9")
        restored = AuditLogEntry.from_dict(original.to_dict())
        assert restored.org_id == "org-clinic-9"

    def test_round_trip_preserves_allowed_true(self) -> None:
        original = _make_audit_entry(allowed=True)
        restored = AuditLogEntry.from_dict(original.to_dict())
        assert restored.allowed is True

    def test_round_trip_preserves_allowed_false(self) -> None:
        original = _make_audit_entry(allowed=False)
        restored = AuditLogEntry.from_dict(original.to_dict())
        assert restored.allowed is False

    def test_round_trip_preserves_accessor_role(self) -> None:
        original = _make_audit_entry(accessor_role=UserRole.PLATFORM_ADMIN)
        restored = AuditLogEntry.from_dict(original.to_dict())
        assert restored.accessor_role == UserRole.PLATFORM_ADMIN

    def test_round_trip_preserves_operation(self) -> None:
        original = _make_audit_entry(operation="delete")
        restored = AuditLogEntry.from_dict(original.to_dict())
        assert restored.operation == "delete"

    def test_round_trip_preserves_source_ip(self) -> None:
        original = _make_audit_entry(source_ip="192.168.1.99")
        restored = AuditLogEntry.from_dict(original.to_dict())
        assert restored.source_ip == "192.168.1.99"

    def test_round_trip_timestamp_preserved(self) -> None:
        ts = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        original = _make_audit_entry(timestamp=ts)
        restored = AuditLogEntry.from_dict(original.to_dict())
        assert restored.timestamp == ts


# ---------------------------------------------------------------------------
# CanonicalMessage — unit tests
# ---------------------------------------------------------------------------

class TestCanonicalMessageSemanticEquivalence:
    """Tests for CanonicalMessage.is_semantically_equivalent()."""

    def test_identical_messages_are_equivalent(self) -> None:
        msg = CanonicalMessage(
            fhir_elements={"Patient.id": "p1", "Patient.birthDate": "1980-01-01"},
            segments=[{1: "PID", 3: "12345"}],
            extension_map={"PID-99": "custom_value"},
        )
        # Same object compared to itself
        assert msg.is_semantically_equivalent(msg) is True

    def test_equal_copies_are_equivalent(self) -> None:
        fhir = {"Observation.status": "final", "Observation.code": "12345-6"}
        segs = [{1: "OBX", 5: "7.2"}]
        ext = {}
        msg_a = CanonicalMessage(fhir_elements=fhir, segments=segs, extension_map=ext)
        msg_b = CanonicalMessage(fhir_elements=fhir.copy(), segments=list(segs), extension_map={})
        assert msg_a.is_semantically_equivalent(msg_b) is True

    def test_different_fhir_elements_not_equivalent(self) -> None:
        msg_a = CanonicalMessage(
            fhir_elements={"Patient.id": "p1"},
            segments=[],
            extension_map={},
        )
        msg_b = CanonicalMessage(
            fhir_elements={"Patient.id": "p2"},  # different value
            segments=[],
            extension_map={},
        )
        assert msg_a.is_semantically_equivalent(msg_b) is False

    def test_different_segments_not_equivalent(self) -> None:
        msg_a = CanonicalMessage(
            fhir_elements={},
            segments=[{1: "PID", 3: "111"}],
            extension_map={},
        )
        msg_b = CanonicalMessage(
            fhir_elements={},
            segments=[{1: "PID", 3: "999"}],  # different patient ID
            extension_map={},
        )
        assert msg_a.is_semantically_equivalent(msg_b) is False

    def test_different_extension_map_not_equivalent(self) -> None:
        msg_a = CanonicalMessage(
            fhir_elements={},
            segments=[],
            extension_map={"PID-99": "value_a"},
        )
        msg_b = CanonicalMessage(
            fhir_elements={},
            segments=[],
            extension_map={"PID-99": "value_b"},
        )
        assert msg_a.is_semantically_equivalent(msg_b) is False

    def test_empty_canonical_messages_are_equivalent(self) -> None:
        msg_a = CanonicalMessage()
        msg_b = CanonicalMessage()
        assert msg_a.is_semantically_equivalent(msg_b) is True


# ---------------------------------------------------------------------------
# Property-based tests — EventEnvelope
# ---------------------------------------------------------------------------

# Hypothesis strategy for printable non-empty strings (safe for org_id / patient_id)
_printable_text = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"),
    min_size=1,
    max_size=64,
)


@given(
    org_id=_printable_text,
    patient_id=_printable_text,
)
@settings(max_examples=100)
def test_event_envelope_round_trip_arbitrary_org_and_patient(
    org_id: str, patient_id: str
) -> None:
    """
    Property: For any org_id and patient_id string, EventEnvelope
    round-trips through to_dict() / from_dict() without data loss.
    """
    original = _make_event_envelope(org_id=org_id, patient_id=patient_id)
    restored = EventEnvelope.from_dict(original.to_dict())
    assert restored.org_id == org_id
    assert restored.patient_id == patient_id


@given(
    org_id=_printable_text,
    event_type=st.sampled_from([
        "fhir.resource.created",
        "fhir.resource.updated",
        "hl7.message.received",
        "healthlake.resource.persisted",
        "file.processed.complete",
    ]),
)
@settings(max_examples=50)
def test_event_envelope_event_type_preserved_after_round_trip(
    org_id: str, event_type: str
) -> None:
    """
    Property: event_type is always preserved through a to_dict() / from_dict() cycle.
    """
    original = _make_event_envelope(org_id=org_id, event_type=event_type)
    restored = EventEnvelope.from_dict(original.to_dict())
    assert restored.event_type == event_type


@given(
    schema_version=st.sampled_from(["1.0", "2.0", "1.1"]),
)
@settings(max_examples=30)
def test_event_envelope_schema_version_preserved(schema_version: str) -> None:
    """
    Property: schema_version survives the round-trip unchanged.
    """
    original = _make_event_envelope(schema_version=schema_version)
    restored = EventEnvelope.from_dict(original.to_dict())
    assert restored.schema_version == schema_version
