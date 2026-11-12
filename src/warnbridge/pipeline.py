import base64
import fcntl
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from warnbridge.config import Config
from warnbridge.formats.xml import parse_body, readable_text
from warnbridge.inputs.streams import Chunk, Journal
from warnbridge.recovery import recover_rejections
from warnbridge.storage.store import Store
from warnbridge.transport.decoder import Decoder, Event


class Ingestor:
    def __init__(
        self,
        config: Config,
        source: str,
        identity: str,
        emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.config = config
        self.emit = emit
        self.last_checkpoint = 0.0
        Path(config.database).parent.mkdir(parents=True, exist_ok=True)
        self.writer_lock = open(str(Path(config.database).resolve()) + ".ingest.lock", "ab")
        try:
            fcntl.flock(self.writer_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.writer_lock.close()
            raise ValueError("another ingestion worker owns this database") from None
        try:
            self.store = Store(config.database, max_rejected=config.max_rejected)
            recovered = recover_rejections(self.store, config)
            with self.store.db:
                self.store.db.execute("UPDATE sessions SET state='abandoned' WHERE state='running'")
            self.sid = self.store.start_session(source, identity)
            if recovered:
                self.store.health_event(
                    self.sid, "recovered_observations", f"{recovered} retained failures recovered"
                )
            self.decoder = Decoder(config.pid, config.limits)
        except BaseException:
            if hasattr(self, "store"):
                self.store.close()
            self.writer_lock.close()
            raise
        self.index = 0
        self.source = source
        self.last_now = 0.0

    def record(self, event: Event) -> None:
        parsed = (
            parse_body(event.body, max_bytes=self.config.limits.max_body)
            if event.kind == "message"
            else None
        )
        if parsed:
            counts = self.decoder.counts
            if parsed.classification == "heartbeat":
                counts["heartbeats"] += 1
            if parsed.protocol == "CMAC":
                counts["cmac_messages"] += 1
            if parsed.protocol == "CAP":
                counts["cap_messages"] += 1
            if parsed.classification == "cmac_link_test":
                counts["link_tests"] += 1
            if parsed.xml is not None and parsed.xml_state == "well_formed":
                self.decoder.count_xml(parsed.xml)
            if parsed.xml_state == "invalid":
                counts["xml_failures"] += 1
        mid = self.store.record(self.sid, event, parsed, self.index)
        if self.emit is not None:
            count = (
                self.store.db.execute(
                    "SELECT count(*) FROM observations WHERE message_id=?", (mid,)
                ).fetchone()[0]
                if mid is not None
                else 0
            )
            self.emit(
                {
                    "type": event.kind,
                    "session_id": self.sid,
                    "message_id": mid,
                    "source": self.source,
                    "received_at": event.received_at,
                    "transport_id": event.transport_id,
                    "reason": event.reason,
                    "classification": parsed.classification if parsed else None,
                    "validation": {
                        "transport": "valid" if event.kind == "message" else "invalid",
                        "xml": parsed.xml_state if parsed else "not_checked",
                        "schema": "not_configured",
                        "signature": "not_checked",
                    },
                    "duplicate": count > 1,
                    "body_base64": base64.b64encode(event.body).decode("ascii"),
                    "xml": readable_text(parsed.xml) if parsed and parsed.xml is not None else None,
                    "fields": parsed.fields if parsed else {},
                }
            )

    def process(self, chunks: Iterable[Chunk], journal: Journal | None = None) -> dict[str, int]:
        state = "finished"
        try:
            for chunk in chunks:
                self.index = chunk.index
                if chunk.monotonic_ns is not None:
                    self.last_now = chunk.monotonic_ns / 1e9
                if journal and chunk.data:
                    journal.append(chunk)
                # Stop instead of deleting accepted evidence when storage quota is reached.
                size = sum(
                    p.stat().st_size
                    for p in [Path(self.config.database), Path(self.config.database + "-wal")]
                    if p.exists()
                )
                if size >= self.config.max_database_bytes:
                    self.store.health_event(
                        self.sid,
                        "storage_quota_reached",
                        "Archive limit reached; archive data or increase max_database_bytes",
                    )
                    raise OSError("database quota reached; archive evidence before restarting")
                if chunk.error:
                    self.decoder.counts["input_errors"] += 1
                    for event in self.decoder.break_stream(chunk.error):
                        self.record(event)
                    self.record(
                        Event(
                            "rejected",
                            chunk.error,
                            chunk.data,
                            [],
                            received_at=chunk.received_at,
                            monotonic_ns=chunk.monotonic_ns,
                        )
                    )
                    continue
                for event in self.decoder.feed(
                    chunk.data,
                    now=self.last_now,
                    received_at=chunk.received_at,
                    monotonic_ns=chunk.monotonic_ns,
                ):
                    self.record(event)
                if time.monotonic() - self.last_checkpoint >= 1:
                    self.store.finish_session(self.sid, dict(self.decoder.counts), "running")
                    self.last_checkpoint = time.monotonic()
                if self.decoder.failed:
                    state = "failed"
                    break
        except BaseException as exc:
            state = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
            self.store.health_event(self.sid, state, type(exc).__name__)
            raise
        finally:
            cleanup_error: BaseException | None = None
            try:
                close = getattr(chunks, "close", None)
                if close is not None:
                    close()  # deterministically unwind an owned tuner on early stop/failure
            except BaseException as exc:
                cleanup_error = exc
                state = "failed"
            try:
                if cleanup_error is not None:
                    self.store.health_event(
                        self.sid, "source_cleanup_failed", type(cleanup_error).__name__
                    )
                for event in self.decoder.finish():
                    self.record(event)
                self.store.finish_session(self.sid, dict(self.decoder.counts), state)
            finally:
                self.store.close()
                self.writer_lock.close()
            if cleanup_error is not None:
                raise cleanup_error
        return dict(self.decoder.counts)
