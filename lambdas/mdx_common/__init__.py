"""
mdx_common — Shared library for all Medyrax™ Lambda functions.

Provides canonical data models, enumerations, custom exceptions, and
platform-wide constants used across every integration subsystem.

Usage::

    from mdx_common.models import EventEnvelope, CanonicalMessage
    from mdx_common.enums import FhirResourceType, Hl7MessageType
    from mdx_common.errors import FhirValidationError, TenantNotFoundError
    from mdx_common.constants import PHI_FIELDS, MDX_PREFIX
"""

__version__ = "1.0.0"
__author__ = "Medyrax™ Platform Team"

from mdx_common.models import (
    EventEnvelope,
    CanonicalMessage,
    TenantConfig,
    AuditLogEntry,
)
from mdx_common.enums import (
    FhirResourceType,
    Hl7MessageType,
    IntegrationPattern,
    UserRole,
)
from mdx_common.errors import (
    FhirValidationError,
    Hl7ParseError,
    TenantNotFoundError,
    PhiAccessDeniedError,
)
from mdx_common.constants import PHI_FIELDS, MDX_PREFIX

__all__ = [
    # models
    "EventEnvelope",
    "CanonicalMessage",
    "TenantConfig",
    "AuditLogEntry",
    # enums
    "FhirResourceType",
    "Hl7MessageType",
    "IntegrationPattern",
    "UserRole",
    # errors
    "FhirValidationError",
    "Hl7ParseError",
    "TenantNotFoundError",
    "PhiAccessDeniedError",
    # constants
    "PHI_FIELDS",
    "MDX_PREFIX",
]
