import json
from dataclasses import replace

import pytest

from tests.unit.test_inputs import Device as MockTuner
from warnbridge.config import Config
from warnbridge.inputs import discovery
from warnbridge.inputs.discovery import (
    Device,
    discover,
    inspect_device,
    open_receiver,
    parse_metadata,
)
from warnbridge.inputs.hdhomerun import TunerError

DEVICE = Device("192.0.2.10", "12345678", "HDHR5-2US", 2)


class Duo:
    def __init__(self):
        self.tuners = [MockTuner(), MockTuner()]
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        path = next(a for a in args if a.startswith("/tuner"))
        index = int(path.split("/")[1][5:])
        return self.tuners[index](args)


def test_native_discovery_and_dedup_no_internet_service(monkeypatch):
    monkeypatch.setattr(discovery, "device_at", lambda host: replace(DEVICE, host=host))

    def runner(args):
        assert args == ["hdhomerun_config", "discover"]
        return (
            "hdhomerun device 12345678 found at 192.0.2.10\n"
            "hdhomerun device 12345678 found at 192.0.2.11\n"
            "hdhomerun device 12345678 found at fe80::1\n"
        )

    assert discover(runner) == [DEVICE]
    assert discover(lambda _: "no devices found") == []


def test_direct_ip_skips_broadcast(monkeypatch):
    monkeypatch.setattr(discovery, "device_at", lambda host: DEVICE)
    monkeypatch.setattr(discovery, "discover", lambda: pytest.fail("broadcast attempted"))
    assert discovery.select_device(Config(receiver_host=DEVICE.host)) == DEVICE


def test_discovery_ambiguity_empty_and_id_conflict(monkeypatch):
    monkeypatch.setattr(discovery, "discover", lambda: [])
    with pytest.raises(TunerError, match="no HDHomeRun"):
        discovery.select_device(Config())
    monkeypatch.setattr(discovery, "discover", lambda: [DEVICE, replace(DEVICE, host="192.0.2.11")])
    with pytest.raises(TunerError, match="multiple HDHomeRuns"):
        discovery.select_device(Config())
    monkeypatch.setattr(discovery, "device_at", lambda _: replace(DEVICE, device_id="87654321"))
    with pytest.raises(TunerError, match="ID mismatch"):
        discover(lambda _: "hdhomerun device 12345678 found at 192.0.2.10")


def test_metadata_only_keeps_safe_fields():
    value = {
        "DeviceID": "12345678",
        "TunerCount": 2,
        "ModelNumber": "HDHR5-2US",
        "DeviceAuth": "must-not-appear",
        "BaseURL": "http://untrusted.example/",
    }
    assert parse_metadata(DEVICE.host, value) == DEVICE
    assert "must-not-appear" not in str(parse_metadata(DEVICE.host, value))
    for count in [None, False, 0, 33, "2"]:
        with pytest.raises(TunerError):
            parse_metadata(DEVICE.host, {**value, "TunerCount": count})


def test_http_metadata_is_bounded_no_redirects_and_closed(monkeypatch):
    state = {"status": 200, "data": json.dumps({"DeviceID": "12345678", "TunerCount": 2}).encode()}
    closed = []

    class Response:
        @property
        def status(self):
            return state["status"]

        def read(self, n):
            assert n == 65537
            return state["data"]

    class HTTP:
        def __init__(self, host, port, timeout):
            assert host == DEVICE.host and port == 80 and timeout == 5

        def request(self, method, path):
            assert (method, path) == ("GET", "/discover.json")

        def getresponse(self):
            return Response()

        def close(self):
            closed.append(True)

    monkeypatch.setattr(discovery.http.client, "HTTPConnection", HTTP)
    assert discovery.device_at(DEVICE.host).tuner_count == 2
    state["status"] = 302
    with pytest.raises(TunerError, match="HTTP 302"):
        discovery.device_at(DEVICE.host)
    state.update(status=200, data=b"x" * 65537)
    with pytest.raises(TunerError, match="64 KiB"):
        discovery.device_at(DEVICE.host)
    assert len(closed) == 3


def test_direct_control_explicit_tuner_fallback_without_metadata(monkeypatch):
    def unavailable(_):
        raise TunerError("HTTP unavailable")

    monkeypatch.setattr(discovery, "device_at", unavailable)
    with pytest.raises(TunerError, match="specify --tuner"):
        discovery.select_device(Config(receiver_host=DEVICE.host))
    d = discovery.select_device(Config(receiver_host=DEVICE.host, tuner=1))
    assert d.tuner_count is None and d.metadata_error
    result = inspect_device(d, Duo(), tuner=1)
    assert len(result) == 1 and result[0]["tuner"] == 1


def test_tuner_inventory_reads_channel_and_never_mutates():
    duo = Duo()
    duo.tuners[0].lock = "jellyfin"
    duo.tuners[0].channel = "auto:9"
    states = inspect_device(DEVICE, duo)
    assert [s["availability"] for s in states] == ["busy", "idle"]
    assert states[0]["channel"] == "auto:9"
    assert all("set" not in args for args in duo.calls)


@pytest.mark.parametrize("race", [False, True])
def test_auto_select_skips_busy_and_acquisition_race(monkeypatch, race):
    monkeypatch.setattr(discovery, "select_device", lambda _: DEVICE)
    duo = Duo()
    if race:
        duo.tuners[0].race = True
    else:
        duo.tuners[0].lock = "jellyfin"
    cfg = Config(channel="auto:7", return_ip="192.0.2.20")
    with open_receiver(cfg, duo) as active:
        assert active.config.tuner == 1
        assert duo.tuners[1].target == "udp://192.0.2.20:5000"
    assert duo.tuners[0].lock in ("jellyfin", "foreign")
    assert duo.tuners[1].lock is None
    assert not any(a[-2:] == ["/tuner0/lockkey", "none"] for a in duo.calls)


def test_all_busy_and_explicit_busy_do_not_take_over(monkeypatch):
    monkeypatch.setattr(discovery, "select_device", lambda _: DEVICE)
    duo = Duo()
    for tuner in duo.tuners:
        tuner.lock = "jellyfin"
    cfg = Config(channel="auto:7", return_ip="192.0.2.20")
    with pytest.raises(TunerError, match="all tuners"):
        with open_receiver(cfg, duo):
            pytest.fail("acquired busy tuner")
    with pytest.raises(TunerError, match="busy"):
        with open_receiver(replace(cfg, tuner=0), duo):
            pytest.fail("switched explicit tuner")
    assert all("set" not in args for args in duo.calls)


def test_invalid_channel_and_tuner_fail_before_mutation(monkeypatch):
    monkeypatch.setattr(discovery, "select_device", lambda _: DEVICE)
    duo = Duo()
    with pytest.raises(ValueError, match="physical RF"):
        with open_receiver(Config(), duo):
            pass
    with pytest.raises(ValueError, match="tuner count"):
        with open_receiver(Config(tuner=2, channel="auto:7", return_ip="192.0.2.20"), duo):
            pass
    assert not duo.calls
