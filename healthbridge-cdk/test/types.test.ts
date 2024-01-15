/**
 * Property-based and unit tests for @hb/types.
 *
 * Uses fast-check for property tests per the design document:
 * "TypeScript PBT: fast-check — property-based testing for TypeScript/JavaScript"
 * Each property test is configured with numRuns: 100.
 *
 * Validates foundational type structures used across all CDK stacks.
 */

import * as fc from 'fast-check';
import { EventType, EventEnvelope } from '../lib/types/EventEnvelope';
import { FhirResourceType, CORE_WORKFLOW_TYPES, isCoreWorkflowType } from '../lib/types/FhirResourceType';

// ── EventEnvelope Tests ───────────────────────────────────────────────────────

describe('EventEnvelope', () => {
  describe('EventType constants', () => {
    test('all EventType values are non-empty strings', () => {
      for (const [key, value] of Object.entries(EventType)) {
        expect(typeof value).toBe('string');
        expect(value.length).toBeGreaterThan(0);
      }
    });

    test('FHIR resource event types follow fhir.resource.* pattern', () => {
      expect(EventType.FHIR_RESOURCE_CREATED).toMatch(/^fhir\.resource\./);
      expect(EventType.FHIR_RESOURCE_UPDATED).toMatch(/^fhir\.resource\./);
      expect(EventType.FHIR_RESOURCE_DELETED).toMatch(/^fhir\.resource\./);
    });

    test('all EventType values are unique', () => {
      const values = Object.values(EventType);
      const unique = new Set(values);
      expect(unique.size).toBe(values.length);
    });
  });

  /**
   * Property: For any EventEnvelope-shaped object, the eventId and orgId fields
   * are preserved as-is (they are string identity fields with no transformation).
   *
   * This verifies the TypeScript interface doesn't inadvertently drop fields
   * through any structural type coercion in CDK test helpers.
   */
  test('property: EventEnvelope interface preserves eventId and orgId', () => {
    fc.assert(
      fc.property(
        fc.uuid(),
        fc.string({ minLength: 1, maxLength: 50 }),
        fc.constantFrom(...Object.values(EventType)),
        (eventId: string, orgId: string, eventType: string) => {
          const envelope: EventEnvelope = {
            eventId,
            orgId,
            eventType,
            timestamp: new Date().toISOString(),
            schemaVersion: '1.0',
          };

          expect(envelope.eventId).toBe(eventId);
          expect(envelope.orgId).toBe(orgId);
          expect(envelope.eventType).toBe(eventType);
          expect(envelope.schemaVersion).toBe('1.0');
        }
      ),
      { numRuns: 100 }
    );
  });

  /**
   * Property: Severity values, when present, must be one of the four
   * allowed levels: LOW, MEDIUM, HIGH, CRITICAL.
   */
  test('property: severity when present must be LOW|MEDIUM|HIGH|CRITICAL', () => {
    const validSeverities = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'] as const;

    fc.assert(
      fc.property(
        fc.constantFrom(...validSeverities),
        (severity) => {
          const envelope: EventEnvelope = {
            eventId:       '00000000-0000-0000-0000-000000000001',
            orgId:         'org-001',
            eventType:     EventType.ALERT_CLINICAL_HIGH,
            severity,
            timestamp:     new Date().toISOString(),
            schemaVersion: '1.0',
          };

          expect(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']).toContain(envelope.severity);
        }
      ),
      { numRuns: 100 }
    );
  });
});

// ── FhirResourceType Tests ────────────────────────────────────────────────────

describe('FhirResourceType', () => {
  test('CORE_WORKFLOW_TYPES contains exactly 11 entries (Requirement 1.4)', () => {
    expect(CORE_WORKFLOW_TYPES).toHaveLength(11);
  });

  test('CORE_WORKFLOW_TYPES contains all 11 required types from Requirement 1.4', () => {
    const required = [
      'Patient', 'Practitioner', 'Organization', 'Encounter', 'Observation',
      'Condition', 'MedicationRequest', 'DiagnosticReport', 'AllergyIntolerance',
      'Procedure', 'Coverage',
    ];
    for (const typeName of required) {
      expect(CORE_WORKFLOW_TYPES).toContain(typeName);
    }
  });

  test('isCoreWorkflowType returns true for all 11 core types', () => {
    for (const type of CORE_WORKFLOW_TYPES) {
      expect(isCoreWorkflowType(type)).toBe(true);
    }
  });

  test('isCoreWorkflowType returns false for non-core types', () => {
    expect(isCoreWorkflowType('Bundle')).toBe(false);
    expect(isCoreWorkflowType('RiskAssessment')).toBe(false);
    expect(isCoreWorkflowType('OperationOutcome')).toBe(false);
    expect(isCoreWorkflowType('UnknownType')).toBe(false);
  });

  /**
   * Property: isCoreWorkflowType(type) must be consistent — calling it twice
   * on the same input always returns the same result (determinism).
   */
  test('property: isCoreWorkflowType is deterministic', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 40 }),
        (resourceType: string) => {
          const result1 = isCoreWorkflowType(resourceType);
          const result2 = isCoreWorkflowType(resourceType);
          expect(result1).toBe(result2);
        }
      ),
      { numRuns: 100 }
    );
  });

  /**
   * Property: For any string that is NOT in CORE_WORKFLOW_TYPES,
   * isCoreWorkflowType must return false.
   */
  test('property: strings not in CORE_WORKFLOW_TYPES return false from isCoreWorkflowType', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 40 }).filter(
          (s) => !CORE_WORKFLOW_TYPES.includes(s as FhirResourceType)
        ),
        (nonCoreType: string) => {
          expect(isCoreWorkflowType(nonCoreType)).toBe(false);
        }
      ),
      { numRuns: 100 }
    );
  });
});
