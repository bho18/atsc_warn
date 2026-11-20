"""Receiver recovery against mocked control and loopback-only UDP sockets."""

import json
import os
import signal
import socket
import sqlite3
import time
from contextlib import nullcontext
from dataclasses import replace
from threading import Event, Timer
from types import SimpleNamespace

import pytest

from tests.fixtures.golden import cmac, heartbeat
from tests.unit.test_discovery import DEVICE, Duo
from warnbridge import cli, pipeline
from warnbridge.inputs import discovery, streams
from warnbridge.inputs.hdhomerun import Tuner
from warnbridge.inputs.streams import Chunk
from warnbridge.storage.store import Store


class Clock:
    def __init__(self):
        self.now = 0.0
        self.waits = []
        self.on_wait = None

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Stop:
    def __init__(self, clock):
        self.clock = clock
        self.stopped = False

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, timeout):
        assert timeout >= 0
        self.clock.waits.append(timeout)
        if self.clock.on_wait:
            self.clock.on_wait(timeout)
        if not self.stopped:
            self.clock.advance(timeout)
        return self.stopped


def stop_then_events(stop):
    first = True

    def create():
        nonlocal first
        if first:
            first = False
            return stop
        return Event()

    return create


@pytest.fixture
def receiver(tmp_path, monkeypatch):
    """Keep real leasing/ingestion, replacing discovery, RF threads and time."""
    clock = Clock()
    stop = Stop(clock)
    duo = Duo()
    selections = []
    state = SimpleNamespace(clock=clock, stop=stop, duo=duo, selections=selections, on_select=None)

    def select(config):
        selections.append(config.tuner)
        if state.on_select:
            state.on_select()
        return replace(DEVICE, host="127.0.0.1")

    monkeypatch.setattr(discovery, "select_device", select)
    monkeypatch.setattr(cli, "open_receiver", lambda config: discovery.open_receiver(config, duo))
    monkeypatch.setattr(cli, "ReceiverMonitor", lambda *a, **kw: nullcontext(None))
    monkeypatch.setattr(cli, "Event", stop_then_events(stop))
    monkeypatch.setattr(
        cli,
        "time",
        SimpleNamespace(monotonic=clock.monotonic, monotonic_ns=lambda: int(clock.now * 1e9)),
    )
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    state.database = tmp_path / "reconnect.db"
    state.config = tmp_path / "reconnect.toml"
    state.config.write_text(
        f'database="{state.database}"\n'
        'receiver_host="127.0.0.1"\nreturn_ip="127.0.0.1"\n'
        f'udp_bind="127.0.0.1"\nudp_port={port}\nchannel="auto:7"\n'
        "no_data_warning=1.0\nreceiver_stall_timeout=2.0\n"
        "receiver_retry_initial=1.0\nreceiver_retry_max=3.0\n"
    )
    state.args = lambda *extra, command="listen": cli.parser().parse_args(
        [command, "--config", str(state.config), *extra]
    )
    state.chunk = lambda data=b"", index=0, **kwargs: Chunk(
        data,
        index,
        received_at="2026-11-15T12:00:00Z",
        monotonic_ns=int(clock.now * 1e9),
        peer="127.0.0.1:5004",
        **kwargs,
    )
    return state


def messages(capsys):
    captured = capsys.readouterr()
    return [json.loads(line) for line in captured.out.splitlines()], captured.err


