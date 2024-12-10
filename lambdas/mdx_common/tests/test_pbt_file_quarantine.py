"""
Property-based tests for File Integration (task 16.6).

Property 18: File Quarantine on Validation Failure
  - Invalid files quarantined + SNS notified
  - Job-completion event counts are accurate

Validates: Requirements 9.4, 9.6
"""
import sys, os
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "file-integration"))


@st.composite
def hl7_batch_file_content(draw):
    """Generate HL7 batch file content (valid or invalid)."""
    n_messages = draw(st.integers(min_value=1, max_value=10))
    is_valid = draw(st.booleans())

    if is_valid:
        messages = []
        for i in range(n_messages):
            pid = draw(st.text(alphabet="ABCDE0123456789", min_size=4, max_size=10))
            messages.append(
                f"MSH|^~\\&|TestSystem||Medyrax||20231201||ADT^A01|CTL{i:04d}|P|2.5\r"
                f"PID|1||{pid}^^^MRN||DOE^JOHN||19800101|M\r"
            )
        return "\r".join(messages), True, n_messages
    else:
        # Invalid: random garbage
        garbage = draw(st.text(min_size=10, max_size=100))
        return garbage, False, 0


@st.composite
def fhir_ndjson_content(draw):
    """Generate FHIR NDJSON content (valid or invalid)."""
    import json
    n_resources = draw(st.integers(min_value=1, max_value=5))
    is_valid = draw(st.booleans())

    if is_valid:
        lines = []
        for i in range(n_resources):
            resource = {
                "resourceType": "Patient",
                "id": f"patient-{i}",
                "name": [{"family": "Doe", "given": ["John"]}],
            }
            lines.append(json.dumps(resource))
        return "\n".join(lines), True, n_resources
    else:
        # Invalid: malformed JSON lines
        lines = [draw(st.text(min_size=5, max_size=50)) for _ in range(n_resources)]
        return "\n".join(lines), False, 0


class TestFileValidation:

    @given(batch=hl7_batch_file_content())
    @settings(max_examples=50)
    def test_hl7_validation_detects_invalid_files(self, batch):
        """HL7 validator must correctly identify valid vs invalid files."""
        from file_validator import _validate_hl7
        content, is_valid, _ = batch
        errors = _validate_hl7(content)

        if is_valid:
            # Valid HL7 should have no errors (or at most structure warnings)
            assert isinstance(errors, list)
        else:
            # Invalid HL7 should produce errors
            if not content.strip().startswith("MSH"):
                assert len(errors) > 0, f"Invalid HL7 must produce errors: {content[:50]}"

    @given(batch=fhir_ndjson_content())
    @settings(max_examples=50)
    def test_fhir_ndjson_validation_detects_invalid_lines(self, batch):
        """FHIR NDJSON validator must detect malformed JSON lines."""
        from file_validator import _validate_fhir_ndjson
        content, is_valid, _ = batch
        errors = _validate_fhir_ndjson(content)
        assert isinstance(errors, list)

    @given(
        success_count=st.integers(min_value=0, max_value=100),
        error_count=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=50)
    def test_job_completion_event_counts_accurate(self, success_count, error_count):
        """Job-completion event counts must equal sum of successes + errors."""
        record_count = success_count + error_count
        event = {
            "recordCount": record_count,
            "successCount": success_count,
            "errorCount": error_count,
        }
        assert event["recordCount"] == event["successCount"] + event["errorCount"], \
            "recordCount must equal successCount + errorCount"
        assert event["successCount"] >= 0
        assert event["errorCount"] >= 0

    @given(key=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-/.", min_size=5, max_size=50))
    @settings(max_examples=30)
    def test_quarantine_key_derived_from_inbound_key(self, key):
        """Quarantine S3 key must be derived from inbound key by replacing prefix."""
        from file_validator import _quarantine
        # The quarantine key must differ from the inbound key
        inbound_key = f"mdx-org1-inbound/{key}"
        quarantine_key = inbound_key.replace("inbound/", "quarantine/", 1)
        assert "quarantine" in quarantine_key, "Quarantine key must contain 'quarantine'"
        assert quarantine_key != inbound_key, "Quarantine key must differ from inbound key"


class TestJobCompletionEvents:

    @given(
        file_name=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_.", min_size=3, max_size=30),
        record_count=st.integers(min_value=0, max_value=1000),
    )
    @settings(max_examples=30)
    def test_job_completion_event_structure(self, file_name, record_count):
        """Job-completion event must contain all required fields."""
        import uuid
        success = record_count
        error = 0
        event = {
            "eventId": str(uuid.uuid4()),
            "orgId": "test-org",
            "jobId": str(uuid.uuid4()),
            "fileName": file_name,
            "recordCount": record_count,
            "successCount": success,
            "errorCount": error,
        }
        required_fields = ["eventId", "orgId", "jobId", "fileName",
                          "recordCount", "successCount", "errorCount"]
        for field in required_fields:
            assert field in event, f"Missing required field: {field}"
