"""
analytics-everything Lambda (task 18.4).

GET /v1/fhir/r4/Patient/{patientId}/$everything
Queries HealthLake for all resources with patient={patientId}.
Returns a FHIR Bundle response.

Requirements: 11.6
"""
from __future__ import annotations
import json, logging, os, sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

RESOURCE_TYPES = [
    "Encounter", "Observation", "Condition", "MedicationRequest",
    "DiagnosticReport", "AllergyIntolerance", "Procedure", "Coverage",
]


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    path_params = event.get("pathParameters") or {}
    patient_id = path_params.get("patientId", "")
    org_id = _org_id(event)

    if not patient_id:
        return _err(400, "Missing patientId")
    if not org_id:
        return _err(401, "Missing orgId")

    from mdx_common.tenant_config_service import get_tenant_config  # type: ignore
    from healthlake_connector.healthlake_client import HealthLakeClient  # type: ignore

    config = get_tenant_config(org_id)
    client = HealthLakeClient(region=_REGION)

    entries = []

    # Fetch Patient resource
    try:
        resp = client.get_resource(config.health_lake_data_store_id, "Patient", patient_id)
        patient = json.loads(resp.get("Resource", "{}"))
        if patient:
            entries.append({"fullUrl": f"Patient/{patient_id}", "resource": patient})
    except Exception as exc:
        logger.warning("Patient fetch failed: %s", exc)

    # Fetch all related resource types
    for resource_type in RESOURCE_TYPES:
        try:
            resp = client.search_resources(
                config.health_lake_data_store_id,
                resource_type,
                f"patient={patient_id}&_count=100",
            )
            bundle = json.loads(resp.get("SearchBundle", "{}"))
            for entry in bundle.get("entry", []):
                entries.append(entry)
        except Exception as exc:
            logger.warning("Failed to fetch %s for patient %s: %s", resource_type, patient_id, exc)

    result_bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(entries),
        "entry": entries,
    }
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/fhir+json"},
        "body": json.dumps(result_bundle),
    }


def _org_id(event: dict) -> str:
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims", {})
    return claims.get("custom:orgId") or ""


def _err(code: int, msg: str) -> dict:
    return {"statusCode": code, "body": json.dumps({"error": msg})}
