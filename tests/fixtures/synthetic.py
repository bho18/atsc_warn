"""Deliberately synthetic packets; CRC calculated only for non-golden tests."""

from tests.fixtures.golden import packet
from warnbridge.transport.crc import crc32_mpeg2


def wrap(body: bytes, ident: int = 0x6AF3C24C, cc: int = 0, first: int = 0x2F) -> bytes:
    header = (
        bytes([first, 0, 0, 255])
        + ident.to_bytes(4, "big")
        + b"\x00"
        + len(body).to_bytes(4, "big")
    )
    raw = header + body
    raw += crc32_mpeg2(raw).to_bytes(4, "big")
    last = (len(raw) - 1) // 176
    raw = raw.ljust((last + 1) * 176, b"\xff")
    return b"".join(
        packet(raw[i * 176 : (i + 1) * 176], ident, i, last, (cc + i) % 16) for i in range(last + 1)
    )
