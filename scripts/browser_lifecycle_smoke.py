"""Self-contained synthetic receive/API/browser lifecycle and text regression."""

import json
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

from tests.fixtures.alert_examples import cap
from tests.fixtures.synthetic import wrap
from tests.integration.test_alert_inbox import ingest
from tests.integration.test_alert_variants import companion
from warnbridge.config import Config
from warnbridge.storage.store import Store
from warnbridge.transport.decoder import Decoder


def check_panel_refresh(page, url):
    held = []
    fault = "hold_cancellations"
    heartbeat_id = 1
    health_offline = False

    def alerts(route):
        cancellation = parse_qs(urlparse(route.request.url).query).get("cancellations") == ["true"]
        if cancellation and fault == "hold_cancellations":
            held.append(route)
        elif not cancellation and fault == "inbox":
            route.fulfill(status=500)
        else:
            route.continue_()

    def health(route):
        if health_offline:
            route.abort()
            return
        response = route.fetch()
        data = response.json()
        data["rf_tuner"] = "locked"
        data["receiver"] = {
            "host": "test-device",
            "tuner": 1,
            "fields": {"ch": "auto:7", "lock": "8vsb"},
            "age_seconds": 1,
            "error": None,
        }
        data["connection"].update(
            state="recent",
            age_seconds=1,
            last_heartbeat={
                "id": heartbeat_id,
                "source": "live_hdhomerun",
                "received_at": datetime.now(UTC).isoformat(),
            },
        )
        route.fulfill(response=response, json=data)

    page.route("**/api/v1/health", health)
    page.route("**/api/v1/alerts?*", alerts)
    page.goto(url)
    expect(page.locator(".alert-card")).to_have_count(3)
    expect(page.locator("#heartbeat")).to_have_text("Live heartbeat")
    expect(page.locator("#rf")).to_have_text("8-VSB locked")
    expect(page.locator("#rfMeta")).to_contain_text("tuner 1")
    expect(page.locator("#connection")).to_contain_text("Local archive connected")

    page.locator("#cancellationSummary").click()
    fault = "inbox"
    assert held, "expected the cancellation request to remain pending"
    for route in held:
        route.fulfill(status=503)
    expect(page.locator("#cancellationError")).to_contain_text("Cancellation history unavailable")
    expect(page.locator(".alert-card")).to_have_count(3)
    expect(page.locator("#heartbeat")).to_have_text("Live heartbeat")
    expect(page.locator("#archiveError")).to_be_hidden()

    heartbeat_id = 2
    refresh = page.get_by_role("button", name="Refresh", exact=True)
    refresh.click()
    expect(page.locator("#archiveError")).to_contain_text("Alert inbox unavailable")
    expect(page.locator(".alert-card")).to_have_count(0)
    expect(page.locator("#cancellationSummary")).to_have_text("Cancellation history · 0")
    expect(page.locator("#cancellationError")).to_be_hidden()
    expect(page.locator("#heartbeatDot")).to_have_attribute("data-observation", "2")
    expect(page.locator("#rf")).to_have_text("8-VSB locked")
    expect(page.locator("#connection")).to_contain_text("Local archive connected")

    heartbeat_id = 3
    expect(page.locator("#heartbeatDot")).to_have_attribute("data-observation", "3", timeout=10000)
    expect(page.locator("#archiveError")).to_be_visible()

    fault = ""
    health_offline = True
    refresh.click()
    expect(page.locator("#connection")).to_contain_text("Disconnected")
    expect(page.locator("#heartbeat")).to_have_text("Connection unknown")
    expect(page.locator("#archiveError")).to_be_hidden()
    expect(page.locator(".alert-card")).to_have_count(3)
    health_offline = False
    refresh.click()
    expect(page.locator("#heartbeat")).to_have_text("Live heartbeat")
    page.locator("#cancellationSummary").click()
    page.unroute("**/api/v1/health", health)
    page.unroute("**/api/v1/alerts?*", alerts)


