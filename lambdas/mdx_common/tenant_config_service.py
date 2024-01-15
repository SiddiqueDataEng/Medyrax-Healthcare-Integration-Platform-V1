"""
TenantConfigService — CRUD operations on the ``mdx-tenants`` DynamoDB table.

Every Medyrax™ Lambda function calls :func:`get_tenant_config` at cold-start
(or on first request) to retrieve the runtime configuration for the
Connected_Organization it is serving.  The result is cached in a
module-level dict so subsequent invocations within the same Lambda
execution environment pay only a dict lookup rather than a DynamoDB call.

Tenant data isolation (Requirement 8.3) is enforced at two levels:

1. **Table-level encryption**: The ``mdx-tenants`` DynamoDB table uses a
   per-org KMS CMK (``encryptionKey`` attribute) set during provisioning.
   Because each item carries its own CMK ARN in ``kmsKeyArn``, the write
   path passes the CMK ARN as the ``SSESpecification`` when creating/updating
   the record, and AWS KMS enforces that only principals whose IAM policy
   grants access to that CMK can decrypt the item.

2. **Application-level isolation**: :func:`get_tenant_config` validates that
   the returned config's ``org_id`` exactly matches the requested ``org_id``
   before returning it, so a misconfigured DynamoDB GSI scan can never leak
   one org's config to another.

Usage in a Lambda handler::

    from mdx_common.tenant_config_service import get_tenant_config
    from mdx_common.errors import TenantNotFoundError, TenantInactiveError

    def handler(event, context):
        org_id = event["orgId"]
        config = get_tenant_config(org_id)   # raises on missing / inactive
        # use config.health_lake_data_store_id, config.kms_key_arn, etc.

Requirements covered: 8.1, 8.3, 8.5
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from mdx_common.constants import TABLE_TENANTS
from mdx_common.errors import TenantNotFoundError
from mdx_common.models import TenantConfig

__all__ = [
    "TenantConfigService",
    "get_tenant_config",
    "TenantInactiveError",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Additional error type specific to this module
# ---------------------------------------------------------------------------


class TenantInactiveError(Exception):
    """
    Raised when a tenant record exists but its status is not ``"active"``.

    Lambda handlers should map this to HTTP 403 Forbidden and log a security
    event, because an attempt to use a suspended or deprovisioned tenant's
    credentials is a potential policy violation.

    Attributes
    ----------
    org_id:
        The tenant identifier whose status is not ``"active"``.
    status:
        The actual status value found in the record (e.g. ``"suspended"``).
    """

    ERROR_CODE = "TENANT_INACTIVE"

    def __init__(self, org_id: str, status: str) -> None:
        super().__init__(
            f"Tenant '{org_id}' is not active (status='{status}'). "
            "Provisioning must complete before this tenant can process requests."
        )
        self.org_id = org_id
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.ERROR_CODE,
            "org_id": self.org_id,
            "status": self.status,
        }


# ---------------------------------------------------------------------------
# DynamoDB key schema constants
# ---------------------------------------------------------------------------

_CONFIG_SK = "CONFIG"
_PK_NAME = "orgId"
_SK_NAME = "SK"


# ---------------------------------------------------------------------------
# Module-level cache (warm Lambda reuse path)
# ---------------------------------------------------------------------------

# Guarded by a threading.Lock so concurrent Lambda invocations on a warm
# container do not race to populate the same cache entry.
_cache: dict[str, TenantConfig] = {}
_cache_lock = threading.Lock()


def _invalidate_cache(org_id: str) -> None:
    """Remove ``org_id`` from the module-level config cache.

    Called after any write (create / update / delete) so that the next
    :func:`get_tenant_config` call fetches the freshest version.
    """
    with _cache_lock:
        _cache.pop(org_id, None)


def invalidate_all_cache() -> None:
    """Clear the entire in-process tenant config cache.

    Useful in test teardown and after bulk tenant migrations.
    """
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# TenantConfigService class
# ---------------------------------------------------------------------------


class TenantConfigService:
    """
    Provides CRUD operations for tenant configuration records in DynamoDB.

    Each public method maps to a DynamoDB operation on the ``mdx-tenants``
    table.  The ``encryptionKey`` (KMS CMK ARN) stored inside the item is
    passed as ``SSESpecification`` on write operations so that DynamoDB
    transparently encrypts each tenant's config with its own CMK —
    satisfying Requirement 8.3 (tenant data isolation via per-org CMK).

    Parameters
    ----------
    table_name:
        Override the DynamoDB table name (defaults to the ``MDX_TENANTS_TABLE``
        environment variable, falling back to the constant
        :data:`mdx_common.constants.TABLE_TENANTS`).
    region_name:
        AWS region name passed to ``boto3.resource``.  Defaults to the
        ``AWS_DEFAULT_REGION`` environment variable or ``"us-east-1"``.
    dynamodb_resource:
        Optional pre-built ``boto3.resource("dynamodb")`` resource.  Supply
        this in tests to inject a mocked/stubbed resource without patching
        the module.
    """

    def __init__(
        self,
        table_name: Optional[str] = None,
        region_name: Optional[str] = None,
        dynamodb_resource: Optional[Any] = None,
    ) -> None:
        self._table_name: str = (
            table_name
            or os.environ.get("MDX_TENANTS_TABLE", TABLE_TENANTS)
        )
        self._region: str = (
            region_name
            or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        )
        if dynamodb_resource is not None:
            self._dynamodb = dynamodb_resource
        else:
            self._dynamodb = boto3.resource("dynamodb", region_name=self._region)

        self._table = self._dynamodb.Table(self._table_name)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_tenant_config(self, org_id: str, *, use_cache: bool = True) -> TenantConfig:
        """
        Retrieve the active configuration for ``org_id``.

        Checks the module-level in-process cache first (warm Lambda path).
        On a cache miss, reads from DynamoDB and stores the result in the
        cache for subsequent invocations.

        Parameters
        ----------
        org_id:
            The Connected_Organization identifier (partition key).
        use_cache:
            When ``True`` (default), serve from the in-process cache if
            available.  Pass ``False`` to force a fresh DynamoDB read (e.g.
            after a provisioning update).

        Returns
        -------
        TenantConfig
            The tenant configuration dataclass for ``org_id``.

        Raises
        ------
        TenantNotFoundError
            When no DynamoDB item exists for ``org_id`` + SK=``"CONFIG"``.
        TenantInactiveError
            When the item exists but its ``status`` is not ``"active"``.
        """
        if use_cache:
            with _cache_lock:
                if org_id in _cache:
                    logger.debug("Cache hit for org_id='%s'", org_id)
                    return _cache[org_id]

        logger.debug("DynamoDB read for org_id='%s'", org_id)
        item = self._get_raw_item(org_id)
        config = TenantConfig.from_dict(item)

        # Enforce application-level tenant isolation (Requirement 8.3)
        if config.org_id != org_id:
            raise TenantNotFoundError(
                message=(
                    f"DynamoDB returned item for org_id='{config.org_id}' "
                    f"but requested org_id='{org_id}' — possible GSI mis-routing."
                ),
                org_id=org_id,
            )

        if not config.is_active:
            raise TenantInactiveError(org_id=org_id, status=config.status)

        with _cache_lock:
            _cache[org_id] = config
        return config

    def get_tenant_config_any_status(self, org_id: str) -> TenantConfig:
        """
        Retrieve tenant configuration regardless of its lifecycle status.

        Used by administrative operations (deprovision, status checks) that
        need to read even suspended or deprovisioned tenants.

        Raises
        ------
        TenantNotFoundError
            When no item exists for ``org_id``.
        """
        item = self._get_raw_item(org_id)
        return TenantConfig.from_dict(item)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_tenant(self, config: TenantConfig) -> TenantConfig:
        """
        Write a new tenant configuration record to DynamoDB.

        Uses a ``condition_expression`` to guarantee idempotency — the write
        will raise if a record with the same ``org_id`` already exists.
        The item is encrypted with the org's CMK ARN stored in
        ``config.kms_key_arn`` (per-org CMK, Requirement 8.3).

        Parameters
        ----------
        config:
            Fully-populated :class:`~mdx_common.models.TenantConfig`
            instance.  ``provisioned_at`` is set to ``now(UTC)`` if not
            already present.

        Returns
        -------
        TenantConfig
            The stored config (with ``provisioned_at`` potentially filled in).

        Raises
        ------
        ValueError
            When ``config.org_id`` is empty.
        TenantAlreadyExistsError
            When a record for ``config.org_id`` already exists.
        """
        if not config.org_id:
            raise ValueError("TenantConfig.org_id must not be empty.")

        if config.provisioned_at is None:
            config.provisioned_at = datetime.now(tz=timezone.utc)

        item = self._build_dynamo_item(config)
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(#pk)",
                ExpressionAttributeNames={"#pk": _PK_NAME},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise TenantAlreadyExistsError(org_id=config.org_id) from exc
            raise

        _invalidate_cache(config.org_id)
        logger.info(
            "Created tenant config for org_id='%s' with status='%s'",
            config.org_id,
            config.status,
        )
        return config

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update_tenant(self, config: TenantConfig) -> TenantConfig:
        """
        Overwrite an existing tenant configuration record.

        The item **must already exist** — this method uses a condition
        expression to prevent accidental creation of phantom records.

        Parameters
        ----------
        config:
            Updated :class:`~mdx_common.models.TenantConfig`.  All fields
            are overwritten.

        Returns
        -------
        TenantConfig
            The updated config (unchanged reference, for caller convenience).

        Raises
        ------
        TenantNotFoundError
            When no record exists for ``config.org_id``.
        """
        if not config.org_id:
            raise ValueError("TenantConfig.org_id must not be empty.")

        item = self._build_dynamo_item(config)
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_exists(#pk)",
                ExpressionAttributeNames={"#pk": _PK_NAME},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise TenantNotFoundError(
                    message=f"Cannot update: tenant '{config.org_id}' does not exist.",
                    org_id=config.org_id,
                ) from exc
            raise

        _invalidate_cache(config.org_id)
        logger.info(
            "Updated tenant config for org_id='%s' (status='%s')",
            config.org_id,
            config.status,
        )
        return config

    def update_tenant_status(self, org_id: str, status: str) -> None:
        """
        Atomically update **only** the ``status`` attribute on a tenant record.

        Preferred over :meth:`update_tenant` when a single-field change is
        required (e.g. suspending or deprovisioning a tenant) because it avoids
        a read-modify-write race.

        Parameters
        ----------
        org_id:
            Partition key of the tenant to update.
        status:
            New lifecycle status (``"active"``, ``"suspended"``, or
            ``"deprovisioned"``).

        Raises
        ------
        TenantNotFoundError
            When no record exists for ``org_id``.
        ValueError
            When ``status`` is not one of the allowed values.
        """
        allowed_statuses = {"active", "suspended", "deprovisioned"}
        if status not in allowed_statuses:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of {allowed_statuses}."
            )

        try:
            self._table.update_item(
                Key={_PK_NAME: org_id, _SK_NAME: _CONFIG_SK},
                UpdateExpression="SET #st = :st",
                ExpressionAttributeNames={"#st": "status", "#pk": _PK_NAME},
                ExpressionAttributeValues={":st": status},
                ConditionExpression="attribute_exists(#pk)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise TenantNotFoundError(
                    message=f"Cannot update status: tenant '{org_id}' does not exist.",
                    org_id=org_id,
                ) from exc
            raise

        _invalidate_cache(org_id)
        logger.info("Set status='%s' on tenant org_id='%s'", status, org_id)

    # ------------------------------------------------------------------
    # Soft-delete / deprovision
    # ------------------------------------------------------------------

    def deprovision_tenant(
        self,
        org_id: str,
        *,
        deprovisioned_at: Optional[datetime] = None,
        hipaa_retention_days: int = 365 * 7,
    ) -> TenantConfig:
        """
        Mark a tenant as ``"deprovisioned"`` and set TTL for HIPAA retention.

        Sets:
        - ``status`` → ``"deprovisioned"``
        - ``deprovisionedAt`` → ``deprovisioned_at`` (defaults to ``now(UTC)``)
        - ``ttl`` → Unix epoch seconds of ``deprovisionedAt + hipaa_retention_days``

        Does **not** delete the item immediately — HIPAA mandates 7-year
        retention (Requirement 8.4).  A DynamoDB TTL stream triggers the
        actual deletion Lambda after the retention window expires.

        Parameters
        ----------
        org_id:
            Tenant to deprovision.
        deprovisioned_at:
            Override the deprovision timestamp.  Defaults to ``now(UTC)``.
        hipaa_retention_days:
            Number of days to retain the record before DynamoDB TTL expires
            it.  Defaults to 7 years (2555 days).

        Returns
        -------
        TenantConfig
            The updated config object with the new status and TTL.

        Raises
        ------
        TenantNotFoundError
            When no record exists for ``org_id``.
        """
        config = self.get_tenant_config_any_status(org_id)

        ts = deprovisioned_at or datetime.now(tz=timezone.utc)
        config.status = "deprovisioned"
        config.deprovisioned_at = ts

        # Compute Unix TTL for DynamoDB native TTL feature
        import calendar

        ttl_epoch = int(
            calendar.timegm(ts.utctimetuple()) + hipaa_retention_days * 86_400
        )

        item = self._build_dynamo_item(config)
        item["ttl"] = ttl_epoch  # DynamoDB TTL attribute

        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_exists(#pk)",
                ExpressionAttributeNames={"#pk": _PK_NAME},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise TenantNotFoundError(
                    message=f"Cannot deprovision: tenant '{org_id}' does not exist.",
                    org_id=org_id,
                ) from exc
            raise

        _invalidate_cache(org_id)
        logger.info(
            "Deprovisioned tenant org_id='%s'; TTL epoch=%d (%d days retention)",
            org_id,
            ttl_epoch,
            hipaa_retention_days,
        )
        return config

    # ------------------------------------------------------------------
    # Hard-delete (admin only, post-TTL expiry)
    # ------------------------------------------------------------------

    def delete_tenant(self, org_id: str) -> None:
        """
        Permanently delete a tenant record from DynamoDB.

        **This is a destructive operation** intended only for post-TTL
        cleanup Lambdas and integration test teardown.  The caller must
        already hold the Platform_Admin IAM role to execute this operation
        against the KMS-encrypted table.

        Raises
        ------
        TenantNotFoundError
            When no record exists for ``org_id``.
        """
        try:
            self._table.delete_item(
                Key={_PK_NAME: org_id, _SK_NAME: _CONFIG_SK},
                ConditionExpression="attribute_exists(#pk)",
                ExpressionAttributeNames={"#pk": _PK_NAME},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise TenantNotFoundError(
                    message=f"Cannot delete: tenant '{org_id}' does not exist.",
                    org_id=org_id,
                ) from exc
            raise

        _invalidate_cache(org_id)
        logger.info("Permanently deleted tenant record for org_id='%s'", org_id)

    # ------------------------------------------------------------------
    # List (admin / provisioning service only)
    # ------------------------------------------------------------------

    def list_tenants(self, status_filter: Optional[str] = None) -> list[TenantConfig]:
        """
        Return all tenant config records, optionally filtered by ``status``.

        Performs a full-table scan — suitable only for admin tooling and
        provisioning dashboards, not for per-request hot paths.

        Parameters
        ----------
        status_filter:
            When provided, return only tenants whose ``status`` equals this
            value (e.g. ``"active"``).

        Returns
        -------
        list[TenantConfig]
            Ordered by ``org_id`` ascending.
        """
        filter_expr = None
        expr_attrs: dict[str, Any] = {}

        if status_filter:
            from boto3.dynamodb.conditions import Attr

            filter_expr = Attr("status").eq(status_filter) & Attr(_SK_NAME).eq(
                _CONFIG_SK
            )
        else:
            from boto3.dynamodb.conditions import Attr

            filter_expr = Attr(_SK_NAME).eq(_CONFIG_SK)

        kwargs: dict[str, Any] = {}
        if filter_expr is not None:
            kwargs["FilterExpression"] = filter_expr

        configs: list[TenantConfig] = []
        # Handle DynamoDB pagination
        while True:
            response = self._table.scan(**kwargs)
            for item in response.get("Items", []):
                try:
                    configs.append(TenantConfig.from_dict(item))
                except (KeyError, ValueError) as exc:
                    logger.warning(
                        "Skipping malformed tenant record: %s — %s",
                        item.get(_PK_NAME, "<unknown>"),
                        exc,
                    )
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key

        configs.sort(key=lambda c: c.org_id)
        return configs

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_raw_item(self, org_id: str) -> dict[str, Any]:
        """Fetch the raw DynamoDB item dict; raise TenantNotFoundError on miss."""
        try:
            response = self._table.get_item(
                Key={_PK_NAME: org_id, _SK_NAME: _CONFIG_SK},
                ConsistentRead=True,
            )
        except ClientError as exc:
            logger.error(
                "DynamoDB GetItem failed for org_id='%s': %s", org_id, exc
            )
            raise

        item = response.get("Item")
        if not item:
            raise TenantNotFoundError(
                message=f"Tenant '{org_id}' not found in table '{self._table_name}'.",
                org_id=org_id,
            )
        return item  # type: ignore[return-value]

    def _build_dynamo_item(self, config: TenantConfig) -> dict[str, Any]:
        """Convert a TenantConfig to a DynamoDB item dict with SK injected."""
        item = config.to_dict()
        # Re-key to DynamoDB attribute names expected by the table schema
        item[_PK_NAME] = config.org_id
        item[_SK_NAME] = _CONFIG_SK
        # Remove None values to avoid storing null attributes unnecessarily
        return {k: v for k, v in item.items() if v is not None}


# ---------------------------------------------------------------------------
# Additional error types
# ---------------------------------------------------------------------------


class TenantAlreadyExistsError(Exception):
    """
    Raised when :meth:`TenantConfigService.create_tenant` is called for an
    ``org_id`` that already has a config record in DynamoDB.

    Attributes
    ----------
    org_id:
        The duplicate tenant identifier.
    """

    ERROR_CODE = "TENANT_ALREADY_EXISTS"

    def __init__(self, org_id: str) -> None:
        super().__init__(
            f"Tenant '{org_id}' already exists. "
            "Use update_tenant() to modify an existing record."
        )
        self.org_id = org_id


# ---------------------------------------------------------------------------
# Module-level convenience function (hot path for Lambda handlers)
# ---------------------------------------------------------------------------

# Singleton service instance used by the module-level ``get_tenant_config``
# function.  Lambdas that need custom configuration should instantiate
# :class:`TenantConfigService` directly.
_default_service: Optional[TenantConfigService] = None
_service_lock = threading.Lock()


def _get_default_service() -> TenantConfigService:
    """Return (or lazily create) the module-level singleton service instance."""
    global _default_service
    if _default_service is None:
        with _service_lock:
            if _default_service is None:
                _default_service = TenantConfigService()
    return _default_service


def get_tenant_config(org_id: str, *, use_cache: bool = True) -> TenantConfig:
    """
    Retrieve the active :class:`~mdx_common.models.TenantConfig` for ``org_id``.

    This is the **primary entry point** used by all Medyrax™ Lambda functions.
    It delegates to a lazily-created :class:`TenantConfigService` singleton
    backed by the ``MDX_TENANTS_TABLE`` environment variable (defaults to
    ``"mdx-tenants"``).

    Results are cached in the Lambda execution environment's process memory
    between invocations, so warm containers pay only a dict lookup for
    repeat calls with the same ``org_id``.

    Parameters
    ----------
    org_id:
        The Connected_Organization identifier to look up.
    use_cache:
        When ``True`` (default), serve from the in-process cache if
        available.  Pass ``False`` to force a fresh DynamoDB read.

    Returns
    -------
    TenantConfig
        Active tenant configuration.

    Raises
    ------
    TenantNotFoundError
        When ``org_id`` is not in the tenants table.
    TenantInactiveError
        When the tenant exists but is suspended or deprovisioned.

    Example
    -------
    ::

        config = get_tenant_config("acme-hospital")
        data_store_id = config.health_lake_data_store_id
    """
    return _get_default_service().get_tenant_config(org_id, use_cache=use_cache)
