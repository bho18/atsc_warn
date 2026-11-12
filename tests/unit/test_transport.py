import struct

import pytest

from tests.fixtures.golden import (
    BODY,
    CRC,
    HEADER,
    HEART_BODY,
    HEART_CRC,
    HEART_HEADER,
    XML,
    cmac,
    heartbeat,
    packet,
)
from warnbridge.transport.crc import crc32_mpeg2
from warnbridge.transport.decoder import Decoder, Limits


def decode(data, **kwargs):
    d = Decoder(**kwargs)
    events = list(d.feed(data)) + list(d.finish())
    return d, events


def test_independent_crc_vectors():
    assert len(XML) == 446 and len(BODY) == 447
    assert crc32_mpeg2(b"123456789") == 0x0376E6E7
    assert crc32_mpeg2(HEADER + BODY) == 0xD0CAE4EF
    assert crc32_mpeg2(HEADER + BODY + CRC) == 0
    assert crc32_mpeg2(HEART_HEADER + HEART_BODY) == int.from_bytes(HEART_CRC, "big")


@pytest.mark.parametrize("chunk", [1, 7, 187, 188, 189, 1316, 65536])
def test_golden_arbitrary_chunks(chunk):
    d = Decoder()
    raw = cmac() + heartbeat()
    events = []
    for start in range(0, len(raw), chunk):
        events.extend(d.feed(raw[start : start + chunk]))
    events.extend(d.finish())
    assert len(events) == 2
    assert events[0].body == BODY
    assert events[0].raw_ts == cmac()
    assert events[0].header == HEADER
    assert events[0].assembled == HEADER + BODY + CRC + b"\xff" * 64
    assert events[1].body == HEART_BODY
    assert events[0].received_at is None
    assert d.counts["crc_pass"] == 2
    assert d.counts["continuity_gaps"] == 0


def test_exact_ts_repeat_not_delivery():
    raw = cmac()
    d, events = decode(raw[:188] + raw[:188] + raw[188:])
    assert len(events) == 1 and events[0].kind == "message"
    assert d.counts["duplicate_ts_packets"] == 1


def test_missing_fragment_and_truncation():
    raw = cmac()
    d, events = decode(raw[:188] + raw[376:] + b"\x47")
    assert not any(e.kind == "message" for e in events)
    assert d.counts["continuity_gaps"] == 1
    assert d.counts["incomplete_messages"] == 1
    assert events[-1].reason == "truncated_or_unparsed_input"


@pytest.mark.parametrize("mask,byte", [(0x80, 1), (0x80, 3)])
def test_tei_scrambling(mask, byte):
    raw = bytearray(heartbeat())
    raw[byte] |= mask
    _, events = decode(bytes(raw))
    assert events[0].kind == "rejected"


def test_adaptation_and_adaptation_only():
    p = heartbeat()
    payload = p[4 : 4 + 8 + 34]
    size = 183 - len(payload)
    adapted = p[:3] + b"\x31" + bytes([size, 0]) + b"\xff" * (size - 1) + payload
    only = b"\x47\x09\x11\x21\xb7\x00" + b"\xff" * 182
    d, events = decode(adapted + only + heartbeat(2))
    assert len(events) == 2
    assert d.counts["continuity_gaps"] == 0
    assert all(e.kind == "message" for e in events)


def test_discontinuity_prevents_join():
    only = b"\x47\x09\x11\x29\xb7\x80" + b"\xff" * 182
    d, events = decode(cmac()[:188] + only + cmac()[188:])
    assert not any(e.kind == "message" for e in events)
    assert d.counts["discontinuities"] == 1


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda p: p.__setitem__(30, p[30] ^ 1), "crc_mismatch"),
        (lambda p: p.__setitem__(-1, 0), "non_ff_stuffing"),
        (lambda p: p.__setitem__(slice(21, 25), b"\xff" * 4), "truncated_message_header"),
        (lambda p: p.__setitem__(7, 5), "inner_outer_id_mismatch"),
        (lambda p: p.__setitem__(1, p[1] & ~0x40), "fragment_index_limit_or_pusi"),
    ],
)
def test_corruption(mutation, reason):
    raw = bytearray(heartbeat())
    mutation(raw)
    _, events = decode(bytes(raw))
    assert events[-1].reason == reason


def test_same_id_overlap_quarantined():
    first = cmac()[:188]
    collision = first[:3] + b"\x1f" + first[4:]
    _, events = decode(first + collision + cmac()[188:])
    assert not any(e.kind == "message" for e in events)
    assert any(e.reason == "ambiguous_reused_id" for e in events)


def test_limits_and_timeout():
    d = Decoder(limits=Limits(max_pending=1, timeout=1))
    list(d.feed(cmac()[:188]))
    other = packet(b"x", 123, 0, 2, 15)
    assert list(d.feed(other))[0].reason == "pending_limit"
    assert list(d.expire(2))[0].reason == "assembly_timeout"
    _, events = decode(cmac(), limits=Limits(max_fragments=2))
    assert not any(e.kind == "message" for e in events)


def test_conflicting_fragment():
    raw = cmac()
    conflict = bytearray(raw[188:376])
    conflict[8:10] = struct.pack(">H", 2)
    _, events = decode(raw[:188] + bytes(conflict))
    assert any(e.reason == "conflicting_or_out_of_order_fragment" for e in events)


def test_strict_sync_no_guessed_resync():
    d, events = decode(b"x" + heartbeat())
    assert d.failed
    assert not any(e.kind == "message" for e in events)


def test_unknown_header_preserved_without_version_claim():
    from tests.fixtures.synthetic import wrap
    from warnbridge.storage.store import known_header

    _, events = decode(wrap(BODY, first=0x9F))
    assert events[0].kind == "message"
    assert events[0].header[0] == 0x9F
    assert not known_header(events[0].header)


def test_bad_packet_does_not_discard_later_packets_in_chunk():
    bad = bytearray(heartbeat())
    bad[1] |= 0x80
    d, events = decode(bytes(bad) + heartbeat(2))
    assert d.counts["crc_pass"] == 1
    assert events[-1].kind == "message"


def test_body_exceeds_assembly_and_adaptation_malformed():
    bad = bytearray(heartbeat())
    bad[21:25] = (1000).to_bytes(4, "big")
    _, events = decode(bytes(bad))
    assert events[0].reason == "body_length_exceeds_assembly"
    bad = bytearray(heartbeat())
    bad[3] = 0x31
    bad[4] = 184
    _, events = decode(bytes(bad))
    assert events[0].reason == "invalid_adaptation_length"


def test_assembly_size_limit():
    _, events = decode(cmac(), limits=Limits(max_body=1))
    assert any(e.reason == "assembly_size_limit" for e in events)


def test_adaptation_only_counter_must_not_increment():
    p = cmac()
    only = b"\x47\x09\x11\x2f\xb7\x00" + b"\xff" * 182
    d, events = decode(p[:188] + only + p[188:])
    assert d.counts["continuity_gaps"] > 0
    assert not any(e.kind == "message" for e in events)
