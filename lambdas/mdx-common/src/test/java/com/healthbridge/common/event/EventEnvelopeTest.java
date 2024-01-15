package com.Medyrax.common.event;

import com.Medyrax.common.util.JsonUtil;
import net.jqwik.api.*;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.UUID;

import static org.assertj.core.api.Assertions.*;

/**
 * Unit and property-based tests for {@link EventEnvelope}.
 */
class EventEnvelopeTest {

    @Test
    void builder_setsDefaultTimestamp() {
        Instant before = Instant.now();
        EventEnvelope envelope = EventEnvelope.builder()
                .eventId(UUID.randomUUID().toString())
                .orgId("org-001")
                .eventType(EventType.FHIR_RESOURCE_CREATED)
                .build();
        Instant after = Instant.now();

        assertThat(envelope.getTimestamp())
                .isAfterOrEqualTo(before)
                .isBeforeOrEqualTo(after);
    }

    @Test
    void builder_setsDefaultSchemaVersion() {
        EventEnvelope envelope = EventEnvelope.builder().build();
        assertThat(envelope.getSchemaVersion()).isEqualTo("1.0");
    }

    @Test
    void jsonRoundTrip_preservesAllFields() {
        String eventId = UUID.randomUUID().toString();
        EventEnvelope original = EventEnvelope.builder()
                .eventId(eventId)
                .orgId("org-hosp-123")
                .patientId("pat-456")
                .resourceType("Observation")
                .eventType(EventType.FHIR_RESOURCE_CREATED)
                .severity("HIGH")
                .correlationId("corr-789")
                .build();

        String json = JsonUtil.toJson(original);
        EventEnvelope deserialized = JsonUtil.fromJson(json, EventEnvelope.class);

        assertThat(deserialized.getEventId()).isEqualTo(eventId);
        assertThat(deserialized.getOrgId()).isEqualTo("org-hosp-123");
        assertThat(deserialized.getPatientId()).isEqualTo("pat-456");
        assertThat(deserialized.getResourceType()).isEqualTo("Observation");
        assertThat(deserialized.getEventType()).isEqualTo(EventType.FHIR_RESOURCE_CREATED);
        assertThat(deserialized.getSeverity()).isEqualTo("HIGH");
    }

    /**
     * Property: For any EventEnvelope serialized to JSON and deserialized back,
     * the eventId, orgId, and eventType must be preserved (basic round-trip integrity).
     */
    @Property(tries = 100)
    void jsonRoundTrip_eventIdAndOrgIdPreserved(
            @ForAll @StringLength(min = 1, max = 50) String eventId,
            @ForAll @StringLength(min = 1, max = 50) String orgId,
            @ForAll @StringLength(min = 1, max = 50) String eventType) {

        EventEnvelope original = EventEnvelope.builder()
                .eventId(eventId)
                .orgId(orgId)
                .eventType(eventType)
                .build();

        String json = JsonUtil.toJson(original);
        EventEnvelope deserialized = JsonUtil.fromJson(json, EventEnvelope.class);

        assertThat(deserialized.getEventId()).isEqualTo(eventId);
        assertThat(deserialized.getOrgId()).isEqualTo(orgId);
        assertThat(deserialized.getEventType()).isEqualTo(eventType);
    }
}
