import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from tests.fixtures.alert_examples import cap
from tests.fixtures.golden import cmac, heartbeat
from tests.fixtures.synthetic import wrap
from warnbridge.api.app import create_app
from warnbridge.config import Config
from warnbridge.formats.xml import parse_body
from warnbridge.inputs.streams import Chunk
from warnbridge.pipeline import Ingestor
from warnbridge.storage.retention import failure_preview, purge_failures, retain, storage_usage
from warnbridge.storage.store import Store
from warnbridge.transport.decoder import Decoder, Event


def record(store, sid, data, age=0, *, failure=False):
    event = (
        Event("rejected", "orphan_fragment", data, [0])
        if failure
        else list(Decoder().feed(data))[0]
    )
    mid = store.record(sid, event, None if failure else parse_body(event.body), 0)
    oid = store.db.execute("SELECT max(id) FROM observations").fetchone()[0]
    with store.db:
        store.db.execute(
            "UPDATE observations SET processed_at=? WHERE id=?",
            ((datetime.now(UTC) - timedelta(days=age)).isoformat(), oid),
        )
    return oid, mid


def test_retention_removes_only_old_diagnostics_and_preserves_alert_evidence(tmp_path):
    config = Config(database=str(tmp_path / "retention.db"))
    store = Store(config.database)
    sid = store.start_session("live_udp", "synthetic live")
    other = store.start_session("replay", "synthetic replay")
    old_hb, shared_mid = record(store, sid, heartbeat(), 8)
    new_hb, _ = record(store, other, heartbeat(), 1)
    old_link, link_mid = record(store, sid, cmac(), 8)
    old_failed, _ = record(store, sid, b"old failure", 31, failure=True)
    retained_failed, _ = record(store, sid, b"recent failure", 29, failure=True)
    protected = []
    for body in (
        cap(),
        cap("test", status="Test"),
        cap("system", status="System"),
        cap("cancel", kind="Cancel"),
        b"<unknown/>",
    ):
        oid, mid = record(store, sid, wrap(body), 100)
        protected.append(
            dict(store.db.execute("SELECT * FROM observations WHERE id=?", (oid,)).fetchone())
        )
    # Recovery audit must not prevent expiry of an old recovered Link Test.
    with store.db:
        store.db.execute(
            "INSERT INTO observation_recoveries VALUES(?,?,?,?,?,?,?)",
            (old_link, datetime.now(UTC).isoformat(), "body_size_limit", b"h", b"b", None, None),
        )
    result = retain(store.db, config)
    assert result["diagnostic_deliveries"] == 2 and result["failures"] == 1
    assert result["diagnostic_contents"] == 1
    ids = {row[0] for row in store.db.execute("SELECT id FROM observations")}
    assert not ids & {old_hb, old_link, old_failed}
    assert {new_hb, retained_failed} <= ids
    assert store.message(shared_mid)["delivery_count"] == 1
    assert store.message(link_mid) is None
    assert store.db.execute("SELECT count(*) FROM observation_recoveries").fetchone()[0] == 0
    for before in protected:
        after = dict(
            store.db.execute("SELECT * FROM observations WHERE id=?", (before["id"],)).fetchone()
        )
        assert before == after
    assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert not any(retain(store.db, config).values())
    store.close()


def test_auxiliary_diagnostics_expire_but_referenced_and_running_sessions_remain(tmp_path):
    config = Config(database=str(tmp_path / "sessions.db"))
    store = Store(config.database)
    old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    empty = store.start_session("replay", "old empty session")
    referenced = store.start_session("replay", "old alert session")
    running = store.start_session("live_udp", "running")
    record(store, referenced, wrap(cap()), 10)
    for sid in (empty, referenced):
        store.finish_session(sid, {})
        store.health_event(sid, "diagnostic", "old")
        store.record_receiver_status(sid, "192.0.2.1", 0, old, None)
    with store.db:
        store.db.execute(
            "UPDATE sessions SET started_at=?,ended_at=? WHERE state!='running'", (old, old)
        )
        store.db.execute("UPDATE health_events SET at=?", (old,))
        store.db.execute(
            "INSERT INTO web_observations VALUES(1,?,?,?,?,'not_comparable')",
            (old, "test", "hash", b"{}"),
        )
    retain(store.db, config)
    assert {r[0] for r in store.db.execute("SELECT id FROM sessions")} == {running, referenced}
    for table in ("health_events", "receiver_status", "web_observations"):
        assert store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    store.close()


