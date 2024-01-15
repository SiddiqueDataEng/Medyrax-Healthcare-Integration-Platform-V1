"""
tenant-provisioner-sftp Lambda
==================================
Step 4 of the ``mdx-org-provision-sfn`` Step Function.

Creates an AWS Transfer Family SFTP server endpoint with a per-org S3
home-directory mapping so that the Connected_Organization's SFTP client
can land files directly in ``s3://{dataBucket}/{orgId}/inbound/``.

Design decisions:
  - One Transfer Family server per environment is provisioned at the
    platform level.  This Lambda creates a *user* on that server (or the
    server itself when ``TRANSFER_SERVER_ID`` env var is not set, which
    happens during first-org provisioning).
  - If the platform-level server already exists (``TRANSFER_SERVER_ID``
    env var is set), only a per-org SFTP user is created.
  - The SFTP user is named after the org_id.
  - The S3 home directory is mapped to ``/{dataBucket}/{orgId}/inbound/``.
  - Access is controlled by the org's IAM execution role.
  - All files landing in S3 are encrypted with the org's CMK
    (enforced by the bucket policy created in the aws_resources step).

Input (from healthlake state):
    {
        "orgId":          str
        "iamRoleArn":     str
        "kmsKeyArn":      str
        "s3InputBucket":  str
        "s3InputPrefix":  str
        … other fields …
    }

Output — input extended with:
    {
        "sftpServerId":   str   — Transfer Family server ID
        "sftpEndpoint":   str   — SFTP hostname (e.g. s-xxxx.server.transfer.us-east-1.amazonaws.com)
    }

Requirements: 8.1, 8.2, 9.1
"""

from __future__ import annotations

import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
# Pre-provisioned platform-level Transfer Family server ID (optional).
# When set, only an SFTP user is created; the server itself is reused.
TRANSFER_SERVER_ID = os.environ.get("MDX_TRANSFER_SERVER_ID", "")

# ---------------------------------------------------------------------------
# Boto3 client
# ---------------------------------------------------------------------------

_transfer = boto3.client("transfer", region_name=AWS_REGION)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_or_create_sftp_server() -> tuple[str, str]:
    """
    Return (server_id, endpoint) for the platform-level SFTP server.

    If ``TRANSFER_SERVER_ID`` is set, describe the existing server.
    Otherwise create a new SFTP-only server backed by S3.

    Returns
    -------
    tuple[str, str]
        (server_id, hostname)
    """
    if TRANSFER_SERVER_ID:
        # Describe existing server to get endpoint
        try:
            response = _transfer.describe_server(ServerId=TRANSFER_SERVER_ID)
            server = response["Server"]
            server_id: str = server["ServerId"]
            endpoint: str = f"{server_id}.server.transfer.{AWS_REGION}.amazonaws.com"
            logger.info(
                "Reusing existing Transfer Family server: %s", server_id
            )
            return server_id, endpoint
        except ClientError as exc:
            logger.error(
                "Failed to describe Transfer Family server '%s': %s",
                TRANSFER_SERVER_ID,
                exc,
            )
            raise

    # Create a new platform-level SFTP server
    response = _transfer.create_server(
        Protocols=["SFTP"],
        Domain="S3",
        IdentityProviderType="SERVICE_MANAGED",
        EndpointType="PUBLIC",
        SecurityPolicyName="TransferSecurityPolicy-2024-01",
        Tags=[
            {"Key": "MdxComponent", "Value": "SftpServer"},
            {"Key": "MdxPlatform", "Value": "Medyrax"},
        ],
    )
    server_id = response["ServerId"]
    endpoint = f"{server_id}.server.transfer.{AWS_REGION}.amazonaws.com"
    logger.info("Created new Transfer Family SFTP server: %s", server_id)
    return server_id, endpoint


def _create_sftp_user(
    server_id: str,
    org_id: str,
    iam_role_arn: str,
    s3_input_bucket: str,
    s3_input_prefix: str,
) -> None:
    """
    Create a per-org SFTP user with an S3 home-directory mapping.

    The user name is the org_id (limited to 32 chars, alphanumeric + hyphen).
    The home directory maps to ``/{s3_input_bucket}/{org_id}/inbound/``.

    Idempotent — if the user already exists, the call is a no-op.
    """
    # Transfer Family usernames are limited to 32 chars, but org IDs can be
    # up to 63 chars.  Truncate to 32 and strip trailing hyphens.
    username = org_id[:32].rstrip("-")

    # Check if user already exists
    try:
        _transfer.describe_user(ServerId=server_id, UserName=username)
        logger.info(
            "SFTP user '%s' already exists on server '%s'", username, server_id
        )
        return
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in (
            "ResourceNotFoundException",
        ):
            raise

    # Determine the S3 home directory key
    # Transfer Family expects the path as /{bucket}/{prefix} without trailing slash
    home_dir = f"/{s3_input_bucket}/{s3_input_prefix.rstrip('/')}"

    _transfer.create_user(
        ServerId=server_id,
        UserName=username,
        Role=iam_role_arn,
        HomeDirectory=home_dir,
        HomeDirectoryType="PATH",
        Tags=[
            {"Key": "MdxOrgId", "Value": org_id},
            {"Key": "MdxComponent", "Value": "SftpUser"},
        ],
    )
    logger.info(
        "Created SFTP user '%s' on server '%s' with home '%s'",
        username,
        server_id,
        home_dir,
    )


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Create AWS Transfer Family SFTP server/user for the new org.

    Parameters
    ----------
    event:
        Step Function state input — must include ``orgId``, ``iamRoleArn``,
        ``s3InputBucket``, and ``s3InputPrefix``.
    context:
        AWS Lambda context object (unused).

    Returns
    -------
    dict
        Input extended with ``sftpServerId`` and ``sftpEndpoint``.
    """
    org_id: str = event["orgId"]
    iam_role_arn: str = event["iamRoleArn"]
    s3_input_bucket: str = event["s3InputBucket"]
    s3_input_prefix: str = event["s3InputPrefix"]

    logger.info("Provisioning SFTP endpoint for org_id='%s'", org_id)

    # 1. Get or create the platform-level SFTP server
    server_id, sftp_endpoint = _get_or_create_sftp_server()

    # 2. Create per-org SFTP user with S3 home directory mapping
    _create_sftp_user(
        server_id=server_id,
        org_id=org_id,
        iam_role_arn=iam_role_arn,
        s3_input_bucket=s3_input_bucket,
        s3_input_prefix=s3_input_prefix,
    )

    logger.info(
        "SFTP provisioning complete for org_id='%s': server=%s endpoint=%s",
        org_id,
        server_id,
        sftp_endpoint,
    )

    return {
        **event,
        "sftpServerId": server_id,
        "sftpEndpoint": sftp_endpoint,
    }
