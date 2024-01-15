package com.Medyrax.common.model;

import net.jqwik.api.*;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.*;

/**
 * Unit and property-based tests for {@link FhirResourceType}.
 *
 * <p>These tests verify the enum structure, lookup correctness, and the
 * core workflow type classification used throughout the platform.
 */
class FhirResourceTypeTest {

    // ── Unit Tests ────────────────────────────────────────────────────────────

    /** All 11 required core workflow types from Requirement 1.4 must be present. */
    @Test
    void allCoreWorkflowTypesAreDefined() {
        List<String> required = Arrays.asList(
                "Patient", "Practitioner", "Organization", "Encounter",
                "Observation", "Condition", "MedicationRequest", "DiagnosticReport",
                "AllergyIntolerance", "Procedure", "Coverage"
        );

        for (String typeName : required) {
            FhirResourceType type = FhirResourceType.fromTypeName(typeName);
            assertThat(type.isCoreWorkflowType())
                    .as("Expected %s to be a core workflow type", typeName)
                    .isTrue();
        }
    }

    @Test
    void fromTypeName_isCaseInsensitive() {
        assertThat(FhirResourceType.fromTypeName("patient"))
                .isEqualTo(FhirResourceType.PATIENT);
        assertThat(FhirResourceType.fromTypeName("OBSERVATION"))
                .isEqualTo(FhirResourceType.OBSERVATION);
        assertThat(FhirResourceType.fromTypeName("medicationRequest"))
                .isEqualTo(FhirResourceType.MEDICATION_REQUEST);
    }

    @Test
    void fromTypeName_throwsForUnknownType() {
        assertThatThrownBy(() -> FhirResourceType.fromTypeName("UnknownResource"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("UnknownResource");
    }

    @Test
    void fromTypeName_throwsForNullOrBlank() {
        assertThatThrownBy(() -> FhirResourceType.fromTypeName(null))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> FhirResourceType.fromTypeName(""))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> FhirResourceType.fromTypeName("   "))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void toStringReturnsTypeName() {
        assertThat(FhirResourceType.PATIENT.toString()).isEqualTo("Patient");
        assertThat(FhirResourceType.MEDICATION_REQUEST.toString()).isEqualTo("MedicationRequest");
    }

    // ── Property-Based Tests (jqwik) ──────────────────────────────────────────

    /**
     * Property: For any valid FhirResourceType enum constant, fromTypeName(type.getTypeName())
     * must return the same enum constant (round-trip lookup).
     */
    @Property(tries = 100)
    void fromTypeName_roundTrip(@ForAll("validFhirResourceTypes") FhirResourceType type) {
        FhirResourceType resolved = FhirResourceType.fromTypeName(type.getTypeName());
        assertThat(resolved).isEqualTo(type);
    }

    /**
     * Property: Exactly 11 FhirResourceType constants must be classified as core
     * workflow types (Requirement 1.4). This is a count invariant.
     */
    @Property(tries = 1)
    void exactlyElevenCoreWorkflowTypes() {
        long coreCount = Arrays.stream(FhirResourceType.values())
                .filter(FhirResourceType::isCoreWorkflowType)
                .count();
        assertThat(coreCount)
                .as("Requirement 1.4 defines exactly 11 core workflow resource types")
                .isEqualTo(11);
    }

    /**
     * Property: For any non-null, non-blank string that is not a known FHIR resource type name,
     * fromTypeName must throw IllegalArgumentException.
     *
     * <p>We test this by generating arbitrary strings that don't match any type name.
     */
    @Property(tries = 100)
    void fromTypeName_throwsForUnknownArbitraryStrings(
            @ForAll("unknownTypeNames") String unknownName) {
        assertThatThrownBy(() -> FhirResourceType.fromTypeName(unknownName))
                .isInstanceOf(IllegalArgumentException.class);
    }

    // ── Providers ─────────────────────────────────────────────────────────────

    @Provide
    Arbitrary<FhirResourceType> validFhirResourceTypes() {
        return Arbitraries.of(FhirResourceType.values());
    }

    /**
     * Generates strings that are known NOT to be valid FHIR resource type names.
     * We prefix with "UNKNOWN_" to guarantee no accidental match.
     */
    @Provide
    Arbitrary<String> unknownTypeNames() {
        return Arbitraries.strings()
                .alpha()
                .ofMinLength(1)
                .ofMaxLength(30)
                .map(s -> "UNKNOWN_" + s);
    }
}
