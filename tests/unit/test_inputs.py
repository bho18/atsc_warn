import socket
from threading import Event

import pytest

from tests.fixtures.golden import heartbeat
from warnbridge.config import Config
from warnbridge.inputs.hdhomerun import Tuner, TunerError, run_command
from warnbridge.inputs.streams import Chunk, Journal, journal_chunks, udp_chunks


def config():
    # TEST-NET addresses; mocked control only.
    return Config(receiver_host="192.0.2.10", tuner=1, channel="auto:7", return_ip="192.0.2.20")


class Device:
    def __init__(self):
        self.lock = None
        self.channel = "none"
        self.target = "none"
        self.calls = []
        self.race = False
        self.takeover = False
        self.filter_failure = False

    def __call__(self, args):
        self.calls.append(args)
        keyed = len(args) > 5 and args[2] == "key"
        key = args[3] if keyed else None
        operation, name = args[4:6] if keyed else args[2:4]
        field = name.rsplit("/", 1)[-1]
        if operation == "get":
            return {
                "status": f"ch={self.channel} lock=none ss=0",
                "target": self.target,
                "lockkey": "192.0.2.20" if self.lock else "none",
            }[field]
        value = args[-1]
        if self.race and field == "lockkey" and value != "none":
            self.lock = "foreign"
        if self.lock and self.lock != key:
            raise TunerError("foreign lock rejects operation")
        if field == "lockkey":
            self.lock = None if value == "none" else value
            if self.takeover and value != "none":
                self.channel = "auto:9"
                self.target = "udp://192.0.2.50:5000"
        if field == "channel":
            self.channel = value
        if field == "target":
            self.target = value
        if field == "filter" and self.filter_failure:
            raise TunerError("filter failed")
        return value


def test_owned_lock_capture_cleanup():
    device = Device()
    with Tuner(config(), device):
        assert device.lock is not None
        assert device.channel == "auto:7"
        assert device.target == "udp://192.0.2.20:5000"
        assert any(a[-2:] == ["/tuner1/filter", "0x0911"] for a in device.calls)
    assert device.lock is None and device.target == "none" and device.channel == "none"
    writes = [a for a in device.calls if "set" in a]
    assert all("key" in a for a in writes[1:])
    assert not any("force" in a for a in device.calls)


@pytest.mark.parametrize("busy", ["lock", "channel", "target"])
def test_busy_refused_without_mutation(busy):
    device = Device()
    setattr(
        device, busy, {"lock": "foreign", "channel": "auto:7", "target": "udp://192.0.2.50:1"}[busy]
    )
    with pytest.raises(TunerError, match="busy"):
        with Tuner(config(), device):
            pass
    assert all("set" not in a for a in device.calls)


def test_acquisition_race_never_releases_foreign_lock():
    device = Device()
    device.race = True
    with pytest.raises(TunerError):
        with Tuner(config(), device):
            pass
    assert device.lock == "foreign"
    assert not any(a[-2:] == ["/tuner1/lockkey", "none"] for a in device.calls)


def test_busy_after_acquire_only_releases_owned_lock():
    device = Device()
    device.takeover = True
    with pytest.raises(TunerError, match="became busy"):
        with Tuner(config(), device):
            pass
    assert device.channel == "auto:9" and device.target == "udp://192.0.2.50:5000"
    assert device.lock is None


def test_foreign_takeover_during_exit_no_unkeyed_cleanup():
    device = Device()
    with pytest.raises(TunerError):
        with Tuner(config(), device):
            device.lock = "foreign"
    assert device.lock == "foreign"
    assert device.target == "udp://192.0.2.20:5000"
    assert not any(a[-2:] == ["/tuner1/lockkey", "none"] for a in device.calls)


def test_partial_startup_cleans_owned_channel():
    device = Device()
    device.filter_failure = True
    with pytest.raises(TunerError):
        with Tuner(config(), device):
            pass
    assert device.channel == "none" and device.lock is None


def test_exception_cleanup_and_full_mux():
    device = Device()
    cfg = config()
    cfg.full_multiplex = True
    with pytest.raises(ValueError):
        with Tuner(cfg, device):
            raise ValueError("synthetic failure")
    assert device.lock is None
    assert any(a[-1] == "0x0000-0x1fff" for a in device.calls)


def test_subprocess_checked_no_shell(monkeypatch):
    def fake(args, **kw):
        assert isinstance(args, list) and kw["timeout"] == 8 and "shell" not in kw
        return type("Result", (), {"returncode": 1, "stdout": "ERROR: denied"})()

    monkeypatch.setattr("subprocess.run", fake)
    with pytest.raises(TunerError):
        run_command(["hdhomerun_config", "192.0.2.10", "get", "/tuner0/status"])


