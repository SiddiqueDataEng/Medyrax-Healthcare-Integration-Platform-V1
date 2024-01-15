package com.Medyrax.common.event;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.JsonNode;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;

/**
 * Standard event envelope published to the Medyrax™ Integration Bus
 * (AWS EventBridge + SQS FIFO).
 *
 * <p>Requirement 5.1 — all events published to EventBridge use this envelope.
 * Requirement 5.5 — the SQS FIFO MessageGroupId is set to {@link #patientId};
 *                   the MessageDeduplicationId is set to {@link #eventId}.
 *
 * <p>Design reference (Integration Bus section):
 * "Java utility class used by all Lambda functions to publish events with
 * standard envelope: {eventId, orgId, patientId, resourceType, eventType,
 * payload, timestamp}"
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class EventEnvelope {

    /**
     * Globally unique event ID (UUID v4).
     * Used as SQS FIFO MessageDeduplicationId.
     */
    private String eventId;

    /**
     * Connected_Organization tenant identifier.
     * Used for EventBridge routing rules and tenant isolation.
     */
    private String orgId;

    /**
     * Patient identifier — used as SQS FIFO MessageGroupId for per-patient ordering.
     * May be null for non-patient-specific events (e.g. terminology refreshes).
     */
    private String patientId;

    /**
     * FHIR resource type of the payload (e.g. "Patient", "Observation").
     * Used by EventBridge routing rules (Requirement 5.3).
     */
    private String resourceType;

    /**
     * Event type qualifier:
     * <ul>
     *   <li>{@code fhir.resource.created}</li>
     *   <li>{@code fhir.resource.updated}</li>
     *   <li>{@code fhir.resource.deleted}</li>
     *   <li>{@code hl7.message.received}</li>
     *   <li>{@code healthlake.resource.persisted}</li>
     *   <li>{@code healthlake.resource.failed}</li>
     *   <li>{@code healthlake.export.complete}</li>
     *   <li>{@code file.processed.complete}</li>
     *   <li>{@code workflow.completed.*}</li>
     *   <li>{@code alert.clinical.*}</li>
     *   <li>{@code alert.model.unavailable}</li>
     *   <li>{@code audit.*}</li>
     * </ul>
     */
    private String eventType;

    /**
     * The event payload — typically a FHIR R4 resource JSON node,
     * a transformation audit record, or a file processing summary.
     */
    private JsonNode payload;

    /** Correlation ID linking related events in an X-Ray trace. */
    private String correlationId;

    /**
     * FHIR resource ID (HealthLake logical ID) — populated after persistence.
     */
    private String fhirResourceId;

    /** HealthLake datastore ID for the tenant. */
    private String healthLakeDataStoreId;

    /** Severity level for clinical alert events: LOW, MEDIUM, HIGH, CRITICAL. */
    private String severity;

    /** ISO-8601 timestamp when the event was created by the publisher. */
    @Builder.Default
    private Instant timestamp = Instant.now();

    /**
     * Schema version of this envelope — used by consumers to handle
     * backward-compatible envelope changes.
     */
    @Builder.Default
    private String schemaVersion = "1.0";
}
