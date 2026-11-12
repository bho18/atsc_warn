from datetime import UTC, datetime

import pytest

from tests.fixtures.alert_examples import CMAC, cap
from warnbridge.domain.alerts import geometry, project_alert
from warnbridge.formats.xml import parse_body

NOW = datetime(2026, 11, 12, 2, tzinfo=UTC)


def project(raw, now=NOW):
    parsed = parse_body(raw)
    return project_alert(parsed.protocol, parsed.fields, now=now)


def test_cap_readable_multilingual_instructions_parameters_and_separate_areas():
    raw = cap()
    parsed = parse_body(raw)
    alert = project(raw)
    assert parsed.xml == raw
    assert alert["status"] == "Actual" and alert["message_type"] == "Alert"
    english, spanish = alert["infos"]
    assert english["language"] == "en-US" and spanish["language"] == "es-US"
    assert english["severity"] == "Severe" and english["certainty"] == "Observed"
    assert "not a real warning" in english["instruction"]
    assert [p["name"] for p in english["parameters"]] == ["CMAMtext", "CMAMlongtext"]
    assert len(english["areas"]) == 2
    area, circle = english["areas"]
    assert area["geocodes"] == [{"name": "SAME", "value": "047037"}]
    assert area["polygons"] == ["36,-87 36,-86 35,-86 36,-87"]
    assert area["geometry"]["features"][0]["geometry"]["coordinates"][0][0] == [-87, 36]
    feature = circle["geometry"]["features"][0]
    assert feature["properties"]["radius_km"] == 5
    assert feature["properties"]["derived"]
    ring = feature["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1] and len(ring) == 65
    assert ring[0][1] - 36.1 == pytest.approx(5 / 111.195, rel=0.001)
    assert not spanish["areas"][0]["geometry"]["features"]  # No invented county boundary.


@pytest.mark.parametrize(
    "polygon",
    [
        "36,-87 36,-86 35,-86",  # too few / not closed
        "36,-87 36,-86 35,-86 35,-87",  # not closed
        "91,-87 36,-86 35,-86 91,-87",
        "nan,-87 36,-86 35,-86 nan,-87",
        "36,181 36,-86 35,-86 36,181",
        " ".join(["36,-87"] * 4097),
    ],
)
def test_bad_polygon_does_not_become_plottable(polygon):
    result = geometry([polygon], [])
    assert not result["features"] and result["issues"]


@pytest.mark.parametrize(
    "circle", ["36,-87 -1", "36,-87 nan", "36,-87 10001", "36,-87", "91,-87 5"]
)
def test_bad_circle_is_reported_without_guessing(circle):
    result = geometry([], [circle])
    assert not result["features"] and result["issues"]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, "active"),
        ({"status": "Test"}, "non_actual"),
        ({"expires": "2026-11-12T01:00:01Z"}, "expired"),
        ({"sent": "2026-11-13T01:00:00Z"}, "scheduled"),
        ({"expires": ""}, "unknown"),
        ({"expires": "2026-11-14T01:00:00"}, "unknown"),
        ({"kind": "Cancel"}, "cancellation"),
        ({"kind": "Ack"}, "acknowledgement"),
        ({"kind": "Error"}, "error_message"),
    ],
)
def test_declared_cap_timing(changes, expected):
    assert project(cap(**changes))["lifecycle"] == expected


def test_missing_one_expiry_prevents_unqualified_active_label():
    raw = cap().replace(b"<expires>2026-11-14T01:00:00Z</expires>", b"", 1)
    assert project(raw)["lifecycle"] == "unknown"


def test_cmac_preserves_leaf_names_repeats_and_unknown_fields_without_cap_guessing():
    raw = CMAC.replace(
        b"</CMAC_alert_info>", b"<CMAC_text_language>es-US</CMAC_text_language></CMAC_alert_info>"
    )
    alert = project(raw)
    assert alert["protocol"] == "CMAC" and alert["status"] == "Actual"
    assert alert["lifecycle"] == "unverified_cmac" and alert["infos"] == []
    assert "current schema unverified" in alert["interpretation"]
    segments = alert["segments"]
    assert {"field": "CMAC_unknown_extension", "value": "Preserve this unknown field."} in segments
    assert [s["value"] for s in segments if s["field"] == "CMAC_text_language"] == [
        "en-US",
        "es-US",
    ]
    assert parse_body(raw).xml == raw
