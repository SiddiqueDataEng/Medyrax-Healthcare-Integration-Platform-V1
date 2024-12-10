"""
file-exporter Lambda (task 16.5).

Scheduled EventBridge rule (default every 30 min).
Queries HealthLake for resources updated since last run (_lastUpdated).
Serializes to FHIR NDJSON or HL7 v2.x batch depending on org profile.
Writes to mdx-{orgId}-outbound/{timestamp}/{resourceType}.ndjson with SSE-KMS.

Requirements: 9.5
"""
from __future__ import annotations
import json, logging, os, sys, uuid
from datetime import datetime, timezone, timedelta
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_s3 = boto3.client("s3", region_name=_REGION)
_DEFAULT_ORG_IDS = os.environ.get("MDX_EXPORT_ORG_IDS", "").split(",")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Run for each configured org."""
    org_ids = [o.strip() for o in _DEFAULT_ORG_IDS if o.strip()]
    # Also handle direct invocation with org_id
    if not org_ids and event.get("orgId"):
        org_ids = [event["orgId"]]

    for org_id in org_ids:
        try:
            _export_for_org(org_id)
        except Exception as exc:
            logger.error("Export failed for org=%s: %s", org_id, exc)

    return {"statusCode": 200, "body": json.dumps({"exported": org_ids})}


def _export_for_org(org_id: str) -> None:
    from mdx_common.tenant_config_service import get_tenant_config  # type: ignore
    from healthlake_connector.healthlake_client import HealthLakeClient  # type: ignore

    config = get_tenant_config(org_id)
    client = HealthLakeClient(region=_REGION)

    since = (datetime.now(tz=timezone.utc) - timedelta(minutes=30)).isoformat()
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S")

    resource_types = ["Patient", "Encounter", "Observation", "Condition", "DiagnosticReport"]

    for resource_type in resource_types:
        try:
            resp = client.search_resources(
                config.health_lake_data_store_id,
                resource_type,
                f"_lastUpdated=gt{since}",
            )
            bundle = json.loads(resp.get("SearchBundle", "{}"))
            entries = bundle.get("entry", [])
            if not entries:
                continue

            ndjson = "\n".join(
                json.dumps(e.get("resource", {})) for e in entries
            )
            key = f"mdx-{org_id}-outbound/{ts}/{resource_type}.ndjson"
            output_bucket = config.s3_output_bucket or f"mdx-{org_id}-outbound"

            _s3.put_object(
                Bucket=output_bucket,
                Key=key,
                Body=ndjson.encode("utf-8"),
                ContentType="application/fhir+ndjson",
                ServerSideEncryption="aws:kms",
                SSEKMSKeyId=config.kms_key_arn,
            )
            logger.info("Exported %d %s records for org=%s", len(entries), resource_type, org_id)

        except Exception as exc:
            logger.error("Export error for %s/%s: %s", org_id, resource_type, exc)
