import pytest
from fastapi.testclient import TestClient

from tests.fixtures.alert_examples import cap
from tests.fixtures.synthetic import wrap
from tests.integration.test_alert_inbox import ingest
from warnbridge.api.app import create_app
from warnbridge.config import Config
from warnbridge.formats.xml import parse_body, readable_text


@pytest.mark.parametrize("encoding", ["utf-8", "iso-8859-1", "utf-16", "utf-16-be", "utf-16-le"])
@pytest.mark.parametrize("terminator", [b"", b"\x00"])
def test_text_entities_accents_and_original_bytes_roundtrip(tmp_path, encoding, terminator):
    text = (
        cap()
        .decode()
        .replace(
            'encoding="UTF-8"', f'encoding="{encoding.replace("-be", "BE").replace("-le", "LE")}"'
        )
        .replace("Flood warning example", "Évacuation à Montréal &amp; café")
        .replace("Datos sintéticos", "Precaución: inundación")
        .replace("—", "-")
    )
    raw = text.encode(encoding)
    body = raw + terminator
    parsed = parse_body(body)
    assert parsed.xml_state == "well_formed"
    assert parsed.xml == raw
    config = Config(database=str(tmp_path / "text.db"))
    ingest(config, wrap(body, payload_type=1, entries=(1,)))
    with TestClient(create_app(config)) as api:
        item = api.get("/api/v1/alerts").json()["items"][0]
        assert "Évacuation à Montréal & café" in item["alert"]["headline"]
        mid = item["id"]
        assert api.get(f"/api/v1/messages/{mid}/text").text == text
        assert api.get(f"/api/v1/messages/{mid}/raw").content == raw
        assert api.get(f"/api/v1/messages/{mid}/raw?part=body").content == body
        assert api.get(f"/api/v1/messages/{mid}/text?part=assembled").status_code == 422


def test_undecodable_bytes_have_hex_preview_instead_of_replacement_characters():
    assert readable_text(b"\xff\x00\x98").endswith("ff 00 98")
    assert "\ufffd" not in readable_text(b"\xff\x00\x98")
