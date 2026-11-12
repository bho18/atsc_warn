"""Synthetic regression vectors for variable headers observed in retained failures."""

import pytest

from tests.fixtures.synthetic import wrap
from warnbridge.storage.store import known_header
from warnbridge.transport.decoder import Decoder, Limits


@pytest.mark.parametrize("entries", [(), (39165,), (1, 2), tuple(range(255))])
@pytest.mark.parametrize("payload_type", [0, 1, 255])
def test_variable_header_roundtrip_binary_and_xml_independent(entries, payload_type):
    body = bytes(range(256)) * 23 + b"\x00"
    raw = wrap(body, entries=entries, payload_type=payload_type)
    decoder = Decoder()
    events = []
    for i in range(0, len(raw), 187):
        events.extend(decoder.feed(raw[i : i + 187]))
    events.extend(decoder.finish())
    assert len(events) == 1
    event = events[0]
    assert event.kind == "message" and event.reason is None
    assert event.body == body and event.raw_ts == raw
    assert len(event.header) == 13 + 3 * len(entries)
    assert known_header(event.header)
    assert event.stored_crc == event.calculated_crc


def test_full_two_byte_body_length_not_misread_as_header_fields():
    body = b"x" * 65535
    events = list(Decoder().feed(wrap(body, entries=(2,), payload_type=1)))
    assert len(events) == 1 and events[0].body == body and events[0].kind == "message"


def test_configured_body_bound_checks_actual_length_and_does_not_stop_next_message():
    too_large = wrap(b"x" * 50, entries=(1,), payload_type=1)
    good = wrap(b"next", cc=1)
    decoder = Decoder(limits=Limits(max_body=49))
    events = list(decoder.feed(too_large + good))
    assert [e.reason for e in events] == ["body_size_limit", None]
    assert events[-1].body == b"next"


def test_header_corruption_does_not_fall_back_to_searching_xml():
    raw = bytearray(wrap(b'<?xml version="1.0"?><root/>', entries=(1,), payload_type=1))
    raw[21] = 0
    events = list(Decoder().feed(raw))
    assert len(events) == 1 and events[0].kind == "rejected"
