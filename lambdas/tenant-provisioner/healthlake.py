"""
tenant-provisioner-healthlake Lambda
========================================
Step 3 of the ``mdx-org-provision-sfn`` Step Function.

Creates an AWS HealthLake FHIR R4 datastore for the new org and polls until
the datastore reaches ACTIVE status.  The polling loop uses Step Functions
``waitForTaskToken`` callback pattern — this Lambda publishes a task token
via :func:`send_task_success` / :func:`send_task_failure` to the Step
Function.

Because HealthLake datastore creation can take 10–20 minutes, this Lambda
is called in two modes:

Mode A — ``initiateOnly=false`` (default, called by Step Functions directly):
    - Call ``CreateFHIRDatastore``
    - Start polling loop (up to ``MAX_POLL_ATTEMPTS`` × ``POLL_INTERVAL_SECONDS``)
    - When ACTIVE, return state with ``healthLakeDataStoreId`` and
      ``healthLakeDataStoreEndpoint``

Mode B — ``initiateOnly=true`` (used in callback / async pattern via SFN
    waitForTaskToken):
    - Start creation and return immediately; a scheduled Lambda or EventBridge
      rule polls DescribeFHIRDatastore and calls SendTaskSuccess when done.

This implementation uses the simpler synchronous polling approach suitable
for Step Functions Express Workflows (short-lived) and standard workflows
with a Lambda timeout of up to 15 minutes.

Input (from aws_resources state):
    {
        "orgId":     str
        "kmsKeyArn": str
        … other fields …
    }

Output — input extended with:
    {
        "healthLakeDataStoreId":       str
        "healthLakeDataStoreEndpoint": str
    }

Requirements: 8.1, 8.2
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
POLL_INTERVAL_SECONDS = int(os.environ.get("HL_POLL_INTERVAL_SECONDS", "30"))
MAX_POLL_ATTEMPTS = int(os.environ.get("HL_MAX_POLL_ATTEMPTS", "30"))  # 30 × 30s = 15 min

# ---------------------------------------------------------------------------
# Boto3 client
# ---------------------------------------------------------------------------

_healthlake = boto3.client("healthlake", region_name=AWS_REGION)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_existing_datastore(org_id: str) -> dict[str, str] | None:
    """
    Return existing datastore info for org_id if one already exists.

    Iterates through all datastores and matches on the ``DatastoreName``
    tag or the conventional name pattern ``mdx-{org_id}-fhir-datastore``.

    Returns a dict with ``id`` and ``endpoint``, or None if not found.
    """
    datastore_name = f"mdx-{org_id}-fhir-datastore"
    paginator = _healthlake.get_paginator("list_fhir_datastores")

    for page in paginator.paginate(
        Filter={"DatastoreName": datastore_name}
    ):
        for ds in page.get("DatastorePropertiesList", []):
            if ds.get("DatastoreName") == datastore_name:
                status = ds.get("DatastoreStatus", "")
                if status in ("ACTIVE", "CREATING"):
                    return {
                        "id": ds["DatastoreId"],
                        "endpoint": ds.get("DatastoreEndpoint", ""),
                        "status": status,
                    }
    return None


def _create_datastore(org_id: str, kms_key_arn: str) -> str:
    """
    Call CreateFHIRDatastore and return the new datastore ID.
    """
    datastore_name = f"mdx-{org_id}-fhir-datastore"
    response = _healthlake.create_fhir_datastore(
        DatastoreName=datastore_name,
        DatastoreTypeVersion="R4",
        SseConfiguration={
            "KmsEncryptionConfig": {
                "CmkType": "CUSTOMER_MANAGED_KMS_KEY",
                "KmsKeyId": kms_key_arn,
            }
        },
        Tags=[
            {"Key": "MdxOrgId", "Value": org_id},
            {"Key": "MdxComponent", "Value": "HealthLakeFhirDatastore"},
        ],
    )
    datastore_id: str = response["DatastoreId"]
    logger.info(
        "Initiated HealthLake datastore creation for org_id='%s': %s",
        org_id,
        datastore_id,
    )
    return datastore_id


def _poll_until_active(datastore_id: str, org_id: str) -> str:
    """
    Poll DescribeFHIRDatastore until the datastore is ACTIVE.

    Returns the datastore endpoint URL.

    Raises
    ------
    RuntimeError
        When the datastore fails to reach ACTIVE within the polling budget,
        or when HealthLake returns a terminal DELETED/CREATE_FAILED status.
    """
    for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
        response = _healthlake.describe_fhir_datastore(DatastoreId=datastore_id)
        ds = response["DatastoreProperties"]
        status = ds["DatastoreStatus"]
        endpoint: str = ds.get("DatastoreEndpoint", "")

        logger.info(
            "HealthLake datastore %s status: %s (attempt %d/%d, org_id='%s')",
            datastore_id,
            status,
            attempt,
            MAX_POLL_ATTEMPTS,
            org_id,
        )

        if status == "ACTIVE":
            return endpoint

        if status in ("DELETED", "CREATE_FAILED"):
            raise RuntimeError(
                f"HealthLake datastore {datastore_id} entered terminal status "
                f"'{status}' for org_id='{org_id}'."
            )

        if attempt < MAX_POLL_ATTEMPTS:
            time.sleep(POLL_INTERVAL_SECONDS)

    raise RuntimeError(
        f"HealthLake datastore {datastore_id} did not reach ACTIVE status "
        f"within {MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS} seconds "
        f"for org_id='{org_id}'."
    )


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Create AWS HealthLake FHIR R4 datastore for the new org and wait for ACTIVE.

    Parameters
    ----------
    event:
        Step Function state input — must include ``orgId`` and ``kmsKeyArn``.
    context:
        AWS Lambda context object (unused).

    Returns
    -------
    dict
        Input extended with ``healthLakeDataStoreId`` and
        ``healthLakeDataStoreEndpoint``.
    """
    org_id: str = event["orgId"]
    kms_key_arn: str = event["kmsKeyArn"]

    logger.info("Provisioning HealthLake datastore for org_id='%s'", org_id)

    # Idempotency — check whether a datastore already exists for this org
    existing = _find_existing_datastore(org_id)
    if existing:
        datastore_id = existing["id"]
        if existing["status"] == "ACTIVE":
            logger.info(
                "HealthLake datastore already ACTIVE for org_id='%s': %s",
                org_id,
                datastore_id,
            )
            return {
                **event,
                "healthLakeDataStoreId": datastore_id,
                "healthLakeDataStoreEndpoint": existing["endpoint"],
            }
        # Still CREATING — continue polling
        logger.info(
            "HealthLake datastore still CREATING for org_id='%s', resuming poll.",
            org_id,
        )
    else:
        datastore_id = _create_datastore(org_id, kms_key_arn)

    endpoint = _poll_until_active(datastore_id, org_id)

    logger.info(
        "HealthLake datastore ACTIVE for org_id='%s': id=%s endpoint=%s",
        org_id,
        datastore_id,
        endpoint,
    )

    return {
        **event,
        "healthLakeDataStoreId": datastore_id,
        "healthLakeDataStoreEndpoint": endpoint,
    }
