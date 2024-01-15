package com.Medyrax.common.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * Canonical representation of a clinical observation, used when converting
 * between HL7 v2.x OBX segments and FHIR R4 Observation resources.
 *
 * <p>Maps to:
 * <ul>
 *   <li>HL7 OBX segment fields (OBX-2 through OBX-16)</li>
 *   <li>FHIR R4 {@code Observation} resource elements</li>
 * </ul>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class CanonicalObservation {

    /** OBX-1 / set ID. */
    private Integer setId;

    /** OBX-2 / value type (NM, ST, CWE, etc.). */
    private String valueType;

    /** OBX-3 / Observation.code — observation identifier (LOINC code). */
    private String codeSystem;

    /** OBX-3.1 / Observation.code.coding[0].code. */
    private String code;

    /** OBX-3.2 / Observation.code.coding[0].display. */
    private String codeDisplay;

    // ── Value[x] ─────────────────────────────────────────────────────────────
    /** OBX-5 / Observation.valueQuantity.value (if numeric). */
    private Double numericValue;

    /** OBX-5 / Observation.valueString (if string). */
    private String stringValue;

    /** OBX-5 / Observation.valueCodeableConcept.coding[0].code (if coded). */
    private String codedValue;

    /** OBX-6 / Observation.valueQuantity.unit — units of measure (UCUM). */
    private String unit;

    /** OBX-6 / Observation.valueQuantity.system — unit system URI. */
    private String unitSystem;

    // ── Reference range ───────────────────────────────────────────────────────
    /** OBX-7 / Observation.referenceRange.text — reference range string. */
    private String referenceRange;

    /** OBX-8 / Observation.interpretation — abnormal flags (N, A, H, L, etc.). */
    private String abnormalFlag;

    /** OBX-11 / Observation.status — result status (F=final, P=preliminary, etc.). */
    private String status;

    /** OBX-14 / Observation.effectiveDateTime — ISO-8601 date/time of observation. */
    private String effectiveDateTime;

    /** OBX-15 / Observation.performer — producer identifier. */
    private String producerId;

    /** OBX-16 / Observation.performer — responsible observer. */
    private String responsibleObserverId;

    /** OBX-23 / Observation.performer (organization) — performing organization name. */
    private String performingOrganizationName;

    // ── Components (for multi-value observations) ─────────────────────────────
    /** Observation.component — for multi-component observations (e.g. blood pressure). */
    @Builder.Default
    private List<CanonicalObservation> components = new ArrayList<>();

    // ── Subject ───────────────────────────────────────────────────────────────
    /** Observation.subject.reference — patient resource reference. */
    private String patientId;

    /** Observation.encounter.reference — encounter resource reference. */
    private String encounterId;
}
