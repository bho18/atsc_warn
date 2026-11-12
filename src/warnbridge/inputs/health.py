"""Read-only RF polling off the UDP/keepalive path; main thread owns DB writes."""

from collections.abc import Callable
from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Event, Thread
from types import TracebackType

from warnbridge.inputs.hdhomerun import Tuner
from warnbridge.storage.store import utc_now


@dataclass(frozen=True)
class RFSample:
    checked_at: str
    raw_status: str | None
    error: str | None = None


class ReceiverMonitor:
    def __init__(self, read_status: Callable[[], str], interval: float = 5.0) -> None:
        if interval <= 0:
            raise ValueError("RF poll interval must be positive")
        self.read_status = read_status
        self.interval = interval
        self.stop = Event()
        self.samples: Queue[RFSample] = Queue(maxsize=1)
        self.thread = Thread(target=self._poll, name="warnbridge-rf", daemon=True)

    def _poll(self) -> None:
        while not self.stop.is_set():
            try:
                raw = self.read_status()
                fields = Tuner.status_fields(raw)
                if "ch" not in fields or "lock" not in fields:
                    raise ValueError("unrecognized tuner status response")
                sample = RFSample(utc_now(), raw)
            except Exception as exc:
                sample = RFSample(utc_now(), None, str(exc)[:300])
            try:
                self.samples.put_nowait(sample)
            except Full:
                self.latest()
                self.samples.put_nowait(sample)
            if self.stop.wait(self.interval):
                break

    def latest(self) -> RFSample | None:
        try:
            return self.samples.get_nowait()
        except Empty:
            return None

    def __enter__(self) -> "ReceiverMonitor":
        self.thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop.set()
        # Native CLI read calls have an 8-second timeout. Never wait indefinitely.
        self.thread.join(timeout=9)
        if self.thread.is_alive():
            raise RuntimeError("RF polling did not stop within its control timeout")
