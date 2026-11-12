import pytest
from fastapi.testclient import TestClient

from warnbridge.api.app import create_app
from warnbridge.config import Config


@pytest.mark.parametrize("peer", ["192.168.1.42", "::ffff:192.168.1.42", "127.0.0.1"])
def test_configured_internal_peers_can_read_the_web_and_api(tmp_path, peer):
    config = Config(
        database=str(tmp_path / "lan.db"), web_allowed_networks=["192.168.1.0/24", "127.0.0.1/32"]
    )
    with TestClient(create_app(config), client=(peer, 12345)) as api:
        assert api.get("/").status_code == 200
        assert api.get("/api/v1/health").status_code == 200
        assert api.get("/assets/map.js").status_code == 200
        # Untrusted headers cannot change an allowed socket peer into a different identity.
        assert api.get("/api/v1/health", headers={"X-Forwarded-For": "8.8.8.8"}).status_code == 200


@pytest.mark.parametrize("peer", ["203.0.113.10", "192.168.2.10", "unrecognized-client"])
def test_other_peers_cannot_read_any_route_or_spoof_forwarding_headers(tmp_path, peer):
    config = Config(database=str(tmp_path / "lan.db"), web_allowed_networks=["192.168.1.0/24"])
    with TestClient(create_app(config), client=(peer, 12345)) as api:
        for path in [
            "/",
            "/api/v1/health",
            "/api/v1/alerts",
            "/assets/map.js",
            "/assets/maps/reference.geojson",
            "/api/v1/messages/x/raw",
            "/openapi.json",
        ]:
            response = api.get(
                path,
                headers={
                    "X-Forwarded-For": "192.168.1.42",
                    "X-Real-IP": "192.168.1.42",
                    "Forwarded": "for=192.168.1.42",
                },
            )
            assert response.status_code == 403, path
            assert response.headers["Cache-Control"] == "no-store"
            assert "script-src" in response.headers["content-security-policy"]


def test_explicit_empty_allowlist_denies_every_peer(tmp_path):
    config = Config(database=str(tmp_path / "none.db"), web_allowed_networks=[])
    with TestClient(create_app(config), client=("127.0.0.1", 12345)) as api:
        assert api.get("/").status_code == 403


def test_invalid_cidr_is_refused_at_startup():
    with pytest.raises(ValueError):
        Config(web_allowed_networks=["192.168.1.99/24"])


def test_cli_does_not_trust_proxy_headers(tmp_path, monkeypatch):
    from warnbridge import cli

    calls = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append(kwargs))
    config = tmp_path / "server.toml"
    config.write_text(f'database="{tmp_path}/app.db"\n')
    assert cli.run(cli.parser().parse_args(["serve", "--config", str(config)])) == 0
    assert calls[0]["proxy_headers"] is False
