/**
 * @mdx/types — FhirResourceType
 *
 * TypeScript mirror of the Python {@code FhirResourceType} enum in mdx-common.
 *
 * Requirement 1.4 — The 11 core clinical workflow resource types are identified
 * by {@link CORE_WORKFLOW_TYPES}.  All CDK stacks and TypeScript tooling import
 * from this single source of truth.
 */

/**
 * All FHIR R4 resource types known to the Medyrax™ platform.
 */
export type FhirResourceType =
  // ── Core clinical workflow types (Requirement 1.4) ────────────────────────
  | 'Patient'
  | 'Practitioner'
  | 'Organization'
  | 'Encounter'
  | 'Observation'
  | 'Condition'
  | 'MedicationRequest'
  | 'DiagnosticReport'
  | 'AllergyIntolerance'
  | 'Procedure'
  | 'Coverage'
  // ── Extended types ────────────────────────────────────────────────────────
  | 'Bundle'
  | 'DocumentReference'
  | 'Appointment'
  | 'RiskAssessment'
  | 'ClinicalImpression'
  | 'Medication'
  | 'MedicationAdministration'
  | 'MedicationStatement'
  | 'Immunization'
  | 'MessageHeader'
  | 'OperationOutcome'
  | 'CapabilityStatement'
  | 'ConceptMap'
  | 'CodeSystem'
  | 'ValueSet';

/**
 * The 11 core clinical workflow resource types required by Requirement 1.4.
 * Used in EventBridge routing rules and Lambda dispatch logic.
 */
export const CORE_WORKFLOW_TYPES: ReadonlyArray<FhirResourceType> = [
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
] as const;

/**
 * Returns {@code true} if the given string is a core clinical workflow resource type.
 */
export function isCoreWorkflowType(resourceType: string): resourceType is FhirResourceType {
  return (CORE_WORKFLOW_TYPES as ReadonlyArray<string>).includes(resourceType);
}

/** All 25 FHIR resource types as a flat array (includes extended types). */
export const ALL_FHIR_RESOURCE_TYPES: ReadonlyArray<FhirResourceType> = [
  ...CORE_WORKFLOW_TYPES,
  'Bundle',
  'DocumentReference',
  'Appointment',
  'RiskAssessment',
  'ClinicalImpression',
  'Medication',
  'MedicationAdministration',
  'MedicationStatement',
  'Immunization',
  'MessageHeader',
  'OperationOutcome',
  'CapabilityStatement',
  'ConceptMap',
  'CodeSystem',
  'ValueSet',
] as const;
