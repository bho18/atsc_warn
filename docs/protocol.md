# Supported experimental transport

This is an implementation of a user-observed ATSC 1.0 encapsulation, not a claim of
PBS C–1 or ATIS conformance. See evidence.md and request.md for the exact vectors.

## TS and fragmentation

Strict 188-byte MPEG-TS: sync 47, PID selection, TEI/scrambling rejection,
PUSI, adaptation control/length, continuity and adaptation discontinuity handling.
Payload-bearing CC increments modulo 16; adaptation-only CC does not increment.
Exact consecutive identical packets are transport duplicates. They do not create
deliveries. Payload CC loss or invalid headers discard all pending WARN assemblies.
A new clean start may follow a loss. No fragments are joined across a known loss.
Strict sync failure stops parsing; no guessed resynchronization is implemented.
Arbitrary file/stdin read boundaries are supported; truncated tails are retained
as rejection evidence. Non-selected PIDs are ignored after TS sync checking.

WARN payload starts with big-endian `>IHH`: transport ID, fragment index, inclusive
last index. No PSI pointer field. PUSI must be true only on fragment 0. Payload-only
capacity: 184 bytes, minus the 8-byte fragment header leaves 176 content bytes.
Different IDs may interleave, with strict per-ID sequence. A second start using a
pending ID rejects both starts; orphan continuations are rejected. Reused IDs after
a completed message are allowed. Same-CC nonidentical packets imply loss/conflict.

Default configurable application bounds: 1 MiB body, 8192 fragments, 16 pending
assemblies, 30-second monotonic timeout, 10,000 XML hashes in summary dedup window.
These are not normative protocol limits. Timestamp-free imports have no temporal
arrival evidence: timeout does not advance with wall-clock processing; other bounds
and EOF still apply. Live idle socket ticks advance timeouts. Journal replay uses
recorded monotonic times. Assemblies also have a byte bound (body limit + headers,
CRC and at most one fragment's stuffing).

## Assembled bytes

| Offset | Bytes | Observation / treatment |
|---|---:|---|
| 0 | 1 | observed 2F; raw value only |
| 1 | 1 | observed 00 CMAC, 03 heartbeat; no normative enum |
| 2 | 2 | observed 00FF; raw |
| 4 | 4 | repeated transport ID, must match outer ID |
| 8 | 1 | observed 00; raw |
| 9 | 4 | big-endian exact body length |
| 13 | length | body retained byte-for-byte |
| next | 4 | big-endian stored CRC |
| remainder | variable | must all be FF |

Unknown header values do not acquire invented protocol/version names: exact header
hex and `observed_header_profile=false` appear in observation metadata. Structural
integrity and body dispatch remain separate. CRC covers the 13-byte header and
exact declared body: poly 04C11DB7, init FFFFFFFF, non-reflected, xorout 0. Ordinary
zlib CRC is not interchangeable. A transport rejection cannot enter messages/alerts.

CMAC body contains one terminal NUL in supplied evidence. Parsing removes only
one terminal NUL in a separate XML view. Original body and complete assembled
bytes, including FF stuffing, remain in each observation. No tag repair, inner
NUL removal or whitespace trimming. Heartbeat is an exact 17-byte body match.

## XML, lifecycle and geography

Dispatch by expanded namespace/root for CMAC 2.0 and CAP 1.2, including prefixes.
DefusedXML forbids DTD/entities/external resources; size, depth and element-count
bounds apply. Ordered child lists, expanded names, attributes, text and tails
preserve repeated infos/areas/parameters/extensions. The original XML view is
stored separately; no signatures are transformed or verified. Comments and XML
prefix spelling remain in raw XML, not the parsed tree view.

Transport integrity, XML well-formedness, schema, signature, classification and
geography are separate states. Schema is `not_configured`, signature `not_checked`,
geography `not_evaluated`. Invalid XML has `invalid` well-formedness and cannot be
an Actual/Public CAP candidate. Unsupported roots remain `unknown`.

System/Link Test is a CMAC-specific classification, not a public warning. Other
CMAC fields retain their protocol-specific names and arrays. No guessed CMAC enum
mapping. CAP Actual/Public Alert/Update records are informational candidates only;
no operational actions exist. CAP identity is sender/identifier/sent, with exact
reference triples retained. Different bytes under an identical identity are
flagged as conflicts. Reference resolution happens at read time, including
out-of-order arrivals and ambiguous multiple matches; no overwrite occurs.

CAP presentation follows the retrieved OASIS CAP 1.2 standard (see sources.md).
Expiration is reported only when every info block supplies a parseable,
timezone-aware expiration and all are past. An in-effect label requires known
expiration/effective times; missing/invalid times remain unknown. Ack/Error are
not displayed as in-effect alerts. All lifecycle labels describe declared fields,
not authentication or successful schema validation.

At read time, Actual/Public Alert/Update content can be shown as superseded or
cancelled by a later Actual/Public Update/Cancel with an exact reference triple,
the same sender, and a later parseable sent time. Resolution is independent of
arrival order. Live sources form one source group; imports/replay cannot cancel
live data. Mixed-source, conflicting identities, simultaneous Update/Cancel times
and reference-query overflow require review. No evidence is overwritten, deleted
or operationally acted upon. Original references, unresolved targets, cancellations
without info blocks, and all message statuses remain inspectable.

Geography retains original CAP lat,lon strings, circle radius in km and geocodes
as strings (including leading zeros); areas and languages remain separate.
Derived GeoJSON explicitly converts coordinates to lon,lat. Valid closed polygons
and approximate 64-point spherical circle boundaries can be plotted offline.
Unclosed/nonfinite/out-of-range shapes are reported, not repaired. Application plot
bounds are 4–4096 vertices per polygon and 0 < circle radius <= 10,000 km; these are
not CAP schema limits. No geocode boundary, basemap, targeting or geographic
relevance is inferred. Schema/signature/geography validation states are unchanged.
CMAC gets a conservative original-leaf-field view, without assumed CAP mapping,
CMAC geography or lifecycle. A current CMAC schema and real alert sample are pending.

## Identity and clocks

Content ID is SHA-256 of exact XML parsing-view bytes (or exact non-XML body),
separate from protocol identity and transport ID. A terminal transport NUL is not
part of the XML view; every body variant remains in delivery evidence. The decoder
summary's duplicate_xml/unique_xml counters are bounded-window counts, not lifetime
archive counts; SQLite content IDs provide persistent exact-content deduplication.

Stored UTC times: import/processing time always; local reception UTC and monotonic
arrival time only for live input or retained original journal metadata; XML-declared
sent unchanged; inferred transport time explicitly labeled and suppressed for
heartbeat ID 411 or years outside 2000–2100. Replay source always stays `replay`,
even when original arrival metadata is retained. UI display uses America/Chicago.
