"""Reconstructed from user-supplied bytes; NOT an original OTA capture."""

import struct

XML = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    b'<CMAC_Alert_Attributes xmlns="cmac:2.0">'
    b"<CMAC_protocol_version>2.0</CMAC_protocol_version>"
    b"<CMAC_sending_gateway_id>http://integration.aws.fema.gov"
    b"</CMAC_sending_gateway_id>"
    b"<CMAC_message_number>b440b6c8</CMAC_message_number>"
    b"<CMAC_sent_date_time>2026-11-11T01:18:00Z"
    b"</CMAC_sent_date_time>"
    b"<CMAC_status>System</CMAC_status>"
    b"<CMAC_message_type>Link Test</CMAC_message_type>"
    b"</CMAC_Alert_Attributes>"
)
HEADER = bytes.fromhex("2f 00 00 ff 6a f3 c2 4c 00 00 00 01 bf")
BODY = XML + b"\x00"
CRC = bytes.fromhex("d0 ca e4 ef")
HEART_HEADER = bytes.fromhex("2f 03 00 ff 00 00 04 11 00 00 00 00 11")
HEART_BODY = b"Heartbeat Message"
HEART_CRC = bytes.fromhex("7d 34 fe 4a")


def packet(content: bytes, ident: int, index: int, last: int, cc: int) -> bytes:
    payload = struct.pack(">IHH", ident, index, last) + content
    assert len(payload) <= 184
    return bytes([0x47, 0x09 | (0x40 if index == 0 else 0), 0x11, 0x10 | cc]) + payload.ljust(
        184, b"\xff"
    )


def cmac() -> bytes:
    raw = HEADER + BODY + CRC + b"\xff" * 64
    return b"".join(
        packet(raw[i * 176 : (i + 1) * 176], 0x6AF3C24C, i, 2, cc)
        for i, cc in enumerate([14, 15, 0])
    )


def heartbeat(cc: int = 1) -> bytes:
    return packet(HEART_HEADER + HEART_BODY + HEART_CRC, 0x411, 0, 0, cc)
