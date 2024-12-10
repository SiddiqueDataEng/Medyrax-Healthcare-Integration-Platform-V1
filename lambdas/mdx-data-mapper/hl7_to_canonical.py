"""
HL7ToCanonicalParser — parse HL7 v2.x messages into CanonicalMessage.

Wraps the ``hl7apy`` library.  Maps the segments listed in the design spec
to canonical fields; stores unmapped fields verbatim in ``extension_map``
to preserve round-trip integrity (Requirement 13.1, 13.3).

Supported message types: ADT (A01–A13, A28, A29, A31, A40), ORM, ORU,
MDM, DFT, SIU, VXU (Requirement 2.2).

Requirements: 13.1, 13.2, 13.3
"""

from __future__ import annotations

import hashlib
import logging
import sys
import os
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Import path resolution (Lambda layer vs local dev)
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from mdx_common.models import CanonicalMessage
    from mdx_common.enums import Hl7MessageType
    from mdx_common.errors import Hl7ParseError, TransformationError
except ImportError:
    # Fallback: run from repo root
    from lambdas.mdx_common.models import CanonicalMessage  # type: ignore
    from lambdas.mdx_common.enums import Hl7MessageType  # type: ignore
    from lambdas.mdx_common.errors import Hl7ParseError, TransformationError  # type: ignore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------

def _safe_field(segment: Any, index: int, default: str = "") -> str:
    """Extract a string value from an hl7apy segment field by index."""
    try:
        field_obj = segment.children[index] if hasattr(segment, "children") else None
        if field_obj is None:
            return default
        val = field_obj.value
        return str(val).strip() if val else default
    except (IndexError, AttributeError):
        return default


