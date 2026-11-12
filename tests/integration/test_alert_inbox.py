from datetime import UTC, datetime, timedelta
from io import BytesIO

from fastapi.testclient import TestClient

from tests.fixtures.alert_examples import CMAC, cap
from tests.fixtures.golden import cmac, heartbeat
from tests.fixtures.synthetic import wrap
from warnbridge.api.app import create_app
from warnbridge.config import Config
from warnbridge.inputs.streams import Chunk, file_chunks
from warnbridge.pipeline import Ingestor
from warnbridge.storage.store import Store

REF = "synthetic.warnbridge.example,demo-alert,2026-11-12T01:00:00Z"


def ingest(config, raw, source="live_udp"):
    return Ingestor(config, source, "synthetic inbox test").process(file_chunks(BytesIO(raw)))


def test_alert_transport_to_api_default_live_scope_diagnostics_and_exact_bytes(tmp_path):
    config = Config(database=str(tmp_path / "alerts.db"))
    ingest(config, cmac() + heartbeat())
    ingest(config, wrap(cap()))
    ingest(config, wrap(cap()), "replay")  # Same bytes never mix the scoped count.
    ingest(config, wrap(CMAC), "live_hdhomerun")
    ingest(config, wrap(cap("demo-test", status="Test")))
    ingest(config, wrap(cap("replay-only")), "replay")
    with TestClient(create_app(config)) as api:
        data = api.get("/api/v1/alerts").json()
        assert data["total"] == 3
        assert {m["classification"] for m in data["items"]} == {"cap", "cmac"}
        assert all(m["sources"] != ["replay"] for m in data["items"])
        assert api.get("/api/v1/alerts?status=Actual").json()["total"] == 2
        assert api.get("/api/v1/alerts?status=Test").json()["total"] == 1
        assert api.get("/api/v1/alerts?source=replay").json()["total"] == 2
        assert api.get("/api/v1/alerts?source=all").json()["total"] == 4
        assert api.get("/api/v1/alerts?source=live&limit=1&offset=2").json()["total"] == 3
        assert len(api.get("/api/v1/alerts?limit=1&offset=2").json()["items"]) == 1
        assert api.get("/api/v1/alerts?limit=101").status_code == 422
        assert api.get("/api/v1/alerts?offset=-1").status_code == 422
        alert = next(m for m in data["items"] if m["protocol_identifier"] == "demo-alert")
        assert alert["delivery_count"] == 1 and alert["sources"] == ["live_udp"]
        assert api.get(f"/api/v1/messages/{alert['id']}/raw").content == cap()
        assert alert["validation"]["signature"] == "not_checked"
        assert alert["operational_notifications"] == "disabled"
        assert api.get("/api/v1/messages?source=live").json()["total"] == 5
        assert api.get("/api/v1/deliveries?source=live").json()["total"] == 5
        assert api.get("/api/v1/health").json()["connection"]["state"] == "stopped"


def test_unknown_cmac_status_is_not_presented_as_actual(tmp_path):
    config = Config(database=str(tmp_path / "ambiguous.db"))
    ingest(
        config,
        wrap(
            CMAC.replace(
                b"<CMAC_status>Actual</CMAC_status>",
                b"<CMAC_status>Actual</CMAC_status><CMAC_status>System</CMAC_status>",
            )
        ),
    )
    ingest(config, wrap(cap(status="")))
    with TestClient(create_app(config)) as api:
        assert api.get("/api/v1/alerts?status=Actual").json()["total"] == 0
        unknown = api.get("/api/v1/alerts?status=Unknown").json()
        assert unknown["total"] == 2
        assert all(m["alert"]["status"] is None for m in unknown["items"])


def test_out_of_order_cap_references_are_source_scoped_and_not_overwrites(tmp_path):
    config = Config(database=str(tmp_path / "lifecycle.db"))
    cancel = cap("demo-cancel", "Cancel", references=REF, sent="2026-11-12T01:02:00Z")
    ingest(config, wrap(cancel), "replay")
    ingest(config, wrap(cap("demo-update", "Update", references=REF, sent="2026-11-12T01:01:00Z")))
    ingest(config, wrap(cap()))
    with TestClient(create_app(config)) as api:
        data = api.get("/api/v1/alerts").json()
        original = next(m for m in data["items"] if m["protocol_identifier"] == "demo-alert")
        mid = original["id"]
        assert original["alert"]["lifecycle"] == "superseded"  # Replay cancel ignored.
        assert original["alert"]["relationships"][0]["type"] == "Update"
        update = next(m for m in data["items"] if m["protocol_identifier"] == "demo-update")
        detail = api.get(f"/api/v1/messages/{update['id']}?source=live").json()
        assert detail["relationships"][0]["resolved_message_ids"] == [mid]
        replay_cancel = api.get("/api/v1/alerts?source=replay").json()["items"][0]
        assert api.get(f"/api/v1/messages/{replay_cancel['id']}?source=live").status_code == 404
        ingest(config, wrap(cancel))
        after = api.get(f"/api/v1/messages/{mid}?source=live").json()
        assert after["alert"]["lifecycle"] == "cancelled"
        assert after["alert"]["relationships"][-1]["type"] == "Cancel"
        assert api.get(f"/api/v1/messages/{mid}/raw").content == cap()
        assert api.get("/api/v1/alerts").json()["total"] == 3  # No deletion on cancellation.


