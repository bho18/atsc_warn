from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from tests.fixtures.alert_examples import CMAC, cap
from tests.fixtures.synthetic import wrap
from tests.integration.test_alert_inbox import ingest
from tests.integration.test_alert_variants import companion
from warnbridge.api.app import create_app
from warnbridge.config import Config


def test_active_filter_after_lifecycle_grouping_before_pagination_and_source_scope(tmp_path):
    config = Config(database=str(tmp_path / "active.db"))
    now = datetime.now(UTC)
    sent = (now - timedelta(hours=1)).isoformat()
    expiry = (now + timedelta(hours=1)).isoformat()

    def alert(identifier, **kwargs):
        return cap(identifier, **{"sent": sent, "expires": expiry, **kwargs})

    def ref(identifier):
        return f"synthetic.warnbridge.example,{identifier},{sent}"

    for identifier in ("active-one", "active-two", "cancelled", "superseded"):
        ingest(config, wrap(alert(identifier)))
    ingest(config, wrap(companion("active-one", sent=sent)))
    ingest(config, wrap(alert("cancel", kind="Cancel", references=ref("cancelled"))))
    ingest(config, wrap(alert("update", kind="Update", references=ref("superseded"))))
    # Replay cancellation must not hide a live active message.
    ingest(
        config, wrap(alert("replay-cancel", kind="Cancel", references=ref("active-two"))), "replay"
    )
    for body in (
        alert("expired", expires=(now - timedelta(minutes=1)).isoformat()),
        alert("future", sent=(now + timedelta(minutes=1)).isoformat()),
        alert("test", status="Test"),
        alert("unknown", expires=""),
        b"<future>unknown message</future>",
    ):
        ingest(config, wrap(body))
    # Standalone CMAC with explicit valid timing belongs in the active filter too.
    cmac = CMAC.replace(b"2026-11-12T01:00:00Z", sent.encode()).replace(
        b"</CMAC_Alert_Attributes>",
        f"<CMAC_expires_date_time>{expiry}</CMAC_expires_date_time></CMAC_Alert_Attributes>".encode(),
    )
    ingest(config, wrap(cmac))
    with TestClient(create_app(config)) as api:
        pages = [
            api.get(f"/api/v1/alerts?lifecycle=active&limit=1&offset={i}").json() for i in range(5)
        ]
        assert all(p["total"] == 4 for p in pages)
        items = [item for p in pages for item in p["items"]]
        assert len(items) == len({item["id"] for item in items}) == 4
        assert all(item["alert"]["lifecycle"] == "active" for item in items)
        grouped = next(i for i in items if i["protocol_identifier"] == "active-one")
        assert grouped["protocols"] == ["CAP", "CMAC"]
        assert api.get("/api/v1/alerts?lifecycle=active&status=Test").json()["total"] == 0
        assert api.get("/api/v1/alerts?lifecycle=active&source=replay").json()["total"] == 0
        for state in ("expired", "cancelled", "superseded", "scheduled", "non_actual"):
            result = api.get(f"/api/v1/alerts?lifecycle={state}").json()
            assert result["total"] == 1
            assert result["items"][0]["alert"]["lifecycle"] == state
        assert api.get("/api/v1/alerts?lifecycle=bogus").status_code == 422
        assert api.get("/api/v1/alerts?lifecycle=active&cancellations=true").json()["total"] == 0


def test_active_filter_expires_on_refresh(tmp_path, monkeypatch):
    config = Config(database=str(tmp_path / "clock.db"))
    now = datetime.now(UTC)
    ingest(
        config,
        wrap(
            cap(
                sent=(now - timedelta(hours=1)).isoformat(),
                expires=(now + timedelta(minutes=1)).isoformat(),
            )
        ),
    )
    with TestClient(create_app(config)) as api:
        assert api.get("/api/v1/alerts?lifecycle=active").json()["total"] == 1

        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return now + timedelta(minutes=2)

        monkeypatch.setattr("warnbridge.domain.alerts.datetime", Later)
        assert api.get("/api/v1/alerts?lifecycle=active").json()["total"] == 0
