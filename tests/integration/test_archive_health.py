from datetime import UTC, datetime, timedelta
from io import BytesIO

from fastapi.testclient import TestClient

from tests.fixtures.golden import cmac, heartbeat
from tests.fixtures.synthetic import wrap
from tests.unit.test_receiver_health import RF
from warnbridge.api.app import create_app
from warnbridge.config import Config
from warnbridge.inputs.streams import file_chunks
from warnbridge.pipeline import Ingestor
from warnbridge.storage.store import Store, utc_now


def ingest(config, raw, source):
    return Ingestor(config, source, "synthetic archive test").process(file_chunks(BytesIO(raw)))


def test_delivery_history_and_content_counts_do_not_mix_filtered_sources(tmp_path):
    config = Config(database=str(tmp_path / "archive.db"))
    ingest(config, heartbeat(), "replay")
    ingest(config, b"".join(heartbeat(i % 16) for i in range(35)), "live_hdhomerun")
    ingest(config, cmac(), "live_hdhomerun")
    # Byte-identical Link Test, new transport ID, two deliveries total.
    from tests.fixtures.golden import BODY

    ingest(config, wrap(BODY, ident=0x6AF3C250), "live_hdhomerun")
    with TestClient(create_app(config)) as api:
        content = api.get("/api/v1/messages?source=live_hdhomerun").json()
        hb = next(m for m in content["items"] if m["classification"] == "heartbeat")
        assert hb["delivery_count"] == 35 and hb["sources"] == ["live_hdhomerun"]
        all_hb = api.get("/api/v1/messages/" + hb["id"]).json()
        assert all_hb["delivery_count"] == 36 and all_hb["sources"] == ["live_hdhomerun", "replay"]
        assert all_hb["first_received_at"] is None  # These synthetic imports have no arrival clock.
        assert content["items"][0]["classification"] == "cmac_link_test"
        assert content["items"][0]["delivery_count"] == 2
        assert content["items"][0]["declared_sent"] == "2026-11-11T01:18:00Z"
        assert content["items"][0]["protocol_identifier"] == "b440b6c8"
        path = f"/api/v1/deliveries?message_id={hb['id']}&source=live_hdhomerun&limit=10"
        pages = [api.get(path + f"&offset={offset}").json() for offset in (0, 10, 20, 30)]
        assert [len(p["items"]) for p in pages] == [10, 10, 10, 5]
        ids = [d["id"] for page in pages for d in page["items"]]
        assert len(set(ids)) == 35 and ids == sorted(ids, reverse=True)
        assert all(d["source"] == "live_hdhomerun" for p in pages for d in p["items"])
        assert all(d["repeated_content"] for p in pages for d in p["items"])
        assert api.get("/api/v1/deliveries?source=replay").json()["total"] == 1
        assert api.get("/api/v1/deliveries?classification=cmac_link_test").json()["total"] == 2
        assert api.get("/api/v1/deliveries?limit=101").status_code == 422
        assert api.get("/api/v1/deliveries?offset=-1").status_code == 422
        assert api.get(
            f"/api/v1/messages/{hb['id']}/raw?part=raw_ts&observation={ids[-1]}"
        ).content == heartbeat(0)
        link_id = content["items"][0]["id"]
        assert (
            api.get(f"/api/v1/messages/{link_id}/raw?part=raw_ts&observation={ids[-1]}").status_code
            == 404
        )
        assert api.get("/api/v1/metrics").json()["deliveries"] == 38


def test_rf_health_is_fresh_then_stale_error_and_stopped(tmp_path, monkeypatch):
    config = Config(database=str(tmp_path / "radio.db"))
    store = Store(config.database)
    sid = store.start_session("live_hdhomerun", "192.0.2.10:tuner0")
    store.record_receiver_status(sid, "192.0.2.10", 0, utc_now(), RF)

    def no_subprocess(*a, **kw):
        raise AssertionError("API must only read stored RF snapshots")

    monkeypatch.setattr("subprocess.run", no_subprocess)
    with TestClient(create_app(config)) as api:
        fresh = api.get("/api/v1/health").json()
        assert fresh["rf_tuner"] == "locked"
        assert fresh["receiver"]["fields"]["snq"] == "98"
        assert fresh["receiver"]["fields"]["ch"] == "auto:7"
        assert fresh["last_observed"]["heartbeat"] is None  # RF lock never implies heartbeat.
        old = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
        store.record_receiver_status(sid, "192.0.2.10", 0, old, RF)
        assert api.get("/api/v1/health").json()["rf_tuner"] == "stale"
        store.record_receiver_status(sid, "192.0.2.10", 0, utc_now(), None, "control unavailable")
        error = api.get("/api/v1/health").json()
        assert error["rf_tuner"] == "unavailable" and error["receiver"]["fields"] == {}
        store.record_receiver_status(
            sid, "192.0.2.10", 0, utc_now(), RF.replace("lock=8vsb", "lock=none")
        )
        assert api.get("/api/v1/health").json()["rf_tuner"] == "no_lock"
        store.finish_session(sid, {})
        assert api.get("/api/v1/health").json()["rf_tuner"] == "stopped"
    store.close()


def test_v1_migration_preserves_original_evidence(tmp_path):
    config = Config(database=str(tmp_path / "v1.db"))
    ingest(config, heartbeat(), "replay")
    store = Store(config.database)
    original = store.db.execute("SELECT raw_ts,body,header FROM observations").fetchone()
    with store.db:
        store.db.execute("DROP TABLE receiver_status")
        store.db.execute("DROP INDEX observations_state_id")
        store.db.execute("PRAGMA user_version=1")
    store.close()
    with TestClient(create_app(config)) as api:
        assert api.get("/api/v1/messages").json()["total"] == 1
        assert api.get("/api/v1/deliveries").json()["total"] == 1
        assert api.get("/api/v1/health").json()["rf_tuner"] == "not_checked"
    store = Store(config.database)
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == 2
    assert tuple(
        store.db.execute("SELECT raw_ts,body,header FROM observations").fetchone()
    ) == tuple(original)
    store.close()


def test_paginated_deliveries_extend_beyond_legacy_detail_cap(tmp_path):
    config = Config(database=str(tmp_path / "long-history.db"))
    ingest(config, b"".join(heartbeat(i % 16) for i in range(125)), "live_hdhomerun")
    with TestClient(create_app(config)) as api:
        listing = api.get("/api/v1/messages").json()
        assert listing["total"] == 1 and listing["items"][0]["delivery_count"] == 125
        mid = listing["items"][0]["id"]
        detail = api.get("/api/v1/messages/" + mid).json()
        assert len(detail["observations"]) == 100 and detail["observations_truncated"]
        tail = api.get(f"/api/v1/deliveries?message_id={mid}&offset=100&limit=50").json()
        assert tail["total"] == 125 and len(tail["items"]) == 25
        first = tail["items"][-1]
        assert first["id"] == 1 and not first["repeated_content"]
        assert api.get(
            f"/api/v1/messages/{mid}/raw?part=raw_ts&observation=1"
        ).content == heartbeat(0)
