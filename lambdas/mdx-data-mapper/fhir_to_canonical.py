"""
FHIRToCanonicalParser — parse FHIR R4 JSON resources into CanonicalMessage.

Supports Patient, Encounter, Observation, DiagnosticReport, Condition,
ServiceRequest, Bundle.  FHIR Extension elements are preserved in
``extension_map`` for round-trip integrity (Requirement 13.2, 13.4).

Requirements: 13.1, 13.2, 13.4
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class FHIRToCanonicalParser:
    """
    Parse a FHIR R4 resource dict (or JSON string) into a CanonicalMessage.
    """

    def parse(self, fhir_resource: Any, org_id: str = "") -> Any:
        """
        Parse ``fhir_resource`` (dict or JSON string) to CanonicalMessage.

        Parameters
        ----------
        fhir_resource:
            FHIR R4 resource as a Python dict or JSON string.
        org_id:
            Owning org identifier.

        Returns
        -------
        CanonicalMessage
        """
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from mdx_common.models import CanonicalMessage  # type: ignore

        if isinstance(fhir_resource, str):
            try:
                resource = json.loads(fhir_resource)
            except json.JSONDecodeError as exc:
                from mdx_common.errors import TransformationError  # type: ignore
                raise TransformationError(
                    message=f"Invalid FHIR JSON: {exc}",
                    source_format="FHIR_R4",
                    target_format="Canonical",
                ) from exc
        else:
            resource = fhir_resource

        raw_str = json.dumps(resource, sort_keys=True)
        sha256 = hashlib.sha256(raw_str.encode()).hexdigest()

        canonical = CanonicalMessage(
            raw_source=raw_str,
            source_sha256=sha256,
        )

        resource_type = resource.get("resourceType", "")

        if resource_type == "Bundle":
            self._parse_bundle(resource, canonical, org_id)
        elif resource_type == "Patient":
            self._parse_patient(resource, canonical)
        elif resource_type == "Encounter":
            self._parse_encounter(resource, canonical)
        elif resource_type == "Observation":
            self._parse_observation(resource, canonical, 0)
        elif resource_type == "DiagnosticReport":
            self._parse_diagnostic_report(resource, canonical, 0)
        elif resource_type == "Condition":
            self._parse_condition(resource, canonical, 0)
        else:
            # Generic — capture all top-level fields as FHIR elements
            for k, v in resource.items():
                if isinstance(v, (str, int, float, bool)):
                    canonical.fhir_elements[f"{resource_type}.{k}"] = str(v)

        # Preserve FHIR extensions as extension_map entries
        exts = resource.get("extension") or []
        for ext in exts:
            url = ext.get("url", "")
            value_key = next((k for k in ext if k.startswith("value")), None)
            if url and value_key:
                canonical.extension_map[url] = ext[value_key]

        canonical.fhir_elements["resourceType"] = resource_type
        canonical.fhir_elements["orgId"] = org_id
        return canonical

    # ------------------------------------------------------------------
    # Resource-specific parsers
    # ------------------------------------------------------------------

    def _parse_bundle(self, resource: dict, canonical: Any, org_id: str) -> None:
        for i, entry in enumerate(resource.get("entry", [])):
            res = entry.get("resource", {})
            rt = res.get("resourceType", "")
            if rt == "Patient":
                self._parse_patient(res, canonical)
            elif rt == "Encounter":
                self._parse_encounter(res, canonical)
            elif rt == "Observation":
                self._parse_observation(res, canonical, i)
            elif rt == "Condition":
                self._parse_condition(res, canonical, i)
            elif rt == "DiagnosticReport":
                self._parse_diagnostic_report(res, canonical, i)

    def _parse_patient(self, res: dict, canonical: Any) -> None:
        canonical.patient_id = res.get("id", "")
        names = res.get("name") or []
        if names:
            name = names[0]
            text = name.get("text") or (
                " ".join(name.get("given", [])) + " " + name.get("family", "")
            ).strip()
            canonical.fhir_elements["patient.name"] = text
        canonical.fhir_elements["patient.id"] = canonical.patient_id
        canonical.fhir_elements["patient.birthDate"] = res.get("birthDate", "")
        canonical.fhir_elements["patient.gender"] = res.get("gender", "")
        addrs = res.get("address") or []
        if addrs:
            canonical.fhir_elements["patient.address"] = addrs[0].get("text", "")

    def _parse_encounter(self, res: dict, canonical: Any) -> None:
        cls = res.get("class") or {}
        canonical.fhir_elements["encounter.class"] = cls.get("code", "")
        period = res.get("period") or {}
        canonical.fhir_elements["encounter.admitDate"] = period.get("start", "")
        canonical.fhir_elements["encounter.dischargeDate"] = period.get("end", "")
        location = res.get("location") or []
        if location:
            loc_ref = location[0].get("location", {}).get("reference", "")
            canonical.fhir_elements["encounter.location"] = loc_ref

    def _parse_observation(self, res: dict, canonical: Any, idx: int) -> None:
        code = res.get("code") or {}
        codings = code.get("coding") or [{}]
        canonical.fhir_elements[f"observation[{idx}].code"] = (
            codings[0].get("code") or code.get("text", "")
        )
        # valueQuantity
        vq = res.get("valueQuantity")
        if vq:
            canonical.fhir_elements[f"observation[{idx}].value"] = str(vq.get("value", ""))
            canonical.fhir_elements[f"observation[{idx}].units"] = vq.get("unit", "")
        elif "valueString" in res:
            canonical.fhir_elements[f"observation[{idx}].value"] = res["valueString"]
        canonical.fhir_elements[f"observation[{idx}].status"] = res.get("status", "final")

    def _parse_diagnostic_report(self, res: dict, canonical: Any, idx: int) -> None:
        code = res.get("code") or {}
        codings = code.get("coding") or [{}]
        canonical.fhir_elements[f"diagnosticReport[{idx}].code"] = (
            codings[0].get("code") or code.get("text", "")
        )
        canonical.fhir_elements[f"diagnosticReport[{idx}].orderDate"] = res.get("effectiveDateTime", "")

    def _parse_condition(self, res: dict, canonical: Any, idx: int) -> None:
        code = res.get("code") or {}
        codings = code.get("coding") or [{}]
        canonical.fhir_elements[f"condition[{idx}].code"] = (
            codings[0].get("code") or code.get("text", "")
        )
        canonical.fhir_elements[f"condition[{idx}].description"] = code.get("text", "")
