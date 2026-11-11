"""Strict incremental decoder of the empirically observed WARN encapsulation.

Safety bounds are application limits, not claims about an unavailable standard.
No PSI pointer byte, heuristic XML repair, or guessed resynchronization.
"""

import struct
from collections import Counter, OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass, field
from hashlib import sha256

from .crc import crc32_mpeg2

BASE_COUNTERS = (
    "warn_packets complete_messages crc_pass crc_fail heartbeats cmac_messages cap_messages "
    "link_tests duplicate_xml unique_xml continuity_gaps duplicate_ts_packets rejected_packets "
    "rejected_messages incomplete_messages"
).split()


@dataclass(frozen=True)
class Limits:
    max_body: int = 1024 * 1024
    max_fragments: int = 8192
    max_pending: int = 16
    timeout: float = 30.0
    dedup_window: int = 10000

    def __post_init__(self) -> None:
        if min(self.max_body, self.max_fragments, self.max_pending, self.dedup_window) < 1:
            raise ValueError("limits must be positive")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")


@dataclass
class Event:
    kind: str
    reason: str | None
    raw_ts: bytes
    offsets: list[int]
    assembled: bytes = b""
    header: bytes = b""
    body: bytes = b""
    stored_crc: int | None = None
    calculated_crc: int | None = None
    transport_id: int | None = None
    received_at: str | None = None
    monotonic_ns: int | None = None


@dataclass
class Assembly:
    transport_id: int
    last: int
    started: float
    received_at: str | None
    monotonic_ns: int | None
    fragments: list[bytes] = field(default_factory=list)
    packets: list[bytes] = field(default_factory=list)
    offsets: list[int] = field(default_factory=list)
    size: int = 0


