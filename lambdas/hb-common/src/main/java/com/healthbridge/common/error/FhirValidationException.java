package com.Medyrax.common.error;

import java.util.Collections;
import java.util.List;

/**
 * Exception thrown when a FHIR R4 resource fails profile validation.
 *
 * <p>Requirement 1.2: When a FHIR resource fails profile validation, the
 * FHIR_Engine SHALL return an OperationOutcome with HTTP 422 and a structured
 * list of all validation errors.
 *
 * <p>This exception carries the full list of validation error messages so
 * the Lambda handler can build the OperationOutcome response.
 */
public class FhirValidationException extends MedyraxException {

    private final List<String> validationErrors;
    private final String resourceType;

    public FhirValidationException(String resourceType, List<String> validationErrors) {
        super(ErrorCode.FHIR_VALIDATION_FAILURE,
                "FHIR " + resourceType + " resource failed profile validation: "
                + validationErrors.size() + " error(s)");
        this.resourceType = resourceType;
        this.validationErrors = Collections.unmodifiableList(validationErrors);
    }

    public FhirValidationException(String resourceType, List<String> validationErrors,
                                    Throwable cause) {
        super(ErrorCode.FHIR_VALIDATION_FAILURE,
                "FHIR " + resourceType + " resource failed profile validation",
                cause);
        this.resourceType = resourceType;
        this.validationErrors = Collections.unmodifiableList(validationErrors);
    }

    /**
     * Returns the unmodifiable list of validation error messages.
     * Each entry corresponds to one OperationOutcome.issue.
     */
    public List<String> getValidationErrors() {
        return validationErrors;
    }

    public String getResourceType() {
        return resourceType;
    }
}
