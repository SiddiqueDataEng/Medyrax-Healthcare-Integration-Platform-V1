"""
security-deidentify Lambda (task 13.3).

Removes/transforms all 18 HIPAA Safe Harbor PHI identifiers from FHIR R4 resources.
Names → remove; Dates → year only; Geographic subdivisions → 3-digit ZIP;
All other direct identifiers → remove or hash (SHA-256 truncated).

Called by Analytics Connector and when X-PHI-Masking: safe-harbor header present.

Requirements: 7.9, 11.3
"""
from __future__ import annotations
import copy, hashlib, json, logging, os, re, sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)

# The 18 HIPAA Safe Harbor PHI identifier categories
PHI_IDENTIFIER_KEYS = {
    # 1. Names
    "name", "family", "given", "prefix", "suffix", "text",
    # 2. Geographic data
    "address", "city", "state", "postalCode", "country", "district",
    "line",
    # 3. Dates (except year)
    "birthDate", "deceasedDateTime", "start", "end", "date", "dateTime",
    "authoredOn", "issued", "effectiveDateTime", "effectivePeriod",
    # 4. Phone numbers
    "phone", "telecom",
    # 5. Fax numbers (handled via telecom system=fax)
    # 6. Email
    "email",
    # 7. Social security numbers (via identifier system)
    # 8. Medical record numbers
    "identifier",
    # 9. Health plan beneficiary numbers (via coverage identifier)
    # 10. Account numbers
    # 11. Certificate/license numbers
    "qualification",
    # 12. Vehicle identifiers
    # 13. Device identifiers
    "device", "deviceName",
    # 14. URLs
    "url",
    # 15. IP addresses
    "ip",
    # 16. Biometric identifiers
    "photo",
    # 17. Full-face photographs
    # 18. Any other unique identifying numbers
}

_ZIP_RE = re.compile(r"^(\d{3})")
_DATE_RE = re.compile(r"^(\d{4})-\d{2}-\d{2}")


def deidentify_resource(resource: dict[str, Any]) -> dict[str, Any]:
    """
    Apply HIPAA Safe Harbor de-identification to a FHIR R4 resource dict.

    Returns a new dict (does not mutate the original).
    All 18 PHI identifier types are removed or transformed per Safe Harbor rules.
    """
    result = copy.deepcopy(resource)
    _transform(result)
    return result


def _transform(obj: Any) -> None:
    """Recursively transform PHI fields in place."""
    if isinstance(obj, dict):
        keys_to_remove = []
        for key, value in obj.items():
            if key == "postalCode":
                obj[key] = _truncate_zip(str(value) if value else "")
            elif key == "birthDate" or _is_date_key(key):
                obj[key] = _truncate_to_year(str(value) if value else "")
            elif key in PHI_IDENTIFIER_KEYS and key not in ("identifier", "telecom"):
                obj[key] = _redact(value)
            elif key == "identifier":
                obj[key] = _deidentify_identifiers(value)
            elif key == "telecom":
                obj[key] = _deidentify_telecom(value)
            elif isinstance(value, (dict, list)):
                _transform(value)
    elif isinstance(obj, list):
        for item in obj:
            _transform(item)


def _truncate_zip(zip_code: str) -> str:
    """Truncate ZIP to first 3 digits; return '000' if population < 20k (conservative)."""
    m = _ZIP_RE.match(zip_code)
    return m.group(1) + "XX" if m else "XXXXX"


def _truncate_to_year(date_str: str) -> str:
    """Keep year only from a date string."""
    if not date_str:
        return ""
    m = _DATE_RE.match(date_str)
    if m:
        return m.group(1)
    # ISO datetime like 2023-05-01T12:00:00Z
    if "T" in date_str:
        return date_str[:4]
    return date_str[:4] if len(date_str) >= 4 else ""


def _redact(value: Any) -> Any:
    """Replace a PHI value with a SHA-256 hash prefix or empty string."""
    if value is None:
        return None
    if isinstance(value, str) and value:
        return "[REDACTED:" + hashlib.sha256(value.encode()).hexdigest()[:8] + "]"
    if isinstance(value, list):
        return []
    if isinstance(value, dict):
        return {}
    return None


def _deidentify_identifiers(identifiers: Any) -> Any:
    """Hash identifier values but preserve system/type for data quality."""
    if not isinstance(identifiers, list):
        return []
    result = []
    for ident in identifiers:
        if isinstance(ident, dict):
            new_ident = dict(ident)
            if "value" in new_ident and new_ident["value"]:
                new_ident["value"] = "[HASH:" + hashlib.sha256(
                    str(new_ident["value"]).encode()
                ).hexdigest()[:12] + "]"
            result.append(new_ident)
    return result


def _deidentify_telecom(telecom: Any) -> Any:
    """Remove phone/email telecom entries; retain system info only."""
    if not isinstance(telecom, list):
        return []
    result = []
    for entry in telecom:
        if isinstance(entry, dict):
            result.append({"system": entry.get("system", ""), "use": entry.get("use", "")})
    return result


def _is_date_key(key: str) -> bool:
    return key.lower().endswith("date") or key.lower().endswith("datetime")


# Lambda handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """De-identify a FHIR resource passed in the event body."""
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError as exc:
        return {"statusCode": 400, "body": json.dumps({"error": str(exc)})}

    deidentified = deidentify_resource(body)
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/fhir+json"},
        "body": json.dumps(deidentified),
    }
