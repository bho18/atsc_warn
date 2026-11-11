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
        assert json.loads(stdout)["heartbeats"] == 1
        store = Store(str(tmp_path / "archive.db"))
        assert store.receivers()[0]["state"] == "finished"
        assert store.health()["ts_reception"]["last_live_received_at"]
        store.close()
        assert list((tmp_path / "captures").glob("*.jsonl"))
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
