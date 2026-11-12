import json
import sys
import tomllib

import pytest

from scripts import configure_docker as setup
from warnbridge.config import Config

INTERFACES = [
    {
        "ifname": "enp1s0",
        "addr_info": [{"family": "inet", "local": "192.168.1.50", "prefixlen": 24}],
    },
    {
        "ifname": "docker0",
        "addr_info": [{"family": "inet", "local": "172.17.0.1", "prefixlen": 16}],
    },
]


def test_detects_the_host_route_without_querying_a_tuner(monkeypatch):
    commands = []

    def read(*args):
        commands.append(args)
        return (
            INTERFACES
            if args == ("address", "show")
            else [{"dev": "enp1s0", "prefsrc": "192.168.1.50"}]
        )

    monkeypatch.setattr(setup, "read_ip", read)
    assert setup.detect_network("192.168.4.159") == ("192.168.1.50", "192.168.1.0/24")
    assert commands == [("address", "show"), ("route", "get", "192.168.4.159")]


def test_explicit_lan_address_must_be_on_host_and_not_a_docker_bridge(monkeypatch):
    monkeypatch.setattr(setup, "read_ip", lambda *args: INTERFACES)
    assert setup.detect_network("192.168.4.159", "192.168.1.50")[0] == "192.168.1.50"
    with pytest.raises(ValueError, match="configured host interface"):
        setup.detect_network("192.168.4.159", "192.168.1.99")
    with pytest.raises(ValueError, match="not a Docker"):
        setup.detect_network("192.168.4.159", "172.17.0.1")


@pytest.mark.parametrize("address", ["0.0.0.0", "127.0.0.1", "8.8.8.8", "::1"])
def test_cannot_generate_a_wildcard_public_or_loopback_web_bind(address):
    with pytest.raises(ValueError):
        setup.render_config(address, ["192.168.1.0/24"], "192.168.4.159", "7", 8080, 5000)


@pytest.mark.parametrize("network", ["0.0.0.0/0", "8.8.8.0/24", "::/0", "192.168.1.1/24"])
def test_cannot_allow_public_or_ambiguous_networks(network):
    with pytest.raises(ValueError):
        setup.render_config("192.168.1.50", [network], "192.168.4.159", "7", 8080, 5000)


def test_generated_config_limits_network_access_and_preserves_live_defaults():
    text = setup.render_config(
        "192.168.1.50", ["192.168.1.0/24", "192.168.4.0/24"], "192.168.4.159", "7", 8082, 5001
    )
    config = Config(**tomllib.loads(text))
    assert config.bind == config.return_ip == config.udp_bind == "192.168.1.50"
    assert config.channel == "auto:7" and config.tuner is None
    assert config.web_allowed_networks == [
        "192.168.1.50/32",
        "127.0.0.1/32",
        "192.168.1.0/24",
        "192.168.4.0/24",
    ]
    assert config.database == "/data/warnbridge.db"
    assert config.capture_dir == "/data/captures"
    assert config.port == 8082 and config.udp_port == 5001
    assert not config.record_raw and not config.full_multiplex


def test_existing_config_is_not_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text("existing installation settings")
    monkeypatch.setattr(setup, "detect_network", lambda *args: ("192.168.1.50", "192.168.1.0/24"))
    monkeypatch.setattr(sys, "argv", ["configure_docker.py", "--output", str(path)])
    with pytest.raises(SystemExit) as result:
        setup.main()
    assert result.value.code == 2
    assert path.read_text() == "existing installation settings"


def test_read_ip_only_invokes_local_iproute_json(monkeypatch):
    from types import SimpleNamespace

    commands = []

    def run(args, **kwargs):
        commands.append(args)
        return SimpleNamespace(stdout=json.dumps(INTERFACES))

    monkeypatch.setattr(setup.subprocess, "run", run)
    assert setup.read_ip("address", "show") == INTERFACES
    assert commands == [["ip", "-j", "-4", "address", "show"]]


def test_downloaded_install_prints_image_pull_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(setup, "detect_network", lambda *args: ("192.168.1.50", "192.168.1.0/24"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "configure_docker.py",
            "--output",
            str(tmp_path / "live.toml"),
            "--compose-file",
            "compose.yaml",
        ],
    )
    setup.main()
    output = capsys.readouterr().out
    assert "http://192.168.1.50:8080" in output
    assert "docker compose -f compose.yaml pull" in output
    assert "docker compose -f compose.yaml up -d" in output
    assert "--build" not in output
