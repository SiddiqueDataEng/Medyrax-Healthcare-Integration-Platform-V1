/**
 * @mdx/types — EventEnvelope
 *
 * TypeScript mirror of the Python {@code EventEnvelope} dataclass in mdx-common.
 *
 * Used by:
 * - CDK integration test helpers
 * - TypeScript Lambda functions (if any)
 * - fast-check property-based test generators
 *
 * Design reference § 5 (Integration Bus):
 *   "Python utility module used by all Lambda functions to publish events with
 *   standard envelope: {eventId, orgId, patientId, resourceType, eventType,
 *   payload, timestamp}"
 *
 * Requirements 5.1, 5.5 — standard event envelope for all Integration Bus messages.
 */
export interface EventEnvelope {
  /** Globally unique event ID (UUID v4).  Used as SQS FIFO MessageDeduplicationId. */
  eventId: string;

  /**
   * Connected_Organization tenant identifier.
   * Used for EventBridge routing rules and tenant isolation.
   */
  orgId: string;

  /**
   * Patient identifier — used as SQS FIFO MessageGroupId for per-patient ordering.
   * May be undefined for non-patient-specific events (e.g. provisioning events).
   */
  patientId?: string;

  /**
   * FHIR resource type (e.g. "Patient", "Observation").
   * Used by EventBridge routing rules (Requirement 5.3).
   */
  resourceType?: string;

  /**
   * Event type qualifier (e.g. "fhir.resource.created", "hl7.message.received").
   * See {@link EventType} for all valid constant values.
   */
  eventType: string;

  /**
   * The event payload — a FHIR resource JSON object, audit record, file summary, etc.
   * Typed as {@code unknown} because different event types carry different payloads;
   * consumers narrow the type using the {@link eventType} discriminant.
   */
  payload?: unknown;

  /** Correlation ID for AWS X-Ray trace linking across Lambda invocations. */
  correlationId?: string;

  /** FHIR resource logical ID (HealthLake-assigned) after persistence. */
  fhirResourceId?: string;

  /** AWS HealthLake datastore ID for the org that owns this event. */
  healthLakeDataStoreId?: string;

  /**
   * Severity for clinical alert events.
   * Only populated when eventType is one of the {@code alert.clinical.*} types.
   */
  severity?: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

  /** ISO-8601 UTC timestamp when the event was created by the producer Lambda. */
  timestamp: string;

  /**
   * Schema version of this envelope (default "1.0").
   * Increment when breaking changes are made to the envelope structure.
   */
  schemaVersion: string;
}

/**
 * All canonical event type string constants used in EventBridge rules and
 * {@link EventEnvelope.eventType} values.
 *
 * Convention: {@code <domain>.<entity>.<action>}
 */
export const EventType = {
  // ── FHIR resource lifecycle ────────────────────────────────────────────────
  FHIR_RESOURCE_CREATED:   'fhir.resource.created',
  FHIR_RESOURCE_UPDATED:   'fhir.resource.updated',
  FHIR_RESOURCE_DELETED:   'fhir.resource.deleted',

  // ── HL7 v2.x message events ────────────────────────────────────────────────
  HL7_MESSAGE_RECEIVED:    'hl7.message.received',
  HL7_MESSAGE_TRANSFORMED: 'hl7.message.transformed',
  HL7_MESSAGE_NAK:         'hl7.message.nak',

  // ── AWS HealthLake connector events ────────────────────────────────────────
  HEALTHLAKE_RESOURCE_PERSISTED: 'healthlake.resource.persisted',
  HEALTHLAKE_RESOURCE_FAILED:    'healthlake.resource.failed',
  HEALTHLAKE_EXPORT_COMPLETE:    'healthlake.export.complete',

  // ── File integration events ────────────────────────────────────────────────
  FILE_DETECTED:           'file.detected',
  FILE_VALIDATED:          'file.validated',
  FILE_VALIDATION_FAILED:  'file.validation.failed',
  FILE_PROCESSED_COMPLETE: 'file.processed.complete',
  FILE_QUARANTINED:        'file.quarantined',

  // ── Workflow completion events ─────────────────────────────────────────────
  WORKFLOW_COMPLETED_TELEHEALTH:   'workflow.completed.telehealth',
  WORKFLOW_COMPLETED_PROVISIONING: 'workflow.completed.provisioning',
  WORKFLOW_COMPLETED_EXPORT:       'workflow.completed.export',

  // ── Clinical alert events ──────────────────────────────────────────────────
  ALERT_CLINICAL_LOW:      'alert.clinical.low',
  ALERT_CLINICAL_MEDIUM:   'alert.clinical.medium',
  ALERT_CLINICAL_HIGH:     'alert.clinical.high',
  ALERT_CLINICAL_CRITICAL: 'alert.clinical.critical',
  ALERT_MODEL_UNAVAILABLE: 'alert.model.unavailable',
  ALERT_DLQ_DEPTH_HIGH:    'alert.dlq.depth.high',

  // ── Security audit events ──────────────────────────────────────────────────
  AUDIT_PHI_ACCESS:        'audit.phi.access',
  AUDIT_PHI_ACCESS_DENIED: 'audit.phi.access.denied',

  // ── Telehealth connector events ────────────────────────────────────────────
  TELEHEALTH_ENCOUNTER_CONCLUDED: 'telehealth.encounter.concluded',
  TELEHEALTH_APPOINTMENT_CREATED: 'telehealth.appointment.created',
  TELEHEALTH_PRESYNC_REQUESTED:   'telehealth.presync.requested',

  // ── Terminology service events ─────────────────────────────────────────────
  TERMINOLOGY_REFRESH_COMPLETE: 'terminology.refresh.complete',
  TERMINOLOGY_REVIEW_REQUIRED:  'terminology.review.required',

  // ── Analytics connector events ─────────────────────────────────────────────
  ANALYTICS_DEIDENTIFIED:  'analytics.resource.deidentified',
  ANALYTICS_EXPORT_READY:  'analytics.export.ready',

  // ── General / error ────────────────────────────────────────────────────────
  PROCESSING_FAILED: 'processing.failed',
  DLQ_MESSAGE_RECEIVED: 'dlq.message.received',
} as const;

/** Union type of all valid EventType values. */
export type EventTypeValue = typeof EventType[keyof typeof EventType];
