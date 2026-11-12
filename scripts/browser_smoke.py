"""Optional local browser smoke test. Server must already be running on loopback."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8080")
parser.add_argument("--chromium", default="/usr/bin/chromium")
parser.add_argument("--screenshot", default="/tmp/warnbridge-ui.png")
parser.add_argument("--check-cap", action="store_true")
parser.add_argument(
    "--check-rf", action="store_true", help="test RF states with mocked health replies"
)
args = parser.parse_args()
assert urlparse(args.url).hostname in ("127.0.0.1", "localhost"), "local browser checks only"
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=args.chromium, headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 1100})
    failures = []
    external = []
    page.on("pageerror", lambda error: failures.append(str(error)))
    page.on(
        "response",
        lambda response: (
            failures.append(f"API HTTP {response.status}")
            if response.request.resource_type in ("fetch", "xhr") and response.status >= 400
            else None
        ),
    )

    def dialog(event):
        failures.append("unexpected script dialog")
        event.dismiss()

    page.on("dialog", dialog)

    def route(request):
        if urlparse(request.request.url).hostname not in ("127.0.0.1", "localhost"):
            external.append(request.request.url)
            request.abort()
        else:
            request.continue_()

    page.route("**/*", route)
    radio_state = ["locked"]
    if args.check_rf:

        def health_route(request):
            if radio_state[0] == "offline":
                request.abort()
                return
            response = request.fetch()
            body = response.json()
            body["rf_tuner"] = radio_state[0]
            body["receiver"] = {
                "state": radio_state[0],
                "host": "192.0.2.10",
                "tuner": 0,
                "age_seconds": 60 if radio_state[0] == "stale" else 1,
                "checked_at": datetime.now(UTC).isoformat(),
                "fields": {"ch": "auto:7", "lock": "8vsb", "ss": "100", "snq": "99", "seq": "100"},
                "error": "Synthetic control failure" if radio_state[0] == "unavailable" else None,
            }
            request.fulfill(response=response, body=json.dumps(body))

        page.route("**/api/v1/health", health_route)
    page.goto(args.url)
    expect(page.get_by_role("tab", name="Deliveries", exact=True)).to_have_attribute(
        "aria-selected", "true"
    )
    if args.check_rf:
        expect(page.locator("#rf")).to_have_text("8-VSB locked")
        expect(page.locator("#rfSignal")).to_contain_text("Quality 99%")
        for state, label in [
            ("stale", "Status stale"),
            ("unavailable", "Status unavailable"),
            ("stopped", "Receiver stopped"),
            ("locked", "8-VSB locked"),
        ]:
            radio_state[0] = state
            page.get_by_role("button", name="Refresh", exact=True).click()
            expect(page.locator("#rf")).to_have_text(label)
    if args.check_rf:
        radio_state[0] = "offline"
        page.get_by_role("button", name="Refresh", exact=True).click()
        expect(page.locator("#connection")).to_contain_text("Disconnected")
        expect(page.locator("#rf")).to_have_text("Status unavailable")
        radio_state[0] = "locked"
        page.get_by_role("button", name="Refresh", exact=True).click()
        expect(page.locator("#rf")).to_have_text("8-VSB locked")
    # Grouped content is a separate view from chronological delivery rows.
    page.get_by_role("tab", name="Unique content", exact=True).click()
    page.get_by_role("button", name="cmac link test", exact=True).first.click()
    page.wait_for_selector("#detail:not([hidden])")
    assert "CMAC_Alert_Attributes" in page.locator("#raw").inner_text()
    assert "not_configured" in page.locator("#fields").inner_text()
    assert not page.locator("#raw script").count()
    expect(page.locator("#historyPage")).to_contain_text("deliveries")
    if args.check_cap:
        page.get_by_role("button", name="cap", exact=True).first.click()
        expect(page.locator("#fields")).to_contain_text("<script>")
        assert not page.locator("#detail script").count()
        assert "&lt;script&gt;" in page.locator("#raw").inner_text()
    if args.check_rf:
        page.get_by_role("button", name="heartbeat", exact=True).first.click()
        expect(page.locator("#historyPage")).to_contain_text("1–10 of 36 deliveries")
        page.get_by_role("button", name="Next deliveries", exact=True).click()
        expect(page.locator("#historyPage")).to_contain_text("11–20 of 36 deliveries")
        page.locator("#source").select_option("live_hdhomerun")
        page.locator("#classification").select_option("heartbeat")
        expect(page.locator("#page")).to_have_text("1–1 of 1 contents")
        expect(page.locator("#messages")).to_contain_text("35")
        page.get_by_role("tab", name="Deliveries", exact=True).click()
        expect(page.locator("#page")).to_have_text("1–20 of 35 deliveries")
        expect(page.locator("#messages tr")).to_have_count(20)
        page.locator("#source").select_option("")
        page.locator("#classification").select_option("")
        page.get_by_role("tab", name="Unique content", exact=True).click()
        page.get_by_role("button", name="cmac link test", exact=True).first.click()
        expect(page.locator("#raw")).to_contain_text("CMAC_Alert_Attributes")
    page.screenshot(path=args.screenshot, full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(Path(args.screenshot).with_stem("warnbridge-mobile")), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert not failures, failures
    assert not external, external
    browser.close()
print("Browser smoke passed: desktop/mobile inspector, no external requests or JS errors.")
