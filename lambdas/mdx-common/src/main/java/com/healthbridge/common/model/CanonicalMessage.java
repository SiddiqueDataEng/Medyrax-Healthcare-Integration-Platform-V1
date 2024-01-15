package com.Medyrax.common.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

/**
 * Top-level canonical message model — the language-neutral intermediate
 * representation used by the Data Mapper when converting between HL7 v2.x
 * and FHIR R4 formats.
 *
 * <p>Design reference (Data Mapper section):
 * "Language-neutral intermediate representation (Java POJO) that captures
 * all HL7 and FHIR elements."
 *
 * <p>Requirements 13.1, 13.2 — the canonical model must capture all
 * segments/fields so that round-trip parse/serialize/parse produces a
 * semantically equivalent result.
 *
 * <p>Unmapped HL7 fields (Requirement 2.4) are preserved in {@link #extensionMap}
 * with keys of the form {@code "hl7-unmapped-{SEGMENT}-{fieldIndex}"}.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class CanonicalMessage {

    // ── Message header (MSH) ─────────────────────────────────────────────────
    /** MSH-9 / MessageHeader — message type (e.g. "ADT_A01", "ORU_R01"). */
    private String messageType;

    /** MSH-9.2 / trigger event (e.g. "A01", "R01"). */
    private String triggerEvent;

    /** MSH-10 / MessageHeader.id — message control ID (globally unique per sender). */
    private String messageControlId;

    /** MSH-7 / MessageHeader.timestamp — date/time message was created (ISO-8601). */
    private Instant messageTimestamp;

    /** MSH-3 / MessageHeader.source.name — sending application. */
    private String sendingApplication;

    /** MSH-4 / MessageHeader.source.software — sending facility. */
    private String sendingFacility;

    /** MSH-5 / MessageHeader.destination.name — receiving application. */
    private String receivingApplication;

    /** MSH-6 / MessageHeader.destination — receiving facility. */
    private String receivingFacility;

    /** MSH-11 / processing ID (P=production, T=test, D=debug). */
    private String processingId;

    /** MSH-12 / HL7 version ID (e.g. "2.5", "2.8"). */
    private String hl7Version;

    // ── Clinical payload ─────────────────────────────────────────────────────
    /** Patient demographics (from PID/PD1 segments). */
    private CanonicalPatient patient;

    /** Encounter information (from PV1/PV2 segments). */
    private CanonicalEncounter encounter;

    /** Primary observation (from OBX segment; for ORU messages). */
    private CanonicalObservation observation;

    // ── Provenance ───────────────────────────────────────────────────────────
    /** Connected_Organization tenant identifier — injected during message ingestion. */
    private String orgId;

    /** FHIR resource ID assigned by the server after successful persistence. */
    private String fhirResourceId;

    /** FHIR resource type after conversion. */
    private FhirResourceType fhirResourceType;

    // ── Unmapped field preservation (Requirement 2.4) ────────────────────────
    /**
     * Map of unmapped HL7 fields, keyed as {@code "hl7-unmapped-{SEGMENT}-{fieldIndex}"}.
     * Requirement 2.4: unmapped data SHALL be preserved in a FHIR Extension element.
     * This map feeds the FHIR Extension generation in CanonicalToFHIRSerializer.
     */
    @Builder.Default
    private Map<String, String> extensionMap = new HashMap<>();

    // ── Raw payload (for audit / replay) ─────────────────────────────────────
    /** SHA-256 hash of the original source message or resource, used in transformation audit. */
    private String sourceSha256;

    /** Original raw HL7 message string, retained for audit purposes. */
    private String rawHl7;

    /**
     * Adds an unmapped HL7 field to the extension map.
     *
     * @param segmentName  HL7 segment name (e.g. "PID", "OBX")
     * @param fieldIndex   1-based field index within the segment
     * @param value        the raw field value
     */
    public void addUnmappedField(String segmentName, int fieldIndex, String value) {
        if (value != null && !value.isBlank()) {
            extensionMap.put(
                    "hl7-unmapped-" + segmentName.toUpperCase() + "-" + fieldIndex,
                    value
            );
        }
    }
}
