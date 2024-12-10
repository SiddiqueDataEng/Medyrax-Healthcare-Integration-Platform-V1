"""
telehealth-presync Lambda (task 17.2).

GET /v1/fhir/r4/integration/telehealth/patient/{patientId}/presync
Queries HealthLake for Patient resource and prior Encounter bundle.
Compresses with gzip when Accept-Encoding: gzip present.
Returns within 2s SLA.

Requirements: 10.3, 10.5
"""
from __future__ import annotations
import base64, gzip, json, logging, os, sys, time
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    start = time.monotonic()
    org_id = _org_id(event)
    if not org_id:
        return _err(401, "Missing orgId")

    path_params = event.get("pathParameters") or {}
    patient_id = path_params.get("patientId", "")
    if not patient_id:
        return _err(400, "Missing patientId")

    accept_gzip = "gzip" in (event.get("headers") or {}).get("Accept-Encoding", "")

    from mdx_common.tenant_config_service import get_tenant_config  # type: ignore
    from healthlake_connector.healthlake_client import HealthLakeClient  # type: ignore

    config = get_tenant_config(org_id)
    client = HealthLakeClient(region=_REGION)

    bundle_entries = []

    # Fetch Patient
    try:
        resp = client.get_resource(config.health_lake_data_store_id, "Patient", patient_id)
        bundle_entries.append({"resource": json.loads(resp.get("Resource", "{}"))})
    except Exception as exc:
        logger.warning("Could not fetch Patient %s: %s", patient_id, exc)

    # Fetch Encounters for this patient
    try:
        resp = client.search_resources(
            config.health_lake_data_store_id, "Encounter",
            f"patient={patient_id}&_count=10&_sort=-date"
        )
        enc_bundle = json.loads(resp.get("SearchBundle", "{}"))
        bundle_entries.extend(enc_bundle.get("entry", []))
    except Exception as exc:
        logger.warning("Could not fetch Encounters for %s: %s", patient_id, exc)

    response_bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(bundle_entries),
        "entry": bundle_entries,
    }

    body_bytes = json.dumps(response_bundle).encode("utf-8")
    elapsed = (time.monotonic() - start) * 1000
    if elapsed > 2000:
        logger.warning("presync exceeded 2s SLA: %.0fms for org=%s", elapsed, org_id)

    if accept_gzip:
        compressed = gzip.compress(body_bytes)
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/fhir+json",
                "Content-Encoding": "gzip",
            },
            "isBase64Encoded": True,
            "body": base64.b64encode(compressed).decode("ascii"),
        }

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/fhir+json"},
        "body": body_bytes.decode("utf-8"),
    }


def _org_id(event: dict) -> str:
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims", {})
    return claims.get("custom:orgId") or ""


def _err(code: int, msg: str) -> dict:
    return {"statusCode": code, "body": json.dumps({"error": msg})}
