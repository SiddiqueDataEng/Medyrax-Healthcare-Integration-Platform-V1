"""
Medyrax™ custom exception hierarchy.

Every subsystem raises a subclass of :class:`MedyraxBaseError` so that top-level
Lambda handlers can catch a single base type, serialize the error via
``to_dict()``, and return a structured JSON error body to the caller.

All exception classes:
- Store ``message``, ``error_code``, and ``details`` on the base.
- Override ``to_dict()`` to include subsystem-specific fields.
- Expose an ``ERROR_CODE`` class constant for programmatic matching.
- Include full docstrings describing when the error is raised.
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Base exception
# ---------------------------------------------------------------------------

class MedyraxBaseError(Exception):
    """
    Base class for all Medyrax™ platform exceptions.

    All subsystem-specific errors extend this class so that Lambda handlers
    can catch a single type and produce a uniform JSON error response.

    Attributes
    ----------
    message:
        Human-readable description of the error.
    error_code:
        Machine-readable code identifying the error type (e.g.
        ``"FHIR_VALIDATION_ERROR"``).  Used by API consumers for programmatic
        error handling.
    details:
        Optional dict of additional context (field names, values, stack frames)
        that is safe to include in an API error response.  Must be
        JSON-serializable.
    """

    ERROR_CODE = "MEDYRAX_BASE_ERROR"

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.ERROR_CODE
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        """
        Return a JSON-serializable dict representation of this error.

        Suitable for inclusion in an API Gateway 4xx/5xx response body or in
        a CloudWatch Logs structured event.
        """
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# FHIR subsystem errors
# ---------------------------------------------------------------------------

class FhirValidationError(MedyraxBaseError):
    """
    Raised when a FHIR R4 resource fails profile validation.

    Produced by the ``fhir-engine-validate`` Lambda when the ``fhir.resources``
    validator detects constraint violations.  The HTTP handler maps this to
    HTTP 422 Unprocessable Entity with an OperationOutcome body.

    Attributes
    ----------
    resource_type:
        FHIR R4 resource type that failed validation (e.g. ``"Patient"``).
    validation_errors:
        Ordered list of human-readable validation error messages, each
        corresponding to a distinct constraint violation.
    """

    ERROR_CODE = "FHIR_VALIDATION_ERROR"

    def __init__(
        self,
        message: str,
        resource_type: str,
        validation_errors: list[str],
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message=message, error_code=self.ERROR_CODE, details=details)
        self.resource_type = resource_type
        self.validation_errors = validation_errors

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base["resource_type"] = self.resource_type
        base["validation_errors"] = self.validation_errors
        return base


# ---------------------------------------------------------------------------
# HL7 subsystem errors
# ---------------------------------------------------------------------------

class Hl7ParseError(MedyraxBaseError):
    """
    Raised when an HL7 v2.x message cannot be parsed.

    Produced by the ``hl7-parser`` Lambda when ``hl7apy`` encounters a
    malformed segment or unsupported message structure.  The MLLP listener
    maps this to an HL7 NAK acknowledgment with error code ``AE``.

    Attributes
    ----------
    segment:
        Name of the HL7 segment that triggered the parse failure
        (e.g. ``"PID"``, ``"OBX"``).
    field_index:
        Zero-based index of the field within the failing segment, or
        ``None`` if the failure is at the segment level.
    """

    ERROR_CODE = "HL7_PARSE_ERROR"

    def __init__(
        self,
        message: str,
        segment: str,
        field_index: Optional[int] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message=message, error_code=self.ERROR_CODE, details=details)
        self.segment = segment
        self.field_index = field_index

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base["segment"] = self.segment
        base["field_index"] = self.field_index
        return base


# ---------------------------------------------------------------------------
# Tenant management errors
# ---------------------------------------------------------------------------

class TenantNotFoundError(MedyraxBaseError):
    """
    Raised when a tenant configuration record cannot be located in DynamoDB.

    Produced by ``TenantConfigService.get_tenant_config()`` when the
    ``mdx-tenants`` table contains no item matching the requested ``org_id``.
    Lambda handlers map this to HTTP 404 Not Found.

    Attributes
    ----------
    org_id:
        The tenant identifier that was not found.
    """

    ERROR_CODE = "TENANT_NOT_FOUND"

    def __init__(
        self,
        message: str,
        org_id: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message=message, error_code=self.ERROR_CODE, details=details)
        self.org_id = org_id

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base["org_id"] = self.org_id
        return base


# ---------------------------------------------------------------------------
# Security / RBAC errors
# ---------------------------------------------------------------------------

class PhiAccessDeniedError(MedyraxBaseError):
    """
    Raised when RBAC enforcement denies access to PHI.

    Produced by the RBAC enforcement middleware when the caller's role does
    not satisfy the permission required for the requested operation.  Lambda
    handlers map this to HTTP 403 Forbidden and always emit a denied-access
    audit log entry (Requirement 7.5).

    Attributes
    ----------
    accessor_id:
        Identity of the principal that was denied access (Cognito sub or
        IAM ARN).
    required_role:
        The minimum RBAC role that would have been required to grant access
        (e.g. ``"Clinical_User"``).
    """

    ERROR_CODE = "PHI_ACCESS_DENIED"

    def __init__(
        self,
        message: str,
        accessor_id: str,
        required_role: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message=message, error_code=self.ERROR_CODE, details=details)
        self.accessor_id = accessor_id
        self.required_role = required_role

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base["accessor_id"] = self.accessor_id
        base["required_role"] = self.required_role
        return base


# ---------------------------------------------------------------------------
# Terminology service errors
# ---------------------------------------------------------------------------

class TerminologyValidationError(MedyraxBaseError):
    """
    Raised when a clinical code fails validation against its declared system.

    Produced by ``terminology-validator`` Lambda when the supplied code is not
    present in the local DynamoDB or ElastiCache code set for the given
    terminology system.

    Attributes
    ----------
    code:
        The clinical code value that failed validation (e.g. ``"12345-6"``).
    code_system:
        The terminology system the code was validated against (e.g.
        ``"http://loinc.org"``).
    """

    ERROR_CODE = "TERMINOLOGY_VALIDATION_ERROR"

    def __init__(
        self,
        message: str,
        code: str,
        code_system: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message=message, error_code=self.ERROR_CODE, details=details)
        self.code = code
        self.code_system = code_system

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base["code"] = self.code
        base["code_system"] = self.code_system
        return base


# ---------------------------------------------------------------------------
# HealthLake connector errors
# ---------------------------------------------------------------------------

class HealthLakeError(MedyraxBaseError):
    """
    Raised when an AWS HealthLake API call fails.

    Produced by the ``healthlake-writer`` and ``healthlake-reader`` Lambdas
    after exhausting all retry attempts with exponential backoff
    (Requirement 3.3).  After all retries the Lambda publishes a dead-letter
    event to the Integration Bus.

    Attributes
    ----------
    status_code:
        HTTP status code returned by the HealthLake API (e.g. ``429``, ``503``).
    operation:
        HealthLake API operation that failed (e.g.
        ``"CreateResource"``, ``"SearchWithGet"``).
    """

    ERROR_CODE = "HEALTHLAKE_ERROR"

    def __init__(
        self,
        message: str,
        status_code: int,
        operation: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message=message, error_code=self.ERROR_CODE, details=details)
        self.status_code = status_code
        self.operation = operation

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base["status_code"] = self.status_code
        base["operation"] = self.operation
        return base


# ---------------------------------------------------------------------------
# Integration Bus errors
# ---------------------------------------------------------------------------

class IntegrationBusError(MedyraxBaseError):
    """
    Raised when publishing an event to EventBridge or SQS fails.

    Produced by the ``integration_bus_publisher`` utility module when an
    ``EventBridge.PutEvents`` or ``SQS.SendMessage`` API call returns a
    non-retryable error or exhausts retries.

    Attributes
    ----------
    queue_url:
        URL of the SQS queue or ARN of the EventBridge bus to which the
        publish was attempted.
    """

    ERROR_CODE = "INTEGRATION_BUS_ERROR"

    def __init__(
        self,
        message: str,
        queue_url: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message=message, error_code=self.ERROR_CODE, details=details)
        self.queue_url = queue_url

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base["queue_url"] = self.queue_url
        return base


# ---------------------------------------------------------------------------
# Data Mapper errors
# ---------------------------------------------------------------------------

class TransformationError(MedyraxBaseError):
    """
    Raised when a data mapping or format transformation fails.

    Produced by the Data Mapper subsystem (``HL7ToCanonicalParser``,
    ``CanonicalToFHIRSerializer``, etc.) when a field mapping or serialization
    step cannot complete.  Distinct from :class:`Hl7ParseError` which covers
    raw parse failures; this error covers semantic mapping failures after a
    structurally valid message has been parsed.

    Attributes
    ----------
    source_format:
        Descriptor of the input format (e.g. ``"HL7_v2.5"``, ``"FHIR_R4"``).
    target_format:
        Descriptor of the output format (e.g. ``"FHIR_R4"``, ``"HL7_v2.5"``).
    """

    ERROR_CODE = "TRANSFORMATION_ERROR"

    def __init__(
        self,
        message: str,
        source_format: str,
        target_format: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message=message, error_code=self.ERROR_CODE, details=details)
        self.source_format = source_format
        self.target_format = target_format

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base["source_format"] = self.source_format
        base["target_format"] = self.target_format
        return base
