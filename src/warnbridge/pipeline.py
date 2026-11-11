import fcntl
from collections.abc import Iterable
from pathlib import Path

from warnbridge.config import Config
from warnbridge.formats.xml import parse_body
from warnbridge.inputs.streams import Chunk, Journal
from warnbridge.storage.store import Store
from warnbridge.transport.decoder import Decoder, Event


class Ingestor:
    def __init__(self, config: Config, source: str, identity: str) -> None:
        self.config = config
        Path(config.database).parent.mkdir(parents=True, exist_ok=True)
        self.writer_lock = open(str(Path(config.database).resolve()) + ".ingest.lock", "ab")
        try:
            fcntl.flock(self.writer_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.writer_lock.close()
            raise ValueError("another ingestion worker owns this database") from None
        try:
            self.store = Store(config.database, max_rejected=config.max_rejected)
            with self.store.db:
                self.store.db.execute("UPDATE sessions SET state='abandoned' WHERE state='running'")
            self.sid = self.store.start_session(source, identity)
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
        self.store.record(self.sid, event, parsed, self.index)

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
                self.store.finish_session(self.sid, dict(self.decoder.counts), "running")
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
