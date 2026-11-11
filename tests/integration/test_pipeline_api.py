import json
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.fixtures.golden import BODY, XML, cmac, heartbeat
from tests.fixtures.synthetic import wrap
from warnbridge.api.app import create_app
from warnbridge.config import Config
from warnbridge.inputs.streams import file_chunks
from warnbridge.inputs.web import import_saved
from warnbridge.pipeline import Ingestor
from warnbridge.storage.store import Store


def ingest(config, data, source="replay"):
    return Ingestor(config, source, "synthetic test").process(file_chunks(BytesIO(data)))


def test_replay_storage_restart_api(tmp_path):
    config = Config(database=str(tmp_path / "archive.db"))
    counts = ingest(config, cmac() + heartbeat())
    assert counts["complete_messages"] == 2 and counts["crc_pass"] == 2
    ingest(config, cmac())
    ingest(config, wrap(BODY, ident=0x6AF3C250))
    with TestClient(create_app(config)) as api:
        listing = api.get("/api/v1/messages?source=replay").json()
        assert listing["total"] == 2
        link = next(m for m in listing["items"] if m["classification"] == "cmac_link_test")
        assert link["delivery_count"] == 3
        detail = api.get("/api/v1/messages/" + link["id"]).json()
        assert all(o["received_at"] is None for o in detail["observations"])
        assert len({o["transport_id"] for o in detail["observations"]}) == 2
        assert detail["validation"]["schema"] == "not_configured"
        assert api.get(f"/api/v1/messages/{link['id']}/raw").content == XML
        assert api.get(f"/api/v1/messages/{link['id']}/raw?part=body").content == BODY
        assert api.get(f"/api/v1/messages/{link['id']}/raw?part=raw_ts").content == cmac()
        assert (
            api.get(f"/api/v1/messages/{link['id']}/raw?part=../../etc/passwd").status_code == 422
        )
        assert api.get("/api/v1/messages/missing/raw").status_code == 404
        assert api.get("/api/v1/messages?limit=101").status_code == 422
        assert api.get("/api/v1/alerts").json()["items"] == []
        assert api.post("/api/v1/messages").status_code == 405
        health = api.get("/api/v1/health").json()
        assert health["last_observed"]["heartbeat"]["source"] == "replay"
        assert health["ts_reception"]["last_live_received_at"] is None
        assert "script-src" in api.get("/").headers["content-security-policy"]
        assert b"textContent" in api.get("/assets/app.js").content
    s = Store(config.database)
    assert s.db.execute("PRAGMA user_version").fetchone()[0] == 1
    assert s.raw(link["id"], "header").hex() == "2f0000ff6af3c24c00000001bf"
    s.close()


def test_conflict_references_expiration_and_out_of_order(tmp_path):
    config = Config(database=str(tmp_path / "archive.db"))
    original = Path("tests/fixtures/cap.xml").read_bytes()
    update = (
        original.replace(b"synthetic-001", b"synthetic-002")
        .replace(b"<cap:msgType>Alert", b"<cap:msgType>Update")
        .replace(
            b"<cap:info>",
            b"<cap:references>sender.example,synthetic-001,2020-11-30T10:00:00Z</cap:references><cap:info>",
            1,
        )
    )
    ingest(config, wrap(update))
    s = Store(config.database)
    mid = s.messages()["items"][0]["id"]
    assert s.message(mid)["relationships"][0]["resolved_message_ids"] == []
    s.close()
    ingest(config, wrap(original))
    ingest(config, wrap(original.replace(b"Synthetic demonstration", b"Different content")))
    s = Store(config.database)
    detail = s.message(mid)
    assert len(detail["relationships"][0]["resolved_message_ids"]) == 2
    assert detail["lifecycle"] == "expired"
    assert all(m["conflict"] for m in s.messages()["items"] if m["id"] != mid)
    s.close()


