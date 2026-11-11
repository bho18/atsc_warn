"""File/stdin and raw UDP inputs, with bounded replayable arrival journals."""

import base64
import json
import socket
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from threading import Event as StopEvent
from typing import BinaryIO
from uuid import uuid4

from warnbridge.storage.store import utc_now


@dataclass
class Chunk:
    data: bytes
    index: int
    received_at: str | None = None
    monotonic_ns: int | None = None
    peer: str | None = None
    error: str | None = None


def file_chunks(stream: BinaryIO) -> Iterator[Chunk]:
    index = 0
    while data := stream.read(65536):
        yield Chunk(data, index)
        index += 1


def udp_chunks(
    sock: socket.socket,
    stop: StopEvent,
    *,
    expected_host: str | None = None,
    duration: float | None = None,
) -> Iterator[Chunk]:
    sock.settimeout(0.5)
    start = time.monotonic()
    index = 0
    while not stop.is_set() and (duration is None or time.monotonic() - start < duration):
        try:
            data, peer = sock.recvfrom(65535)  # actual bytes; never unused buffer capacity
        except TimeoutError:
            yield Chunk(b"", index, monotonic_ns=time.monotonic_ns())
            continue
        error = None
        if expected_host and peer[0] != expected_host:
            error = "unexpected_udp_sender"
        elif not data or len(data) % 188 or any(data[i] != 0x47 for i in range(0, len(data), 188)):
            error = "unsupported_udp_framing_rtp_or_non_ts"
        yield Chunk(data, index, utc_now(), time.monotonic_ns(), f"{peer[0]}:{peer[1]}", error)
        index += 1


class Journal:
    """Independent JSONL records, bounded disk retention; never a private fixture."""

    def __init__(self, directory: str, segment_bytes: int, segments: int) -> None:
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.segment_bytes, self.segments = segment_bytes, segments
        self.path: Path | None = None
        self.size = 0
        self.session = uuid4().hex
        self.sequence = 0

    def append(self, chunk: Chunk) -> None:
        record = {
            "format": "warnbridge-arrival-v1",
            "index": chunk.index,
            "received_at": chunk.received_at,
            "monotonic_ns": chunk.monotonic_ns,
            "peer": chunk.peer,
            "error": chunk.error,
            "data": base64.b64encode(chunk.data).decode("ascii"),
        }
        encoded = (json.dumps(record) + "\n").encode()
        if len(encoded) > self.segment_bytes:
            raise ValueError("record exceeds capture segment bound")
        if self.path is None or self.size + len(encoded) > self.segment_bytes:
            self.path = self.root / f"arrival-{time.time_ns()}-{self.session}-{self.sequence}.jsonl"
            self.sequence += 1
            self.size = 0
            self.path.touch(mode=0o600, exist_ok=False)
            files = sorted(self.root.glob("arrival-*.jsonl"))
            for old in files[: -self.segments]:
                old.unlink()
        with self.path.open("ab") as stream:
            stream.write(encoded)
        self.size += len(encoded)


def journal_chunks(path: Path) -> Iterator[Chunk]:
    files = sorted(path.glob("arrival-*.jsonl")) if path.is_dir() else [path]
    previous_index: int | None = None
    for file in files:
        with file.open("rb") as stream:
            while line := stream.readline(131073):
                if len(line) > 131072:
                    raise ValueError("oversized journal record")
                raw = json.loads(line)
                if raw.get("format") != "warnbridge-arrival-v1":
                    raise ValueError("unknown journal format")
                data = base64.b64decode(raw["data"], validate=True)
                if len(data) > 65535:
                    raise ValueError("oversized journal payload")
                index = int(raw["index"])
                if previous_index is not None and index != previous_index + 1:
                    yield Chunk(b"", index, error="journal_sequence_boundary")
                previous_index = index
                yield Chunk(
                    data, index, raw["received_at"], raw["monotonic_ns"], raw["peer"], raw["error"]
                )
