package com.Medyrax.common.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * Canonical representation of a clinical encounter.
 *
 * <p>Maps to HL7 PV1/PV2 segments and FHIR R4 {@code Encounter} resource.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class CanonicalEncounter {

    /** PV1-19 / Encounter.identifier — visit number. */
    private String visitNumber;

    /** PV1-2 / Encounter.class — patient class (I=inpatient, O=outpatient, E=emergency). */
    private String patientClass;

    /** PV1-3 / Encounter.location — assigned patient location (point of care). */
    private String assignedLocation;

    /** PV1-4 / Encounter.type — admission type (E=emergency, U=urgent, etc.). */
    private String admissionType;

    /** PV1-7 / Encounter.participant — attending doctor NPI/ID. */
    private String attendingDoctorId;

    /** PV1-8 / Encounter.participant — referring doctor NPI/ID. */
    private String referringDoctorId;

    /** PV1-9 / Encounter.participant — consulting doctor NPI/ID. */
    private String consultingDoctorId;

    /** PV1-10 / Encounter.serviceType — hospital service code. */
    private String hospitalService;

    /** PV1-44 / Encounter.period.start — admit date/time (ISO-8601). */
    private String admitDateTime;

    /** PV1-45 / Encounter.period.end — discharge date/time (ISO-8601). */
    private String dischargeDateTime;

    /** PV1-36 / Encounter.hospitalization.dischargeDisposition — discharge disposition code. */
    private String dischargeDisposition;

    /** PV2-3 / Encounter.reasonCode — admit reason text. */
    private String admitReason;

    /** Encounter.status — planned|arrived|triaged|in-progress|onleave|finished|cancelled. */
    private String status;

    /** Encounter.subject.reference — patient ID. */
    private String patientId;

    /** Diagnosis codes associated with this encounter. */
    @Builder.Default
    private List<CanonicalDiagnosis> diagnoses = new ArrayList<>();
}
