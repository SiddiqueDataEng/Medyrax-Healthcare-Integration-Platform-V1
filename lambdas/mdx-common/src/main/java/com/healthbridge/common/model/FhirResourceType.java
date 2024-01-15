package com.Medyrax.common.model;

/**
 * Enumeration of FHIR R4 resource types supported by the Medyrax™ platform.
 *
 * <p>Requirements 1.4: The FHIR_Engine SHALL support all FHIR R4 resource types
 * required for core clinical workflows: Patient, Practitioner, Organization, Encounter,
 * Observation, Condition, MedicationRequest, DiagnosticReport, AllergyIntolerance,
 * Procedure, and Coverage.
 *
 * <p>Additional resource types are included for the extended platform workflows
 * (telehealth, CDS, analytics, etc.).
 */
public enum FhirResourceType {

    // ── Core clinical workflow resource types (Requirement 1.4) ─────────────
    PATIENT("Patient"),
    PRACTITIONER("Practitioner"),
    ORGANIZATION("Organization"),
    ENCOUNTER("Encounter"),
    OBSERVATION("Observation"),
    CONDITION("Condition"),
    MEDICATION_REQUEST("MedicationRequest"),
    DIAGNOSTIC_REPORT("DiagnosticReport"),
    ALLERGY_INTOLERANCE("AllergyIntolerance"),
    PROCEDURE("Procedure"),
    COVERAGE("Coverage"),

    // ── Extended resource types used by platform subsystems ─────────────────
    BUNDLE("Bundle"),
    DOCUMENT_REFERENCE("DocumentReference"),
    APPOINTMENT("Appointment"),
    RISK_ASSESSMENT("RiskAssessment"),
    CLINICAL_IMPRESSION("ClinicalImpression"),
    MEDICATION("Medication"),
    MEDICATION_ADMINISTRATION("MedicationAdministration"),
    MEDICATION_STATEMENT("MedicationStatement"),
    IMMUNIZATION("Immunization"),
    MESSAGE_HEADER("MessageHeader"),
    OPERATION_OUTCOME("OperationOutcome"),
    CAPABILITY_STATEMENT("CapabilityStatement"),
    CONCEPT_MAP("ConceptMap"),
    CODE_SYSTEM("CodeSystem"),
    VALUE_SET("ValueSet"),
    PATIENT_EVERYTHING("Patient/$everything");

    /** The FHIR resource type string as used in resource JSON and REST paths. */
    private final String typeName;

    FhirResourceType(String typeName) {
        this.typeName = typeName;
    }

    public String getTypeName() {
        return typeName;
    }

    /**
     * Returns the {@link FhirResourceType} matching the given type name string,
     * performing a case-insensitive match against the FHIR type name.
     *
     * @param typeName the FHIR resource type string (e.g. "Patient", "Observation")
     * @return matching enum constant
     * @throws IllegalArgumentException if no match is found
     */
    public static FhirResourceType fromTypeName(String typeName) {
        if (typeName == null || typeName.isBlank()) {
            throw new IllegalArgumentException("FHIR resource type name must not be null or blank");
        }
        for (FhirResourceType t : values()) {
            if (t.typeName.equalsIgnoreCase(typeName)) {
                return t;
            }
        }
        throw new IllegalArgumentException("Unknown FHIR resource type: " + typeName);
    }

    /**
     * Returns {@code true} if this resource type is one of the 11 core clinical
     * workflow types required by Requirement 1.4.
     */
    public boolean isCoreWorkflowType() {
        return switch (this) {
            case PATIENT, PRACTITIONER, ORGANIZATION, ENCOUNTER, OBSERVATION,
                 CONDITION, MEDICATION_REQUEST, DIAGNOSTIC_REPORT,
                 ALLERGY_INTOLERANCE, PROCEDURE, COVERAGE -> true;
            default -> false;
        };
    }

    @Override
    public String toString() {
        return typeName;
    }
}
