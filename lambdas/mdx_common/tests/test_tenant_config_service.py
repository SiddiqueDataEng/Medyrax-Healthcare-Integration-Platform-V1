"""
Unit and property-based tests for TenantConfigService.

Tests cover:
- CRUD happy-path operations (create, get, update, deprovision, delete)
- TenantNotFoundError on missing records
- TenantInactiveError for non-active tenants
- TenantAlreadyExistsError on duplicate create
- Module-level get_tenant_config() cache behaviour
- Tenant data-isolation assertion (org_id mismatch guard)
- HIPAA TTL calculation for deprovisioned tenants
- update_tenant_status() valid and invalid status values
- Hypothesis-driven round-trip for arbitrary org configuration values

All DynamoDB interactions are exercised against a boto3 ``moto``-style stub
built with ``boto3.resource`` + a real ``moto`` mock (or the project's
preferred lightweight stub pattern using ``unittest.mock``).

Because the project has no moto dependency declared, the tests use
``unittest.mock.MagicMock`` to stub the DynamoDB Table resource so that no
real AWS call is made and no extra test dependency is required.

Requirements validated: 8.1, 8.3, 8.5
"""

from __future__ import annotations

import sys
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path bootstrap (run pytest from aws/ root or lambdas/ sub-dir)
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from mdx_common.errors import TenantNotFoundError
from mdx_common.models import TenantConfig
from mdx_common.tenant_config_service import (
    TenantAlreadyExistsError,
    TenantConfigService,
    TenantInactiveError,
    get_tenant_config,
    invalidate_all_cache,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    org_id: str = "org-test-001",
    org_name: str = "Test Hospital",
    status: str = "active",
    **kwargs: Any,
) -> TenantConfig:
    """Return a minimal valid TenantConfig, overridable via kwargs."""
    defaults: dict[str, Any] = dict(
        org_id=org_id,
        org_name=org_name,
        status=status,
        kms_key_arn=f"arn:aws:kms:us-east-1:123456789012:key/{uuid.uuid4()}",
        iam_role_arn=f"arn:aws:iam::123456789012:role/mdx-{org_id}-role",
        health_lake_data_store_id=f"ds-{uuid.uuid4().hex[:16]}",
        sqs_fifo_queue_url=f"https://sqs.us-east-1.amazonaws.com/123/{org_id}-hl7.fifo",
        event_bus_arn=f"arn:aws:events:us-east-1:123456789012:event-bus/mdx-{org_id}-bus",
    )
    defaults.update(kwargs)
    return TenantConfig(**defaults)


def _make_service(mock_table: Any) -> TenantConfigService:
    """Return a TenantConfigService wired to the given mock DynamoDB Table."""
    mock_dynamodb = MagicMock()
    mock_dynamodb.Table.return_value = mock_table
    svc = TenantConfigService(dynamodb_resource=mock_dynamodb)
    return svc


def _dynamo_item(config: TenantConfig) -> dict[str, Any]:
    """Build the DynamoDB item dict that a table.get_item() would return."""
    d = config.to_dict()
    d["orgId"] = config.org_id
    d["SK"] = "CONFIG"
    return {k: v for k, v in d.items() if v is not None}


