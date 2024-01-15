package com.Medyrax.common.error;

/**
 * Enumeration of Medyrax™ platform error codes.
 *
 * <p>Error codes are structured as {@code HB-{SUBSYSTEM}-{NUMBER}} so that
 * CloudWatch Logs Insights queries can filter by subsystem prefix.
 *
 * <p>Each error code carries an associated HTTP status code used when the
 * error is surfaced via the API Gateway.
 */
public enum ErrorCode {

    // ── FHIR Engine (HB-FHIR-*) ─────────────────────────────────────────────
    /** FHIR resource failed profile validation. HTTP 422. */
    FHIR_VALIDATION_FAILURE("HB-FHIR-001", 422, "FHIR resource failed profile validation"),

    /** FHIR resource type is not supported by the platform. HTTP 400. */
    FHIR_UNSUPPORTED_RESOURCE_TYPE("HB-FHIR-002", 400, "FHIR resource type is not supported"),

    /** FHIR Bundle transaction failure — at least one entry failed. HTTP 422. */
    FHIR_BUNDLE_TRANSACTION_FAILURE("HB-FHIR-003", 422, "FHIR Bundle transaction failed"),

    /** FHIR search parameters are invalid or unsupported. HTTP 400. */
    FHIR_INVALID_SEARCH_PARAMETERS("HB-FHIR-004", 400, "Invalid FHIR search parameters"),

    // ── HL7 Adapter (HB-HL7-*) ───────────────────────────────────────────────
    /** HL7 message parsing failed — malformed segment or field. Returns NAK AE. */
    HL7_PARSE_FAILURE("HB-HL7-001", 400, "HL7 message parsing failed"),

    /** HL7 message type is not supported. Returns NAK AE. */
    HL7_UNSUPPORTED_MESSAGE_TYPE("HB-HL7-002", 400, "HL7 message type is not supported"),

    /** HL7 version is not supported (only 2.3–2.8 are supported). */
    HL7_UNSUPPORTED_VERSION("HB-HL7-003", 400, "HL7 version is not supported"),

    /** MLLP framing error — message is not wrapped with correct MLLP bytes. */
    HL7_MLLP_FRAMING_ERROR("HB-HL7-004", 400, "MLLP frame is malformed"),

    // ── HealthLake Connector (HB-HL-*) ───────────────────────────────────────
    /** HealthLake persistence failed after exhausting all retries. HTTP 503. */
    HEALTHLAKE_PERSISTENCE_FAILURE("HB-HL-001", 503, "HealthLake persistence failed after retries"),

    /** HealthLake datastore not found for the given tenant. HTTP 500. */
    HEALTHLAKE_DATASTORE_NOT_FOUND("HB-HL-002", 500, "HealthLake datastore not found for tenant"),

    /** Tenant isolation violation — cross-org HealthLake access attempt detected. HTTP 403. */
    HEALTHLAKE_TENANT_ISOLATION_VIOLATION("HB-HL-003", 403, "Cross-org HealthLake access denied"),

    // ── Terminology Service (HB-TERM-*) ───────────────────────────────────────
    /** Code system is not supported by the Terminology Service. HTTP 400. */
    TERMINOLOGY_UNSUPPORTED_CODE_SYSTEM("HB-TERM-001", 400, "Code system is not supported"),

    /** Code could not be found in the specified code system. */
    TERMINOLOGY_CODE_NOT_FOUND("HB-TERM-002", 422, "Code not found in code system"),

    /** Local code could not be mapped to any standard code. */
    TERMINOLOGY_MAPPING_NOT_FOUND("HB-TERM-003", 422, "No mapping found for local code"),

    // ── Security Layer (HB-SEC-*) ──────────────────────────────────────────────
    /** JWT is missing, expired, or invalid. HTTP 401. */
    SECURITY_INVALID_JWT("HB-SEC-001", 401, "JWT is missing or invalid"),

    /** Principal does not have the required RBAC permission. HTTP 403. */
    SECURITY_RBAC_DENIED("HB-SEC-002", 403, "Access denied by RBAC policy"),

    /** PHI access audit log could not be written within SLA. HTTP 500. */
    SECURITY_AUDIT_LOG_FAILURE("HB-SEC-003", 500, "PHI audit log write failed"),

    // ── Tenant Management (HB-TENANT-*) ──────────────────────────────────────
    /** Tenant not found for the given orgId. HTTP 404. */
    TENANT_NOT_FOUND("HB-TENANT-001", 404, "Tenant not found"),

    /** Tenant is in a deprovisioned state and cannot process requests. HTTP 403. */
    TENANT_DEPROVISIONED("HB-TENANT-002", 403, "Tenant has been deprovisioned"),

    /** Tenant provisioning request is invalid. HTTP 400. */
    TENANT_INVALID_PROVISIONING_REQUEST("HB-TENANT-003", 400, "Invalid tenant provisioning request"),

    // ── Integration Bus (HB-BUS-*) ────────────────────────────────────────────
    /** Event could not be published to EventBridge. */
    BUS_PUBLISH_FAILURE("HB-BUS-001", 500, "Failed to publish event to Integration Bus"),

    /** Webhook delivery failed after exhausting all retry attempts. */
    BUS_WEBHOOK_DELIVERY_FAILURE("HB-BUS-002", 500, "Webhook delivery failed after retries"),

    // ── File Integration (HB-FILE-*) ──────────────────────────────────────────
    /** Uploaded file failed format validation. */
    FILE_VALIDATION_FAILURE("HB-FILE-001", 422, "File failed format validation"),

    /** File processing job failed. */
    FILE_PROCESSING_FAILURE("HB-FILE-002", 500, "File processing job failed"),

    // ── Data Mapper (HB-MAP-*) ────────────────────────────────────────────────
    /** Transformation ruleset could not be loaded from S3. */
    MAPPER_RULESET_LOAD_FAILURE("HB-MAP-001", 500, "Transformation ruleset could not be loaded"),

    /** Canonical model comparison failed during validation diff. */
    MAPPER_DIFF_FAILURE("HB-MAP-002", 500, "Canonical model diff computation failed"),

    // ── General (HB-GEN-*) ────────────────────────────────────────────────────
    /** Unexpected internal server error. HTTP 500. */
    INTERNAL_SERVER_ERROR("HB-GEN-001", 500, "Unexpected internal server error"),

    /** Request rate limit exceeded for the calling organization. HTTP 429. */
    RATE_LIMIT_EXCEEDED("HB-GEN-002", 429, "API rate limit exceeded"),

    /** External service (HealthLake, SageMaker, partner API) is unavailable. HTTP 503. */
    EXTERNAL_SERVICE_UNAVAILABLE("HB-GEN-003", 503, "External service unavailable");

    // ── Fields ───────────────────────────────────────────────────────────────
    private final String code;
    private final int httpStatus;
    private final String defaultMessage;

    ErrorCode(String code, int httpStatus, String defaultMessage) {
        this.code = code;
        this.httpStatus = httpStatus;
        this.defaultMessage = defaultMessage;
    }

    public String getCode() {
        return code;
    }

    public int getHttpStatus() {
        return httpStatus;
    }

    public String getDefaultMessage() {
        return defaultMessage;
    }

    @Override
    public String toString() {
        return code + ": " + defaultMessage;
    }
}
