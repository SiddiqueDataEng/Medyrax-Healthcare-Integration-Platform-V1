package com.Medyrax.common.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Canonical representation of a clinical identifier (e.g. MRN, NPI, UPIN).
 *
 * <p>Maps to FHIR R4 {@code Identifier} type and to HL7 CX composite field.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class CanonicalIdentifier {

    /**
     * The identifier value — e.g. "12345678", "1234567890" (NPI), "A1B2C3" (MRN).
     * Maps to: FHIR Identifier.value / HL7 CX.1
     */
    private String value;

    /**
     * The identifier system URI — e.g. "http://hospital.example/mrn",
     * "http://hl7.org/fhir/sid/us-npi".
     * Maps to: FHIR Identifier.system / HL7 CX.4 (assigning authority)
     */
    private String system;

    /**
     * The identifier type code — e.g. "MR" (Medical Record), "NPI", "SS" (SSN).
     * Maps to: FHIR Identifier.type.coding[0].code / HL7 CX.5 (identifier type code)
     */
    private String typeCode;

    /**
     * Human-readable display for the identifier type.
     * Maps to: FHIR Identifier.type.text
     */
    private String typeDisplay;

    /**
     * Use context — usual|official|temp|secondary|old.
     * Maps to: FHIR Identifier.use
     */
    private String use;

    /**
     * Assigning authority name (HL7 CX.4.1).
     */
    private String assigningAuthority;
}
