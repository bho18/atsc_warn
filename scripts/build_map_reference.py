"""Reduce pinned Natural Earth GeoJSON files to a small offline reference basemap.

See docs/maps.md for the source URLs. This script uses local inputs only:
python -m scripts.build_map_reference --source-dir /tmp
"""

import argparse
import hashlib
import json
from pathlib import Path

COMMIT = "ca96624a56bd078437bca8184e78163e5039ad19"
ROOT = f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{COMMIT}"
SOURCES = {
    "countries": "ne_110m_admin_0_countries.geojson",
    "states": "ne_110m_admin_1_states_provinces.geojson",
    "places": "ne_50m_populated_places.geojson",
}


def rounded(value):
    return [rounded(v) for v in value] if isinstance(value, list) else round(value, 4)


def build(source_dir: Path, destination: Path):
    features, sources = [], []
    for layer, filename in SOURCES.items():
        blob = (source_dir / f"warnbridge-ne-{layer}.geojson").read_bytes()
        sources.append(
            {"url": f"{ROOT}/geojson/{filename}", "sha256": hashlib.sha256(blob).hexdigest()}
        )
        for f in json.loads(blob)["features"]:
            p = f["properties"]
            properties = {"layer": layer, "name": p.get("NAME_EN") or p.get("name_en")}
            if layer == "countries":
                properties.update(label=[p["LABEL_Y"], p["LABEL_X"]], min_zoom=p["MIN_LABEL"])
            elif layer == "states":
                properties.update(label=[p["latitude"], p["longitude"]], min_zoom=p["min_label"])
            else:
                properties.update(min_zoom=p["MIN_ZOOM"])
            features.append(
                {
                    "type": "Feature",
                    "properties": properties,
                    "geometry": {
                        "type": f["geometry"]["type"],
                        "coordinates": rounded(f["geometry"]["coordinates"]),
                    },
                }
            )
    destination.mkdir(parents=True, exist_ok=True)
    payload = {"type": "FeatureCollection", "features": features}
    (destination / "reference.geojson").write_text(
        json.dumps(payload, separators=(",", ":")) + "\n"
    )
    license_blob = (source_dir / "warnbridge-ne-license.md").read_bytes()
    (destination / "LICENSE.md").write_bytes(license_blob)
    manifest = {
        "dataset": "Natural Earth",
        "commit": COMMIT,
        "license": "Public domain",
        "sources": sources,
        "license_url": f"{ROOT}/LICENSE.md",
        "license_sha256": hashlib.sha256(license_blob).hexdigest(),
        "transformation": "Keep names/label locations/minimum zoom and geometry; round basemap "
        "coordinates to four decimals. Alert coordinates are never modified.",
        "feature_count": len(features),
        "output_sha256": hashlib.sha256(
            (destination / "reference.geojson").read_bytes()
        ).hexdigest(),
    }
    (destination / "provenance.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote {len(features)} reference features to {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path("/tmp"))
    parser.add_argument("--destination", type=Path, default=Path("src/warnbridge/web/maps"))
    options = parser.parse_args()
    build(options.source_dir, options.destination)
