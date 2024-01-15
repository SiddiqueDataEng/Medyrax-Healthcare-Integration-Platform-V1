/**
 * TypeScript mirror of the Java {@code EventEnvelope} class.
 *
 * Used by:
 * - CDK integration test helpers
 * - TypeScript Lambda functions (if any)
 * - fast-check property-based test generators
 *
 * Design reference: "Java utility class used by all Lambda functions to publish
 * events with standard envelope: {eventId, orgId, patientId, resourceType,
 * eventType, payload, timestamp}"
 *
 * Requirements 5.1, 5.5
 */
export interface EventEnvelope {
  /** Globally unique event ID (UUID v4). Used as SQS FIFO MessageDeduplicationId. */
  eventId: string;

  /**
   * Connected_Organization tenant identifier.
   * Used for EventBridge routing rules and tenant isolation.
   */
  orgId: string;

  /**
   * Patient identifier — used as SQS FIFO MessageGroupId for per-patient ordering.
   * May be undefined for non-patient-specific events.
   */
  patientId?: string;

  /**
   * FHIR resource type (e.g. "Patient", "Observation").
   * Used by EventBridge routing rules (Requirement 5.3).
   */
  resourceType?: string;

  /**
   * Event type qualifier (e.g. "fhir.resource.created", "hl7.message.received").
   * See {@link EventType} for all valid values.
   */
  eventType: string;

  /** The event payload — FHIR resource JSON, audit record, file summary, etc. */
  payload?: unknown;

  /** Correlation ID for X-Ray trace linking. */
  correlationId?: string;

  /** FHIR resource ID (HealthLake logical ID) after persistence. */
  fhirResourceId?: string;

  /** HealthLake datastore ID for the tenant. */
  healthLakeDataStoreId?: string;

  /** Severity for clinical alert events: LOW | MEDIUM | HIGH | CRITICAL. */
  severity?: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

  /** ISO-8601 timestamp when the event was created. */
  timestamp: string;

  /** Schema version of this envelope (default "1.0"). */
  schemaVersion: string;
}

/**
 * All event type string constants for use in EventBridge rules
 * and EventEnvelope.eventType values.
 */
export const EventType = {
  // FHIR resource lifecycle
  FHIR_RESOURCE_CREATED:   'fhir.resource.created',
  FHIR_RESOURCE_UPDATED:   'fhir.resource.updated',
  FHIR_RESOURCE_DELETED:   'fhir.resource.deleted',

  // HL7 events
  HL7_MESSAGE_RECEIVED:    'hl7.message.received',
  HL7_MESSAGE_TRANSFORMED: 'hl7.message.transformed',

  // HealthLake events
  HEALTHLAKE_RESOURCE_PERSISTED: 'healthlake.resource.persisted',
  HEALTHLAKE_RESOURCE_FAILED:    'healthlake.resource.failed',
  HEALTHLAKE_EXPORT_COMPLETE:    'healthlake.export.complete',

  // File integration
  FILE_DETECTED:           'file.detected',
  FILE_VALIDATED:          'file.validated',
  FILE_VALIDATION_FAILED:  'file.validation.failed',
  FILE_PROCESSED_COMPLETE: 'file.processed.complete',
  FILE_QUARANTINED:        'file.quarantined',

  // Workflow
  WORKFLOW_COMPLETED_TELEHEALTH:   'workflow.completed.telehealth',
  WORKFLOW_COMPLETED_PROVISIONING: 'workflow.completed.provisioning',

  // Clinical alerts
  ALERT_CLINICAL_LOW:      'alert.clinical.low',
  ALERT_CLINICAL_MEDIUM:   'alert.clinical.medium',
  ALERT_CLINICAL_HIGH:     'alert.clinical.high',
  ALERT_CLINICAL_CRITICAL: 'alert.clinical.critical',
  ALERT_MODEL_UNAVAILABLE: 'alert.model.unavailable',
  ALERT_DLQ_DEPTH_HIGH:    'alert.dlq.depth.high',

  // Audit
  AUDIT_PHI_ACCESS:        'audit.phi.access',
  AUDIT_PHI_ACCESS_DENIED: 'audit.phi.access.denied',

  // Telehealth
  TELEHEALTH_ENCOUNTER_CONCLUDED: 'telehealth.encounter.concluded',
  TELEHEALTH_APPOINTMENT_CREATED: 'telehealth.appointment.created',

  // Terminology
  TERMINOLOGY_REFRESH_COMPLETE: 'terminology.refresh.complete',

  // General
  PROCESSING_FAILED: 'processing.failed',
} as const;

export type EventTypeValue = typeof EventType[keyof typeof EventType];