@pytest.mark.parametrize(("foreign", "command"), [(True, "listen"), (False, "capture")])
def test_lost_receiver_gets_fresh_socket_session_and_available_tuner(
    receiver, monkeypatch, capsys, foreign, command
):
    sockets = []

    def stream(sock, stop, **kwargs):
        assert kwargs["expected_host"] == "127.0.0.1"
        sockets.append(sock)
        yield receiver.chunk(heartbeat())
        if len(sockets) == 1:
            device = receiver.duo.tuners[0]
            device.lock = "jellyfin" if foreign else None
            device.channel = "auto:9"
            device.target = "http://jellyfin:5004" if foreign else "none"
            receiver.clock.advance(2.1)
            yield receiver.chunk(index=1)
            pytest.fail("stalled receiver did not unwind for retry")
        assert sockets[0].fileno() == -1
        stop.set()

    monkeypatch.setattr(cli, "udp_chunks", stream)
    assert cli.run(receiver.args(command=command)) == 0
    records, stderr = messages(capsys)
    assert [r["tuner"] for r in records if r["type"] == "receiver"] == [0, int(foreign)]
    accepted = [r for r in records if r["type"] == "message"]
    assert len(accepted) == 2
    assert len({r["session_id"] for r in accepted}) == 2
    assert len(sockets) == 2 and sockets[0] is not sockets[1]
    assert all(sock.fileno() == -1 for sock in sockets)
    assert "retry" in stderr.lower()
    assert not any("force" in call for call in receiver.duo.calls)
    if foreign:
        assert receiver.duo.tuners[0].lock == "jellyfin"
        assert receiver.duo.tuners[0].channel == "auto:9"
        assert receiver.duo.tuners[0].target == "http://jellyfin:5004"
    assert receiver.duo.tuners[int(foreign)].lock is None
    store = Store(str(receiver.database))
    try:
        assert store.db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 2
        assert not store.db.execute("SELECT 1 FROM sessions WHERE state='running'").fetchone()
    finally:
        store.close()


def test_all_tuners_busy_recovers_after_release_without_forcing_locks(
    receiver, monkeypatch, capsys
):
    for device in receiver.duo.tuners:
        device.lock = "jellyfin"

    def release(_):
        assert all("set" not in call for call in receiver.duo.calls)
        receiver.duo.tuners[1].lock = None
        receiver.duo.tuners[1].channel = "auto:9"
        receiver.duo.tuners[1].target = "http://jellyfin:5004"

    receiver.clock.on_wait = release

    def stream(sock, stop, **kwargs):
        yield receiver.chunk(cmac())
        stop.set()

    monkeypatch.setattr(cli, "udp_chunks", stream)
    assert cli.run(receiver.args()) == 0
    records, stderr = messages(capsys)
    assert len(receiver.selections) == 2
    assert [r["tuner"] for r in records if r["type"] == "receiver"] == [1]
    assert any(r.get("classification") == "cmac_link_test" for r in records)
    assert "retry" in stderr.lower() and "tuners" in stderr.lower()
    assert receiver.duo.tuners[0].lock == "jellyfin"
    assert all("set" not in call for call in receiver.duo.tuners[0].calls)
    assert receiver.duo.tuners[1].lock is None


def test_pinned_busy_tuner_never_switches_to_free_second_tuner(receiver, monkeypatch):
    receiver.duo.tuners[0].lock = "jellyfin"
    monkeypatch.setattr(cli, "udp_chunks", lambda *a, **kw: pytest.fail("busy tuner streamed"))
    cli.run(receiver.args("--tuner", "0", "--duration", "2.5"))
    assert receiver.selections == [0, 0]
    assert not receiver.duo.tuners[1].calls
    assert receiver.duo.tuners[0].lock == "jellyfin"
    assert receiver.clock.now == pytest.approx(2.5)


