package com.Medyrax.common.event;

/**
 * Constants for all Integration Bus event type strings used as
 * {@link EventEnvelope#getEventType()} values and as EventBridge
 * rule detail-type patterns.
 *
 * <p>Design reference (Integration Bus section): "Event Types:
 * fhir.resource.*, hl7.message.*, file.processed.*,
 * workflow.completed.*, alert.clinical.*, audit.*"
 */
public final class EventType {

    private EventType() {}

    // ── FHIR resource lifecycle ───────────────────────────────────────────────
    public static final String FHIR_RESOURCE_CREATED  = "fhir.resource.created";
    public static final String FHIR_RESOURCE_UPDATED  = "fhir.resource.updated";
    public static final String FHIR_RESOURCE_DELETED  = "fhir.resource.deleted";

    // ── HL7 message events ────────────────────────────────────────────────────
    public static final String HL7_MESSAGE_RECEIVED   = "hl7.message.received";
    public static final String HL7_MESSAGE_TRANSFORMED = "hl7.message.transformed";

    // ── HealthLake Connector events ────────────────────────────────────────────
    public static final String HEALTHLAKE_RESOURCE_PERSISTED = "healthlake.resource.persisted";
    public static final String HEALTHLAKE_RESOURCE_FAILED    = "healthlake.resource.failed";
    public static final String HEALTHLAKE_EXPORT_COMPLETE    = "healthlake.export.complete";

    // ── File integration events ────────────────────────────────────────────────
    public static final String FILE_DETECTED           = "file.detected";
    public static final String FILE_VALIDATED          = "file.validated";
    public static final String FILE_VALIDATION_FAILED  = "file.validation.failed";
    public static final String FILE_PROCESSED_COMPLETE = "file.processed.complete";
    public static final String FILE_QUARANTINED        = "file.quarantined";

    // ── Workflow completion events ─────────────────────────────────────────────
    public static final String WORKFLOW_COMPLETED_TELEHEALTH  = "workflow.completed.telehealth";
    public static final String WORKFLOW_COMPLETED_PROVISIONING = "workflow.completed.provisioning";

    // ── Clinical alert events ──────────────────────────────────────────────────
    public static final String ALERT_CLINICAL_LOW      = "alert.clinical.low";
    public static final String ALERT_CLINICAL_MEDIUM   = "alert.clinical.medium";
    public static final String ALERT_CLINICAL_HIGH     = "alert.clinical.high";
    public static final String ALERT_CLINICAL_CRITICAL = "alert.clinical.critical";
    public static final String ALERT_MODEL_UNAVAILABLE = "alert.model.unavailable";
    public static final String ALERT_DLQ_DEPTH_HIGH    = "alert.dlq.depth.high";

    // ── Audit events ────────────────────────────────────────────────────────────
    public static final String AUDIT_PHI_ACCESS        = "audit.phi.access";
    public static final String AUDIT_PHI_ACCESS_DENIED = "audit.phi.access.denied";

    // ── Telehealth events ────────────────────────────────────────────────────────
    public static final String TELEHEALTH_ENCOUNTER_CONCLUDED = "telehealth.encounter.concluded";
    public static final String TELEHEALTH_APPOINTMENT_CREATED = "telehealth.appointment.created";

    // ── Terminology events ────────────────────────────────────────────────────────
    public static final String TERMINOLOGY_REFRESH_COMPLETE = "terminology.refresh.complete";

    // ── Processing failure events ──────────────────────────────────────────────
    public static final String PROCESSING_FAILED = "processing.failed";
}
