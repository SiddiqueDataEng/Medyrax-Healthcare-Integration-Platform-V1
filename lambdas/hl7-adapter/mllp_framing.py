"""
MLLP framing utilities (task 8.1).

MLLP (Minimum Lower Layer Protocol) wraps HL7 messages with:
    0x0B         — start of block (SB)
    <HL7 data>
    0x1C 0x0D    — end of block (EB) + carriage return (CR)

Requirements: 2.1, 2.5
"""

from __future__ import annotations

# MLLP control bytes
MLLP_SB: bytes = b"\x0b"      # Start Block
MLLP_EB: bytes = b"\x1c"      # End Block
MLLP_CR: bytes = b"\x0d"      # Carriage Return

ACK_AA = "AA"   # Application Accept
ACK_AE = "AE"   # Application Error
ACK_AR = "AR"   # Application Reject


def extract_hl7(mllp_data: bytes) -> str:
    """
    Extract the HL7 message string from MLLP-framed bytes.

    Parameters
    ----------
    mllp_data:
        Raw bytes from the TCP socket (may include SB/EB/CR control bytes).

    Returns
    -------
    str
        UTF-8 decoded HL7 message without MLLP framing.

    Raises
    ------
    ValueError
        When the data is not valid MLLP framing.
    """
    # Handle raw bytes that may or may not include framing
    data = mllp_data
    if data.startswith(MLLP_SB):
        data = data[1:]
    if data.endswith(MLLP_EB + MLLP_CR):
        data = data[:-2]
    elif data.endswith(MLLP_EB):
        data = data[:-1]

    return data.decode("utf-8", errors="replace")


def wrap_hl7(hl7_message: str) -> bytes:
    """
    Wrap an HL7 message string in MLLP framing for TCP transmission.

    Parameters
    ----------
    hl7_message:
        Plain HL7 v2.x pipe-delimited string.

    Returns
    -------
    bytes
        MLLP-framed bytes ready for TCP socket transmission.
    """
    encoded = hl7_message.encode("utf-8")
    return MLLP_SB + encoded + MLLP_EB + MLLP_CR


def build_ack(
    original_msh: str,
    ack_code: str = ACK_AA,
    error_msg: str = "",
    sending_app: str = "MEDYRAX",
) -> str:
    """
    Build an HL7 ACK (or NAK) message in response to an inbound message.

    Parameters
    ----------
    original_msh:
        The MSH segment line of the original message (used to extract
        MSH-3, MSH-7, MSH-10 for the ACK header).
    ack_code:
        One of ``"AA"``, ``"AE"``, or ``"AR"``.
    error_msg:
        Human-readable error description (only included for AE/AR).
    sending_app:
        MSH-3 of the ACK sender.

    Returns
    -------
    str
        HL7 ACK message string.
    """
    from datetime import datetime, timezone

    now = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
    fields = original_msh.split("|")

    orig_sender = fields[2] if len(fields) > 2 else "UNKNOWN"
    orig_msg_id = fields[9] if len(fields) > 9 else "UNKNOWN"

    ack_lines = [
        f"MSH|^~\\&|{sending_app}||{orig_sender}||{now}||ACK|{now}|P|2.5",
        f"MSA|{ack_code}|{orig_msg_id}|{error_msg}",
    ]
    if ack_code != ACK_AA and error_msg:
        ack_lines.append(f"ERR|||{ack_code}|E|||{error_msg}")

    return "\r".join(ack_lines) + "\r"


def extract_patient_id_from_hl7(hl7_text: str) -> str:
    """
    Quick-parse PID-3 (patient ID) from HL7 text without full hl7apy parse.

    Used by MLLP listener to get the SQS MessageGroupId fast (< 200ms budget).
    """
    for line in hl7_text.splitlines():
        if line.startswith("PID|"):
            fields = line.split("|")
            # PID-3 is field index 3
            pid3 = fields[3] if len(fields) > 3 else ""
            # PID-3 may be a CWE like "12345^^^MRN"
            return pid3.split("^")[0] if pid3 else ""
    return ""
