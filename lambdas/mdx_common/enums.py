"""
Medyrax™ platform enumerations.

All enums use string values so they serialize cleanly to JSON (EventBridge
event detail, DynamoDB attributes, CloudWatch Logs) without any custom
serializer.  Extend these enums as new resource types or patterns are
onboarded — never use bare string literals for these concepts elsewhere.
"""

from __future__ import annotations

from enum import Enum


class FhirResourceType(str, Enum):
    """
    FHIR R4 resource types supported by the Medyrax™ platform.

    Core clinical workflow types are listed first (Requirement 1.4).
    Additional resource types used by internal subsystems follow.
    """

    # Core clinical resources (Requirement 1.4)
    PATIENT = "Patient"
    PRACTITIONER = "Practitioner"
    ORGANIZATION = "Organization"
    ENCOUNTER = "Encounter"
    OBSERVATION = "Observation"
    CONDITION = "Condition"
    MEDICATION_REQUEST = "MedicationRequest"
    DIAGNOSTIC_REPORT = "DiagnosticReport"
    ALLERGY_INTOLERANCE = "AllergyIntolerance"
    PROCEDURE = "Procedure"
    COVERAGE = "Coverage"

    # Additional types used by integration subsystems
    APPOINTMENT = "Appointment"
    DOCUMENT_REFERENCE = "DocumentReference"
    RISK_ASSESSMENT = "RiskAssessment"
    CLINICAL_IMPRESSION = "ClinicalImpression"
    BUNDLE = "Bundle"
    OPERATION_OUTCOME = "OperationOutcome"
    CAPABILITY_STATEMENT = "CapabilityStatement"
    CODE_SYSTEM = "CodeSystem"
    CONCEPT_MAP = "ConceptMap"
    VALUE_SET = "ValueSet"
    MESSAGE_HEADER = "MessageHeader"
    MEDICATION = "Medication"
    IMMUNIZATION = "Immunization"
    CARE_PLAN = "CarePlan"
    CARE_TEAM = "CareTeam"
    LOCATION = "Location"
    ENDPOINT = "Endpoint"
    HEALTHCARE_SERVICE = "HealthcareService"
    RELATED_PERSON = "RelatedPerson"
    PERSON = "Person"
    PROVENANCE = "Provenance"
    AUDIT_EVENT = "AuditEvent"
    COMPOSITION = "Composition"
    MEDIA = "Media"
    DEVICE = "Device"
    DEVICE_METRIC = "DeviceMetric"
    SPECIMEN = "Specimen"
    SUBSTANCE = "Substance"
    BODY_STRUCTURE = "BodyStructure"
    IMAGING_STUDY = "ImagingStudy"
    CLAIM = "Claim"
    EXPLANATION_OF_BENEFIT = "ExplanationOfBenefit"
    MEDICATION_ADMINISTRATION = "MedicationAdministration"
    MEDICATION_DISPENSE = "MedicationDispense"
    SERVICE_REQUEST = "ServiceRequest"
    TASK = "Task"
    COMMUNICATION = "Communication"
    FLAG = "Flag"


class Hl7MessageType(str, Enum):
    """
    HL7 v2.x message event types supported by the HL7 Adapter.

    Values follow the ``{messageType}_{eventCode}`` convention used by
    the ``hl7apy`` library.  Requirement 2.2 mandates support for all
    types listed here.
    """

    # ADT — Admit / Discharge / Transfer events (Requirement 2.2)
    ADT_A01 = "ADT_A01"   # Admit / Visit notification
    ADT_A02 = "ADT_A02"   # Transfer a patient
    ADT_A03 = "ADT_A03"   # Discharge / End visit
    ADT_A04 = "ADT_A04"   # Register a patient
    ADT_A05 = "ADT_A05"   # Pre-admit a patient
    ADT_A06 = "ADT_A06"   # Change an outpatient to an inpatient
    ADT_A07 = "ADT_A07"   # Change an inpatient to an outpatient
    ADT_A08 = "ADT_A08"   # Update patient information
    ADT_A09 = "ADT_A09"   # Patient departing — tracking
    ADT_A10 = "ADT_A10"   # Patient arriving — tracking
    ADT_A11 = "ADT_A11"   # Cancel admit / visit notification
    ADT_A12 = "ADT_A12"   # Cancel transfer
    ADT_A13 = "ADT_A13"   # Cancel discharge / end visit
    ADT_A28 = "ADT_A28"   # Add person information
    ADT_A29 = "ADT_A29"   # Delete person information
    ADT_A31 = "ADT_A31"   # Update person information
    ADT_A40 = "ADT_A40"   # Merge patient — patient identifier list

    # ORM — Order messages
    ORM_O01 = "ORM_O01"

    # ORU — Observation result (unsolicited)
    ORU_R01 = "ORU_R01"

    # MDM — Medical document management
    MDM_T01 = "MDM_T01"   # Original document notification
    MDM_T02 = "MDM_T02"   # Original document notification and content
    MDM_T11 = "MDM_T11"   # Document cancel notification

    # DFT — Detail financial transaction
    DFT_P03 = "DFT_P03"

    # SIU — Scheduling information unsolicited
    SIU_S12 = "SIU_S12"   # Notification of new appointment booking
    SIU_S13 = "SIU_S13"   # Notification of appointment rescheduling
    SIU_S14 = "SIU_S14"   # Notification of appointment modification
    SIU_S15 = "SIU_S15"   # Notification of appointment cancellation

    # VXU — Vaccination record update
    VXU_V04 = "VXU_V04"


class IntegrationPattern(str, Enum):
    """
    Integration channel / pattern through which a message entered the platform.

    Used as an EventBridge event detail field and as a CloudWatch metric
    dimension (``Medyrax/Integration`` namespace).
    """

    FHIR_API = "fhir_api"
    HL7_MLLP = "hl7_mllp"
    HL7_FILE = "hl7_file"
    FHIR_BULK = "fhir_bulk"
    SFTP_FILE = "sftp_file"
    WEBHOOK = "webhook"
    TELEHEALTH_API = "telehealth_api"
    ANALYTICS_STREAM = "analytics_stream"
    CDS_WORKFLOW = "cds_workflow"
    INTERNAL_SFN = "internal_sfn"


class UserRole(str, Enum):
    """
    RBAC roles enforced by the Security Layer (Requirement 7.4).

    These roles map directly to the IAM policies and Cognito groups defined
    in the CDK Security Stack.  Exact string values are stored in the
    ``mdx-rbac-permissions`` DynamoDB table and in JWT ``cognito:groups``
    claims.
    """

    PLATFORM_ADMIN = "Platform_Admin"
    ORGANIZATION_ADMIN = "Organization_Admin"
    CLINICAL_USER = "Clinical_User"
    INTEGRATION_SERVICE = "Integration_Service"
    AUDIT_REVIEWER = "Audit_Reviewer"