with tempfile.TemporaryDirectory(prefix="warnbridge-browser-") as directory:
    root = Path(directory)
    config = Config(database=str(root / "archive.db"), port=8097)
    now = datetime.now(UTC)
    sent = (now - timedelta(hours=1)).isoformat()
    expires = (now + timedelta(hours=1)).isoformat()
    reference = f"synthetic.warnbridge.example,original,{sent}"
    original = cap("original", sent=sent, expires=expires).replace(
        b"Flood warning example", "Original alert · café &amp; météo".encode()
    )
    ingest(config, wrap(original, payload_type=1, entries=(1,)))
    ingest(
        config,
        wrap(
            cap("old", sent=sent, expires=(now - timedelta(minutes=1)).isoformat()).replace(
                b"Flood warning example", b"Expired example"
            )
        ),
    )
    ingest(config, wrap(b"<future>Unknown content</future>"))
    store = Store(config.database)
    failure_raw = bytearray(wrap(b"broken framing sample"))
    failure_raw[28] ^= 1
    event = list(Decoder().feed(failure_raw))[0]
    sid = store.start_session("replay", "synthetic failure")
    store.record(sid, event, None, 0)
    store.finish_session(sid, {})
    store.close()
    config_file = root / "config.toml"
    config_file.write_text(f"database = {json.dumps(config.database)}\nport = 8097\n")
    server = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from warnbridge.cli import main; main()",
            "serve",
            "--config",
            str(config_file),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                with urlopen("http://127.0.0.1:8097/api/v1/health", timeout=1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("local test server did not start")
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.route(
                "https://tile.openstreetmap.org/**",
                lambda r: r.fulfill(
                    content_type="image/svg+xml",
                    body='<svg xmlns="http://www.w3.org/2000/svg" '
                    'width="256" height="256"><rect width="256" height="256" '
                    'fill="#fafaf5"/></svg>',
                ),
            )
            check_panel_refresh(page, "http://127.0.0.1:8097")
            cards = page.locator(".alert-card")
            expect(cards).to_have_count(3)
            original_card = cards.filter(has_text="Original alert")
            expect(original_card.locator(".lifecycle")).to_have_text("Active")
            expect(cards.filter(has_text="Expired example").locator(".lifecycle")).to_have_text(
                "Expired"
            )
            expect(cards.filter(has_text="Unrecognized message")).to_have_count(1)
            page.get_by_role("combobox", name="Alert state", exact=True).select_option("active")
            expect(cards).to_have_count(1)
            expect(cards.locator(".lifecycle")).to_have_text("Active")
            page.get_by_role("combobox", name="Alert state", exact=True).select_option("")
            expect(cards).to_have_count(3)
            original_card.locator(".alert-title").click()
            expect(page.locator("#alertDetail")).to_contain_text("café & météo")
            page.locator("#evidence").evaluate("(e)=>e.open=true")
            expect(page.locator("#raw")).to_contain_text("café &amp; météo")
            page.get_by_label("Map basemap", exact=True).select_option("streets")
            expect(page.locator(".map-status")).to_have_text("Street map · OpenStreetMap")
            # A companion arriving after the CAP card is open must merge, not add a card.
            wireless_text = (
                "Wireless paired text — café &amp; météo. Stay indoors. "
                "Keep away from windows and follow instructions from local officials. "
                "&lt;img src=x onerror=alert(1)&gt;"
            )
            ingest(config, wrap(companion("original", sent=sent, text=wireless_text)))
            page.locator("#refresh").click()
            expect(cards).to_have_count(3)
            expect(original_card).to_contain_text("CAP + CMAC")
            expect(original_card).to_contain_text("2 across formats")
            preview = original_card.get_by_role("region", name="CMAC phone preview")
            expect(preview).to_contain_text("Wireless Emergency Alert")
            expect(preview.locator(".phone-message")).to_have_text(
                wireless_text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            )
            assert not preview.locator("img").count()
            assert preview.locator(".phone-message").evaluate(
                "e=>e.scrollHeight<=e.clientHeight && getComputedStyle(e).webkitLineClamp==='none'"
            )
            original_card.screenshot(path="/tmp/warnbridge-phone-preview.png")
            expect(page.locator("#alertDetail .message-variants")).to_contain_text(
                "Wireless paired text"
            )
            expect(page.get_by_label("Map basemap", exact=True)).to_have_value("streets")
            expect(page.locator(".map-status")).to_have_text("Street map · OpenStreetMap")
            page.get_by_role("button", name="Inspect original CMAC", exact=True).click()
            expect(page.locator("#alertDetail")).to_contain_text("Wireless paired text")
            page.get_by_role("button", name="Inspect original CAP", exact=True).click()
            cancel = (
                cap("proper-cancel", references=reference, sent=now.isoformat(), expires=expires)
                .replace(b"<msgType>Alert</msgType>", b"<msgType>Cancel</msgType>")
                .replace(b"Flood warning example", b"Cancellation details")
                .replace(
                    b"DEMO ONLY: Example instructions appear here.",
                    b"Extra cancellation instructions: road reopened.",
                )
            )
            cancel = cancel.replace(b"</scope>", b"</scope><note>Cancellation root note.</note>")
            ingest(config, wrap(cancel, entries=(1,), payload_type=1))
            ingest(
                config,
                wrap(
                    companion(
                        "proper-cancel",
                        "Cancel",
                        sent=now.isoformat(),
                        text="Wireless cancellation content",
                    )
                ),
            )
            # Inspection stays open and refreshes its status and cancellation content.
            page.locator("#refresh").click()
            expect(original_card.locator(".lifecycle")).to_have_text("Cancelled")
            expect(page.locator("#alertDetail .cancellation-content")).to_contain_text(
                "road reopened"
            )
            expect(page.locator("#alertDetail .cancellation-content")).to_contain_text(
                "Cancellation root note."
            )
            expect(page.locator("#alertDetail .cancellation-content")).to_contain_text(
                "Wireless cancellation content"
            )
            expect(cards).to_have_count(3)
            expect(page.locator("#cancellationSummary")).to_have_text("Cancellation history · 1")
            clear = cap(
                "all-clear", references=reference, sent=now.isoformat(), expires=expires
            ).replace(b"Flood warning example", b"All clear as new alert")
            ingest(config, wrap(clear))
            page.locator("#refresh").click()
            expect(cards).to_have_count(4)
            expect(
                cards.filter(has_text="All clear as new alert").locator(".lifecycle")
            ).to_have_text("Active")
            page.locator("#failurePanel").evaluate("(e)=>e.open=true")
            expect(page.locator("#failureItems")).to_contain_text("crc_mismatch")
            with page.expect_download() as download:
                page.get_by_role("link", name="Download packets", exact=True).click()
            assert download.value.suggested_filename.endswith("-raw_ts.bin")
            page.get_by_role("combobox", name="Alert state", exact=True).select_option("active")
            expect(cards).to_have_count(1)
            expect(cards).to_contain_text("All clear as new alert")
            page.locator("#retentionPanel").evaluate("(e)=>e.open=true")
            expect(page.locator("#retentionPolicy")).to_contain_text("7 days")
            expect(page.locator("#retentionPolicy")).to_contain_text("30 days")
            # Confirm the preview is harmless, cancellation is harmless, and an
            # explicit purge works over ordinary HTTP (no clipboard/HTTPS dependency).
            page.locator("#purgeAge").select_option("0")
            page.locator("#previewPurge").click()
            expect(page.locator("#purgeSummary")).to_contain_text("1 failed records")
            page.locator("#cancelPurge").click()
            expect(page.locator("#failureItems")).to_contain_text("crc_mismatch")
            page.locator("#previewPurge").click()
            page.locator("#confirmPurge").click()
            expect(page.locator("#purgeStatus")).to_contain_text("Purged 1 failed records")
            expect(page.locator("#failureItems")).to_contain_text("No retained failures")
            expect(cards).to_have_count(1)
            page.get_by_role("combobox", name="Alert state", exact=True).select_option("")
            expect(cards).to_have_count(4)
            page.screenshot(path="/tmp/warnbridge-lifecycle-desktop.png", full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path="/tmp/warnbridge-lifecycle-mobile.png", full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert not errors, errors
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
print(
    "Browser lifecycle passed: independent health and alert refresh, badges, "
    "cancellation content, all-clear Alert, Unicode, failure download, mobile."
)