class Decoder:
    def __init__(self, pid: int = 0x0911, limits: Limits | None = None) -> None:
        if not 0 <= pid <= 0x1FFE:
            raise ValueError("invalid PID")
        self.pid = pid
        self.limits = limits or Limits()
        self.counts: Counter[str] = Counter(dict.fromkeys(BASE_COUNTERS, 0))
        self.pending: dict[int, Assembly] = {}
        self.buffer = bytearray()
        self.offset = 0
        self.cc: int | None = None
        self.previous: bytes | None = None
        self.failed = False
        self.xml_seen: OrderedDict[str, None] = OrderedDict()

    def _reject(self, reason: str, raw: bytes, offsets: list[int]) -> Event:
        self.counts["rejected_packets"] += 1
        return Event("rejected", reason, raw, offsets)

    def _drop(self, reason: str, ids: list[int] | None = None) -> Iterator[Event]:
        for ident in list(self.pending) if ids is None else ids:
            a = self.pending.pop(ident)
            self.counts["incomplete_messages"] += 1
            self.counts["rejected_messages"] += 1
            yield Event(
                "rejected",
                reason,
                b"".join(a.packets),
                a.offsets,
                assembled=b"".join(a.fragments),
                transport_id=ident,
                received_at=a.received_at,
                monotonic_ns=a.monotonic_ns,
            )

    def expire(self, now: float) -> Iterator[Event]:
        yield from self._drop(
            "assembly_timeout",
            [k for k, a in self.pending.items() if now - a.started > self.limits.timeout],
        )

    def break_stream(self, reason: str) -> Iterator[Event]:
        """Explicit source loss/corruption boundary; never join across it."""
        yield from self._drop(reason)
        if self.buffer:
            yield self._reject(reason, bytes(self.buffer), [self.offset])
            self.offset += len(self.buffer)
            self.buffer.clear()
        self.cc = None
        self.previous = None

    def feed(
        self,
        data: bytes,
        *,
        now: float = 0,
        received_at: str | None = None,
        monotonic_ns: int | None = None,
    ) -> Iterator[Event]:
        if self.failed:
            raise ValueError("decoder stopped at invalid TS framing")
        yield from self.expire(now)
        self.buffer.extend(data)
        while len(self.buffer) >= 188:
            packet = bytes(self.buffer[:188])
            del self.buffer[:188]
            offset = self.offset
            self.offset += 188
            if packet[0] != 0x47:
                yield from self._drop("sync_loss")
                yield self._reject("invalid_sync_strict_stop", packet, [offset])
                self.failed = True
                return
            yield from self._packet(packet, offset, now, received_at, monotonic_ns)

    def finish(self) -> Iterator[Event]:
        if self.buffer:
            yield self._reject("truncated_or_unparsed_input", bytes(self.buffer), [self.offset])
            self.buffer.clear()
        yield from self._drop("end_of_input")

    def _packet(
        self, p: bytes, offset: int, now: float, received_at: str | None, monotonic_ns: int | None
    ) -> Iterator[Event]:
        if ((p[1] & 0x1F) << 8 | p[2]) != self.pid:
            return
        self.counts["warn_packets"] += 1
        afc = (p[3] >> 4) & 3
        if p[1] & 0x80 or p[3] & 0xC0 or afc == 0:
            yield from self._drop("invalid_ts_header")
            self.cc, self.previous = None, None
            yield self._reject("tei_scrambling_or_reserved_afc", p, [offset])
            return
        start = 4
        discontinuity = False
        if afc & 2:
            length = p[4]
            start = 5 + length
            if start > 188 or (afc == 2 and start != 188) or (afc == 3 and start >= 188):
                yield from self._drop("invalid_adaptation")
                self.cc = None
                self.previous = None
                yield self._reject("invalid_adaptation_length", p, [offset])
                return
            discontinuity = bool(length and p[5] & 0x80)
        # Exact consecutive repeats are transport retransmissions, not message deliveries.
        if p == self.previous:
            self.counts["duplicate_ts_packets"] += 1
            return
        payload = bool(afc & 1)
        cc = p[3] & 15
        if discontinuity:
            self.counts["discontinuities"] += 1
            yield from self._drop("explicit_discontinuity")
            self.cc = None
        gap = self.cc is not None and cc != ((self.cc + int(payload)) & 15)
        if gap:
            self.counts["continuity_gaps"] += 1
            yield from self._drop("continuity_gap")
        self.cc, self.previous = cc, p
        if not payload:
            return
        content = p[start:]
        if len(content) < 8:
            yield from self._drop("short_fragment_header")
            yield self._reject("short_fragment_header", p, [offset])
            return
        ident, index, last = struct.unpack(">IHH", content[:8])
        pusi = bool(p[1] & 0x40)
        if index > last or last >= self.limits.max_fragments or pusi != (index == 0):
            yield from self._drop("invalid_fragment_header")
            yield self._reject("fragment_index_limit_or_pusi", p, [offset])
            return
        if index == 0:
            if ident in self.pending:
                yield from self._drop("ambiguous_reused_id", [ident])
                yield self._reject("ambiguous_reused_id_new_start", p, [offset])
                return
            if len(self.pending) >= self.limits.max_pending:
                yield self._reject("pending_limit", p, [offset])
                return
            self.pending[ident] = Assembly(ident, last, now, received_at, monotonic_ns)
        a = self.pending.get(ident)
        if a is None:
            yield self._reject("orphan_fragment", p, [offset])
            return
        if a.last != last or index != len(a.fragments):
            yield from self._drop("conflicting_or_out_of_order_fragment", [ident])
            yield self._reject("conflicting_or_out_of_order_fragment", p, [offset])
            return
        a.fragments.append(content[8:])
        a.packets.append(p)
        a.offsets.append(offset)
        a.size += len(content) - 8
        if a.size > self.limits.max_body + 13 + 4 + 175:
            yield from self._drop("assembly_size_limit", [ident])
            return
        if index == last:
            del self.pending[ident]
            yield self._message(a)

    def _message(self, a: Assembly) -> Event:
        raw = b"".join(a.fragments)
        e = Event(
            "message",
            None,
            b"".join(a.packets),
            a.offsets,
            assembled=raw,
            header=raw[:13],
            transport_id=a.transport_id,
            received_at=a.received_at,
            monotonic_ns=a.monotonic_ns,
        )
        self.counts["complete_messages"] += 1
        reason = None
        if len(raw) < 17:
            reason = "short_message"
        else:
            length = int.from_bytes(raw[9:13], "big")
            if length > self.limits.max_body:
                reason = "body_size_limit"
            elif 13 + length + 4 > len(raw):
                reason = "body_length_exceeds_assembly"
            else:
                end = 13 + length
                e.body = raw[13:end]
                e.stored_crc = int.from_bytes(raw[end : end + 4], "big")
                e.calculated_crc = crc32_mpeg2(raw[:end])
                self.counts["crc_pass" if e.stored_crc == e.calculated_crc else "crc_fail"] += 1
                if int.from_bytes(raw[4:8], "big") != a.transport_id:
                    reason = "inner_outer_id_mismatch"
                elif e.calculated_crc != e.stored_crc:
                    reason = "crc_mismatch"
                elif any(b != 0xFF for b in raw[end + 4 :]):
                    reason = "non_ff_stuffing"
        if reason:
            e.kind, e.reason = "rejected", reason
            self.counts["rejected_messages"] += 1
        return e

    def count_xml(self, xml: bytes) -> None:
        key = sha256(xml).hexdigest()
        self.counts["duplicate_xml" if key in self.xml_seen else "unique_xml"] += 1
        self.xml_seen[key] = None
        self.xml_seen.move_to_end(key)
        if len(self.xml_seen) > self.limits.dedup_window:
            self.xml_seen.popitem(last=False)
