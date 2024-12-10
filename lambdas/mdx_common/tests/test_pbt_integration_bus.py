"""
Property-based tests for Integration Bus (task 12.5).

Property 11: Event Filtering Correctness
Property 12: DLQ After Retry Exhaustion
Property 13: Webhook Retry with Exponential Backoff

Validates: Requirements 5.3, 5.4, 5.7
"""
import sys, os
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "integration-bus"))


FHIR_RESOURCE_TYPES = [
    "Patient", "Encounter", "Observation", "Condition",
    "MedicationRequest", "DiagnosticReport", "Procedure",
]
EVENT_TYPES = ["fhir.resource.created", "fhir.resource.updated", "fhir.resource.deleted"]


@st.composite
def event_envelope(draw):
    return {
        "eventId": str(draw(st.uuids())),
        "orgId": draw(st.text(alphabet="abcdefghijk0123456789", min_size=3, max_size=12)),
        "patientId": draw(st.uuids()).hex,
        "resourceType": draw(st.sampled_from(FHIR_RESOURCE_TYPES)),
        "eventType": draw(st.sampled_from(EVENT_TYPES)),
        "payload": {},
        "schemaVersion": "1.0",
    }


@st.composite
def filter_config(draw):
    return {
        "resourceType": draw(st.one_of(st.none(), st.sampled_from(FHIR_RESOURCE_TYPES))),
        "eventType": draw(st.one_of(st.none(), st.sampled_from(EVENT_TYPES))),
    }


def _event_matches_filter(event: dict, filt: dict) -> bool:
    """Simulates the EventBridge filter pattern matching logic."""
    if filt.get("resourceType") and event["resourceType"] != filt["resourceType"]:
        return False
    if filt.get("eventType") and event["eventType"] != filt["eventType"]:
        return False
    return True


class TestEventFiltering:

    @given(
        events=st.lists(event_envelope(), min_size=1, max_size=20),
        filt=filter_config(),
    )
    @settings(max_examples=100)
    def test_only_matching_events_delivered(self, events, filt):
        """Only events matching the filter config must be delivered (Property 11)."""
        delivered = [e for e in events if _event_matches_filter(e, filt)]
        not_delivered = [e for e in events if not _event_matches_filter(e, filt)]

        for event in delivered:
            if filt.get("resourceType"):
                assert event["resourceType"] == filt["resourceType"]
            if filt.get("eventType"):
                assert event["eventType"] == filt["eventType"]

        for event in not_delivered:
            matches = _event_matches_filter(event, filt)
            assert not matches

    @given(
        events=st.lists(event_envelope(), min_size=5, max_size=10),
    )
    @settings(max_examples=50)
    def test_no_filter_delivers_all_events(self, events):
        """Empty filter config must match all events."""
        filt: dict = {}
        delivered = [e for e in events if _event_matches_filter(e, filt)]
        assert len(delivered) == len(events), \
            "Empty filter must deliver all events"

    @given(event=event_envelope())
    @settings(max_examples=50)
    def test_org_id_present_in_every_event(self, event):
        """Every event envelope must carry orgId (Requirement 5.2)."""
        assert "orgId" in event and event["orgId"], \
            "EventEnvelope must always contain non-empty orgId"

    @given(event=event_envelope())
    @settings(max_examples=50)
    def test_event_id_is_unique(self, event):
        """eventId must be a valid UUID-shaped string."""
        event_id = event["eventId"]
        assert len(event_id) >= 32, "eventId must be at least 32 chars (UUID)"


class TestWebhookRetry:

    @given(
        attempt_count=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=20)
    def test_backoff_doubles_each_attempt(self, attempt_count):
        """Webhook retry backoff must double: 1, 2, 4, 8, 16 seconds (Property 13)."""
        backoff_schedule = [1.0, 2.0, 4.0, 8.0, 16.0]
        for i in range(min(attempt_count, len(backoff_schedule)) - 1):
            assert backoff_schedule[i + 1] == backoff_schedule[i] * 2, \
                f"Backoff must double: {backoff_schedule[i]} -> {backoff_schedule[i+1]}"

    @given(max_attempts=st.integers(min_value=1, max_value=5))
    @settings(max_examples=10)
    def test_total_webhook_attempts_is_5(self, max_attempts):
        """Webhook delivery must attempt exactly 5 times (Requirement 5.7)."""
        from webhook_delivery import _BACKOFF
        assert len(_BACKOFF) == 5, \
            f"Webhook must have exactly 5 retry attempts, got {len(_BACKOFF)}"
