"""
healthlake-reader Lambda (task 11.2).

Serves GET and search requests via HealthLake GetResource/SearchWithGet.
Enforces tenant isolation: always passes dataStoreId from caller's tenant config.
Rejects if dataStoreId mismatch detected.
Returns results within 2s SLA.

Requirements: 3.4, 3.7
"""
from __future__ import annotations
import json, logging, os, sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    from mdx_common.tenant_config_service import get_tenant_config  # type: ignore
    from healthlake_client import HealthLakeClient  # type: ignore

    path_params = event.get("pathParameters") or {}
    query_params = event.get("queryStringParameters") or {}
    http_method = (event.get("httpMethod") or "GET").upper()

    resource_type = path_params.get("resource", "")
    resource_id = path_params.get("id", "")
    org_id = _org_id(event)

    if not org_id:
        return _err(401, "Missing orgId in JWT claims")
    if not resource_type:
        return _err(400, "Missing resource type")

    config = get_tenant_config(org_id)
    data_store_id = config.health_lake_data_store_id

    # Tenant isolation: verify caller's claimed dataStoreId matches config
    claimed_ds = query_params.get("dataStoreId")
    if claimed_ds and claimed_ds != data_store_id:
        logger.warning("dataStoreId mismatch: claimed=%s config=%s", claimed_ds, data_store_id)
        return _err(403, "dataStoreId does not match tenant configuration")

    client = HealthLakeClient(region=_REGION)

    try:
        if resource_id and http_method == "GET":
            resp = client.get_resource(data_store_id, resource_type, resource_id)
            return _ok(json.loads(resp.get("Resource", "{}")))
        else:
            # Search mode
            search_str = "&".join(f"{k}={v}" for k, v in query_params.items()
                                  if k != "dataStoreId")
            resp = client.search_resources(data_store_id, resource_type, search_str)
            return _ok(json.loads(resp.get("SearchBundle", "{}")))
    except Exception as exc:
        logger.error("HealthLake read failed: %s", exc)
        return _err(503, f"HealthLake read failed: {exc}")


def _org_id(event: dict) -> str:
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims", {})
    return claims.get("custom:orgId") or claims.get("orgId") or ""


def _ok(body: Any) -> dict:
    return {"statusCode": 200, "headers": {"Content-Type": "application/fhir+json"},
            "body": json.dumps(body)}


def _err(code: int, msg: str) -> dict:
    return {"statusCode": code, "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": msg})}
