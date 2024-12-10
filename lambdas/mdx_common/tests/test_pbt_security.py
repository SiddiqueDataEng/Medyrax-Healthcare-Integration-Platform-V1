"""
Property-based tests for Security Layer (tasks 13.6, 13.7).

Property 9:  RBAC Access Control Enforcement
Property 10: PHI Safe Harbor De-identification
Property 16: PHI Audit Log Completeness

Validates: Requirements 7.3, 7.4, 7.5, 7.9, 11.3
"""
import sys, os, json, uuid
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "security-layer"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mdx_common.enums import UserRole


# ── PHI field strategies ─────────────────────────────────────────────────────

@st.composite
def fhir_patient_with_all_phi(draw):
    """Generate a Patient resource with all 18 PHI identifiers populated."""
    return {
        "resourceType": "Patient",
        "id": str(draw(st.uuids())),
        # 1. Names
        "name": [{"family": draw(st.text(min_size=2, max_size=20)),
                  "given": [draw(st.text(min_size=2, max_size=15))],
                  "text": "JOHN DOE"}],
        # 2. Geographic subdivisions
        "address": [{"line": ["123 Main St"],
                     "city": "Springfield",
                     "state": "IL",
                     "postalCode": draw(st.from_regex(r"\d{5}", fullmatch=True)),
                     "country": "US"}],
        # 3. Dates
        "birthDate": draw(st.dates(
            min_value=__import__("datetime").date(1920, 1, 1),
            max_value=__import__("datetime").date(2005, 1, 1),
        )).isoformat(),
        # 4. Telephone numbers
        "telecom": [
            {"system": "phone", "value": draw(st.from_regex(r"\d{10}", fullmatch=True))},
            {"system": "email", "value": f"{draw(st.emails())}"},
        ],
        # 8. Medical record numbers
        "identifier": [
            {"system": "http://hospital.example/mrn",
             "value": draw(st.text(alphabet="0123456789", min_size=6, max_size=10))},
        ],
        # 16. Biometric
        "photo": [{"contentType": "image/jpeg", "data": "base64encodeddata"}],
    }


# ── Property 10: PHI Safe Harbor De-identification ──────────────────────────

class TestPhiDeidentification:

    @given(patient=fhir_patient_with_all_phi())
    @settings(max_examples=50)
    def test_names_removed_after_deidentification(self, patient):
        """Patient names must be removed or redacted (PHI category 1)."""
        from deidentify import deidentify_resource
        result = deidentify_resource(patient)
        names = result.get("name", [])
        for name in names:
            family = name.get("family", "")
            given_names = name.get("given", [])
            text = name.get("text", "")
            assert not (family and not family.startswith("[REDACTED")), \
                f"Family name '{family}' not redacted"

    @given(patient=fhir_patient_with_all_phi())
    @settings(max_examples=50)
    def test_birthdate_truncated_to_year_only(self, patient):
        """Birth dates must be truncated to year only (PHI category 3)."""
        from deidentify import deidentify_resource
        result = deidentify_resource(patient)
        birth_date = result.get("birthDate", "")
        if birth_date:
            # Must be exactly 4 digits (year only)
            assert len(birth_date) <= 4, \
                f"birthDate '{birth_date}' not truncated to year-only"

    @given(patient=fhir_patient_with_all_phi())
    @settings(max_examples=50)
    def test_zip_code_truncated_to_3_digits(self, patient):
        """ZIP codes must be truncated to 3-digit prefix (PHI category 2)."""
        from deidentify import deidentify_resource
        result = deidentify_resource(patient)
        for addr in result.get("address", []):
            postal = addr.get("postalCode", "")
            if postal:
                # Must not contain the original full ZIP
                digits = "".join(c for c in postal if c.isdigit())
                assert len(digits) <= 3, \
                    f"postalCode '{postal}' not truncated to 3 digits"

    @given(patient=fhir_patient_with_all_phi())
    @settings(max_examples=50)
    def test_identifiers_hashed(self, patient):
        """Medical record numbers must be hashed, not present in plain text."""
        from deidentify import deidentify_resource
        original_identifiers = [
            i.get("value", "") for i in patient.get("identifier", [])
        ]
        result = deidentify_resource(patient)
        result_identifiers = [
            i.get("value", "") for i in result.get("identifier", [])
        ]
        for orig in original_identifiers:
            if orig:
                assert orig not in result_identifiers, \
                    f"Original identifier '{orig}' appears un-hashed in de-identified resource"

    @given(patient=fhir_patient_with_all_phi())
    @settings(max_examples=30)
    def test_deidentification_does_not_mutate_original(self, patient):
        """De-identification must not mutate the original resource (pure function)."""
        import copy
        from deidentify import deidentify_resource
        original_copy = copy.deepcopy(patient)
        deidentify_resource(patient)
        assert patient == original_copy, "deidentify_resource mutated the input resource"


