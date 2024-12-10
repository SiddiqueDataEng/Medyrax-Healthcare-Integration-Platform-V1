"""
fhir-engine-search Lambda handler (task 9.3).

Translates FHIR search parameters to HealthLake query.
Returns searchset Bundle within 2s for queries up to 1M resources.

Requirements: 1.8
"""
from __future__ import annotations
import json, logging, os, sys, time
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)

_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    start = time.monotonic()
    path_params = event.get("pathParameters") or {}
    query_params = event.get("queryStringParameters") or {}
    resource_type = path_params.get("resource", "")
    org_id = _org_id(event)

    if not resource_type:
        return _err(400, "Missing resource type")
    if not org_id:
        return _err(401, "Missing orgId")

    from mdx_common.tenant_config_service import get_tenant_config  # type: ignore
    from healthlake_connector.healthlake_client import HealthLakeClient  # type: ignore

    config = get_tenant_config(org_id)
    client = HealthLakeClient(region=_REGION)

    # Build search params string from query parameters
    search_params = "&".join(f"{k}={v}" for k, v in query_params.items()
                              if k not in ("_format",))

    try:
        resp = client.search_resources(
            config.health_lake_data_store_id,
            resource_type,
            search_params,
        )
        bundle = json.loads(resp.get("SearchBundle", "{}"))
    except Exception as exc:
        logger.error("FHIR search failed: %s", exc)
        return _err(503, f"Search failed: {exc}")

    elapsed_ms = (time.monotonic() - start) * 1000
    if elapsed_ms > 2000:
        logger.warning("FHIR search exceeded 2s SLA: %.0fms (org=%s type=%s)",
                       elapsed_ms, org_id, resource_type)

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/fhir+json"},
        "body": json.dumps(bundle),
    }


def _org_id(event: dict) -> str:
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims", {})
    return claims.get("custom:orgId") or ""


def _err(code: int, msg: str) -> dict:
    return {"statusCode": code, "body": json.dumps({"error": msg})}