def _client_error(code: str) -> ClientError:
    """Build a botocore ClientError with the given error code."""
    return ClientError(
        {"Error": {"Code": code, "Message": "Mocked error"}},
        "operation",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    """Ensure the module-level tenant cache is clean before every test."""
    invalidate_all_cache()
    yield
    invalidate_all_cache()


# ---------------------------------------------------------------------------
# get_tenant_config — happy path
# ---------------------------------------------------------------------------


class TestGetTenantConfig:
    """Tests for TenantConfigService.get_tenant_config()."""

    def test_returns_tenant_config_for_active_tenant(self) -> None:
        config = _make_config()
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
        svc = _make_service(mock_table)

        result = svc.get_tenant_config("org-test-001")

        assert result.org_id == "org-test-001"
        assert result.is_active is True

    def test_cache_prevents_second_dynamodb_call(self) -> None:
        config = _make_config()
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
        svc = _make_service(mock_table)

        svc.get_tenant_config("org-test-001")
        svc.get_tenant_config("org-test-001")

        assert mock_table.get_item.call_count == 1, (
            "Second get_tenant_config call should be served from cache, not DynamoDB"
        )

    def test_use_cache_false_bypasses_cache(self) -> None:
        config = _make_config()
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
        svc = _make_service(mock_table)

        svc.get_tenant_config("org-test-001", use_cache=False)
        svc.get_tenant_config("org-test-001", use_cache=False)

        assert mock_table.get_item.call_count == 2

    def test_raises_tenant_not_found_when_no_item(self) -> None:
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": None}  # DynamoDB miss
        svc = _make_service(mock_table)

        with pytest.raises(TenantNotFoundError) as exc_info:
            svc.get_tenant_config("missing-org")

        assert exc_info.value.org_id == "missing-org"

    def test_raises_tenant_not_found_when_item_key_absent(self) -> None:
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}  # No "Item" key at all
        svc = _make_service(mock_table)

        with pytest.raises(TenantNotFoundError):
            svc.get_tenant_config("ghost-org")

    def test_raises_tenant_inactive_for_suspended_tenant(self) -> None:
        config = _make_config(status="suspended")
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
        svc = _make_service(mock_table)

        with pytest.raises(TenantInactiveError) as exc_info:
            svc.get_tenant_config("org-test-001")

        assert exc_info.value.status == "suspended"

    def test_raises_tenant_inactive_for_deprovisioned_tenant(self) -> None:
        config = _make_config(status="deprovisioned")
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
        svc = _make_service(mock_table)

        with pytest.raises(TenantInactiveError) as exc_info:
            svc.get_tenant_config("org-test-001")

        assert exc_info.value.status == "deprovisioned"

    def test_consistent_read_is_used(self) -> None:
        """DynamoDB GetItem must use ConsistentRead=True for isolation."""
        config = _make_config()
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
        svc = _make_service(mock_table)

        svc.get_tenant_config("org-test-001")

        call_kwargs = mock_table.get_item.call_args.kwargs
        assert call_kwargs.get("ConsistentRead") is True, (
            "get_item must use ConsistentRead=True to prevent stale reads"
        )

    def test_org_id_mismatch_raises_not_found(self) -> None:
        """Requirement 8.3: application-level isolation guard."""
        config = _make_config(org_id="org-real-001")
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
        svc = _make_service(mock_table)

        # Ask for a different org_id — service must reject even though DynamoDB
        # returned *some* item (simulating a GSI mis-routing scenario).
        # We need to override the mock so the Key used in get_item still returns
        # the wrong org's data.
        with pytest.raises(TenantNotFoundError) as exc_info:
            svc.get_tenant_config("org-different-999")

        assert exc_info.value.org_id == "org-different-999"


# ---------------------------------------------------------------------------
# create_tenant
# ---------------------------------------------------------------------------


class TestCreateTenant:
    def test_creates_new_tenant_successfully(self) -> None:
        config = _make_config()
        mock_table = MagicMock()
        svc = _make_service(mock_table)

        result = svc.create_tenant(config)

        mock_table.put_item.assert_called_once()
        assert result.org_id == config.org_id

    def test_sets_provisioned_at_when_absent(self) -> None:
        config = _make_config()
        config.provisioned_at = None
        mock_table = MagicMock()
        svc = _make_service(mock_table)

        result = svc.create_tenant(config)

        assert result.provisioned_at is not None
        assert result.provisioned_at.tzinfo is not None  # must be tz-aware

    def test_preserves_existing_provisioned_at(self) -> None:
        fixed_ts = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        config = _make_config(provisioned_at=fixed_ts)
        mock_table = MagicMock()
        svc = _make_service(mock_table)

        result = svc.create_tenant(config)

        assert result.provisioned_at == fixed_ts

    def test_raises_already_exists_on_duplicate(self) -> None:
        config = _make_config()
        mock_table = MagicMock()
        mock_table.put_item.side_effect = _client_error(
            "ConditionalCheckFailedException"
        )
        svc = _make_service(mock_table)

        with pytest.raises(TenantAlreadyExistsError) as exc_info:
            svc.create_tenant(config)

        assert exc_info.value.org_id == config.org_id

    def test_raises_value_error_for_empty_org_id(self) -> None:
        config = _make_config(org_id="")
        mock_table = MagicMock()
        svc = _make_service(mock_table)

        with pytest.raises(ValueError):
            svc.create_tenant(config)

    def test_condition_expression_prevents_overwrite(self) -> None:
        """put_item must use attribute_not_exists condition."""
        config = _make_config()
        mock_table = MagicMock()
        svc = _make_service(mock_table)

        svc.create_tenant(config)

        call_kwargs = mock_table.put_item.call_args.kwargs
        assert "ConditionExpression" in call_kwargs
        assert "attribute_not_exists" in call_kwargs["ConditionExpression"]

    def test_invalidates_cache_after_create(self) -> None:
        """After create, a subsequent get must hit DynamoDB (cache invalidated)."""
        config = _make_config()
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
        svc = _make_service(mock_table)

        # Warm the cache
        svc.get_tenant_config("org-test-001")
        assert mock_table.get_item.call_count == 1

        # Create triggers cache invalidation
        svc.create_tenant(config)
        svc.get_tenant_config("org-test-001", use_cache=True)

        assert mock_table.get_item.call_count == 2