def _capture_unmapped(segment: Any, mapped_indices: set[int], seg_name: str) -> dict[str, Any]:
    """Return a dict of field values that were NOT in the mapped set."""
    unmapped: dict[str, Any] = {}
    try:
        for i, child in enumerate(segment.children):
            if i not in mapped_indices:
                val = getattr(child, "value", None)
                if val:
                    unmapped[f"{seg_name}-{i}"] = str(val)
    except (AttributeError, TypeError):
        pass
    return unmapped


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class HL7ToCanonicalParser:
    """
    Parse an HL7 v2.x pipe-delimited message string into a CanonicalMessage.

    Usage::

        parser = HL7ToCanonicalParser()
        canonical = parser.parse(hl7_text)

    The parser uses ``hl7apy`` in LENIENT mode so it can handle real-world
    messages with non-standard extensions.  Unmapped fields from every segment
    are captured in ``canonical.extension_map`` keyed as ``"{SEGMENT}-{index}"``.
    """

    def __init__(self, lenient: bool = True) -> None:
        self._lenient = lenient

    def parse(self, raw_message: str, org_id: str = "") -> CanonicalMessage:
        """
        Parse ``raw_message`` and return a populated CanonicalMessage.

        Parameters
        ----------
        raw_message:
            Raw HL7 v2.x pipe-delimited string (with or without MLLP framing).
        org_id:
            Owning org identifier — stored on the canonical message for
            downstream routing.

        Returns
        -------
        CanonicalMessage

        Raises
        ------
        Hl7ParseError
            When the message cannot be parsed by hl7apy.
        """
        # Strip MLLP framing if present
        cleaned = raw_message.strip()
        if cleaned.startswith("\x0b"):
            cleaned = cleaned[1:]
        if cleaned.endswith("\x1c\x0d"):
            cleaned = cleaned[:-2]

        # Compute SHA-256 of original
        sha256 = hashlib.sha256(cleaned.encode("utf-8", errors="replace")).hexdigest()

        try:
            from hl7apy.core import Message  # type: ignore
            from hl7apy import core as hl7_core  # type: ignore

            msg = Message(version="2.5", validation_level=2 if self._lenient else 0)
            msg.parse_message(cleaned)
        except ImportError:
            # hl7apy not installed — do a minimal fallback parse
            return self._minimal_parse(cleaned, sha256, org_id)
        except Exception as exc:
            raise Hl7ParseError(
                message=f"hl7apy failed to parse message: {exc}",
                segment="MSH",
            ) from exc

        canonical = CanonicalMessage(
            raw_source=cleaned,
            source_sha256=sha256,
        )

        extension_map: dict[str, Any] = {}
        segments: list[dict[int, str]] = []

        # ── MSH ─────────────────────────────────────────────────────────────
        try:
            msh = msg.children[0]
            mapped = {0, 2, 3, 4, 8}
            canonical.source_system = _safe_field(msh, 2)
            msg_type_raw = _safe_field(msh, 8)
            canonical.message_type = self._resolve_message_type(msg_type_raw)
            seg_dict: dict[int, str] = {
                i: _safe_field(msh, i) for i in range(min(len(msh.children), 20))
                if _safe_field(msh, i)
            }
            segments.append(seg_dict)
            extension_map.update(_capture_unmapped(msh, mapped, "MSH"))
        except (IndexError, AttributeError) as exc:
            raise Hl7ParseError(message=f"MSH segment error: {exc}", segment="MSH") from exc

        # ── PID ─────────────────────────────────────────────────────────────
        try:
            pid = self._find_segment(msg, "PID")
            if pid:
                canonical.patient_id = _safe_field(pid, 3) or _safe_field(pid, 2)
                mapped_pid = {1, 2, 3, 5, 7, 8, 11, 18}
                seg_dict = {
                    i: _safe_field(pid, i) for i in range(min(len(pid.children), 30))
                    if _safe_field(pid, i)
                }
                segments.append(seg_dict)
                extension_map.update(_capture_unmapped(pid, mapped_pid, "PID"))
                canonical.fhir_elements["patient.id"] = canonical.patient_id
                canonical.fhir_elements["patient.name"] = _safe_field(pid, 5)
                canonical.fhir_elements["patient.birthDate"] = _safe_field(pid, 7)
                canonical.fhir_elements["patient.gender"] = _safe_field(pid, 8)
                canonical.fhir_elements["patient.address"] = _safe_field(pid, 11)
        except Exception as exc:
            logger.warning("PID segment parse warning: %s", exc)

        # ── PV1 ─────────────────────────────────────────────────────────────
        try:
            pv1 = self._find_segment(msg, "PV1")
            if pv1:
                canonical.fhir_elements["encounter.class"] = _safe_field(pv1, 2)
                canonical.fhir_elements["encounter.admitDate"] = _safe_field(pv1, 44)
                canonical.fhir_elements["encounter.dischargeDate"] = _safe_field(pv1, 45)
                canonical.fhir_elements["encounter.location"] = _safe_field(pv1, 3)
                mapped_pv1 = {2, 3, 7, 19, 44, 45}
                seg_dict = {
                    i: _safe_field(pv1, i) for i in range(min(len(pv1.children), 50))
                    if _safe_field(pv1, i)
                }
                segments.append(seg_dict)
                extension_map.update(_capture_unmapped(pv1, mapped_pv1, "PV1"))
        except Exception as exc:
            logger.warning("PV1 segment parse warning: %s", exc)

        # ── OBR / OBX (for ORU) ─────────────────────────────────────────────
        obr_list = self._find_all_segments(msg, "OBR")
        for idx, obr in enumerate(obr_list):
            try:
                canonical.fhir_elements[f"diagnosticReport[{idx}].code"] = _safe_field(obr, 4)
                canonical.fhir_elements[f"diagnosticReport[{idx}].orderDate"] = _safe_field(obr, 6)
                seg_dict = {
                    i: _safe_field(obr, i) for i in range(min(len(obr.children), 30))
                    if _safe_field(obr, i)
                }
                segments.append(seg_dict)
                extension_map.update(_capture_unmapped(obr, {4, 6, 16}, f"OBR[{idx}]"))
            except Exception as exc:
                logger.warning("OBR[%d] parse warning: %s", idx, exc)

        obx_list = self._find_all_segments(msg, "OBX")
        for idx, obx in enumerate(obx_list):
            try:
                canonical.fhir_elements[f"observation[{idx}].code"] = _safe_field(obx, 3)
                canonical.fhir_elements[f"observation[{idx}].value"] = _safe_field(obx, 5)
                canonical.fhir_elements[f"observation[{idx}].units"] = _safe_field(obx, 6)
                canonical.fhir_elements[f"observation[{idx}].status"] = _safe_field(obx, 11)
                seg_dict = {
                    i: _safe_field(obx, i) for i in range(min(len(obx.children), 20))
                    if _safe_field(obx, i)
                }
                segments.append(seg_dict)
                extension_map.update(_capture_unmapped(obx, {2, 3, 5, 6, 11}, f"OBX[{idx}]"))
            except Exception as exc:
                logger.warning("OBX[%d] parse warning: %s", idx, exc)

        # ── DG1 (diagnoses) ──────────────────────────────────────────────────
        dg1_list = self._find_all_segments(msg, "DG1")
        for idx, dg1 in enumerate(dg1_list):
            try:
                canonical.fhir_elements[f"condition[{idx}].code"] = _safe_field(dg1, 3)
                canonical.fhir_elements[f"condition[{idx}].description"] = _safe_field(dg1, 4)
                seg_dict = {
                    i: _safe_field(dg1, i) for i in range(min(len(dg1.children), 10))
                    if _safe_field(dg1, i)
                }
                segments.append(seg_dict)
                extension_map.update(_capture_unmapped(dg1, {3, 4, 6}, f"DG1[{idx}]"))
            except Exception as exc:
                logger.warning("DG1[%d] parse warning: %s", idx, exc)

        # ── IN1 (insurance) ──────────────────────────────────────────────────
        in1_list = self._find_all_segments(msg, "IN1")
        for idx, in1 in enumerate(in1_list):
            try:
                canonical.fhir_elements[f"coverage[{idx}].planId"] = _safe_field(in1, 2)
                canonical.fhir_elements[f"coverage[{idx}].groupNumber"] = _safe_field(in1, 8)
                seg_dict = {
                    i: _safe_field(in1, i) for i in range(min(len(in1.children), 30))
                    if _safe_field(in1, i)
                }
                segments.append(seg_dict)
                extension_map.update(_capture_unmapped(in1, {2, 3, 4, 8}, f"IN1[{idx}]"))
            except Exception as exc:
                logger.warning("IN1[%d] parse warning: %s", idx, exc)

        canonical.segments = segments
        canonical.extension_map = extension_map
        canonical.fhir_elements["orgId"] = org_id

        return canonical

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_message_type(raw: str) -> Optional[Hl7MessageType]:
        """Map raw MSH-9 string (e.g. 'ADT^A01') to Hl7MessageType enum."""
        normalized = raw.replace("^", "_").upper()
        try:
            return Hl7MessageType(normalized)
        except ValueError:
            # Try first part only (e.g. 'ADT_A01' from 'ADT^A01^ADT_A01')
            parts = normalized.split("_")
            if len(parts) >= 2:
                short = f"{parts[0]}_{parts[1]}"
                try:
                    return Hl7MessageType(short)
                except ValueError:
                    pass
        logger.debug("Unknown HL7 message type: %s", raw)
        return None

    @staticmethod
    def _find_segment(msg: Any, seg_name: str) -> Optional[Any]:
        """Find the first occurrence of ``seg_name`` in an hl7apy Message."""
        try:
            for child in msg.children:
                if hasattr(child, "name") and child.name.upper() == seg_name.upper():
                    return child
        except (AttributeError, TypeError):
            pass
        return None

    @staticmethod
    def _find_all_segments(msg: Any, seg_name: str) -> list[Any]:
        """Find all occurrences of ``seg_name`` in an hl7apy Message."""
        result = []
        try:
            for child in msg.children:
                if hasattr(child, "name") and child.name.upper() == seg_name.upper():
                    result.append(child)
        except (AttributeError, TypeError):
            pass
        return result

    def _minimal_parse(self, raw: str, sha256: str, org_id: str) -> CanonicalMessage:
        """Fallback parser when hl7apy is unavailable — splits on | delimiter."""
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        canonical = CanonicalMessage(raw_source=raw, source_sha256=sha256)
        extension_map: dict[str, Any] = {}
        segments: list[dict[int, str]] = []

        for line in lines:
            fields = line.split("|")
            seg_name = fields[0] if fields else ""
            seg_dict: dict[int, str] = {i: v for i, v in enumerate(fields) if v}
            segments.append(seg_dict)

            if seg_name == "MSH":
                canonical.source_system = fields[2] if len(fields) > 2 else ""
                raw_type = fields[8] if len(fields) > 8 else ""
                canonical.message_type = self._resolve_message_type(raw_type)
            elif seg_name == "PID":
                canonical.patient_id = fields[3] if len(fields) > 3 else ""
                canonical.fhir_elements["patient.id"] = canonical.patient_id
                canonical.fhir_elements["patient.name"] = fields[5] if len(fields) > 5 else ""
                canonical.fhir_elements["patient.birthDate"] = fields[7] if len(fields) > 7 else ""
                canonical.fhir_elements["patient.gender"] = fields[8] if len(fields) > 8 else ""
            else:
                for i, val in enumerate(fields[1:], 1):
                    if val:
                        extension_map[f"{seg_name}-{i}"] = val

        canonical.segments = segments
        canonical.extension_map = extension_map
        canonical.fhir_elements["orgId"] = org_id
        return canonical
