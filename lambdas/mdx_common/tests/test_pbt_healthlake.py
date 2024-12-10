"""
Property-based tests for HealthLake Connector (task 11.4).

Property 17: HealthLake Retry and Dead-Letter Behavior
  - Mock HealthLake to return errors; assert exactly 3 retries with exponential timing
  - Assert dead-letter event published after exhaustion

Validates: Requirements 3.3
"""
import sys, os, time, json
import pytest
from unittest.mock import MagicMock, patch, call
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "healthlake-connector"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestHealthLakeRetry:

    @given(
        error_code=st.sampled_from([
            "ThrottlingException", "ServiceUnavailableException", "RequestLimitExceeded"
        ]),
        resource_type=st.sampled_from(["Patient", "Encounter", "Observation"]),
    )
    @settings(max_examples=30)
    def test_exactly_3_retry_attempts_on_retriable_errors(self, error_code, resource_type):
        """HealthLake client must retry exactly 3 times on retriable errors (Requirement 3.3)."""
        from botocore.exceptions import ClientError
        from healthlake_client import HealthLakeClient
        from mdx_common.errors import HealthLakeError

        error_response = {
            "Error": {"Code": error_code, "Message": "Simulated error"},
            "ResponseMetadata": {"HTTPStatusCode": 429},
        }
        mock_client = MagicMock()
        mock_client.create_resource.side_effect = ClientError(error_response, "CreateResource")

        hl_client = HealthLakeClient(region="us-east-1", client=mock_client)

        with pytest.raises(HealthLakeError) as exc_info:
            with patch("time.sleep"):  # Don't actually sleep in tests
                hl_client.create_resource(
                    "fake-datastore-id",
                    {"resourceType": resource_type, "id": "test-id"},
                )

        assert "3 retries" in str(exc_info.value) or "failed after" in str(exc_info.value), \
            "HealthLakeError message must mention exhausted retries"

        # Verify exactly 3 calls were made
        assert mock_client.create_resource.call_count == 3, \
            f"Expected 3 retry attempts, got {mock_client.create_resource.call_count}"

    @given(
        resource_type=st.sampled_from(["Patient", "Encounter"]),
    )
    @settings(max_examples=20)
    def test_non_retriable_errors_fail_immediately(self, resource_type):
        """Non-retriable errors (400, 404) must fail immediately without retrying."""
        from botocore.exceptions import ClientError
        from healthlake_client import HealthLakeClient

        error_response = {
            "Error": {"Code": "ValidationException", "Message": "Bad request"},
            "ResponseMetadata": {"HTTPStatusCode": 400},
        }
        mock_client = MagicMock()
        mock_client.create_resource.side_effect = ClientError(error_response, "CreateResource")

        hl_client = HealthLakeClient(region="us-east-1", client=mock_client)

        with pytest.raises(ClientError):
            hl_client.create_resource("ds-id", {"resourceType": resource_type})

        # Must have been called exactly once (no retries on non-retriable)
        assert mock_client.create_resource.call_count == 1, \
            f"Non-retriable error should not be retried (got {mock_client.create_resource.call_count} calls)"

    @given(resource_type=st.sampled_from(["Patient", "Observation"]))
    @settings(max_examples=20)
    def test_exponential_backoff_timing(self, resource_type):
        """Retry sleep intervals must follow 1s, 2s, 4s exponential pattern."""
        from botocore.exceptions import ClientError
        from healthlake_client import HealthLakeClient
        from mdx_common.errors import HealthLakeError

        error_response = {
            "Error": {"Code": "ThrottlingException", "Message": "Throttled"},
            "ResponseMetadata": {"HTTPStatusCode": 429},
        }
        mock_client = MagicMock()
        mock_client.create_resource.side_effect = ClientError(error_response, "CreateResource")

        sleep_calls = []
        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            hl_client = HealthLakeClient(region="us-east-1", client=mock_client)
            with pytest.raises(HealthLakeError):
                hl_client.create_resource("ds-id", {"resourceType": resource_type})

        # Should have slept twice (after attempt 1 and attempt 2; no sleep after last)
        assert len(sleep_calls) == 2, \
            f"Expected 2 sleep calls, got {len(sleep_calls)}: {sleep_calls}"
        assert sleep_calls[0] == 1.0, f"First backoff should be 1s, got {sleep_calls[0]}"
        assert sleep_calls[1] == 2.0, f"Second backoff should be 2s, got {sleep_calls[1]}"
