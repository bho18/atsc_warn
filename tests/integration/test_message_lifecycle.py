from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from tests.fixtures.alert_examples import CMAC, cap
from tests.fixtures.synthetic import wrap
from tests.integration.test_alert_inbox import REF, ingest
from warnbridge.api.app import create_app
from warnbridge.config import Config
from warnbridge.domain.alerts import project_alert
from warnbridge.formats.xml import parse_body


def test_cancel_content_attaches_and_all_clear_alert_stays_independent(tmp_path):
    config = Config(database=str(tmp_path / "cancel.db"))
    original = cap()
    cancel = (
        cap("cancel", references=REF, sent="2026-11-12T01:02:00Z")
        .replace(b"<msgType>Alert</msgType>", b"<msgType>Cancel</msgType>")
        .replace(b"Flood warning example", b"Cancellation details")
        .replace(
            b"DEMO ONLY: Example instructions appear here.", b"All clear: roads have reopened."
        )
    )
    cancel = cancel.replace(b"</scope>", b"</scope><note>Cancellation note survives.</note>")
    # Arriving out of order must not lose the cancellation or its additional text.
    ingest(config, wrap(cancel, entries=(1,), payload_type=1))
    with TestClient(create_app(config)) as api:
        assert api.get("/api/v1/alerts").json()["total"] == 0
        history = api.get("/api/v1/alerts?cancellations=true").json()
        assert history["total"] == 1
        cancel_id = history["items"][0]["id"]
        detail = api.get(f"/api/v1/messages/{cancel_id}?source=live").json()
        assert detail["relationships"][0]["resolved_message_ids"] == []
        ingest(config, wrap(original))
        item = api.get("/api/v1/alerts").json()["items"][0]
        assert item["alert"]["lifecycle"] == "cancelled"
        content = item["alert"]["cancellations"][0]
        assert content["message_id"] == cancel_id
        assert content["note"] == "Cancellation note survives."
        assert len(content["infos"]) == 2
        assert "roads have reopened" in content["infos"][0]["instruction"]
        assert api.get(f"/api/v1/messages/{item['id']}/raw").content == original
        # Even with a reference and all-clear text, Alert is not Cancel.
        fresh = cap(
            "all-clear", references=REF, sent="2026-11-12T01:03:00Z", expires="2099-01-01T00:00:00Z"
        ).replace(b"Flood warning example", b"ALL CLEAR")
        ingest(config, wrap(fresh))
        cards = api.get("/api/v1/alerts").json()
        assert cards["total"] == 2
        clear = next(i for i in cards["items"] if i["protocol_identifier"] == "all-clear")
        assert clear["alert"]["lifecycle"] == "active"
        assert clear["alert"]["cancellations"] == []
        assert api.get(f"/api/v1/messages/{item['id']}").json()["alert"]["lifecycle"] == "cancelled"
        # Diagnostic accepted history still includes every delivery.
        assert api.get("/api/v1/deliveries").json()["total"] == 3


def test_matching_status_and_explicit_references_not_sender_or_text_heuristics(tmp_path):
    config = Config(database=str(tmp_path / "references.db"))
    ingest(config, wrap(cap()))
    # CAP does not require a cancellation's sender to equal the referenced sender.
    # Equal second precision timestamps must also work.
    cancel = cap("delegated", "Cancel", references=REF).replace(
        b"<sender>synthetic.warnbridge.example", b"<sender>delegated.example"
    )
    ingest(config, wrap(cancel))
    with TestClient(create_app(config)) as api:
        assert api.get("/api/v1/alerts").json()["items"][0]["alert"]["lifecycle"] == "cancelled"