# ---------------------------------------------------------------------------
# update_tenant
# ---------------------------------------------------------------------------


class TestUpdateTenant:
    def test_updates_existing_tenant_successfully(self) -> None:
        config = _make_config(org_name="Updated Name")
        mock_table = MagicMock()
        svc = _make_service(mock_table)

        result = svc.update_tenant(config)

        mock_table.put_item.assert_called_once()
        assert result.org_name == "Updated Name"

    def test_raises_not_found_when_record_missing(self) -> None:
        config = _make_config()
        mock_table = MagicMock()
        mock_table.put_item.side_effect = _client_error(
            "ConditionalCheckFailedException"
        )
        svc = _make_service(mock_table)

        with pytest.raises(TenantNotFoundError):
            svc.update_tenant(config)

    def test_condition_expression_requires_existing_record(self) -> None:
        config = _make_config()
        mock_table = MagicMock()
        svc = _make_service(mock_table)

        svc.update_tenant(config)

        call_kwargs = mock_table.put_item.call_args.kwargs
        assert "ConditionExpression" in call_kwargs
        assert "attribute_exists" in call_kwargs["ConditionExpression"]

    def test_invalidates_cache_after_update(self) -> None:
        config = _make_config()
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
        svc = _make_service(mock_table)

        svc.get_tenant_config("org-test-001")  # warm cache
        svc.update_tenant(config)  # must bust cache
        svc.get_tenant_config("org-test-001")

        assert mock_table.get_item.call_count == 2


# ---------------------------------------------------------------------------
# update_tenant_status
# ---------------------------------------------------------------------------


class TestUpdateTenantStatus:
    def test_valid_status_active(self) -> None:
        mock_table = MagicMock()
        svc = _make_service(mock_table)
        svc.update_tenant_status("org-test-001", "active")
        mock_table.update_item.assert_called_once()

    def test_valid_status_suspended(self) -> None:
        mock_table = MagicMock()
        svc = _make_service(mock_table)
        svc.update_tenant_status("org-test-001", "suspended")
        mock_table.update_item.assert_called_once()

    def test_valid_status_deprovisioned(self) -> None:
        mock_table = MagicMock()
        svc = _make_service(mock_table)
        svc.update_tenant_status("org-test-001", "deprovisioned")
        mock_table.update_item.assert_called_once()

    def test_raises_value_error_for_invalid_status(self) -> None:
        mock_table = MagicMock()
        svc = _make_service(mock_table)
        with pytest.raises(ValueError, match="Invalid status"):
            svc.update_tenant_status("org-test-001", "unknown_state")

    def test_raises_not_found_on_conditional_fail(self) -> None:
        mock_table = MagicMock()
        mock_table.update_item.side_effect = _client_error(
            "ConditionalCheckFailedException"
        )
        svc = _make_service(mock_table)
        with pytest.raises(TenantNotFoundError):
            svc.update_tenant_status("missing-org", "suspended")


