from dataclasses import replace

from fastapi.testclient import TestClient

from tests.fixtures.alert_examples import cap
from tests.fixtures.synthetic import wrap
from warnbridge.api.app import create_app
from warnbridge.config import Config
from warnbridge.pipeline import Ingestor
from warnbridge.storage.store import Store
from warnbridge.transport.decoder import Decoder


def rejected(store, source, raw, reason="body_size_limit"):
    event = list(Decoder().feed(raw))[0]
    sid = store.start_session(source, "synthetic prior receiver")
    event = replace(
        event,
        kind="rejected",
        reason=reason,
        header=event.assembled[:13],
        body=b"",
        stored_crc=None,
        calculated_crc=None,
        received_at="2026-11-12T15:11:22+00:00",
        monotonic_ns=12345678,
    )
    store.record(sid, event, None, 42)
    oid = store.db.execute("SELECT max(id) FROM observations").fetchone()[0]
    store.finish_session(sid, {"rejected_messages": 1})
    return oid


def test_recovery_is_automatic_idempotent_and_preserves_original_evidence(tmp_path):
    config = Config(database=str(tmp_path / "archive.db"))
    store = Store(config.database)
    raw = wrap(cap(), entries=(1,), payload_type=1)
    oid = rejected(store, "live_hdhomerun", raw)
    replay_oid = rejected(store, "replay", raw)
    rejected(store, "live_udp", raw, "continuity_gap")
    before = dict(store.db.execute("SELECT * FROM observations WHERE id=?", (oid,)).fetchone())
    store.db.execute("DROP TABLE observation_recoveries")
    store.db.execute("DROP INDEX relationships_target")
    store.db.execute("PRAGMA user_version=2")
    store.db.commit()
    store.close()
    Ingestor(config, "live_udp", "restart").process([])
    Ingestor(config, "live_udp", "second restart").process([])
    store = Store(config.database)
    after = dict(store.db.execute("SELECT * FROM observations WHERE id=?", (oid,)).fetchone())
    for key in (
        "id",
        "session_id",
        "processed_at",
        "received_at",
        "monotonic_ns",
        "chunk_index",
        "transport_id",
        "inferred_transport_at",
        "assembled",
        "raw_ts",
        "offsets",
    ):
        assert after[key] == before[key]
    assert after["state"] == "message" and after["reason"] is None
    assert after["stored_crc"] == after["calculated_crc"]
    assert store.metrics()["recovered_observations"] == 2
    assert store.metrics()["retained_rejections"] == 1
    assert store.metrics()["deliveries"] == 2
    assert (
        store.db.execute(
            "SELECT summary FROM sessions WHERE id=?", (before["session_id"],)
        ).fetchone()[0]
        == '{"rejected_messages": 1}'
    )
    store.close()
    with TestClient(create_app(config)) as api:
        item = api.get("/api/v1/alerts").json()["items"][0]
        assert item["delivery_count"] == 1 and item["sources"] == ["live_hdhomerun"]
        assert api.get("/api/v1/alerts?source=replay").json()["total"] == 1
        detail = api.get(f"/api/v1/messages/{item['id']}").json()
        assert {o["id"] for o in detail["observations"]} == {oid, replay_oid}
        assert all(
            o["recovery"]["original_reason"] == "body_size_limit" for o in detail["observations"]
        )
        assert (
            api.get(f"/api/v1/messages/{item['id']}/raw?part=raw_ts&observation={oid}").content
            == raw
        )
        failure = api.get("/api/v1/diagnostics").json()["items"][0]
        assert api.get(f"/api/v1/diagnostics/{failure['id']}/raw").content == raw
        assert api.get(f"/api/v1/diagnostics/{oid}/raw").status_code == 404
        assert api.get("/api/v1/diagnostics/9999/raw").status_code == 404
        assert (
            api.get(f"/api/v1/diagnostics/{failure['id']}/raw?part=../etc/passwd").status_code
            == 422
        )
