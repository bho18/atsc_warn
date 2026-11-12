import json
import signal
import socket
import subprocess
import time
from pathlib import Path

from tests.fixtures.golden import heartbeat
from warnbridge.storage.store import Store

CLI = str(Path(".venv/bin/warnbridge").resolve())


def test_stdin_summary_and_bad_input_exit(tmp_path):
    result = subprocess.run(
        [CLI, "decode", "-", "--out", str(tmp_path / "ok")], input=heartbeat(), capture_output=True
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["heartbeats"] == 1
    result = subprocess.run(
        [CLI, "decode", "-", "--out", str(tmp_path / "bad")], input=b"bad", capture_output=True
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["rejected_packets"] == 1


def test_live_udp_sigterm_cleanup(tmp_path):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'database = "{tmp_path}/archive.db"\nudp_port = {port}\n'
        f'capture_dir = "{tmp_path}/captures"\n'
    )
    proc = subprocess.Popen(
        [CLI, "udp", "--config", str(cfg)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / "archive.db").exists() and time.monotonic() < deadline:
            assert proc.poll() is None
            time.sleep(0.02)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(heartbeat(), ("127.0.0.1", port))
        while time.monotonic() < deadline:
            store = Store(str(tmp_path / "archive.db"))
            count = store.metrics()["messages"]
            store.close()
            if count:
                break
            time.sleep(0.02)
        assert count == 1
        proc.send_signal(signal.SIGTERM)
        stdout, stderr = proc.communicate(timeout=5)
        assert proc.returncode == 0, stderr
        records = [json.loads(line) for line in stdout.splitlines()]
        assert records[0]["type"] == "message"
        assert records[0]["classification"] == "heartbeat"
        assert records[-1]["counts"]["heartbeats"] == 1
        store = Store(str(tmp_path / "archive.db"))
        assert store.receivers()[0]["state"] == "finished"
        assert store.health()["ts_reception"]["last_live_received_at"]
        store.close()
        assert not (tmp_path / "captures").exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_doctor_default_no_network_or_database_creation(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'database = "{tmp_path}/missing.db"\n')
    result = subprocess.run([CLI, "doctor", "--config", str(cfg)], capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(result.stdout)["receiver"] == "not_contacted"
    assert not (tmp_path / "missing.db").exists()


def test_live_listen_connects_outputs_immediately_and_filters_only_warn(
    tmp_path, monkeypatch, capsys
):
    from contextlib import contextmanager
    from dataclasses import replace

    from tests.unit.test_inputs import Device as MockTuner
    from warnbridge import cli
    from warnbridge.inputs.hdhomerun import Tuner

    device = MockTuner()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    cfg = tmp_path / "live.toml"
    cfg.write_text(f'database="{tmp_path}/live.db"\ncapture_dir="{tmp_path}/raw"\n')

    def runner(args):
        result = device(args)
        if args[-2] == "/tuner0/target" and args[-1].startswith("udp://"):
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as transmitter:
                # A non-WARN PID is ignored and never retained in SQLite.
                non_warn = bytearray(heartbeat())
                non_warn[2] = 0x12
                transmitter.sendto(bytes(non_warn) + heartbeat(), ("127.0.0.1", port))
        return result

    @contextmanager
    def connect(config):
        active = replace(config, receiver_host="127.0.0.1", tuner=0, return_ip="127.0.0.1")
        with Tuner(active, runner) as tuner:
            yield tuner

    monkeypatch.setattr(cli, "open_receiver", connect)
    args = cli.parser().parse_args(
        [
            "listen",
            "--config",
            str(cfg),
            "--channel",
            "7",
            "--udp-port",
            str(port),
            "--duration",
            ".01",
        ]
    )
    assert cli.run(args) == 0
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["type"] for r in records] == ["receiver", "message", "summary"]
    assert records[0]["channel"] == "auto:7" and not records[0]["raw_recording"]
    assert records[1]["classification"] == "heartbeat" and records[1]["received_at"]
    assert records[1]["body_base64"] == "SGVhcnRiZWF0IE1lc3NhZ2U="
    assert not (tmp_path / "raw").exists()
    store = Store(str(tmp_path / "live.db"))
    assert store.db.execute("SELECT length(raw_ts) FROM observations").fetchone()[0] == 188
    assert store.receivers()[0]["identity"] == "127.0.0.1:tuner0"
    store.close()
    assert device.lock is None and device.target == "none"


def test_live_journal_requires_explicit_opt_in(tmp_path, monkeypatch, capsys):
    from warnbridge import cli
    from warnbridge.inputs.streams import Chunk

    cfg = tmp_path / "raw.toml"
    cfg.write_text(f'database="{tmp_path}/raw.db"\ncapture_dir="{tmp_path}/raw"\n')
    monkeypatch.setattr(cli, "udp_chunks", lambda *a, **kw: iter([Chunk(heartbeat(), 0)]))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert (
        cli.run(
            cli.parser().parse_args(
                ["udp", "--config", str(cfg), "--udp-port", str(port), "--record-raw"]
            )
        )
        == 0
    )
    assert list((tmp_path / "raw").glob("arrival-*.jsonl"))


def test_live_message_emitted_before_input_finishes(tmp_path):
    from warnbridge.config import Config
    from warnbridge.inputs.streams import Chunk
    from warnbridge.pipeline import Ingestor

    records = []

    def chunks():
        yield Chunk(heartbeat(), 0)
        assert records and records[0]["classification"] == "heartbeat"

    Ingestor(
        Config(database=str(tmp_path / "instant.db")), "live_udp", "mock", emit=records.append
    ).process(chunks())


def test_no_udp_warning_is_actionable_and_persisted(tmp_path, monkeypatch, capsys):
    from warnbridge import cli
    from warnbridge.inputs.streams import Chunk

    cfg = tmp_path / "silent.toml"
    cfg.write_text(f'database="{tmp_path}/silent.db"\nno_data_warning=0.001\n')

    def silent(*args, **kwargs):
        time.sleep(0.003)
        yield Chunk(b"", 0)

    monkeypatch.setattr(cli, "udp_chunks", silent)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert (
        cli.run(cli.parser().parse_args(["udp", "--config", str(cfg), "--udp-port", str(port)]))
        == 0
    )
    assert "WSL NAT" in capsys.readouterr().err
    store = Store(str(tmp_path / "silent.db"))
    assert store.db.execute("SELECT kind FROM health_events").fetchone()[0] == "no_udp_data"
    store.close()


def test_cli_overrides_config_tuner_and_recording(tmp_path):
    from warnbridge import cli

    cfg = tmp_path / "override.toml"
    cfg.write_text("tuner=1\nrecord_raw=true\n")
    args = cli.parser().parse_args(
        ["listen", "--config", str(cfg), "--tuner", "auto", "--channel", "7", "--no-record-raw"]
    )
    settings = cli.configure(args)
    assert settings.tuner is None and settings.channel == "auto:7" and not settings.record_raw