# ---------------------------------------------------------------------------
# deprovision_tenant
# ---------------------------------------------------------------------------


class TestDeprovisionTenant:
    def test_sets_status_to_deprovisioned(self) -> None:
        config = _make_config()
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
        svc = _make_service(mock_table)

        result = svc.deprovision_tenant("org-test-001")

        assert result.status == "deprovisioned"

    def test_sets_deprovisioned_at_when_not_provided(self) -> None:
        config = _make_config()
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
        svc = _make_service(mock_table)

        result = svc.deprovision_tenant("org-test-001")

        assert result.deprovisioned_at is not None
        assert result.deprovisioned_at.tzinfo is not None

    def test_sets_correct_deprovisioned_at_when_provided(self) -> None:
        config = _make_config()
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
        svc = _make_service(mock_table)
        ts = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        result = svc.deprovision_tenant("org-test-001", deprovisioned_at=ts)

        assert result.deprovisioned_at == ts

    def test_ttl_attribute_set_in_dynamo_item(self) -> None:
        """HIPAA retention: TTL must be set ≈ 7 years after deprovisionedAt."""
        config = _make_config()
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
        svc = _make_service(mock_table)
        ts = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        svc.deprovision_tenant("org-test-001", deprovisioned_at=ts)

        put_item_call = mock_table.put_item.call_args.kwargs
        stored_item = put_item_call["Item"]
        assert "ttl" in stored_item
        # 7 years ≈ 2555 days = 220,752,000 seconds
        import calendar

        epoch_ts = calendar.timegm(ts.utctimetuple())
        expected_ttl = epoch_ts + 365 * 7 * 86_400
        assert stored_item["ttl"] == expected_ttl

    def test_raises_not_found_for_unknown_org(self) -> None:
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}
        svc = _make_service(mock_table)

        with pytest.raises(TenantNotFoundError):
            svc.deprovision_tenant("ghost-org")


# ---------------------------------------------------------------------------
# delete_tenant
# ---------------------------------------------------------------------------


class TestDeleteTenant:
    def test_deletes_existing_tenant(self) -> None:
        mock_table = MagicMock()
        svc = _make_service(mock_table)

        svc.delete_tenant("org-test-001")

        mock_table.delete_item.assert_called_once()

    def test_raises_not_found_when_record_absent(self) -> None:
        mock_table = MagicMock()
        mock_table.delete_item.side_effect = _client_error(
            "ConditionalCheckFailedException"
        )
        svc = _make_service(mock_table)

        with pytest.raises(TenantNotFoundError):
            svc.delete_tenant("no-such-org")

    def test_invalidates_cache_after_delete(self) -> None:
        config = _make_config()
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
        svc = _make_service(mock_table)

        svc.get_tenant_config("org-test-001")  # warm cache
        svc.delete_tenant("org-test-001")
        svc.get_tenant_config("org-test-001")  # cache was busted

        assert mock_table.get_item.call_count == 2


# ---------------------------------------------------------------------------
# list_tenants
# ---------------------------------------------------------------------------


class TestListTenants:
    def test_returns_empty_list_when_no_items(self) -> None:
        mock_table = MagicMock()
        mock_table.scan.return_value = {"Items": []}
        svc = _make_service(mock_table)

        result = svc.list_tenants()

        assert result == []

    def test_returns_configs_sorted_by_org_id(self) -> None:
        configs = [_make_config(org_id="org-b"), _make_config(org_id="org-a")]
        items = [_dynamo_item(c) for c in configs]
        mock_table = MagicMock()
        mock_table.scan.return_value = {"Items": items}
        svc = _make_service(mock_table)

        result = svc.list_tenants()

        assert [r.org_id for r in result] == ["org-a", "org-b"]

    def test_handles_dynamo_pagination(self) -> None:
        config_a = _make_config(org_id="org-a")
        config_b = _make_config(org_id="org-b")
        mock_table = MagicMock()
        # First page has LastEvaluatedKey; second page does not
        mock_table.scan.side_effect = [
            {"Items": [_dynamo_item(config_a)], "LastEvaluatedKey": {"orgId": "org-a"}},
            {"Items": [_dynamo_item(config_b)]},
        ]
        svc = _make_service(mock_table)

        result = svc.list_tenants()

        assert len(result) == 2
        assert mock_table.scan.call_count == 2

    def test_skips_malformed_items_without_raising(self) -> None:
        mock_table = MagicMock()
        mock_table.scan.return_value = {
            "Items": [{"SK": "CONFIG"}]  # missing orgId — TenantConfig.from_dict raises
        }
        svc = _make_service(mock_table)

        result = svc.list_tenants()  # should not raise

        assert result == []


