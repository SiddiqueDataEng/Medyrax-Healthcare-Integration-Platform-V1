package com.Medyrax.common.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.annotation.JsonDeserialize;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.datatype.jsr310.deser.LocalDateDeserializer;
import com.fasterxml.jackson.datatype.jsr310.ser.LocalDateSerializer;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

/**
 * Canonical representation of a patient, used as the intermediate model when
 * converting between HL7 v2.x PID/PD1 segments and FHIR R4 Patient resources.
 *
 * <p>All fields are nullable — callers must check presence before use.
 * Unmapped HL7 fields are captured in the parent {@link CanonicalMessage#getExtensionMap()}.
 *
 * <p>Maps to:
 * <ul>
 *   <li>HL7 PID segment fields</li>
 *   <li>FHIR R4 {@code Patient} resource elements</li>
 * </ul>
 *
 * <p>Requirement 13.1 / 13.2 — canonical model must capture all patient fields
 * so round-trip parse/serialize/parse produces semantically equivalent output.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class CanonicalPatient {

    // ── Identifiers ──────────────────────────────────────────────────────────
    /** PID-3 / Patient.identifier — primary patient identifier (MRN or similar). */
    private String patientId;

    /** PID-3 alternate identifiers / Patient.identifier list. */
    @Builder.Default
    private List<CanonicalIdentifier> identifiers = new ArrayList<>();

    // ── Demographics ─────────────────────────────────────────────────────────
    /** PID-5 / Patient.name — family name (last name). */
    private String familyName;

    /** PID-5 / Patient.name — given name(s). */
    @Builder.Default
    private List<String> givenNames = new ArrayList<>();

    /** PID-5 / Patient.name — name prefix (e.g. "Dr."). */
    private String namePrefix;

    /** PID-5 / Patient.name — name suffix (e.g. "Jr."). */
    private String nameSuffix;

    /** PID-7 / Patient.birthDate — date of birth. */
    @JsonSerialize(using = LocalDateSerializer.class)
    @JsonDeserialize(using = LocalDateDeserializer.class)
    private LocalDate birthDate;

    /** PID-8 / Patient.gender — administrative gender (male|female|other|unknown). */
    private String gender;

    /** PID-11 / Patient.address — street line 1. */
    private String addressLine1;

    /** PID-11 / Patient.address — street line 2. */
    private String addressLine2;

    /** PID-11 / Patient.address — city. */
    private String city;

    /** PID-11 / Patient.address — state/province. */
    private String state;

    /** PID-11 / Patient.address — postal code. */
    private String postalCode;

    /** PID-11 / Patient.address — country. */
    private String country;

    // ── Contact ──────────────────────────────────────────────────────────────
    /** PID-13 / Patient.telecom — home phone number. */
    private String homePhone;

    /** PID-14 / Patient.telecom — work phone number. */
    private String workPhone;

    /** PID-13.4 email / Patient.telecom — email address. */
    private String email;

    // ── Clinical ─────────────────────────────────────────────────────────────
    /** PID-10 / Patient.extension — race code (HL7 table 0005). */
    private String race;

    /** PID-22 / Patient.extension — ethnic group code. */
    private String ethnicGroup;

    /** PID-28 / Patient.communication — primary language code. */
    private String primaryLanguage;

    /** PID-30 / Patient.deceased — patient death indicator ("Y"/"N"). */
    private String deathIndicator;

    /** PID-29 / Patient.deceasedDateTime — date/time of death (ISO-8601). */
    private String deathDateTime;

    /** PD1-3 / Patient.managingOrganization — organization identifier. */
    private String managingOrganizationId;

    // ── Status ───────────────────────────────────────────────────────────────
    /** FHIR Patient.active — whether the patient record is active. */
    @Builder.Default
    private boolean active = true;
}
