import socket
import time
from threading import Event
from unittest.mock import Mock

from warnbridge.inputs.health import ReceiverMonitor
from warnbridge.inputs.streams import udp_chunks

RF = "ch=auto:7 lock=8vsb ss=100 snq=98 seq=100 bps=4512 pps=2"


def next_sample(monitor):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        sample = monitor.latest()
        if sample:
            return sample
        time.sleep(0.002)
    raise AssertionError("RF sample did not arrive")


def test_polling_refreshes_and_reports_errors_then_stops():
    count = [0]

    def status():
        count[0] += 1
        if count[0] == 1:
            return RF
        raise OSError("device control unavailable")

    with ReceiverMonitor(status, interval=0.02) as monitor:
        first = next_sample(monitor)
        assert first.raw_status == RF and first.error is None
        second = next_sample(monitor)
        assert second.raw_status is None and "unavailable" in second.error
    assert not monitor.thread.is_alive()
    final = count[0]
    time.sleep(0.03)
    assert count[0] == final


def test_invalid_status_is_not_a_good_snapshot():
    with ReceiverMonitor(lambda: "unrecognized", interval=10) as monitor:
        sample = next_sample(monitor)
        assert sample.raw_status is None and "unrecognized" in sample.error


def test_slow_rf_poll_cannot_delay_udp_keepalives(monkeypatch):
    from warnbridge.inputs import streams

    entered, release = Event(), Event()

    def slow():
        entered.set()
        assert release.wait(2)
        return RF

    clock = [0.0]
    sent = []
    sock = Mock(spec=socket.socket)

    def timeout(_):
        clock[0] += 0.5
        raise TimeoutError

    sock.recvfrom.side_effect = timeout
    with ReceiverMonitor(slow, interval=10) as monitor:
        assert entered.wait(1)
        try:
            monkeypatch.setattr(streams.time, "monotonic", lambda: clock[0])
            list(udp_chunks(sock, Event(), duration=2.1, keepalive=lambda: sent.append(clock[0])))
            assert sent == [0, 1, 2]
            assert monitor.latest() is None
        finally:
            release.set()
    assert not monitor.thread.is_alive()