# ---------------------------------------------------------------------------
# Module-level get_tenant_config()
# ---------------------------------------------------------------------------


class TestModuleLevelGetTenantConfig:
    def test_module_function_raises_tenant_not_found(self) -> None:
        """The convenience function must propagate TenantNotFoundError."""
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}

        import mdx_common.tenant_config_service as tcs

        original = tcs._default_service
        try:
            svc = TenantConfigService(
                dynamodb_resource=MagicMock(Table=MagicMock(return_value=mock_table))
            )
            tcs._default_service = svc
            with pytest.raises(TenantNotFoundError):
                get_tenant_config("no-such-org")
        finally:
            tcs._default_service = original

    def test_module_function_returns_active_tenant(self) -> None:
        config = _make_config(org_id="org-module-test")
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": _dynamo_item(config)}

        import mdx_common.tenant_config_service as tcs

        original = tcs._default_service
        try:
            svc = TenantConfigService(
                dynamodb_resource=MagicMock(Table=MagicMock(return_value=mock_table))
            )
            tcs._default_service = svc
            result = get_tenant_config("org-module-test")
            assert result.org_id == "org-module-test"
        finally:
            tcs._default_service = original


# ---------------------------------------------------------------------------
# TenantInactiveError
# ---------------------------------------------------------------------------


class TestTenantInactiveError:
    def test_str_contains_org_id_and_status(self) -> None:
        err = TenantInactiveError(org_id="org-x", status="suspended")
        assert "org-x" in str(err)
        assert "suspended" in str(err)

    def test_to_dict_contains_required_keys(self) -> None:
        err = TenantInactiveError(org_id="org-x", status="deprovisioned")
        d = err.to_dict()
        assert d["error_code"] == "TENANT_INACTIVE"
        assert d["org_id"] == "org-x"
        assert d["status"] == "deprovisioned"


# ---------------------------------------------------------------------------
# TenantAlreadyExistsError
# ---------------------------------------------------------------------------


class TestTenantAlreadyExistsError:
    def test_str_contains_org_id(self) -> None:
        err = TenantAlreadyExistsError(org_id="org-dup")
        assert "org-dup" in str(err)

    def test_error_code_attribute(self) -> None:
        err = TenantAlreadyExistsError(org_id="org-dup")
        assert err.ERROR_CODE == "TENANT_ALREADY_EXISTS"


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------

# Hypothesis strategy: realistic org_id values (alphanumeric + hyphens)
_org_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-"),
    min_size=3,
    max_size=32,
).filter(lambda s: s[0].isalnum() and s[-1].isalnum())

# Strategy for tenant status values
_status_strategy = st.sampled_from(["active", "suspended", "deprovisioned"])


@given(org_id=_org_id_strategy, org_name=st.text(min_size=1, max_size=128))
@settings(max_examples=60)
def test_property_create_get_round_trip(org_id: str, org_name: str) -> None:
    """
    **Validates: Requirements 8.1, 8.5**

    Property: For any valid org_id and org_name, a TenantConfig written via
    create_tenant() can be retrieved via get_tenant_config() and the
    org_id and org_name fields are preserved exactly.
    """
    config = _make_config(org_id=org_id, org_name=org_name)
    mock_table = MagicMock()
    mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
    svc = _make_service(mock_table)

    svc.create_tenant(config)
    # Reset cache to force DynamoDB read on get
    invalidate_all_cache()
    result = svc.get_tenant_config(org_id)

    assert result.org_id == org_id
    assert result.org_name == org_name


