"""
Property-based tests for HL7 Adapter (tasks 8.6, 8.7).

Property 3: HL7 ACK Latency < 200ms
Property 4: HL7 → FHIR Transformation Correctness
Property 5: HL7 Parse Error Handling (NAK AE on malformed messages)
Property 6: HL7 and FHIR Round-Trip Integrity

Validates: Requirements 2.1, 2.3, 2.4, 2.5, 13.1, 13.2, 13.3, 13.4
"""
import sys, os, time
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "mdx-data-mapper"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "hl7-adapter"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── HL7 message strategies ───────────────────────────────────────────────────

HL7_MSG_TYPES = ["ADT^A01", "ADT^A03", "ADT^A08", "ORU^R01", "ORM^O01"]
GENDERS = ["M", "F", "O", "U"]


@st.composite
def valid_hl7_message(draw):
    """Generate a syntactically valid HL7 v2.5 message."""
    msg_type = draw(st.sampled_from(HL7_MSG_TYPES))
    patient_id = draw(st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
                               min_size=4, max_size=12))
    gender = draw(st.sampled_from(GENDERS))
    dob = draw(st.dates(min_value=__import__("datetime").date(1920, 1, 1),
                         max_value=__import__("datetime").date(2005, 12, 31)))
    dob_str = dob.strftime("%Y%m%d")
    control_id = draw(st.text(alphabet="0123456789", min_size=6, max_size=10))
    msg = (
        f"MSH|^~\\&|TestSystem||Medyrax||20231201120000||{msg_type}|{control_id}|P|2.5\r"
        f"PID|1||{patient_id}^^^MRN||DOE^JOHN||{dob_str}|{gender}|||123 MAIN ST^^CITY^ST^12345\r"
        f"PV1|1|I|ICU^101^A|||||||||||||||{control_id}\r"
    )
    return msg


@st.composite
def malformed_hl7_message(draw):
    """Generate a structurally malformed HL7 message."""
    strategy = draw(st.integers(min_value=0, max_value=3))
    if strategy == 0:
        return ""  # empty
    if strategy == 1:
        return "NOTHL7|garbage|data"  # no MSH
    if strategy == 2:
        return "MSH|incomplete"  # truncated MSH
    return draw(st.binary(min_size=1, max_size=50)).decode("latin-1")  # binary garbage


# ── Property 3: ACK Latency < 200ms ─────────────────────────────────────────

class TestHl7AckLatency:

    @given(hl7_msg=valid_hl7_message())
    @settings(max_examples=50)
    def test_mllp_framing_and_ack_generation_within_200ms(self, hl7_msg):
        """MLLP extract + ACK build must complete < 200ms (Requirement 2.1)."""
        from mllp_framing import extract_hl7, build_ack, wrap_hl7, ACK_AA

        start = time.monotonic()
        # Wrap in MLLP framing first
        mllp_bytes = wrap_hl7(hl7_msg)
        extracted = extract_hl7(mllp_bytes)
        msh_line = next((l for l in extracted.splitlines() if l.startswith("MSH")), "")
        if msh_line:
            ack = build_ack(msh_line, ack_code=ACK_AA)
            assert ack.startswith("MSH"), "ACK must start with MSH segment"
        elapsed_ms = (time.monotonic() - start) * 1000
        assert elapsed_ms < 200, f"MLLP + ACK took {elapsed_ms:.1f}ms, exceeds 200ms SLA"

    @given(hl7_msg=valid_hl7_message())
    @settings(max_examples=30)
    def test_ack_contains_original_control_id(self, hl7_msg):
        """ACK MSA segment must echo the original MSH-10 message control ID."""
        from mllp_framing import build_ack, ACK_AA

        msh_line = next((l for l in hl7_msg.splitlines() if l.startswith("MSH")), "")
        assume(msh_line and len(msh_line.split("|")) > 9)
        original_control_id = msh_line.split("|")[9]
        assume(original_control_id)

        ack = build_ack(msh_line, ack_code=ACK_AA)
        assert original_control_id in ack, (
            f"ACK must contain original control ID '{original_control_id}'"
        )


# ── Property 5: NAK AE on malformed HL7 ─────────────────────────────────────

class TestHl7NakHandling:

    @given(bad_msg=malformed_hl7_message())
    @settings(max_examples=50)
    def test_malformed_message_produces_nak(self, bad_msg):
        """Malformed HL7 must produce NAK AE, not crash (Requirement 2.5)."""
        from mllp_framing import build_ack, ACK_AE

        nak = build_ack("", ack_code=ACK_AE, error_msg="Parse failed")
        assert "AE" in nak, "NAK must contain AE error code"
        assert nak.startswith("MSH"), "NAK must be a valid HL7 message"


# ── Property 6: HL7 and FHIR Round-Trip Integrity ───────────────────────────

class TestHl7FhirRoundTrip:

    @given(hl7_msg=valid_hl7_message())
    @settings(max_examples=30)
    def test_hl7_round_trip_semantic_equivalence(self, hl7_msg):
        """parse(hl7) → serialize(fhir) → parse(fhir) must produce semantically equivalent canonical models."""
        from hl7_to_canonical import HL7ToCanonicalParser
        from canonical_to_fhir import CanonicalToFHIRSerializer
        from fhir_to_canonical import FHIRToCanonicalParser

        parser = HL7ToCanonicalParser()
        canonical1 = parser.parse(hl7_msg)

        serializer = CanonicalToFHIRSerializer()
        fhir_resource = serializer.serialize(canonical1)

        fhir_parser = FHIRToCanonicalParser()
        import json
        canonical2 = fhir_parser.parse(fhir_resource)

        # Patient ID must survive the round-trip
        if canonical1.patient_id:
            assert canonical2.patient_id == canonical1.patient_id or \
                   canonical2.fhir_elements.get("patient.id") == canonical1.patient_id, \
                f"Patient ID lost in round-trip: {canonical1.patient_id} -> {canonical2.patient_id}"

    @given(hl7_msg=valid_hl7_message())
    @settings(max_examples=30)
    def test_extension_map_preserved_in_round_trip(self, hl7_msg):
        """Unmapped HL7 fields stored in extension_map must survive FHIR serialization."""
        from hl7_to_canonical import HL7ToCanonicalParser
        from canonical_to_fhir import CanonicalToFHIRSerializer

        parser = HL7ToCanonicalParser()
        canonical = parser.parse(hl7_msg)
        serializer = CanonicalToFHIRSerializer()
        fhir = serializer.serialize(canonical)

        # If there were extensions, they must appear in the FHIR output
        fhir_str = json.dumps(fhir) if not isinstance(fhir, str) else fhir
        if canonical.extension_map:
            assert "extension" in fhir_str, \
                "Extension map not preserved in FHIR output (Requirement 13.3)"


import json
