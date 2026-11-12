"""Inbox presentation groups explicit protocol counterparts, never similar wording."""

from fastapi.testclient import TestClient

from tests.fixtures.alert_examples import CMAC, cap
from tests.fixtures.synthetic import wrap
from tests.integration.test_alert_inbox import REF, ingest
from warnbridge.api.app import create_app
from warnbridge.config import Config
from warnbridge.storage.store import Store


def companion(
    identifier="demo-alert",
    kind="Alert",
    status="Actual",
    sent="2026-11-11T20:00:00-05:00",
    text="Wireless companion text",
):
    return (
        CMAC.replace(b"<CMAC_status>Actual", f"<CMAC_status>{status}".encode())
        .replace(b"<CMAC_message_type>Alert", f"<CMAC_message_type>{kind}".encode())
        .replace(
            b"</CMAC_Alert_Attributes>",
            f"""
<CMAC_sender>synthetic.warnbridge.example</CMAC_sender>
<CMAC_cap_identifier>{identifier}</CMAC_cap_identifier>
<CMAC_cap_sent_date_time>{sent}</CMAC_cap_sent_date_time>
<CMAC_long_text_alert_message>{text}</CMAC_long_text_alert_message>
</CMAC_Alert_Attributes>""".encode(),
        )
    )


def test_companions_arrive_in_either_order_group_before_pagination_and_keep_evidence(tmp_path):
    config = Config(database=str(tmp_path / "variants.db"))
    ingest(config, wrap(companion()))
    with TestClient(create_app(config)) as api:
        before = api.get("/api/v1/alerts").json()
        assert before["total"] == 1 and before["items"][0]["protocol"] == "CMAC"
        cmac_id = before["items"][0]["id"]
        ingest(config, wrap(cap("other")))
        ingest(config, wrap(cap()))
        # The newest repeat is CMAC; the representative is still the CAP record.
        ingest(config, wrap(companion()))
        first = api.get("/api/v1/alerts?limit=1").json()
        assert first["total"] == 2
        item = first["items"][0]
        assert item["protocol"] == "CAP" and item["protocol_identifier"] == "demo-alert"
        assert item["protocols"] == ["CAP", "CMAC"] and item["group_delivery_count"] == 3
        assert {v["delivery_count"] for v in item["variants"]} == {1, 2}
        assert (
            next(v for v in item["variants"] if v["protocol"] == "CMAC")["text"]
            == "Wireless companion text"
        )
        assert (
            api.get("/api/v1/alerts?limit=1&offset=1").json()["items"][0]["protocol_identifier"]
            == "other"
        )
        assert api.get("/api/v1/alerts?limit=1&offset=2").json()["items"] == []
        for mid, body in ((cmac_id, companion()), (item["id"], cap())):
            detail = api.get(f"/api/v1/messages/{mid}?source=live").json()
            assert len(detail["variants"]) == 2
            assert api.get(f"/api/v1/messages/{mid}/raw").content == body
        assert api.get("/api/v1/messages").json()["total"] == 3
        assert api.get("/api/v1/deliveries").json()["total"] == 4


def test_cmac_and_cap_cancels_use_history_attach_text_and_do_not_hide_new_alert(tmp_path):
    config = Config(database=str(tmp_path / "cancel-variants.db"))
    cancel = cap("cancel", "Cancel", references=REF, sent="2026-11-12T01:02:00Z")
    cmac_cancel = companion(
        "cancel", "Cancel", sent="2026-11-12T01:02:00Z", text="Extra wireless cancel instructions"
    )
    ingest(config, wrap(cap()))
    ingest(config, wrap(companion()))
    ingest(config, wrap(cmac_cancel))
    with TestClient(create_app(config)) as api:
        # A CMAC Cancel without its CAP counterpart is still visible in history.
        assert api.get("/api/v1/alerts").json()["total"] == 1
        history = api.get("/api/v1/alerts?cancellations=true").json()
        assert history["total"] == 1 and history["items"][0]["alert"]["lifecycle"] == "cancellation"
        ingest(config, wrap(cancel))
        inbox = api.get("/api/v1/alerts").json()
        assert inbox["total"] == 1 and inbox["items"][0]["alert"]["lifecycle"] == "cancelled"
        history = api.get("/api/v1/alerts?cancellations=true").json()
        assert history["total"] == 1 and history["items"][0]["protocols"] == ["CAP", "CMAC"]
        mid = inbox["items"][0]["id"]
        detail = api.get(f"/api/v1/messages/{mid}?source=live").json()
        variants = detail["alert"]["cancellations"][0]["variants"]
        assert any(v["text"] == "Extra wireless cancel instructions" for v in variants)
        ingest(
            config,
            wrap(
                cap("clear", sent="2026-11-12T01:03:00Z").replace(
                    b"Flood warning example", b"ALL CLEAR"
                )
            ),
        )
        ingest(config, wrap(companion("clear", sent="2026-11-12T01:03:00Z", text="ALL CLEAR")))
        assert api.get("/api/v1/alerts").json()["total"] == 2
        assert api.get("/api/v1/alerts?cancellations=true").json()["total"] == 1
        assert api.get("/api/v1/messages").json()["total"] == 6


def test_no_fuzzy_merge_missing_conflicting_or_different_source_status_type_identity(tmp_path):
    config = Config(database=str(tmp_path / "separate.db"))
    ingest(config, wrap(cap()))
    # Matching text is not evidence of identity.
    ingest(config, wrap(companion("different")))
    ingest(config, wrap(companion(status="Test")))
    ingest(config, wrap(companion(sent="2026-11-12T01:00:01Z")))
    ingest(config, wrap(companion(kind="Update")))
    ingest(config, wrap(CMAC))
    with TestClient(create_app(config)) as api:
        assert api.get("/api/v1/alerts").json()["total"] == 6
        assert api.get("/api/v1/alerts?status=Test").json()["total"] == 1
        ingest(config, wrap(companion()), "replay")
        assert api.get("/api/v1/alerts?source=all").json()["total"] == 7
        assert api.get("/api/v1/alerts?source=replay").json()["total"] == 1
        # Even in one source, multiple CAP bodies claiming the identity remain separate.
        ingest(config, wrap(cap().replace(b"Flood warning example", b"Conflicting CAP")))
        ingest(config, wrap(companion()))
        assert api.get("/api/v1/alerts").json()["total"] == 8


def test_live_sources_can_pair_but_mixed_import_provenance_requires_source_selection(tmp_path):
    config = Config(database=str(tmp_path / "sources.db"))
    ingest(config, wrap(cap()), "live_udp")
    ingest(config, wrap(companion()), "live_hdhomerun")
    store = Store(config.database)
    item = store.alerts()["items"][0]
    assert store.alerts()["total"] == 1
    assert item["group_sources"] == ["live_hdhomerun", "live_udp"]
    store.close()
    ingest(config, wrap(cap()), "replay")
    store = Store(config.database)
    assert store.alerts(source=None)["total"] == 2
    assert store.alerts(source="live")["total"] == 1
    store.close()