@given(org_id=_org_id_strategy)
@settings(max_examples=60)
def test_property_get_active_tenant_never_raises_inactive_error(org_id: str) -> None:
    """
    **Validates: Requirements 8.3, 8.5**

    Property: For any org_id, if the DynamoDB item has status='active',
    get_tenant_config() must not raise TenantInactiveError.
    """
    config = _make_config(org_id=org_id, status="active")
    mock_table = MagicMock()
    mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
    svc = _make_service(mock_table)

    result = svc.get_tenant_config(org_id)

    assert result.is_active is True


@given(org_id=_org_id_strategy, status=st.sampled_from(["suspended", "deprovisioned"]))
@settings(max_examples=60)
def test_property_non_active_tenant_always_raises_inactive_error(
    org_id: str, status: str
) -> None:
    """
    **Validates: Requirements 8.3, 8.5**

    Property: For any org_id, if the DynamoDB item has status≠'active',
    get_tenant_config() must always raise TenantInactiveError.
    """
    config = _make_config(org_id=org_id, status=status)
    mock_table = MagicMock()
    mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
    svc = _make_service(mock_table)

    with pytest.raises(TenantInactiveError) as exc_info:
        svc.get_tenant_config(org_id)

    assert exc_info.value.status == status


@given(org_id=_org_id_strategy)
@settings(max_examples=40)
def test_property_missing_tenant_always_raises_not_found(org_id: str) -> None:
    """
    **Validates: Requirements 8.1, 8.3**

    Property: For any org_id not in the table, get_tenant_config() must
    always raise TenantNotFoundError with the exact org_id.
    """
    mock_table = MagicMock()
    mock_table.get_item.return_value = {}  # DynamoDB miss (no "Item" key)
    svc = _make_service(mock_table)

    with pytest.raises(TenantNotFoundError) as exc_info:
        svc.get_tenant_config(org_id)

    assert exc_info.value.org_id == org_id


@given(
    org_id=_org_id_strategy,
    kms_arn=st.text(min_size=20, max_size=200).filter(lambda s: "arn:aws:kms" not in s or True),
)
@settings(max_examples=40)
def test_property_tenant_config_to_dict_from_dict_round_trip(
    org_id: str, kms_arn: str
) -> None:
    """
    **Validates: Requirements 8.1, 8.5**

    Property: TenantConfig.to_dict() / TenantConfig.from_dict() is a
    lossless round-trip for any org_id and kms_key_arn string.
    This guarantees the DynamoDB serialization layer does not lose data.
    """
    config = _make_config(org_id=org_id, kms_key_arn=kms_arn)
    restored = TenantConfig.from_dict(config.to_dict())

    assert restored.org_id == config.org_id
    assert restored.kms_key_arn == config.kms_key_arn
    assert restored.status == config.status
    assert restored.is_active == config.is_active


@given(
    org_id=_org_id_strategy,
    hipaa_days=st.integers(min_value=1, max_value=365 * 10),
)
@settings(max_examples=40)
def test_property_deprovision_ttl_always_greater_than_deprovisioned_at(
    org_id: str, hipaa_days: int
) -> None:
    """
    **Validates: Requirements 8.4 (HIPAA retention)**

    Property: For any org_id and retention period, the DynamoDB TTL value
    stored during deprovisioning must always be strictly greater than the
    deprovision timestamp epoch.
    """
    import calendar

    config = _make_config(org_id=org_id)
    mock_table = MagicMock()
    mock_table.get_item.return_value = {"Item": _dynamo_item(config)}
    captured_item: dict[str, Any] = {}

    def capture_put(**kwargs: Any) -> None:
        captured_item.update(kwargs["Item"])

    mock_table.put_item.side_effect = capture_put
    svc = _make_service(mock_table)

    ts = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    svc.deprovision_tenant(org_id, deprovisioned_at=ts, hipaa_retention_days=hipaa_days)

    epoch_ts = calendar.timegm(ts.utctimetuple())
    assert "ttl" in captured_item
    assert captured_item["ttl"] > epoch_ts
    # TTL should be exactly deprovisioned_at + hipaa_days * 86400
    assert captured_item["ttl"] == epoch_ts + hipaa_days * 86_400
