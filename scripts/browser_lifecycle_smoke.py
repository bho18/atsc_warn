"""Self-contained synthetic receive/API/browser lifecycle and text regression."""

import json
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

from tests.fixtures.alert_examples import cap
from tests.fixtures.synthetic import wrap
from tests.integration.test_alert_inbox import ingest
from tests.integration.test_alert_variants import companion
from warnbridge.config import Config
from warnbridge.storage.store import Store
from warnbridge.transport.decoder import Decoder

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
            page.goto("http://127.0.0.1:8097")
            cards = page.locator(".alert-card")
            expect(cards).to_have_count(3)
            original_card = cards.filter(has_text="Original alert")
            expect(original_card.locator(".lifecycle")).to_have_text("Active")
            expect(cards.filter(has_text="Expired example").locator(".lifecycle")).to_have_text(
                "Expired"
            )
            expect(cards.filter(has_text="Unrecognized message")).to_have_count(1)
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
    "Browser lifecycle passed: badges, cancellation content, all-clear Alert, "
    "Unicode, failure download, mobile."
)
