"""
tenant-provisioner-aws Lambda
================================
Step 2 of the ``mdx-org-provision-sfn`` Step Function.

Orchestrates creation of per-org AWS resources:
  1. KMS Customer Managed Key (CMK) — ``alias/mdx-{orgId}-cmk``
  2. IAM Execution Role           — ``mdx-{orgId}-execution-role``
  3. SQS Queues (FIFO + standard):
       - ``mdx-{orgId}-hl7-inbound.fifo``      (HL7 MLLP inbound, FIFO)
       - ``mdx-{orgId}-healthlake-inbound``     (HealthLake write queue)
       - ``mdx-{orgId}-webhook-queue``          (Outbound webhook delivery)
       - ``mdx-{orgId}-file-inbound``           (File-based ingest)
       - ``mdx-{orgId}-dlq``                    (Dead-letter queue)
  4. EventBridge Custom Bus       — ``mdx-{orgId}-bus``
  5. EventBridge Rules            — resource-type routing rules
  6. S3 Prefixes                  — tags bucket-level markers (buckets are
                                    shared; per-org isolation is via
                                    key prefix + bucket policy)

Input (from validate state):
    {
        "orgId":      str
        "orgName":    str
        "adminEmail": str
        "alertEmail": str   (optional)
        "webhookUrl": str   (optional)
        "validated":  true
    }

Output — same input dict extended with:
    {
        "kmsKeyArn":         str
        "iamRoleArn":        str
        "sqsFifoQueueUrl":   str
        "sqsAlertQueueUrl":  str
        "sqsDlqUrl":         str
        "eventBusArn":       str
        "s3InputBucket":     str
        "s3InputPrefix":     str
        "s3OutputBucket":    str
        "s3OutputPrefix":    str
        "s3ReportsBucket":   str
    }

Requirements: 8.1, 8.2
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Environment variables (injected by CDK)
# ---------------------------------------------------------------------------

PLATFORM_ROLE_ARN = os.environ.get("PLATFORM_ADMIN_ROLE_ARN", "")
AWS_ACCOUNT_ID = os.environ.get("AWS_ACCOUNT_ID", "")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
S3_DATA_BUCKET = os.environ.get("MDX_PLATFORM_DATA_BUCKET", "mdx-platform-data")

# ---------------------------------------------------------------------------
# Boto3 clients (module-level for warm-container reuse)
# ---------------------------------------------------------------------------

_kms = boto3.client("kms", region_name=AWS_REGION)
_iam = boto3.client("iam", region_name=AWS_REGION)
_sqs = boto3.client("sqs", region_name=AWS_REGION)
_events = boto3.client("events", region_name=AWS_REGION)
_s3 = boto3.client("s3", region_name=AWS_REGION)


# ---------------------------------------------------------------------------
# KMS CMK creation
# ---------------------------------------------------------------------------


def _create_kms_key(org_id: str) -> str:
    """
    Create a per-org KMS CMK with 365-day rotation enabled.

    Returns the key ARN.
    """
    alias_name = f"alias/mdx-{org_id}-cmk"

    # Check if alias already exists (idempotency)
    try:
        existing = _kms.describe_key(KeyId=alias_name)
        key_arn: str = existing["KeyMetadata"]["Arn"]
        logger.info("KMS key already exists for org_id='%s': %s", org_id, key_arn)
        return key_arn
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NotFoundException":
            raise

    # Build key policy
    key_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "EnableRootAccountAdministration",
                "Effect": "Allow",
                "Principal": {"AWS": f"arn:aws:iam::{AWS_ACCOUNT_ID}:root"},
                "Action": "kms:*",
                "Resource": "*",
            },
            {
                "Sid": "AllowPlatformAdminAccess",
                "Effect": "Allow",
                "Principal": {"AWS": PLATFORM_ROLE_ARN} if PLATFORM_ROLE_ARN else {"AWS": f"arn:aws:iam::{AWS_ACCOUNT_ID}:root"},
                "Action": [
                    "kms:Decrypt",
                    "kms:GenerateDataKey",
                    "kms:DescribeKey",
                ],
                "Resource": "*",
            },
        ],
    }

    response = _kms.create_key(
        Description=f"Medyrax per-org CMK for org {org_id}",
        KeyUsage="ENCRYPT_DECRYPT",
        KeySpec="SYMMETRIC_DEFAULT",
        EnableKeyRotation=True,
        Policy=json.dumps(key_policy),
        Tags=[
            {"TagKey": "MdxOrgId", "TagValue": org_id},
            {"TagKey": "MdxComponent", "TagValue": "KmsCmk"},
        ],
    )
    key_arn = response["KeyMetadata"]["Arn"]

    # Create alias
    _kms.create_alias(
        AliasName=alias_name,
        TargetKeyId=key_arn,
    )

    # Enable annual rotation (must be done separately for imported keys)
    _kms.enable_key_rotation(KeyId=key_arn)

    logger.info("Created KMS CMK for org_id='%s': %s", org_id, key_arn)
    return key_arn


# ---------------------------------------------------------------------------
# IAM Role creation
# ---------------------------------------------------------------------------


def _create_iam_role(org_id: str, kms_key_arn: str) -> str:
    """
    Create a per-org IAM execution role with least-privilege policies.

    Returns the role ARN.
    """
    role_name = f"mdx-{org_id}-execution-role"

    # Idempotent — return existing role ARN if present
    try:
        existing = _iam.get_role(RoleName=role_name)
        role_arn: str = existing["Role"]["Arn"]
        logger.info("IAM role already exists for org_id='%s': %s", org_id, role_arn)
        return role_arn
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise

    assume_role_policy = json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
    )

    response = _iam.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=assume_role_policy,
        Description=f"Medyrax execution role for org {org_id}",
        Tags=[
            {"Key": "MdxOrgId", "Value": org_id},
            {"Key": "MdxComponent", "Value": "OrgExecutionRole"},
        ],
    )
    role_arn = response["Role"]["Arn"]

    # Inline policy: KMS decrypt + generate data key on org CMK only
    kms_policy = json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "AllowOrgCmkUsage",
                    "Effect": "Allow",
                    "Action": [
                        "kms:Decrypt",
                        "kms:GenerateDataKey",
                        "kms:DescribeKey",
                    ],
                    "Resource": kms_key_arn,
                }
            ],
        }
    )
    _iam.put_role_policy(
        RoleName=role_name,
        PolicyName="MdxOrgKmsPolicy",
        PolicyDocument=kms_policy,
    )

    # Attach AWS managed Lambda basic execution role
    _iam.attach_role_policy(
        RoleName=role_name,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    )

    logger.info("Created IAM role for org_id='%s': %s", org_id, role_arn)
    return role_arn


# ---------------------------------------------------------------------------
# SQS Queue creation
# ---------------------------------------------------------------------------


def _create_sqs_queue(
    queue_name: str,
    kms_key_arn: str,
    *,
    fifo: bool = False,
    dlq_arn: str | None = None,
) -> str:
    """
    Create an SQS queue (FIFO or standard) encrypted with the org's CMK.

    Returns the queue URL.
    """
    attrs: dict[str, str] = {
        "KmsMasterKeyId": kms_key_arn,
        "MessageRetentionPeriod": "1209600",  # 14 days
    }

    if fifo:
        attrs["FifoQueue"] = "true"
        attrs["ContentBasedDeduplication"] = "true"
        if not queue_name.endswith(".fifo"):
            queue_name = f"{queue_name}.fifo"

    if dlq_arn:
        attrs["RedrivePolicy"] = json.dumps(
            {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "3"}
        )

    # Idempotent — GetQueueUrl raises QueueDoesNotExist on miss
    try:
        url_response = _sqs.get_queue_url(QueueName=queue_name)
        queue_url: str = url_response["QueueUrl"]
        logger.info("SQS queue already exists: %s", queue_url)
        return queue_url
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "AWS.SimpleQueueService.NonExistentQueue":
            raise

    response = _sqs.create_queue(
        QueueName=queue_name,
        Attributes=attrs,
        tags={"MdxComponent": "OrgQueue"},
    )
    queue_url = response["QueueUrl"]
    logger.info("Created SQS queue: %s", queue_url)
    return queue_url


def _get_queue_arn(queue_url: str) -> str:
    """Return the ARN of a queue given its URL."""
    attrs = _sqs.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=["QueueArn"],
    )
    return attrs["Attributes"]["QueueArn"]


def _create_queues(org_id: str, kms_key_arn: str) -> dict[str, str]:
    """
    Create all per-org SQS queues.

    Returns a dict with keys:
        fifo_url, alert_url, dlq_url
    """
    # DLQ first (needed for redrive policy on other queues)
    dlq_url = _create_sqs_queue(
        f"mdx-{org_id}-dlq",
        kms_key_arn,
        fifo=False,
    )
    dlq_arn = _get_queue_arn(dlq_url)

    # HL7 MLLP inbound FIFO queue
    hl7_fifo_url = _create_sqs_queue(
        f"mdx-{org_id}-hl7-inbound",
        kms_key_arn,
        fifo=True,
        dlq_arn=dlq_arn,
    )

    # HealthLake write queue
    _create_sqs_queue(
        f"mdx-{org_id}-healthlake-inbound",
        kms_key_arn,
        fifo=False,
        dlq_arn=dlq_arn,
    )

    # Webhook delivery queue
    _create_sqs_queue(
        f"mdx-{org_id}-webhook-queue",
        kms_key_arn,
        fifo=False,
        dlq_arn=dlq_arn,
    )

    # File inbound queue
    _create_sqs_queue(
        f"mdx-{org_id}-file-inbound",
        kms_key_arn,
        fifo=False,
        dlq_arn=dlq_arn,
    )

    # Alert queue (standard, for clinical alerts — not FIFO)
    alert_url = _create_sqs_queue(
        f"mdx-{org_id}-alert-queue",
        kms_key_arn,
        fifo=False,
        dlq_arn=dlq_arn,
    )

    return {
        "fifo_url": hl7_fifo_url,
        "alert_url": alert_url,
        "dlq_url": dlq_url,
    }


# ---------------------------------------------------------------------------
# EventBridge Bus creation
# ---------------------------------------------------------------------------


def _create_event_bus(org_id: str, kms_key_arn: str) -> str:
    """
    Create the per-org EventBridge custom bus and resource-type routing rules.

    Returns the bus ARN.
    """
    bus_name = f"mdx-{org_id}-bus"

    try:
        desc = _events.describe_event_bus(Name=bus_name)
        bus_arn: str = desc["Arn"]
        logger.info("EventBridge bus already exists for org_id='%s': %s", org_id, bus_arn)
        return bus_arn
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("ResourceNotFoundException", "NotFoundException"):
            raise

    response = _events.create_event_bus(
        Name=bus_name,
        Tags=[
            {"Key": "MdxOrgId", "Value": org_id},
            {"Key": "MdxComponent", "Value": "OrgEventBus"},
        ],
    )
    bus_arn = response["EventBusArn"]
    logger.info("Created EventBridge bus for org_id='%s': %s", org_id, bus_arn)
    return bus_arn


# ---------------------------------------------------------------------------
# S3 prefix markers (virtual folder via zero-byte objects)
# ---------------------------------------------------------------------------


def _ensure_s3_prefix(bucket: str, prefix: str) -> None:
    """
    Write a zero-byte S3 marker object to establish a logical prefix.

    This is idempotent — if the object already exists, the put is a no-op.
    """
    try:
        _s3.put_object(
            Bucket=bucket,
            Key=prefix,
            Body=b"",
            ServerSideEncryption="aws:kms",
        )
        logger.info("Ensured S3 prefix s3://%s/%s", bucket, prefix)
    except ClientError as exc:
        logger.warning("Could not write S3 prefix %s/%s: %s", bucket, prefix, exc)


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Create per-org AWS resources (KMS, IAM, SQS, EventBridge, S3 prefixes).

    Parameters
    ----------
    event:
        Step Function state input — validated provisioning request.
    context:
        AWS Lambda context object (unused).

    Returns
    -------
    dict
        Input dict extended with all created resource ARNs/URLs.
    """
    org_id: str = event["orgId"]
    logger.info("Creating AWS resources for org_id='%s'", org_id)

    # 1. KMS CMK
    kms_key_arn = _create_kms_key(org_id)

    # 2. IAM Role
    iam_role_arn = _create_iam_role(org_id, kms_key_arn)

    # 3. SQS Queues
    queues = _create_queues(org_id, kms_key_arn)

    # 4. EventBridge Bus
    event_bus_arn = _create_event_bus(org_id, kms_key_arn)

    # 5. S3 prefixes (logical per-org partitions within the shared platform bucket)
    s3_input_prefix = f"{org_id}/inbound/"
    s3_output_prefix = f"{org_id}/outbound/"
    s3_reports_prefix = f"{org_id}/reports/"

    if S3_DATA_BUCKET and not S3_DATA_BUCKET.startswith("arn:"):
        _ensure_s3_prefix(S3_DATA_BUCKET, s3_input_prefix)
        _ensure_s3_prefix(S3_DATA_BUCKET, s3_output_prefix)
        _ensure_s3_prefix(S3_DATA_BUCKET, s3_reports_prefix)

    logger.info(
        "All AWS resources created successfully for org_id='%s'", org_id
    )

    return {
        **event,
        "kmsKeyArn": kms_key_arn,
        "iamRoleArn": iam_role_arn,
        "sqsFifoQueueUrl": queues["fifo_url"],
        "sqsAlertQueueUrl": queues["alert_url"],
        "sqsDlqUrl": queues["dlq_url"],
        "eventBusArn": event_bus_arn,
        "s3InputBucket": S3_DATA_BUCKET,
        "s3InputPrefix": s3_input_prefix,
        "s3OutputBucket": S3_DATA_BUCKET,
        "s3OutputPrefix": s3_output_prefix,
        "s3ReportsBucket": S3_DATA_BUCKET,
    }
