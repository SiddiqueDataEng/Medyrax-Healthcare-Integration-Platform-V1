"""
tenant-provisioner-finalize Lambda
========================================
Final step of the ``mdx-org-provision-sfn`` Step Function.

1. Assembles a complete :class:`~mdx_common.models.TenantConfig` from all
   the resource ARNs/IDs accumulated across previous states.
2. Writes (or updates) the tenant record in the ``mdx-tenants`` DynamoDB
   table via :class:`~mdx_common.tenant_config_service.TenantConfigService`.
3. Publishes an SNS welcome notification to the org's admin email with the
   provisioned resource details.
4. Returns a completion summary to the Step Function.

Input (from sftp state):
    {
        "orgId":                      str
        "orgName":                    str
        "adminEmail":                 str
        "alertEmail":                 str   (optional)
        "webhookUrl":                 str   (optional)
        "kmsKeyArn":                  str
        "iamRoleArn":                 str
        "sqsFifoQueueUrl":            str
        "sqsAlertQueueUrl":           str
        "sqsDlqUrl":                  str
        "eventBusArn":                str
        "healthLakeDataStoreId":      str
        "healthLakeDataStoreEndpoint": str
        "sftpServerId":               str
        "sftpEndpoint":               str
        "s3InputBucket":              str
        "s3InputPrefix":              str
        "s3OutputBucket":             str
        "s3OutputPrefix":             str
        "s3ReportsBucket":            str
    }

Output:
    {
        "orgId":   str
        "status":  "active"
        "message": "Provisioning complete"
    }

Requirements: 8.1, 8.2
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

# Relative import from sibling package (same Lambda layer / PYTHONPATH)
import sys
import importlib

# Support running both inside the Lambda layer (mdx_common on PYTHONPATH) and
# locally with the repo root on sys.path.
try:
    from mdx_common.models import TenantConfig
    from mdx_common.tenant_config_service import TenantConfigService
    from mdx_common.tenant_config_service import TenantAlreadyExistsError
except ImportError:
    # Fallback: adjust path for local development / unit testing
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mdx_common"))
    from mdx_common.models import TenantConfig  # type: ignore[no-redef]
    from mdx_common.tenant_config_service import TenantConfigService  # type: ignore[no-redef]
    from mdx_common.tenant_config_service import TenantAlreadyExistsError  # type: ignore[no-redef]

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
WELCOME_SNS_TOPIC_ARN = os.environ.get("MDX_WELCOME_SNS_TOPIC_ARN", "")
MDX_TENANTS_TABLE = os.environ.get("MDX_TENANTS_TABLE", "mdx-tenants")

# ---------------------------------------------------------------------------
# Boto3 client
# ---------------------------------------------------------------------------

_sns = boto3.client("sns", region_name=AWS_REGION)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_tenant_config(event: dict[str, Any]) -> TenantConfig:
    """
    Construct a TenantConfig dataclass from the Step Function accumulated state.
    """
    return TenantConfig(
        org_id=event["orgId"],
        org_name=event["orgName"],
        status="active",
        kms_key_arn=event.get("kmsKeyArn", ""),
        iam_role_arn=event.get("iamRoleArn", ""),
        health_lake_data_store_id=event.get("healthLakeDataStoreId", ""),
        sqs_fifo_queue_url=event.get("sqsFifoQueueUrl", ""),
        sqs_alert_queue_url=event.get("sqsAlertQueueUrl", ""),
        sqs_dlq_url=event.get("sqsDlqUrl", ""),
        event_bus_arn=event.get("eventBusArn", ""),
        sftp_server_id=event.get("sftpServerId", ""),
        s3_input_bucket=event.get("s3InputBucket", ""),
        s3_input_prefix=event.get("s3InputPrefix", "inbound/"),
        s3_output_bucket=event.get("s3OutputBucket", ""),
        s3_output_prefix=event.get("s3OutputPrefix", "outbound/"),
        s3_reports_bucket=event.get("s3ReportsBucket", ""),
        webhook_url=event.get("webhookUrl"),
        alert_email=event.get("alertEmail"),
        provisioned_at=datetime.now(tz=timezone.utc),
    )


def _write_tenant_record(config: TenantConfig) -> None:
    """
    Write the tenant record to DynamoDB (create or update).

    Uses TenantAlreadyExistsError to detect and update existing records
    (idempotency — re-running provisioning for the same org updates the record).
    """
    svc = TenantConfigService(table_name=MDX_TENANTS_TABLE)
    try:
        svc.create_tenant(config)
        logger.info("Created tenant record for org_id='%s'", config.org_id)
    except TenantAlreadyExistsError:
        logger.warning(
            "Tenant record already exists for org_id='%s', updating.",
            config.org_id,
        )
        svc.update_tenant(config)
        logger.info("Updated tenant record for org_id='%s'", config.org_id)


def _publish_welcome_notification(
    org_id: str,
    org_name: str,
    admin_email: str,
    sftp_endpoint: str,
    healthlake_endpoint: str,
) -> None:
    """
    Publish an SNS welcome notification to the platform's welcome topic.

    The SNS topic should have an email subscription for the org admin.
    """
    if not WELCOME_SNS_TOPIC_ARN:
        logger.warning(
            "MDX_WELCOME_SNS_TOPIC_ARN not configured; skipping welcome notification "
            "for org_id='%s'",
            org_id,
        )
        return

    subject = f"Medyrax™ Platform — Provisioning Complete for {org_name}"
    message = (
        f"Your Medyrax™ Connected_Organization has been successfully provisioned.\n\n"
        f"Organization ID: {org_id}\n"
        f"Organization Name: {org_name}\n"
        f"Admin Contact: {admin_email}\n\n"
        f"SFTP Endpoint: {sftp_endpoint}\n"
        f"FHIR Datastore Endpoint: {healthlake_endpoint}\n\n"
        f"Please contact your Medyrax™ platform administrator to complete the "
        f"integration configuration and upload your clinical credentials.\n\n"
        f"— Medyrax™ Platform"
    )

    try:
        _sns.publish(
            TopicArn=WELCOME_SNS_TOPIC_ARN,
            Subject=subject,
            Message=message,
            MessageAttributes={
                "orgId": {
                    "DataType": "String",
                    "StringValue": org_id,
                },
                "eventType": {
                    "DataType": "String",
                    "StringValue": "tenant.provisioned",
                },
            },
        )
        logger.info(
            "Published welcome notification for org_id='%s' to SNS topic %s",
            org_id,
            WELCOME_SNS_TOPIC_ARN,
        )
    except ClientError as exc:
        # Log but do not fail the provisioning workflow — welcome notification
        # is best-effort; the tenant record has already been written.
        logger.error(
            "Failed to publish SNS welcome notification for org_id='%s': %s",
            org_id,
            exc,
        )


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Finalize tenant provisioning: write DynamoDB record and send SNS notification.

    Parameters
    ----------
    event:
        Step Function accumulated state containing all provisioned resource ARNs.
    context:
        AWS Lambda context object (unused).

    Returns
    -------
    dict
        Completion summary: ``{orgId, status, message}``.
    """
    org_id: str = event["orgId"]
    logger.info("Finalizing provisioning for org_id='%s'", org_id)

    # 1. Build and write tenant config record
    config = _build_tenant_config(event)
    _write_tenant_record(config)

    # 2. Publish welcome notification
    _publish_welcome_notification(
        org_id=org_id,
        org_name=event.get("orgName", ""),
        admin_email=event.get("adminEmail", ""),
        sftp_endpoint=event.get("sftpEndpoint", ""),
        healthlake_endpoint=event.get("healthLakeDataStoreEndpoint", ""),
    )

    logger.info("Provisioning complete for org_id='%s'", org_id)
    return {
        "orgId": org_id,
        "status": "active",
        "message": "Provisioning complete",
    }
