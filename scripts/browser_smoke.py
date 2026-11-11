"""Optional local browser smoke test. Server must already be running on loopback."""

import argparse
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8080")
parser.add_argument("--chromium", default="/usr/bin/chromium")
parser.add_argument("--screenshot", default="/tmp/warnbridge-ui.png")
parser.add_argument("--check-cap", action="store_true")
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
    page.goto(args.url)
    page.get_by_role("button", name="cmac link test", exact=True).click()
    page.wait_for_selector("#detail:not([hidden])")
    assert "CMAC_Alert_Attributes" in page.locator("#raw").inner_text()
    assert "not_configured" in page.locator("#fields").inner_text()
    assert not page.locator("#raw script").count()
    if args.check_cap:
        page.get_by_role("button", name="cap", exact=True).click()
        expect(page.locator("#fields")).to_contain_text("<script>")
        assert not page.locator("#detail script").count()
        assert "&lt;script&gt;" in page.locator("#raw").inner_text()
    page.screenshot(path=args.screenshot, full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(Path(args.screenshot).with_stem("warnbridge-mobile")), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert not failures, failures
    assert not external, external
    browser.close()
print("Browser smoke passed: desktop/mobile inspector, no external requests or JS errors.")
