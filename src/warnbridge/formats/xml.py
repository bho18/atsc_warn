"""Hardened, bounded XML views. Original bytes are never rewritten."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from xml.etree.ElementTree import Element, ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import iterparse

CMAC = "cmac:2.0"
CAP = "urn:oasis:names:tc:emergency:cap:1.2"


@dataclass
class Parsed:
    classification: str = "unknown"
    protocol: str = "unknown"
    xml_state: str = "not_applicable"
    schema_state: str = "not_configured"
    signature_state: str = "not_checked"
    geography_state: str = "not_evaluated"
    xml: bytes | None = None
    reason: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    identity: tuple[str, str, str] | None = None
    references: list[tuple[str, str, str]] = field(default_factory=list)
    actual_public: bool = False


def utc_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except ValueError:
        return None


def tree_view(node: Element) -> dict[str, Any]:
    return {
        "tag": node.tag,
        "attributes": dict(node.attrib),
        "text": node.text,
        "tail": node.tail,
        "children": [tree_view(child) for child in node],
    }


def values(node: Element, namespace: str, key: str) -> list[str]:
    return [c.text or "" for c in node.findall(f"{{{namespace}}}{key}")]


def one(node: Element, namespace: str, key: str) -> str:
    found = values(node, namespace, key)
    return found[0] if len(found) == 1 else ""


def xml_width(data: bytes) -> int:
    if data.startswith(
        (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff", b"\x00\x00\x00<", b"<\x00\x00\x00")
    ):
        return 4
    if data.startswith((b"\xff\xfe", b"\xfe\xff", b"\x00<", b"<\x00")):
        return 2
    return 1


def xml_view(body: bytes) -> bytes:
    width = xml_width(body)
    # The observed transport adds one byte, not an encoded XML NUL character.
    # Never remove the last byte of a complete UTF-16/32 code unit.
    if body.endswith(b"\x00") and (width == 1 or len(body) % width == 1):
        return body[:-1]
    return body


def readable_text(data: bytes) -> str:
    """Decode a display copy; downloads always return the untouched byte stream."""
    encoding = "utf-8-sig"
    if xml_width(data) == 4:
        encoding = (
            "utf-32"
            if data.startswith((b"\xff\xfe", b"\x00\x00\xfe\xff"))
            else ("utf-32-be" if data.startswith(b"\x00") else "utf-32-le")
        )
    elif xml_width(data) == 2:
        encoding = (
            "utf-16"
            if data.startswith((b"\xff\xfe", b"\xfe\xff"))
            else ("utf-16-be" if data.startswith(b"\x00") else "utf-16-le")
        )
    else:
        declaration = re.match(rb"""\s*<\?xml\s[^?]*encoding\s*=\s*["']([^"']+)["']""", data[:1024])
        if declaration:
            encoding = declaration[1].decode("ascii", errors="replace")
    try:
        text = data.decode(encoding)
        if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
            raise ValueError("binary controls")
        return text
    except (LookupError, UnicodeError, ValueError):
        return "Binary or undecodable content (hex):\n" + data.hex(" ")


def parse_body(
    body: bytes, *, max_bytes: int = 1024 * 1024, max_depth: int = 64, max_elements: int = 10000
) -> Parsed:
    result = Parsed()
    if body == b"Heartbeat Message":
        result.classification = "heartbeat"
        return result
    # The one terminal NUL is an observed framing convention, not arbitrary cleanup.
    xml = xml_view(body)
    result.xml = xml
    if len(xml) > max_bytes:
        result.xml_state, result.reason = "invalid", "xml_size_limit"
        return result
    try:
        depth = count = 0
        root = None
        iterator = iterparse(
            BytesIO(xml),
            events=("start", "end"),
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
        for event, element in iterator:
            if root is None:
                root = element
            if event == "start":
                depth += 1
                count += 1
                if depth > max_depth or count > max_elements:
                    raise ValueError("xml_structure_limit")
            else:
                depth -= 1
        if root is None:
            raise ValueError("empty_xml")
        result.xml_state = "well_formed"
    except (DefusedXmlException, ParseError, ValueError, LookupError, UnicodeError) as exc:
        result.xml_state, result.reason = "invalid", type(exc).__name__ + ": " + str(exc)[:200]
        return result
    result.fields["tree"] = tree_view(root)
    if root.tag == f"{{{CMAC}}}CMAC_Alert_Attributes":
        result.protocol = "CMAC"
        result.classification = "cmac"
        for key in (
            "CMAC_protocol_version",
            "CMAC_sending_gateway_id",
            "CMAC_message_number",
            "CMAC_sent_date_time",
            "CMAC_status",
            "CMAC_message_type",
        ):
            result.fields[key] = values(root, CMAC, key)
        if (
            one(root, CMAC, "CMAC_status") == "System"
            and one(root, CMAC, "CMAC_message_type") == "Link Test"
        ):
            result.classification = "cmac_link_test"
        result.fields["sent"] = one(root, CMAC, "CMAC_sent_date_time")
        # No speculative CMAC enum/lifecycle normalization.
    elif root.tag == f"{{{CAP}}}alert":
        result.protocol, result.classification = "CAP", "cap"
        for key in ("identifier", "sender", "sent", "status", "msgType", "scope", "references"):
            result.fields[key] = one(root, CAP, key)
        result.fields["info"] = [tree_view(c) for c in root.findall(f"{{{CAP}}}info")]
        identity = tuple(result.fields[k] for k in ("sender", "identifier", "sent"))
        if all(identity):
            result.identity = (identity[0], identity[1], identity[2])
        for raw in result.fields["references"].split():
            pieces = raw.split(",")
            if len(pieces) == 3 and all(pieces):
                result.references.append((pieces[0], pieces[1], pieces[2]))
            else:
                result.fields.setdefault("unparsed_references", []).append(raw)
        result.actual_public = (
            result.fields["status"] == "Actual"
            and result.fields["scope"] == "Public"
            and result.fields["msgType"] in ("Alert", "Update")
            and result.identity is not None
        )
        result.fields["expires"] = [
            one(info, CAP, "expires") for info in root.findall(f"{{{CAP}}}info")
        ]
    else:
        result.reason = "unsupported_root_or_namespace"
    return result
