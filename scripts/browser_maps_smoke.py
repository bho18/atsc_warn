"""Local Leaflet browser checks using synthetic alert-demo.ts replay data only."""

import argparse
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8087")
parser.add_argument("--chromium", default="/usr/bin/chromium")
parser.add_argument("--screenshot", default="/tmp/warnbridge-map.png")
args = parser.parse_args()
assert urlparse(args.url).hostname in ("127.0.0.1", "localhost"), "local browser checks only"
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=args.chromium, headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 1100})
    errors, external, tiles = [], [], []
    tile_mode = ["success"]
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("dialog", lambda d: (errors.append("unexpected script dialog"), d.dismiss()))
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

    def route(request):
        url = urlparse(request.request.url)
        if url.hostname in ("127.0.0.1", "localhost"):
            request.continue_()
        elif url.hostname == "tile.openstreetmap.org":
            tiles.append(request.request.url)
            if tile_mode[0] == "failure":
                request.abort()
            else:
                # Local synthetic tile response; never contacts the real tile provider.
                request.fulfill(
                    path="src/warnbridge/web/vendor/leaflet/images/layers.png",
                    content_type="image/png",
                )
        else:
            external.append(request.request.url)
            request.abort()

    page.route("**/*", route)
    page.goto(args.url)
    page.locator("#source").select_option("replay")
    page.locator("#alertStatus").select_option("Actual")
    page.get_by_role("button", name="DEMO ONLY — Flood warning example", exact=True).first.click()
    widget = page.locator(".alert-map")
    expect(widget).to_have_attribute("data-ready", "true")
    expect(page.locator(".map-status")).to_have_text("Offline reference map · Natural Earth")
    assert page.evaluate("L.version") == "1.9.4"
    expect(page.locator(".alert-area-shape")).to_have_count(2)
    expect(page.locator(".reference-label")).not_to_have_count(0)
    expect(page.locator(".leaflet-control-attribution")).to_contain_text("Natural Earth")
    assert not tiles and not external  # Offline basemap must be truly local by default.
    initial_scale = page.locator(".leaflet-control-scale-line").first.inner_text()
    page.locator(".leaflet-control-zoom-in").click()
    assert page.locator(".leaflet-control-scale-line").first.inner_text() != initial_scale
    page.get_by_role("button", name="Fit alert areas", exact=True).click()
    expect(page.locator(".leaflet-control-scale-line").first).to_have_text(initial_scale)
    page.locator(".alert-area-shape").nth(1).click(force=True)
    expect(page.locator(".leaflet-popup")).to_contain_text("Synthetic circle area")
    expect(page.locator(".leaflet-popup")).to_contain_text("5 km radius")
    page.locator(".leaflet-popup-close-button").click()
    widget.scroll_into_view_if_needed()
    before_pan = page.locator(".leaflet-map-pane").get_attribute("style")
    box = widget.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 100)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2 + 100, box["y"] + 140, steps=8)
    page.mouse.up()
    assert page.locator(".leaflet-map-pane").get_attribute("style") != before_pan
    page.get_by_role("button", name="Fit alert areas", exact=True).click()
    page.get_by_label("Map basemap", exact=True).select_option("streets")
    expect(page.locator(".map-status")).to_have_text("Street map · OpenStreetMap")
    assert tiles
    expect(page.locator(".leaflet-control-attribution")).to_contain_text("OpenStreetMap")
    page.get_by_label("Map basemap", exact=True).select_option("offline")
    expect(page.locator(".map-status")).to_have_text("Offline reference map · Natural Earth")
    tile_mode[0] = "failure"
    prior_errors = len(errors)
    # Use a new zoom level so previously decoded image tiles cannot mask failure.
    page.locator(".leaflet-control-zoom-in").click()
    page.locator(".leaflet-control-zoom-in").click()
    page.get_by_label("Map basemap", exact=True).select_option("streets")
    expect(page.locator(".map-status")).to_have_text(
        "Street tiles unavailable · showing offline reference map"
    )
    expect(page.get_by_label("Map basemap", exact=True)).to_have_value("offline")
    expect(page.locator(".alert-area-shape")).to_have_count(2)
    # Browser reports intentionally aborted tile loads; keep unrelated console errors fatal.
    errors[prior_errors:] = [e for e in errors[prior_errors:] if "net::ERR_FAILED" not in e]
    tile_mode[0] = "success"
    page.locator("#alertLanguage").select_option("1")
    expect(page.locator(".alert-map")).to_have_count(0)
    for _ in range(3):
        page.locator("#alertLanguage").select_option("0")
        expect(page.locator(".alert-map")).to_have_attribute("data-ready", "true")
        expect(page.locator(".alert-area-shape")).to_have_count(2)
        page.locator("#alertLanguage").select_option("1")
        expect(page.locator(".alert-map")).to_have_count(0)
    page.locator("#alertLanguage").select_option("0")
    expect(page.locator(".map-status")).to_have_text("Offline reference map · Natural Earth")
    page.locator(".area-map").screenshot(path=args.screenshot)
    page.set_viewport_size({"width": 390, "height": 844})
    expect(widget).to_have_attribute("data-ready", "true")
    page.get_by_role("button", name="Fit alert areas", exact=True).click()
    page.locator(".area-map").screenshot(
        path=str(Path(args.screenshot).with_stem("warnbridge-map-mobile"))
    )
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    # Exercise the renderer with a small dateline-crossing area and a polar area.
    for coordinates, polar in [
        ([[179, 10], [-179, 10], [-179, 11], [179, 10]], False),
        ([[10, 87], [11, 87], [11, 88], [10, 87]], True),
    ]:
        page.evaluate(
            """coordinates => {
          const target=document.getElementById('alertDetail');target.replaceChildren();
          WarnBridgeMap.render(target,[{description:'<img src=x onerror=alert(1)>',geometry:{
            features:[{properties:{shape:'polygon',derived:false},geometry:{
              type:'Polygon',coordinates:[coordinates]}}]}}]);
        }""",
            coordinates,
        )
        expect(widget).to_have_attribute("data-ready", "true")
        expect(page.locator(".alert-area-shape")).to_have_count(1)
        if polar:
            assert page.get_by_label("Map basemap").locator("option[value=streets]").is_disabled()
        else:
            # A 2-degree dateline area should fit locally, not span the entire world.
            expect(page.locator(".leaflet-control-scale")).not_to_contain_text("1000 km")
        page.locator(".alert-area-shape").click(force=True)
        expect(page.locator(".leaflet-popup")).to_contain_text("<img src=x onerror=alert(1)>")
        assert not page.locator(".leaflet-popup img").count()
    assert not external, external
    assert not errors, errors
    # A missing reference asset must not prevent rendering supplied alert areas.
    fault = browser.new_page(viewport={"width": 1000, "height": 900})
    fault_errors = []
    fault.on("pageerror", lambda error: fault_errors.append(str(error)))

    def fault_route(request):
        host = urlparse(request.request.url).hostname
        if host not in ("127.0.0.1", "localhost"):
            external.append(request.request.url)
            request.abort()
        elif request.request.url.endswith("/maps/reference.geojson"):
            request.abort()
        else:
            request.continue_()

    fault.route("**/*", fault_route)
    fault.goto(args.url)
    fault.locator("#source").select_option("replay")
    fault.locator("#alertStatus").select_option("Actual")
    fault.get_by_role("button", name="DEMO ONLY — Flood warning example", exact=True).first.click()
    expect(fault.locator(".map-status")).to_have_text(
        "Reference basemap unavailable · alert geometry remains visible"
    )
    expect(fault.locator(".alert-area-shape")).to_have_count(2)
    fault.get_by_role("button", name="Fit alert areas", exact=True).click()
    assert not fault_errors, fault_errors
    assert not external, external
    browser.close()
print("Map browser smoke passed: offline, map controls, popups, tiles, mobile, dateline/poles.")
