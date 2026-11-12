"""Read-only alert presentation from preserved trees; never repairs original XML.

CAP presentation follows CAP 1.2. CMAC 2.0 field display is experimental until its
current schema/actual alert samples are available; unknown fields stay visible.
"""

import math
from datetime import UTC, datetime
from typing import Any

from warnbridge.formats.xml import CAP, CMAC, utc_time

Tree = dict[str, Any]


def children(node: Tree, namespace: str, *names: str) -> list[Tree]:
    tags = {f"{{{namespace}}}{name}" for name in names}
    return [c for c in node.get("children", []) if c["tag"] in tags]


def texts(node: Tree, namespace: str, name: str) -> list[str]:
    return [c.get("text") or "" for c in children(node, namespace, name)]


def value(node: Tree, namespace: str, name: str) -> str | None:
    found = texts(node, namespace, name)
    return found[0] if len(found) == 1 else None


def walk(node: Tree) -> list[Tree]:
    result = [node]
    for child in node.get("children", []):
        result.extend(walk(child))
    return result


def pairs(node: Tree, namespace: str, name: str) -> list[dict[str, Any]]:
    return [
        {"name": value(c, namespace, "valueName"), "value": value(c, namespace, "value")}
        for c in children(node, namespace, name)
    ]


def point(raw: str) -> list[float]:
    pieces = raw.split(",")
    if len(pieces) != 2:
        raise ValueError("expected latitude,longitude")
    lat, lon = map(float, pieces)
    if (
        not math.isfinite(lat)
        or not math.isfinite(lon)
        or not (-90 <= lat <= 90 and -180 <= lon <= 180)
    ):
        raise ValueError("coordinate out of range")
    return [lon, lat]  # Explicit CAP lat,lon -> GeoJSON lon,lat.


def geometry(polygons: list[str], circles: list[str]) -> dict[str, Any]:
    features, issues = [], []
    for raw in polygons:
        try:
            tokens = raw.split()
            if not 4 <= len(tokens) <= 4096:
                raise ValueError("polygon requires 4–4096 vertices")
            points = [point(token) for token in tokens]
            if points[0] != points[-1]:
                raise ValueError("polygon ring is not closed")
            features.append(
                {
                    "type": "Feature",
                    "properties": {"shape": "polygon", "derived": False},
                    "geometry": {"type": "Polygon", "coordinates": [points]},
                }
            )
        except ValueError as exc:
            issues.append(str(exc))
    for raw in circles:
        try:
            center, distance = raw.split()
            lon, lat = point(center)
            radius = float(distance)
            if not math.isfinite(radius) or not 0 < radius <= 10000:
                raise ValueError("circle radius outside plotting bounds")
            lat1, lon1, angle = math.radians(lat), math.radians(lon), radius / 6371.0088
            ring = []
            for i in range(64):
                bearing = 2 * math.pi * i / 64
                lat2 = math.asin(
                    max(
                        -1,
                        min(
                            1,
                            math.sin(lat1) * math.cos(angle)
                            + math.cos(lat1) * math.sin(angle) * math.cos(bearing),
                        ),
                    )
                )
                lon2 = lon1 + math.atan2(
                    math.sin(bearing) * math.sin(angle) * math.cos(lat1),
                    math.cos(angle) - math.sin(lat1) * math.sin(lat2),
                )
                ring.append([(math.degrees(lon2) + 180) % 360 - 180, math.degrees(lat2)])
            ring.append(ring[0])
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "shape": "circle",
                        "derived": True,
                        "radius_km": radius,
                        "approximation": "64-point geodesic boundary",
                    },
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                }
            )
        except (ValueError, OverflowError) as exc:
            issues.append(str(exc))
    return {"type": "FeatureCollection", "features": features, "issues": issues}


def cap_info(node: Tree) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in (
        "language",
        "event",
        "urgency",
        "severity",
        "certainty",
        "effective",
        "onset",
        "expires",
        "senderName",
        "headline",
        "description",
        "instruction",
        "web",
    ):
        result[key] = value(node, CAP, key)
    for key in ("category", "responseType"):
        result[key] = texts(node, CAP, key)
    result["language"] = result["language"] or "en-US"
    result["parameters"] = pairs(node, CAP, "parameter")
    result["event_codes"] = pairs(node, CAP, "eventCode")
    result["areas"] = []
    for area in children(node, CAP, "area"):
        polygons, circles = texts(area, CAP, "polygon"), texts(area, CAP, "circle")
        result["areas"].append(
            {
                "description": value(area, CAP, "areaDesc"),
                "polygons": polygons,
                "circles": circles,
                "geocodes": pairs(area, CAP, "geocode"),
                "altitude": value(area, CAP, "altitude"),
                "ceiling": value(area, CAP, "ceiling"),
                "geometry": geometry(polygons, circles),
            }
        )
    return result