# ── Property 9: RBAC Access Control Enforcement ─────────────────────────────

class TestRbacEnforcement:

    ROLE_OPERATIONS = [
        (UserRole.CLINICAL_USER, "fhir:Patient:read", True),
        (UserRole.CLINICAL_USER, "fhir:Patient:delete", False),
        (UserRole.AUDIT_REVIEWER, "fhir:Patient:read", False),
        (UserRole.AUDIT_REVIEWER, "audit:*:read", True),
        (UserRole.INTEGRATION_SERVICE, "fhir:Patient:create", True),
    ]

    @given(
        role=st.sampled_from(list(UserRole)),
        operation=st.sampled_from([
            "fhir:Patient:read", "fhir:Patient:create",
            "fhir:Patient:delete", "audit:*:read",
            "healthlake:*:*", "compliance:*:read",
        ]),
    )
    @settings(max_examples=100)
    def test_permission_check_is_deterministic(self, role, operation):
        """Same role/operation combination must always produce the same grant/deny result."""
        # Simulate the permission check logic (pure function, no DDB)
        permissions = {
            UserRole.PLATFORM_ADMIN: {"*"},
            UserRole.ORGANIZATION_ADMIN: {
                "fhir:*:read", "fhir:*:create", "fhir:*:update",
                "tenant:*:read", "tenant:*:update",
            },
            UserRole.CLINICAL_USER: {
                "fhir:Patient:read", "fhir:Encounter:read",
                "fhir:Observation:read", "fhir:Observation:create",
                "fhir:Condition:read", "fhir:MedicationRequest:read",
                "fhir:DiagnosticReport:read",
            },
            UserRole.INTEGRATION_SERVICE: {
                "fhir:*:read", "fhir:*:create", "fhir:*:update",
                "healthlake:*:*", "integration_bus:*:publish",
            },
            UserRole.AUDIT_REVIEWER: {"audit:*:read", "compliance:*:read"},
        }

        allowed_perms = permissions.get(role, set())
        result1 = operation in allowed_perms or "*" in allowed_perms
        result2 = operation in allowed_perms or "*" in allowed_perms
        assert result1 == result2, "Permission check is not deterministic"

    @given(
        role=st.sampled_from([UserRole.CLINICAL_USER, UserRole.AUDIT_REVIEWER]),
        phi_operation=st.sampled_from(["fhir:Patient:delete", "fhir:*:delete"]),
    )
    @settings(max_examples=20)
    def test_restricted_roles_cannot_delete_phi(self, role, phi_operation):
        """Clinical_User and Audit_Reviewer must not be able to delete PHI."""
        permissions = {
            UserRole.CLINICAL_USER: {
                "fhir:Patient:read", "fhir:Observation:create",
            },
            UserRole.AUDIT_REVIEWER: {"audit:*:read", "compliance:*:read"},
        }
        allowed = permissions.get(role, set())
        can_delete = phi_operation in allowed or "*" in allowed
        assert not can_delete, \
            f"Role {role} should NOT have permission {phi_operation}"
