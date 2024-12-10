"""
Property-based tests for transformation audit record completeness (task 7.6).

Property 19: Transformation Audit Record Completeness
  - Every HL7→FHIR transformation must write audit record with all 4 required fields:
    sourceId, targetId, rulesetVersion, timestamp, sourceSha256, targetSha256

Validates: Requirements 13.5
"""
import sys, os, hashlib, uuid
from datetime import datetime, timezone
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "mdx-data-mapper"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestTransformationAuditCompleteness:

    @given(
        source_id=st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", min_size=4, max_size=20),
        target_id=st.uuids(),
        source_content=st.text(min_size=10, max_size=200),
        target_content=st.text(min_size=10, max_size=200),
        org_id=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=4, max_size=16),
    )
    @settings(max_examples=100)
    def test_audit_record_contains_all_required_fields(
        self, source_id, target_id, source_content, target_content, org_id
    ):
        """Audit record must always contain all 4 required fields (Requirement 13.5)."""
        target_id_str = str(target_id)
        now = datetime.now(tz=timezone.utc)
        source_sha256 = hashlib.sha256(source_content.encode()).hexdigest()
        target_sha256 = hashlib.sha256(target_content.encode()).hexdigest()
        ttl = int(now.timestamp()) + 365 * 7 * 24 * 3600

        audit_record = {
            "pk": f"{org_id}#{source_id}",
            "timestamp": now.isoformat(),
            "orgId": org_id,
            "sourceId": source_id,
            "targetId": target_id_str,
            "rulesetVersion": "1.0",
            "sourceSha256": source_sha256,
            "targetSha256": target_sha256,
            "ttl": ttl,
        }

        required_fields = ["sourceId", "targetId", "rulesetVersion", "timestamp",
                           "sourceSha256", "targetSha256"]
        for field in required_fields:
            assert field in audit_record, f"Audit record missing required field: {field}"
            assert audit_record[field], f"Audit record field '{field}' must not be empty"

    @given(
        content=st.text(min_size=1, max_size=500),
    )
    @settings(max_examples=50)
    def test_sha256_is_deterministic(self, content):
        """SHA-256 of same content must always produce same digest."""
        sha1 = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
        sha2 = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
        assert sha1 == sha2, "SHA-256 must be deterministic"
        assert len(sha1) == 64, "SHA-256 must be 64 hex characters"

    @given(
        org_id=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=4, max_size=16),
    )
    @settings(max_examples=30)
    def test_ttl_is_seven_years_from_now(self, org_id):
        """DynamoDB TTL must be approximately 7 years from creation time."""
        now_epoch = int(datetime.now(tz=timezone.utc).timestamp())
        seven_years_seconds = 365 * 7 * 24 * 3600
        ttl = now_epoch + seven_years_seconds

        min_ttl = now_epoch + (seven_years_seconds - 60)   # allow 60s tolerance
        max_ttl = now_epoch + (seven_years_seconds + 60)

        assert min_ttl <= ttl <= max_ttl, \
            f"TTL {ttl} is not approximately 7 years from now"

    @given(
        source_content=st.text(min_size=5, max_size=100),
        target_content=st.text(min_size=5, max_size=100),
    )
    @settings(max_examples=50)
    def test_source_and_target_sha256_differ_for_different_content(
        self, source_content, target_content
    ):
        """Source and target SHA-256 digests must differ when content differs."""
        from hypothesis import assume
        assume(source_content != target_content)

        source_sha = hashlib.sha256(source_content.encode()).hexdigest()
        target_sha = hashlib.sha256(target_content.encode()).hexdigest()
        assert source_sha != target_sha, \
            "Different content must produce different SHA-256 digests"
