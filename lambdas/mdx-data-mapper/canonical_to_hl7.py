"""
CanonicalToHL7Serializer — rebuild HL7 v2.x pipe-delimited messages.

Reconstructs a HL7 v2.5 message from a CanonicalMessage produced by
FHIRToCanonicalParser or HL7ToCanonicalParser.  All fields stored in
``extension_map`` are written back to their original segment positions,
preserving unmapped data for round-trip integrity (Requirement 13.2, 13.4).

Requirements: 13.1, 13.2
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Field separator and encoding chars
_FS = "|"
_COMPONENT_SEP = "^"
_ENCODING_CHARS = "^~\\&"


class CanonicalToHL7Serializer:
    """
    Reconstruct an HL7 v2.x pipe-delimited message from a CanonicalMessage.

    Usage::

        serializer = CanonicalToHL7Serializer()
        hl7_text = serializer.serialize(canonical)
    """

    def serialize(self, canonical: Any) -> str:
        """
        Serialize ``canonical`` back to HL7 v2.x pipe-delimited format.

        Parameters
        ----------
        canonical:
            CanonicalMessage instance (from either HL7ToCanonicalParser
            or FHIRToCanonicalParser).

        Returns
        -------
        str
            HL7 v2.x pipe-delimited message string (no MLLP framing).
        """
        segments: list[str] = []

        # ── MSH ─────────────────────────────────────────────────────────────
        now = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
        msg_type = (canonical.message_type.value if canonical.message_type else "ADT^A08")
        msg_type_hl7 = msg_type.replace("_", "^", 1)

        msh_fields = [
            "",           # MSH.1 — field separator itself
            _ENCODING_CHARS,  # MSH.2
            canonical.source_system or "MEDYRAX",  # MSH.3
            "",           # MSH.4
            "",           # MSH.5
            "",           # MSH.6
            now,          # MSH.7
            "",           # MSH.8
            msg_type_hl7, # MSH.9
            canonical.message_id,  # MSH.10
            "P",          # MSH.11
            "2.5",        # MSH.12
        ]
        # Restore any extension_map MSH fields
        for key, val in canonical.extension_map.items():
            if key.startswith("MSH-"):
                try:
                    idx = int(key.split("-")[1])
                    while len(msh_fields) <= idx:
                        msh_fields.append("")
                    msh_fields[idx] = str(val)
                except (ValueError, IndexError):
                    pass

        segments.append("MSH" + _FS + _FS.join(msh_fields[1:]))

        # ── PID ─────────────────────────────────────────────────────────────
        fe = canonical.fhir_elements
        pid_fields = [""] * 20
        pid_fields[3] = canonical.patient_id or fe.get("patient.id", "")
        pid_fields[5] = fe.get("patient.name", "")
        pid_fields[7] = self._iso_to_hl7(fe.get("patient.birthDate", ""))
        pid_fields[8] = self._fhir_gender_to_hl7(fe.get("patient.gender", ""))
        pid_fields[11] = fe.get("patient.address", "")
        # Restore extension_map PID fields
        for key, val in canonical.extension_map.items():
            if key.startswith("PID-"):
                try:
                    idx = int(key.split("-")[1])
                    while len(pid_fields) <= idx:
                        pid_fields.append("")
                    pid_fields[idx] = str(val)
                except (ValueError, IndexError):
                    pass
        segments.append("PID" + _FS + _FS.join(pid_fields))

        # ── PV1 (only for ADT/encounter messages) ───────────────────────────
        if fe.get("encounter.class") or fe.get("encounter.admitDate"):
            pv1_fields = [""] * 50
            pv1_fields[2] = fe.get("encounter.class", "I")
            pv1_fields[3] = fe.get("encounter.location", "")
            pv1_fields[44] = self._iso_to_hl7(fe.get("encounter.admitDate", ""))
            pv1_fields[45] = self._iso_to_hl7(fe.get("encounter.dischargeDate", ""))
            # Restore extension_map PV1 fields
            for key, val in canonical.extension_map.items():
                if key.startswith("PV1-"):
                    try:
                        idx = int(key.split("-")[1])
                        while len(pv1_fields) <= idx:
                            pv1_fields.append("")
                        pv1_fields[idx] = str(val)
                    except (ValueError, IndexError):
                        pass
            segments.append("PV1" + _FS + _FS.join(pv1_fields))

        # ── OBX (observations) ──────────────────────────────────────────────
        obs_index = 0
        while fe.get(f"observation[{obs_index}].code"):
            code = fe.get(f"observation[{obs_index}].code", "")
            value = fe.get(f"observation[{obs_index}].value", "")
            units = fe.get(f"observation[{obs_index}].units", "")
            status = fe.get(f"observation[{obs_index}].status", "F")
            obx_fields = [
                str(obs_index + 1),  # OBX.1 sequence
                "NM" if self._is_numeric(value) else "ST",  # OBX.2 value type
                code,                # OBX.3 observation id
                "",                  # OBX.4 sub-id
                value,               # OBX.5 value
                units,               # OBX.6 units
                "",                  # OBX.7 reference range
                "",                  # OBX.8 abnormal flag
                "",                  # OBX.9
                "",                  # OBX.10
                status,              # OBX.11
            ]
            segments.append("OBX" + _FS + _FS.join(obx_fields))
            obs_index += 1

        # ── DG1 (conditions) ────────────────────────────────────────────────
        cond_index = 0
        while fe.get(f"condition[{cond_index}].code"):
            code = fe.get(f"condition[{cond_index}].code", "")
            desc = fe.get(f"condition[{cond_index}].description", "")
            dg1_fields = [
                str(cond_index + 1),  # DG1.1
                "I10",                # DG1.2 coding method
                code,                 # DG1.3
                desc,                 # DG1.4
                "",                   # DG1.5
                "W",                  # DG1.6 diagnosis type
            ]
            segments.append("DG1" + _FS + _FS.join(dg1_fields))
            cond_index += 1

        return "\r".join(segments) + "\r"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _iso_to_hl7(iso_date: str) -> str:
        """Convert ISO date (YYYY-MM-DD or ISO-8601) to HL7 YYYYMMDD."""
        if not iso_date:
            return ""
        cleaned = iso_date.replace("-", "").replace("T", "")[:8]
        return cleaned if len(cleaned) == 8 else ""

    @staticmethod
    def _fhir_gender_to_hl7(fhir_gender: str) -> str:
        """Convert FHIR gender string to HL7 admin sex code."""
        return {"male": "M", "female": "F", "other": "O", "unknown": "U"}.get(
            fhir_gender.lower(), "U"
        )

    @staticmethod
    def _is_numeric(value: str) -> bool:
        try:
            float(value)
            return True
        except (ValueError, TypeError):
            return False
