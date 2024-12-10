"""
healthlake-export-trigger Lambda (task 11.3).

Accepts $export request, starts HealthLake StartFHIRExportJob.
The Step Function (mdx-healthlake-export-sfn) polls DescribeFHIRExportJob,
then publishes healthlake.export.complete event with S3 location and manifest.

Requirements: 3.5, 3.6
"""
from __future__ import annotations
import json, logging, os, sys, uuid
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_SFN_ARN = os.environ.get("MDX_EXPORT_SFN_ARN", "")
_S3_OUTPUT_BUCKET = os.environ.get("MDX_EXPORT_OUTPUT_BUCKET", "mdx-analytics")
_sfn = boto3.client("stepfunctions", region_name=_REGION)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    from mdx_common.tenant_config_service import get_tenant_config  # type: ignore
    from healthlake_client import HealthLakeClient  # type: ignore

    org_id = _org_id(event)
    if not org_id:
        return _err(401, "Missing orgId")

    config = get_tenant_config(org_id)
    client = HealthLakeClient(region=_REGION)

    output_uri = f"s3://{_S3_OUTPUT_BUCKET}/{org_id}/exports/"
    job_id = client.start_export(config.health_lake_data_store_id, output_uri)

    # Start Step Function to poll job completion
    if _SFN_ARN:
        _sfn.start_execution(
            stateMachineArn=_SFN_ARN,
            name=f"export-{org_id}-{job_id[:8]}",
            input=json.dumps({
                "orgId": org_id,
                "jobId": job_id,
                "dataStoreId": config.health_lake_data_store_id,
                "outputUri": output_uri,
            }),
        )

    return {
        "statusCode": 202,
        "body": json.dumps({"jobId": job_id, "status": "SUBMITTED", "outputUri": output_uri}),
    }


def _org_id(event: dict) -> str:
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims", {})
    return claims.get("custom:orgId") or ""


def _err(code: int, msg: str) -> dict:
    return {"statusCode": code, "body": json.dumps({"error": msg})}
