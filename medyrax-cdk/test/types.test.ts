/**
 * Property-based and unit tests for @mdx/types type definitions.
 *
 * Uses jest + fast-check to validate:
 * 1. EventEnvelope required fields are always present in generated objects.
 * 2. EventType constant has all expected keys.
 * 3. isCoreWorkflowType() returns truthy for known core types and falsy for unknown.
 * 4. CORE_WORKFLOW_TYPES has exactly 11 items.
 */

import * as fc from 'fast-check';
import {
  EventEnvelope,
  EventType,
  EventTypeValue,
  FhirResourceType,
  CORE_WORKFLOW_TYPES,
  ALL_FHIR_RESOURCE_TYPES,
  isCoreWorkflowType,
  MedyraxStackProps,
  EnvironmentConfig,
} from '@mdx/types';

// ── Arbitrary generators ──────────────────────────────────────────────────

/**
 * fast-check arbitrary that produces a valid {@link EventEnvelope} object.
 * All required fields are populated; optional fields are omitted or set.
 */
const arbitraryEventEnvelope: fc.Arbitrary<EventEnvelope> = fc.record({
  eventId: fc.uuid(),
  orgId: fc.stringOf(
    fc.constantFrom(...'abcdefghijklmnopqrstuvwxyz0123456789-'.split('')),
    { minLength: 1, maxLength: 32 }
  ),
  timestamp: fc.date({ min: new Date('2020-01-01'), max: new Date('2030-01-01') })
    .map(d => d.toISOString()),
  schemaVersion: fc.constantFrom('1.0', '2.0', '1.1'),
  eventType: fc.constantFrom(
    EventType.FHIR_RESOURCE_CREATED,
    EventType.FHIR_RESOURCE_UPDATED,
    EventType.FHIR_RESOURCE_DELETED,
    EventType.HL7_MESSAGE_RECEIVED,
    EventType.HEALTHLAKE_RESOURCE_PERSISTED,
  ),
});

// ── EventEnvelope property tests ──────────────────────────────────────────

describe('EventEnvelope — property-based tests', () => {
  it('generated EventEnvelope always has all required fields', () => {
    fc.assert(
      fc.property(arbitraryEventEnvelope, (envelope: EventEnvelope) => {
        expect(envelope).toHaveProperty('eventId');
        expect(envelope).toHaveProperty('orgId');
        expect(envelope).toHaveProperty('timestamp');
        expect(envelope).toHaveProperty('schemaVersion');
        expect(envelope).toHaveProperty('eventType');
      }),
      { numRuns: 200 }
    );
  });

  it('eventId is always a non-empty string', () => {
    fc.assert(
      fc.property(arbitraryEventEnvelope, (envelope: EventEnvelope) => {
        expect(typeof envelope.eventId).toBe('string');
        expect(envelope.eventId.length).toBeGreaterThan(0);
      }),
      { numRuns: 200 }
    );
  });

  it('orgId is always a non-empty string', () => {
    fc.assert(
      fc.property(arbitraryEventEnvelope, (envelope: EventEnvelope) => {
        expect(typeof envelope.orgId).toBe('string');
        expect(envelope.orgId.length).toBeGreaterThan(0);
      }),
      { numRuns: 200 }
    );
  });

  it('timestamp is always a valid ISO-8601 string', () => {
    fc.assert(
      fc.property(arbitraryEventEnvelope, (envelope: EventEnvelope) => {
        const parsed = new Date(envelope.timestamp);
        expect(parsed.toString()).not.toBe('Invalid Date');
      }),
      { numRuns: 200 }
    );
  });

  it('schemaVersion is always a non-empty string', () => {
    fc.assert(
      fc.property(arbitraryEventEnvelope, (envelope: EventEnvelope) => {
        expect(typeof envelope.schemaVersion).toBe('string');
        expect(envelope.schemaVersion.length).toBeGreaterThan(0);
      }),
      { numRuns: 200 }
    );
  });
});

// ── EventType constant tests ───────────────────────────────────────────────

describe('EventType constant', () => {
  it('has FHIR_RESOURCE_CREATED key with correct value', () => {
    expect(EventType.FHIR_RESOURCE_CREATED).toBe('fhir.resource.created');
  });

  it('has HL7_MESSAGE_RECEIVED key with correct value', () => {
    expect(EventType.HL7_MESSAGE_RECEIVED).toBe('hl7.message.received');
  });

  it('has HEALTHLAKE_RESOURCE_PERSISTED key', () => {
    expect(EventType).toHaveProperty('HEALTHLAKE_RESOURCE_PERSISTED');
    expect(typeof EventType.HEALTHLAKE_RESOURCE_PERSISTED).toBe('string');
  });

  it('has ALERT_CLINICAL_CRITICAL key', () => {
    expect(EventType).toHaveProperty('ALERT_CLINICAL_CRITICAL');
    expect(EventType.ALERT_CLINICAL_CRITICAL).toBe('alert.clinical.critical');
  });

  it('has AUDIT_PHI_ACCESS key', () => {
    expect(EventType).toHaveProperty('AUDIT_PHI_ACCESS');
    expect(EventType.AUDIT_PHI_ACCESS).toBe('audit.phi.access');
  });

  it('has FHIR_RESOURCE_UPDATED key', () => {
    expect(EventType.FHIR_RESOURCE_UPDATED).toBe('fhir.resource.updated');
  });

  it('has FHIR_RESOURCE_DELETED key', () => {
    expect(EventType.FHIR_RESOURCE_DELETED).toBe('fhir.resource.deleted');
  });

  it('has HL7_MESSAGE_TRANSFORMED key', () => {
    expect(EventType).toHaveProperty('HL7_MESSAGE_TRANSFORMED');
  });

  it('has FILE_QUARANTINED key', () => {
    expect(EventType).toHaveProperty('FILE_QUARANTINED');
  });

  it('all values are non-empty strings following domain.entity.action convention', () => {
    const values = Object.values(EventType) as string[];
    expect(values.length).toBeGreaterThan(0);
    values.forEach(v => {
      expect(typeof v).toBe('string');
      expect(v.length).toBeGreaterThan(0);
      // Each event type should contain at least one dot separator
      expect(v).toContain('.');
    });
  });
});