def test_foreign_sender_test_cancel_and_ambiguous_latest_references(tmp_path):
    config = Config(database=str(tmp_path / "references.db"))
    ingest(config, wrap(cap()))
    cancel = cap("demo-cancel", "Cancel", references=REF, sent="2026-11-12T01:02:00Z")
    ingest(config, wrap(cancel.replace(b"<status>Actual", b"<status>Test")))
    ingest(
        config,
        wrap(cancel.replace(b"<sender>synthetic.warnbridge.example", b"<sender>another.example")),
    )
    store = Store(config.database)
    original = next(m for m in store.alerts()["items"] if m["protocol_identifier"] == "demo-alert")
    assert original["alert"]["relationships"] == []
    store.close()
    ingest(config, wrap(cancel))
    ingest(config, wrap(cap("demo-update", "Update", references=REF, sent="2026-11-12T01:02:00Z")))
    store = Store(config.database)
    assert store.message(original["id"], source="live")["alert"]["lifecycle"] == "reference_review"
    store.close()


def test_conflicting_referencing_identity_requires_review(tmp_path):
    config = Config(database=str(tmp_path / "conflict.db"))
    ingest(config, wrap(cap()))
    update = cap("demo-update", "Update", references=REF, sent="2026-11-12T01:02:00Z")
    ingest(config, wrap(update))
    ingest(config, wrap(update.replace(b"Flood warning example", b"Conflicting example")))
    store = Store(config.database)
    original = next(m for m in store.alerts()["items"] if m["protocol_identifier"] == "demo-alert")
    assert original["alert"]["lifecycle"] == "reference_review"
    assert any("Conflicting" in issue for issue in original["alert"]["issues"])
    store.close()


def test_live_heartbeat_health_never_uses_replay_or_untimed_import(tmp_path):
    config = Config(database=str(tmp_path / "heartbeat.db"), heartbeat_stale_after=45)
    old = (datetime.now(UTC) - timedelta(seconds=80)).isoformat()
    Ingestor(config, "live_udp", "synthetic live").process([Chunk(heartbeat(), 0, old, 0)])
    store = Store(config.database)
    sid = store.receivers()[0]["id"]
    store.finish_session(sid, {}, state="running")
    with TestClient(create_app(config)) as api:
        assert api.get("/api/v1/health").json()["connection"]["state"] == "stale"
        # An imported replay with a new arrival timestamp must not refresh the live indicator.
        Ingestor(config, "replay", "synthetic replay").process(
            [Chunk(heartbeat(), 0, datetime.now(UTC).isoformat(), 0)]
        )
        ingest(config, heartbeat(), "live_hdhomerun")  # Untimed input also cannot refresh it.
        health = api.get("/api/v1/health").json()["connection"]
        assert health["last_heartbeat"]["received_at"] == old
        assert health["state"] != "recent"
        now = datetime.now(UTC).isoformat()
        Ingestor(config, "live_udp", "synthetic new live").process([Chunk(heartbeat(), 0, now, 0)])
        sid = store.receivers()[0]["id"]
        store.finish_session(sid, {}, state="running")
        fresh = api.get("/api/v1/health").json()["connection"]
        assert fresh["state"] == "recent" and fresh["age_seconds"] < 5
        assert fresh["last_heartbeat"]["received_at"] == now
        store.finish_session(sid, {})
        assert api.get("/api/v1/health").json()["connection"]["state"] == "stopped"
    store.close()


def test_synthetic_alert_demo_replays_all_seven_messages(tmp_path):
    from pathlib import Path

    config = Config(database=str(tmp_path / "demo.db"))
    counts = ingest(config, Path("tests/fixtures/alert-demo.ts").read_bytes(), "replay")
    assert counts["complete_messages"] == 7 and counts["crc_pass"] == 7
    assert counts["cap_messages"] == 6 and counts["cmac_messages"] == 1
    assert counts["continuity_gaps"] == 0
    with TestClient(create_app(config)) as api:
        assert api.get("/api/v1/alerts").json()["total"] == 0
        data = api.get("/api/v1/alerts?source=replay").json()
        assert data["total"] == 7
        assert any(m["alert"]["lifecycle"] == "cancelled" for m in data["items"])
        assert api.get("/api/v1/health").json()["connection"]["state"] == "waiting"


def test_restarted_listener_waits_for_its_own_heartbeat(tmp_path):
    config = Config(database=str(tmp_path / "restart.db"))
    Ingestor(config, "live_udp", "synthetic previous").process(
        [Chunk(heartbeat(), 0, datetime.now(UTC).isoformat(), 0)]
    )
    store = Store(config.database)
    assert store.health()["connection"]["state"] == "stopped"
    sid = store.start_session("live_udp", "synthetic restart")
    assert store.health()["connection"]["state"] == "waiting"
    store.finish_session(sid, {})
    assert store.health()["connection"]["state"] == "stopped"
    store.close()
