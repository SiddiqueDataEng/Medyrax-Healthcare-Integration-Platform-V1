/**
 * TypeScript mirror of the Java {@code FhirResourceType} enum.
 *
 * Requirement 1.4 — The 11 core clinical workflow resource types are identified
 * by {@link CORE_WORKFLOW_TYPES}.
 */
export type FhirResourceType =
  // Core clinical workflow types (Requirement 1.4)
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
  // Extended types
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
];

/**
 * Returns true if the given string is a core clinical workflow resource type.
 */
export function isCoreWorkflowType(resourceType: string): resourceType is FhirResourceType {
  return (CORE_WORKFLOW_TYPES as ReadonlyArray<string>).includes(resourceType);
}