// ── isCoreWorkflowType() tests ────────────────────────────────────────────

describe('isCoreWorkflowType()', () => {
  it('returns true for "Patient"', () => {
    expect(isCoreWorkflowType('Patient')).toBe(true);
  });

  it('returns true for "Observation"', () => {
    expect(isCoreWorkflowType('Observation')).toBe(true);
  });

  it('returns true for "Encounter"', () => {
    expect(isCoreWorkflowType('Encounter')).toBe(true);
  });

  it('returns true for "Condition"', () => {
    expect(isCoreWorkflowType('Condition')).toBe(true);
  });

  it('returns true for "MedicationRequest"', () => {
    expect(isCoreWorkflowType('MedicationRequest')).toBe(true);
  });

  it('returns true for "DiagnosticReport"', () => {
    expect(isCoreWorkflowType('DiagnosticReport')).toBe(true);
  });

  it('returns true for "AllergyIntolerance"', () => {
    expect(isCoreWorkflowType('AllergyIntolerance')).toBe(true);
  });

  it('returns true for "Procedure"', () => {
    expect(isCoreWorkflowType('Procedure')).toBe(true);
  });

  it('returns true for "Coverage"', () => {
    expect(isCoreWorkflowType('Coverage')).toBe(true);
  });

  it('returns true for "Practitioner"', () => {
    expect(isCoreWorkflowType('Practitioner')).toBe(true);
  });

  it('returns true for "Organization"', () => {
    expect(isCoreWorkflowType('Organization')).toBe(true);
  });

  it('returns false for "Unknown"', () => {
    expect(isCoreWorkflowType('Unknown')).toBe(false);
  });

  it('returns false for empty string', () => {
    expect(isCoreWorkflowType('')).toBe(false);
  });

  it('returns false for "Bundle" (extended type)', () => {
    expect(isCoreWorkflowType('Bundle')).toBe(false);
  });

  it('returns false for "DocumentReference" (extended type)', () => {
    expect(isCoreWorkflowType('DocumentReference')).toBe(false);
  });

  it('returns false for "RiskAssessment" (extended type)', () => {
    expect(isCoreWorkflowType('RiskAssessment')).toBe(false);
  });

  it('returns false for lowercase "patient"', () => {
    expect(isCoreWorkflowType('patient')).toBe(false);
  });
});

// ── CORE_WORKFLOW_TYPES array tests ───────────────────────────────────────

describe('CORE_WORKFLOW_TYPES', () => {
  it('has exactly 11 items (Requirement 1.4)', () => {
    expect(CORE_WORKFLOW_TYPES.length).toBe(11);
  });

  it('contains all 11 required resource types', () => {
    const expected: FhirResourceType[] = [
      'Patient',
      'Practitioner',
      'Organization',
      'Encounter',
      'Observation',
      'Condition',
      'MedicationRequest',
      'DiagnosticReport',
      'AllergyIntolerance',
      'Procedure',
      'Coverage',
    ];
    expected.forEach(type => {
      expect(CORE_WORKFLOW_TYPES).toContain(type);
    });
  });

  it('every item passes isCoreWorkflowType()', () => {
    CORE_WORKFLOW_TYPES.forEach(type => {
      expect(isCoreWorkflowType(type)).toBe(true);
    });
  });

  it('has no duplicate entries', () => {
    const unique = new Set(CORE_WORKFLOW_TYPES);
    expect(unique.size).toBe(CORE_WORKFLOW_TYPES.length);
  });
});

// ── ALL_FHIR_RESOURCE_TYPES tests ─────────────────────────────────────────

describe('ALL_FHIR_RESOURCE_TYPES', () => {
  it('contains all CORE_WORKFLOW_TYPES', () => {
    CORE_WORKFLOW_TYPES.forEach(type => {
      expect(ALL_FHIR_RESOURCE_TYPES).toContain(type);
    });
  });

  it('has more than 11 entries (includes extended types)', () => {
    expect(ALL_FHIR_RESOURCE_TYPES.length).toBeGreaterThan(11);
  });
});