def test_fragments_are_never_joined_across_receiver_reconnect(receiver, monkeypatch, capsys):
    attempts = 0

    def stream(sock, stop, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            yield receiver.chunk(cmac()[:188])
            receiver.clock.advance(2.1)
            yield receiver.chunk(index=1)
            pytest.fail("incomplete stalled session did not end")
        yield receiver.chunk(cmac()[188:])
        yield receiver.chunk(heartbeat(), 1)
        stop.set()

    monkeypatch.setattr(cli, "udp_chunks", stream)
    assert cli.run(receiver.args()) == 0
    records, _ = messages(capsys)
    accepted = [r for r in records if r["type"] == "message"]
    assert [r["classification"] for r in accepted] == ["heartbeat"]
    rejected = [r for r in records if r["type"] == "rejected"]
    assert any(r["reason"] == "orphan_fragment" for r in rejected)
    assert len({r["session_id"] for r in rejected}) == 2


@pytest.mark.parametrize("traffic", ["unrelated_pid", "unexpected_sender", "transport_error"])
def test_invalid_or_unrelated_traffic_does_not_mask_warn_stall(
    receiver, monkeypatch, capsys, traffic
):
    attempts = 0
    bad = bytearray(heartbeat())
    if traffic == "unrelated_pid":
        bad[2] = 0x12
    elif traffic == "transport_error":
        bad[1] |= 0x80

    def stream(sock, stop, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            for index in range(4):
                receiver.clock.advance(1.0)
                yield receiver.chunk(
                    bytes(bad),
                    index,
                    error="unexpected_udp_sender" if traffic == "unexpected_sender" else None,
                )
            pytest.fail("unusable traffic indefinitely refreshed the WARN watchdog")
        yield receiver.chunk(heartbeat())
        stop.set()

    monkeypatch.setattr(cli, "udp_chunks", stream)
    assert cli.run(receiver.args()) == 0
    records, stderr = messages(capsys)
    assert attempts == 2
    assert any(r.get("classification") == "heartbeat" for r in records)
    assert "retry" in stderr.lower()


def test_link_tests_keep_receiver_healthy_without_heartbeats(receiver, monkeypatch, capsys):
    def stream(sock, stop, **kwargs):
        for index in range(5):
            receiver.clock.advance(1.5)
            data = bytearray(cmac())
            for offset in range(3):
                data[188 * offset + 3] = 0x10 | ((index * 3 + offset) & 15)
            yield receiver.chunk(bytes(data), index)
        stop.set()

    monkeypatch.setattr(cli, "udp_chunks", stream)
    assert cli.run(receiver.args()) == 0
    records, _ = messages(capsys)
    assert len(receiver.selections) == 1
    assert not receiver.clock.waits
    accepted = [r["classification"] for r in records if r["type"] == "message"]
    assert accepted == ["cmac_link_test"] * 5


def test_overall_duration_bounds_busy_retries_and_final_backoff(receiver, monkeypatch):
    for device in receiver.duo.tuners:
        device.lock = "jellyfin"
    monkeypatch.setattr(cli, "udp_chunks", lambda *a, **kw: pytest.fail("busy tuner streamed"))
    cli.run(receiver.args("--duration", "5.5"))
    assert receiver.clock.waits == pytest.approx([1.0, 2.0, 2.5])
    assert receiver.clock.now == pytest.approx(5.5)
    assert len(receiver.selections) == 3
    assert all("set" not in call for call in receiver.duo.calls)


def test_keepalive_send_failure_unwinds_owned_tuner_with_bounded_retry(
    receiver, monkeypatch, capsys
):
    def fail(self, sock):
        raise OSError("synthetic outbound UDP failure")

    # Use the same clock in the public CLI and the real UDP iterator.
    monkeypatch.setattr(streams, "time", SimpleNamespace(monotonic=receiver.clock.monotonic))
    monkeypatch.setattr(Tuner, "send_keepalive", fail)
    assert cli.run(receiver.args("--duration", "0.1")) == 2
    _, stderr = messages(capsys)
    assert "receiver UDP I/O failed" in stderr
    assert receiver.selections == [None]
    assert receiver.clock.waits == pytest.approx([0.1])
    device = receiver.duo.tuners[0]
    assert device.lock is None and device.target == "none" and device.channel == "none"
    store = Store(receiver.database)
    try:
        assert [row["state"] for row in store.receivers()] == ["failed"]
    finally:
        store.close()


def test_sigterm_interrupts_long_receiver_backoff(receiver, monkeypatch):
    for device in receiver.duo.tuners:
        device.lock = "jellyfin"
    receiver.config.write_text(
        receiver.config.read_text()
        .replace("receiver_retry_initial=1.0", "receiver_retry_initial=30.0")
        .replace("receiver_retry_max=3.0", "receiver_retry_max=30.0")
    )
    stop = Event()
    monkeypatch.setattr(cli, "Event", stop_then_events(stop))
    timer = Timer(0.05, lambda: os.kill(os.getpid(), signal.SIGTERM))
    receiver.on_select = timer.start
    started = time.monotonic()
    try:
        assert cli.run(receiver.args()) == 0
    finally:
        timer.cancel()
        if timer.ident is not None:
            timer.join(timeout=1)
    assert stop.is_set()
    assert time.monotonic() - started < 2
    assert len(receiver.selections) == 1


@pytest.mark.parametrize("failure", ["quota", "sqlite"])
@pytest.mark.parametrize("foreign_takeover", [False, True])
def test_storage_failures_remain_fatal_even_if_owned_cleanup_fails(
    receiver, monkeypatch, failure, foreign_takeover
):
    started = False

    def stream(*args, **kwargs):
        nonlocal started
        started = True
        if foreign_takeover:
            receiver.duo.tuners[0].lock = "jellyfin"
        yield receiver.chunk(heartbeat())

    monkeypatch.setattr(cli, "udp_chunks", stream)
    if failure == "quota":
        monkeypatch.setattr(
            pipeline, "storage_usage", lambda *a: {"used_bytes": 2**40 if started else 0}
        )
        exception, detail = OSError, "quota"
    else:

        def fail(*args):
            raise sqlite3.OperationalError("synthetic disk full")

        monkeypatch.setattr(pipeline.Ingestor, "record", fail)
        exception, detail = sqlite3.OperationalError, "disk full"
    with pytest.raises(exception, match=detail):
        cli.run(receiver.args())
    assert len(receiver.selections) == 1
    assert not receiver.clock.waits
    assert receiver.duo.tuners[0].lock == ("jellyfin" if foreign_takeover else None)
    assert receiver.duo.tuners[1].lock is None


def test_full_archive_stops_before_busy_tuner_attempts(receiver, monkeypatch):
    for device in receiver.duo.tuners:
        device.lock = "jellyfin"
    monkeypatch.setattr(pipeline, "storage_usage", lambda *a: {"used_bytes": 2**40})
    monkeypatch.setattr(cli, "udp_chunks", lambda *a, **kw: pytest.fail("full archive streamed"))
    with pytest.raises(OSError, match="quota"):
        cli.run(receiver.args())
    assert not receiver.selections
    assert not receiver.duo.calls
    assert not receiver.clock.waits
    assert all(device.lock == "jellyfin" for device in receiver.duo.tuners)


def test_bind_failure_stays_fatal_before_tuner_mutation(receiver):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        with pytest.raises(OSError):
            cli.run(receiver.args("--udp-port", str(occupied.getsockname()[1])))
    assert not receiver.selections
    assert not receiver.duo.calls
    assert not receiver.clock.waits


def test_raw_udp_does_not_acquire_or_restart_a_tuner(receiver, monkeypatch, capsys):
    def stream(sock, stop, **kwargs):
        assert kwargs.get("keepalive") is None
        receiver.clock.advance(3.0)
        yield receiver.chunk()
        yield receiver.chunk(heartbeat(), 1)
        stop.set()

    monkeypatch.setattr(cli, "udp_chunks", stream)
    assert cli.run(receiver.args(command="udp")) == 0
    records, _ = messages(capsys)
    assert not receiver.selections
    assert not receiver.clock.waits
    assert any(r.get("classification") == "heartbeat" for r in records)
    assert len([r for r in records if r["type"] == "summary"]) == 1