def test_purge_preview_is_bounded_and_new_records_survive_and_ids_never_repeat(tmp_path):
    config = Config(database=str(tmp_path / "purge.db"))
    app = create_app(config)
    store = Store(config.database)
    sid = store.start_session("live_udp", "synthetic")
    old, _ = record(store, sid, b"old", 10, failure=True)
    recent, _ = record(store, sid, b"recent", 1, failure=True)
    alert, _ = record(store, sid, wrap(cap()), 10)
    headers = {"X-WarnBridge-Action": "purge-failures", "Origin": "http://testserver"}
    with TestClient(app) as api:
        preview = api.get("/api/v1/diagnostics/purge-preview?older_than_days=7").json()
        assert preview["count"] == 1
        # Even a subsequently backdated record cannot fall into an already-previewed purge.
        later, _ = record(store, sid, b"new", 10, failure=True)
        body = {"before": preview["before"], "through_id": preview["through_id"], "confirm": True}
        assert api.post("/api/v1/diagnostics/purge", json=body).status_code == 403
        assert (
            api.post(
                "/api/v1/diagnostics/purge",
                json=body,
                headers={**headers, "Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        assert (
            api.post(
                "/api/v1/diagnostics/purge", json=body, headers={**headers, "Origin": "null"}
            ).status_code
            == 403
        )
        assert (
            api.post(
                "/api/v1/diagnostics/purge", json={**body, "confirm": False}, headers=headers
            ).status_code
            == 422
        )
        assert (
            api.post(
                "/api/v1/diagnostics/purge",
                json={**body, "before": "2099-01-01T00:00:00Z"},
                headers=headers,
            ).status_code
            == 422
        )
        assert api.post("/api/v1/diagnostics/purge", json=body, headers=headers).json() == {
            "removed": 1
        }
        assert api.post("/api/v1/diagnostics/purge", json=body, headers=headers).json() == {
            "removed": 0
        }
        assert api.get(f"/api/v1/diagnostics/{old}/raw").status_code == 404
        assert {r[0] for r in store.db.execute("SELECT id FROM observations")} == {
            recent,
            alert,
            later,
        }
        assert api.get("/api/v1/diagnostics/purge-preview?older_than_days=-1").status_code == 422
    # Empty an isolated failed-only archive, then ensure a stale raw URL stays missing.
    store.close()
    separate = Store(tmp_path / "empty.db")
    sid = separate.start_session("replay", "empty")
    first, _ = record(separate, sid, b"first", failure=True)
    preview = failure_preview(separate.db, 0)
    assert purge_failures(separate.db, preview["before"], preview["through_id"]) == 1
    next_id, _ = record(separate, sid, b"next", failure=True)
    assert next_id > first
    separate.close()


def test_expiry_runs_before_quota_and_reuses_deleted_pages(tmp_path):
    config = Config(database=str(tmp_path / "quota.db"), max_database_bytes=1048576)
    store = Store(config.database)
    sid = store.start_session("replay", "large expired failures")
    record(store, sid, b"x" * 1500000, 31, failure=True)
    assert storage_usage(config.database, store.db)["used_bytes"] > config.max_database_bytes
    store.close()
    # Startup retention must allow ingestion even though the file remains large.
    counts = Ingestor(config, "replay", "after expiry").process([Chunk(heartbeat(), 0)])
    assert counts["heartbeats"] == 1
    with TestClient(create_app(config)) as api:
        storage = api.get("/api/v1/health").json()["storage"]
        assert storage["state"] == "ok" and storage["reusable_bytes"] > 1000000
        assert storage["bytes"] > config.max_database_bytes > storage["used_bytes"]


def test_schema_three_upgrade_preserves_bytes_and_seeds_sequence(tmp_path):
    path = tmp_path / "old.db"
    store = Store(path)
    sid = store.start_session("replay", "schema3")
    oid, _ = record(store, sid, heartbeat())
    before = dict(store.db.execute("SELECT * FROM observations").fetchone())
    with store.db:
        store.db.execute("DROP TABLE observation_sequence")
        store.db.execute("DROP TABLE maintenance_status")
        store.db.execute("DROP INDEX observations_processed")
        store.db.execute("PRAGMA user_version=3")
    store.close()
    store = Store(path)
    assert dict(store.db.execute("SELECT * FROM observations").fetchone()) == before
    assert record(store, sid, heartbeat())[0] == oid + 1
    # An old receiver may finish an insert while Compose replaces the services.
    with store.db:
        store.db.execute("UPDATE observations SET id=100 WHERE id=?", (oid + 1,))
    assert record(store, sid, heartbeat())[0] == 101
    store.close()


def test_idle_ingestion_ticks_also_run_expiry(tmp_path):
    config = Config(database=str(tmp_path / "idle.db"))
    ingestor = Ingestor(config, "replay", "idle ticks")
    record(ingestor.store, ingestor.sid, b"old failure", 31, failure=True)
    ingestor.last_retention -= 61
    ingestor.process([Chunk(b"", 0)])
    store = Store(config.database)
    assert store.metrics()["retained_rejections"] == 0
    store.close()


def test_web_service_expires_diagnostics_without_receiver(tmp_path, monkeypatch):
    import warnbridge.api.app as api_module

    config = Config(database=str(tmp_path / "web-only.db"))
    app = create_app(config)
    store = Store(config.database)
    sid = store.start_session("replay", "web-only maintenance")
    record(store, sid, heartbeat(), 8)
    store.finish_session(sid, {})
    monkeypatch.setattr(api_module, "MAINTENANCE_INTERVAL", 0.01)
    with TestClient(app) as api:
        deadline = time.monotonic() + 3
        while api.get("/api/v1/metrics").json()["deliveries"]:
            assert time.monotonic() < deadline, "web-only scheduled retention did not run"
            time.sleep(0.01)
    store.close()


@pytest.mark.parametrize("days", [0, -1, 3651, 1.5, True])
def test_invalid_retention_settings(days):
    with pytest.raises(ValueError, match="retention days"):
        Config(diagnostic_retention_days=days)
