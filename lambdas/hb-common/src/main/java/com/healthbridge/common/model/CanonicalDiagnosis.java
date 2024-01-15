package com.Medyrax.common.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Canonical representation of a clinical diagnosis.
 *
 * <p>Maps to HL7 DG1 segment and FHIR R4 {@code Condition} resource
 * (also used as Encounter.diagnosis reference).
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class CanonicalDiagnosis {

    /** DG1-1 / set ID. */
    private Integer setId;

    /** DG1-2 / diagnosis coding method — ICD-10, SNOMED, etc. */
    private String codingMethod;

    /** DG1-3.1 / Condition.code.coding[0].code — diagnosis code (e.g. ICD-10: "I21.0"). */
    private String code;

    /** DG1-3.3 / Condition.code.coding[0].display — diagnosis description. */
    private String description;

    /** DG1-3.4 / Condition.code.coding[0].system — code system URI. */
    private String codeSystem;

    /** DG1-4 / Condition.code.text — free-text diagnosis description. */
    private String freeTextDescription;

    /** DG1-5 / Condition.onsetDateTime — diagnosis date/time (ISO-8601). */
    private String diagnosisDateTime;

    /** DG1-6 / diagnosis type: A=admitting, W=working, F=final. */
    private String diagnosisType;

    /** DG1-15 / Condition.clinicalStatus — diagnosis priority/rank. */
    private Integer rank;

    /** Condition.subject.reference — patient ID. */
    private String patientId;

    /** Condition.encounter.reference — encounter ID. */
    private String encounterId;

    /** Condition.verificationStatus — unconfirmed|provisional|differential|confirmed|refuted. */
    private String verificationStatus;

    /** Condition.clinicalStatus — active|recurrence|relapse|inactive|remission|resolved. */
    private String clinicalStatus;
}
