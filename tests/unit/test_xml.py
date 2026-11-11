from pathlib import Path

import pytest

from tests.fixtures.golden import BODY, XML
from warnbridge.formats.xml import CAP, parse_body

CAP_XML = Path("tests/fixtures/cap.xml").read_bytes()


def test_cmac_golden():
    p = parse_body(BODY)
    assert p.xml == XML
    assert p.xml_state == "well_formed"
    assert p.classification == "cmac_link_test"
    assert not p.actual_public
    assert p.schema_state == "not_configured" and p.signature_state == "not_checked"


def test_cap_preserves_multilingual_areas_params_extensions():
    p = parse_body(CAP_XML)
    assert p.xml == CAP_XML
    assert p.protocol == "CAP" and not p.actual_public
    assert p.identity == ("sender.example", "synthetic-001", "2020-11-30T10:00:00Z")
    assert len(p.fields["info"]) == 2
    children = p.fields["info"][0]["children"]
    assert len([c for c in children if c["tag"] == f"{{{CAP}}}area"]) == 2
    assert len([c for c in children if c["tag"] == f"{{{CAP}}}parameter"]) == 2
    ext = [c for c in children if c["tag"] == "{urn:warnbridge:synthetic}extension"]
    assert ext[0]["attributes"] == {"flag": "keep"}
    assert ext[0]["children"][0]["tail"] == "tail"
    assert "047037" in str(p.fields)
    assert "36.1,-86.7 5" in str(p.fields)


@pytest.mark.parametrize(
    "raw",
    [
        b"<bad>",
        b"<a>\x00x</a>\x00",
        b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>',
        b"<!DOCTYPE a><a/>",
        b"<a>" * 65 + b"</a>" * 65,
        b"<a/>" + b"\x00\x00",
    ],
)
def test_reject_untrusted_xml(raw):
    p = parse_body(raw)
    assert p.xml_state == "invalid"
    assert not p.actual_public


def test_element_size_limits_and_unknown_root():
    assert parse_body(b"<a><b/><b/></a>", max_elements=2).xml_state == "invalid"
    assert parse_body(b"<a/>", max_bytes=3).xml_state == "invalid"
    p = parse_body(b'<alert xmlns="urn:wrong"/>')
    assert p.protocol == "unknown" and p.reason == "unsupported_root_or_namespace"


@pytest.mark.parametrize("status", ["Test", "System", "Exercise", "Draft"])
def test_nonactual_status(status):
    p = parse_body(CAP_XML.replace(b">Test<", f">{status}<".encode()))
    assert not p.actual_public


def test_prefixes_and_references():
    p = parse_body(
        XML.replace(b"<CMAC_", b"<p:CMAC_")
        .replace(b"</CMAC_", b"</p:CMAC_")
        .replace(b"xmlns=", b"xmlns:p=")
    )
    assert p.classification == "cmac_link_test"
    raw = CAP_XML.replace(b"<cap:msgType>Alert", b"<cap:msgType>Cancel").replace(
        b"<cap:info>",
        b"<cap:references>sender.example,old,2020-11-30T09:00:00Z broken"
        b"</cap:references><cap:info>",
        1,
    )
    p = parse_body(raw)
    assert p.references == [("sender.example", "old", "2020-11-30T09:00:00Z")]
    assert p.fields["unparsed_references"] == ["broken"]


def test_terminal_zero_in_utf16_is_not_transport_nul():
    body = '<?xml version="1.0" encoding="UTF-16"?><a/>'.encode("utf-16")
    assert body.endswith(b"\x00")
    parsed = parse_body(body)
    assert parsed.xml == body
    assert parsed.xml_state == "well_formed"
