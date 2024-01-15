"""
Medyrax™ platform-wide constants.

Centralises every magic string, numeric threshold, and configuration value
used across all Lambda functions and CDK constructs.  Import individual names
rather than the module to keep Lambda cold-start imports lightweight.

Usage::

    from mdx_common.constants import PHI_FIELDS, MDX_PREFIX, HEALTHLAKE_MAX_RETRIES
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Global resource prefix
# ---------------------------------------------------------------------------

#: Short prefix prepended to every AWS resource name created by the platform.
#: Ensures resources are easily identifiable in the AWS console and CLI.
MDX_PREFIX: str = "mdx"

# ---------------------------------------------------------------------------
# HIPAA Safe Harbor PHI field names
# ---------------------------------------------------------------------------

#: HIPAA Safe Harbor 18 PHI identifier field names used by the de-identification
#: Lambda (``security-deidentify``).  Any FHIR element whose *key* appears in
#: this set must be removed or transformed before data reaches the analytics
#: layer (Requirement 7.9, 11.3).
#:
#: Field names follow FHIR R4 element naming conventions where applicable.
PHI_FIELDS: frozenset[str] = frozenset({
    # Names (identifier 1)
    "name", "names", "given", "family", "prefix", "suffix",
    # Geographic data (identifier 3)
    "address", "line", "city", "state", "postalCode", "country", "district",
    # Dates (identifier 4)
    "birthDate", "deceasedDateTime", "deceasedDate",
    # Phone / fax / email (identifiers 5, 6, 7)
    "telecom", "phone", "fax", "email",
    # Social security / medical record / health plan numbers (identifiers 8-10)
    "identifier", "id", "ssn", "mrn", "healthPlanBeneficiaryNumber",
    # Account / certificate / license numbers (identifiers 11-13)
    "accountNumber", "certificateNumber", "licenseNumber",
    # Vehicle / device identifiers / serial numbers (identifiers 14-15)
    "vehicleIdentificationNumber", "vin",
    "deviceIdentifier", "serialNumber",
    # Web URLs (identifier 16)
    "url", "webUrl",
    # IP addresses (identifier 17)
    "ip", "ipAddress",
    # Biometric identifiers (identifier 18a)
    "biometricIdentifier",
    # Full-face photographs (identifier 18b)
    "fullFacePhotograph", "photo",
    # Any other unique identifying number (identifier 18c)
    "uniqueIdentifyingNumber",
})

# ---------------------------------------------------------------------------
# Supported HL7 versions
# ---------------------------------------------------------------------------

#: Tuple of HL7 v2.x version strings supported by the HL7 Adapter
#: (Requirement 2.8).  The ``hl7apy`` library accepts these version strings.
SUPPORTED_HL7_VERSIONS: tuple[str, ...] = (
    "2.3",
    "2.3.1",
    "2.4",
    "2.5",
    "2.5.1",
    "2.6",
    "2.7",
    "2.8",
)

# ---------------------------------------------------------------------------
# FHIR R4 base URL
# ---------------------------------------------------------------------------

#: FHIR R4 canonical base URL used when constructing code system and profile URLs.
FHIR_R4_BASE_URL: str = "http://hl7.org/fhir/R4"

# ---------------------------------------------------------------------------
# DynamoDB table names
# ---------------------------------------------------------------------------

#: Tenant configuration table — one item per Connected_Organization.
TABLE_TENANTS: str = "mdx-tenants"

#: Maps client-submitted FHIR resource IDs to server-generated HealthLake IDs.
TABLE_FHIR_ID_REGISTRY: str = "mdx-fhir-id-registry"

#: Transformation audit records (HL7→FHIR, FHIR→HL7, FHIR normalize).
TABLE_TRANSFORMATION_AUDIT: str = "mdx-transformation-audit"

#: Terminology code sets (LOINC, SNOMED CT, ICD-10, NPI).
TABLE_TERMINOLOGY_CODES: str = "mdx-terminology-codes"

#: De-identification mapping — de-identified ID → original FHIR resource ID.
TABLE_DEIDENT_MAPPING: str = "mdx-deident-mapping"

#: Clinical Decision Support rule definitions per Connected_Organization.
TABLE_CDS_RULES: str = "mdx-cds-rules"

#: RBAC permission matrix — role → allowed operations.
TABLE_RBAC_PERMISSIONS: str = "mdx-rbac-permissions"

# ---------------------------------------------------------------------------
# SQS queue name patterns
# ---------------------------------------------------------------------------

#: SQS FIFO queue for inbound HL7 MLLP messages per org.
#: Format with ``org_id``: ``QUEUE_HL7_INBOUND_PATTERN.format(org_id=org_id)``.
QUEUE_HL7_INBOUND_PATTERN: str = "mdx-{org_id}-hl7-inbound.fifo"

#: SQS standard queue for inbound HealthLake write requests per org.
QUEUE_HEALTHLAKE_INBOUND_PATTERN: str = "mdx-{org_id}-healthlake-inbound"

#: SQS standard queue for outbound webhook delivery per org.
QUEUE_WEBHOOK_PATTERN: str = "mdx-{org_id}-webhook-queue"

#: SQS standard queue for inbound file processing per org.
QUEUE_FILE_INBOUND_PATTERN: str = "mdx-{org_id}-file-inbound"

# ---------------------------------------------------------------------------
# EventBridge bus name pattern
# ---------------------------------------------------------------------------

#: EventBridge custom bus name per Connected_Organization.
#: Format with ``org_id``: ``EVENT_BUS_PATTERN.format(org_id=org_id)``.
EVENT_BUS_PATTERN: str = "mdx-{org_id}-bus"

# ---------------------------------------------------------------------------
# CloudWatch namespace
# ---------------------------------------------------------------------------

#: Custom CloudWatch namespace for all Medyrax™ operational metrics
#: (Requirement 14.1).
CW_NAMESPACE: str = "Medyrax/Integration"

# ---------------------------------------------------------------------------
# MLLP framing bytes
# ---------------------------------------------------------------------------

#: MLLP start-of-block character (0x0B) used to frame HL7 v2.x messages
#: over TCP (Requirement 2.1).
MLLP_START_BLOCK: bytes = b"\x0b"

#: MLLP end-of-block + carriage-return sequence (0x1C 0x0D) used to
#: terminate MLLP-framed HL7 v2.x messages.
MLLP_END_BLOCK: bytes = b"\x1c\x0d"

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

#: Maximum number of retry attempts for AWS HealthLake API calls before
#: publishing a dead-letter event (Requirement 3.3).
HEALTHLAKE_MAX_RETRIES: int = 3

#: Base backoff interval in seconds for HealthLake retries.  Actual delay
#: follows exponential backoff: ``HEALTHLAKE_RETRY_BASE_SECONDS * 2**attempt``.
HEALTHLAKE_RETRY_BASE_SECONDS: int = 1

#: Maximum number of retry attempts for outbound webhook delivery
#: (Requirement 5.7).
WEBHOOK_MAX_RETRIES: int = 5

#: Explicit per-attempt backoff delays in seconds for webhook delivery.
#: Delays follow the sequence: 1s, 2s, 4s, 8s, 16s.
WEBHOOK_RETRY_BACKOFF_SECONDS: list[int] = [1, 2, 4, 8, 16]

# ---------------------------------------------------------------------------
# HIPAA retention
# ---------------------------------------------------------------------------

#: Minimum PHI / audit-log retention period in days required by HIPAA
#: (Requirement 7.8).  Equals 7 years × 365 days.
HIPAA_RETENTION_DAYS: int = 365 * 7

# ---------------------------------------------------------------------------
# Terminology service SLAs
# ---------------------------------------------------------------------------

#: Maximum allowable latency in milliseconds for a terminology code validation
#: response (Requirement 4.1).
TERMINOLOGY_SLA_MS: int = 300

#: Maximum allowable latency in milliseconds for an NPI lookup response
#: (Requirement 4.7).
NPI_LOOKUP_SLA_MS: int = 500
