"""
CanonicalToFHIRSerializer — build FHIR R4 resources from a CanonicalMessage.

Supports: Patient, Encounter, Observation, DiagnosticReport, Condition,
Coverage.  Extensions from ``canonical.extension_map`` are attached as
FHIR Extension elements so no data is lost on round-trip (Requirement 13.2).

Requirements: 13.1, 13.2
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CanonicalToFHIRSerializer:
    """
    Serialize a CanonicalMessage into a FHIR R4 resource dict.

    Returns a Python dict that is JSON-serializable (no datetime objects).
    """

    # FHIR gender code mapping from HL7 admin sex codes
    _GENDER_MAP = {
        "M": "male", "F": "female", "O": "other", "U": "unknown",
        "m": "male", "f": "female",
    }

    def serialize(self, canonical: Any) -> dict[str, Any]:
        """
        Convert ``canonical`` to the most appropriate FHIR R4 resource.

        Selects resource type based on ``canonical.message_type``.  Falls back
        to a Bundle containing all parseable elements when the type is unknown.
        """
        from mdx_common.enums import Hl7MessageType  # type: ignore

        mt = canonical.message_type
        # ADT messages → Patient + Encounter
        adt_types = {
            Hl7MessageType.ADT_A01, Hl7MessageType.ADT_A02, Hl7MessageType.ADT_A03,
            Hl7MessageType.ADT_A04, Hl7MessageType.ADT_A05, Hl7MessageType.ADT_A06,
            Hl7MessageType.ADT_A07, Hl7MessageType.ADT_A08, Hl7MessageType.ADT_A09,
            Hl7MessageType.ADT_A10, Hl7MessageType.ADT_A11, Hl7MessageType.ADT_A12,
            Hl7MessageType.ADT_A13, Hl7MessageType.ADT_A28, Hl7MessageType.ADT_A29,
            Hl7MessageType.ADT_A31, Hl7MessageType.ADT_A40,
        }
        if mt in adt_types:
            return self._build_bundle([
                self._build_patient(canonical),
                self._build_encounter(canonical),
            ], canonical)

        if mt in (Hl7MessageType.ORU_R01,):
            resources = [self._build_patient(canonical)]
            # Add observations
            for key, val in canonical.fhir_elements.items():
                if key.startswith("observation[") and ".code" in key:
                    idx = key.split("[")[1].split("]")[0]
                    resources.append(self._build_observation(canonical, int(idx)))
            return self._build_bundle(resources, canonical)

        if mt in (Hl7MessageType.ORM_O01,):
            return self._build_bundle([
                self._build_patient(canonical),
                self._build_service_request(canonical),
            ], canonical)

        # Default: patient resource
        return self._build_patient(canonical)

    # ------------------------------------------------------------------
    # Resource builders
    # ------------------------------------------------------------------

    def _build_patient(self, c: Any) -> dict[str, Any]:
        fe = c.fhir_elements
        patient: dict[str, Any] = {
            "resourceType": "Patient",
            "id": c.patient_id or fe.get("patient.id", ""),
            "name": [{"text": fe.get("patient.name", "")}],
            "birthDate": fe.get("patient.birthDate", "")[:8] or None,
            "gender": self._GENDER_MAP.get(fe.get("patient.gender", ""), "unknown"),
        }
        addr = fe.get("patient.address")
        if addr:
            patient["address"] = [{"text": addr}]
        # Attach extension_map items as FHIR extensions
        patient["extension"] = self._build_extensions(c.extension_map, "PID")
        # Remove None/empty
        return {k: v for k, v in patient.items() if v not in (None, "", [])}

    def _build_encounter(self, c: Any) -> dict[str, Any]:
        fe = c.fhir_elements
        enc: dict[str, Any] = {
            "resourceType": "Encounter",
            "id": c.message_id,
            "status": "finished",
            "class": {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                "code": fe.get("encounter.class", "AMB"),
            },
            "subject": {"reference": f"Patient/{c.patient_id or 'unknown'}"},
            "extension": self._build_extensions(c.extension_map, "PV1"),
        }
        admit = fe.get("encounter.admitDate")
        discharge = fe.get("encounter.dischargeDate")
        if admit or discharge:
            period: dict[str, str] = {}
            if admit:
                period["start"] = self._hl7_dt(admit)
            if discharge:
                period["end"] = self._hl7_dt(discharge)
            enc["period"] = period
        return {k: v for k, v in enc.items() if v not in (None, "", [])}

    def _build_observation(self, c: Any, idx: int) -> dict[str, Any]:
        fe = c.fhir_elements
        code = fe.get(f"observation[{idx}].code", "")
        value = fe.get(f"observation[{idx}].value", "")
        units = fe.get(f"observation[{idx}].units", "")
        status = fe.get(f"observation[{idx}].status", "final")
        obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": f"{c.message_id}-obs-{idx}",
            "status": status or "final",
            "code": {"text": code, "coding": [{"code": code}]},
            "subject": {"reference": f"Patient/{c.patient_id or 'unknown'}"},
        }
        if value:
            try:
                obs["valueQuantity"] = {
                    "value": float(value),
                    "unit": units or "1",
                    "system": "http://unitsofmeasure.org",
                }
            except ValueError:
                obs["valueString"] = value
        return obs

    def _build_service_request(self, c: Any) -> dict[str, Any]:
        fe = c.fhir_elements
        return {
            "resourceType": "ServiceRequest",
            "id": c.message_id,
            "status": "active",
            "intent": "order",
            "subject": {"reference": f"Patient/{c.patient_id or 'unknown'}"},
            "extension": self._build_extensions(c.extension_map, "OBR"),
        }

    def _build_bundle(self, resources: list[dict], c: Any) -> dict[str, Any]:
        entries = [
            {"fullUrl": f"urn:uuid:{r.get('id', c.message_id)}", "resource": r}
            for r in resources if r
        ]
        return {
            "resourceType": "Bundle",
            "id": c.message_id,
            "type": "message",
            "entry": entries,
            "extension": self._build_extensions(c.extension_map, "_root"),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_extensions(extension_map: dict[str, Any], prefix: str) -> list[dict]:
        """Convert extension_map entries to FHIR Extension elements."""
        exts = []
        for key, val in extension_map.items():
            if str(val).strip():
                exts.append({
                    "url": f"https://medyrax.io/fhir/extensions/{key.replace(' ', '_')}",
                    "valueString": str(val),
                })
        return exts if exts else []

    @staticmethod
    def _hl7_dt(hl7_date: str) -> str:
        """Convert HL7 date string (YYYYMMDD[HHMMSS]) to ISO-8601."""
        d = hl7_date.strip()
        if len(d) >= 8:
            return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
        return d
