"""Native SiliconDust CLI discovery plus bounded local device metadata reads.

No Internet discovery service. Explicit IP skips broadcast discovery altogether.
Only the documented local /discover.json resource is requested; redirects and
arbitrary URLs from discovery results are never followed.
"""

import http.client
import json
import re
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from ipaddress import IPv4Address
from typing import Any

from warnbridge.config import Config
from warnbridge.inputs.hdhomerun import Runner, Tuner, TunerBusy, TunerError, run_command

DISCOVERY_LINE = re.compile(r"^hdhomerun device ([0-9a-fA-F]{8}) found at ([0-9.]+)$")


@dataclass(frozen=True)
class Device:
    host: str
    device_id: str | None
    model: str | None
    tuner_count: int | None
    metadata_error: str | None = None


def device_at(host: str) -> Device:
    """Direct-IP metadata, without broadcast, a cloud service, proxy or redirect."""
    IPv4Address(host)
    connection = http.client.HTTPConnection(host, 80, timeout=5)
    try:
        connection.request("GET", "/discover.json")
        response = connection.getresponse()
        if response.status != 200:
            raise TunerError(f"device /discover.json returned HTTP {response.status}")
        raw = response.read(65537)
        if len(raw) > 65536:
            raise TunerError("device metadata exceeds 64 KiB limit")
        return parse_metadata(host, json.loads(raw))
    except (OSError, http.client.HTTPException, ValueError, RecursionError) as exc:
        raise TunerError(f"device metadata unavailable at {host}: {type(exc).__name__}") from None
    finally:
        connection.close()


def parse_metadata(host: str, value: Any) -> Device:
    if not isinstance(value, dict):
        raise TunerError("invalid device metadata object")
    count = value.get("TunerCount")
    ident = value.get("DeviceID")
    if type(count) is not int or not 1 <= count <= 32:
        raise TunerError("device metadata must report 1–32 tuners")
    if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-fA-F]{8}", ident):
        raise TunerError("invalid device ID in metadata")
    model = value.get("ModelNumber")
    # DeviceAuth and all unknown fields are intentionally excluded.
    return Device(host, ident.upper(), model[:128] if isinstance(model, str) else None, count)


def discover(runner: Runner = run_command) -> list[Device]:
    output = runner(["hdhomerun_config", "discover"])
    found: dict[str, str] = {}
    for line in output.splitlines():
        match = DISCOVERY_LINE.fullmatch(line.strip())
        if match:
            ident, host = match.groups()
            IPv4Address(host)
            found.setdefault(ident.upper(), host)
            if len(found) > 32:
                raise TunerError("discovery exceeded 32-device application limit")
    devices = []
    for ident, host in found.items():
        try:
            device = device_at(host)
        except TunerError as exc:
            devices.append(Device(host, ident, None, None, str(exc)))
            continue
        if device.device_id != ident:
            raise TunerError("native discovery/device metadata ID mismatch")
        devices.append(device)
    return devices


def select_device(config: Config) -> Device:
    if config.receiver_host:
        try:
            return device_at(config.receiver_host)
        except TunerError as exc:
            # TCP control can work even if local HTTP metadata is unavailable. An
            # explicitly selected tuner is sufficient; do not invent a tuner count.
            if config.tuner is not None:
                return Device(config.receiver_host, None, None, None, str(exc))
            raise TunerError(
                f"{exc}; specify --tuner to use direct control without metadata"
            ) from None
    devices = discover()
    if not devices:
        raise TunerError("no HDHomeRun discovered; use --host IP across VLANs or WSL NAT")
    if len(devices) != 1:
        raise TunerError("multiple HDHomeRuns discovered; choose one with --host IP")
    return devices[0]


def inspect_device(
    device: Device, runner: Runner = run_command, *, tuner: int | None = None
) -> list[dict[str, Any]]:
    indices = (
        range(device.tuner_count) if device.tuner_count else ([tuner] if tuner is not None else [])
    )
    result = []
    for index in indices:
        try:
            snapshot = Tuner(Config(receiver_host=device.host, tuner=index), runner).inspect()
            status = Tuner.status_fields(snapshot["status"])
            result.append(
                {
                    "tuner": index,
                    "availability": "idle"
                    if Tuner.idle(snapshot, require_unlocked=True)
                    else "busy",
                    "channel": status.get("ch"),
                    "rf": status,
                    **snapshot,
                }
            )
        except TunerError as exc:
            result.append({"tuner": index, "availability": "unknown", "error": str(exc)})
    return result


def return_address(host: str) -> str:
    """Ask the local routing table; UDP connect sends no application datagram."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((host, 65001))
        return str(sock.getsockname()[0])


def receiver_config(config: Config, device: Device) -> Config:
    return replace(
        config, receiver_host=device.host, return_ip=config.return_ip or return_address(device.host)
    )


@contextmanager
def open_receiver(config: Config, runner: Runner = run_command) -> Iterator[Tuner]:
    """Select one device and acquire one idle tuner; retry only lost/busy leases."""
    if not config.channel:
        raise ValueError("choose a physical RF channel with --channel (for example --channel 7)")
    device = select_device(config)
    selected = receiver_config(config, device)
    if config.tuner is not None:
        if device.tuner_count is not None and config.tuner >= device.tuner_count:
            raise ValueError("selected tuner is outside the device's reported tuner count")
        candidates = [config.tuner]
    elif device.tuner_count is not None:
        candidates = list(range(device.tuner_count))
    else:
        raise TunerError("tuner count unavailable; select --tuner explicitly")
    for index in candidates:
        tuner = Tuner(replace(selected, tuner=index), runner)
        try:
            tuner.__enter__()
        except TunerBusy:
            if config.tuner is not None:
                raise
            continue
        try:
            yield tuner
        finally:
            tuner.close()
        return
    raise TunerBusy("all tuners are busy or foreign-owned; retry when one is idle")