def test_replay_identity_conflict_cannot_block_live_cancellation(tmp_path):
    config = Config(database=str(tmp_path / "scope.db"))
    ingest(config, wrap(cap()))
    ingest(config, wrap(cap().replace(b"Flood warning example", b"Conflict")), "replay")
    ingest(config, wrap(cap("cancel", "Cancel", references=REF, sent="2026-11-12T01:02:00Z")))
    with TestClient(create_app(config)) as api:
        original = api.get("/api/v1/alerts").json()["items"][0]
        assert not original["conflict"]
        assert original["alert"]["lifecycle"] == "cancelled"


def test_cmac_declared_timing_and_explicit_cap_counterpart(tmp_path):
    config = Config(database=str(tmp_path / "cmac.db"))
    cmac = CMAC.replace(
        b"</CMAC_Alert_Attributes>",
        b"""
<CMAC_sender>synthetic.warnbridge.example</CMAC_sender>
<CMAC_cap_identifier>demo-alert</CMAC_cap_identifier>
<CMAC_cap_sent_date_time>2026-11-11T20:00:00-05:00</CMAC_cap_sent_date_time>
<CMAC_expires_date_time>2099-01-01T00:00:00Z</CMAC_expires_date_time>
</CMAC_Alert_Attributes>""",
    )
    parsed = parse_body(cmac)
    assert project_alert(parsed.protocol, parsed.fields)["lifecycle"] == "active"
    ingest(config, wrap(cmac, entries=(1,)))
    ingest(config, wrap(cap()))
    ingest(config, wrap(cap("cancel", "Cancel", references=REF, sent="2026-11-12T01:02:00Z")))
    with TestClient(create_app(config)) as api:
        items = api.get("/api/v1/alerts").json()["items"]
        assert len(items) == 2
        assert all(item["alert"]["lifecycle"] == "cancelled" for item in items)
        cmac_item = next(item for item in items if item["protocol"] == "CMAC")
        assert cmac_item["alert"]["cap_message_id"]
        assert cmac_item["alert"]["cancellations"]


def test_unknown_invalid_and_unusual_status_messages_are_visible(tmp_path):
    config = Config(database=str(tmp_path / "unknown.db"))
    for body in (
        b'<future xmlns="urn:future">New content</future>',
        b"<alert broken",
        b'<?xml version="1.0" encoding="nonsense"?><root/>',
        cap(status="NewStatus"),
        cap(status="Exercise"),
    ):
        ingest(config, wrap(body))
    with TestClient(create_app(config)) as api:
        data = api.get("/api/v1/alerts").json()
        assert data["total"] == 5
        assert sum(i["validation"]["xml"] == "invalid" for i in data["items"]) == 2
        assert all(i["alert"]["lifecycle"] != "active" for i in data["items"])
        assert api.get("/api/v1/alerts?status=Unknown").json()["total"] == 3


def test_expiry_changes_at_read_time_without_new_transmission(tmp_path, monkeypatch):
    config = Config(database=str(tmp_path / "expiry.db"))
    now = datetime.now(UTC)
    ingest(
        config,
        wrap(
            cap(
                sent=(now - timedelta(hours=1)).isoformat(),
                expires=(now + timedelta(seconds=1)).isoformat(),
            )
        ),
    )
    with TestClient(create_app(config)) as api:
        assert api.get("/api/v1/alerts").json()["items"][0]["alert"]["lifecycle"] == "active"

        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return now + timedelta(seconds=2)

        monkeypatch.setattr("warnbridge.domain.alerts.datetime", Later)
        assert api.get("/api/v1/alerts").json()["items"][0]["alert"]["lifecycle"] == "expired"


def test_archive_limit_is_visible_before_it_stops_ingestion(tmp_path):
    config = Config(database=str(tmp_path / "storage.db"))
    ingest(config, wrap(cap()))
    config.max_database_bytes = 1  # Exercise read-only health against an already-created archive.
    with TestClient(create_app(config)) as api:
        health = api.get("/api/v1/health").json()
        assert health["storage"]["state"] == "full"
        assert health["storage"]["bytes"] >= health["storage"]["limit_bytes"]
