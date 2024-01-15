package com.Medyrax.common.error;

/**
 * Exception thrown when an HL7 v2.x message fails to parse.
 *
 * <p>Requirement 2.5: If an HL7 v2.x message fails parsing due to a malformed
 * segment, the HL7_Adapter SHALL return an NAK acknowledgment with error code AE
 * and a human-readable description of the parsing failure.
 *
 * <p>The {@link #getHumanReadableDescription()} value is used directly as the
 * error description in the NAK ERR segment.
 */
public class Hl7ParseException extends MedyraxException {

    /** NAK error code — AE (Application Error) as per HL7 Table 0357. */
    public static final String NAK_ERROR_CODE = "AE";

    private final String segment;
    private final int fieldIndex;
    private final String humanReadableDescription;

    /**
     * Constructs an HL7 parse exception.
     *
     * @param segment                  the HL7 segment that caused the failure (e.g. "PID")
     * @param fieldIndex               1-based field index within the segment (0 if unknown)
     * @param humanReadableDescription human-readable description for the NAK ERR segment
     */
    public Hl7ParseException(String segment, int fieldIndex, String humanReadableDescription) {
        super(ErrorCode.HL7_PARSE_FAILURE,
                "HL7 parse failure in segment " + segment + " field " + fieldIndex
                + ": " + humanReadableDescription);
        this.segment = segment;
        this.fieldIndex = fieldIndex;
        this.humanReadableDescription = humanReadableDescription;
    }

    public Hl7ParseException(String segment, int fieldIndex, String humanReadableDescription,
                              Throwable cause) {
        super(ErrorCode.HL7_PARSE_FAILURE,
                "HL7 parse failure in segment " + segment + " field " + fieldIndex
                + ": " + humanReadableDescription, cause);
        this.segment = segment;
        this.fieldIndex = fieldIndex;
        this.humanReadableDescription = humanReadableDescription;
    }

    /** The HL7 segment name where parsing failed, e.g. "MSH", "PID", "OBX". */
    public String getSegment() {
        return segment;
    }

    /** 1-based field index that caused the failure, or 0 if the segment itself is malformed. */
    public int getFieldIndex() {
        return fieldIndex;
    }

    /**
     * Human-readable error description suitable for inclusion in the NAK ERR.3 field.
     * Requirement 2.5: must be non-empty.
     */
    public String getHumanReadableDescription() {
        return humanReadableDescription;
    }

    /** Returns the NAK error code — always {@value #NAK_ERROR_CODE}. */
    public String getNakErrorCode() {
        return NAK_ERROR_CODE;
    }
}
