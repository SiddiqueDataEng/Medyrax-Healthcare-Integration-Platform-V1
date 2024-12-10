"""
HealthLake API client with exponential backoff retry (task 11.1).

Wraps boto3 HealthLake to provide CreateResource/UpdateResource/GetResource.
Retry: 1s → 2s → 4s (3 attempts).  On exhaustion raises HealthLakeError.

Requirements: 3.1, 3.2, 3.3
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_MAX_RETRIES = 3
_BACKOFF_SECONDS = [1.0, 2.0, 4.0]


class HealthLakeClient:
    """
    Thread-safe HealthLake API client with retry and dead-letter escalation.
    """

    def __init__(
        self,
        region: Optional[str] = None,
        client: Optional[Any] = None,
    ) -> None:
        self._region = region or _REGION
        self._client = client or boto3.client("healthlake", region_name=self._region)

    def create_resource(self, data_store_id: str, resource: dict[str, Any]) -> dict[str, Any]:
        """
        Create a FHIR resource in HealthLake.

        Retries up to 3 times with exponential backoff on retriable errors.
        Raises HealthLakeError on exhaustion (Requirement 3.3).
        """
        resource_type = resource.get("resourceType", "")
        return self._call_with_retry(
            "create_resource",
            DatastoreId=data_store_id,
            ResourceType=resource_type,
            Resource=json.dumps(resource),
        )

    def update_resource(
        self, data_store_id: str, resource_type: str, resource_id: str, resource: dict
    ) -> dict[str, Any]:
        """Update an existing FHIR resource in HealthLake."""
        return self._call_with_retry(
            "update_resource",
            DatastoreId=data_store_id,
            ResourceType=resource_type,
            ResourceId=resource_id,
            Resource=json.dumps(resource),
        )

    def get_resource(
        self, data_store_id: str, resource_type: str, resource_id: str
    ) -> dict[str, Any]:
        """Read a FHIR resource from HealthLake."""
        return self._call_with_retry(
            "read_resource",
            DatastoreId=data_store_id,
            ResourceType=resource_type,
            ResourceId=resource_id,
        )

    def search_resources(
        self,
        data_store_id: str,
        resource_type: str,
        search_params: str,
    ) -> dict[str, Any]:
        """Search FHIR resources in HealthLake."""
        return self._call_with_retry(
            "search_with_get",
            DatastoreId=data_store_id,
            ResourceType=resource_type,
            SearchParams=search_params,
        )

    def start_export(self, data_store_id: str, output_s3_uri: str) -> str:
        """Start a HealthLake bulk FHIR export job; return job ID."""
        resp = self._client.start_fhir_export_job(
            DatastoreId=data_store_id,
            OutputDataConfig={"S3Configuration": {"S3Uri": output_s3_uri, "KmsKeyId": ""}},
            DataAccessRoleArn=os.environ.get("MDX_HEALTHLAKE_ROLE_ARN", ""),
            JobName=f"mdx-export-{int(time.time())}",
        )
        return resp["JobId"]

    def describe_export(self, data_store_id: str, job_id: str) -> dict[str, Any]:
        """Describe a HealthLake export job."""
        return self._client.describe_fhir_export_job(
            DatastoreId=data_store_id, JobId=job_id
        )

    # ------------------------------------------------------------------
    # Retry machinery
    # ------------------------------------------------------------------

    def _call_with_retry(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        """Call a HealthLake API operation with up to 3 retry attempts."""
        last_exc: Optional[Exception] = None

        for attempt, backoff in enumerate(_BACKOFF_SECONDS, start=1):
            try:
                method = getattr(self._client, operation)
                return method(**kwargs)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)

                if self._is_retriable(code, status):
                    logger.warning(
                        "HealthLake %s attempt %d/%d failed (%s): retrying in %.1fs",
                        operation, attempt, _MAX_RETRIES, code, backoff,
                    )
                    last_exc = exc
                    if attempt < _MAX_RETRIES:
                        time.sleep(backoff)
                else:
                    # Non-retriable error — raise immediately
                    raise
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "HealthLake %s attempt %d/%d unexpected error: %s",
                    operation, attempt, _MAX_RETRIES, exc,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(backoff)

        # All retries exhausted
        import sys, os as _os
        sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), ".."))
        from mdx_common.errors import HealthLakeError  # type: ignore
        raise HealthLakeError(
            message=f"HealthLake {operation} failed after {_MAX_RETRIES} retries: {last_exc}",
            status_code=503,
            operation=operation,
        ) from last_exc

    @staticmethod
    def _is_retriable(error_code: str, status_code: int) -> bool:
        """Return True when the error is transient and should be retried."""
        retriable_codes = {"ThrottlingException", "RequestLimitExceeded", "ServiceUnavailableException"}
        return error_code in retriable_codes or status_code in (429, 500, 502, 503, 504)
