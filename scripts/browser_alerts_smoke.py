"""Local alert-demo browser checks; seed alert-demo.ts and no live alert content first."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8087")
parser.add_argument("--chromium", default="/usr/bin/chromium")
parser.add_argument("--screenshot", default="/tmp/warnbridge-alerts.png")
args = parser.parse_args()
assert urlparse(args.url).hostname in ("127.0.0.1", "localhost"), "local browser checks only"
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=args.chromium, headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 1100})
    errors, external = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("dialog", lambda d: (errors.append("unexpected script dialog"), d.dismiss()))

    def route(request):
        if urlparse(request.request.url).hostname not in ("127.0.0.1", "localhost"):
            external.append(request.request.url)
            request.abort()
        else:
            request.continue_()

    page.route("**/*", route)
    heartbeat = {
        "state": "waiting",
        "last_heartbeat": None,
        "age_seconds": None,
        "stale_after_seconds": 45,
        "scope": "live_only",
    }
    offline = [False]
    superseded = [False]

    def detail_route(request):
        path = urlparse(request.request.url).path
        if path.endswith("/raw"):
            request.continue_()
            return
        response = request.fetch()
        data = response.json()
        if superseded[0] and data.get("alert"):
            data["alert"]["lifecycle"] = "superseded"
        request.fulfill(response=response, body=json.dumps(data))

    page.route("**/api/v1/messages/*?*", detail_route)

    def health(request):
        if offline[0]:
            request.abort()
            return
        response = request.fetch()
        data = response.json()
        data["connection"] = heartbeat
        request.fulfill(response=response, body=json.dumps(data))

    page.route("**/api/v1/health", health)
    page.goto(args.url)
    expect(page.locator("#viewTitle")).to_have_text("Alert inbox")
    expect(page.locator("#alertCards")).to_contain_text("No matching alerts received")
    expect(page.locator("#heartbeat")).to_have_text("Waiting for heartbeat")
    assert not page.locator("#heartbeatDot").get_attribute("data-observation")
    assert not page.locator("#diagnosticArchive").is_visible()
    page.locator("#source").select_option("replay")
    expect(page.locator(".alert-card")).to_have_count(8)
    expect(page.locator("#alertCards")).not_to_contain_text("cmac link test")
    page.locator("#alertStatus").select_option("Test")
    expect(page.locator(".alert-card")).to_have_count(2)
    expect(page.locator("#alertCards")).to_contain_text("Test · declared")
    page.locator("#alertStatus").select_option("Actual")
    expect(page.locator(".alert-card")).to_have_count(6)
    page.get_by_role("button", name="CMAC Alert", exact=True).click()
    expect(page.locator("#alertDetail")).to_contain_text("current schema unverified")
    expect(page.locator("#alertDetail")).to_contain_text("Preserve this unknown field.")
    page.get_by_role("button", name="DEMO ONLY — Flood warning example", exact=True).first.click()
    expect(page.locator("#alertDetail")).to_contain_text("Example instructions appear here")
    expect(page.locator("#alertDetail svg")).to_have_count(1)
    expect(page.locator("#alertDetail polygon")).to_have_count(2)
    expect(page.locator("#alertDetail")).to_contain_text("047037")
    expect(page.locator("#alertDetail")).to_contain_text("CMAMlongtext")
    page.locator("#alertLanguage").select_option("1")
    expect(page.locator("#alertDetail")).to_contain_text("Instrucciones de ejemplo")
    expect(page.locator("#alertDetail")).to_contain_text("No plottable coordinates supplied")
    expect(page.locator("#alertDetail svg")).to_have_count(0)
    superseded[0] = True
    page.get_by_role("button", name="Refresh", exact=True).click()
    expect(page.locator("#alertDetail")).to_contain_text("Superseded by update")
    expect(page.locator("#alertLanguage")).to_have_value("1")
    superseded[0] = False
    page.locator("#alertLanguage").select_option("0")
    page.locator("#close").click()
    page.locator("#alertStatus").select_option("")
    expect(page.locator("#alertCards")).to_contain_text("Cancelled by reference")
    expect(page.locator("#alertCards")).to_contain_text("Expired")
    page.evaluate("""window.beats=0;document.getElementById('heartbeatDot').addEventListener(
        'animationstart',e=>{window.beats++;e.target.dataset.beats=String(window.beats);});""")
    heartbeat.update(
        state="recent",
        age_seconds=1,
        last_heartbeat={
            "id": 900,
            "received_at": datetime.now(UTC).isoformat(),
            "source": "live_udp",
            "session_id": "synthetic-browser",
            "session_state": "running",
        },
    )
    page.locator("#refresh").click()
    expect(page.locator("#heartbeat")).to_have_text("Live heartbeat")
    expect(page.locator("#heartbeatDot")).to_have_attribute("data-beats", "1")
    page.locator("#refresh").click()
    page.wait_for_timeout(1800)
    assert page.evaluate("window.beats") == 1  # Polling the same observation must not pulse.
    heartbeat["last_heartbeat"]["id"] = 901
    page.locator("#refresh").click()
    expect(page.locator("#heartbeatDot")).to_have_attribute("data-beats", "2")
    heartbeat["age_seconds"] = 44.8
    page.locator("#refresh").click()
    expect(page.locator("#heartbeat")).to_have_text("Heartbeat overdue", timeout=3000)
    assert "beat" not in page.locator("#heartbeatDot").get_attribute("class").split()
    heartbeat["age_seconds"] = 1
    heartbeat["state"] = "stopped"
    page.locator("#refresh").click()
    expect(page.locator("#heartbeat")).to_have_text("Receiver stopped")
    heartbeat["state"] = "recent"
    offline[0] = True
    page.locator("#refresh").click()
    expect(page.locator("#heartbeat")).to_have_text("Connection unknown")
    assert "recent" not in page.locator("#heartbeatDot").get_attribute("class")
    offline[0] = False
    heartbeat["state"] = "waiting"
    heartbeat["last_heartbeat"] = None
    heartbeat["age_seconds"] = None
    page.locator("#refresh").click()
    expect(page.locator("#heartbeat")).to_have_text("Waiting for heartbeat")
    # All example cards say Replay; UI never fetches URLs carried by messages.
    for card in page.locator(".alert-card").all():
        expect(card).to_contain_text("Replay")
    page.screenshot(path=args.screenshot, full_page=True)
    page.get_by_role("button", name="DEMO ONLY — Flood warning example", exact=True).first.click()
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(
        path=str(Path(args.screenshot).with_stem("warnbridge-alert-mobile")), full_page=True
    )
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.emulate_media(reduced_motion="reduce")
    heartbeat.update(
        state="recent",
        age_seconds=1,
        last_heartbeat={
            "id": 902,
            "received_at": datetime.now(UTC).isoformat(),
            "source": "live_udp",
        },
    )
    page.locator("#refresh").click()
    expect(page.locator("#heartbeat")).to_have_text("Live heartbeat")
    assert (
        page.locator("#heartbeatDot").evaluate("e => e.getAnimations({subtree:true}).length") == 0
    )
    assert not external, external
    assert not errors, errors
    browser.close()
print("Alert browser smoke passed: sources, CAP languages/areas, CMAC review, heartbeat freshness.")
