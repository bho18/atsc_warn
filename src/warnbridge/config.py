import tomllib
from dataclasses import dataclass, field
from ipaddress import IPv4Address
from pathlib import Path
from zoneinfo import ZoneInfo

from warnbridge.transport.decoder import Limits


@dataclass
class Config:
    database: str = "data/warnbridge.db"
    bind: str = "127.0.0.1"
    port: int = 8080
    timezone: str = "America/Chicago"
    pid: int = 0x0911
    receiver_host: str | None = None
    tuner: int | None = None
    channel: str | None = None
    udp_bind: str = "0.0.0.0"
    return_ip: str | None = None
    udp_port: int = 5000
    full_multiplex: bool = False
    record_raw: bool = False
    no_data_warning: float = 45.0
    rf_poll_interval: float = 5.0
    rf_stale_after: float = 20.0
    heartbeat_stale_after: float = 45.0
    capture_dir: str = "data/captures"
    capture_segment_bytes: int = 8 * 1024 * 1024
    capture_segments: int = 8
    max_database_bytes: int = 512 * 1024 * 1024
    max_rejected: int = 1000
    limits: Limits = field(default_factory=Limits)

    def __post_init__(self) -> None:
        ZoneInfo(self.timezone)
        if not 0 <= self.pid <= 0x1FFE:
            raise ValueError("invalid PID")
        if not 1 <= self.port <= 65535 or not 1 <= self.udp_port <= 65535:
            raise ValueError("invalid port")
        if self.tuner is not None and not 0 <= self.tuner < 32:
            raise ValueError("tuner must be between 0 and 31")
        if self.receiver_host:
            IPv4Address(self.receiver_host)
        IPv4Address(self.udp_bind)
        if self.return_ip:
            IPv4Address(self.return_ip)
        if self.rf_poll_interval < 1 or self.rf_stale_after <= self.rf_poll_interval:
            raise ValueError("RF poll interval must be >=1s; stale threshold must exceed interval")
        if self.heartbeat_stale_after <= 0:
            raise ValueError("heartbeat_stale_after must be positive")
        if self.no_data_warning <= 0:
            raise ValueError("no_data_warning must be positive")
        if min(self.capture_segments, self.max_rejected) < 1:
            raise ValueError("retention limits must be positive")
        if self.capture_segment_bytes < 131072 or self.max_database_bytes < 1048576:
            raise ValueError("storage limits too small")

    def require_receiver(self) -> None:
        if not self.receiver_host or self.tuner is None or not self.channel or not self.return_ip:
            raise ValueError(
                "capture requires explicit receiver_host, tuner, channel and return_ip"
            )


def load_config(path: str | None) -> Config:
    if path is None:
        return Config()
    with Path(path).open("rb") as stream:
        raw = tomllib.load(stream)
    if "limits" in raw:
        raw["limits"] = Limits(**raw["limits"])
    return Config(**raw)