def test_bounded_rejections_not_alerts(tmp_path):
    config = Config(database=str(tmp_path / "archive.db"), max_rejected=2)
    for _ in range(5):
        bad = bytearray(heartbeat())
        bad[30] ^= 1
        ingest(config, bytes(bad))
    s = Store(config.database)
    assert s.metrics()["retained_rejections"] == 2
    assert s.messages()["total"] == 0
    assert sum(r["summary"]["crc_fail"] for r in s.receivers()) == 5
    s.close()


def test_worker_lock_and_recovery(tmp_path):
    config = Config(database=str(tmp_path / "archive.db"))
    first = Ingestor(config, "replay", "one")
    with pytest.raises(ValueError, match="another ingestion"):
        Ingestor(config, "replay", "two")
    first.process([])
    assert ingest(config, heartbeat())["heartbeats"] == 1


def test_input_failure_finishes_session(tmp_path):
    config = Config(database=str(tmp_path / "archive.db"))

    def chunks():
        yield from file_chunks(BytesIO(cmac()[:188]))
        raise OSError("synthetic source failure")

    with pytest.raises(OSError):
        Ingestor(config, "replay", "failed").process(chunks())
    s = Store(config.database)
    assert s.receivers()[0]["state"] == "failed"
    assert s.metrics()["retained_rejections"] == 1
    s.close()
    ingest(config, heartbeat())


def test_saved_web_separate(tmp_path):
    config = Config(database=str(tmp_path / "archive.db"))
    path = tmp_path / "web.json"
    path.write_text(json.dumps({"alerts": [{"id": "synthetic"}]}))
    result = import_saved(path, config.database)
    assert result["comparison"] == "not_comparable"
    s = Store(config.database)
    assert s.messages()["total"] == 0 and not s.receivers()
    s.close()


def test_concurrent_api_dependency_thread_handoffs(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    config = Config(database=str(tmp_path / "concurrent.db"))
    ingest(config, cmac() + heartbeat())
    with TestClient(create_app(config)) as api, ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: api.get("/api/v1/messages"), range(32)))
    assert all(r.status_code == 200 and r.json()["total"] == 2 for r in responses)


def test_early_stop_closes_owned_source_and_reports_cleanup_failure(tmp_path):
    from warnbridge.inputs.streams import Chunk

    cfg = Config(database=str(tmp_path / "cleanup.db"))
    closed = []

    def source():
        try:
            yield Chunk(b"x" * 188, 0)
            raise AssertionError("must stop at strict framing failure")
        finally:
            closed.append(True)
            raise RuntimeError("synthetic tuner cleanup failure")

    with pytest.raises(RuntimeError, match="cleanup"):
        Ingestor(cfg, "live_udp", "test").process(source())
    assert closed == [True]
    s = Store(cfg.database)
    assert s.receivers()[0]["state"] == "failed"
    assert s.db.execute("SELECT kind FROM health_events").fetchone()[0] == "source_cleanup_failed"
    s.close()


def test_persistent_duplicate_counts_in_one_import(tmp_path):
    cfg = Config(database=str(tmp_path / "duplicates.db"))
    counts = ingest(cfg, cmac() + wrap(BODY, cc=1) + wrap(BODY, ident=0x6AF3C250, cc=4))
    assert counts["continuity_gaps"] == 0
    assert counts["duplicate_xml"] == 2 and counts["unique_xml"] == 1
    s = Store(cfg.database)
    detail = s.message(s.messages()["items"][0]["id"])
    assert detail["delivery_count"] == 3
    assert detail["observations"][0]["inferred_transport_at"] == "2026-11-11T01:18:04+00:00"
    s.close()


def test_newer_database_rejected_and_writer_lock_released(tmp_path):
    cfg = Config(database=str(tmp_path / "future.db"))
    s = Store(cfg.database)
    s.db.execute("PRAGMA user_version=99")
    s.close()
    with pytest.raises(ValueError, match="newer"):
        Ingestor(cfg, "replay", "future")
    with pytest.raises(ValueError, match="newer"):
        Ingestor(cfg, "replay", "future again")