def timing(status: str | None, periods: list[tuple[str, str]], now: datetime) -> str:
    parsed = [(utc_time(e), utc_time(x)) for e, x in periods]
    if not parsed or any(e is None or x is None or e >= x for e, x in parsed):
        return "unknown"
    valid = [(e, x) for e, x in parsed if e is not None and x is not None]
    if all(x <= now for _, x in valid):
        return "expired"
    if any(e <= now < x for e, x in valid):
        return "active" if status == "Actual" else "non_actual"
    return "scheduled"


def project_alert(protocol: str, fields: Tree, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    root = fields.get("tree", {})
    result: dict[str, Any] = {
        "protocol": protocol,
        "interpretation": "CAP 1.2 field view",
        "status": None,
        "message_type": None,
        "scope": None,
        "sender": None,
        "identifier": None,
        "sent": None,
        "infos": [],
        "lifecycle": "unknown",
        "relationships": [],
        "cancellations": [],
        "issues": [],
    }
    if protocol == "CAP":
        for output, source in (
            ("status", "status"),
            ("message_type", "msgType"),
            ("scope", "scope"),
            ("sender", "sender"),
            ("identifier", "identifier"),
            ("sent", "sent"),
        ):
            result[output] = value(root, CAP, source) or None
        result["infos"] = [cap_info(c) for c in children(root, CAP, "info")]
        result["references"] = fields.get("references", "")
        if result["message_type"] == "Cancel":
            result["lifecycle"] = "cancellation"
        elif result["message_type"] in ("Ack", "Error"):
            result["lifecycle"] = (
                "acknowledgement" if result["message_type"] == "Ack" else "error_message"
            )
        elif result["message_type"] in ("Alert", "Update") and result["infos"]:
            result["lifecycle"] = timing(
                result["status"],
                [
                    (info["effective"] or result["sent"] or "", info["expires"] or "")
                    for info in result["infos"]
                ],
                now,
            )
        if not result["infos"] and result["message_type"] != "Cancel":
            result["issues"].append("No CAP info blocks supplied")
    elif protocol == "CMAC":
        result["interpretation"] = "Experimental CMAC field view; current schema unverified"
        for output, source in (
            ("status", "CMAC_status"),
            ("message_type", "CMAC_message_type"),
            ("sender", "CMAC_sender"),
            ("identifier", "CMAC_message_number"),
            ("sent", "CMAC_sent_date_time"),
        ):
            result[output] = value(root, CMAC, source)
        result["sender"] = result["sender"] or value(root, CMAC, "CMAC_sending_gateway_id")
        # Every CMAC leaf remains available under its original field name, including
        # repeated text/language/area segments. No speculative CAP normalization.
        result["segments"] = []
        for node in walk(root):
            if node.get("tag", "").startswith(f"{{{CMAC}}}") and not node.get("children"):
                text = node.get("text")
                if text is not None:
                    result["segments"].append(
                        {"field": node["tag"].split("}", 1)[1], "value": text}
                    )
        expiries = [
            s["value"] for s in result["segments"] if s["field"] == "CMAC_expires_date_time"
        ]
        result["expires"] = expiries
        if result["message_type"] in ("Alert", "Update"):
            result["lifecycle"] = timing(
                result["status"], [(result["sent"] or "", expiry) for expiry in expiries], now
            )
        result["preview"] = next(
            (
                segment["value"]
                for field in (
                    "CMAC_long_text_alert_message",
                    "CMAC_text_alert_message",
                    "CMAC_short_text_alert_message",
                )
                for segment in result["segments"]
                if segment["field"] == field
            ),
            None,
        )
    else:
        result["issues"].append("Unsupported alert protocol")
    result["headline"] = next(
        (i["headline"] or i["event"] for i in result["infos"] if i["headline"] or i["event"]), None
    ) or (
        f"CMAC {result['message_type'] or 'message'}"
        if protocol == "CMAC"
        else f"CAP {result['message_type'] or 'message'}"
        if protocol == "CAP"
        else "Unrecognized message · inspect original bytes"
    )
    return result