def test_udp_actual_lengths_and_rtp_rejection():
    stop = Event()
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver,
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender,
    ):
        receiver.bind(("127.0.0.1", 0))
        sender.sendto(heartbeat(), receiver.getsockname())
        sender.sendto(b"\x80\x21" + b"\0" * 10 + heartbeat(), receiver.getsockname())
        source = udp_chunks(receiver, stop, duration=2)
        first = next(source)
        second = next(source)
        stop.set()
        assert len(first.data) == 188 and first.error is None
        assert first.received_at and first.monotonic_ns
        assert second.error == "unsupported_udp_framing_rtp_or_non_ts"
        assert list(source) == []


def test_journal_rotation_order_and_bytes(tmp_path):
    journal = Journal(str(tmp_path), 131072, 2)
    for i in range(8):
        journal.append(Chunk(b"x" * 50000, i, "2026-11-11T01:00:00+00:00", i * 1000, "test"))
    assert len(list(tmp_path.glob("*.jsonl"))) == 2
    records = list(journal_chunks(tmp_path))
    assert [r.index for r in records] == [6, 7]
    assert records[-1].data == b"x" * 50000
    assert records[-1].monotonic_ns == 7000


def test_journal_replay_provenance(tmp_path):
    from warnbridge.pipeline import Ingestor
    from warnbridge.storage.store import Store

    journal = Journal(str(tmp_path / "captures"), 131072, 2)
    journal.append(Chunk(heartbeat(), 0, "2026-11-11T01:00:00+00:00", 1000, "test"))
    cfg = Config(database=str(tmp_path / "archive.db"))
    result = Ingestor(cfg, "replay", "journal").process(journal_chunks(tmp_path / "captures"))
    assert result["heartbeats"] == 1
    store = Store(cfg.database)
    mid = store.messages()["items"][0]["id"]
    detail = store.message(mid)
    assert detail["sources"] == ["replay"]
    assert detail["observations"][0]["received_at"] == "2026-11-11T01:00:00+00:00"
    assert store.health()["ts_reception"]["last_live_received_at"] is None
    store.close()


def test_acquire_timeout_releases_only_uncertain_owned_key():
    device = Device()

    def uncertain(args):
        result = device(args)
        if args[2] == "set" and args[-2] == "/tuner1/lockkey":
            raise TunerError("timeout after device accepted key", uncertain=True)
        return result

    with pytest.raises(TunerError, match="timeout"):
        with Tuner(config(), uncertain):
            pass
    assert device.lock is None and device.channel == "none" and device.target == "none"
    assert device.calls[-1][2] == "key"


def test_unexpected_udp_sender():
    stop = Event()
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver,
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender,
    ):
        receiver.bind(("127.0.0.1", 0))
        sender.sendto(heartbeat(), receiver.getsockname())
        source = udp_chunks(receiver, stop, expected_host="192.0.2.99", duration=1)
        assert next(source).error == "unexpected_udp_sender"
        stop.set()
        assert list(source) == []


def test_native_keepalive_uses_owned_key_and_receiving_socket():
    from unittest.mock import Mock

    from warnbridge.inputs.hdhomerun import KEEPALIVE_PORT

    device = Device()
    lease = Tuner(config(), device)
    lease.key = str(0x12345678)
    sock = Mock(spec=socket.socket)
    with pytest.raises(TunerError, match="owned stream"):
        lease.send_keepalive(sock)
    sock.sendto.assert_not_called()
    with lease:
        lease.send_keepalive(sock)
        sock.sendto.assert_called_once_with(b"\x12\x34\x56\x78", ("192.0.2.10", KEEPALIVE_PORT))
    with pytest.raises(TunerError, match="owned stream"):
        lease.send_keepalive(sock)


def test_keepalive_is_periodic_while_udp_is_idle(monkeypatch):
    from unittest.mock import Mock

    from warnbridge.inputs import streams

    clock = [0.0]
    sent = []
    stop = Event()
    sock = Mock(spec=socket.socket)

    def timeout(_):
        clock[0] += 0.5
        raise TimeoutError

    sock.recvfrom.side_effect = timeout
    monkeypatch.setattr(streams.time, "monotonic", lambda: clock[0])
    source = streams.udp_chunks(sock, stop, duration=2.1, keepalive=lambda: sent.append(clock[0]))
    assert all(not chunk.data for chunk in source)
    assert sent == [0.0, 1.0, 2.0]
    stop.set()
    assert list(source) == []
